# combo-test-runner

Combinatorial pytest suite for `cece_standalone_driver`. Combinations of
enum-valued driver options (declared in a suite file, e.g.
`src/tests/config/suite/simple-maccity-suite.yaml`) are rendered to YAML
configs and each runs in its own Docker container, followed by per-combo
assertions on the output (exit code, file counts/names, attributes) and a
statistics/plotting analysis step. Design rationale lives in
[design/design.md](design/design.md).

## Prerequisites

- Docker, with the `cece/cece-dev` image available locally (build it via
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

To rebuild the driver and run the CECE C++ tests in the container (this
suite is separate — run it with `uv run pytest` as above), from any
directory:

```sh
<repo-root>/scripts/build-and-test-container.py            # build + C++ tests
<repo-root>/scripts/build-and-test-container.py --clean    # wipe build dirs first
<repo-root>/scripts/build-and-test-container.py --test-filter Configured  # gtest subset
# --no-build / --no-test skip a phase; --mount and --image override defaults
```

Driver output is printed after every driver call: with `-vs` (or `-s`) it
appears in the terminal as the suite runs; without `-s`, passing tests stay
quiet and failing tests include the output in their report under
"Captured stdout call".

Each combination produces one test per assertion/analysis step —
`test_driver_execution` (driver exits 0), `test_nc_file_count` (expected
NetCDF output count), `test_nc_filenames` (filenames match
`filename_pattern` at the expected write times), `test_species_attributes`
(the species variable's full attribute dictionary, one test per combo ×
configured species; `exact: true` — the default — requires the dictionaries
to match exactly, `exact: false` checks the expectation as a subset; per
value, `null` asserts absence and `"__ignore__"` allows any value),
`test_descriptive_stats` (per-NetCDF statistics via distributed dask,
written to `<combo_id>-stats.csv`; all combos concatenated into
`descriptive_stats.csv` at the output root when the session ends), and
`test_baseline_comparison` (nccmp-style comparison against a per-combination
baseline: each `baseline_comparisons` entry carries a `sweep_selector` —
mirroring the sweep structure with regexes at the leaves — that must select
exactly one combination, a baseline `ulid` under `CECE_BASELINE_ROOT_DIR`,
and an optional per-entry `atol`; structure and attributes exact, data
bit-for-bit or within `atol`; unselected combinations skip) — with the
driver running once per combination. If the driver run fails, its
`test_driver_execution` fails and that combination's assertion tests are
skipped with a `driver run failed: ...` reason.

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
    9004a4e23c1dd90a-comparison.yaml  # baseline comparison record (when configured)
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
| `CECE_DOCKER_IMAGE`             | container image                                | `cece/cece-dev`              |
| `CECE_ROOT`                     | host repo root mounted at /work                | derived from this checkout       |
| `CECE_DRIVER_PATH`              | driver path inside the container               | `./build/cece_standalone_driver` |
| `CECE_RUN_TIMEOUT_S`            | caps the suite `timeout_s` when smaller        | `300`                            |
| `CECE_LOG_LEVEL`                | runner log level (`DEBUG`, `INFO`, ...)        | `INFO`                           |
| `CECE_DASK_NWORKERS`            | dask workers for the stats cluster (int > 0)   | unset → all available cores      |
| `CECE_BASELINE_ROOT_DIR`        | baselines live at `<root>/<ulid>/`             | unset → current working directory |
| `CECE_ENABLE_BASELINE_COMPARISONS` | global switch; `false` skips comparison tests | `true`                           |
| `CECE_CONFIG_SEARCH_PATH`       | prepended to relative `config_path` values     | unset                            |
| `CECE_SUITE_CONFIG_SEARCH_PATH` | prepended to relative `--suite-config` values  | unset                            |
