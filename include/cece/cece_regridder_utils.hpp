// SPDX-License-Identifier: Apache-2.0
// CECE — Chemical Emissions Coupling Engine
// Copyright (c) HELM Project Contributors

#ifndef CECE_REGRIDDER_UTILS_HPP
#define CECE_REGRIDDER_UTILS_HPP

#include <amio/amio.h>

#include <Kokkos_Core.hpp>
#include <axis/axis.hpp>
#include <string>
#include <vector>

namespace cece::io {

/// Build an AXIS UnstructuredMesh from rectilinear coordinate arrays.
axis::topology::UnstructuredMesh<Kokkos::HostSpace> build_axis_mesh(int ni, int nj, const std::vector<double>& lons, const std::vector<double>& lats);

/// Dynamically regrids a source field from an open AMIO dataset to a target Kokkos view conservatively using AXIS.
bool regrid_stream_field(amio_dataset_handle read_dataset, const std::string& input_var_name, int step_index, int file_nt, size_t time_offset,
                         bool is_float, const void* view_data, int file_nx, int file_ny, int nx, int ny, const std::vector<double>& target_lons,
                         const std::vector<double>& target_lats, const std::string& map_algo,
                         Kokkos::View<double***, Kokkos::LayoutLeft, Kokkos::DefaultExecutionSpace>& tide_view);

}  // namespace cece::io

#endif  // CECE_REGRIDDER_UTILS_HPP
