# combo-test-runner

Combinatorial pytest suite for `cece_standalone_driver`. Combinations of
enum-valued driver options (defined in `suite.yaml`) are rendered to YAML
configs and each is run in its own Docker container; a test passes if the
driver exits 0. Design rationale lives in [design/design.md](design/design.md).

## Prerequisites

- Docker, with the `deckyfre/cece-dev` image available locally (build it via
  `./setup.sh` at the repo root).
- The driver built at `./build/cece_standalone_driver` (repo root).
- [uv](https://docs.astral.sh/uv/) installed.

## Setup

```sh
cd combo-test-runner
uv sync
```

## Running

```sh
uv run pytest                      # everything: integration + runner harness tests
uv run pytest -vs                  # show each driver's output as it runs
uv run pytest -x                   # fail fast: stop at the first failure
uv run pytest -k map-consd         # run a subset by combo name
uv run pytest --combo-clean-root   # delete an existing output root first

uv run pytest src/tests/combo_test_runner      # runner harness only: fast, no docker
uv run pytest src/tests/test_driver_combos.py  # integration only (real docker)
```

Driver output is printed after every driver call: with `-vs` (or `-s`) it
appears in the terminal as the suite runs; without `-s`, passing tests stay
quiet and failing tests include the output in their report under
"Captured stdout call".

Each combination produces one test per assertion/analysis step —
`test_driver_execution` (driver exits 0), `test_nc_file_count` (expected
NetCDF output count), `test_nc_filenames` (filenames match
`filename_pattern` at the expected write times), and
`test_descriptive_stats` (per-NetCDF statistics via distributed dask,
written to `<combo>-stats.csv`; all combos concatenated into
`descriptive_stats.csv` at the output root when the session ends) — with the
driver running once per combination. If the driver run fails, its
`test_driver_execution` fails and that combination's assertion tests are
skipped with a `driver run failed: ...` reason.

**Known driver bug — expected failures**: the driver currently stamps output
at hour 0 instead of hour 1, so the three `test_nc_filenames` tests fail by
design until the driver is fixed. Set `validate_filenames: false` in the
suite's `assertions` block to skip them if you need a green run.

Options:

- `--suite-config=PATH` — suite YAML defining the suite's unique `name`
  (lowercase slug; by convention suite `X` lives in `X-suite.yaml`), the base
  driver config (`config_path`), the per-combination timeout (`timeout_s`),
  and the sweep — which mirrors the driver-config structure, attaching swept
  values to named streams (or positional species entries)
  (default: `src/tests/config/suite/simple-maccity-suite.yaml`). Use the
  `--suite-config=PATH` form (with `=`), not a space.
- `--combo-output-root=PATH` — root artifact directory; relative paths
  resolve against `/work` in the container, so results persist in the repo
  checkout. Default: a pytest-managed temporary directory (nothing is
  written to the checkout).
- `--combo-clean-root` — with an explicit `--combo-output-root`, remove an
  existing output root before running. Without it, an existing root is an
  error — prior results are never mixed with a new run.

## Results

By default results land in a pytest temp directory (printed paths in test
failures point there; pytest keeps the last few runs under e.g.
`/tmp/pytest-of-<user>/`). With `--combo-output-root=combo_runs` they land in
`combo_runs/` at the repo root. Either way, one directory per combination:

```
<output-root>/
  run.yaml                       # run manifest: session ULID + the resolved suite config
  combos.csv                     # maps combo directory ids to the tested combinations
  descriptive_stats.csv          # all combos' statistics, concatenated
  9004a4e23c1dd90a/              # one directory per combination (content-hash id)
    9004a4e23c1dd90a.yaml        # generated driver config
    9004a4e23c1dd90a.out         # captured driver stdout+stderr
    9004a4e23c1dd90a-stats.csv   # per-NetCDF descriptive statistics
    plots/                       # spatial plot per NetCDF + per-variable GIF
    *.nc                         # driver NetCDF output
```

Test ids stay human-readable (`MACCITY.map-consd`, target-qualified);
directories use a deterministic 16-char content hash of the combination so
names never outgrow filesystem limits. `combos.csv` dereferences ids back to
the swept dimensions; the same combination hashes to the same id in every
run, so ids are safe cross-run join keys.

Every run gets a runtime-generated ULID (`run_id`) — logged at session
start, written to `run.yaml`, and stamped into every stats row so CSVs from
different runs stay distinguishable. It is never set via configuration;
unknown keys in suite or driver config files are rejected at load time.

Spatial plots render at session end (suite `plotting.enabled`, default on;
`gif_enabled` controls the per-variable GIF). All plots of a variable share
one **exact suite-wide min/max color scale** derived from the descriptive
statistics — so plotting requires `compute_descriptive_stats`. First-time
boundary rendering downloads Natural Earth coastline/border data; offline,
plots degrade to data-only maps with a warning.

Stats CSV columns: `run_id`, `suite` (the suite's unique `name` from its
yaml, e.g. `simple-maccity`), identity (`combo_id`, `combo`, `file`,
`variable`), the file's
timestamp from its NetCDF time coordinate as `time` (ISO-8601) plus part
columns `year`/`month`/`day`/`hour`/`minute`/`second` for easy time
summaries (null if the file has no time coordinate), and the nan-aware
statistics (`count`, `sum`, `mean`, `std`, `min`, `max`, `median`).

## Environment variables

| Env var                         | Meaning                                        | Default                          |
|---------------------------------|------------------------------------------------|----------------------------------|
| `CECE_DOCKER_IMAGE`             | container image                                | `deckyfre/cece-dev`              |
| `CECE_ROOT`                     | host repo root mounted at /work                | derived from this checkout       |
| `CECE_DRIVER_PATH`              | driver path inside the container               | `./build/cece_standalone_driver` |
| `CECE_RUN_TIMEOUT_S`            | caps the suite `timeout_s` when smaller        | `300`                            |
| `CECE_LOG_LEVEL`                | runner log level (`DEBUG`, `INFO`, ...)        | `INFO`                           |
| `CECE_DASK_NWORKERS`            | dask workers for the stats cluster (int > 0)   | unset → all available cores      |
| `CECE_CONFIG_SEARCH_PATH`       | prepended to relative `config_path` values     | unset                            |
| `CECE_SUITE_CONFIG_SEARCH_PATH` | prepended to relative `--suite-config` values  | unset                            |
