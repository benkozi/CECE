#!/usr/bin/env bash

set -ue

cd /opt/project/build
cmake .. \
  -DKokkos_ENABLE_OPENMP=ON \
  -DBUILD_PYTHON_BINDINGS=ON \
  -DCMAKE_INSTALL_PREFIX=/opt/cece/install \
  -DCMAKE_BUILD_TYPE=Debug && \
  make -j$(nproc)
#ctest --output-on-failure
./test_integration_harness