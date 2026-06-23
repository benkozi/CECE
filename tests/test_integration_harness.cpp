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
    std::vector<double> final_co_export;
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
        std::vector<double> co_export_data(nx_ * ny_ * nz_, 0.0);

        // Register export fields in internal state
        cece_core_set_export_field(data_ptr, "co", 2, co_export_data.data(), nx_, ny_, nz_, &rc);
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

            // Generate mocked input data for variable "co"
            auto mocked_co = retriever_->RetrieveField("co", step, nx_, ny_, nz_, lons, lats);

            // Set the mocked stream field
            cece_ingestor_set_field(data_ptr, "co", 2, mocked_co.data(), nz_, nx_ * ny_, &rc);
            if (rc != 0) {
                std::cerr << "Failed to ingest field: co" << std::endl;
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
        }

        // Save final memory state before finalizing
        auto* internal_data = static_cast<cece::CeceInternalData*>(data_ptr);
        if (internal_data && internal_data->export_state.fields.find("co") != internal_data->export_state.fields.end()) {
            auto view = internal_data->export_state.fields.at("co").view_host();
            for (size_t idx = 0; idx < view.size(); ++idx) {
                result.final_co_export.push_back(view.data()[idx]);
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
        config["output"]["fields"] = std::vector<std::string>{"co"};

        // Configure driver dimensions
        config["driver"]["grid"]["nx"] = nx_;
        config["driver"]["grid"]["ny"] = ny_;
        config["driver"]["grid"]["nz"] = nz_;

        std::ofstream fout(output_yaml_path);
        fout << config;
        fout.close();

        return CeceTestRunner(output_yaml_path, nx_, ny_, nz_, retriever_);
    }

private:
    std::string template_path_;
    int nx_ = 4, ny_ = 4, nz_ = 1;
    std::shared_ptr<DataRetriever> retriever_;
};

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
    std::string template_path = "/opt/cece/src/examples/cece_config_ex1.yaml";
    if (!std::filesystem::exists(template_path)) {
        template_path = "examples/cece_config_ex1.yaml";
    }
    builder.SetConfigTemplate(template_path)
           .SetGridDimensions(4, 4, 1)
           .SetDataRetriever(retriever);

    auto runner = builder.Build("temp_test_config.yaml");
    auto result = runner.Run(3);

    EXPECT_TRUE(result.success);
    EXPECT_FALSE(result.output_nc_file.empty());
}

TEST(DataRetrieverTest, MockDataGeneratorValues) {
    cece::test::MockDataRetriever retriever;
    std::vector<double> lons = {-180.0, -90.0, 0.0, 90.0};
    std::vector<double> lats = {-90.0, -30.0, 30.0, 90.0};
    int nx = 4, ny = 4, nz = 1;
    int step = 2;
    
    auto result = retriever.RetrieveField("co", step, nx, ny, nz, lons, lats);
    ASSERT_EQ(result.size(), 16);
    // Expected value at index 0: lats[0] + lons[0] + step = -90.0 + -180.0 + 2.0 = -268.0
    EXPECT_DOUBLE_EQ(result[0], -268.0);
}

TEST(DataRetrieverTest, NetCDFRetrieverThrows) {
    cece::test::NetCDFDataRetriever retriever;
    EXPECT_THROW(retriever.RetrieveField("co", 1, 4, 4, 1, {}, {}), std::runtime_error);
}

int main(int argc, char** argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
