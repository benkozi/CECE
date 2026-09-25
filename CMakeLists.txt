cmake_minimum_required(VERSION 3.20)
project(CECE LANGUAGES CXX C)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

# Optional Fortran support
include(CheckLanguage)
check_language(Fortran)
if(CMAKE_Fortran_COMPILER)
  enable_language(Fortran)
  set(CECE_HAS_FORTRAN ON)
  file(MAKE_DIRECTORY ${CMAKE_BINARY_DIR}/share)
else()
  message(WARNING "Fortran compiler not found. Fortran features will be disabled.")
endif()

# Set build type before any FetchContent dependencies configure,
# since ArborX (via HELM AXIS) force-sets this cache variable itself if left unspecified.
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE "RelWithDebInfo" CACHE STRING "Choose the type of build." FORCE)
  set_property(
    CACHE CMAKE_BUILD_TYPE
    PROPERTY STRINGS "Debug" "Release" "RelWithDebInfo" "MinSizeRel"
  )
endif()

list(INSERT CMAKE_MODULE_PATH 0 "${CMAKE_CURRENT_SOURCE_DIR}/cmake")

if(EXISTS "/opt/views/view")
  list(APPEND CMAKE_PREFIX_PATH "/opt/views/view")
endif()

# Allow find_package to use <PackageName>_ROOT variables
if(POLICY CMP0074)
  cmake_policy(SET CMP0074 NEW)
endif()

# Discover and append standard HPC/Spack-Stack NetCDF environment variables to CMAKE_PREFIX_PATH
foreach(
  env_var
  NetCDF_ROOT
  NETCDF_ROOT
  NETCDF_DIR
  NetCDF_DIR
  netCDF_ROOT
  netcdf_ROOT
  NetCDF_C_ROOT
  NETCDF_C_ROOT
)
  if(DEFINED ENV{${env_var}})
    list(APPEND CMAKE_PREFIX_PATH "$ENV{${env_var}}")
  endif()
endforeach()

# Disable Intel oneAPI warnings about -g without -O0
if(CMAKE_CXX_COMPILER_ID STREQUAL "IntelLLVM")
  set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -Rno-debug-disables-optimization")
endif()
if(CMAKE_C_COMPILER_ID STREQUAL "IntelLLVM")
  set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS} -Rno-debug-disables-optimization")
endif()
if(CECE_HAS_FORTRAN AND CMAKE_Fortran_COMPILER_ID STREQUAL "IntelLLVM")
  set(CMAKE_Fortran_FLAGS "${CMAKE_Fortran_FLAGS} -diag-disable=10440")
endif()

# --- Dependencies ---
#
# Every external dependency is discovered with find_package() first; FetchContent
# is only a fallback for hosts that do not provide the package, and the fallbacks
# can be disabled entirely for network-isolated builds (e.g. HPC compute nodes).

include(FetchContent)

# Master switch for the FetchContent fallbacks. When OFF, every dependency must
# resolve via find_package() and configure never reaches for the network.
option(CECE_FETCH_DEPS "Allow FetchContent fallbacks when find_package() fails" ON)

# The test suite needs GTest and RapidCheck, which HPC stacks generally do not
# provide (e.g. spack-stack); turn testing off there.
option(CECE_BUILD_TESTING "Build the CECE test suite (requires GTest and RapidCheck)" ON)

# Record how each dependency was resolved; summarized at the end of configure.
set_property(GLOBAL PROPERTY CECE_DEP_SUMMARY "")
function(cece_register_dep name provider)
  set_property(GLOBAL APPEND PROPERTY CECE_DEP_SUMMARY "${name}: ${provider}")
  message(STATUS "CECE dependency ${name}: ${provider}")
endfunction()

# Check for OpenMP availability to set generic defaults
find_package(OpenMP QUIET)

# GPU support is optional - users must explicitly enable
option(Kokkos_ENABLE_CUDA "Enable Kokkos CUDA execution space for NVIDIA GPUs" OFF)
option(Kokkos_ENABLE_HIP "Enable Kokkos HIP execution space for AMD GPUs" OFF)

# Python bindings support
option(BUILD_PYTHON_BINDINGS "Build Python bindings for CECE" OFF)

# Validate that at most one GPU backend is enabled
if(Kokkos_ENABLE_CUDA AND Kokkos_ENABLE_HIP)
  message(FATAL_ERROR "Cannot enable both CUDA and HIP. Choose one GPU backend or neither.")
endif()

# Kokkos
find_package(Kokkos QUIET)

if(TARGET Kokkos::kokkos)
  cece_register_dep("Kokkos" "system ${Kokkos_VERSION} (${Kokkos_DIR})")
  message(STATUS "Kokkos execution spaces (pre-installed): ${Kokkos_DEVICES}")
  # A pre-installed Kokkos arrives already configured; verify the required
  # execution spaces are present instead of forcing cache options that the
  # installed binary cannot honor.
  if(COMMAND kokkos_check)
    kokkos_check(DEVICES SERIAL)
    if(Kokkos_ENABLE_CUDA)
      kokkos_check(DEVICES CUDA)
    endif()
    if(Kokkos_ENABLE_HIP)
      kokkos_check(DEVICES HIP)
    endif()
  endif()
elseif(CECE_FETCH_DEPS)
  # Configure execution spaces for the in-tree build: default to Serial and
  # OpenMP (when available) for CPU portability. Users can override with
  # -DKokkos_ENABLE_CUDA=ON or -DKokkos_ENABLE_HIP=ON for GPU support.
  if(NOT DEFINED Kokkos_ENABLE_SERIAL)
    set(Kokkos_ENABLE_SERIAL ON CACHE BOOL "Enable Kokkos Serial execution space" FORCE)
  endif()

  if(NOT DEFINED Kokkos_ENABLE_OPENMP)
    if(OpenMP_CXX_FOUND)
      set(Kokkos_ENABLE_OPENMP ON CACHE BOOL "Enable Kokkos OpenMP execution space" FORCE)
    else()
      set(Kokkos_ENABLE_OPENMP OFF CACHE BOOL "Enable Kokkos OpenMP execution space" FORCE)
    endif()
  endif()

  # Log Kokkos configuration
  message(STATUS "Kokkos Execution Spaces Configuration:")
  message(STATUS "  Serial: ${Kokkos_ENABLE_SERIAL}")
  message(STATUS "  OpenMP: ${Kokkos_ENABLE_OPENMP}")
  message(STATUS "  CUDA: ${Kokkos_ENABLE_CUDA}")
  message(STATUS "  HIP: ${Kokkos_ENABLE_HIP}")

  FetchContent_Declare(kokkos GIT_REPOSITORY https://github.com/kokkos/kokkos.git GIT_TAG 5.1.1)
  FetchContent_MakeAvailable(kokkos)
  cece_register_dep("Kokkos" "FetchContent (5.1.1)")

  # The HELM subdirectories call find_package(Kokkos) themselves; point them at
  # a stub package config that vouches for the in-tree FetchContent targets.
  # The stub lives in the build dir so it can never shadow a real installation.
  set(_cece_kokkos_stub_dir "${CMAKE_BINARY_DIR}/cece-deps/Kokkos")
  file(
    WRITE "${_cece_kokkos_stub_dir}/KokkosConfig.cmake"
    [=[
# Generated by CECE: bridges the FetchContent-built Kokkos to downstream
# find_package(Kokkos) consumers (e.g. the HELM libraries).
set(Kokkos_FOUND TRUE)
set(Kokkos_VERSION "5.1.1")
set(Kokkos_VERSION_MAJOR 5)
set(Kokkos_VERSION_MINOR 1)
set(Kokkos_VERSION_PATCH 1)
if(NOT TARGET Kokkos::kokkos)
  message(
    WARNING
    "Kokkos::kokkos target not defined yet. Ensure FetchContent_MakeAvailable(kokkos) runs before find_package."
  )
endif()
]=]
  )
  file(
    WRITE "${_cece_kokkos_stub_dir}/KokkosConfigVersion.cmake"
    [=[
set(PACKAGE_VERSION "5.1.1")
set(PACKAGE_VERSION_COMPATIBLE TRUE)
set(PACKAGE_VERSION_EXACT FALSE)
]=]
  )
  set(Kokkos_DIR "${_cece_kokkos_stub_dir}" CACHE PATH "Kokkos stub config (FetchContent)" FORCE)
else()
  message(
    FATAL_ERROR
    "Kokkos not found via find_package() and CECE_FETCH_DEPS=OFF. Install Kokkos (e.g. via spack) or re-enable the FetchContent fallback."
  )
endif()

# mdspan headers (<mdspan/mdspan.hpp>), used by the HELM libraries (SPAN, AXIS, DAGR)
if(kokkos_SOURCE_DIR)
  # FetchContent path: use Kokkos's bundled reference mdspan headers.
  include_directories(SYSTEM "${kokkos_SOURCE_DIR}/tpls/mdspan/include")
  cece_register_dep("mdspan" "bundled with fetched Kokkos")
else()
  find_package(mdspan CONFIG QUIET)
  if(TARGET std::mdspan)
    get_target_property(_cece_mdspan_incs std::mdspan INTERFACE_INCLUDE_DIRECTORIES)
    include_directories(SYSTEM ${_cece_mdspan_incs})
    cece_register_dep("mdspan" "system package (${mdspan_DIR})")
  else()
    # An installed Kokkos may ship the reference mdspan headers in its include dir.
    find_path(CECE_MDSPAN_INCLUDE_DIR NAMES mdspan/mdspan.hpp)
    if(CECE_MDSPAN_INCLUDE_DIR)
      include_directories(SYSTEM "${CECE_MDSPAN_INCLUDE_DIR}")
      cece_register_dep("mdspan" "system headers (${CECE_MDSPAN_INCLUDE_DIR})")
    elseif(CECE_FETCH_DEPS)
      FetchContent_Declare(
        mdspan
        GIT_REPOSITORY https://github.com/kokkos/mdspan.git
        GIT_TAG mdspan-0.6.0
      )
      FetchContent_MakeAvailable(mdspan)
      include_directories(SYSTEM "${mdspan_SOURCE_DIR}/include")
      cece_register_dep("mdspan" "FetchContent (mdspan-0.6.0)")
    else()
      message(
        FATAL_ERROR
        "mdspan headers (mdspan/mdspan.hpp) not found and CECE_FETCH_DEPS=OFF. Install the reference mdspan (or a Kokkos that ships it)."
      )
    endif()
  endif()
endif()

# YAML-CPP
if(CMAKE_VERSION VERSION_GREATER_EQUAL "3.30")
  set(CMAKE_POLICY_VERSION_MINIMUM "3.5")
endif()

find_package(yaml-cpp 0.8 CONFIG QUIET)

if(TARGET yaml-cpp::yaml-cpp)
  cece_register_dep("yaml-cpp" "system ${yaml-cpp_VERSION} (${yaml-cpp_DIR})")
  # Have HELM CONF reuse the same installation instead of its own FetchContent.
  set(CONF_USE_SYSTEM_YAMLCPP ON)
  # Installed yaml-cpp packages do not always provide the legacy un-namespaced
  # target; provide a global shim so consumers written against `yaml-cpp`
  # (e.g. HELM CONF) resolve it as a target in every directory scope instead of
  # degrading to a raw -lyaml-cpp on their link lines.
  if(NOT TARGET yaml-cpp)
    add_library(yaml-cpp INTERFACE IMPORTED GLOBAL)
    target_link_libraries(yaml-cpp INTERFACE yaml-cpp::yaml-cpp)
  endif()
else()
  # In-tree build: prefer the vendored submodule (no network), then the GitHub
  # fetch. Both feed through FetchContent so HELM CONF's own
  # FetchContent_MakeAvailable(yaml-cpp) remains a no-op (the name is already
  # populated here); a plain add_subdirectory would leave CONF trying its own
  # network clone on top of duplicate targets.
  if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/extern/yaml-cpp/CMakeLists.txt")
    FetchContent_Declare(yaml-cpp SOURCE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/extern/yaml-cpp")
    set(_cece_yaml_cpp_provider "submodule (extern/yaml-cpp)")
  elseif(CECE_FETCH_DEPS)
    # Keep the tag in sync with the extern/yaml-cpp submodule pin (the submodule
    # is the source of truth if they drift).
    FetchContent_Declare(
      yaml-cpp
      GIT_REPOSITORY https://github.com/jbeder/yaml-cpp.git
      GIT_TAG 0.8.0
    )
    set(_cece_yaml_cpp_provider "FetchContent (0.8.0)")
  else()
    message(
      FATAL_ERROR
      "yaml-cpp not found via find_package(), the extern/yaml-cpp submodule is not populated, and CECE_FETCH_DEPS=OFF. Run `git submodule update --init extern/yaml-cpp`, install yaml-cpp >= 0.8, or re-enable the FetchContent fallback."
    )
  endif()
  FetchContent_MakeAvailable(yaml-cpp)
  if(NOT TARGET yaml-cpp::yaml-cpp)
    add_library(yaml-cpp::yaml-cpp ALIAS yaml-cpp)
  endif()
  cece_register_dep("yaml-cpp" "${_cece_yaml_cpp_provider}")
endif()

# HELM Ingestion (subdirectories added individually because HELM has no root CMakeLists)
if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/extern/helm/libs/tick/CMakeLists.txt")
  set(HELM_BUILD_TESTING_SAVE ${BUILD_TESTING})
  set(BUILD_TESTING OFF)

  add_subdirectory(extern/helm/libs/logs EXCLUDE_FROM_ALL)
  add_subdirectory(extern/helm/libs/tick EXCLUDE_FROM_ALL)
  add_subdirectory(extern/helm/libs/span EXCLUDE_FROM_ALL)
  add_subdirectory(extern/helm/libs/conf EXCLUDE_FROM_ALL)
  add_subdirectory(extern/helm/libs/halo EXCLUDE_FROM_ALL)
  add_subdirectory(extern/helm/libs/amio EXCLUDE_FROM_ALL)
  add_subdirectory(extern/helm/libs/axis EXCLUDE_FROM_ALL)
  add_subdirectory(extern/helm/libs/blend EXCLUDE_FROM_ALL)
  add_subdirectory(extern/helm/libs/dagr EXCLUDE_FROM_ALL)

  set(BUILD_TESTING ${HELM_BUILD_TESTING_SAVE})
else()
  message(
    FATAL_ERROR
    "HELM submodule not found at extern/helm. Please run 'git submodule update --init --recursive'"
  )
endif()

# ESMF and NUOPC support option (disabled by default)
option(ENABLE_ESMF "Enable ESMF and NUOPC support" OFF)

if(ENABLE_ESMF)
  find_package(ESMF)
  if(ESMF_FOUND)
    message(STATUS "Found ESMF: ${ESMF_VERSION}")
    message(STATUS "ESMF include dirs: ${ESMF_INCLUDE_DIRS}")
    cece_register_dep("ESMF" "system ${ESMF_VERSION}")
  endif()
else()
  set(ESMF_FOUND FALSE)
  message(STATUS "ESMF/NUOPC support is disabled (ENABLE_ESMF is OFF by default)")
endif()

# Find standard NetCDF: try CONFIG mode first, fallback to standard library discovery
find_package(netCDF CONFIG QUIET)

if(NOT netCDF_FOUND)
  message(STATUS "NetCDF Config file not found. Falling back to standard library discovery...")

  find_path(
    netCDF_INCLUDE_DIR
    NAMES netcdf.h
    PATHS
      ${NetCDF_ROOT}
      $ENV{NetCDF_ROOT}
      $ENV{NETCDF_ROOT}
      $ENV{NETCDF_DIR}
      $ENV{NetCDF_DIR}
      $ENV{NETCDF_C_ROOT}
      $ENV{NetCDF_C_ROOT}
    PATH_SUFFIXES include
  )
  find_library(
    netCDF_LIBRARY
    NAMES netcdf
    PATHS
      ${NetCDF_ROOT}
      $ENV{NetCDF_ROOT}
      $ENV{NETCDF_ROOT}
      $ENV{NETCDF_DIR}
      $ENV{NetCDF_DIR}
      $ENV{NETCDF_C_ROOT}
      $ENV{NetCDF_C_ROOT}
    PATH_SUFFIXES lib lib64
  )

  include(FindPackageHandleStandardArgs)
  find_package_handle_standard_args(netCDF DEFAULT_MSG netCDF_LIBRARY netCDF_INCLUDE_DIR)

  if(netCDF_FOUND)
    set(netCDF_INCLUDE_DIRS "${netCDF_INCLUDE_DIR}")
    set(netCDF_LIBRARIES "${netCDF_LIBRARY}")

    if(NOT TARGET netCDF::netcdf)
      add_library(netCDF::netcdf UNKNOWN IMPORTED GLOBAL)
      set_target_properties(
        netCDF::netcdf
        PROPERTIES
          IMPORTED_LOCATION "${netCDF_LIBRARY}"
          INTERFACE_INCLUDE_DIRECTORIES "${netCDF_INCLUDE_DIR}"
      )
    endif()

    cece_register_dep("NetCDF" "system library (${netCDF_LIBRARY})")
  else()
    message(
      FATAL_ERROR
      "Could not find NetCDF library or headers. Please set NetCDF_ROOT or NETCDF_ROOT."
    )
  endif()
else()
  if(NOT netCDF_INCLUDE_DIRS)
    set(netCDF_INCLUDE_DIRS "${netCDF_INCLUDE_DIR}")
  endif()
  cece_register_dep("NetCDF" "system package (${netCDF_DIR})")
endif()

# Discovery PIO and NetCDF from ESMF if possible
function(find_root_by_file root_var filename)
  if(NOT ${root_var})
    foreach(lib ${ESMF_LIBRARIES})
      if(lib MATCHES "^-L(.*)")
        set(search_path "${CMAKE_MATCH_1}")
        if(EXISTS "${search_path}/../include/${filename}")
          set(root "${search_path}/..")
          get_filename_component(root "${root}" ABSOLUTE)
          set(${root_var} "${root}" PARENT_SCOPE)
          message(STATUS "Found ${root_var} from ESMF path: ${root}")
          return()
        endif()
      endif()
    endforeach()
  endif()
endfunction()

find_root_by_file(NetCDF_ROOT "netcdf.h")
find_root_by_file(NetCDFF_ROOT "netcdf.mod")
find_root_by_file(PIO_ROOT "pio.h")

if(NetCDF_ROOT)
  set(NetCDF_FOUND TRUE)
  set(ENV{NetCDF_ROOT} "${NetCDF_ROOT}")
endif()
if(NetCDFF_ROOT)
  set(NetCDFF_FOUND TRUE)
  set(ENV{NetCDFF_ROOT} "${NetCDFF_ROOT}")
endif()
if(PIO_ROOT)
  set(PIO_FOUND TRUE)
  set(ENV{PIO_ROOT} "${PIO_ROOT}")
endif()

find_package(MPI REQUIRED)

# Container preflags for mpiexec/mpirun test launches, composed exactly once
# so every TEST_LAUNCHER and multi-rank add_test sees the same list.
# --allow-run-as-root exists for the container's root user and
# --oversubscribe for oversubscribed local/container CPUs — use-case flags,
# never needed on HPC compute nodes, and Intel MPI's hydra rejects
# --allow-run-as-root outright. Container entry points pass this ON;
# HPC/default configures stay clean.
option(
  CECE_MPIEXEC_CONTAINER_FLAGS
  "Append --allow-run-as-root/--oversubscribe to MPIEXEC_PREFLAGS for container/root/oversubscribed local runs (never needed on HPC)"
  OFF
)
if(CECE_MPIEXEC_CONTAINER_FLAGS)
  if(NOT "${MPIEXEC_PREFLAGS}" MATCHES "allow-run-as-root")
    list(APPEND MPIEXEC_PREFLAGS "--allow-run-as-root")
  endif()
  if(NOT "${MPIEXEC_PREFLAGS}" MATCHES "oversubscribe")
    list(APPEND MPIEXEC_PREFLAGS "--oversubscribe")
  endif()
endif()
message(STATUS "Found MPI: ${MPI_CXX_VERSION}")
cece_register_dep("MPI" "system (${MPI_CXX_COMPILER})")

# --- CECE Core Library ---

set(
  CECE_CORE_SRCS
  src/core/cece_band_decomposition.cpp
  src/core/cece_clock.cpp
  src/core/cece_config_parser.cpp
  src/core/cece_compute.cpp
  src/core/cece_stacking_engine.cpp
  src/core/cece_physics_factory.cpp
  src/core/cece_provenance.cpp
  src/core/physics/cece_native_example.cpp
  src/core/physics/cece_sea_salt.cpp
  src/core/physics/cece_megan.cpp
  src/core/physics/cece_dms.cpp
  src/core/physics/cece_lightning.cpp
  src/core/physics/cece_soil_nox.cpp
  src/core/physics/cece_dust.cpp
  src/core/physics/cece_fengsha.cpp
  src/core/physics/cece_ginoux.cpp
  src/core/physics/cece_k14.cpp
  src/core/physics/cece_volcano.cpp
  src/core/physics/cece_speciation_config.cpp
  src/core/physics/cece_speciation_engine.cpp
  src/core/physics/cece_canopy_model.cpp
  src/core/physics/cece_emission_activity.cpp
  src/core/physics/cece_megan3.cpp
  src/core/physics/cece_bdsnp.cpp
  src/core/cece_data_ingestor.cpp
  src/core/cece_diagnostic_manager.cpp
  src/core/cece_io.cpp
  src/core/cece_core_driver_config.cpp
  src/core/cece_core_advertise.cpp
  src/core/cece_core_realize.cpp
  src/core/cece_core_realize_wrapper.cpp
  src/core/cece_core_initialize_p1.cpp
  src/core/cece_core_initialize_p2.cpp
  src/core/cece_core_field_helpers.cpp
  src/core/cece_core_run.cpp
  src/core/cece_core_finalize.cpp
  src/core/cece_config_path.cpp
  src/core/cece_c_api.cpp
  src/core/cece_config_validator.cpp
  src/core/cece_run_info.cpp
)

if(CECE_HAS_FORTRAN)
  list(
    APPEND CECE_CORE_SRCS
    src/core/physics/cece_fortran_bridge.cpp
    src/core/physics/legacy_fortran.F90
    src/core/physics/cece_sea_salt_fortran_bridge.cpp
    src/core/physics/sea_salt_kernel.F90
    src/core/physics/cece_megan_fortran_bridge.cpp
    src/core/physics/megan_kernel.F90
    src/core/physics/cece_dms_fortran_bridge.cpp
    src/core/physics/dms_kernel.F90
    src/core/physics/cece_lightning_fortran_bridge.cpp
    src/core/physics/lightning_kernel.F90
    src/core/physics/cece_soil_nox_fortran_bridge.cpp
    src/core/physics/soil_nox_kernel.F90
    src/core/physics/cece_dust_fortran_bridge.cpp
    src/core/physics/dust_kernel.F90
    src/core/physics/cece_fengsha_fortran_bridge.cpp
    src/core/physics/fengsha_kernel.F90
    src/core/physics/cece_ginoux_fortran_bridge.cpp
    src/core/physics/ginoux_kernel.F90
    src/core/physics/cece_k14_fortran_bridge.cpp
    src/core/physics/k14_kernel.F90
    src/core/physics/cece_volcano_fortran_bridge.cpp
    src/core/physics/volcano_kernel.F90
    src/core/physics/cece_megan3_fortran_bridge.cpp
    src/core/physics/megan3_kernel.F90
    src/core/physics/cece_bdsnp_fortran_bridge.cpp
    src/core/physics/bdsnp_kernel.F90
    src/core/cece_ingestor_bridge.cpp
  )
endif()

add_library(cece_core SHARED ${CECE_CORE_SRCS})

if(CECE_HAS_FORTRAN)
  set_target_properties(
    cece_core
    PROPERTIES Fortran_MODULE_DIRECTORY ${CMAKE_BINARY_DIR}/fortran_modules/cece
  )
  target_include_directories(
    cece_core
    PUBLIC $<BUILD_INTERFACE:${CMAKE_BINARY_DIR}/fortran_modules/cece>
  )
  target_compile_definitions(cece_core PRIVATE CECE_HAS_FORTRAN)
endif()

target_include_directories(
  cece_core
  PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:include>
    ${ESMF_INCLUDE_DIRS}
)

# Suppress conflicting C++ MPI bindings pulled in via ESMF's ESMC.h -> mpi.h -> mpicxx.h
target_compile_definitions(cece_core PUBLIC MPICH_SKIP_MPICXX OMPI_SKIP_MPICXX)

if(ESMF_FOUND)
  target_link_libraries(cece_core PUBLIC Kokkos::kokkos ESMF::ESMF conf yaml-cpp)
else()
  target_link_libraries(cece_core PUBLIC Kokkos::kokkos conf yaml-cpp)
endif()

target_link_libraries(cece_core PUBLIC HELM::LOGS)

if(netCDF_FOUND)
  target_link_libraries(cece_core PUBLIC netCDF::netcdf)
  target_include_directories(cece_core PUBLIC ${netCDF_INCLUDE_DIRS})
endif()

if(CECE_HAS_FORTRAN AND NetCDFF_ROOT)
  target_include_directories(cece_core PRIVATE "${NetCDFF_ROOT}/include")
endif()

if(MPI_FOUND)
  target_link_libraries(cece_core PUBLIC MPI::MPI_CXX)
endif()

# Suppress conflicting C++ MPI bindings pulled in via ESMF's ESMC.h -> mpi.h -> mpicxx.h
target_compile_definitions(cece_core PUBLIC MPICH_SKIP_MPICXX OMPI_SKIP_MPICXX)

# --- cece_driver Library ---

add_library(
  cece_driver
  SHARED
  src/driver/cece_helm_graph.cpp
  src/driver/cece_regridder_utils.cpp
  src/driver/cece_standalone_writer.cpp
  src/driver/cece_core_writer_init.cpp
  src/driver/cece_amio_utils.cpp
  src/driver/cece_calendar.cpp
  src/driver/cece_time_indexing.cpp
  src/driver/cece_driver_facade.cpp
)

target_include_directories(
  cece_driver
  PUBLIC $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include> $<INSTALL_INTERFACE:include>
)

target_link_libraries(
  cece_driver
  PUBLIC cece_core amio_core HELM::SPAN blend axis HELM::DAGR HELM::HALO HELM::TICK conf
)

# --- Backward-Compatibility target aliases ---
add_library(cece INTERFACE)
target_link_libraries(cece INTERFACE cece_core cece_driver)

# --- Install Rules ---
install(
  TARGETS cece_core cece_driver
  LIBRARY DESTINATION lib
  ARCHIVE DESTINATION lib
  RUNTIME DESTINATION bin
)
install(DIRECTORY include/cece DESTINATION include)

# --- Tests ---

enable_testing()

if(POLICY CMP0178)
  # New behavior ignores TEST_LAUNCHER documentation about
  # semicolon-separated lists
  cmake_policy(SET CMP0178 OLD)
endif()

if(CECE_BUILD_TESTING)
  # GTest
  find_package(GTest QUIET)

  if(TARGET GTest::gtest AND TARGET GTest::gtest_main)
    cece_register_dep("GTest" "system (${GTest_DIR})")
  elseif(CECE_FETCH_DEPS)
    FetchContent_Declare(
      googletest
      GIT_REPOSITORY https://github.com/google/googletest.git
      GIT_TAG v1.15.2
    )
    set(gtest_force_shared_crt ON CACHE BOOL "" FORCE)
    FetchContent_MakeAvailable(googletest)
    cece_register_dep("GTest" "FetchContent (v1.15.2)")
  else()
    message(
      FATAL_ERROR
      "GTest not found via find_package() and CECE_FETCH_DEPS=OFF. Install GTest or configure with -DCECE_BUILD_TESTING=OFF."
    )
  endif()

  # RapidCheck (Property-Based Testing)
  find_package(rapidcheck CONFIG QUIET)

  if(TARGET rapidcheck)
    if(NOT TARGET rapidcheck_gtest)
      # Installed RapidCheck packages do not always export the header-only gtest
      # extra as its own target; the extras headers ship with the install.
      add_library(rapidcheck_gtest INTERFACE)
      target_link_libraries(rapidcheck_gtest INTERFACE rapidcheck)
    endif()
    cece_register_dep("RapidCheck" "system (${rapidcheck_DIR})")
  elseif(CECE_FETCH_DEPS)
    FetchContent_Declare(
      rapidcheck
      GIT_REPOSITORY https://github.com/emil-e/rapidcheck.git
      GIT_TAG b2d9ed2dddefc4b84318d664b4f221eb792d89c7
    )
    set(RC_ENABLE_GTEST ON CACHE BOOL "Enable RapidCheck GTest integration" FORCE)
    FetchContent_MakeAvailable(rapidcheck)
    cece_register_dep("RapidCheck" "FetchContent (pinned master)")
  else()
    message(
      FATAL_ERROR
      "RapidCheck not found via find_package() and CECE_FETCH_DEPS=OFF. Install RapidCheck or configure with -DCECE_BUILD_TESTING=OFF."
    )
  endif()

  # Shared main() + process-level MPI/HALO/Kokkos environment for the MPI test
  # executables (tests/support/). Link `cece_test_main` (or
  # `cece_test_main_kokkos` for Kokkos-only tests) in place of
  # GTest::gtest_main. A test file that needs its own global environment adds
  # it with CECE_TEST_ADD_ENVIRONMENT; it is registered after (so torn down
  # before) the MPI/Kokkos one. Initialization happens in Environment::SetUp,
  # which gtest skips for --gtest_list_tests, so test discovery never
  # initializes MPI or Kokkos and no per-file discovery guard is needed.
  add_library(cece_test_support STATIC tests/support/cece_test_environment.cpp)
  target_include_directories(cece_test_support PUBLIC tests)
  target_link_libraries(cece_test_support PUBLIC cece GTest::gtest)
  add_library(cece_test_main STATIC tests/support/cece_test_main.cpp)
  target_link_libraries(cece_test_main PUBLIC cece_test_support)
  # Kokkos-only variant: no MPI init, for tests that never touch MPI and
  # therefore carry no MPI TEST_LAUNCHER.
  add_library(cece_test_main_kokkos STATIC tests/support/cece_test_main_kokkos.cpp)
  target_link_libraries(cece_test_main_kokkos PUBLIC cece_test_support)

  add_executable(test_driver_configuration tests/test_driver_configuration.cpp)
  target_link_libraries(test_driver_configuration PRIVATE cece GTest::gtest_main)

  if(ESMF_FOUND)
    add_executable(test_driver_config_validation tests/test_driver_config_validation.cpp)
    target_link_libraries(
      test_driver_config_validation
      PRIVATE cece iso8601_utils GTest::gtest_main
    )
    set_target_properties(
      test_driver_config_validation
      PROPERTIES TEST_LAUNCHER "${MPIEXEC_EXECUTABLE};${MPIEXEC_NUMPROC_FLAG};1;${MPIEXEC_PREFLAGS}"
    )
  endif()

  add_executable(test_driver_clock_management tests/test_driver_clock_management.cpp)
  target_link_libraries(test_driver_clock_management PRIVATE GTest::gtest_main)

  add_executable(test_clock_operations_unit tests/test_clock_operations_unit.cpp)
  target_link_libraries(test_clock_operations_unit PRIVATE GTest::gtest_main)

  add_executable(test_driver_integration_end_to_end tests/test_driver_integration_end_to_end.cpp)
  target_link_libraries(test_driver_integration_end_to_end PRIVATE GTest::gtest_main)

  if(ESMF_FOUND)
    add_executable(test_cece_cap tests/test_cece_cap.cpp)
    target_link_libraries(test_cece_cap PRIVATE cece GTest::gtest_main)

    add_executable(test_diagnostics tests/test_diagnostics.cpp)
    target_link_libraries(test_diagnostics PRIVATE cece cece_test_main_kokkos)
  endif()

  add_executable(test_cece_ingestor tests/test_cece_ingestor.cpp)
  target_link_libraries(test_cece_ingestor PRIVATE cece GTest::gtest_main)

  add_executable(test_cece_utils tests/test_cece_utils.cpp)
  target_link_libraries(test_cece_utils PRIVATE cece cece_test_main)
  set_target_properties(
    test_cece_utils
    PROPERTIES TEST_LAUNCHER "${MPIEXEC_EXECUTABLE};${MPIEXEC_NUMPROC_FLAG};1;${MPIEXEC_PREFLAGS}"
  )

  add_executable(test_numerical_equivalence tests/test_numerical_equivalence.cpp)
  target_link_libraries(test_numerical_equivalence PRIVATE cece GTest::gtest_main)
  set_target_properties(
    test_numerical_equivalence
    PROPERTIES TEST_LAUNCHER "${MPIEXEC_EXECUTABLE};${MPIEXEC_NUMPROC_FLAG};1;${MPIEXEC_PREFLAGS}"
  )

  add_executable(test_cece_compute tests/test_cece_compute.cpp)
  target_link_libraries(test_cece_compute PRIVATE cece GTest::gtest_main)

  add_executable(test_standalone_writer_attributes tests/test_standalone_writer_attributes.cpp)
  target_link_libraries(test_standalone_writer_attributes PRIVATE cece cece_test_main)
  set_target_properties(
    test_standalone_writer_attributes
    PROPERTIES TEST_LAUNCHER "${MPIEXEC_EXECUTABLE};${MPIEXEC_NUMPROC_FLAG};1;${MPIEXEC_PREFLAGS}"
  )

  # Ensure tests are run under MPI
  set_target_properties(
    test_standalone_writer_attributes
    test_cece_utils
    PROPERTIES TEST_LAUNCHER "${MPIEXEC_EXECUTABLE};${MPIEXEC_NUMPROC_FLAG};1;${MPIEXEC_PREFLAGS}"
  )

  add_executable(test_physics tests/test_physics.cpp)
  target_link_libraries(test_physics PRIVATE cece GTest::gtest_main)

  add_executable(test_hemco_mimic tests/test_hemco_mimic.cpp)
  target_link_libraries(test_hemco_mimic PRIVATE cece GTest::gtest_main)

  add_executable(test_stacking_engine tests/test_stacking_engine.cpp)
  target_link_libraries(test_stacking_engine PRIVATE cece GTest::gtest_main)

  add_executable(test_vertical_distribution_single tests/test_vertical_distribution_single.cpp)
  target_link_libraries(test_vertical_distribution_single PRIVATE cece GTest::gtest_main)

  add_executable(test_field_resolution_priority tests/test_field_resolution_priority.cpp)
  target_link_libraries(test_field_resolution_priority PRIVATE cece GTest::gtest_main)

  add_executable(test_ingest_setfield_bypass tests/test_ingest_setfield_bypass.cpp)
  target_link_libraries(test_ingest_setfield_bypass PRIVATE cece GTest::gtest_main)

  add_executable(test_ingest_copyback_neutralized tests/test_ingest_copyback_neutralized.cpp)
  target_link_libraries(test_ingest_copyback_neutralized PRIVATE cece GTest::gtest_main)

  if(CECE_HAS_FORTRAN AND ESMF_FOUND)
    add_library(test_helpers STATIC tests/test_helpers.F90)
    target_include_directories(test_helpers PUBLIC ${ESMF_INCLUDE_DIRS})
    target_link_libraries(test_helpers PUBLIC ESMF::ESMF)
    set_target_properties(
      test_helpers
      PROPERTIES TEST_LAUNCHER "${MPIEXEC_EXECUTABLE};${MPIEXEC_NUMPROC_FLAG};1;${MPIEXEC_PREFLAGS}"
    )
    if(MPI_FOUND)
      target_link_libraries(test_helpers PUBLIC MPI::MPI_CXX)
    endif()
  endif()

  add_executable(hemco_comparison_driver tests/hemco_comparison_driver.cpp)
  target_link_libraries(hemco_comparison_driver PRIVATE cece)
  add_test(NAME test_hemco_comparison COMMAND hemco_comparison_driver)

  add_executable(benchmark_cece_hemco tests/benchmark_cece_hemco.cpp)
  target_link_libraries(benchmark_cece_hemco PRIVATE cece)

  # Before/after ingest/assembly micro-benchmark (ingest-copy-consolidation, Task 1.1)
  add_executable(benchmark_ingest_copy_consolidation tests/benchmark_ingest_copy_consolidation.cpp)
  target_link_libraries(benchmark_ingest_copy_consolidation PRIVATE cece)

  # Standalone ex5-shaped end-to-end per-step ingest/assembly benchmark (F360)
  add_executable(benchmark_ex5_end_to_end tests/benchmark_ex5_end_to_end.cpp)
  target_link_libraries(benchmark_ex5_end_to_end PRIVATE cece)

  # Standalone regrid APPLY hot-loop micro-benchmark (driver-io-regrid-perf)
  add_executable(benchmark_regrid_apply tests/benchmark_regrid_apply.cpp)
  target_link_libraries(benchmark_regrid_apply PRIVATE cece)

  # Standalone develop-vs-optimize per-step pipeline benchmark (regrid+assemble+ingest).
  # Its DEVELOP path constructs a KokkosSparse::CrsMatrix directly; KokkosKernels is
  # now a hard AXIS dependency (found or fetched), so this always builds and the
  # KokkosSparse headers are always on the include path via the cece->axis link.
  add_executable(
    benchmark_pipeline_develop_vs_optimize
    tests/benchmark_pipeline_develop_vs_optimize.cpp
  )
  target_link_libraries(benchmark_pipeline_develop_vs_optimize PRIVATE cece)

  # Standalone MPI develop-vs-optimize distributed gather/assembly timing harness.
  # MPI-main pattern (own main() with MPI + Kokkos init; does NOT link
  # GTest::gtest_main). Runnable single-process AND under mpirun --oversubscribe
  # -np {1,2,4}. Reports actual MPI wall-time per assembly for the per-level
  # MPI_Allgatherv (develop) vs the single cached gather_replicated (optimize).
  add_executable(
    benchmark_mpi_pipeline
    tests/benchmark_mpi_pipeline.cpp
    tools/pmpi_allgatherv_timer.cpp
  )
  target_link_libraries(benchmark_mpi_pipeline PRIVATE cece HELM::HALO MPI::MPI_CXX Kokkos::kokkos)

  add_executable(test_hemco_parity tests/test_hemco_parity.cpp)
  target_link_libraries(test_hemco_parity PRIVATE cece GTest::gtest_main)

  # Kokkos Configuration Tests (Requirement 6.13-6.18, 6.21)
  add_executable(test_kokkos_configuration tests/test_kokkos_configuration.cpp)
  target_link_libraries(test_kokkos_configuration PRIVATE cece cece_test_main_kokkos)

  # Comprehensive Property-Based Test Suite (Task 11.1)
  add_executable(test_properties tests/test_properties.cpp)
  target_link_libraries(test_properties PRIVATE cece cece_test_main_kokkos)

  # Test Suite Idempotence (Requirement 8.16)
  add_executable(test_suite_idempotence tests/test_suite_idempotence.cpp)
  target_link_libraries(test_suite_idempotence PRIVATE cece GTest::gtest_main)

  # Temporary Reproduction Test
  add_executable(test_repro_failure tests/repro_failure.cpp)
  target_link_libraries(test_repro_failure PRIVATE cece GTest::gtest_main)

  # CCPP Readiness and Core Link Isolation Test
  add_executable(test_ccpp_readiness tests/test_ccpp_readiness.cpp)
  target_link_libraries(test_ccpp_readiness PRIVATE cece_core GTest::gtest_main)
  target_compile_definitions(
    test_ccpp_readiness
    PRIVATE CECE_SOURCE_DIR="${CMAKE_CURRENT_SOURCE_DIR}"
  )

  # Unit tests for field creation (Requirement R4) FENGSHA Dust Scheme Property
  # Tests
  add_executable(test_fengsha_properties tests/test_fengsha_properties.cpp)
  target_link_libraries(test_fengsha_properties PRIVATE cece GTest::gtest_main)

  # Ginoux (GOCART2G) Dust Scheme Property Tests
  add_executable(test_ginoux_properties tests/test_ginoux_properties.cpp)
  target_link_libraries(test_ginoux_properties PRIVATE cece GTest::gtest_main)

  # K14 Dust Scheme Property Tests
  add_executable(test_k14_properties tests/test_k14_properties.cpp)
  target_link_libraries(test_k14_properties PRIVATE cece GTest::gtest_main)

  # Speciation Config Property Tests (MEGAN3)
  add_executable(test_speciation tests/test_speciation.cpp)
  target_link_libraries(
    test_speciation
    PRIVATE cece cece_test_main_kokkos rapidcheck rapidcheck_gtest
  )
  target_compile_definitions(test_speciation PRIVATE CECE_SOURCE_DIR="${CMAKE_CURRENT_SOURCE_DIR}")

  # CeceClock Property Tests
  add_executable(test_cece_clock_properties tests/test_cece_clock_properties.cpp)
  target_link_libraries(
    test_cece_clock_properties
    PRIVATE cece GTest::gtest_main rapidcheck rapidcheck_gtest
  )

  # Data Stream Time Indexing Unit Tests
  add_executable(test_cece_time_indexing tests/test_cece_time_indexing.cpp)
  target_link_libraries(test_cece_time_indexing PRIVATE cece GTest::gtest_main)
  if(UNIX AND NOT APPLE)
    # This test only references cece_driver, so --as-needed drops libcece_core from DT_NEEDED;
    # Kokkos statics are duplicated in both libraries and double-free at teardown when it does.
    target_link_options(test_cece_time_indexing PRIVATE "LINKER:--no-as-needed")
  endif()

  # CF Time-Units Decoding Unit Tests
  add_executable(test_cece_calendar tests/test_cece_calendar.cpp)
  target_link_libraries(test_cece_calendar PRIVATE cece GTest::gtest_main)
  if(UNIX AND NOT APPLE)
    target_link_options(test_cece_calendar PRIVATE "LINKER:--no-as-needed")
  endif()

  # AMIO View Widening Unit Tests
  add_executable(test_cece_amio_utils tests/test_cece_amio_utils.cpp)
  target_link_libraries(test_cece_amio_utils PRIVATE cece GTest::gtest_main)
  if(UNIX AND NOT APPLE)
    target_link_options(test_cece_amio_utils PRIVATE "LINKER:--no-as-needed")
  endif()

  # Time Axis Integration Tests (real NetCDF fixtures read through AMIO).
  # Provides its own main() for MPI init, so it links GTest::gtest rather than gtest_main.
  add_executable(test_cece_time_axis_netcdf tests/test_cece_time_axis_netcdf.cpp)
  target_link_libraries(test_cece_time_axis_netcdf PRIVATE cece GTest::gtest)
  if(UNIX AND NOT APPLE)
    target_link_options(test_cece_time_axis_netcdf PRIVATE "LINKER:--no-as-needed")
  endif()
  set_target_properties(
    test_cece_time_axis_netcdf
    PROPERTIES TEST_LAUNCHER "${MPIEXEC_EXECUTABLE};${MPIEXEC_NUMPROC_FLAG};1;${MPIEXEC_PREFLAGS}"
  )

  # CeceClock Run Loop Unit Tests
  add_executable(test_cece_clock_run_loop tests/test_cece_clock_run_loop.cpp)
  target_link_libraries(test_cece_clock_run_loop PRIVATE cece cece_test_main_kokkos)

  # Bracket-equality Property Tests (driver-io-regrid-perf, Property 5)
  add_executable(test_bracket_equal_properties tests/test_bracket_equal_properties.cpp)
  target_link_libraries(
    test_bracket_equal_properties
    PRIVATE cece GTest::gtest_main rapidcheck rapidcheck_gtest
  )

  add_executable(test_band_decomposition_partition tests/test_band_decomposition_partition.cpp)
  target_link_libraries(
    test_band_decomposition_partition
    PRIVATE cece GTest::gtest_main rapidcheck rapidcheck_gtest
  )

  add_executable(test_band_single_rank_properties tests/test_band_single_rank_properties.cpp)
  target_link_libraries(
    test_band_single_rank_properties
    PRIVATE cece MPI::MPI_CXX rapidcheck rapidcheck_gtest GTest::gtest
  )
  set_target_properties(
    test_band_single_rank_properties
    PROPERTIES TEST_LAUNCHER "${MPIEXEC_EXECUTABLE};${MPIEXEC_NUMPROC_FLAG};1;${MPIEXEC_PREFLAGS}"
  )

  add_executable(test_band_regrid_equals_global_rows tests/test_band_regrid_equals_global_rows.cpp)
  target_link_libraries(
    test_band_regrid_equals_global_rows
    PRIVATE cece GTest::gtest_main rapidcheck rapidcheck_gtest
  )
  set_target_properties(
    test_band_regrid_equals_global_rows
    PROPERTIES TEST_LAUNCHER "${MPIEXEC_EXECUTABLE};${MPIEXEC_NUMPROC_FLAG};1;${MPIEXEC_PREFLAGS}"
  )

  # StreamKey Property Tests (regrid-per-stream, Property 1)
  add_executable(test_stream_key_properties tests/test_stream_key_properties.cpp)
  target_link_libraries(
    test_stream_key_properties
    PRIVATE cece GTest::gtest_main rapidcheck rapidcheck_gtest
  )

  # HandleKey Property Tests (regrid-per-stream, Amendment 1, Property 4)
  add_executable(test_handle_key_properties tests/test_handle_key_properties.cpp)
  target_link_libraries(
    test_handle_key_properties
    PRIVATE cece GTest::gtest_main rapidcheck rapidcheck_gtest
  )

  # StreamKey-extends-HandleKey Property Tests (regrid-per-stream, Amendment 1, Property 5)
  add_executable(test_stream_key_extends_handle_key tests/test_stream_key_extends_handle_key.cpp)
  target_link_libraries(
    test_stream_key_extends_handle_key
    PRIVATE cece GTest::gtest_main rapidcheck rapidcheck_gtest
  )

  # StreamConfig Resolution Property Tests (driver-io-regrid-perf, Property 4)
  add_executable(test_stream_config_resolution tests/test_stream_config_resolution.cpp)
  target_link_libraries(
    test_stream_config_resolution
    PRIVATE cece GTest::gtest_main rapidcheck rapidcheck_gtest
  )
  target_compile_definitions(
    test_stream_config_resolution
    PRIVATE CECE_SOURCE_DIR="${CMAKE_CURRENT_SOURCE_DIR}"
  )

  # No-manifest / No-reparse Regression Guards (driver-io-regrid-perf, Task 13.2)
  add_executable(test_no_manifest_no_reparse tests/test_no_manifest_no_reparse.cpp)
  target_link_libraries(test_no_manifest_no_reparse PRIVATE cece GTest::gtest_main)
  target_compile_definitions(
    test_no_manifest_no_reparse
    PRIVATE CECE_SOURCE_DIR="${CMAKE_CURRENT_SOURCE_DIR}"
  )

  # Slice-cache Equivalence Property Tests (driver-io-regrid-perf, Property 6)
  add_executable(test_slice_cache_equivalence tests/test_slice_cache_equivalence.cpp)
  target_link_libraries(
    test_slice_cache_equivalence
    PRIVATE cece GTest::gtest_main rapidcheck rapidcheck_gtest
  )

  # Slice-cache Independence Property Tests (regrid-per-stream, Property 3)
  add_executable(test_slice_cache_independence tests/test_slice_cache_independence.cpp)
  target_link_libraries(
    test_slice_cache_independence
    PRIVATE cece GTest::gtest_main rapidcheck rapidcheck_gtest
  )

  # Open-once / no-per-step-close Tests (driver-io-regrid-perf, Task 13.1, Req 9.1)
  add_executable(test_open_once_no_per_step_close tests/test_open_once_no_per_step_close.cpp)
  target_link_libraries(
    test_open_once_no_per_step_close
    PRIVATE cece GTest::gtest_main rapidcheck rapidcheck_gtest
  )
  target_compile_definitions(
    test_open_once_no_per_step_close
    PRIVATE CECE_SOURCE_DIR="${CMAKE_CURRENT_SOURCE_DIR}"
  )

  # Cache-hit Skips-work Property Tests (driver-io-regrid-perf, Task 13.3, Req 9.4)
  add_executable(test_cache_hit_skips_work tests/test_cache_hit_skips_work.cpp)
  target_link_libraries(
    test_cache_hit_skips_work
    PRIVATE cece GTest::gtest_main rapidcheck rapidcheck_gtest
  )

  # Endpoint-blend Equivalence Property Tests (temporal-endpoint-regrid-cache,
  # Property 1). Uses apply_regrid_plan + AXIS weight generation (Kokkos), so it
  # provides its own main() that initializes Kokkos/MPI (see the file's
  # KokkosMpiEnvironment), matching the test_numerical_equivalence pattern.
  add_executable(test_endpoint_blend_equivalence tests/test_endpoint_blend_equivalence.cpp)
  target_link_libraries(
    test_endpoint_blend_equivalence
    PRIVATE cece GTest::gtest_main rapidcheck rapidcheck_gtest
  )
  set_target_properties(
    test_endpoint_blend_equivalence
    PROPERTIES TEST_LAUNCHER "${MPIEXEC_EXECUTABLE};${MPIEXEC_NUMPROC_FLAG};1;${MPIEXEC_PREFLAGS}"
  )

  # Endpoint Work-reduction Property Tests (temporal-endpoint-regrid-cache,
  # Property 2). Reproduces the Tier ladder with a WorkSpy counting read_slab /
  # regrid-front invocations via the real bracket_equal; no Kokkos/MPI needed, so
  # it uses the shared GTest::gtest_main like the test_cache_hit_skips_work sibling.
  add_executable(test_endpoint_work_reduction tests/test_endpoint_work_reduction.cpp)
  target_link_libraries(
    test_endpoint_work_reduction
    PRIVATE cece GTest::gtest_main rapidcheck rapidcheck_gtest
  )

  # Endpoint per-variable Shared-plan Correctness Property Tests
  # (temporal-endpoint-regrid-cache, Property 5). Uses apply_regrid_plan + AXIS
  # weight generation (Kokkos), so it provides its own main() that initializes
  # Kokkos/MPI (see the file's KokkosMpiEnvironment), matching the
  # test_numerical_equivalence / test_endpoint_blend_equivalence pattern.
  add_executable(test_endpoint_shared_plan tests/test_endpoint_shared_plan.cpp)
  target_link_libraries(
    test_endpoint_shared_plan
    PRIVATE cece GTest::gtest_main rapidcheck rapidcheck_gtest
  )
  set_target_properties(
    test_endpoint_shared_plan
    PROPERTIES TEST_LAUNCHER "${MPIEXEC_EXECUTABLE};${MPIEXEC_NUMPROC_FLAG};1;${MPIEXEC_PREFLAGS}"
  )

  # Endpoint Tier-precedence Property Tests (temporal-endpoint-regrid-cache,
  # Property 3, Task 9.1, Req 2.4/6.1/6.5/9.3). Pure decision-ladder property test
  # over the real RecordBracket/SliceCacheEntry/EndpointCacheEntry types and the
  # real bracket_equal; no Kokkos/regrid math, so it uses GTest::gtest_main like
  # the test_cache_hit_skips_work / test_endpoint_work_reduction siblings.
  add_executable(test_endpoint_tier_precedence tests/test_endpoint_tier_precedence.cpp)
  target_link_libraries(
    test_endpoint_tier_precedence
    PRIVATE cece GTest::gtest_main rapidcheck rapidcheck_gtest
  )

  # Endpoint Sizing and Tier-3 Population Unit/Example Tests
  # (temporal-endpoint-regrid-cache, Task 12.1, Req 1.1/1.3/2.5/8.1). Example-based
  # GTest companions to the endpoint property tests: assert each Endpoint_Field is
  # sized field_nlev*nx*ny, that a Tier-3 compute populates the endpoint entry, and
  # that the single-record path builds no endpoint entry. Reproduces the Tier ladder
  # over the real RecordBracket/SliceCacheEntry/EndpointCacheEntry types and the real
  # bracket_equal. Linking cece pulls in Kokkos/AXIS static globals, so it provides
  # its own main() with a KokkosMpiEnvironment (matching test_endpoint_blend_equivalence
  # / test_numerical_equivalence) for clean process teardown.
  add_executable(test_endpoint_sizing tests/test_endpoint_sizing.cpp)
  target_link_libraries(
    test_endpoint_sizing
    PRIVATE cece GTest::gtest_main MPI::MPI_CXX Kokkos::kokkos
  )
  set_target_properties(
    test_endpoint_sizing
    PROPERTIES TEST_LAUNCHER "${MPIEXEC_EXECUTABLE};${MPIEXEC_NUMPROC_FLAG};1;${MPIEXEC_PREFLAGS}"
  )

  # Endpoint Invalidation and Failure unit/example tests
  # (temporal-endpoint-regrid-cache, Task 12.2). Example-based companions asserting
  # that rollover forces a rebuild, a plan (re)build invalidates dependent entries,
  # a shape change forces a miss, TeardownHandles clears endpoint_caches_, and an
  # injected endpoint-compute failure marks the entry invalid and sets
  # failure_detail. Reproduces the Tier ladder over the real
  # RecordBracket/SliceCacheEntry/EndpointCacheEntry types and the real
  # bracket_equal. Linking cece pulls in Kokkos/AXIS static globals, so it provides
  # its own main() with a KokkosMpiEnvironment (matching test_endpoint_sizing
  # / test_endpoint_blend_equivalence) for clean process teardown.
  add_executable(test_endpoint_invalidation tests/test_endpoint_invalidation.cpp)
  target_link_libraries(
    test_endpoint_invalidation
    PRIVATE cece GTest::gtest_main MPI::MPI_CXX Kokkos::kokkos
  )
  set_target_properties(
    test_endpoint_invalidation
    PROPERTIES TEST_LAUNCHER "${MPIEXEC_EXECUTABLE};${MPIEXEC_NUMPROC_FLAG};1;${MPIEXEC_PREFLAGS}"
  )

  # Regrid Conservation Property Tests (driver-io-regrid-perf, Property 9)
  add_executable(test_regrid_conservation_properties tests/test_regrid_conservation_properties.cpp)
  target_link_libraries(
    test_regrid_conservation_properties
    PRIVATE cece GTest::gtest_main rapidcheck rapidcheck_gtest
  )
  set_target_properties(
    test_regrid_conservation_properties
    PROPERTIES TEST_LAUNCHER "${MPIEXEC_EXECUTABLE};${MPIEXEC_NUMPROC_FLAG};1;${MPIEXEC_PREFLAGS}"
  )

  # Shared-plan Equivalence Property Tests (regrid-per-stream, Property 2)
  add_executable(test_shared_plan_equivalence tests/test_shared_plan_equivalence.cpp)
  target_link_libraries(
    test_shared_plan_equivalence
    PRIVATE cece GTest::gtest_main rapidcheck rapidcheck_gtest
  )
  set_target_properties(
    test_shared_plan_equivalence
    PROPERTIES TEST_LAUNCHER "${MPIEXEC_EXECUTABLE};${MPIEXEC_NUMPROC_FLAG};1;${MPIEXEC_PREFLAGS}"
  )

  # No-stale-data Property Tests (ingest-copy-consolidation, Property 4)
  add_executable(test_ingest_no_stale_data tests/test_ingest_no_stale_data.cpp)
  target_link_libraries(
    test_ingest_no_stale_data
    PRIVATE cece GTest::gtest_main rapidcheck rapidcheck_gtest
  )

  # Ingest Consolidation Equivalence Property Tests (ingest-copy-consolidation,
  # Property 1). Uses Kokkos DualView3D + deep_copy, so it provides its own main()
  # that initializes Kokkos/MPI (see the file's KokkosMpiEnvironment), matching
  # the test_regrid_conservation_properties pattern.
  add_executable(
    test_ingest_consolidation_equivalence
    tests/test_ingest_consolidation_equivalence.cpp
  )
  target_link_libraries(
    test_ingest_consolidation_equivalence
    PRIVATE cece GTest::gtest_main rapidcheck rapidcheck_gtest
  )
  set_target_properties(
    test_ingest_consolidation_equivalence
    PROPERTIES TEST_LAUNCHER "${MPIEXEC_EXECUTABLE};${MPIEXEC_NUMPROC_FLAG};1;${MPIEXEC_PREFLAGS}"
  )

  # MPI Collective Gate Order Property Tests (ingest-copy-consolidation, Property 3)
  add_executable(test_ingest_collective_gate_order tests/test_ingest_collective_gate_order.cpp)
  target_link_libraries(
    test_ingest_collective_gate_order
    PRIVATE cece GTest::gtest_main rapidcheck rapidcheck_gtest
  )

  # Ingest single-write Property Tests (ingest-copy-consolidation, Property 2)
  add_executable(test_ingest_single_write tests/test_ingest_single_write.cpp)
  target_link_libraries(
    test_ingest_single_write
    PRIVATE cece GTest::gtest_main rapidcheck rapidcheck_gtest
  )
  set_target_properties(
    test_ingest_single_write
    PROPERTIES TEST_LAUNCHER "${MPIEXEC_EXECUTABLE};${MPIEXEC_NUMPROC_FLAG};1;${MPIEXEC_PREFLAGS}"
  )

  # MPI cross-rank reuse-decision integration test (driver-io-regrid-perf,
  # Property 8, Task 12.3). Provides its own main() with MPI init, so it does NOT
  # link GTest::gtest_main. Runnable as a single process AND under mpirun -np 2/4.
  add_executable(test_mpi_reuse_decision tests/test_mpi_reuse_decision.cpp)
  target_link_libraries(test_mpi_reuse_decision PRIVATE cece GTest::gtest MPI::MPI_CXX)
  set_target_properties(
    test_mpi_reuse_decision
    PROPERTIES TEST_LAUNCHER "${MPIEXEC_EXECUTABLE};${MPIEXEC_NUMPROC_FLAG};1;${MPIEXEC_PREFLAGS}"
  )
  # Single-process registration (ctest default): runs the binary directly so the
  # rank-invariance property is validated structurally even without a launcher.
  add_test(NAME test_mpi_reuse_decision_np1 COMMAND test_mpi_reuse_decision)
  set_tests_properties(
    test_mpi_reuse_decision_np1
    PROPERTIES ENVIRONMENT "FI_PROVIDER=tcp;I_MPI_FABRICS=shm"
  )
  # Multi-rank registration under mpirun. MPIEXEC_* come from find_package(MPI)
  # (called earlier in this file). Container preflags come from the
  # CECE_MPIEXEC_CONTAINER_FLAGS option near find_package(MPI).
  add_test(
    NAME test_mpi_reuse_decision_np2
    COMMAND
      ${MPIEXEC_EXECUTABLE} ${MPIEXEC_NUMPROC_FLAG} 2 ${MPIEXEC_PREFLAGS}
      $<TARGET_FILE:test_mpi_reuse_decision> ${MPIEXEC_POSTFLAGS}
  )
  set_tests_properties(
    test_mpi_reuse_decision_np2
    PROPERTIES
      ENVIRONMENT
        "FI_PROVIDER=tcp;I_MPI_FABRICS=shm;OMPI_ALLOW_RUN_AS_ROOT=1;OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1"
  )

  # Endpoint reuse-decision rank-invariance property test
  # (temporal-endpoint-regrid-cache, Property 4, Task 10.1). Mirrors
  # test_mpi_reuse_decision: provides its own main() with MPI init (so it does NOT
  # link GTest::gtest_main) and is runnable as a single process AND under
  # mpirun -np 2. Uses RapidCheck for the weight-independence / rank-invariance
  # property, so it also links rapidcheck + rapidcheck_gtest.
  add_executable(test_endpoint_reuse_decision tests/test_endpoint_reuse_decision.cpp)
  target_link_libraries(
    test_endpoint_reuse_decision
    PRIVATE cece GTest::gtest MPI::MPI_CXX rapidcheck rapidcheck_gtest
  )
  set_target_properties(
    test_endpoint_reuse_decision
    PROPERTIES TEST_LAUNCHER "${MPIEXEC_EXECUTABLE};${MPIEXEC_NUMPROC_FLAG};1;${MPIEXEC_PREFLAGS}"
  )
  # Single-process registration (ctest default): runs the binary directly so the
  # rank-invariance property is validated structurally even without a launcher.
  add_test(NAME test_endpoint_reuse_decision_np1 COMMAND test_endpoint_reuse_decision)
  set_tests_properties(
    test_endpoint_reuse_decision_np1
    PROPERTIES ENVIRONMENT "FI_PROVIDER=tcp;I_MPI_FABRICS=shm"
  )
  # Multi-rank registration under mpirun. Container preflags
  # (--allow-run-as-root/--oversubscribe) come from the
  # CECE_MPIEXEC_CONTAINER_FLAGS option near find_package(MPI).
  add_test(
    NAME test_endpoint_reuse_decision_np2
    COMMAND
      ${MPIEXEC_EXECUTABLE} ${MPIEXEC_NUMPROC_FLAG} 2 ${MPIEXEC_PREFLAGS}
      $<TARGET_FILE:test_endpoint_reuse_decision> ${MPIEXEC_POSTFLAGS}
  )
  set_tests_properties(
    test_endpoint_reuse_decision_np2
    PROPERTIES
      ENVIRONMENT
        "FI_PROVIDER=tcp;I_MPI_FABRICS=shm;OMPI_ALLOW_RUN_AS_ROOT=1;OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1"
  )

  # Fused front-half gate-equivalence property test
  # (cece-halo-collective-adoption, Property 4, Task 10.3). Drives the REAL pure
  # static CeceDriverOrchestrator::FusedGateDecision (reached via the
  # CollectiveGateTestAccess friend shim) with generated (mn, mx) vectors and
  # asserts it equals the conjunction of the five separate legacy gates and their
  # failure_detail under the legacy precedence; plus an end-to-end packing case
  # exercising the REAL fused halo::allreduce<int>(MIN)/(MAX) over a
  # halo::Communicator. Provides its own main() with MPI init (so it does NOT link
  # GTest::gtest_main) and is runnable as a single process AND under
  # mpirun -np 2 / -np 4. Uses RapidCheck (>=100 iterations) so it links
  # rapidcheck + rapidcheck_gtest, and HELM::HALO for the fused collective.
  add_executable(test_fused_gate_equivalence tests/test_fused_gate_equivalence.cpp)
  target_link_libraries(
    test_fused_gate_equivalence
    PRIVATE cece GTest::gtest MPI::MPI_CXX HELM::HALO rapidcheck rapidcheck_gtest
  )
  set_target_properties(
    test_fused_gate_equivalence
    PROPERTIES TEST_LAUNCHER "${MPIEXEC_EXECUTABLE};${MPIEXEC_NUMPROC_FLAG};1;${MPIEXEC_PREFLAGS}"
  )
  # Single-process registration (ctest default): runs the binary directly so the
  # pure-decision properties and the (identity-reduction) packing case validate
  # structurally even without a launcher.
  add_test(NAME test_fused_gate_equivalence_np1 COMMAND test_fused_gate_equivalence)
  set_tests_properties(
    test_fused_gate_equivalence_np1
    PROPERTIES ENVIRONMENT "FI_PROVIDER=tcp;I_MPI_FABRICS=shm"
  )
  # Multi-rank registration under mpirun. Container preflags
  # (--allow-run-as-root/--oversubscribe) come from the
  # CECE_MPIEXEC_CONTAINER_FLAGS option near find_package(MPI).
  add_test(
    NAME test_fused_gate_equivalence_np2
    COMMAND
      ${MPIEXEC_EXECUTABLE} ${MPIEXEC_NUMPROC_FLAG} 2 ${MPIEXEC_PREFLAGS}
      $<TARGET_FILE:test_fused_gate_equivalence> ${MPIEXEC_POSTFLAGS}
  )
  set_tests_properties(
    test_fused_gate_equivalence_np2
    PROPERTIES
      ENVIRONMENT
        "FI_PROVIDER=tcp;I_MPI_FABRICS=shm;OMPI_ALLOW_RUN_AS_ROOT=1;OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1"
  )
  add_test(
    NAME test_fused_gate_equivalence_np4
    COMMAND
      ${MPIEXEC_EXECUTABLE} ${MPIEXEC_NUMPROC_FLAG} 4 ${MPIEXEC_PREFLAGS}
      $<TARGET_FILE:test_fused_gate_equivalence> ${MPIEXEC_POSTFLAGS}
  )
  set_tests_properties(
    test_fused_gate_equivalence_np4
    PROPERTIES
      ENVIRONMENT
        "FI_PROVIDER=tcp;I_MPI_FABRICS=shm;OMPI_ALLOW_RUN_AS_ROOT=1;OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1"
  )

  # Collective-count independence Property Test (cece-halo-collective-adoption,
  # Property 5, Task 10.4). PMPI-style spy counts MPI_Allgatherv/MPI_Allreduce and
  # proves the single-gather assembly issues exactly one Allgatherv and a total
  # collective count independent of field_nlev, with a fixed front-gate reduction
  # count of 2. Provides its own main() with MPI + Kokkos init (so it does NOT link
  # GTest::gtest_main); uses RapidCheck; links HELM::HALO and Kokkos. Runnable as a
  # single process AND under mpirun --oversubscribe -np 2.
  add_executable(test_collective_count tests/test_collective_count.cpp)
  target_link_libraries(
    test_collective_count
    PRIVATE cece HELM::HALO MPI::MPI_CXX Kokkos::kokkos GTest::gtest rapidcheck rapidcheck_gtest
  )
  set_target_properties(
    test_collective_count
    PROPERTIES TEST_LAUNCHER "${MPIEXEC_EXECUTABLE};${MPIEXEC_NUMPROC_FLAG};1;${MPIEXEC_PREFLAGS}"
  )
  # Single-process registration (ctest default): runs the binary directly so the
  # level-independence property is validated structurally even without a launcher.
  add_test(NAME test_collective_count_np1 COMMAND test_collective_count)
  set_tests_properties(
    test_collective_count_np1
    PROPERTIES ENVIRONMENT "FI_PROVIDER=tcp;I_MPI_FABRICS=shm"
  )
  # Multi-rank registration under mpirun. Container preflags
  # (--allow-run-as-root/--oversubscribe) come from the
  # CECE_MPIEXEC_CONTAINER_FLAGS option near find_package(MPI).
  add_test(
    NAME test_collective_count_np2
    COMMAND
      ${MPIEXEC_EXECUTABLE} ${MPIEXEC_NUMPROC_FLAG} 2 ${MPIEXEC_PREFLAGS}
      $<TARGET_FILE:test_collective_count> ${MPIEXEC_POSTFLAGS}
  )
  set_tests_properties(
    test_collective_count_np2
    PROPERTIES
      ENVIRONMENT
        "FI_PROVIDER=tcp;I_MPI_FABRICS=shm;OMPI_ALLOW_RUN_AS_ROOT=1;OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1"
  )

  # HALO single-gather assembly equivalence Property Test
  # (cece-halo-collective-adoption, Property 1, Task 10.1). Compares the naive
  # per-level MPI_Allgatherv assembly against the new contiguous-send-buffer +
  # Replicated_Gather_Plan + gather_replicated assembly on the same random source,
  # a real identity plan and matrix-style bands, asserting bit-for-bit (identity)
  # or within kRegridTolerance (matrix), the mpi_size == 1 boundary, and cross-rank
  # bit-identity. Provides its own main() with MPI + Kokkos init (so it does NOT
  # link GTest::gtest_main); uses RapidCheck; links HELM::HALO and Kokkos. Runnable
  # as a single process AND under mpirun --oversubscribe -np {2,4}.
  add_executable(test_halo_gather_equivalence tests/test_halo_gather_equivalence.cpp)
  target_link_libraries(
    test_halo_gather_equivalence
    PRIVATE cece HELM::HALO MPI::MPI_CXX Kokkos::kokkos GTest::gtest rapidcheck rapidcheck_gtest
  )
  set_target_properties(
    test_halo_gather_equivalence
    PROPERTIES TEST_LAUNCHER "${MPIEXEC_EXECUTABLE};${MPIEXEC_NUMPROC_FLAG};1;${MPIEXEC_PREFLAGS}"
  )
  # Single-process registration (ctest default): runs the binary directly so the
  # mpi_size == 1 boundary (Decision A std::copy fast path) is validated even
  # without a launcher.
  add_test(NAME test_halo_gather_equivalence_np1 COMMAND test_halo_gather_equivalence)
  set_tests_properties(
    test_halo_gather_equivalence_np1
    PROPERTIES ENVIRONMENT "FI_PROVIDER=tcp;I_MPI_FABRICS=shm"
  )
  # Multi-rank registration under mpirun. Container preflags
  # (--allow-run-as-root/--oversubscribe) come from the
  # CECE_MPIEXEC_CONTAINER_FLAGS option near find_package(MPI).
  add_test(
    NAME test_halo_gather_equivalence_np2
    COMMAND
      ${MPIEXEC_EXECUTABLE} ${MPIEXEC_NUMPROC_FLAG} 2 ${MPIEXEC_PREFLAGS}
      $<TARGET_FILE:test_halo_gather_equivalence> ${MPIEXEC_POSTFLAGS}
  )
  set_tests_properties(
    test_halo_gather_equivalence_np2
    PROPERTIES
      ENVIRONMENT
        "FI_PROVIDER=tcp;I_MPI_FABRICS=shm;OMPI_ALLOW_RUN_AS_ROOT=1;OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1"
  )
  add_test(
    NAME test_halo_gather_equivalence_np4
    COMMAND
      ${MPIEXEC_EXECUTABLE} ${MPIEXEC_NUMPROC_FLAG} 4 ${MPIEXEC_PREFLAGS}
      $<TARGET_FILE:test_halo_gather_equivalence> ${MPIEXEC_POSTFLAGS}
  )
  set_tests_properties(
    test_halo_gather_equivalence_np4
    PROPERTIES
      ENVIRONMENT
        "FI_PROVIDER=tcp;I_MPI_FABRICS=shm;OMPI_ALLOW_RUN_AS_ROOT=1;OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1"
  )

  # Collective gate-equivalence property tests (cece-halo-collective-adoption,
  # Properties 2 & 3, Task 10.2). Compares the HALO-backed collective_all_ready /
  # collective_int_matches helpers' (bool, failure_detail) against a legacy
  # reference over generated per-rank readiness/int vectors, including the
  # short-circuit cases (NULL comm / size-1). Reaches the REAL production helpers
  # via the CollectiveGateTestAccess friend shim's CallCollectiveAllReady /
  # CallCollectiveIntMatches forwarders. Provides its own main() with MPI init (so
  # it does NOT link GTest::gtest_main) and is runnable as a single process AND
  # under mpirun --oversubscribe -np 2. Uses RapidCheck (>=100 iterations), so it
  # links rapidcheck + rapidcheck_gtest.
  add_executable(test_collective_gate_equivalence tests/test_collective_gate_equivalence.cpp)
  target_link_libraries(
    test_collective_gate_equivalence
    PRIVATE cece GTest::gtest MPI::MPI_CXX rapidcheck rapidcheck_gtest
  )
  set_target_properties(
    test_collective_gate_equivalence
    PROPERTIES TEST_LAUNCHER "${MPIEXEC_EXECUTABLE};${MPIEXEC_NUMPROC_FLAG};1;${MPIEXEC_PREFLAGS}"
  )
  # Single-process registration (ctest default): runs the binary directly so the
  # short-circuit (NULL comm / size-1) branches are validated even without a
  # launcher.
  add_test(NAME test_collective_gate_equivalence_np1 COMMAND test_collective_gate_equivalence)
  set_tests_properties(
    test_collective_gate_equivalence_np1
    PROPERTIES ENVIRONMENT "FI_PROVIDER=tcp;I_MPI_FABRICS=shm"
  )
  # Multi-rank registration under mpirun. Container preflags
  # (--allow-run-as-root/--oversubscribe) come from the
  # CECE_MPIEXEC_CONTAINER_FLAGS option near find_package(MPI).
  add_test(
    NAME test_collective_gate_equivalence_np2
    COMMAND
      ${MPIEXEC_EXECUTABLE} ${MPIEXEC_NUMPROC_FLAG} 2 ${MPIEXEC_PREFLAGS}
      $<TARGET_FILE:test_collective_gate_equivalence> ${MPIEXEC_POSTFLAGS}
  )
  set_tests_properties(
    test_collective_gate_equivalence_np2
    PROPERTIES
      ENVIRONMENT
        "FI_PROVIDER=tcp;I_MPI_FABRICS=shm;OMPI_ALLOW_RUN_AS_ROOT=1;OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1"
  )

  # HALO-adoption unit / example / edge-case tests (cece-halo-collective-adoption,
  # Task 10.6). Deterministic checks pinning: Replicated_Gather_Plan accessors ==
  # CECE's counts/displs, send_buf offset index-math, the halo_comm_ wrapping
  # decision + real predefined/duplicated wrap behavior, and the cache-clear
  # invalidation invariant. Needs a size>1 halo::Communicator for the plan
  # accessors, so it uses the MPI-main pattern (own main(), links
  # GTest::gtest MPI::MPI_CXX HELM::HALO) and registers at np1/np2/np4 via
  # mpirun --oversubscribe. The np1 registration validates the pure index-math and
  # decision-predicate tests even without a launcher.
  add_executable(test_halo_adoption_units tests/test_halo_adoption_units.cpp)
  target_link_libraries(test_halo_adoption_units PRIVATE cece GTest::gtest MPI::MPI_CXX HELM::HALO)
  set_target_properties(
    test_halo_adoption_units
    PROPERTIES TEST_LAUNCHER "${MPIEXEC_EXECUTABLE};${MPIEXEC_NUMPROC_FLAG};1;${MPIEXEC_PREFLAGS}"
  )
  add_test(NAME test_halo_adoption_units_np1 COMMAND test_halo_adoption_units)
  set_tests_properties(
    test_halo_adoption_units_np1
    PROPERTIES ENVIRONMENT "FI_PROVIDER=tcp;I_MPI_FABRICS=shm"
  )
  add_test(
    NAME test_halo_adoption_units_np2
    COMMAND
      ${MPIEXEC_EXECUTABLE} ${MPIEXEC_NUMPROC_FLAG} 2 ${MPIEXEC_PREFLAGS}
      $<TARGET_FILE:test_halo_adoption_units> ${MPIEXEC_POSTFLAGS}
  )
  set_tests_properties(
    test_halo_adoption_units_np2
    PROPERTIES
      ENVIRONMENT
        "FI_PROVIDER=tcp;I_MPI_FABRICS=shm;OMPI_ALLOW_RUN_AS_ROOT=1;OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1"
  )
  add_test(
    NAME test_halo_adoption_units_np4
    COMMAND
      ${MPIEXEC_EXECUTABLE} ${MPIEXEC_NUMPROC_FLAG} 4 ${MPIEXEC_PREFLAGS}
      $<TARGET_FILE:test_halo_adoption_units> ${MPIEXEC_POSTFLAGS}
  )
  set_tests_properties(
    test_halo_adoption_units_np4
    PROPERTIES
      ENVIRONMENT
        "FI_PROVIDER=tcp;I_MPI_FABRICS=shm;OMPI_ALLOW_RUN_AS_ROOT=1;OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1"
  )

  # HALO-adoption multi-rank integration test (cece-halo-collective-adoption,
  # Task 11.1). Exercises the REAL regrid+gather path primitives — the pre-gather
  # local_ok readiness allreduce, the fused front-half gate (packed 5-entry
  # halo::allreduce MIN + MAX), and the single-gather assembly (Replicated_Gather_
  # Plan + gather_replicated) — in a focused harness. Asserts deadlock freedom /
  # no-skip under a not-ready failure injection (rank 0, a non-zero rank, and a
  # shape mismatch), np2/np4 cross-rank bit-identity, and np1-equivalence against
  # the full-grid serial reference within 1e-10. Provides its own main() with MPI +
  # Kokkos init (so it does NOT link GTest::gtest_main); links HELM::HALO and
  # Kokkos. Runnable as a single process AND under mpirun --oversubscribe -np {2,4}.
  add_executable(test_halo_multirank_integration tests/test_halo_multirank_integration.cpp)
  target_link_libraries(
    test_halo_multirank_integration
    PRIVATE cece HELM::HALO MPI::MPI_CXX Kokkos::kokkos GTest::gtest
  )
  set_target_properties(
    test_halo_multirank_integration
    PROPERTIES TEST_LAUNCHER "${MPIEXEC_EXECUTABLE};${MPIEXEC_NUMPROC_FLAG};1;${MPIEXEC_PREFLAGS}"
  )
  # Single-process registration (ctest default): the np1 short-circuit branches
  # (local decision, Decision A std::copy fast path) are validated without a
  # launcher.
  add_test(NAME test_halo_multirank_integration_np1 COMMAND test_halo_multirank_integration)
  set_tests_properties(
    test_halo_multirank_integration_np1
    PROPERTIES ENVIRONMENT "FI_PROVIDER=tcp;I_MPI_FABRICS=shm"
  )
  # Multi-rank registration under mpirun. Container preflags
  # (--allow-run-as-root/--oversubscribe) come from the
  # CECE_MPIEXEC_CONTAINER_FLAGS option near find_package(MPI).
  add_test(
    NAME test_halo_multirank_integration_np2
    COMMAND
      ${MPIEXEC_EXECUTABLE} ${MPIEXEC_NUMPROC_FLAG} 2 ${MPIEXEC_PREFLAGS}
      $<TARGET_FILE:test_halo_multirank_integration> ${MPIEXEC_POSTFLAGS}
  )
  set_tests_properties(
    test_halo_multirank_integration_np2
    PROPERTIES
      ENVIRONMENT
        "FI_PROVIDER=tcp;I_MPI_FABRICS=shm;OMPI_ALLOW_RUN_AS_ROOT=1;OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1"
  )
  add_test(
    NAME test_halo_multirank_integration_np4
    COMMAND
      ${MPIEXEC_EXECUTABLE} ${MPIEXEC_NUMPROC_FLAG} 4 ${MPIEXEC_PREFLAGS}
      $<TARGET_FILE:test_halo_multirank_integration> ${MPIEXEC_POSTFLAGS}
  )
  set_tests_properties(
    test_halo_multirank_integration_np4
    PROPERTIES
      ENVIRONMENT
        "FI_PROVIDER=tcp;I_MPI_FABRICS=shm;OMPI_ALLOW_RUN_AS_ROOT=1;OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1"
  )

  # MEGAN3 Canopy Model Property Tests
  add_executable(test_megan3 tests/test_megan3.cpp)
  target_link_libraries(test_megan3 PRIVATE cece cece_test_main_kokkos rapidcheck rapidcheck_gtest)

  # BDSNP Soil NO Property Tests
  add_executable(test_bdsnp tests/test_bdsnp.cpp)
  target_link_libraries(test_bdsnp PRIVATE cece cece_test_main_kokkos rapidcheck rapidcheck_gtest)

  # Canonical BDSNP production-kernel regression tests
  add_executable(test_bdsnp_runtime tests/test_bdsnp_runtime.cpp)
  target_link_libraries(test_bdsnp_runtime PRIVATE cece cece_test_main_kokkos)

  if(ESMF_FOUND)
    add_executable(test_field_creation tests/test_field_creation.cpp)
    add_executable(test_field_creation_error_handling tests/test_field_creation_error_handling.cpp)
    if(CECE_HAS_FORTRAN AND TARGET test_helpers)
      target_link_libraries(test_field_creation PRIVATE cece test_helpers cece_test_main)
      set_target_properties(
        test_field_creation
        PROPERTIES
          TEST_LAUNCHER "${MPIEXEC_EXECUTABLE};${MPIEXEC_NUMPROC_FLAG};1;${MPIEXEC_PREFLAGS}"
      )
      target_link_libraries(
        test_field_creation_error_handling
        PRIVATE cece test_helpers cece_test_main
      )
      set_target_properties(
        test_field_creation_error_handling
        PROPERTIES
          TEST_LAUNCHER "${MPIEXEC_EXECUTABLE};${MPIEXEC_NUMPROC_FLAG};1;${MPIEXEC_PREFLAGS}"
      )
    else()
      target_link_libraries(test_field_creation PRIVATE cece cece_test_main)
      target_link_libraries(test_field_creation_error_handling PRIVATE cece cece_test_main)
    endif()

    # Unit tests for field pointer passing (Requirement R5)
    add_executable(test_field_pointer_passing tests/test_field_pointer_passing.cpp)
    if(CECE_HAS_FORTRAN AND TARGET test_helpers)
      target_link_libraries(test_field_pointer_passing PRIVATE cece test_helpers cece_test_main)
      set_target_properties(
        test_field_pointer_passing
        PROPERTIES
          TEST_LAUNCHER "${MPIEXEC_EXECUTABLE};${MPIEXEC_NUMPROC_FLAG};1;${MPIEXEC_PREFLAGS}"
      )
    else()
      target_link_libraries(test_field_pointer_passing PRIVATE cece cece_test_main)
    endif()

    set_target_properties(
      test_field_creation
      test_field_creation_error_handling
      test_field_pointer_passing
      PROPERTIES TEST_LAUNCHER "${MPIEXEC_EXECUTABLE};${MPIEXEC_NUMPROC_FLAG};1;${MPIEXEC_PREFLAGS}"
    )
  endif()

  # C++ HELM Unit Tests
  add_executable(test_helm_cpp tests/test_helm_cpp.cpp)
  target_link_libraries(
    test_helm_cpp
    PRIVATE cece HELM::DAGR HELM::HALO HELM::TICK HELM::SPAN cece_test_main
  )
  target_compile_definitions(test_helm_cpp PRIVATE CECE_SOURCE_DIR="${CMAKE_CURRENT_SOURCE_DIR}")

  # Ensure tests run under MPI
  set_target_properties(
    test_helm_cpp
    PROPERTIES TEST_LAUNCHER "${MPIEXEC_EXECUTABLE};${MPIEXEC_NUMPROC_FLAG};1;${MPIEXEC_PREFLAGS}"
  )

  # Python script tests
  find_package(Python3 COMPONENTS Interpreter)
  if(Python3_Interpreter_FOUND)
    # Use a venv inside the build directory so pip installs work even in
    # read-only container environments (e.g. Singularity).
    set(CECE_PYTHON_DIR "${CMAKE_BINARY_DIR}/python")
    set(CECE_PYTHON_VENV_DIR "${CECE_PYTHON_DIR}/venv")
    set(CECE_PYTHON_TMP_DIR "${CECE_PYTHON_DIR}/tmp")
    set(CECE_PYTHON_CACHE_DIR "${CECE_PYTHON_DIR}/cache")

    file(MAKE_DIRECTORY "${CECE_PYTHON_DIR}")
    file(MAKE_DIRECTORY "${CECE_PYTHON_TMP_DIR}")
    file(MAKE_DIRECTORY "${CECE_PYTHON_CACHE_DIR}")

    if(WIN32)
      set(VENV_PYTHON "${CECE_PYTHON_VENV_DIR}/Scripts/python.exe")
    else()
      set(VENV_PYTHON "${CECE_PYTHON_VENV_DIR}/bin/python")
    endif()

    # Keep pip and temp files inside the build tree for containerized CI runs.
    set(
      CECE_PIP_TEST_ENV
      "PIP_CACHE_DIR=${CECE_PYTHON_CACHE_DIR}"
      "PIP_DISABLE_PIP_VERSION_CHECK=1"
      "HOME=${CECE_PYTHON_DIR}"
      "TMPDIR=${CECE_PYTHON_TMP_DIR}"
      "PYTHONNOUSERSITE=1"
    )
    if(WIN32)
      list(
        APPEND CECE_PIP_TEST_ENV
        "TMP=${CECE_PYTHON_TMP_DIR}"
        "TEMP=${CECE_PYTHON_TMP_DIR}"
        "USERPROFILE=${CECE_PYTHON_DIR}"
      )
    endif()

    # Python packages the pytest-based tests need — single source of truth for
    # the configure-time prefetch and the install_python_deps fixture test.
    set(CECE_PYTHON_TEST_DEPS pytest PyYAML matplotlib numpy)

    # Prefetch the venv + packages at configure time: configure typically runs
    # where the network is available (e.g. HPC login nodes) while ctest may run
    # where it is not (compute nodes). pip install is an offline no-op once the
    # requirements are satisfied, so the fixture tests below then pass without
    # network. Best-effort by design — an offline configure warns and defers to
    # the fixture tests, never fails.
    option(
      CECE_PREFETCH_PYTHON_TEST_DEPS
      "Install python test deps into the build-tree venv at configure time"
      ON
    )
    if(CECE_PREFETCH_PYTHON_TEST_DEPS)
      execute_process(
        COMMAND
          ${CMAKE_COMMAND} -E env ${CECE_PIP_TEST_ENV} ${Python3_EXECUTABLE} -m venv
          ${CECE_PYTHON_VENV_DIR}
        RESULT_VARIABLE _cece_venv_rc
        OUTPUT_QUIET
        ERROR_QUIET
      )
      set(_cece_prefetch_rc 1)
      if(_cece_venv_rc EQUAL 0)
        execute_process(
          COMMAND
            ${CMAKE_COMMAND} -E env ${CECE_PIP_TEST_ENV} ${VENV_PYTHON} -I -m pip install
            ${CECE_PYTHON_TEST_DEPS}
          RESULT_VARIABLE _cece_prefetch_rc
          OUTPUT_QUIET
          ERROR_QUIET
          TIMEOUT 300
        )
      endif()
      if(_cece_prefetch_rc EQUAL 0)
        cece_register_dep("python-test-deps" "prefetched at configure (${CECE_PYTHON_VENV_DIR})")
      else()
        message(
          WARNING
          "Could not prefetch python test deps into ${CECE_PYTHON_VENV_DIR} (offline configure?). The install_python_deps test will retry at test time."
        )
        cece_register_dep("python-test-deps" "deferred to test time (prefetch failed)")
      endif()
    else()
      cece_register_dep("python-test-deps" "deferred to test time (prefetch disabled)")
    endif()

    add_test(NAME create_python_venv COMMAND ${Python3_EXECUTABLE} -m venv ${CECE_PYTHON_VENV_DIR})
    add_test(
      NAME ensure_pip_in_venv
      COMMAND ${VENV_PYTHON} -I -m ensurepip --upgrade
    )
    add_test(
      NAME upgrade_pip_in_venv
      COMMAND ${VENV_PYTHON} -I -m pip install --upgrade pip
    )
    set_tests_properties(
      create_python_venv
      ensure_pip_in_venv
      upgrade_pip_in_venv
      PROPERTIES FIXTURES_SETUP "python_venv_ready" ENVIRONMENT "${CECE_PIP_TEST_ENV}"
    )
    set_tests_properties(ensure_pip_in_venv PROPERTIES DEPENDS create_python_venv)
    set_tests_properties(upgrade_pip_in_venv PROPERTIES DEPENDS ensure_pip_in_venv)

    add_test(
      NAME install_python_deps
      COMMAND ${VENV_PYTHON} -I -m pip install ${CECE_PYTHON_TEST_DEPS}
    )
    set_tests_properties(
      install_python_deps
      PROPERTIES
        FIXTURES_SETUP "python_deps_installed"
        FIXTURES_REQUIRED "python_venv_ready"
        ENVIRONMENT "${CECE_PIP_TEST_ENV}"
    )

    add_test(
      NAME test_hemco_to_cece_python
      COMMAND ${VENV_PYTHON} -m pytest ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_converters.py
    )
    set_tests_properties(
      test_hemco_to_cece_python
      PROPERTIES
        ENVIRONMENT "PYTHONPATH=${CMAKE_CURRENT_SOURCE_DIR}/scripts"
        FIXTURES_REQUIRED "python_deps_installed"
    )

    add_test(
      NAME test_scripts_python
      COMMAND ${VENV_PYTHON} -m pytest ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_scripts.py
    )
    set_tests_properties(
      test_scripts_python
      PROPERTIES
        ENVIRONMENT "PYTHONPATH=${CMAKE_CURRENT_SOURCE_DIR}/scripts"
        FIXTURES_REQUIRED "python_deps_installed"
    )

    if(BUILD_PYTHON_BINDINGS)
      add_test(
        NAME test_enum_config_bindings
        COMMAND
          ${VENV_PYTHON} -m pytest ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_enum_config_bindings.py -v
      )
      set_tests_properties(
        test_enum_config_bindings
        PROPERTIES
          ENVIRONMENT "PYTHONPATH=${CMAKE_BINARY_DIR}/src/python/cece"
          FIXTURES_REQUIRED "python_deps_installed"
      )

      add_test(
        NAME test_state_bindings
        COMMAND ${VENV_PYTHON} -m pytest ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_state_bindings.py -v
      )
      set_tests_properties(
        test_state_bindings
        PROPERTIES
          ENVIRONMENT "PYTHONPATH=${CMAKE_BINARY_DIR}/src/python/cece"
          FIXTURES_REQUIRED "python_deps_installed"
      )

      add_test(
        NAME test_compute_bindings
        COMMAND
          ${VENV_PYTHON} -m pytest ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_compute_bindings.py -v
      )
      set_tests_properties(
        test_compute_bindings
        PROPERTIES
          ENVIRONMENT "PYTHONPATH=${CMAKE_BINARY_DIR}/src/python/cece"
          FIXTURES_REQUIRED "python_deps_installed"
      )

      add_test(
        NAME test_validator_logger_bindings
        COMMAND
          ${VENV_PYTHON} -m pytest
          ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_validator_logger_bindings.py -v
      )
      set_tests_properties(
        test_validator_logger_bindings
        PROPERTIES
          ENVIRONMENT "PYTHONPATH=${CMAKE_BINARY_DIR}/src/python/cece"
          FIXTURES_REQUIRED "python_deps_installed"
      )

      add_test(
        NAME test_python_api_rewired
        COMMAND
          ${VENV_PYTHON} -m pytest ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_python_api_rewired.py -v
      )
      set_tests_properties(
        test_python_api_rewired
        PROPERTIES
          ENVIRONMENT "PYTHONPATH=${CMAKE_BINARY_DIR}/src/python"
          FIXTURES_REQUIRED "python_deps_installed"
      )
    endif()
  endif()

  include(GoogleTest)

  # Defer GTest test enumeration from build time to test (ctest) run time for ALL
  # gtest_discover_tests calls below. With the default POST_BUILD mode, CMake runs
  # each test binary during `make` to list its cases; on HPC/MPI systems that
  # aborts for MPI-initializing binaries when built on a login/build node with no
  # Slurm PMI context (e.g. "PMI2_Job_GetId returned 14"), breaking the build.
  # PRE_TEST enumerates at `ctest` time instead — inside the job allocation where
  # MPI can initialize. Set as the global default so every discovery call honors
  # it without per-call edits. Requires CMake >= 3.18 (project already uses 3.27).
  set(CMAKE_GTEST_DISCOVER_TESTS_DISCOVERY_MODE PRE_TEST)

  # Every discovered gtest suite runs single-rank (its TEST_LAUNCHER, where
  # present, is `mpiexec -n 1`), so tag all discovered tests LABELS np1 —
  # rank-count selection (`ctest -L np1|np2|np4`) then covers the whole
  # suite. Shadowing the module function keeps the call sites untouched and
  # future calls covered; the module's implementation stays reachable under
  # the underscore name, and repeated PROPERTIES keywords accumulate, so
  # call-site PROPERTIES merge with the injected pair. The injection is
  # PREPENDED: discovery serializes PROPERTIES as a flat list and re-pairs
  # it name/value, so a semicolon-list value at a call site (see the
  # FI_PROVIDER note below) silently corrupts every pair after it —
  # prepending keeps the injected pairs ahead of any such value.
  # Directly-registered tests get the same two properties from the `_np<N>`
  # suffix sweep at the end of this block.
  #
  # ENVIRONMENT_MODIFICATION OMP_PROC_BIND=set:false is Kokkos's own
  # unit-testing recommendation (silences the OpenMP-backend warning). It is a
  # separate property from ENVIRONMENT, so call-site ENVIRONMENT values are
  # untouched. Discovery itself needs no such default: gtest lists tests
  # before any Environment::SetUp runs, so no test binary initializes Kokkos
  # while being enumerated.
  function(gtest_discover_tests target)
    _gtest_discover_tests(
      ${target}
      PROPERTIES LABELS np1 ENVIRONMENT_MODIFICATION "OMP_PROC_BIND=set:false" ${ARGN}
    )
  endfunction()

  gtest_discover_tests(test_driver_configuration)
  gtest_discover_tests(test_driver_clock_management)
  gtest_discover_tests(test_clock_operations_unit)
  gtest_discover_tests(test_driver_integration_end_to_end)
  gtest_discover_tests(test_stacking_engine)
  gtest_discover_tests(test_vertical_distribution_single)
  gtest_discover_tests(test_cece_utils PROPERTIES PROCESSORS 1)
  gtest_discover_tests(test_numerical_equivalence)
  gtest_discover_tests(test_cece_compute)
  gtest_discover_tests(test_standalone_writer_attributes PROPERTIES PROCESSORS 1)
  gtest_discover_tests(test_physics)
  gtest_discover_tests(test_cece_ingestor)
  gtest_discover_tests(test_hemco_mimic)
  gtest_discover_tests(test_field_resolution_priority)
  gtest_discover_tests(test_ingest_setfield_bypass)
  gtest_discover_tests(test_ingest_copyback_neutralized)
  gtest_discover_tests(test_hemco_parity)
  gtest_discover_tests(test_kokkos_configuration)
  gtest_discover_tests(test_properties)
  gtest_discover_tests(test_suite_idempotence)
  gtest_discover_tests(test_repro_failure)
  gtest_discover_tests(test_ccpp_readiness)
  gtest_discover_tests(test_fengsha_properties)
  gtest_discover_tests(test_ginoux_properties)
  gtest_discover_tests(test_k14_properties)
  gtest_discover_tests(test_speciation)
  gtest_discover_tests(test_megan3)
  gtest_discover_tests(test_cece_clock_properties)
  gtest_discover_tests(test_cece_time_indexing)
  gtest_discover_tests(test_cece_calendar)
  gtest_discover_tests(test_cece_amio_utils)
  gtest_discover_tests(test_cece_time_axis_netcdf PROPERTIES PROCESSORS 1)
  gtest_discover_tests(test_cece_clock_run_loop)
  gtest_discover_tests(test_bracket_equal_properties)
  gtest_discover_tests(
    test_band_decomposition_partition
    PROPERTIES ENVIRONMENT "RC_PARAMS=max_success=100"
  )
  gtest_discover_tests(
    test_band_regrid_equals_global_rows
    PROPERTIES ENVIRONMENT "RC_PARAMS=max_success=100"
  )
  gtest_discover_tests(test_band_single_rank_properties)
  gtest_discover_tests(test_stream_key_properties)
  gtest_discover_tests(test_handle_key_properties)
  gtest_discover_tests(test_stream_key_extends_handle_key)
  gtest_discover_tests(test_stream_config_resolution)
  gtest_discover_tests(test_no_manifest_no_reparse)
  gtest_discover_tests(test_slice_cache_equivalence)
  gtest_discover_tests(test_slice_cache_independence)
  gtest_discover_tests(test_open_once_no_per_step_close)
  gtest_discover_tests(test_cache_hit_skips_work)
  gtest_discover_tests(test_endpoint_blend_equivalence)
  gtest_discover_tests(test_endpoint_work_reduction)
  gtest_discover_tests(test_endpoint_shared_plan)
  gtest_discover_tests(test_endpoint_tier_precedence)
  gtest_discover_tests(test_endpoint_sizing)
  gtest_discover_tests(test_endpoint_invalidation)
  gtest_discover_tests(test_regrid_conservation_properties)
  gtest_discover_tests(test_shared_plan_equivalence)
  gtest_discover_tests(test_ingest_no_stale_data)
  gtest_discover_tests(test_ingest_consolidation_equivalence)
  gtest_discover_tests(test_ingest_collective_gate_order)
  gtest_discover_tests(test_ingest_single_write)
  gtest_discover_tests(test_bdsnp)
  gtest_discover_tests(test_bdsnp_runtime)
  # gtest_discover_tests PROPERTIES cannot carry semicolon-list values:
  # discovery flattens PROPERTIES and re-pairs name/value, so a list value
  # (e.g. ENVIRONMENT "A=1;B=2") shifts every pair after it into garbage
  # properties — B=2 becomes a property NAME and later pairs are lost.
  # Keep ENVIRONMENT single-valued here (historically only the first entry
  # ever applied); multi-entry env strings are fine on set_tests_properties
  # for directly-registered tests, which parse quoted values whole.
  gtest_discover_tests(test_helm_cpp PROPERTIES ENVIRONMENT "FI_PROVIDER=tcp" PROCESSORS 1)

  if(ESMF_FOUND)
    gtest_discover_tests(
      test_driver_config_validation
      PROPERTIES ENVIRONMENT "FI_PROVIDER=tcp" PROCESSORS 1
    )
    gtest_discover_tests(test_cece_cap PROPERTIES ENVIRONMENT "FI_PROVIDER=tcp")
    gtest_discover_tests(test_diagnostics PROPERTIES ENVIRONMENT "FI_PROVIDER=tcp")
    gtest_discover_tests(test_field_creation PROPERTIES ENVIRONMENT "FI_PROVIDER=tcp" PROCESSORS 1)
    gtest_discover_tests(test_field_creation_error_handling PROPERTIES PROCESSORS 1)
    gtest_discover_tests(
      test_field_pointer_passing
      PROPERTIES ENVIRONMENT "FI_PROVIDER=tcp" PROCESSORS 1
    )
  endif()
  # Band-boundary conservation on NON-UNIFORM grids (distributed-domain-decomposition,
  # Property 10). Drives the REAL build_band_mesh_with_global_corners production
  # helper + AXIS conservative regrid; own Kokkos/MPI main().
  add_executable(test_band_boundary_conservation tests/test_band_boundary_conservation.cpp)
  target_link_libraries(
    test_band_boundary_conservation
    PRIVATE cece cece_test_main MPI::MPI_CXX Kokkos::kokkos HELM::AXIS rapidcheck rapidcheck_gtest
  )
  set_target_properties(
    test_band_boundary_conservation
    PROPERTIES TEST_LAUNCHER "${MPIEXEC_EXECUTABLE};${MPIEXEC_NUMPROC_FLAG};1;${MPIEXEC_PREFLAGS}"
  )

  # Band-boundary conservation on CURVILINEAR grids (distributed-domain-decomposition,
  # Property 11). Drives the REAL build_band_mesh_curvilinear_with_global_corners
  # production helper (AXIS synthesize_band_corners) + AXIS conservative regrid;
  # own Kokkos/MPI main().
  add_executable(test_band_boundary_curvilinear tests/test_band_boundary_curvilinear.cpp)
  target_link_libraries(
    test_band_boundary_curvilinear
    PRIVATE cece cece_test_main MPI::MPI_CXX Kokkos::kokkos HELM::AXIS rapidcheck rapidcheck_gtest
  )
  set_target_properties(
    test_band_boundary_curvilinear
    PROPERTIES TEST_LAUNCHER "${MPIEXEC_EXECUTABLE};${MPIEXEC_NUMPROC_FLAG};1;${MPIEXEC_PREFLAGS}"
  )

  gtest_discover_tests(
    test_band_boundary_conservation
    PROPERTIES ENVIRONMENT "RC_PARAMS=max_success=100"
  )
  gtest_discover_tests(
    test_band_boundary_curvilinear
    PROPERTIES ENVIRONMENT "RC_PARAMS=max_success=100"
  )

  # ---------------------------------------------------------------------------
  # Task 10 — integration / property tests (distributed-domain-decomposition)
  # ---------------------------------------------------------------------------

  # 10.1 Output_Gather reconstruction (Property 4). Pure pack/place reassembly +
  # a per-level MPI_Gatherv multi-rank variant, both RapidCheck. Own main() with
  # MPI init (does NOT link GTest::gtest_main), so it runs single-process AND
  # under mpirun. Registered at np1/np2/np4 so the surplus-rank (ny < size) case
  # is exercised by the gatherv property.
  add_executable(test_output_gather_reconstruction tests/test_output_gather_reconstruction.cpp)
  target_link_libraries(
    test_output_gather_reconstruction
    PRIVATE cece GTest::gtest MPI::MPI_CXX rapidcheck rapidcheck_gtest
  )
  set_target_properties(
    test_output_gather_reconstruction
    PROPERTIES TEST_LAUNCHER "${MPIEXEC_EXECUTABLE};${MPIEXEC_NUMPROC_FLAG};1;${MPIEXEC_PREFLAGS}"
  )
  add_test(NAME test_output_gather_reconstruction_np1 COMMAND test_output_gather_reconstruction)
  set_tests_properties(
    test_output_gather_reconstruction_np1
    PROPERTIES ENVIRONMENT "RC_PARAMS=max_success=100;FI_PROVIDER=tcp;I_MPI_FABRICS=shm"
  )
  foreach(np 2 4)
    add_test(
      NAME test_output_gather_reconstruction_np${np}
      COMMAND
        ${MPIEXEC_EXECUTABLE} ${MPIEXEC_NUMPROC_FLAG} ${np} ${MPIEXEC_PREFLAGS}
        $<TARGET_FILE:test_output_gather_reconstruction> ${MPIEXEC_POSTFLAGS}
    )
    set_tests_properties(
      test_output_gather_reconstruction_np${np}
      PROPERTIES
        ENVIRONMENT
          "RC_PARAMS=max_success=100;FI_PROVIDER=tcp;I_MPI_FABRICS=shm;OMPI_ALLOW_RUN_AS_ROOT=1;OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1"
    )
  endforeach()

  # 10.3 Column-local band invariance (Property 7). Drives the REAL Ginoux scheme
  # over the full global range vs a band and asserts bit-for-bit equality of the
  # band-owned cells. Own main() with Kokkos init; single-process.
  add_executable(test_column_local_band_invariance tests/test_column_local_band_invariance.cpp)
  target_link_libraries(
    test_column_local_band_invariance
    PRIVATE cece cece_test_main_kokkos Kokkos::kokkos rapidcheck rapidcheck_gtest
  )
  add_test(
    NAME test_column_local_band_invariance
    COMMAND $<TARGET_FILE:test_column_local_band_invariance>
  )
  set_tests_properties(
    test_column_local_band_invariance
    PROPERTIES ENVIRONMENT "RC_PARAMS=max_success=100"
  )

  # 10.4 Collective lock-step with a surplus rank (Property 8). Drives the exact
  # Output_Gather primitive sequence (per-level Gatherv + Bcast) under size > ny
  # so a rank owns ny_local == 0. Own main() with MPI init. The harness uses
  # ny = 2 and ny = 3, so it needs np >= 4 to produce a surplus rank; registered
  # at np1 (structural, single-rank == whole-grid path) and np4 (surplus path).
  add_executable(test_surplus_rank_lockstep tests/test_surplus_rank_lockstep.cpp)
  target_link_libraries(test_surplus_rank_lockstep PRIVATE cece GTest::gtest MPI::MPI_CXX)
  set_target_properties(
    test_surplus_rank_lockstep
    PROPERTIES TEST_LAUNCHER "${MPIEXEC_EXECUTABLE};${MPIEXEC_NUMPROC_FLAG};1;${MPIEXEC_PREFLAGS}"
  )
  add_test(NAME test_surplus_rank_lockstep_np1 COMMAND test_surplus_rank_lockstep)
  set_tests_properties(
    test_surplus_rank_lockstep_np1
    PROPERTIES ENVIRONMENT "FI_PROVIDER=tcp;I_MPI_FABRICS=shm"
  )
  add_test(
    NAME test_surplus_rank_lockstep_np4
    COMMAND
      ${MPIEXEC_EXECUTABLE} ${MPIEXEC_NUMPROC_FLAG} 4 ${MPIEXEC_PREFLAGS}
      $<TARGET_FILE:test_surplus_rank_lockstep> ${MPIEXEC_POSTFLAGS}
  )
  set_tests_properties(
    test_surplus_rank_lockstep_np4
    PROPERTIES
      ENVIRONMENT
        "FI_PROVIDER=tcp;I_MPI_FABRICS=shm;OMPI_ALLOW_RUN_AS_ROOT=1;OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1"
  )

  # 10.2 Distributed output equivalence (Property 5 & 6). End-to-end: runs the
  # REAL cece_standalone_driver at -np 1/2/3 on the tiny CEDS OC config and
  # asserts the written `oc` field is bit-for-bit identical across rank counts.
  # The shell harness compiles tests/nccmp_var.c against the container NetCDF-C
  # and drives mpirun itself, so it is registered as a single ctest entry with a
  # DEPENDS on the driver target. Requires the CEDS source data in data/.
  if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/data/OC-em-anthro_CMIP_CEDS_2023.nc")
    add_test(
      NAME test_distributed_output_equivalence
      COMMAND
        ${CMAKE_COMMAND} -E env "MPIEXEC_EXECUTABLE=${MPIEXEC_EXECUTABLE}"
        "MPIEXEC_NUMPROC_FLAG=${MPIEXEC_NUMPROC_FLAG}" bash
        ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_distributed_output_equivalence.sh --driver
        $<TARGET_FILE:cece_standalone_driver> --config
        ${CMAKE_CURRENT_SOURCE_DIR}/examples/cece_config_ceds_oc_small.yaml --comparator
        ${CMAKE_CURRENT_SOURCE_DIR}/tests/nccmp_var.c --workdir
        ${CMAKE_CURRENT_BINARY_DIR}/_equiv_workdir
    )
    set_tests_properties(
      test_distributed_output_equivalence
      PROPERTIES
        DEPENDS cece_standalone_driver
        ENVIRONMENT
          "FI_PROVIDER=tcp;I_MPI_FABRICS=shm;OMPI_ALLOW_RUN_AS_ROOT=1;OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1"
        TIMEOUT 600
        # Self-drives -np 1/2/3 sequentially; label/budget for its 3-rank peak
        # (the suffix loop below skips tests that carry an explicit np label).
        LABELS np3
        PROCESSORS 3
    )
  endif()

  # Rank-count labels/processors and the OMP_PROC_BIND default for the
  # directly-registered (non-discovered) tests — the counterpart of the
  # gtest_discover_tests wrapper above — keyed on the `_np<N>` name-suffix
  # convention rather than a hand-kept list. LABELS enable rank-count selection (`ctest -L np2`);
  # PROCESSORS makes `ctest -j` budget ranks correctly (e.g. `-j 4` packs
  # 4x np1, 2x np2, or 1x np4 without oversubscribing a 4-task allocation).
  # Tests without the suffix default to np1 unless their registration
  # already set an explicit np label (e.g. the self-driving
  # test_distributed_output_equivalence). The sweep walks the whole
  # directory tree — the vendored HELM libs register tests in their own
  # subdirectories — via the DIRECTORY-scoped test-property API. That API
  # (the DIRECTORY argument of get_property/set_property for TEST) needs
  # CMake 3.28; on older CMakes only this directory's tests are swept, and
  # the vendored subdirectories' tests keep their own registrations.
  if(CMAKE_VERSION VERSION_GREATER_EQUAL 3.28)
    set(_cece_sweep_subdirs ON)
  else()
    set(_cece_sweep_subdirs OFF)
  endif()
  set(_cece_label_dir_queue "${CMAKE_CURRENT_SOURCE_DIR}")
  while(_cece_label_dir_queue)
    list(POP_FRONT _cece_label_dir_queue _cece_label_dir)
    if(_cece_sweep_subdirs)
      get_property(_cece_label_subdirs DIRECTORY "${_cece_label_dir}" PROPERTY SUBDIRECTORIES)
      list(APPEND _cece_label_dir_queue ${_cece_label_subdirs})
      set(_cece_dir_arg DIRECTORY "${_cece_label_dir}")
    else()
      set(_cece_dir_arg)
    endif()
    get_property(_cece_registered_tests DIRECTORY "${_cece_label_dir}" PROPERTY TESTS)
    foreach(_cece_test IN LISTS _cece_registered_tests)
      set_property(
        TEST ${_cece_test} ${_cece_dir_arg}
        APPEND
        PROPERTY ENVIRONMENT_MODIFICATION "OMP_PROC_BIND=set:false"
      )
      if(_cece_test MATCHES "_np([0-9]+)$")
        set_property(
          TEST ${_cece_test} ${_cece_dir_arg}
          APPEND
          PROPERTY LABELS "np${CMAKE_MATCH_1}"
        )
        set_property(TEST ${_cece_test} ${_cece_dir_arg} PROPERTY PROCESSORS "${CMAKE_MATCH_1}")
      else()
        get_property(_cece_test_labels TEST ${_cece_test} ${_cece_dir_arg} PROPERTY LABELS)
        if(NOT _cece_test_labels MATCHES "np[0-9]")
          set_property(TEST ${_cece_test} ${_cece_dir_arg} APPEND PROPERTY LABELS np1)
        endif()
      endif()
    endforeach()
  endwhile()
endif() # CECE_BUILD_TESTING

# Standalone NUOPC driver
if(ESMF_FOUND)
  add_subdirectory(src/driver/nuopc)
endif()

# --- Python Bindings ---

if(BUILD_PYTHON_BINDINGS)
  message(STATUS "Building Python bindings for CECE")
  add_subdirectory(src/python)
else()
  message(STATUS "Python bindings disabled. Enable with -DBUILD_PYTHON_BINDINGS=ON")
endif()

# --- Doxygen Documentation ---

find_package(Doxygen OPTIONAL_COMPONENTS dot)
if(DOXYGEN_FOUND)
  set(DOXYGEN_OUTPUT_DIRECTORY ${CMAKE_CURRENT_BINARY_DIR}/docs/api)
  set(DOXYGEN_GENERATE_HTML YES)
  set(DOXYGEN_GENERATE_LATEX NO)
  set(DOXYGEN_GENERATE_MAN NO)
  set(DOXYGEN_HAVE_DOT ${DOXYGEN_dot_FOUND})
  set(DOXYGEN_DOT_NUM_THREADS 4)
  set(DOXYGEN_EXTRACT_ALL NO)
  set(DOXYGEN_EXTRACT_PRIVATE NO)
  set(DOXYGEN_EXTRACT_STATIC YES)
  set(DOXYGEN_SOURCE_BROWSER YES)
  set(DOXYGEN_GENERATE_TREEVIEW YES)
  set(DOXYGEN_TREEVIEW_WIDTH 250)
  set(DOXYGEN_CALL_GRAPH YES)
  set(DOXYGEN_CALLER_GRAPH YES)
  set(DOXYGEN_INCLUDE_GRAPH YES)
  set(DOXYGEN_INCLUDED_BY_GRAPH YES)
  set(DOXYGEN_DIRECTORY_GRAPH YES)
  set(DOXYGEN_CLASS_GRAPH YES)
  set(DOXYGEN_COLLABORATION_GRAPH YES)
  set(DOXYGEN_GROUP_GRAPHS YES)
  set(DOXYGEN_PREDEFINED "KOKKOS_LAMBDA=[]" "KOKKOS_FUNCTION=" "KOKKOS_INLINE_FUNCTION=inline")

  doxygen_add_docs(
    cece_docs
    ${CMAKE_CURRENT_SOURCE_DIR}/include
    ${CMAKE_CURRENT_SOURCE_DIR}/src
    COMMENT "Generating CECE API documentation with Doxygen"
    ALL
  )
else()
  message(STATUS "Doxygen not found. API documentation generation disabled.")
  message(STATUS "Install Doxygen to enable: sudo apt-get install doxygen graphviz")
endif()

# --- Code Quality Checks ---

find_program(CLANG_FORMAT_EXECUTABLE clang-format)
if(CLANG_FORMAT_EXECUTABLE)
  file(
    GLOB_RECURSE CECE_FORMAT_FILES
    "${CMAKE_CURRENT_SOURCE_DIR}/include/cece/*.hpp"
    "${CMAKE_CURRENT_SOURCE_DIR}/include/cece/*.h"
    "${CMAKE_CURRENT_SOURCE_DIR}/src/*.cpp"
  )

  add_custom_target(
    clang-format
    COMMAND ${CLANG_FORMAT_EXECUTABLE} -i ${CECE_FORMAT_FILES}
    COMMENT "Running clang-format on CECE source files"
  )

  add_custom_target(
    clang-format-check
    COMMAND ${CLANG_FORMAT_EXECUTABLE} --dry-run --Werror ${CECE_FORMAT_FILES}
    COMMENT "Checking clang-format compliance on CECE source files"
  )
else()
  message(STATUS "clang-format not found. Code formatting targets disabled.")
endif()

find_program(CLANG_TIDY_EXECUTABLE clang-tidy)
if(CLANG_TIDY_EXECUTABLE)
  file(GLOB_RECURSE CECE_TIDY_FILES "${CMAKE_CURRENT_SOURCE_DIR}/src/*.cpp")

  set(_tidy_extra_args "")

  # Python sources require Python.h; exclude them unless bindings are built,
  # and if they are built pass the Python include dir so clang-tidy can find Python.h.
  if(NOT BUILD_PYTHON_BINDINGS)
    list(FILTER CECE_TIDY_FILES EXCLUDE REGEX ".*/src/python/.*")
  else()
    find_package(Python3 COMPONENTS Development QUIET)
    foreach(_py_inc ${Python3_INCLUDE_DIRS})
      list(APPEND _tidy_extra_args "--extra-arg=-I${_py_inc}")
    endforeach()
  endif()

  # clang-tidy uses clang's frontend, which can't find the host compiler's omp.h
  # automatically. Try GCC's -print-file-name first, fall back to a path search.
  execute_process(
    COMMAND ${CMAKE_CXX_COMPILER} -print-file-name=include
    OUTPUT_VARIABLE _gcc_include_dir
    OUTPUT_STRIP_TRAILING_WHITESPACE
    ERROR_QUIET # suppress noise from non-GCC compilers that don't support this flag
    RESULT_VARIABLE _gcc_print_result
  )
  if(_gcc_print_result EQUAL 0 AND EXISTS "${_gcc_include_dir}/omp.h")
    list(APPEND _tidy_extra_args "--extra-arg=-I${_gcc_include_dir}")
  else()
    # Fallback for Intel, Clang, or other compilers: search standard locations
    find_path(_omp_h_dir NAMES omp.h)
    if(_omp_h_dir)
      list(APPEND _tidy_extra_args "--extra-arg=-I${_omp_h_dir}")
    endif()
  endif()

  add_custom_target(
    clang-tidy
    COMMAND
      ${CLANG_TIDY_EXECUTABLE} -p ${CMAKE_BINARY_DIR}
      "--header-filter=^${CMAKE_CURRENT_SOURCE_DIR}/(include|src)/.*\\.(hpp|cpp|h)$$"
      ${_tidy_extra_args} ${CECE_TIDY_FILES}
    COMMENT "Running clang-tidy on CECE source files"
    VERBATIM
  )
else()
  message(STATUS "clang-tidy not found. Code analysis targets disabled.")
endif()

# --- Standalone Driver Executable ---
add_executable(cece_standalone_driver src/main.cpp)
target_link_libraries(
  cece_standalone_driver
  PRIVATE
    cece
    HELM::DAGR
    HELM::SPAN
    HELM::TICK
    AMIO::amio_core
    HELM::AXIS
    HELM::BLEND
    Kokkos::kokkos
    conf
    yaml-cpp
    MPI::MPI_CXX
)

# --- Dependency Resolution Summary ---
get_property(_cece_dep_summary GLOBAL PROPERTY CECE_DEP_SUMMARY)
message(STATUS "CECE external dependency resolution:")
foreach(_cece_dep_entry IN LISTS _cece_dep_summary)
  message(STATUS "  ${_cece_dep_entry}")
endforeach()
