ARG BASE_IMAGE=noaaepic/ufschem-spack-base-ubuntu-gcc-13-dev:latest
FROM ${BASE_IMAGE}

SHELL ["/bin/bash", "-c"]

COPY . /opt/cece/src

RUN source /opt/ufschem/spack-stack/setup.sh && \
    spack env activate ufschem && \
    cd /opt/cece/src && \
    mkdir build && \
    cd build && \
    cmake .. \
      -DKokkos_ENABLE_OPENMP=ON \
      -DBUILD_PYTHON_BINDINGS=ON \
      -DCMAKE_INSTALL_PREFIX=/opt/cece/install \
      -DCMAKE_BUILD_TYPE=Debug && \
    make -j$(nproc) && \
    make install && \
    ctest --output-on-failure

RUN cat <<EOF >> ~/.bashrc
# enable spack env by default
source /opt/ufschem/spack-stack/setup.sh
spack env activate ufschem
EOF

WORKDIR /opt

CMD ["/bin/bash"]
