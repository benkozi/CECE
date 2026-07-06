#include <gtest/gtest.h>
#include <mpi.h>
#include <unistd.h>

#include <Kokkos_Core.hpp>
#include <algorithm>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <vector>

#include "cece/cece_config.hpp"
#include "cece/cece_standalone_writer.hpp"
#include "cece/cece_utils.hpp"

namespace cece::test {

class CeceUtilsTest : public ::testing::Test {
   protected:
    void SetUp() override {
        // Kokkos and MPI are managed by KokkosMpiEnvironment
    }
};

TEST_F(CeceUtilsTest, WrapESMCFieldUpdatesRawData) {
    const int nx = 10;
    const int ny = 5;
    const int nz = 2;
    std::vector<double> raw_data(static_cast<size_t>(nx) * ny * nz, 0.0);

    UnmanagedHostView3D view;

    // On real ESMF, ESMC_FieldGetPtr would SegFault on a fake handle.
    // We test the Kokkos wrapping logic directly here to prove that
    // LayoutLeft and Unmanaged traits work as expected for ESMF data.
    view = UnmanagedHostView3D(raw_data.data(), nx, ny, nz);

    // Verify dimensions
    EXPECT_EQ(view.extent(0), nx);
    EXPECT_EQ(view.extent(1), ny);
    EXPECT_EQ(view.extent(2), nz);

    // Modify the Kokkos View
    view(2, 3, 1) = 42.0;

    // Verify the raw data is updated
    // Since it's LayoutLeft (Fortran order):
    // index = i + j*nx + k*nx*ny
    int expected_index = 2 + 3 * nx + 1 * nx * ny;
    EXPECT_DOUBLE_EQ(raw_data[expected_index], 42.0);

    // Also verify through the view
    EXPECT_DOUBLE_EQ(view(2, 3, 1), 42.0);
}

TEST_F(CeceUtilsTest, StandaloneWriterDuplicateCoordsDetection) {
    std::string test_dir = "test_output_dir_" + std::to_string(getpid());
    CeceOutputConfig config;
    config.enabled = true;
    config.directory = test_dir;

    CeceStandaloneWriter writer(config);

    // Standard non-duplicate coordinates
    std::vector<double> lon_ok = {-180.0, -90.0, 0.0, 90.0};
    std::vector<double> lat_ok = {-90.0, -45.0, 0.0, 45.0};

    // 1. Unique coordinates should succeed
    int rc_ok = writer.InitializeWithCoords("2026-06-29T12:00:00", 4, 4, 1, lon_ok, lat_ok);
    EXPECT_EQ(rc_ok, 0);
    writer.Finalize();

    // 2. Duplicate longitudes should fail
    std::vector<double> lon_dup = {-180.0, 0.0, 0.0, 90.0};
    int rc_lon_dup = writer.InitializeWithCoords("2026-06-29T12:00:00", 4, 4, 1, lon_dup, lat_ok);
    EXPECT_EQ(rc_lon_dup, -1);
    writer.Finalize();

    // 3. Duplicate latitudes should fail
    std::vector<double> lat_dup = {-90.0, 0.0, 0.0, 45.0};
    int rc_lat_dup = writer.InitializeWithCoords("2026-06-29T12:00:00", 4, 4, 1, lon_ok, lat_dup);
    EXPECT_EQ(rc_lat_dup, -1);
    writer.Finalize();

    // Cleanup output directory if created
    if (std::filesystem::exists(test_dir)) {
        std::filesystem::remove_all(test_dir);
    }
}

TEST_F(CeceUtilsTest, StandaloneWriterDuplicateFieldsFiltering) {
    std::string test_dir = "test_output_dir_fields_" + std::to_string(getpid());
    CeceOutputConfig config;
    config.enabled = true;
    config.directory = test_dir;
    config.fields = {"lon", "lat", "lev", "time", "test_field"};

    CeceStandaloneWriter writer(config);

    std::vector<double> lon_ok = {-180.0, -90.0, 0.0, 90.0};
    std::vector<double> lat_ok = {-90.0, -45.0, 0.0, 45.0};

    int rc = writer.InitializeWithCoords("2026-06-29T12:00:00", 4, 4, 1, lon_ok, lat_ok);
    ASSERT_EQ(rc, 0);

    // Create a mock field map
    std::unordered_map<std::string, DualView3D> fields;
    DualView3D test_field_view("test_field", 4, 4, 1);
    test_field_view.sync<Kokkos::HostSpace>();
    auto h_view = test_field_view.view_host();
    Kokkos::deep_copy(h_view, 1.0);
    test_field_view.modify<Kokkos::HostSpace>();

    // Also put coordinate fields if they are present in the map to see if they are skipped
    DualView3D lon_field_view("lon", 4, 4, 1);
    fields["test_field"] = test_field_view;
    fields["lon"] = lon_field_view;  // This should be skipped safely!

    // Write a time step
    int rc_write = writer.WriteTimeStep(fields, 0.0, 0);
    EXPECT_EQ(rc_write, 0);  // Should succeed and write test_field, skipping lon!

    writer.Finalize();

    // Verify file exists
    std::string expected_file = test_dir + "/cece_output_20260629_120000.nc";
    EXPECT_TRUE(std::filesystem::exists(expected_file));

    if (std::filesystem::exists(test_dir)) {
        std::filesystem::remove_all(test_dir);
    }
}

}  // namespace cece::test

// Custom GTest Environment to manage Kokkos & MPI lifecycle globally
class KokkosMpiEnvironment : public ::testing::Environment {
   private:
    int argc_;
    char** argv_;

   public:
    KokkosMpiEnvironment(int argc, char** argv) : argc_(argc), argv_(argv) {}

    void SetUp() override {
        // Initialize MPI first
        int mpi_initialized = 0;
        MPI_Initialized(&mpi_initialized);
        if (!mpi_initialized) {
            int provided = 0;
            MPI_Init_thread(&argc_, &argv_, MPI_THREAD_MULTIPLE, &provided);
        }

        // Initialize Kokkos
        if (!Kokkos::is_initialized()) {
            Kokkos::initialize(argc_, argv_);
        }
    }
    void TearDown() override {
        // Finalize Kokkos
        if (Kokkos::is_initialized()) {
            Kokkos::finalize();
        }

        // Finalize MPI
        int mpi_initialized = 0;
        MPI_Initialized(&mpi_initialized);
        if (mpi_initialized) {
            MPI_Finalize();
        }
    }
};

int main(int argc, char** argv) {
    bool is_discovery = false;
    for (int i = 1; i < argc; ++i) {
        if (std::string(argv[i]) == "--gtest_list_tests") {
            is_discovery = true;
            break;
        }
    }

    if (!is_discovery) {
        // Prevent Intel MPI from detecting Slurm and attempting PMI/PMIX process manager bootstrap during unit tests
        unsetenv("SLURM_JOB_ID");
        unsetenv("SLURM_STEP_ID");
        unsetenv("PMI_RANK");
        unsetenv("PMI_SIZE");

        // Configure Intel MPI to allow standalone, local-only execution on login nodes (prevent PMI2/Hydra aborts)
        setenv("I_MPI_HYDRA_BOOTSTRAP", "none", 0);
        setenv("I_MPI_SHM", "disable", 0);

        // Initialize MPI to check rank and prevent parallel duplicate execution conflicts of local unit tests
        int mpi_initialized = 0;
        MPI_Initialized(&mpi_initialized);
        if (!mpi_initialized) {
            int provided = 0;
            MPI_Init_thread(&argc, &argv, MPI_THREAD_MULTIPLE, &provided);
        }
        int rank = 0;
        MPI_Comm_rank(MPI_COMM_WORLD, &rank);
        if (rank > 0) {
            MPI_Finalize();
            return 0;
        }
    }

    ::testing::InitGoogleTest(&argc, argv);
    ::testing::AddGlobalTestEnvironment(new KokkosMpiEnvironment(argc, argv));
    return RUN_ALL_TESTS();
}
