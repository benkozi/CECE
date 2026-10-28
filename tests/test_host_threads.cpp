/**
 * @file test_host_threads.cpp
 * @brief Tests for the OpenMP thread count CECE gives Kokkos.
 *
 * Tests verify:
 * - driver.num_threads wins over a host-supplied count (the NUOPC cap passes
 *   the PEs ESMF gives the PET), which wins over OMP_NUM_THREADS, which wins
 *   over the Kokkos default
 * - cece_core_initialize_p1 initializes Kokkos with the host count
 * - An already-initialized Kokkos running more threads than the host count is
 *   refused by name
 */

#include <gtest/gtest.h>

#include <Kokkos_Core.hpp>
#include <filesystem>
#include <fstream>
#include <sstream>
#include <stdexcept>
#include <string>

#include "cece/cece_config.hpp"
#include "cece/cece_host_threads.hpp"

extern "C" {
void cece_set_config_file_path(const char* config_path, int path_len);
void cece_core_initialize_p1(void** data_ptr_ptr, int* rc);
void cece_core_finalize(void* data_ptr, int* rc);
}

TEST(HostThreadsTest, ConfigWinsOverHostCount) {
    const cece::HostThreadChoice choice = cece::ResolveHostThreads(4, 3, "8");
    EXPECT_EQ(choice.threads, 4);
    EXPECT_EQ(choice.source, "config");
}

TEST(HostThreadsTest, HostCountWinsOverEnvironment) {
    const cece::HostThreadChoice choice = cece::ResolveHostThreads(0, 3, "8");
    EXPECT_EQ(choice.threads, 3);
    EXPECT_EQ(choice.source, "vm");
}

TEST(HostThreadsTest, EnvironmentWithoutHostCount) {
    const cece::HostThreadChoice choice = cece::ResolveHostThreads(0, 0, "4");
    EXPECT_EQ(choice.threads, 4);
    EXPECT_EQ(choice.source, "OMP_NUM_THREADS");
}

TEST(HostThreadsTest, KokkosDefaultWithoutEither) {
    for (const char* env : {static_cast<const char*>(nullptr), "", "abc", "0", "-2"}) {
        const cece::HostThreadChoice choice = cece::ResolveHostThreads(0, 0, env);
        EXPECT_EQ(choice.threads, 0) << (env == nullptr ? "(unset)" : env);
        EXPECT_EQ(choice.source, "Kokkos default") << (env == nullptr ? "(unset)" : env);
    }
}

TEST(HostThreadsTest, ExistingConcurrencyCheck) {
    EXPECT_EQ(cece::CheckExistingConcurrency(0, 16), "");
    EXPECT_EQ(cece::CheckExistingConcurrency(2, 1), "");
    EXPECT_EQ(cece::CheckExistingConcurrency(2, 2), "");
    EXPECT_EQ(cece::CheckExistingConcurrency(1, 16), "CECE: Kokkos is already initialized with 16 threads, more than the 1 CECE was given");
}

TEST(HostThreadsTest, SetAndClear) {
    cece_set_host_thread_count(5);
    EXPECT_EQ(cece::GetHostThreadCount(), 5);
    cece_set_host_thread_count(-1);
    EXPECT_EQ(cece::GetHostThreadCount(), 0);
}

namespace {

/// The mock control config with `num_threads: <n>` added to its driver block.
std::string WriteConfigWithThreads(const std::string& name, int n) {
    std::ifstream in(CECE_TEST_CONFIG);
    std::stringstream text;
    text << in.rdbuf();
    std::string yaml = text.str();
    const std::string key = "driver:\n";
    yaml.insert(yaml.find(key) + key.size(), "  num_threads: " + std::to_string(n) + "\n");
    const auto path = std::filesystem::temp_directory_path() / name;
    std::ofstream(path) << yaml;
    return path.string();
}

}  // namespace

TEST(HostThreadsTest, ParserReadsDriverNumThreads) {
    EXPECT_EQ(cece::ParseConfig(CECE_TEST_CONFIG).driver_config.num_threads, 0);
    EXPECT_EQ(cece::ParseConfig(WriteConfigWithThreads("cece_threads_3.yaml", 3)).driver_config.num_threads, 3);
    EXPECT_THROW(cece::ParseConfig(WriteConfigWithThreads("cece_threads_0.yaml", 0)), std::invalid_argument);
}

// Kokkos initializes once per process, so the core-init cases share one test:
// the first init takes driver.num_threads over the host count, the second
// (without the key) meets the running instance with fewer PEs than it has.
TEST(HostThreadsTest, CoreInitializeUsesConfigThenHostCount) {
    ASSERT_FALSE(Kokkos::is_initialized());
    const std::string with_threads = WriteConfigWithThreads("cece_threads_init.yaml", 3);
    cece_set_config_file_path(with_threads.c_str(), static_cast<int>(with_threads.length()));

    void* data_ptr = nullptr;
    int rc = -1;
    cece_set_host_thread_count(2);
    cece_core_initialize_p1(&data_ptr, &rc);
    ASSERT_EQ(rc, 0);
    EXPECT_EQ(Kokkos::DefaultHostExecutionSpace().concurrency(), 3);

    const std::string plain = CECE_TEST_CONFIG;
    cece_set_config_file_path(plain.c_str(), static_cast<int>(plain.length()));
    void* second_ptr = nullptr;
    int second_rc = 0;
    cece_set_host_thread_count(1);
    cece_core_initialize_p1(&second_ptr, &second_rc);
    EXPECT_EQ(second_rc, -1);
    EXPECT_EQ(second_ptr, nullptr);

    cece_set_host_thread_count(0);
    cece_core_finalize(data_ptr, &rc);
    EXPECT_EQ(rc, 0);
}
