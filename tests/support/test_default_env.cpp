// Linked into every test/benchmark executable (see the
// cece_test_default_env loop in the top-level CMakeLists.txt).
//
// Kokkos's OpenMP backend warns at initialize when OMP_PROC_BIND is
// unset and recommends OMP_PROC_BIND=false for unit testing. Setting it
// per-test via ctest ENVIRONMENT properties cannot cover gtest
// discovery re-runs (--gtest_list_tests), which are not tests; a
// pre-main default in the binary itself covers every execution path.
// overwrite=0: an externally exported OMP_PROC_BIND always wins.

#include <cstdlib>

namespace {

const bool cece_test_omp_defaults_applied = [] {
    ::setenv("OMP_PROC_BIND", "false", /*overwrite=*/0);
    return true;
}();

}  // namespace
