#!/bin/bash
# Data for examples/cece_config_ex6.yaml (multi-stream NO).
# Fetches are skipped when the target already exists in data/.
set -euo pipefail
cd "$(dirname "$0")/../.."  # CECE repo root
fetch() {
  local key="$1" target="data/$(basename "$1")"
  if [ ! -f "$target" ]; then ./scripts/download_hemco_data.py "$key" -o "$target"; fi
}
fetch HEMCO/EDGARv43/v2016-11/EDGAR_v43.NOx.POW.0.1x0.1.nc
fetch HEMCO/CEDS/v2020-08/1970/ALK4_butanes-em-total-anthro_CEDS_1970.nc
