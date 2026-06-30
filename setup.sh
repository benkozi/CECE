#!/bin/bash
# setup.sh
#
# This script sets up the independent CECE development environment using Docker.
# It uses the local Dockerfile (which builds on top of a clean Ubuntu 24.04 image
# with GCC-13, OpenMPI, NetCDF-C, Kokkos, RapidCheck, and KokkosKernels) and
# drops you into a bash shell.
#
# Usage:
#   ./setup.sh              # Interactive shell
#   ./setup.sh -c "command" # Execute command and exit

set -e

# Define the container image name
IMAGE="deckyfre/cece-dev"

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
        echo "Docker image $IMAGE not found. Building it from Dockerfile..."
        docker buildx build --platform linux/arm64 \
          --builder cloud-bkrlps-cece-builder \
          --push \
          -t "$IMAGE" .
    else
        echo "Error: Dockerfile not found at root directory to build $IMAGE."
        exit 1
    fi
fi

echo "Launching CECE Development Container using $IMAGE..."

# Check if command mode or interactive mode
if [ "$1" = "-c" ] && [ -n "$2" ]; then
    # Command mode: execute command and exit
    docker run --rm \
        -v "$(pwd):/work" \
        -w /work \
        -e OMPI_ALLOW_RUN_AS_ROOT=1 \
        -e OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1 \
        "$IMAGE" \
        /bin/bash -c "$2"
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
