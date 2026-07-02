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
uv run pytest                      # full suite; continues past failures (default)
uv run pytest -x                   # fail fast: stop at the first failure
uv run pytest -k map-consd         # run a subset by combo name
uv run pytest --combo-clean-root   # delete an existing output root first
```

Options:

- `--suite-config=PATH` — suite YAML defining the sweep
  (default: `combo-test-runner/suite.yaml`).
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

| Env var              | Meaning                          | Default                          |
|----------------------|----------------------------------|----------------------------------|
| `CECE_DOCKER_IMAGE`  | container image                  | `deckyfre/cece-dev`              |
| `CECE_ROOT`          | host repo root mounted at /work  | derived from this checkout       |
| `CECE_DRIVER_PATH`   | driver path inside the container | `./build/cece_standalone_driver` |
| `CECE_RUN_TIMEOUT_S` | per-run timeout (seconds)        | `300`                            |
