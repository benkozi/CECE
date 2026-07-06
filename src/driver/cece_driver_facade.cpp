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

#include "cece/cece_fatal.hpp"
#include "cece/cece_helm_graph.hpp"
#include "cece/cece_internal.hpp"
#include "cece/cece_regridder_utils.hpp"
#include "cece/cece_standalone_writer.hpp"

namespace fs = std::filesystem;

extern "C" {
void cece_ingestor_set_field(void* data_ptr, const char* field_name, int name_len, const double* field_data, int n_lev, int n_elem, int* rc);
void amio_set_parent_communicator(MPI_Fint comm);
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
    // Cleanly drain any in-flight pipeline tasks and release hijacked ranks
    // before destroying the graph. Without this, tearing down the DAGR
    // GraphOrchestrator while a task is still in flight races with the
    // Event_Loop worker(s) and can segfault at teardown. shutdown() is
    // idempotent and safe to call here.
    if (dagr_) {
        dagr_->shutdown();
    }
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
        std::string mapalgo = "consd";                                   // default fallback
        std::string stream_data_model = "enhanced";                      // default AMIO data model
        bool stream_data_model_explicit = false;
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
                        if (stream["mapalgo"]) {
                            mapalgo = stream["mapalgo"].as<std::string>();
                        }
                        if (stream["data_model"]) {
                            std::string requested_model = stream["data_model"].as<std::string>();
                            std::transform(requested_model.begin(), requested_model.end(), requested_model.begin(),
                                           [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
                            if (requested_model == "classic" || requested_model == "enhanced") {
                                stream_data_model = requested_model;
                                stream_data_model_explicit = true;
                            } else if (requested_model == "auto") {
                                stream_data_model = "enhanced";
                                stream_data_model_explicit = false;
                            } else {
                                std::cout << "[DRIVER WARNING] Invalid stream data_model='" << requested_model
                                          << "' for stream variable '" << var_name
                                          << "'; using default auto behavior (enhanced then classic fallback)." << std::endl;
                            }
                        }
                        found_var = true;
                        break;
                    }
                }
                if (found_var) break;
            }
        }

        // Verify if the input file path exists and is accessible from this compute/login node
        std::error_code fs_ec;
        if (!fs::exists(input_file_path, fs_ec)) {
            LogFatal("[DRIVER FATAL] File '" + input_file_path +
                     "' does not exist or is unreadable on this node! (System error: " + fs_ec.message() + ")");
        } else {
            std::cout << "[DRIVER DEBUG] Input file '" << input_file_path << "' successfully verified on local filesystem." << std::endl;
        }

        bool read_success = false;
        // Human-readable reason for the most recent read failure, propagated to
        // the fatal error message so the underlying AMIO status reaches CECE.
        std::string failure_detail;

        // Dynamically open and read using AMIO API
        std::string read_manifest_path = "amio_read_manifest_facade_" + var_name + ".yaml";

        int rank = 0;
        int mpi_initialized = 0;
        MPI_Initialized(&mpi_initialized);
        if (mpi_initialized && comm_c_ != MPI_COMM_NULL) {
            MPI_Comm_rank(comm_c_, &rank);
        }

        amio_core_handle read_core = nullptr;
        amio_dataset_handle read_dataset = nullptr;
        amio_view_handle read_view = nullptr;

        std::vector<std::string> data_models_to_try;
        if (stream_data_model_explicit) {
            data_models_to_try.push_back(stream_data_model);
        } else {
            data_models_to_try.push_back("enhanced");
            data_models_to_try.push_back("classic");
        }

        amio_status_t amio_rc = AMIO_ERR_BACKEND_FAILURE;
        std::string active_data_model = data_models_to_try.front();

        for (const auto& candidate_model : data_models_to_try) {
            active_data_model = candidate_model;

            if (rank == 0) {
                // Write input manifest YAML (Rank 0 only to prevent parallel write conflicts)
                std::ofstream m_file(read_manifest_path);
                m_file << "backend: netcdf4\n"
                       << "path: " << input_file_path << "\n"
                       << "data_model: " << candidate_model << "\n"
                       << "staging_pool:\n"
                       << "  buffer_count: 8\n"
                       << "  buffer_capacity_bytes: 268435456\n"
                       << "worker_pool:\n"
                       << "  threads: 1\n"
                       << "prefetch:\n"
                       << "  depth: 2\n"
                       << "  read_timeout_s: 120\n"
                       << "staging_timeout_ms: 30000\n";
                m_file.close();
            }

            // Wait for Rank 0 to finish writing the manifest before other ranks load it.
            if (mpi_initialized && comm_c_ != MPI_COMM_NULL) {
                MPI_Barrier(comm_c_);
            }

            // Temporarily force serial nc_open read fallback to improve portability.
            if (mpi_initialized) {
                amio_set_parent_communicator(MPI_Comm_c2f(MPI_COMM_SELF));
            }

            amio_rc = amio_init(read_manifest_path.c_str(), &read_core);
            if (amio_rc == AMIO_OK) {
                amio_rc = amio_open_dataset(read_core, read_manifest_path.c_str(), AMIO_MODE_READ, &read_dataset);
            }

            // Restore parent communicator for downstream operations.
            if (mpi_initialized && comm_c_ != MPI_COMM_NULL) {
                amio_set_parent_communicator(MPI_Comm_c2f(comm_c_));
            }

            if (amio_rc == AMIO_OK) {
                break;
            }

            std::cout << "[DRIVER DEBUG] AMIO open attempt failed (data_model='" << candidate_model << "') with rc = " << amio_rc << " ("
                      << amio_strerror(amio_rc) << ")" << std::endl;

            if (read_dataset) {
                amio_close(read_dataset);
                read_dataset = nullptr;
            }
            if (read_core) {
                amio_finalize(read_core);
                read_core = nullptr;
            }
        }

        if (amio_rc != AMIO_OK) {
            std::cout << "[DRIVER DEBUG] amio_open_dataset failed for " << input_file_path << " with rc = " << amio_rc << " ("
                      << amio_strerror(amio_rc) << ") after trying data_model='" << active_data_model << "'" << std::endl;
        } else {
            if (!stream_data_model_explicit && active_data_model != "enhanced") {
                std::cout << "[DRIVER INFO] AMIO read manifest auto-fell back to data_model='" << active_data_model << "' for " << input_file_path
                          << std::endl;
            }

            // Determine this rank's contiguous destination latitude band [j0, j1)
            // via a simple block decomposition of the ny_ destination rows.
            int mpi_size = 1;
            int mpi_rank = 0;
            if (mpi_initialized && comm_c_ != MPI_COMM_NULL) {
                MPI_Comm_size(comm_c_, &mpi_size);
                MPI_Comm_rank(comm_c_, &mpi_rank);
            }
            const int band_base = ny_ / mpi_size;
            const int band_rem = ny_ % mpi_size;
            auto band_start = [&](int r) { return r * band_base + std::min(r, band_rem); };
            const int j0 = band_start(mpi_rank);
            const int j1 = band_start(mpi_rank + 1);

            // 1. Determine total timesteps from the coordinate variable (time or date).
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

            // 2. Build (or reuse cached) interpolation weights for this rank's band.
            //    Weights depend only on the grids, so they are generated once and
            //    reused for every timestep.
            auto plan_it = regrid_plans_.find(var_name);
            if (plan_it == regrid_plans_.end() || !plan_it->second.built) {
                cece::io::RegridPlan plan;
                if (!cece::io::build_regrid_plan(read_dataset, nx_, ny_, target_lons_, target_lats_, mapalgo, j0, j1, plan)) {
                    std::cout << "[DRIVER DEBUG] build_regrid_plan failed for '" << var_name << "'" << std::endl;
                    failure_detail = "regrid plan construction failed (could not read source grid coordinates)";
                } else {
                    plan_it = regrid_plans_.emplace(var_name, std::move(plan)).first;
                }
            }

            // 3. Read the main variable for this timestep and apply the cached weights.
            if (plan_it != regrid_plans_.end() && plan_it->second.built) {
                const cece::io::RegridPlan& plan = plan_it->second;
                const int t_idx = (file_nt > 0) ? (step_index_ % file_nt) : 0;

                // Read only the requested timestep. The AMIO netCDF backend detects
                // the CF time dimension and reads a single [lat, lon] slab (count[0]=1),
                // so we never stage the whole (time, lat, lon) variable. This keeps each
                // read to ny*nx elements even for long, high-resolution sub-daily
                // datasets (e.g. CAMS-TEMPO hourly), avoiding staging-pool exhaustion.
                amio_rc = amio_read(read_dataset, input_var_name.c_str(), t_idx, nullptr, &read_view);
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

                            // Determine the offset of the requested timestep within the
                            // returned view. amio_read() is asked for a single timestep, so
                            // the view normally contains just one 2D slice (offset 0). We
                            // stay robust to a backend that returns the whole variable by
                            // checking how many spatial slices the view actually holds.
                            const size_t spatial = static_cast<size_t>(file_ny) * file_nx;
                            const size_t slices_in_view = (spatial > 0) ? (total_elements / spatial) : 1;
                            size_t time_offset = 0;
                            if (slices_in_view > 1) {
                                const int t_idx = step_index_ % file_nt;
                                time_offset = static_cast<size_t>(t_idx) * spatial;
                            }

                            std::vector<double> local_dst;
                            if (cece::io::apply_regrid_plan(plan, time_offset, is_float, view_data, file_nx, file_ny, nx_, local_dst)) {
                                // Gather each rank's destination band into the full [nx_*ny_] field.
                                std::vector<double> full_dst(static_cast<size_t>(nx_) * ny_, 0.0);
                                if (mpi_initialized && mpi_size > 1 && comm_c_ != MPI_COMM_NULL) {
                                    std::vector<int> counts(mpi_size), displs(mpi_size);
                                    for (int r = 0; r < mpi_size; ++r) {
                                        counts[r] = (band_start(r + 1) - band_start(r)) * nx_;
                                        displs[r] = band_start(r) * nx_;
                                    }
                                    MPI_Allgatherv(local_dst.data(), counts[mpi_rank], MPI_DOUBLE, full_dst.data(), counts.data(), displs.data(),
                                                   MPI_DOUBLE, comm_c_);
                                } else {
                                    std::copy(local_dst.begin(), local_dst.end(), full_dst.begin() + static_cast<size_t>(j0) * nx_);
                                }

                                // Populate the CECE field view (i, j, 0) from the full field.
                                auto h_view = Kokkos::create_mirror_view(tide_view);
                                for (int j = 0; j < ny_; ++j) {
                                    for (int i = 0; i < nx_; ++i) {
                                        h_view(i, j, 0) = full_dst[static_cast<size_t>(j) * nx_ + i];
                                    }
                                }
                                Kokkos::deep_copy(tide_view, h_view);
                                read_success = true;
                            } else {
                                std::cout << "[DRIVER DEBUG] apply_regrid_plan returned false!" << std::endl;
                                failure_detail = "regrid weight application failed";
                            }
                        } else {
                            std::cout << "[DRIVER DEBUG] amio_view_shape failed!" << std::endl;
                            failure_detail = "amio_view_shape failed";
                        }
                    } else {
                        std::cout << "[DRIVER DEBUG] amio_view_data failed with rc = " << amio_rc << std::endl;
                        failure_detail = std::string("amio_view_data failed: rc=") + std::to_string(amio_rc) + " (" + amio_strerror(amio_rc) + ")";
                    }
                    amio_release_view(read_view);
                } else {
                    std::cout << "[DRIVER DEBUG] amio_read('" << input_var_name << "') failed with rc = " << amio_rc << std::endl;
                    failure_detail = std::string("amio_read('") + input_var_name + "') failed: rc=" + std::to_string(amio_rc) + " (" +
                                     amio_strerror(amio_rc) + ")";
                }
            }
            amio_close(read_dataset);
        }
        amio_finalize(read_core);

        // Wait for all ranks to finalize their AMIO sessions before deleting the manifest file
        if (mpi_initialized && comm_c_ != MPI_COMM_NULL) {
            MPI_Barrier(comm_c_);
        }
        if (rank == 0) {
            std::remove(read_manifest_path.c_str());
        }

        // Throw a fatal error on AMIO read failures
        if (!read_success) {
            std::string detail = failure_detail.empty() ? ("open/init failed: rc=" + std::to_string(amio_rc) + " (" + amio_strerror(amio_rc) + ")")
                                                        : failure_detail;
            LogFatal("[FATAL ERROR] AMIO read failed for field '" + var_name + "' in file '" + input_file_path + "'. Reason: " + detail +
                     ". Idealized fallback is disabled!");
            return false;
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
