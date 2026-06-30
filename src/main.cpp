#include <amio/amio.h>
#include <mpi.h>
#include <yaml-cpp/yaml.h>

#include <Kokkos_Core.hpp>
#include <axis/topology/named_grid_registry.hpp>
#include <cmath>
#include <fstream>
#include <halo/communicator.hpp>
#include <halo/environment.hpp>
#include <iostream>
#include <memory>
#include <string>
#include <tick/tick.hpp>
#include <vector>

#include "cece/cece_driver_facade.hpp"

// CECE Core C-Linkage Lifecycle functions
extern "C" {
void cece_set_config_file_path(const char* config_path, int path_len);
void cece_core_initialize_p1(void** data_ptr_ptr, int* rc);
void cece_core_realize(void* data_ptr, int* rc);
void cece_core_initialize_p2(void* data_ptr, int* nx, int* ny, int* nz, int* rc);
void cece_core_run(void* data_ptr, int hour, int day_of_week, int* rc);
void cece_core_finalize(void* data_ptr, int* rc);
void cece_core_writer_initialize(void* data_ptr, int nx, int ny, int nz, const char* start_time_iso8601, int start_time_len, int* rc);
void cece_core_writer_initialize_with_coords(void* data_ptr, int nx, int ny, int nz, const double* lon_coords, const double* lat_coords,
                                             const char* start_time_iso8601, int start_time_len, int* rc);
void cece_core_write_step(void* data_ptr, double time_seconds, int step_index, int* rc);
void cece_core_set_export_field(void* data_ptr, const char* name, int name_len, const double* field_data, int nx, int ny, int nz, int* rc);
}

extern "C" {
void cece_driver_create(const char* yaml_path, int path_len, int nx, int ny, int nz, const double* lon_coords, const double* lat_coords,
                        int mpi_comm_f, void** driver_ptr_out, int* rc);
}

int main(int argc, char* argv[]) {
    // 1. Initialize MPI with thread support
    int provided = 0;
    MPI_Init_thread(&argc, &argv, MPI_THREAD_MULTIPLE, &provided);

    // 2. Initialize Kokkos (allocates execution resources on GPU or CPU)
    Kokkos::initialize(argc, argv);
    {
        // Initialize the HALO Environment & Communicator
        halo::Environment::initialize();
        halo::Communicator world(MPI_COMM_WORLD);
        const int my_rank = world.rank();

        std::string config_file = "cece_control_mock.yaml";
        if (argc > 1) {
            config_file = argv[1];
        }

        if (my_rank == 0) {
            std::cout << "[DRIVER] Starting CECE-HELM standalone C++ driver with config: " << config_file << std::endl;
        }

        // Set config file path dynamically
        cece_set_config_file_path(config_file.c_str(), static_cast<int>(config_file.length()));

        // --- Dynamic Config Parsing via yaml-cpp ---
        YAML::Node config = YAML::LoadFile(config_file);

        // A. Grid Dimensions
        int nx = 4;
        int ny = 4;
        int nz = 1;
        std::string grid_name = "";
        if (config["driver"] && config["driver"]["grid"]) {
            auto grid_node = config["driver"]["grid"];
            if (grid_node["nz"]) {
                nz = grid_node["nz"].as<int>(1);
            }
            if (grid_node["grid_name"]) {
                grid_name = grid_node["grid_name"].as<std::string>();
            }
            if (grid_name.empty()) {
                nx = grid_node["nx"].as<int>(4);
                ny = grid_node["ny"].as<int>(4);
            } else {
                try {
                    auto parsed = axis::topology::NamedGridRegistry::parse(grid_name);
                    if (parsed.family == 'F') {
                        int expected_nx = 4 * parsed.number;
                        int expected_ny = 2 * parsed.number;

                        int declared_nx = grid_node["nx"].as<int>(0);
                        int declared_ny = grid_node["ny"].as<int>(0);
                        if (declared_nx != 0 && declared_ny != 0) {
                            if (declared_nx != expected_nx || declared_ny != expected_ny) {
                                std::cerr << "ERROR: Grid dimensions nx=" << declared_nx << ", ny=" << declared_ny
                                          << " do not match the expected dimensions for Named Grid " << grid_name << " (" << expected_nx << "x"
                                          << expected_ny << ")!" << std::endl;
                                return -1;
                            }
                        }
                        nx = expected_nx;
                        ny = expected_ny;
                    } else {
                        std::cerr
                            << "ERROR: Only regular Gaussian grids (family 'F', e.g. 'F360') are currently supported as structured CECE target grids."
                            << std::endl;
                        return -1;
                    }
                } catch (const std::exception& e) {
                    std::cerr << "ERROR: Failed to parse named grid '" << grid_name << "': " << e.what() << std::endl;
                    return -1;
                }
            }
        }

        // B. Simulation Clock Timing
        std::string start_time_str = config["driver"]["start_time"].as<std::string>();
        std::string end_time_str = config["driver"]["end_time"].as<std::string>();
        int timestep_seconds = config["driver"]["timestep_seconds"].as<int>();

        // 3. Initialize TICK Clock
        tick::Gregorian_Calendar cal;
        tick::Time_Point sim_time = cal.to_time_point(tick::parse_iso8601(start_time_str));
        tick::Time_Point end_time = cal.to_time_point(tick::parse_iso8601(end_time_str));
        tick::Duration dt = tick::seconds(timestep_seconds);

        // 4. Initialize the CECE Compute Engine via C-linkage
        void* cece_data_ptr = nullptr;
        int rc = 0;

        // Phase 1: Allocate internal structures (StackingEngine, DiagnosticManager)
        cece_core_initialize_p1(&cece_data_ptr, &rc);

        // Realize: Validate and lock configuration
        cece_core_realize(cece_data_ptr, &rc);

        // Phase 2: Complete grid-binding (dynamically sized)
        cece_core_initialize_p2(cece_data_ptr, &nx, &ny, &nz, &rc);

        // Register the export fields configured for output
        if (config["output"] && config["output"]["fields"]) {
            for (const auto& field_node : config["output"]["fields"]) {
                std::string field_name = field_node.as<std::string>();
                std::vector<double> field_mem(static_cast<std::size_t>(nx) * ny * nz, 0.0);
                cece_core_set_export_field(cece_data_ptr, field_name.c_str(), static_cast<int>(field_name.length()), field_mem.data(), nx, ny, nz,
                                           &rc);
            }
        }

        // Setup CECE grid coordinate arrays (either generated dynamically from NamedGridRegistry, or calculated uniformly)
        std::vector<double> file_lons(nx, 0.0);
        std::vector<double> file_lats(ny, 0.0);
        bool has_file_coords = false;

        if (!grid_name.empty()) {
            try {
                auto mesh = axis::topology::NamedGridRegistry::generate<Kokkos::HostSpace>(grid_name);
                auto coords = mesh.node_coords();
                for (int i = 0; i < nx; ++i) {
                    double lon = coords(i, 0);
                    if (lon >= 180.0) {
                        lon -= 360.0;
                    }
                    file_lons[i] = lon;
                }
                for (int j = 0; j < ny; ++j) {
                    file_lats[j] = coords(j * nx, 1);
                }
                std::sort(file_lons.begin(), file_lons.end());
                std::sort(file_lats.begin(), file_lats.end());
                has_file_coords = true;
            } catch (const std::exception& e) {
                std::cerr << "ERROR: Failed to retrieve coordinates from named grid '" << grid_name << "': " << e.what() << std::endl;
                return -1;
            }
        } else {
            double lon_min = -180.0;
            double lon_max = 180.0;
            double lat_min = -90.0;
            double lat_max = 90.0;

            if (config["driver"] && config["driver"]["grid"]) {
                auto grid_node = config["driver"]["grid"];
                lon_min = grid_node["lon_min"].as<double>(-180.0);
                lon_max = grid_node["lon_max"].as<double>(180.0);
                lat_min = grid_node["lat_min"].as<double>(-90.0);
                lat_max = grid_node["lat_max"].as<double>(90.0);
            }

            double dlon = (lon_max - lon_min) / nx;
            double dlat = (lat_max - lat_min) / ny;

            for (int i = 0; i < nx; ++i) {
                file_lons[i] = lon_min + dlon * (i + 0.5);
            }
            for (int j = 0; j < ny; ++j) {
                file_lats[j] = lat_min + dlat * (j + 0.5);
            }
            has_file_coords = true;
        }

        // 5. Initialize the cece_driver orchestrator facade
        void* cece_driver_data = nullptr;
        int mpi_comm_f = MPI_Comm_c2f(MPI_COMM_WORLD);
        cece_driver_create(config_file.c_str(), static_cast<int>(config_file.length()), nx, ny, nz, file_lons.data(), file_lats.data(), mpi_comm_f,
                           &cece_driver_data, &rc);

        // Standalone Writer: Initialize output writing if configured
        if (has_file_coords) {
            cece_core_writer_initialize_with_coords(cece_data_ptr, nx, ny, nz, file_lons.data(), file_lats.data(), start_time_str.c_str(),
                                                    start_time_str.length(), &rc);
        } else {
            cece_core_writer_initialize(cece_data_ptr, nx, ny, nz, start_time_str.c_str(), start_time_str.length(), &rc);
        }

        if (my_rank == 0) {
            std::cout << "[DRIVER] Initialization completed on " << nx << "x" << ny << "x" << nz << " grid. Entering run loop..." << std::endl;
        }

        // 6. Event-driven simulation run loop
        tick::Time_Point start_time = sim_time;
        int step_index = 0;
        while (sim_time < end_time) {
            tick::Date_Time current_dt = cal.to_date_time(sim_time);

            if (my_rank == 0) {
                std::cout << "[DRIVER] Advancing simulation to: " << tick::format_iso8601(current_dt) << std::endl;
            }

            std::string time_str = tick::format_iso8601(current_dt);

            // A. Let cece_driver handle all offline AMIO reading and AXIS regridding:
            cece_driver_advance_time(cece_driver_data, time_str.c_str(), static_cast<int>(time_str.length()), cece_data_ptr, &rc);

            // B. Execute the CECE Compute Engine
            int hour = current_dt.hour;
            int day_of_week = 1;  // Default Monday/Tuesday
            cece_core_run(cece_data_ptr, hour, day_of_week, &rc);

            double elapsed_seconds = static_cast<double>((sim_time - start_time).nanos()) / 1e9;

            // C. Write output timestep via standalone writer
            cece_core_write_step(cece_data_ptr, elapsed_seconds, step_index, &rc);

            // D. Advance simulation clock by one timestep
            sim_time += dt;
            step_index++;
        }

        // 7. Cleanup and release resources
        if (my_rank == 0) {
            std::cout << "[DRIVER] Standalone execution completed. Cleaning up..." << std::endl;
        }

        cece_driver_destroy(cece_driver_data);
        cece_core_finalize(cece_data_ptr, &rc);
    }
    Kokkos::finalize();
    MPI_Finalize();
    return 0;
}
