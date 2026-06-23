# CECE Integration Test Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a mocked end-to-end integration test harness in C++ for the CECE model execution using a YAML configuration entrypoint and evaluate outputs for correctness.

**Architecture:** Use the builder design pattern to construct the C++ integration runner. The test reads `examples/cece_config_ex1.yaml` using `yaml-cpp`, programmatically configures the grid, timestep, and output directory, and runs the initialization and execution phases. A mock data generator provides coordinate-dependent synthetic values to mock file and import inputs. Correctness is verified by checking the internal memory map and reading the generated NetCDF files.

**Tech Stack:** C++, Google Test, Kokkos, NetCDF C Library (`netcdf.h`), `yaml-cpp`.

## Global Constraints

- Run a CECE operation end-to-end using a YAML configuration entrypoint.
- Following test completion, output should be evaluated for correctness. Output includes netCDF and export fields contained in an unordered map.
- YAML configurations should be generated programmatically using yaml-cpp.
- Test harness should be written in C++ using fixtures following the host project's unit test pattern.
- Mocked form uses synthetic data in place of any data read from file.
- Meteorological fields / import fields are always mocked.
- Use a "builder" design pattern to build up the unit test implementation.
- All code changes must pass in the docker container with the command: `docker run --rm --platform linux/amd64 cece-image /opt/cece/src/build/test_integration_harness`.

---

### Task 1: CMake Target and Scaffolding

**Files:**
- Modify: `CMakeLists.txt`
- Create: `tests/test_integration_harness.cpp`

**Interfaces:**
- Produces: `test_integration_harness` test executable target in CMake.

- [ ] **Step 1: Create a minimal test file with a failing test**
  Write a minimal test that fails by asserting false.
  
  Create `tests/test_integration_harness.cpp` with content:
  ```cpp
  #include <gtest/gtest.h>

  TEST(IntegrationHarnessTest, FailOnPurpose) {
      ASSERT_TRUE(false) << "Scaffolding fail verification";
  }

  int main(int argc, char** argv) {
      ::testing::InitGoogleTest(&argc, argv);
      return RUN_ALL_TESTS();
  }
  ```

- [ ] **Step 2: Add target to CMakeLists.txt**
  Register the new test target.
  
  Modify `CMakeLists.txt` (around line 345, before `if(CECE_HAS_FORTRAN)`):
  ```cmake
  add_executable(test_integration_harness tests/test_integration_harness.cpp)
  target_link_libraries(test_integration_harness PRIVATE cece GTest::gtest)
  ```

- [ ] **Step 3: Run docker build to verify compilation and test failure**
  Build the docker container and run the new test to verify it fails as expected.
  
  Run command:
  ```bash
  docker build -t cece-image -f docker/Dockerfile .
  ```
  Then run command:
  ```bash
  docker run --rm --platform linux/amd64 cece-image /opt/cece/src/build/test_integration_harness
  ```
  Expected output: `FAIL` with "Scaffolding fail verification".

- [ ] **Step 4: Commit the scaffolding**
  ```bash
  git add CMakeLists.txt tests/test_integration_harness.cpp
  git commit -m "test: add test_integration_harness scaffolding"
  ```

---

### Task 2: Implement Data Retriever and Builder Interfaces

**Files:**
- Modify: `tests/test_integration_harness.cpp`

**Interfaces:**
- Produces: `cece::test::DataRetriever`, `cece::test::MockDataRetriever`, `cece::test::NetCDFDataRetriever`, and `cece::test::CeceTestBuilder`.

- [ ] **Step 1: Write tests for MockDataRetriever and NetCDFDataRetriever**
  Replace the failing test in `tests/test_integration_harness.cpp` with unit tests for the data retrievers.
  
  Modify `tests/test_integration_harness.cpp`:
  ```cpp
  #include <gtest/gtest.h>
  #include <vector>
  #include <string>
  #include <memory>
  #include <stdexcept>

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

  } // namespace cece::test

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
  ```

- [ ] **Step 2: Build and run the test in Docker**
  Rebuild and run the tests.
  
  Run command:
  ```bash
  docker build -t cece-image -f docker/Dockerfile .
  ```
  Then run command:
  ```bash
  docker run --rm --platform linux/amd64 cece-image /opt/cece/src/build/test_integration_harness
  ```
  Expected output: `PASS`.

- [ ] **Step 3: Commit the retriever implementations**
  ```bash
  git add tests/test_integration_harness.cpp
  git commit -m "feat: implement DataRetriever interfaces and tests"
  ```

---

### Task 3: Implement `CeceTestRunner` & End-To-End Execution Loop

**Files:**
- Modify: `tests/test_integration_harness.cpp`

**Interfaces:**
- Produces: `cece::test::CeceTestRunner` class which executes initialization, timestep runs, and teardown.

- [ ] **Step 1: Write runner integration code**
  Flesh out the runner and builder classes in `tests/test_integration_harness.cpp` to call the CECE bridge API.
  
  Modify `tests/test_integration_harness.cpp`:
  ```cpp
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
  ```

- [ ] **Step 2: Add End-to-End runner test case**
  Add a Google Test case in `tests/test_integration_harness.cpp` that constructs and runs the mock configuration.
  
  ```cpp
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
      builder.SetConfigTemplate("/opt/cece/src/examples/cece_config_ex1.yaml")
             .SetGridDimensions(4, 4, 1)
             .SetDataRetriever(retriever);

      auto runner = builder.Build("temp_test_config.yaml");
      auto result = runner.Run(3);

      EXPECT_TRUE(result.success);
      EXPECT_FALSE(result.output_nc_file.empty());
  }
  ```

- [ ] **Step 3: Run and verify in Docker**
  Verify everything builds and executes cleanly inside docker.
  
  Run command:
  ```bash
  docker build -t cece-image -f docker/Dockerfile .
  ```
  Then run command:
  ```bash
  docker run --rm --platform linux/amd64 cece-image /opt/cece/src/build/test_integration_harness
  ```
  Expected output: `PASS`.

- [ ] **Step 4: Commit the runner changes**
  ```bash
  git add tests/test_integration_harness.cpp
  git commit -m "feat: implement CeceTestRunner and end-to-end execution"
  ```

---

### Task 4: Output Evaluation (In-Memory and NetCDF)

**Files:**
- Modify: `tests/test_integration_harness.cpp`

**Interfaces:**
- Consumes: `CeceTestRunner`, `TestExecutionResult`.
- Produces: Correctness assertions for generated NetCDF values and in-memory export fields.

- [ ] **Step 1: Write NetCDF reader helper function**
  Add a helper function to read double arrays from NetCDF using the C APIs.
  
  Add to `tests/test_integration_harness.cpp` (in namespace `cece::test`):
  ```cpp
  #include <netcdf.h>

  bool ReadNetCDFVariable(const std::string& filepath, const std::string& varname, std::vector<double>& out_data) {
      int ncid;
      if (nc_open(filepath.c_str(), NC_NOWRITE, &ncid) != NC_NOERR) {
          return false;
      }

      int varid;
      if (nc_inq_varid(ncid, varname.c_str(), &varid) != NC_NOERR) {
          nc_close(ncid);
          return false;
      }

      int ndims;
      if (nc_inq_varndims(ncid, varid, &ndims) != NC_NOERR) {
          nc_close(ncid);
          return false;
      }

      int dimids[8];
      if (nc_inq_vardimid(ncid, varid, dimids) != NC_NOERR) {
          nc_close(ncid);
          return false;
      }

      size_t total_size = 1;
      for (int i = 0; i < ndims; ++i) {
          size_t len;
          if (nc_inq_dimlen(ncid, dimids[i], &len) != NC_NOERR) {
              nc_close(ncid);
              return false;
          }
          total_size *= len;
      }

      out_data.resize(total_size);
      if (nc_get_var_double(ncid, varid, out_data.data()) != NC_NOERR) {
          nc_close(ncid);
          return false;
      }

      nc_close(ncid);
      return true;
  }
  ```

- [ ] **Step 2: Add validation assertions to end-to-end test**
  Verify in-memory correctness and NetCDF persistence. In the mocked configuration:
  `co_out = co_in * 1.0` (since species `co` operation is `add` with scale `1.0`).
  Since step 2 is the final step, the final `co` values should align with the step 2 synthetic values:
  `value = lat + lon + 2.0`.
  
  Modify test inside `tests/test_integration_harness.cpp`:
  ```cpp
  TEST_F(CeceIntegrationHarnessTest, EndToEndMockedRun) {
      auto retriever = std::make_shared<cece::test::MockDataRetriever>();
      cece::test::CeceTestBuilder builder;
      builder.SetConfigTemplate("/opt/cece/src/examples/cece_config_ex1.yaml")
             .SetGridDimensions(4, 4, 1)
             .SetDataRetriever(retriever);

      auto runner = builder.Build("temp_test_config.yaml");
      auto result = runner.Run(3);

      EXPECT_TRUE(result.success);
      EXPECT_EQ(result.output_nc_file, "cece_test_output/cece_output_test.nc");

      // Verify in-memory export fields correctness
      // Dimensions: 4x4x1
      // For Step 2: value = lat + lon + 2.0
      // Latitudes: -67.5, -22.5, 22.5, 67.5
      // Longitudes: -135.0, -45.0, 45.0, 135.0
      // Check index 0: lat[0] + lon[0] + 2.0 = -67.5 + -135.0 + 2.0 = -200.5
      ASSERT_EQ(result.final_co_export.size(), 16);
      EXPECT_DOUBLE_EQ(result.final_co_export[0], -200.5);

      // Verify NetCDF output file correctness
      std::vector<double> nc_co_data;
      bool read_success = cece::test::ReadNetCDFVariable(result.output_nc_file, "co", nc_co_data);
      ASSERT_TRUE(read_success) << "Failed to read variable 'co' from generated NetCDF file: " << result.output_nc_file;

      // NetCDF output contains all timesteps (3 steps, each 16 elements = 48 total)
      ASSERT_EQ(nc_co_data.size(), 48);
      
      // Last step values (index 32 to 47) should match the step 2 mocked values (final memory state)
      for (int i = 0; i < 16; ++i) {
          EXPECT_DOUBLE_EQ(nc_co_data[32 + i], result.final_co_export[i]);
      }
  }
  ```

- [ ] **Step 3: Rebuild and execute final tests in Docker**
  Validate the entire build pipeline and assertions.
  
  Run command:
  ```bash
  docker build -t cece-image -f docker/Dockerfile .
  ```
  Then run command:
  ```bash
  docker run --rm --platform linux/amd64 cece-image /opt/cece/src/build/test_integration_harness
  ```
  Expected output: `PASS`.

- [ ] **Step 4: Commit implementation**
  ```bash
  git add tests/test_integration_harness.cpp
  git commit -m "test: implement output verification of export fields and netCDF files"
  ```
