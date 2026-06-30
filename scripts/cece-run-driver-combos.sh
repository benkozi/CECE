#!/bin/bash

# Exit immediately if a command exits with a non-zero status,
# but allow the loop/driver executions to be handled.
set -e

# Check if the directory argument is provided
if [ -z "$1" ]; then
    echo "Usage: $0 <directory>"
    exit 1
fi

SEARCH_DIR="$1"

# Check if the provided argument is indeed a directory
if [ ! -d "$SEARCH_DIR" ]; then
    echo "Error: '$SEARCH_DIR' is not a directory."
    exit 1
fi

# Recursively find YAML files (.yaml and .yml) and execute the driver.
# Using -print0 and read -r -d '' to robustly handle spaces or special characters in paths.
find "$SEARCH_DIR" -type f \( -name "*.yaml" -o -name "*.yml" \) -print0 | while IFS= read -r -d '' y; do
    echo "Executing: ./cece_standalone_driver \"$y\""
    ./cece_standalone_driver "$y"
done
