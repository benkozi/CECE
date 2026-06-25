#include <gtest/gtest.h>
#include <yaml-cpp/yaml.h>
#include <Kokkos_Core.hpp>
#include <vector>
#include <string>
#include <memory>
#include <stdexcept>
#include <fstream>
#include <filesystem>
#include <iostream>

#include "cece/cece_internal.hpp"
#include "cece/cece_config_path.hpp"

extern "C" {
void cece_core_initialize_p1(void** data_ptr_ptr, int* rc);
void cece_core_initialize_p2(void* data_ptr, int* nx, int* ny, int* nz, int* rc);
void cece_core_run(void* data_ptr, int hour, int day_of_week, int* rc);
void cece_core_finalize(void* data_ptr, int* rc);
void cece_set_config_file_path(const char* config_path, int path_len);
void cece_ingestor_set_field(void* data_ptr, const char* field_name, int name_len, const double* field_data, int n_lev, int n_elem, int* rc);
void cece_core_set_export_field(void* data_ptr, const char* name, int name_len, double* field_data, int nx, int ny, int nz, int* rc);
void cece_core_write_step(void* data_ptr, double time_seconds, int step_index, int* rc);
void cece_core_writer_initialize(void* data_ptr, int nx, int ny, int nz, const char* start_time, int start_time_len, int* rc);
}

namespace cece::test {

class DataRetriever {
public:
    virtual ~DataRetriever() = default;
    virtual std::vector<double> RetrieveField(
        const std::string& name,
        int step,
        int nx, int ny, int nz,
        const std::vector<double>& lons,
        const std::vector<double>& lats
    ) = 0;
};

class MockDataRetriever : public DataRetriever {
public:
    std::vector<double> RetrieveField(
        const std::string& name,
        int step,
        int nx, int ny, int nz,
        const std::vector<double>& lons,
        const std::vector<double>& lats
    ) override {
        std::vector<double> data(nx * ny * nz, 0.0);
        for (int k = 0; k < nz; ++k) {
            for (int j = 0; j < ny; ++j) {
                for (int i = 0; i < nx; ++i) {
                    double lon = lons[i];
                    double lat = lats[j];
                    int idx = k * (nx * ny) + j * nx + i;
                    data[idx] = lat + lon + static_cast<double>(step);
                }
            }
        }
        return data;
    }
};

class NetCDFDataRetriever : public DataRetriever {
public:
    std::vector<double> RetrieveField(
        const std::string& name,
        int step,
        int nx, int ny, int nz,
        const std::vector<double>& lons,
        const std::vector<double>& lats
    ) override {
        throw std::runtime_error("NetCDF file reading is not supported/implemented in this milestone.");
    }
};

struct TestExecutionResult {
    bool success = false;
    std::string output_nc_file;
    std::vector<double> final_pm25_export;
};

class CeceTestRunner {
public:
    CeceTestRunner(const std::string& yaml_path, int nx, int ny, int nz, std::shared_ptr<DataRetriever> retriever)
        : yaml_path_(yaml_path), nx_(nx), ny_(ny), nz_(nz), retriever_(retriever) {}

    TestExecutionResult Run(int total_steps) {
        TestExecutionResult result;
        int rc = 0;

        // Set config file path
        cece_set_config_file_path(yaml_path_.c_str(), static_cast<int>(yaml_path_.length()));

        void* data_ptr = nullptr;
        cece_core_initialize_p1(&data_ptr, &rc);
        if (rc != 0 || !data_ptr) {
            std::cerr << "Phase 1 Initialization failed" << std::endl;
            return result;
        }

        int nx = nx_;
        int ny = ny_;
        int nz = nz_;
        cece_core_initialize_p2(data_ptr, &nx, &ny, &nz, &rc);
        if (rc != 0) {
            std::cerr << "Phase 2 Initialization failed" << std::endl;
            cece_core_finalize(data_ptr, &rc);
            return result;
        }

        // Initialize standalone writer
        std::string start_time = "2020-07-15T00:00:00";
        cece_core_writer_initialize(data_ptr, nx, ny, nz, start_time.c_str(), static_cast<int>(start_time.length()), &rc);
        if (rc != 0) {
            std::cerr << "Writer initialization failed" << std::endl;
            cece_core_finalize(data_ptr, &rc);
            return result;
        }

        // Generate coordinates: regular grid centers
        double lon_min = -180.0, lon_max = 180.0;
        double lat_min = -90.0, lat_max = 90.0;
        double dx = (lon_max - lon_min) / nx_;
        double dy = (lat_max - lat_min) / ny_;

        std::vector<double> lons(nx_);
        for (int i = 0; i < nx_; ++i) lons[i] = lon_min + (i + 0.5) * dx;

        std::vector<double> lats(ny_);
        for (int j = 0; j < ny_; ++j) lats[j] = lat_min + (j + 0.5) * dy;

        // Allocate memory for bound export fields
        std::vector<double> pm25_export_data(nx_ * ny_ * nz_, 0.0);

        // Register export fields in internal state
        cece_core_set_export_field(data_ptr, "pm25", 4, pm25_export_data.data(), nx_, ny_, nz_, &rc);
        if (rc != 0) {
            std::cerr << "Failed to register export field" << std::endl;
            cece_core_finalize(data_ptr, &rc);
            return result;
        }

        // Simulation loop
        int timestep_seconds = 3600;
        for (int step = 0; step < total_steps; ++step) {
            int hour = (step * (timestep_seconds / 3600)) % 24;
            int day_of_week = 0; // Monday

            // Generate mocked input data for variable "HTAP_PM25_ENERGY"
            auto mocked_pm25 = retriever_->RetrieveField("HTAP_PM25_ENERGY", step, nx_, ny_, nz_, lons, lats);

            // Set the mocked stream field
            cece_ingestor_set_field(data_ptr, "HTAP_PM25_ENERGY", 16, mocked_pm25.data(), nz_, nx_ * ny_, &rc);
            if (rc != 0) {
                std::cerr << "Failed to ingest field: HTAP_PM25_ENERGY" << std::endl;
                cece_core_finalize(data_ptr, &rc);
                return result;
            }

            // Run core emissions stacking
            cece_core_run(data_ptr, hour, day_of_week, &rc);
            if (rc != 0) {
                std::cerr << "Core run step failed" << std::endl;
                cece_core_finalize(data_ptr, &rc);
                return result;
            }

            // Write standalone NetCDF output if configured
            double time_seconds = static_cast<double>(step * timestep_seconds);
            cece_core_write_step(data_ptr, time_seconds, step, &rc);
            if (rc != 0) {
                std::cerr << "Failed to write step " << step << " (rc = " << rc << ")" << std::endl;
                cece_core_finalize(data_ptr, &rc);
                return result;
            }
        }

        // Save final memory state before finalizing
        auto* internal_data = static_cast<cece::CeceInternalData*>(data_ptr);
        if (internal_data && internal_data->export_state.fields.find("pm25") != internal_data->export_state.fields.end()) {
            auto view = internal_data->export_state.fields.at("pm25").view_host();
            for (size_t idx = 0; idx < view.size(); ++idx) {
                result.final_pm25_export.push_back(view.data()[idx]);
            }
        }

        // Standalone writer output filename verification
        if (internal_data && internal_data->config.output_config.enabled) {
            result.output_nc_file = internal_data->config.output_config.directory + "/cece_output_test.nc";
        }

        cece_core_finalize(data_ptr, &rc);
        result.success = (rc == 0);
        return result;
    }

private:
    std::string yaml_path_;
    int nx_, ny_, nz_;
    std::shared_ptr<DataRetriever> retriever_;
};

class CeceTestBuilder {
public:
    CeceTestBuilder& SetConfigTemplate(const std::string& path) {
        template_path_ = path;
        return *this;
    }

    CeceTestBuilder& SetGridDimensions(int nx, int ny, int nz) {
        nx_ = nx;
        ny_ = ny;
        nz_ = nz;
        return *this;
    }

    CeceTestBuilder& SetDataRetriever(std::shared_ptr<DataRetriever> retriever) {
        retriever_ = retriever;
        return *this;
    }

    CeceTestRunner Build(const std::string& output_yaml_path) {
        // Programmatically construct configuration via yaml-cpp
        YAML::Node config = YAML::LoadFile(template_path_);

        // Ensure output configuration is enabled for testing
        config["output"]["enabled"] = true;
        config["output"]["directory"] = "cece_test_output";
        config["output"]["filename_pattern"] = "cece_output_test.nc";
        config["output"]["frequency_steps"] = 1;
        config["output"]["fields"] = std::vector<std::string>{"pm25"};

        // Extract grid dimensions directly from the yaml configuration without modifying them
        int nx = config["driver"]["grid"]["nx"].as<int>();
        int ny = config["driver"]["grid"]["ny"].as<int>();
        int nz = config["driver"]["grid"]["nz"].as<int>();

        std::ofstream fout(output_yaml_path);
        fout << config;
        fout.close();

        return CeceTestRunner(output_yaml_path, nx, ny, nz, retriever_);
    }

private:
    std::string template_path_;
    int nx_ = 4, ny_ = 4, nz_ = 1;
    std::shared_ptr<DataRetriever> retriever_;
};

#include <netcdf.h>

bool ReadNetCDFVariable(const std::string& filepath, const std::string& varname, std::vector<double>& out_data) {
    int ncid;
    int status = nc_open(filepath.c_str(), NC_NOWRITE, &ncid);
    if (status != NC_NOERR) {
        std::cerr << "ReadNetCDFVariable ERROR: nc_open failed for '" << filepath 
                  << "' with error: " << nc_strerror(status) << " (code " << status << ")" << std::endl;
        return false;
    }

    int varid;
    status = nc_inq_varid(ncid, varname.c_str(), &varid);
    if (status != NC_NOERR) {
        std::cerr << "ReadNetCDFVariable ERROR: nc_inq_varid failed for '" << varname 
                  << "' with error: " << nc_strerror(status) << " (code " << status << ")" << std::endl;
        nc_close(ncid);
        return false;
    }

    int ndims;
    status = nc_inq_varndims(ncid, varid, &ndims);
    if (status != NC_NOERR) {
        std::cerr << "ReadNetCDFVariable ERROR: nc_inq_varndims failed with error: " << nc_strerror(status) << " (code " << status << ")" << std::endl;
        nc_close(ncid);
        return false;
    }

    int dimids[8];
    status = nc_inq_vardimid(ncid, varid, dimids);
    if (status != NC_NOERR) {
        std::cerr << "ReadNetCDFVariable ERROR: nc_inq_vardimid failed with error: " << nc_strerror(status) << " (code " << status << ")" << std::endl;
        nc_close(ncid);
        return false;
    }

    size_t total_size = 1;
    for (int i = 0; i < ndims; ++i) {
        size_t len;
        status = nc_inq_dimlen(ncid, dimids[i], &len);
        if (status != NC_NOERR) {
            std::cerr << "ReadNetCDFVariable ERROR: nc_inq_dimlen failed for dim " << i 
                      << " with error: " << nc_strerror(status) << " (code " << status << ")" << std::endl;
            nc_close(ncid);
            return false;
        }
        total_size *= len;
    }

    out_data.resize(total_size);
    status = nc_get_var_double(ncid, varid, out_data.data());
    if (status != NC_NOERR) {
        std::cerr << "ReadNetCDFVariable ERROR: nc_get_var_double failed with error: " << nc_strerror(status) << " (code " << status << ")" << std::endl;
        nc_close(ncid);
        return false;
    }

    nc_close(ncid);
    return true;
}

} // namespace cece::test

class CeceIntegrationHarnessTest : public ::testing::Test {
protected:
    void SetUp() override {
        if (!Kokkos::is_initialized()) {
            Kokkos::initialize();
        }
        std::filesystem::create_directories("cece_test_output");
    }

    void TearDown() override {
        std::filesystem::remove_all("cece_test_output");
        std::filesystem::remove("temp_test_config.yaml");
    }
};

TEST_F(CeceIntegrationHarnessTest, EndToEndMockedRun) {
    auto retriever = std::make_shared<cece::test::MockDataRetriever>();
    cece::test::CeceTestBuilder builder;
    std::string template_path = "/opt/project/local-data/cece-edgar-htap.yaml";
    if (!std::filesystem::exists(template_path)) {
        template_path = "/work/local-data/cece-edgar-htap.yaml";
    }
    if (!std::filesystem::exists(template_path)) {
        template_path = "../local-data/cece-edgar-htap.yaml";
    }
    if (!std::filesystem::exists(template_path)) {
        template_path = "local-data/cece-edgar-htap.yaml";
    }
    builder.SetConfigTemplate(template_path)
           .SetDataRetriever(retriever);

    auto runner = builder.Build("temp_test_config.yaml");
    auto result = runner.Run(3);

    EXPECT_TRUE(result.success);
    EXPECT_EQ(result.output_nc_file, "cece_test_output/cece_output_test.nc");
    EXPECT_TRUE(std::filesystem::exists(result.output_nc_file));

    // Verify in-memory export fields correctness
    // Dimensions: 3600x1800x1
    // For Step 2: value = lat + lon + 2.0
    // Latitudes index 0 center: -90.0 + 0.5 * 0.1 = -89.95
    // Longitudes index 0 center: -180.0 + 0.5 * 0.1 = -179.95
    // Check index 0: lat[0] + lon[0] + 2.0 = -89.95 + -179.95 + 2.0 = -267.9
    ASSERT_EQ(result.final_pm25_export.size(), 3600 * 1800 * 1);
    EXPECT_DOUBLE_EQ(result.final_pm25_export[0], -267.9);

    // Verify NetCDF output file correctness
    std::vector<double> nc_pm25_data;
    bool read_success = cece::test::ReadNetCDFVariable(result.output_nc_file, "pm25", nc_pm25_data);
    ASSERT_TRUE(read_success) << "Failed to read variable 'pm25' from generated NetCDF file: " << result.output_nc_file;

    // NetCDF output contains only the last timestep (1 step, 3600*1800 elements = 6,480,000 total) due to clobbering behavior
    ASSERT_EQ(nc_pm25_data.size(), 3600 * 1800 * 1);

    // Last step values (index 0 to 15) should match the step 2 mocked values (final memory state)
    for (int i = 0; i < 16; ++i) {
        EXPECT_DOUBLE_EQ(nc_pm25_data[i], result.final_pm25_export[i]);
    }
}

TEST(DataRetrieverTest, MockDataGeneratorValues) {
    cece::test::MockDataRetriever retriever;
    std::vector<double> lons = {-180.0, -90.0, 0.0, 90.0};
    std::vector<double> lats = {-90.0, -30.0, 30.0, 90.0};
    int nx = 4, ny = 4, nz = 1;
    int step = 2;
    
    auto result = retriever.RetrieveField("HTAP_PM25_ENERGY", step, nx, ny, nz, lons, lats);
    ASSERT_EQ(result.size(), 16);
    // Expected value at index 0: lats[0] + lons[0] + step = -90.0 + -180.0 + 2.0 = -268.0
    EXPECT_DOUBLE_EQ(result[0], -268.0);
}

TEST(DataRetrieverTest, NetCDFRetrieverThrows) {
    cece::test::NetCDFDataRetriever retriever;
    EXPECT_THROW(retriever.RetrieveField("HTAP_PM25_ENERGY", 1, 4, 4, 1, {}, {}), std::runtime_error);
}

int main(int argc, char** argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}

