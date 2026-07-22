#!/bin/bash
# Data for examples/cece_config_ex1.yaml (multi-sector NO + temporal scale factors).
# Fetches are skipped when the target already exists in data/.
#
# Sector files (EDGAR-HTAP v2015-03) come from the public noaa-ufs-srw-pds
# bucket. NOTE: the CAMS-TEMPO fetches at the bottom are EXPECTED TO FAIL
# for now — the geos-chem keys are aspirational (no public CAMS-TEMPO
# source exists yet). They are last so the failure cannot block the
# available data above; place local CAMS copies in data/ to run ex1.
set -euo pipefail
cd "$(dirname "$0")/../.."  # CECE repo root
fetch() {
  local key="$1" target="data/$(basename "$1")"
  if [ ! -f "$target" ]; then ./scripts/download_hemco_data.py "$key" -o "$target"; fi
}
fetch_noaa() {
  local key="$1" target="data/$(basename "$1")"
  if [ ! -f "$target" ]; then
    mkdir -p data
    curl -L -f -o "$target" "https://noaa-ufs-srw-pds.s3.amazonaws.com/$key"
  fi
}
NOAA_HTAP=experiment-user-cases/release-public-v3.0.0/fix/fix_emis/HTAP/v2015-03/NO
fetch_noaa $NOAA_HTAP/EDGAR_HTAP_NO_TRANSPORT.generic.01x01.nc
fetch_noaa $NOAA_HTAP/EDGAR_HTAP_NO_SHIPS.generic.01x01.nc
fetch_noaa $NOAA_HTAP/EDGAR_HTAP_NO_RESIDENTIAL.generic.01x01.nc
fetch_noaa $NOAA_HTAP/EDGAR_HTAP_NO_INDUSTRY.generic.01x01.nc
fetch_noaa $NOAA_HTAP/EDGAR_HTAP_NO_ENERGY.generic.01x01.nc
fetch HEMCO/CAMS-TEMPO/v3.1-2021/CAMS-GLOB-TEMPO_Glb_0.1x0.1_tmp_weights_v3.1_hourly.nc
fetch HEMCO/CAMS-TEMPO/v3.1-2021/CAMS-GLOB-TEMPO_Glb_0.1x0.1_tmp_weights_v3.1_weekly.nc
fetch HEMCO/CAMS-TEMPO/v3.1-2021/CAMS-GLOB-TEMPO_Glb_0.1x0.1_tmp_weights_v3.1_monthly.nc
