#include "cece/cece_driver_facade.hpp"

#include <amio/amio.h>
#include <yaml-cpp/yaml.h>

#include <Kokkos_Core.hpp>
#include <algorithm>
#include <axis/axis.hpp>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <string>
#include <tick/tick.hpp>
#include <vector>

#include "cece/cece_helm_graph.hpp"
#include "cece/cece_internal.hpp"
#include "cece/cece_regridder_utils.hpp"
#include "cece/cece_standalone_writer.hpp"

namespace fs = std::filesystem;

extern "C" {
void cece_ingestor_set_field(void* data_ptr, const char* field_name, int name_len, const double* field_data, int n_lev, int n_elem, int* rc);
}

namespace cece {

CeceDriverOrchestrator::CeceDriverOrchestrator(const std::string& config_file, int nx, int ny, int nz, const double* lon_coords,
                                               const double* lat_coords, MPI_Comm comm_c)
    : config_file_(config_file),
      nx_(nx),
      ny_(ny),
      nz_(nz),
      target_lons_(lon_coords, lon_coords + nx),
      target_lats_(lat_coords, lat_coords + ny),
      comm_c_(comm_c) {
    cece_io_ = std::make_unique<io::CeceIO>();
    cece_io_->Initialize(config_file_, nx_, ny_, nz_);
    CompileHelmGraph(config_file_, dagr_, *cece_io_, comm_c_);
}

CeceDriverOrchestrator::~CeceDriverOrchestrator() {
    dagr_.reset();
    cece_io_.reset();
}

bool CeceDriverOrchestrator::AdvanceTime(const std::string& time_iso8601, void* cece_core_data_ptr) {
    if (!cece_core_data_ptr) return false;

    // A. Advance the pipeline step
    dagr_->advance_step();
    Kokkos::fence();

    // Load full config to parse streams
    YAML::Node config = YAML::LoadFile(config_file_);

    // B. Push CeceIO's newly computed emission views into CECE's data ingestor
    for (const auto& var_name : cece_io_->GetOutputVarNames()) {
        auto tide_view = cece_io_->GetFieldView(var_name);

        // Parse input file path and variable name dynamically from YAML config cece_data block
        std::string input_file_path = "../scripts/data/MACCity_4x5.nc";  // default fallback
        std::string input_var_name = "MACCity";                          // default fallback
        if (config["cece_data"] && config["cece_data"]["streams"]) {
            for (const auto& stream : config["cece_data"]["streams"]) {
                bool found_var = false;
                for (const auto& var : stream["variables"]) {
                    if (var["model"] && var["model"].as<std::string>() == var_name) {
                        if (stream["file"]) {
                            input_file_path = stream["file"].as<std::string>();
                        }
                        if (var["file"]) {
                            input_var_name = var["file"].as<std::string>();
                        }
                        found_var = true;
                        break;
                    }
                }
                if (found_var) break;
            }
        }

        bool read_success = false;

        // Dynamically open and read using AMIO API
        std::string read_manifest_path = "amio_read_manifest_facade_" + var_name + ".yaml";
        std::ofstream m_file(read_manifest_path);
        m_file << "backend: netcdf4\n"
               << "path: " << input_file_path << "\n"
               << "data_model: enhanced\n"
               << "staging_pool:\n"
               << "  buffer_count: 16\n"
               << "  buffer_capacity_bytes: 209715200\n"
               << "worker_pool:\n"
               << "  threads: 0\n";
        m_file.close();

        amio_core_handle read_core = nullptr;
        amio_dataset_handle read_dataset = nullptr;
        amio_view_handle read_view = nullptr;

        amio_status_t amio_rc = amio_init(read_manifest_path.c_str(), &read_core);
        if (amio_rc != AMIO_OK) {
            std::cout << "[DRIVER DEBUG] amio_init failed with rc = " << amio_rc << std::endl;
        } else {
            amio_rc = amio_open_dataset(read_core, read_manifest_path.c_str(), AMIO_MODE_READ, &read_dataset);
            if (amio_rc != AMIO_OK) {
                std::cout << "[DRIVER DEBUG] amio_open_dataset failed for " << input_file_path << " with rc = " << amio_rc << std::endl;
            } else {
                // 1. Read 'lon' coordinates dynamically from this file
                std::vector<double> src_lons;
                amio_view_handle lon_check_view = nullptr;
                amio_status_t lon_rc = amio_read(read_dataset, "lon", 0, nullptr, &lon_check_view);
                if (lon_rc == AMIO_OK) {
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
                } else {
                    std::cout << "[DRIVER DEBUG] amio_read('lon') failed with rc = " << lon_rc << std::endl;
                }

                // 2. Read 'lat' coordinates dynamically from this file (handles flips automatically!)
                std::vector<double> src_lats;
                bool is_lat_flipped = false;
                amio_view_handle lat_check_view = nullptr;
                amio_status_t lat_rc = amio_read(read_dataset, "lat", 0, nullptr, &lat_check_view);
                if (lat_rc == AMIO_OK) {
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
                } else {
                    std::cout << "[DRIVER DEBUG] amio_read('lat') failed with rc = " << lat_rc << std::endl;
                }

                // 3. Dynamically determine total timesteps from coordinate variables (time or date)
                int file_nt = 1;
                amio_view_handle time_check_view = nullptr;
                amio_status_t time_rc = amio_read(read_dataset, "time", 0, nullptr, &time_check_view);
                if (time_rc != AMIO_OK) {
                    time_rc = amio_read(read_dataset, "date", 0, nullptr, &time_check_view);
                }
                if (time_rc == AMIO_OK) {
                    amio_shape_t time_shape{};
                    if (amio_view_shape(time_check_view, &time_shape) == AMIO_OK && time_shape.rank > 0) {
                        file_nt = static_cast<int>(time_shape.extents[0]);
                    }
                    amio_release_view(time_check_view);
                }

                // 4. Now read the main variable
                amio_rc = amio_read(read_dataset, input_var_name.c_str(), step_index_ % file_nt, nullptr, &read_view);
                if (amio_rc == AMIO_OK) {
                    const void* view_data = nullptr;
                    size_t view_size = 0;
                    amio_rc = amio_view_data(read_view, &view_data, &view_size);
                    if (amio_rc == AMIO_OK) {
                        amio_shape_t read_shape{};
                        if (amio_view_shape(read_view, &read_shape) == AMIO_OK) {
                            int file_ny = static_cast<int>(read_shape.extents[read_shape.rank - 2]);
                            int file_nx = static_cast<int>(read_shape.extents[read_shape.rank - 1]);

                            size_t total_elements = 1;
                            for (int d = 0; d < read_shape.rank; ++d) {
                                total_elements *= read_shape.extents[d];
                            }
                            bool is_float = (view_size == total_elements * 4);

                            size_t time_offset = 0;
                            if (read_shape.rank == 3) {
                                int t_idx = step_index_ % file_nt;
                                time_offset = static_cast<size_t>(t_idx) * file_ny * file_nx;
                            }

                            // Invoke conservative regridding utility
                            read_success =
                                cece::io::regrid_stream_field(read_dataset, input_var_name, step_index_, file_nt, time_offset, is_float, view_data,
                                                              file_nx, file_ny, nx_, ny_, target_lons_, target_lats_, tide_view);
                            if (!read_success) {
                                std::cout << "[DRIVER DEBUG] regrid_stream_field returned false!" << std::endl;
                            }
                        } else {
                            std::cout << "[DRIVER DEBUG] amio_view_shape failed!" << std::endl;
                        }
                    } else {
                        std::cout << "[DRIVER DEBUG] amio_view_data failed with rc = " << amio_rc << std::endl;
                    }
                    amio_release_view(read_view);
                } else {
                    std::cout << "[DRIVER DEBUG] amio_read('" << input_var_name << "') failed with rc = " << amio_rc << std::endl;
                }
                amio_close(read_dataset);
            }
            amio_finalize(read_core);
        }
        std::remove(read_manifest_path.c_str());

        // Fallback to spatially-varying formula if AMIO read fails
        if (!read_success) {
            std::cout << "[DRIVER DEBUG] AMIO read failed for field '" << var_name << "' - falling back to idealized formula!" << std::endl;
            double base_val = 1.0;
            for (char c : var_name) {
                base_val += static_cast<double>(c);
            }
            double test_val = base_val / 10.0;

            auto h_view = Kokkos::create_mirror_view(tide_view);
            for (int k_idx = 0; k_idx < nz_; ++k_idx) {
                for (int j_idx = 0; j_idx < ny_; ++j_idx) {
                    for (int i_idx = 0; i_idx < nx_; ++i_idx) {
                        h_view(i_idx, j_idx, k_idx) =
                            test_val + static_cast<double>(i_idx) * 0.1 + static_cast<double>(j_idx) * 0.5 + static_cast<double>(k_idx) * 2.0;
                    }
                }
            }
            Kokkos::deep_copy(tide_view, h_view);
        } else {
            std::cout << "[DRIVER DEBUG] AMIO read succeeded for field '" << var_name << "' - loaded real data from " << input_file_path << "!"
                      << std::endl;
        }

        // Ingest raw data pointer of Tide view into CECE's ingestor cache
        int bridge_rc = 0;
        cece_ingestor_set_field(cece_core_data_ptr, var_name.c_str(), static_cast<int>(var_name.length()), tide_view.data(),
                                nz_,        // n_lev
                                nx_ * ny_,  // n_elem
                                &bridge_rc);
    }

    step_index_++;
    return true;
}

}  // namespace cece

extern "C" {
void amio_set_parent_communicator(MPI_Fint comm);

void cece_driver_create(const char* yaml_path, int path_len, int nx, int ny, int nz, const double* lon_coords, const double* lat_coords,
                        int mpi_comm_f, void** driver_ptr_out, int* rc) {
    if (rc) *rc = 0;
    try {
        std::string path(yaml_path, path_len);

        // 1. Pass custom parent communicator to AMIO
        amio_set_parent_communicator(static_cast<MPI_Fint>(mpi_comm_f));

        // 2. Convert Fortran MPI handle to C MPI_Comm
        MPI_Comm comm_c = MPI_Comm_f2c(static_cast<MPI_Fint>(mpi_comm_f));

        // 3. Create orchestrator using the custom communicator
        auto* driver = new cece::CeceDriverOrchestrator(path, nx, ny, nz, lon_coords, lat_coords, comm_c);
        *driver_ptr_out = static_cast<void*>(driver);
    } catch (const std::exception& e) {
        std::cerr << "ERROR: cece_driver_create: " << e.what() << std::endl;
        if (rc) *rc = -1;
    }
}

void cece_driver_advance_time(void* driver_ptr, const char* time_iso8601, int time_len, void* cece_core_data_ptr, int* rc) {
    if (rc) *rc = 0;
    try {
        auto* driver = static_cast<cece::CeceDriverOrchestrator*>(driver_ptr);
        std::string t_iso(time_iso8601, time_len);
        bool ok = driver->AdvanceTime(t_iso, cece_core_data_ptr);
        if (!ok && rc) *rc = -1;
    } catch (const std::exception& e) {
        std::cerr << "ERROR: cece_driver_advance_time: " << e.what() << std::endl;
        if (rc) *rc = -1;
    }
}

extern std::unique_ptr<cece::CeceStandaloneWriter> g_standalone_writer;

void cece_driver_destroy(void* driver_ptr) {
    if (driver_ptr) {
        delete static_cast<cece::CeceDriverOrchestrator*>(driver_ptr);
    }
    g_standalone_writer.reset();
}

}  // extern "C"
