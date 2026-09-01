#ifndef CECE_TEST_MPI_SINGLETON_HPP
#define CECE_TEST_MPI_SINGLETON_HPP

#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

extern char** environ;

namespace cece::test {

// Force MPI into standalone (singleton) initialization by removing every
// Slurm/PMI process-management variable a launcher may have exported into the
// environment. Test binaries are launched by ctest — not by srun/mpiexec — so
// they must never speak PMI. Two field incidents this guards against (both
// under `srun ... ctest` on Ursa, where the binaries are forked grandchildren
// of the job step):
//   - Intel MPI: a PARTIAL environment is the worst case — PMI_FD present but
//     PMI_RANK scrubbed makes the runtime open the inherited PMI socket and
//     send a malformed handshake ("pmirank missing in fullinit command").
//   - OpenMPI: any surviving SLURM_* vars make startup conclude the process
//     was "direct launched using srun" and attempt a PMI/PMIx wire-up no
//     endpoint exists for ("OMPI was not built with SLURM support" — a
//     misleading catch-all banner), aborting MPI_Init_thread.
// OpenMPI keys its detection on variables outside any fixed name list (an
// exact-list scrub was probed on Ursa and failed; a full prefix sweep passed),
// so sweep by prefix instead of pinning names. Call at the top of main(),
// before MPI_Init/InitGoogleTest.
inline void force_mpi_singleton() {
    // Sweep everything Slurm/PMI: names starting with SLURM or PMI (the PMI
    // prefix also covers PMIX_*). Anchored at the name start, so I_MPI_* and
    // OMPI_MCA_* are untouched. Collect first, then unset — never mutate
    // environ while iterating it.
    std::vector<std::string> doomed;
    for (char** entry = environ; entry != nullptr && *entry != nullptr; ++entry) {
        const char* eq = std::strchr(*entry, '=');
        if (eq == nullptr) {
            continue;
        }
        const std::string name(*entry, static_cast<size_t>(eq - *entry));
        if (name.rfind("SLURM", 0) == 0 || name.rfind("PMI", 0) == 0) {
            doomed.push_back(name);
        }
    }
    for (const std::string& name : doomed) {
        unsetenv(name.c_str());
    }

    unsetenv("I_MPI_PMI_LIBRARY");
    // Keep Intel MPI local-only on login nodes (prevent PMI2/Hydra aborts)
    setenv("I_MPI_HYDRA_BOOTSTRAP", "none", 0);
    setenv("I_MPI_SHM", "disable", 0);
}

}  // namespace cece::test

#endif  // CECE_TEST_MPI_SINGLETON_HPP
