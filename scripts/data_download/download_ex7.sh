#!/bin/bash
# Data for examples/cece_config_ex7.yaml (cadence-aware temporal scale factors).
# Fetches are skipped when the target already exists in data/.
#
# NOTE: the CAMS-TEMPO fetches at the bottom are EXPECTED TO FAIL for now —
# the keys are aspirational (no public CAMS-TEMPO source exists yet; a
# public location is being sought). They are last so the failure cannot
# block the available data above; the example fails until CAMS data exists.
set -euo pipefail
cd "$(dirname "$0")/../.."  # CECE repo root
fetch() {
  local key="$1" target="data/$(basename "$1")"
  if [ ! -f "$target" ]; then ./scripts/download_hemco_data.py "$key" -o "$target"; fi
}
fetch HEMCO/HTAPv3/v2022-12/2010/HTAPv3_NO_0.1x0.1_2010.nc
fetch HEMCO/CAMS-TEMPO/v3.1-2021/CAMS-GLOB-TEMPO_Glb_0.1x0.1_tmp_weights_v3.1_hourly.nc
fetch HEMCO/CAMS-TEMPO/v3.1-2021/CAMS-GLOB-TEMPO_Glb_0.1x0.1_tmp_weights_v3.1_weekly.nc
fetch HEMCO/CAMS-TEMPO/v3.1-2021/CAMS-GLOB-TEMPO_Glb_0.1x0.1_tmp_weights_v3.1_monthly.nc
