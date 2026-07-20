#!/bin/bash
# Data for examples/cece_config_ex4.yaml (physics schemes).
# Fetches are skipped when the target already exists in data/.
set -euo pipefail
cd "$(dirname "$0")/../.."  # CECE repo root
fetch() {
  local key="$1" target="data/$(basename "$1")"
  if [ ! -f "$target" ]; then ./scripts/download_hemco_data.py "$key" -o "$target"; fi
}
fetch HEMCO/HTAPv3/v2022-12/2018/HTAPv3_NO_0.1x0.1_2018.nc
