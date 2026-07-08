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

Each combination produces one test per assertion — `test_driver_execution`
(driver exits 0), `test_nc_file_count` (expected NetCDF output count), and
`test_nc_filenames` (filenames match `filename_pattern` at the expected
write times) — with the driver running once per combination. If the driver
run fails, its `test_driver_execution` fails and that combination's
assertion tests are skipped with a `driver run failed: ...` reason.

**Known driver bug — expected failures**: the driver currently stamps output
at hour 0 instead of hour 1, so the three `test_nc_filenames` tests fail by
design until the driver is fixed. Set `validate_filenames: false` in the
suite's `assertions` block to skip them if you need a green run.

Options:

- `--suite-config=PATH` — suite YAML defining the base driver config
  (`config_path`), the per-combination timeout (`timeout_s`), and the sweep
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
  map-consd/
    map-consd.yaml   # generated driver config
    map-consd.out    # captured driver stdout+stderr
    *.nc             # driver NetCDF output
```

## Environment variables

| Env var                         | Meaning                                        | Default                          |
|---------------------------------|------------------------------------------------|----------------------------------|
| `CECE_DOCKER_IMAGE`             | container image                                | `deckyfre/cece-dev`              |
| `CECE_ROOT`                     | host repo root mounted at /work                | derived from this checkout       |
| `CECE_DRIVER_PATH`              | driver path inside the container               | `./build/cece_standalone_driver` |
| `CECE_RUN_TIMEOUT_S`            | caps the suite `timeout_s` when smaller        | `300`                            |
| `CECE_LOG_LEVEL`                | runner log level (`DEBUG`, `INFO`, ...)        | `INFO`                           |
| `CECE_CONFIG_SEARCH_PATH`       | prepended to relative `config_path` values     | unset                            |
| `CECE_SUITE_CONFIG_SEARCH_PATH` | prepended to relative `--suite-config` values  | unset                            |
