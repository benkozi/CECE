/**
 * @file cece_host_threads.hpp
 * @brief The OpenMP thread count CECE gives Kokkos.
 *
 * cece_core_initialize_p1 initializes Kokkos with driver.num_threads when the
 * config sets it, else with the host's count (the NUOPC cap sets the number of
 * PEs its runtime gave the calling PET before the simulation is created), else
 * with OMP_NUM_THREADS, else with the Kokkos default (every hardware thread).
 */

#ifndef CECE_HOST_THREADS_HPP
#define CECE_HOST_THREADS_HPP

#include <string>

namespace cece {

/// Thread count chosen for Kokkos; threads == 0 leaves the Kokkos default.
struct HostThreadChoice {
    int threads = 0;
    std::string source;  ///< "config", "vm", "OMP_NUM_THREADS" or "Kokkos default"
};

/**
 * @brief Set the host-supplied thread count for the next Kokkos initialization.
 *
 * @param pe_count PEs the host gives this PET; values <= 0 clear it
 */
void SetHostThreadCount(int pe_count);

/// The host-supplied thread count, 0 when none is set.
int GetHostThreadCount();

/**
 * @brief Choose the thread count: config, then host count, then OMP_NUM_THREADS, then the Kokkos default.
 *
 * @param config_threads driver.num_threads (0 = not set)
 * @param host_count Host-supplied count (0 = none)
 * @param omp_num_threads Value of OMP_NUM_THREADS, or nullptr when unset
 */
HostThreadChoice ResolveHostThreads(int config_threads, int host_count, const char* omp_num_threads);

/**
 * @brief Check an already-initialized Kokkos against the count CECE was given.
 *
 * @param requested Threads from the config or the host (0 = none, always accepted)
 * @param concurrency Threads of the running host execution space
 * @return Empty when acceptable, otherwise the error message
 */
std::string CheckExistingConcurrency(int requested, int concurrency);

}  // namespace cece

extern "C" {
/// C interface for the Fortran cap: see cece::SetHostThreadCount.
void cece_set_host_thread_count(int pe_count);
}

#endif  // CECE_HOST_THREADS_HPP
