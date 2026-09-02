# CECE Configuration Examples

Example YAML configurations demonstrating CECE capabilities, living in
`examples/config/`. Every `cece_config_ex*.yaml` is expected to run green.

Two stdlib-Python entrypoints drive everything; both accept
`--example <id[,id...]>` (ids like `ex1` or `megan3`), `--all`, and
`--dst-dir <path>` (default `data/`, created if missing). The example →
data mapping lives in `examples/common.py`; input data comes from
public S3 buckets (`geos-chem`, and `noaa-ufs-srw-pds` for the EDGAR-HTAP
sector files) into `data/`, skipping files that are already present and
non-empty.

## Running an example

`run-example.py` downloads any missing data, then **executes the driver
binary directly — no docker is spawned**, so the same command works inside
the dev container and natively (e.g. HPC platforms without docker; set
`CECE_EXAMPLES_DRIVER_PATH` if the driver is not at
`build/cece_standalone_driver`).

```bash
# natively, from the repo root (driver built, python3 >= 3.11):
python3 examples/run-example.py --example ex3

# or inside the dev container:
docker run --rm -v "$PWD":/work -w /work \
    cece/cece-dev python3 examples/run-example.py --example ex3

# download data only (e.g. to prefetch several examples):
python3 examples/download-example-data.py --example ex1,ex7
python3 examples/download-example-data.py --all
```

## The examples

| Example | Lesson | Data |
|---|---|---|
| `ex1` | Multi-sector NO with hourly/weekly/monthly temporal scale factors | EDGAR-HTAP v2015-03 per-sector NO files (TRANSPORT/SHIPS/RESIDENTIAL/INDUSTRY/ENERGY) + CAMS-TEMPO v3.1 weights (*local copies; no public download source yet*) |
| `ex2` | Regional masking: hierarchy + mask-scoped `replace` | MACCity CO, CEDS 1970 CO, mask file |
| `ex3` | Minimal smoke test (2x2 grid, 1 step) | MACCity CO |
| `ex4` | High-resolution (0.1°) inventory regridded to a coarse grid, 24 steps | HTAPv3 2018 shipping NO |
| `ex5` | Two species, two streams, monthly diagnostics cadence | MACCity CO + NOx |
| `ex6` | Multi-stream additive NO from two inventories | EDGAR v4.3 NOx POW, CEDS 1970 ALK4 (agr sector) |
| `ex7` | ex1 + explicit stream `cadence` handling + `amio_worker_threads` | as ex1 |
| `advanced`, `megan3` | Physics schemes (megan, sea_salt, bdsnp, megan3) with met inputs — not part of the automated example gate | see file headers |

Data provenance: ex1/ex7 use their **original** EDGAR-HTAP v2015-03
sector files, publicly fetched from the `noaa-ufs-srw-pds` bucket
(`…/fix/fix_emis/HTAP/v2015-03/NO/`). ex2's original EMEP data is not
publicly available; it uses CEDS instead.

**Known gap — CAMS-TEMPO has no public download source yet**: ex1/ex7's
v3.1 temporal weights are kept deliberately (no dataset substitution)
and **run green from local copies in `data/`** — all seven examples
pass. The CAMS entries in the data mapping point at aspirational
geos-chem-bucket keys (`HEMCO/CAMS-TEMPO/v3.1-2021/…`) and 404 until the
data is published there, so a download-then-run from a *fresh* machine
fails for ex1/ex7 until then. Note the hourly file must be the
`(time, latitude, longitude)`-ordered variant — a dimensionally
mis-ordered copy makes AMIO fail with a misleading
`AMIO_ERR_STAGING_BACKPRESSURE`.

Historical note (resolved 2026-07-23): `amio_worker_threads` >= 2 used to
crash, and ex2 could intermittently segfault — both caused by one
unserialized netCDF metadata path in AMIO's driver
(`describe_variable`) racing concurrent reads; fixed by completing the
driver's mutex discipline. ex7 now runs with `amio_worker_threads: 2`
as the regression check.

## Configuration sections

- `driver:` — `start_time` / `end_time` (ISO-8601), `timestep_seconds`,
  optional `log_file` and `amio_worker_threads`, and the nested `grid:`
  (either `grid_name` or `nx`/`ny` with lon/lat bounds).
- `species:` — per-species entry list: `field` (import name), `operation`
  (`add`/`replace`), optional `scale`, `scale_fields`, `mask`,
  `hierarchy`, `category`, `diurnal_cycle`.
- `cece_data.streams:` — one block per input stream: `file` (relative
  `data/…` path, resolved against the repo-root working directory in any
  environment), year window (`yearFirst`/`yearLast`/`yearAlign`),
  `taxmode`, `tintalgo`, `mapalgo`, optional `cadence`
  (`hourly`/`weekly`/`monthly`; absent = legacy cycling), and the
  file-variable → model-field `variables` mapping.
- `output:` — directory, `filename_pattern`, `frequency_steps`, `fields`.
- `diagnostics:`, `temporal_profiles:`, `meteorology:`,
  `physics_schemes:` — see `cece_config_advanced.yaml` /
  `cece_config_megan3.yaml` for physics usage.
