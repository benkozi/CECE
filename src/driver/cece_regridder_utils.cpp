// SPDX-License-Identifier: Apache-2.0
// CECE — Chemical Emissions Coupling Engine
// Copyright (c) HELM Project Contributors

#include "cece/cece_regridder_utils.hpp"

#include <cmath>
#include <iostream>

namespace cece::io {

axis::topology::UnstructuredMesh<Kokkos::HostSpace> build_axis_mesh(int ni, int nj, const std::vector<double>& lons,
                                                                    const std::vector<double>& lats) {
    size_t n_cells = static_cast<size_t>(ni) * nj;
    Kokkos::View<double*, Kokkos::HostSpace> center_lon("center_lon", n_cells);
    Kokkos::View<double*, Kokkos::HostSpace> center_lat("center_lat", n_cells);

    for (int j = 0; j < nj; ++j) {
        for (int i = 0; i < ni; ++i) {
            size_t idx = static_cast<size_t>(j) * ni + i;
            center_lon(idx) = lons[i];
            center_lat(idx) = lats[j];
        }
    }

    axis::topology::StructuredGrid<Kokkos::HostSpace> grid(ni, nj, center_lon, center_lat, axis::topology::CoordinateSystem::SphericalDeg);

    return grid.to_unstructured();
}

bool regrid_stream_field(amio_dataset_handle read_dataset, const std::string& input_var_name, int step_index, int file_nt, size_t time_offset,
                         bool is_float, const void* view_data, int file_nx, int file_ny, int nx, int ny, const std::vector<double>& target_lons,
                         const std::vector<double>& target_lats, const std::string& map_algo,
                         Kokkos::View<double***, Kokkos::LayoutLeft, Kokkos::DefaultExecutionSpace>& tide_view) {
    // 1. Read 'lon' coordinates dynamically from this file
    std::vector<double> src_lons;
    amio_view_handle lon_check_view = nullptr;
    if (amio_read(read_dataset, "lon", 0, nullptr, &lon_check_view) == AMIO_OK) {
        const void* lon_data = nullptr;
        size_t lon_size = 0;
        if (amio_view_data(lon_check_view, &lon_data, &lon_size) == AMIO_OK) {
            amio_shape_t lon_shape{};
            if (amio_view_shape(lon_check_view, &lon_shape) == AMIO_OK && lon_shape.rank > 0) {
                int lon_len = static_cast<int>(lon_shape.extents[0]);
                src_lons.resize(lon_len);
                bool is_lon_float = (lon_size == static_cast<size_t>(lon_len) * 4);
                for (int i = 0; i < lon_len; ++i) {
                    src_lons[i] = is_lon_float ? static_cast<const float*>(lon_data)[i] : static_cast<const double*>(lon_data)[i];
                }
            }
        }
        amio_release_view(lon_check_view);
    }

    // 2. Read 'lat' coordinates dynamically from this file (handles flips automatically!)
    std::vector<double> src_lats;
    bool is_lat_flipped = false;
    amio_view_handle lat_check_view = nullptr;
    if (amio_read(read_dataset, "lat", 0, nullptr, &lat_check_view) == AMIO_OK) {
        const void* lat_data = nullptr;
        size_t lat_size = 0;
        if (amio_view_data(lat_check_view, &lat_data, &lat_size) == AMIO_OK) {
            amio_shape_t lat_shape{};
            if (amio_view_shape(lat_check_view, &lat_shape) == AMIO_OK && lat_shape.rank > 0) {
                int lat_len = static_cast<int>(lat_shape.extents[0]);
                src_lats.resize(lat_len);
                bool is_lat_float = (lat_size == static_cast<size_t>(lat_len) * 4);
                for (int i = 0; i < lat_len; ++i) {
                    src_lats[i] = is_lat_float ? static_cast<const float*>(lat_data)[i] : static_cast<const double*>(lat_data)[i];
                }
                if (lat_len >= 2) {
                    if (src_lats[0] > src_lats[1]) {
                        is_lat_flipped = true;
                    }
                }
            }
        }
        amio_release_view(lat_check_view);
    }

    if (src_lons.empty() || src_lats.empty()) {
        return false;
    }

    // A. Build source and destination meshes
    auto src_mesh = build_axis_mesh(file_nx, file_ny, src_lons, src_lats);
    auto dst_mesh = build_axis_mesh(nx, ny, target_lons, target_lats);

    // B. Configure weight generation method
    axis::solver::RegridConfig regrid_cfg;
    regrid_cfg.method = axis::solver::InterpolationMethod::Conservative1stOrder;
    if (map_algo == "nearest" || map_algo == "near" || map_algo == "nn") {
        regrid_cfg.method = axis::solver::InterpolationMethod::NearestNeighbor;
    } else if (map_algo == "bilinear" || map_algo == "bilin" || map_algo == "bi") {
        regrid_cfg.method = axis::solver::InterpolationMethod::Bilinear;
    } else if (map_algo == "cubic" || map_algo == "bicubic" || map_algo == "cu") {
        regrid_cfg.method = axis::solver::InterpolationMethod::Bicubic;
    } else if (map_algo == "conss" || map_algo == "conservative2nd" || map_algo == "cons2nd") {
        regrid_cfg.method = axis::solver::InterpolationMethod::Conservative2ndOrder;
    } else if (map_algo == "consd" || map_algo == "conservative" || map_algo == "cons" || map_algo == "conservative1st") {
        regrid_cfg.method = axis::solver::InterpolationMethod::Conservative1stOrder;
    }
    regrid_cfg.norm_type = axis::solver::NormType::DstArea;
    regrid_cfg.unmapped = axis::solver::UnmappedAction::Ignore;

    // C. Generate sparse weight matrix and convert to CSR for performance
    auto matrix = axis::solver::WeightGenerator::generate<Kokkos::HostSpace>(src_mesh, dst_mesh, regrid_cfg);
    matrix.to_csr();

    // D. Prepare source field view [file_nx * file_ny]
    Kokkos::View<double*, Kokkos::HostSpace> src_field("src_field", file_nx * file_ny);
    const float* float_data = static_cast<const float*>(view_data);
    const double* double_data = static_cast<const double*>(view_data);
    for (int j = 0; j < file_ny; ++j) {
        for (int i = 0; i < file_nx; ++i) {
            size_t src_idx = time_offset + static_cast<size_t>(j) * file_nx + i;
            src_field(j * file_nx + i) = is_float ? static_cast<double>(float_data[src_idx]) : double_data[src_idx];
        }
    }

    // E. Apply weights to compute regridded destination field [nx * ny]
    Kokkos::View<double*, Kokkos::HostSpace> dst_field("dst_field", nx * ny);
    axis::field_view<const double, 1> src_view(src_field.data(), file_nx * file_ny);
    axis::field_view<double, 1> dst_view(dst_field.data(), nx * ny);
    axis::solver::apply(matrix, src_view, dst_view);

    // F. Populate results into TIDE's view
    auto h_view = Kokkos::create_mirror_view(tide_view);
    for (int j = 0; j < ny; ++j) {
        for (int i = 0; i < nx; ++i) {
            h_view(i, j, 0) = dst_field(j * nx + i);
        }
    }
    Kokkos::deep_copy(tide_view, h_view);
    return true;
}

}  // namespace cece::io
