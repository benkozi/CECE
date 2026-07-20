#!/bin/bash
# Data for examples/cece_config_ex5.yaml (two species, monthly diagnostics).
# Fetches are skipped when the target already exists in data/.
set -euo pipefail
cd "$(dirname "$0")/../.."  # CECE repo root
fetch() {
  local key="$1" target="data/$(basename "$1")"
  if [ ! -f "$target" ]; then ./scripts/download_hemco_data.py "$key" -o "$target"; fi
}
fetch HEMCO/MACCITY/v2014-07/MACCity_4x5.nc
fetch HEMCO/MACCITY/v2014-07/MACCity_anthro_NOx_2000-2010_16080.nc
