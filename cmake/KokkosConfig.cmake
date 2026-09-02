# Custom KokkosConfig to satisfy find_package(Kokkos 5.1.1 REQUIRED) when using FetchContent.
# When Kokkos is built in-tree via FetchContent rather than installed on the host system,
# CMake's find_package() cannot locate a system-installed KokkosConfig.cmake.
# This file bridges FetchContent with downstream find_package() calls by confirming
# that Kokkos has been populated and its targets (e.g., Kokkos::kokkos) are available.
set(Kokkos_FOUND TRUE)
set(Kokkos_VERSION "5.1.1")
set(Kokkos_VERSION_MAJOR 5)
set(Kokkos_VERSION_MINOR 1)
set(Kokkos_VERSION_PATCH 1)
set(Kokkos_DIR "${CMAKE_BINARY_DIR}/_deps/kokkos-src")

# Verify that the Kokkos targets created by FetchContent_MakeAvailable(kokkos) are present.
if(NOT TARGET Kokkos::kokkos)
  message(
    WARNING
    "Kokkos::kokkos target not defined yet. Ensure FetchContent_MakeAvailable(kokkos) runs before find_package."
  )
endif()
