/**
 * @file cece_host_threads.cpp
 * @brief The OpenMP thread count CECE gives Kokkos (see cece_host_threads.hpp).
 *
 * Kokkos defaults to every hardware thread, so several MPI ranks per node
 * oversubscribe the cores unless something narrows it. The NUOPC cap passes
 * the PEs ESMF gives its PET, which is 1 for a plain MPI launch and the
 * component's threads under ESMF-managed threading.
 */

#include "cece/cece_host_threads.hpp"

#include <atomic>
#include <cstdlib>
#include <limits>
#include <string>

namespace cece {

static std::atomic<int> g_host_thread_count{0};

void SetHostThreadCount(int pe_count) {
    g_host_thread_count.store(pe_count > 0 ? pe_count : 0);
}

int GetHostThreadCount() {
    return g_host_thread_count.load();
}

HostThreadChoice ResolveHostThreads(int config_threads, int host_count, const char* omp_num_threads) {
    if (config_threads > 0) {
        return {config_threads, "config"};
    }
    if (host_count > 0) {
        return {host_count, "vm"};
    }
    if (omp_num_threads != nullptr) {
        char* end = nullptr;
        long threads = std::strtol(omp_num_threads, &end, 10);
        if (end != omp_num_threads && *end == '\0' && threads > 0) {
            if (threads > std::numeric_limits<int>::max()) {
                threads = std::numeric_limits<int>::max();
            }
            return {static_cast<int>(threads), "OMP_NUM_THREADS"};
        }
    }
    return {0, "Kokkos default"};
}

std::string CheckExistingConcurrency(int requested, int concurrency) {
    if (requested <= 0 || concurrency <= requested) {
        return {};
    }
    return "CECE: Kokkos is already initialized with " + std::to_string(concurrency) + " threads, more than the " + std::to_string(requested) +
           " CECE was given";
}

}  // namespace cece

extern "C" {

void cece_set_host_thread_count(int pe_count) {
    cece::SetHostThreadCount(pe_count);
}

}  // extern "C"
