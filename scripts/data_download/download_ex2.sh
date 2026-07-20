#!/bin/bash
# Data for examples/cece_config_ex2.yaml (regional masking).
# Fetches are skipped when the target already exists in data/.
set -euo pipefail
cd "$(dirname "$0")/../.."  # CECE repo root
fetch() {
  local key="$1" target="data/$(basename "$1")"
  if [ ! -f "$target" ]; then ./scripts/download_hemco_data.py "$key" -o "$target"; fi
}
fetch HEMCO/MACCITY/v2014-07/MACCity_4x5.nc
fetch HEMCO/CEDS/v2020-08/1970/CO-em-total-anthro_CEDS_1970.nc
fetch HEMCO/MASKS/v2014-07/Canada_mask.gen.1x1.nc
