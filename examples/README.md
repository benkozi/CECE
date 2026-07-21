# CECE Configuration Examples

Example YAML configurations demonstrating CECE capabilities. This is the
**single** example set (the former `scripts/examples/` copies used a schema
the driver no longer reads and were removed). Every `cece_config_ex*.yaml`
is expected to run green; they are exercised as regression tests by the
[cece-combo-test-runner](https://github.com/benkozi/cece-combo-test-runner)
via `pytest src/tests/test_examples.py --run-examples`.

All input data is fetched from the public geos-chem S3 bucket by the
matching script in `scripts/data_download/` (files land in `data/`; fetches
are skipped when the target already exists).

## Running an example

```bash
# from the repo root; replace N with the example number
./scripts/data_download/download_exN.sh
docker run --rm -v "$PWD":/work -w /work \
    -e OMPI_ALLOW_RUN_AS_ROOT=1 -e OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1 \
    cece/cece-dev ./build/cece_standalone_driver examples/cece_config_exN.yaml
```

## The examples

| Example | Lesson | Data |
|---|---|---|
| `ex1` | Multi-sector NO with hourly/weekly/monthly temporal scale factors | HTAPv3 2010 NO (sector variables TRA/SHP/RCO/IND/ENE) + CAMS-TEMPO v3.1 weights (*no public source yet — currently fails*) |
| `ex2` | Regional masking: hierarchy + mask-scoped `replace` | MACCity CO, CEDS 1970 CO, mask file |
| `ex3` | Minimal smoke test (2x2 grid, 1 step) | MACCity CO |
| `ex4` | High-resolution (0.1°) inventory regridded to a coarse grid, 24 steps | HTAPv3 2018 shipping NO |
| `ex5` | Two species, two streams, monthly diagnostics cadence | MACCity CO + NOx |
| `ex6` | Multi-stream additive NO from two inventories | EDGAR v4.3 NOx POW, CEDS 1970 ALK4 (agr sector) |
| `ex7` | ex1 + explicit stream `cadence` handling + `amio_worker_threads` | as ex1 (*currently fails with ex1*) |
| `advanced`, `megan3` | Physics schemes (megan, sea_salt, bdsnp, megan3) with met inputs — not part of the automated example gate | see file headers |

Data provenance: ex1/ex7 originally used EDGAR-HTAP v2015-03 sector files
and ex2 used EMEP, neither publicly downloadable; sector data now comes
from HTAPv3 (HTAP's successor, in the public bucket) and ex2 uses CEDS.

**Known gap — ex1/ex7 currently FAIL**: their CAMS-TEMPO v3.1 temporal
weights are kept deliberately (no dataset substitution). The weights have
no *public* download source yet — the download scripts' CAMS fetches
point at aspirational geos-chem-bucket keys
(`HEMCO/CAMS-TEMPO/v3.1-2021/…`) and 404 until the data is published
there — but local copies in `data/` are honored. With local copies
present, the examples still fail on a **driver limitation**: AMIO's
staging pool is hardcoded (8 × 256 MB buffers, 30 s timeout) and the 0.1°
hourly/monthly weight variables (~622 MB / ~311 MB uncompressed) exceed a
buffer, so reads die with `AMIO_ERR_STAGING_BACKPRESSURE`. Resolving
requires a driver change (configurable staging pool or per-record
staging). The `--run-examples` green set is currently ex3–ex6; ex2 is
intermittently failing on a post-merge driver race (segfault during
stream ingest at default thread count) under investigation.

Known driver issue (2026-07-20): `amio_worker_threads` >= 2 segfaults
during stream ingest (ex7 pins it to 1 with a comment).

## Configuration sections

- `driver:` — `start_time` / `end_time` (ISO-8601), `timestep_seconds`,
  optional `log_file` and `amio_worker_threads`, and the nested `grid:`
  (either `grid_name` or `nx`/`ny` with lon/lat bounds).
- `species:` — per-species entry list: `field` (import name), `operation`
  (`add`/`replace`), optional `scale`, `scale_fields`, `mask`,
  `hierarchy`, `category`, `diurnal_cycle`.
- `cece_data.streams:` — one block per input stream: `file` (container
  path under `/work`), year window (`yearFirst`/`yearLast`/`yearAlign`),
  `taxmode`, `tintalgo`, `mapalgo`, optional `cadence`
  (`hourly`/`weekly`/`monthly`; absent = legacy cycling), and the
  file-variable → model-field `variables` mapping.
- `output:` — directory, `filename_pattern`, `frequency_steps`, `fields`.
- `diagnostics:`, `temporal_profiles:`, `meteorology:`,
  `physics_schemes:` — see `cece_config_advanced.yaml` /
  `cece_config_megan3.yaml` for physics usage.
