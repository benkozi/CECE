# Combinatorial Test Runner — Design

## Goal

A standalone pytest-based test suite that exercises `cece_standalone_driver`
across combinations of the enum-valued configuration options defined in
`combo-test-runner/src/models/cece_config.py`. The combinations to sweep are
declared in a YAML **suite configuration** validated by pydantic. Each
combination is rendered to a driver YAML config, executed in an isolated
Docker container with its stdout/stderr captured to a per-combo `.out` file,
and passes if the driver exits 0. A later phase adds assertions that inspect
the captured output and NetCDF output.

## Non-goals (v1)

- No standalone CLI — pytest's command line is the only entry point.
- No dependency on existing CECE Python infrastructure; the runner lives in its
  own `uv`-managed environment under `combo-test-runner/`.
- No validation of NetCDF output contents or captured driver output. v1's
  pass criterion is driver exit code 0.

## Suite configuration

The sweep is defined in a YAML file loaded into a pydantic model — not
hardcoded. Each entry names an enum dimension and lists the values to sweep;
enums absent from the file are **not swept** and stay at their base-config
values. The combination space is the cartesian product of the listed values.

```yaml
# simple-maccity-suite.yaml — initial suite
config_path: ../cece/simple-maccity.yaml   # base driver config (suite-relative)
timeout_s: 10                              # per combination; capped by CECE_RUN_TIMEOUT_S
assertions:
  expected_nc_file_count: null             # null = derive from the combo config
  validate_filenames: true                 # false skips the filename tests
sweep:
  mapalgo: [bilinear, consd, passthrough]
```

```python
class Sweep(BaseModel):
    operation: list[Operation] | None = None
    category: list[Category] | None = None
    vdist_method: list[VdistMethod] | None = None
    taxmode: list[Taxmode] | None = None
    tintalgo: list[Tintalgo] | None = None
    mapalgo: list[Mapalgo] | None = None

class SuiteConfig(BaseModel):
    config_path: Path   # base CECE driver config; relative → suite-file dir
    timeout_s: int      # per-combination driver timeout (seconds)
    sweep: Sweep
```

A suite file fully describes a run: which base scenario (`config_path`),
the per-combination timeout, and which sweep. Full `config_path` resolution
and timeout semantics live in
`design/feat/20260707-1515-use-cece-config-directory.md`.

Reusing the enums from `cece_config.py` means invalid values fail at suite-load
time with a pydantic error, before any container runs.

The **initial suite** sweeps only `Mapalgo` over `bilinear`, `consd`, and
`passthrough` — 3 combinations. The full 6-enum product (864 combinations)
remains expressible later purely by editing the suite YAML.

The suite file path is a pytest option (`--suite-config`, default:
`combo-test-runner/src/tests/config/suite/simple-maccity-suite.yaml`,
checked in with the initial sweep).

## Combination space

Where each enum dimension is injected into the driver config:

| Enum          | Values | Injected at                                  |
|---------------|--------|----------------------------------------------|
| `Operation`   | 2      | `species.<name>[0].operation`                 |
| `Category`    | 6      | `species.<name>[0].category`                  |
| `VdistMethod` | 3      | `species.<name>[0].vdist_method`              |
| `Taxmode`     | 2      | `cece_data.streams[0].taxmode`                |
| `Tintalgo`    | 2      | `cece_data.streams[0].tintalgo`               |
| `Mapalgo`     | 6      | `cece_data.streams[0].mapalgo`                |

Some enum values require companion fields to form a valid config; the generator
supplies them:

- `VdistMethod.height` → set `vdist_h_start` / `vdist_h_end` to fixed sensible
  defaults (e.g. 0.0 / 100.0 m).
- `VdistMethod.pressure` → set `vdist_p_start` / `vdist_p_end` (e.g. 100000.0 /
  90000.0 Pa).

### Combination naming

Each combination gets a deterministic, filesystem-safe unique name built from
the **swept dimensions only**, in a fixed canonical order
(`op`, `cat`, `vd`, `tax`, `tint`, `map`):

- Initial suite: `map-bilinear`, `map-consd`, `map-passthrough`
- A hypothetical two-dimension sweep: `op-add_map-consd`, …

This name is used as the pytest parameter id, the per-combo directory name, and
the YAML filename — so `pytest -k <expr>` selects slices of the suite for free.
Unswept dimensions are omitted from the name; they are constant across the run
and recorded in the generated YAML itself.

## Base configuration

Combinations are diffs applied to a **base config** — a known-good driver
config selected by the suite's `config_path` (the initial
`src/tests/config/cece/simple-maccity.yaml`, modeled on
`examples/cece_config_ex1.yaml`: single species `co`, single `MACCITY` stream
reading `/work/data/MACCity_4x5.nc`, coarse global grid, three-hour run). Base
configs live inside `combo-test-runner/`, preserving zero runtime dependency
on files elsewhere in the repo. For each combination the generator:

1. Loads the base config via `CeceConfig.from_yaml(config_path)`.
2. Applies the swept enum values (plus companion vdist fields) at the
   injection points above.
3. Points `output.directory` at the combo's own directory (see layout below).
4. Serializes with `CeceConfig.to_yaml()`.

**Requirement — all config construction goes through `cece_config.py`.**
Every generated driver config is built as a `CeceConfig` model instance
(base config and per-combo mutations alike) and written to disk only via
`CeceConfig.to_yaml()`. No hand-assembled dicts, string templates, or direct
`yaml.dump` calls anywhere in the generator. This guarantees every config the
driver receives has passed pydantic validation, and keeps serialization
behavior (`exclude_none`, key ordering, the YAML 1.2 boolean handling in
`cece_config.py`) in one place. If a combination needs a field the model
doesn't have, the fix is to extend `cece_config.py` — not to bypass it.

## Directory layout (runtime artifacts)

**By default, all test-generated data — combo yamls, captured output, NetCDF —
is written to a pytest-managed temporary directory** (session-scoped
`tmp_path_factory`, the machinery behind the `tmp_path` fixture). Nothing
lands in the repo checkout and nothing needs git-ignoring; pytest keeps the
last few runs under its base temp dir and prunes older ones.

Passing `--combo-output-root=PATH` opts out of the temp default: the path is
then interpreted as container-relative, resolved against `/work` (the mounted
repo root), so results persist in the checkout.

Layout under the output root is the same either way:

```
<output-root>/                 # default: pytest tmp dir; else /work-relative
  run.yaml                     # RunManifest: session ULID + resolved suite config
  descriptive_stats.csv        # all combos' statistics, concatenated at session end
  map-consd/                   # one directory per combination
    map-consd.yaml             # generated driver config
    map-consd.out              # captured driver stdout+stderr (".log" is
                               #   reserved for a future real driver log file)
    *.nc                       # driver NetCDF output (output.directory in
                               #   the yaml points here)
```

Everything produced by or for a combination — config, captured output,
NetCDF — lives in that combination's directory.

The output root must not exist when a session starts: an existing root fails
the run immediately unless `--combo-clean-root` is passed, which removes the
old root first (see Pytest integration). Each run therefore always starts
from an empty root. This check only has teeth for an explicit
`--combo-output-root`; the default pytest temp root is freshly created every
session and can never pre-exist.

## Execution model

Each combination runs independently in a fresh container using the image built
by `setup.sh` (`deckyfre/cece-dev`, assumed already built — the runner never
builds it). One driver invocation per container, container removed on exit
(`--rm`):

```
docker run --rm \
    -v <host-cece-repo-root>:/work \   # bind mount: <host path>:<container path>
    -w /work \                         # working directory inside the container
    -e OMPI_ALLOW_RUN_AS_ROOT=1 \
    -e OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1 \
    deckyfre/cece-dev \
    ./build/cece_standalone_driver <output-root>/<combo-name>/<combo-name>.yaml
```

The `-v` flag carries the host→container mapping: the host-side CECE repo
root (the `root` setting, `CECE_ROOT`) maps to `/work` in the container. The
`-w` flag takes a container path only — it sets the driver's working
directory to the mounted repo root, so the relative `./build/...` driver path
and `/work`-relative config paths resolve correctly.

When the output root is the default pytest temp directory, it lies outside
the repo and therefore outside the `/work` mount — the command gains a second
bind mount, `-v <host-tmp-root>:/combo_runs`, and the generated configs and
driver arguments reference the output root as `/combo_runs`. With an explicit
`--combo-output-root` the output root already lives under `/work` and no
extra mount is added.

Invoked with `subprocess.check_output(..., stderr=subprocess.STDOUT)` so the
driver's combined stdout/stderr is captured. The runner writes the captured
output to `<combo-name>.out` in the combo directory **whether the run passes
or fails** (on failure, `CalledProcessError.output` carries the text; the
runner writes the capture, then re-raises so the test fails). A nonzero driver
exit is the failure condition. The environment variables mirror `setup.sh`
(the container runs as root and the driver calls `MPI_Init`).

## Pytest integration

- **One test per assertion, parameterized by combo.** A session-scoped step
  loads the suite config and generates all combo YAML files up front. The
  driver runs once per combination in a combo-parameterized, session-scoped
  fixture that captures the outcome without raising; `test_driver_execution`
  asserts exit 0, and each post-run assertion (`test_nc_file_count`, …) is
  its own test that skips explicitly when the run failed. See
  `design/feat/20260708-1055-add-assertions-for-file-counts.md`.
- **Fail fast vs. continue** uses pytest built-ins — no custom flags.
  **Continue is the default and the desired behavior**: a plain `pytest`
  invocation runs every combination to completion regardless of individual
  failures, so one bad combo never hides results for the rest. Fail-fast is
  opt-in via `pytest -x` (first failure) or `--maxfail=N`.
- **Custom options** (registered in `conftest.py` via `pytest_addoption`):
  - `--suite-config=PATH` — suite YAML defining the sweep (default:
    `combo-test-runner/suite.yaml`).
  - `--combo-output-root=PATH` — root artifact directory (container-relative
    semantics as above). Default: unset, meaning a pytest-managed temporary
    directory via session-scoped `tmp_path_factory`.
  - `--combo-clean-root` — flag; if an explicitly given output root already
    exists, remove it (`shutil.rmtree`) before generating configs. Has no
    effect with the default temp root, which is always freshly created.
- **Existing explicit output root is an error by default.** When
  `--combo-output-root` is given, the runner checks at session start — before
  any configs are generated or containers run — whether that root exists on
  the host. If it does and `--combo-clean-root` was not given, the session
  fails immediately with a clear message — prior results are never silently
  mixed with or overwritten by a new run. With `--combo-clean-root`, the
  existing root is deleted wholesale and recreated. The rmtree targets only
  the resolved output root, never its parent. The default temp root needs no
  guard: `tmp_path_factory` allocates a fresh directory every session.
- **Selection**: `pytest -k <expr>` against the combo-name ids runs subsets.

## Settings

`pydantic-settings` (`BaseSettings`, env prefix `CECE_`) supplies
environment-derived configuration, keeping the pytest CLI for run-shaping
options only. The prefix is deliberately `CECE_` rather than something
runner-specific: the settings class may later host other variable groups
beyond the test runner.

| Setting          | Env var               | Default              |
|------------------|-----------------------|----------------------|
| `docker_image`   | `CECE_DOCKER_IMAGE`   | `deckyfre/cece-dev`  |
| `root`           | `CECE_ROOT`           | repo root (derived)  |
| `driver_path`    | `CECE_DRIVER_PATH`    | `./build/cece_standalone_driver` |
| `run_timeout_s`  | `CECE_RUN_TIMEOUT_S`  | 300 — caps the suite's `timeout_s` when smaller |
| `log_level`      | `CECE_LOG_LEVEL`      | `INFO`               |
| `dask_nworkers`  | `CECE_DASK_NWORKERS`  | unset → all available; else int > 0 |
| `config_search_path`       | `CECE_CONFIG_SEARCH_PATH`       | unset |
| `suite_config_search_path` | `CECE_SUITE_CONFIG_SEARCH_PATH` | unset |

The search-path settings, when set, override normal config resolution: the
search directory is prepended to the provided (relative) suite/CECE config
path, which is kept whole so nested directories work. Full semantics live in
`design/feat/20260707-1515-use-cece-config-directory.md`.

## Code layout

All new code under `combo-test-runner/src/`; the project is `uv`-managed with
its own `pyproject.toml` at `combo-test-runner/`:

```
combo-test-runner/
  pyproject.toml          # uv project: pytest, pytest-mock, pydantic>=2, pydantic-settings, pyyaml
  README.md               # user-facing setup + run instructions
  design/design.md
  src/
    models/
      base.py             # StrictModel: extra="forbid" base for all config models
      cece_config.py      # existing pydantic model of the driver config
      suite_config.py     # SuiteConfig / Sweep / RunManifest models + YAML loader
    analysis.py           # descriptive stats (dask distributed), CSV writing
    assertions.py         # post-run assertions (NetCDF file count, filenames)
    combos.py             # sweep → combinations, combo naming, config generation
    logs.py               # namespace logger, level from CECE_LOG_LEVEL
    resolution.py         # pure path-resolution rules (suite path, output roots)
    runner.py             # docker run construction, check_output, .out writing,
                          #   DriverRunResult
    settings.py           # pydantic-settings
    tests/
      config/
        cece/simple-maccity.yaml          # base driver config
        suite/simple-maccity-suite.yaml   # initial suite (--suite-config default)
      combo_test_runner/  # the runner's own tests: mocked process call, no docker
      conftest.py         # options, session fixture (generate yamls), param fixture
      test_driver_combos.py               # integration tests (real docker)
```

Dependencies: `pytest`, `pytest-mock`, `pydantic>=2`, `pydantic-settings`,
`python-ulid`, `pyyaml`, and the analysis stack (`pandas`, `xarray`,
`netcdf4`, `dask[distributed]`). Nothing
imported from the CECE repo outside `combo-test-runner/`.

## README (user documentation)

A `combo-test-runner/README.md` ships with v1 — deliberately simple at this
stage: enough for a user to set up and run the suite. It covers:

- **Prerequisites**: Docker with the `deckyfre/cece-dev` image available
  (built via `./setup.sh` at the repo root), the driver built at
  `./build/cece_standalone_driver`, and `uv` installed.
- **Setup**: `cd combo-test-runner && uv sync`.
- **Running**:
  - full suite: `uv run pytest`
  - fail fast: `uv run pytest -x`
  - a subset: `uv run pytest -k map-consd`
  - alternate suite file / output root: `--suite-config`,
    `--combo-output-root`
  - rerun over an existing output root: `--combo-clean-root` (without it,
    an existing root is an error)
- **Where results land**: the per-combo directory layout (yaml, `.out`,
  NetCDF) under the output root.
- **Environment variables**: the `CECE_*` settings table.

The README grows alongside future features (evaluation step, richer suite
config) but stays a quick-start document; design rationale lives here, not
there.

## Future work

- **Assertion / evaluation step**: post-run evaluation that inspects the
  captured driver output (already persisted per combo as `.out`), eventual
  real driver log files, and the produced NetCDF
  to assert on values and expected-error conditions, rather than exit code
  alone.
- **Richer suite configuration**: base-config overrides, per-combo excludes /
  expected-failure lists, multiple named sweeps in one file.
- Possible `pytest-xdist` parallelism — combinations are already fully isolated
  (own container, own directory), so `-n auto` should be safe.

## Resolved decisions

- Test-generated data goes to a pytest temp directory by default (mounted
  into the container at `/combo_runs`), so the repo checkout stays clean and
  no `.gitignore` entries are needed. An explicit `--combo-output-root` opts
  into a `/work`-relative root that persists in the checkout. Either way the
  root is bind-mounted, so artifacts survive `--rm`.
- Input data (`/work/data/MACCity_4x5.nc`) is guaranteed present in the
  mounted checkout.
- Exit code 0 is the sole pass criterion for v1; log/NetCDF inspection comes
  with the future evaluation step.
- The sweep is YAML-configured from day one; the initial suite covers only
  `mapalgo ∈ {bilinear, consd, passthrough}` (3 runs), not the 864-combo full
  product.
- Every YAML-backed config model (the full `CeceConfig` and `SuiteConfig`
  hierarchies, plus `RunManifest`) inherits `models/base.py:StrictModel`
  (`extra="forbid"`): unknown keys at any nesting level fail at load time
  instead of being silently dropped. Each run is identified by a runtime
  ULID — logged at session start, stamped into every stats row (`run_id`),
  and recorded with the resolved suite in `<output-root>/run.yaml`; it is
  never read from configuration.
- Data-carrying objects (`ComboRoots`, `GeneratedCombo`, `DriverRunResult`)
  are frozen pydantic models, consistent with the config models — not
  dataclasses. The exception is the enumeration machinery in `combos.py`
  (`Dimension`, `Combo`), which holds callables and generic enum members
  that pydantic cannot deep-validate; those stay dataclasses and are
  isinstance-checked (`InstanceOf`) where they appear as model fields.
