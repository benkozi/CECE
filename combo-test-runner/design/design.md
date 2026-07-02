# Combinatorial Test Runner — Design

## Goal

A standalone pytest-based test suite that exercises `cece_standalone_driver` across
every combination of the enum-valued configuration options defined in
`combo-test-runner/src/models/cece_config.py`. Each combination is rendered to a
YAML config, executed in an isolated Docker container, and passes if the driver
exits cleanly. A later phase adds output/error assertions.

## Non-goals (v1)

- No standalone CLI — pytest's command line is the only entry point.
- No dependency on existing CECE Python infrastructure; the runner lives in its
  own `uv`-managed environment under `combo-test-runner/`.
- No validation of NetCDF output contents. v1's pass criterion is driver exit
  code 0 (`subprocess.check_call` raises on nonzero).

## Combination space

`cece_config.py` defines six enums. A combination is one value chosen from each:

| Enum          | Values | Injected at                                  |
|---------------|--------|----------------------------------------------|
| `Operation`   | 2      | `species.<name>[0].operation`                 |
| `Category`    | 6      | `species.<name>[0].category`                  |
| `VdistMethod` | 3      | `species.<name>[0].vdist_method`              |
| `Taxmode`     | 2      | `cece_data.streams[0].taxmode`                |
| `Tintalgo`    | 2      | `cece_data.streams[0].tintalgo`               |
| `Mapalgo`     | 6      | `cece_data.streams[0].mapalgo`                |

Full cartesian product: **2 × 6 × 3 × 2 × 2 × 6 = 864 combinations**, i.e. 864
container runs per full suite execution.

Some enum values require companion fields to form a valid config; the generator
is responsible for supplying them:

- `VdistMethod.height` → set `vdist_h_start` / `vdist_h_end` to fixed sensible
  defaults (e.g. 0.0 / 100.0 m).
- `VdistMethod.pressure` → set `vdist_p_start` / `vdist_p_end` (e.g. 100000.0 /
  90000.0 Pa).

### Combination naming

Each combination gets a deterministic, filesystem-safe unique name built from
its enum values in a fixed order:

```
op-{operation}_cat-{category}_vd-{vdist}_tax-{taxmode}_tint-{tintalgo}_map-{mapalgo}
```

Example: `op-add_cat-anthropogenic_vd-PBL_tax-cycle_tint-linear_map-consd`

This name is used as the pytest parameter id, the per-combo directory name, and
the YAML filename — so `pytest -k 'map-consd and vd-PBL'` selects slices of the
suite for free.

## Base configuration

Combinations are diffs applied to a **base config** — a known-good
`CeceConfig` (modeled on `examples/cece_config_ex1.yaml`: single species `co`,
single `MACCITY` stream, coarse global grid, one-hour run). The base config is
defined in code (constructed as a `CeceConfig` instance) so the runner has zero
runtime dependency on files elsewhere in the repo. For each combination the
generator:

1. Deep-copies the base config.
2. Applies the six enum values (plus companion vdist fields) at the injection
   points above.
3. Points `output.directory` at the combo's own directory (see layout below).
4. Serializes with `CeceConfig.to_yaml()`.

## Directory layout (runtime artifacts)

All paths below are as seen **inside the container**, where the CECE repo root
is mounted at `/work`. The output root defaults to a directory under `/work` so
results persist on the host through the bind mount.

```
<output-root>/                        # configurable, default: /work/combo_runs
  op-add_cat-..._map-consd/           # one directory per combination
    op-add_cat-..._map-consd.yaml     # generated driver config
    *.nc                              # driver NetCDF output (output.directory
                                      #   in the yaml points here)
```

The generated YAML sets `output.directory` to
`<output-root>/<combo-name>/` so every artifact for a combination lives in one
place. Relative `--combo-output-root` values are resolved against `/work`.

Note: the original notes say the output root "will be relative to the /root
directory in the container". This design interprets that as the mounted repo
root (`/work`); writing under the container's `/root` home would be lost when
the container is removed. **Confirm this interpretation.**

## Execution model

Each combination runs independently in a fresh container using the image built
by `setup.sh` (`deckyfre/cece-dev`, assumed already built — the runner never
builds it). One driver invocation per container, container removed on exit
(`--rm`):

```
docker run --rm \
    -v <cece-repo-root>:/work \
    -w /work \
    -e OMPI_ALLOW_RUN_AS_ROOT=1 \
    -e OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1 \
    deckyfre/cece-dev \
    ./build/cece_standalone_driver <output-root>/<combo-name>/<combo-name>.yaml
```

Invoked with `subprocess.check_call(...)` — a nonzero driver exit raises
`CalledProcessError` and fails that combination's test. The environment
variables mirror `setup.sh` (the container runs as root and the driver calls
`MPI_Init`).

## Pytest integration

- **One test, parameterized by combo.** A session-scoped step generates all 864
  YAML files up front; a parameterized fixture hands each test a single YAML
  path (host path + matching container path). The test body is just the docker
  invocation.
- **Fail fast vs. continue** uses pytest built-ins — no custom flags:
  - continue (default): plain `pytest`
  - fail fast: `pytest -x` (or `--maxfail=N`)
- **Custom options** (registered in `conftest.py` via `pytest_addoption`):
  - `--combo-output-root=PATH` — root artifact directory (container-relative
    semantics as above; default `combo_runs`).
- **Selection**: `pytest -k <expr>` against the combo-name ids runs subsets.

## Settings

`pydantic-settings` (`BaseSettings`, env prefix `CECE_COMBO_`) supplies
environment-derived configuration, keeping the pytest CLI for run-shaping
options only:

| Setting          | Env var                     | Default              |
|------------------|-----------------------------|----------------------|
| `docker_image`   | `CECE_COMBO_DOCKER_IMAGE`   | `deckyfre/cece-dev`  |
| `cece_root`      | `CECE_COMBO_CECE_ROOT`      | repo root (derived)  |
| `driver_path`    | `CECE_COMBO_DRIVER_PATH`    | `./build/cece_standalone_driver` |
| `run_timeout_s`  | `CECE_COMBO_RUN_TIMEOUT_S`  | e.g. 300             |

## Code layout

All new code under `combo-test-runner/src/`; the project is `uv`-managed with
its own `pyproject.toml` at `combo-test-runner/`:

```
combo-test-runner/
  pyproject.toml          # uv project: pytest, pydantic>=2, pydantic-settings, pyyaml
  design/design.md
  src/
    models/cece_config.py # existing pydantic model of the driver config
    combos.py             # enum-product enumeration, combo naming, config generation
    runner.py             # docker run construction + subprocess.check_call
    settings.py           # pydantic-settings
    tests/
      conftest.py         # options, session fixture (generate yamls), param fixture
      test_driver_combos.py
```

Dependencies: `pytest`, `pydantic>=2`, `pydantic-settings`, `pyyaml`. Nothing
imported from the CECE repo outside `combo-test-runner/`.

## Future work

- **Suite configuration file**: YAML + pydantic config for the test suite
  itself (which enums to sweep, base-config overrides, per-combo excludes),
  replacing/augmenting the in-code base config.
- **Assertion step**: post-run evaluation that reads the produced NetCDF and/or
  captured driver output to assert on values and expected-error conditions,
  rather than exit code alone.
- Possible `pytest-xdist` parallelism — combinations are already fully isolated
  (own container, own directory), so `-n auto` should be safe.

## Open questions

1. **Output-root semantics**: confirm the `/work`-relative interpretation over
   the container's literal `/root` home directory.
2. **Full product vs. constrained product**: 864 serial container runs is a
   long suite. Is the full cartesian product intended for every run, with
   `-k` slicing for day-to-day use — or should v1 constrain the product (e.g.
   pairwise coverage)?
3. **Expected failures**: are all 864 combinations expected to be *valid*
   driver configs (exit 0), or are some enum combinations legitimately
   rejected by the driver? If the latter, v1 needs an expected-failure list
   before the assertion step lands.
4. **Data dependency**: the base config's stream references
   `/work/data/MACCity_4x5.nc`. Confirm that file is guaranteed present in the
   repo checkout that gets mounted.
