#!/bin/bash
# setup.sh
#
# This script sets up the independent CECE development environment using Docker.
# It uses the local Dockerfile (which builds on top of a clean Ubuntu 24.04 image
# with GCC-13, OpenMPI, NetCDF-C, Kokkos, RapidCheck, and KokkosKernels) and
# drops you into a bash shell.
#
# Usage:
#   ./setup.sh              # Interactive shell (no ESMF)
#   ./setup.sh -c "command" # Execute command and exit
#   ./setup.sh --with-esmf  # Build image with ESMF/NUOPC (only applies when image is built)
#
# Flags may be given in any order.

set -e

USAGE='Usage: ./setup.sh [--with-esmf] [-c "command"]'

# Define the container image name
IMAGE="cece/cece-dev"

# ESMF is not built by default; pass --with-esmf to include it in the image build
# (OFF disables the ESMF build)
BUILD_ESMF=OFF
# Command to run in the container; empty means interactive shell
COMMAND=

while [ $# -gt 0 ]; do
    case "$1" in
        --with-esmf)
            BUILD_ESMF=ON
            ;;
        -c)
            if [ -z "$2" ]; then
                echo "Error: -c requires a command argument." >&2
                echo "$USAGE" >&2
                exit 1
            fi
            COMMAND="$2"
            shift
            ;;
        *)
            echo "Error: unrecognized argument: $1" >&2
            echo "$USAGE" >&2
            exit 1
            ;;
    esac
    shift
done

# Ensure docker is installed
if ! command -v docker &> /dev/null; then
    echo "Error: Docker is not installed or not in PATH."
    exit 1
fi

# Check if the development image already exists locally, if not build it
if docker image inspect "$IMAGE" &> /dev/null; then
    echo "Docker image $IMAGE already exists locally."
else
    if [ -f "Dockerfile" ]; then
        echo "Docker image $IMAGE not found. Building it from Dockerfile (BUILD_ESMF=$BUILD_ESMF)..."
        docker buildx build --build-arg BUILD_ESMF="$BUILD_ESMF" -t "$IMAGE" .
    else
        echo "Error: Dockerfile not found at root directory to build $IMAGE."
        exit 1
    fi
fi

echo "Launching CECE Development Container using $IMAGE..."

# Check if command mode or interactive mode
if [ -n "$COMMAND" ]; then
    # Command mode: execute command and exit
    docker run --rm \
        -v "$(pwd):/work" \
        -w /work \
        -e OMPI_ALLOW_RUN_AS_ROOT=1 \
        -e OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1 \
        "$IMAGE" \
        /bin/bash -c "$COMMAND"
else
    # Interactive mode: drop into bash shell
    docker run -it --rm \
        -v "$(pwd):/work" \
        -w /work \
        -e OMPI_ALLOW_RUN_AS_ROOT=1 \
        -e OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1 \
        "$IMAGE" \
        /bin/bash -c "exec bash"
fi
