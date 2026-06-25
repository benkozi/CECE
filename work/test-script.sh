#!/usr/bin/env bash

set -eu

# --- Configuration ---
CONTAINER_NAME=cece-test-runner
IMAGE_NAME="ghcr.io/noaa-emc/ci-common-build-cache/ufs-weather-model-ubuntu-24.04-gcc-13-mpich-x"       # Change to your required image
HOST_DIR=~/sandbox/git-benkozi/CECE # Change to your actual host directory
CONTAINER_DIR=/opt/project

# --- Container Lifecycle ---

echo "=> Starting container '$CONTAINER_NAME'..."
# Start detached and keep alive
docker run -d \
  --name "$CONTAINER_NAME" \
  -v "$HOST_DIR:$CONTAINER_DIR" \
  "$IMAGE_NAME" tail -f /dev/null

# Safety net: ensure the container is removed if the exec steps fail
trap 'echo "=> Cleaning up..."; docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1' EXIT

echo "=> Executing script..."
# -w sets the working directory inside the container
docker exec -w "$CONTAINER_DIR" "$CONTAINER_NAME" bash /opt/project/work/work.sh

echo "=> Stopping container..."
docker stop "$CONTAINER_NAME" >/dev/null

echo "=> Success!"