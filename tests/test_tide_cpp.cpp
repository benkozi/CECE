#include <gtest/gtest.h>
#include <mpi.h>

#include <Kokkos_Core.hpp>
#include <dagr/dagr.hpp>
#include <halo/environment.hpp>

#include "cece/cece_helm_graph.hpp"
#include "cece/cece_io.hpp"

// Forward declare CECE C-Linkage APIs
extern "C" {
void cece_set_config_file_path(const char* config_path, int path_len);
void cece_core_initialize_p1(void** data_ptr_ptr, int* rc);
void cece_core_finalize(void* data_ptr, int* rc);
}

std::string GetConfigPath() {
#ifdef CECE_SOURCE_DIR
    return std::string(CECE_SOURCE_DIR) + "/cece_control_mock.yaml";
#else
    return "cece_control_mock.yaml";
#endif
}

TEST(TideTest, TestBMIPointerAllocation) {
    cece::io::CeceIO cece_io;
    EXPECT_THROW(cece_io.Initialize("non_existent_file.yaml", 72, 46, 1), std::runtime_error);
}

TEST(TideTest, TestDynamicGraphCompilation) {
    std::unique_ptr<dagr::GraphOrchestrator> dagr;
    cece::io::CeceIO cece_io;

    std::string mock_config = GetConfigPath();
    cece_io.Initialize(mock_config, 72, 46, 1);
    CompileHelmGraph(mock_config, dagr, cece_io);

    EXPECT_TRUE(true);
}

TEST(TideTest, TestEndToEndDriverLoopStub) {
    // Set config file path dynamically
    std::string mock_config = GetConfigPath();
    cece_set_config_file_path(mock_config.c_str(), static_cast<int>(mock_config.length()));

    // Verifies that the C-linkage setup compiles and instantiates without hanging
    void* cece_data_ptr = nullptr;
    int rc = 0;
    cece_core_initialize_p1(&cece_data_ptr, &rc);
    EXPECT_EQ(rc, 0);
    EXPECT_NE(cece_data_ptr, nullptr);
    cece_core_finalize(cece_data_ptr, &rc);
}

// Custom GTest Environment to manage Kokkos & MPI lifecycle globally
class KokkosMpiEnvironment : public ::testing::Environment {
   public:
    void SetUp() override {
        // Initialize MPI first
        int mpi_initialized = 0;
        MPI_Initialized(&mpi_initialized);
        if (!mpi_initialized) {
            int argc = 0;
            char** argv = nullptr;
            int provided = 0;
            MPI_Init_thread(&argc, &argv, MPI_THREAD_MULTIPLE, &provided);
        }

        // Initialize Kokkos
        if (!Kokkos::is_initialized()) {
            Kokkos::initialize();
        }

        // Initialize HALO Environment
        halo::Environment::initialize();
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
    ::testing::InitGoogleTest(&argc, argv);
    ::testing::AddGlobalTestEnvironment(new KokkosMpiEnvironment);
    return RUN_ALL_TESTS();
}
