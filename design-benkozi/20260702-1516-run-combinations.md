# Run combinatorial configs in Docker (pytest suite)

## Goal

Execute every config produced by the combinatorial generator
(`design/feat/20260629-1132-combinatorial-generator.md`) through
`cece_standalone_driver`. The target command is the driver binary itself —
`./build/cece_standalone_driver <config.yaml>` — not
`cece-run-driver-combos.sh`; that bash script is only the reference for the
loop logic (recursively find YAML files, run the driver on each). The bash
script is never invoked, on the host or in a container.

The implementation **is** a pytest suite — there is no separate CLI
entrypoint or batch-loop function. Each combination is one parametrized test
case; pytest is the runner, reporter, and (via `-x`, `-k`, etc.) the
execution policy. The web app triggers runs by invoking pytest as a
subprocess with arguments.

**Isolation is the point.** Each configuration YAML runs the driver in its
own fresh Docker container — exactly one config per `docker run`, never a
batch — and the container is removed after each execution (`--rm`). No
process state, environment, or filesystem changes inside the container leak
from one combination to the next; only output written under the `/work`
mount persists. One test = one config = one container, so pytest reporting
maps 1:1 onto combination isolation.

## Assumptions

- CECE is already built: `build/cece_standalone_driver` exists in the CECE
  repo checkout at `/Users/bkoziol/sandbox/git-benkozi/CECE`.
- The dev image `deckyfre/cece-dev` (from `CECE/setup.sh` / `CECE/Dockerfile`)
  already exists locally; the suite does not build it.
- The CECE checkout is mounted at `/work` inside the container
  (`/work = /Users/bkoziol/sandbox/git-benkozi/CECE`), mirroring `setup.sh`.

## Module: `app/cece_combo_tester/` — portable by construction

The suite will move to the CECE project eventually, so it is a
self-contained directory the viewer only ever touches as a filesystem path.
Moving it is a `git mv` of the directory plus deleting the viewer-side glue.

```
app/cece_combo_tester/
  README.md             # how to run the suite standalone
  conftest.py           # pytest options + parametrization + fixtures
  runner.py             # ComboRun, find_configs, build_docker_command, run_combination
  test_combinations.py  # the single parametrized test
```

Independence rules:

- **Dependencies**: stdlib + pytest only. No imports from `app`, no
  pydantic, no Flask, no viewer `Settings`.
- **No `__init__.py`**: the directory is not part of the `app` package and
  is never imported by the viewer. Sibling imports (`import runner`) work
  because pytest prepends a rootdir-independent test directory to
  `sys.path` in its default import mode — the suite runs identically from
  this repo or from a future `CECE/tests/combos/` home. (mypy resolves
  `import runner` via `mypy_path = ["app/cece_combo_tester"]` in
  `pyproject.toml`.)
- **Configuration via pytest options only** (`--combos-root`, `--cece-root`,
  `--image`) — no environment variables, no settings file.
- **Not collected by default**: `testpaths = ["tests"]` in `pyproject.toml`
  (already set) keeps `uv run pytest` / the pre-commit hook away from this
  directory, which requires Docker and a built CECE. The suite runs only
  when its path is passed explicitly — which also makes its `conftest.py`
  an initial conftest, so `pytest_addoption` is honoured.

## Invocation

```
uv run pytest app/cece_combo_tester \
    --combos-root /path/to/generated/combos \
    [--cece-root /Users/bkoziol/sandbox/git-benkozi/CECE] \
    [--image deckyfre/cece-dev]
```

| Option | Description |
|---|---|
| `--combos-root` | Required. Host path to the root directory written by the combinatorial generator (one subdirectory per combination, each holding one config YAML) |
| `--cece-root` | Host path to the CECE checkout, mounted at `/work`. Default: `/Users/bkoziol/sandbox/git-benkozi/CECE` |
| `--image` | Docker image to run. Default: `deckyfre/cece-dev` |

Standard pytest flags compose naturally: `-x` for fail-fast (the bash
script's `set -e` behaviour), `-k taxmode-cycle` to run a subset of
combinations, `--junit-xml` for machine-readable results, and later
`pytest-xdist` for parallelism (safe, since container-per-run isolation
means no shared state between tests).

## `runner.py` (library core)

Pure stdlib, no pytest imports — usable from any future harness.

```python
@dataclass
class ComboRun:
    config: str      # config path relative to combos_root
    returncode: int  # 0 = success

def find_configs(combos_root: Path) -> list[Path]:
    """All *.yaml / *.yml files under combos_root, recursively, sorted."""

def build_docker_command(
    config: Path, combos_root: Path, cece_root: Path, image: str
) -> list[str]:
    """The full docker-run argv for one config."""

def run_combination(
    config: Path, combos_root: Path, cece_root: Path, image: str
) -> ComboRun:
    """Run one config in its own container; never raises on driver failure."""
```

`run_combination` is the atomic unit — one config, one container, one
`ComboRun`. It performs `subprocess.check_call(build_docker_command(...))`,
catching `CalledProcessError` and converting it to a `ComboRun` with the
failing return code, so the test body is a plain assertion and pytest owns
failure reporting.

## `conftest.py`

```python
def pytest_addoption(parser):
    parser.addoption("--combos-root", required=True, type=Path, ...)
    parser.addoption("--cece-root", type=Path,
                     default=Path("/Users/bkoziol/sandbox/git-benkozi/CECE"))
    parser.addoption("--image", default="deckyfre/cece-dev")

def pytest_generate_tests(metafunc):
    if "combo_config" in metafunc.fixturenames:
        root = metafunc.config.getoption("--combos-root")
        configs = find_configs(root)
        metafunc.parametrize(
            "combo_config",
            configs,
            ids=[str(c.parent.relative_to(root)) for c in configs],  # param slug
        )
```

Plus session-scoped `combos_root`, `cece_root`, and `image` fixtures that
read the options and validate the directories exist (fail at setup with a
clear message rather than mid-run). An empty `--combos-root` (no YAML files)
fails collection — an empty root almost certainly means the wrong directory
was passed.

Test ids come from the combination subdirectory name (the param slug), so a
failing combination is identifiable directly from pytest output, e.g.
`test_combination[taxmode-cycle__tintalgo-nearest]`.

## `test_combinations.py`

```python
def test_combination(combo_config, combos_root, cece_root, image):
    result = run_combination(combo_config, combos_root, cece_root, image)
    assert result.returncode == 0
```

## Container invocation

One `docker run` per config file — a fresh container per combination,
removed on exit via `--rm`. The run configuration mirrors `CECE/setup.sh`
command mode (`/work` mount, `/work` workdir, OMPI root env vars), plus a
second read-only mount exposing the generated configs:

```
docker run --rm \
    -v {cece_root}:/work \
    -v {combos_root}:/configs:ro \
    -w /work \
    -e OMPI_ALLOW_RUN_AS_ROOT=1 \
    -e OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1 \
    {image} \
    ./build/cece_standalone_driver /configs/{config_rel_path}
```

`config_rel_path` is the config's path relative to `--combos-root`, e.g.
`taxmode-cycle__tintalgo-linear/cece_config_ex1__20260629T113245Z.yaml`.

The `/configs` mount is read-only on purpose: the driver reads the config
from there but writes all simulation output under `/work` (see Notes on
`sim_output_root`).

## Web app integration (combinatorial workflow)

The web app does not import the suite — it shells out to pytest, exactly as
a user would, passing configuration as pytest arguments.

`app.settings.Settings` gains the two host-side defaults (env-overridable
via the existing `CECE_*` prefix); they exist only to build the pytest
command line:

```python
class Settings(BaseSettings):
    ...
    cece_root: Path = Path("/Users/bkoziol/sandbox/git-benkozi/CECE")
    cece_image: str = "deckyfre/cece-dev"
```

### `POST /combinatorial/run`

| Field | Description |
|---|---|
| `root_dir` | The combos root directory (host path), as returned by `POST /combinatorial/generate` |

The route validates `root_dir` (exists, contains at least one YAML), then
runs:

```python
subprocess.run(
    [
        sys.executable, "-m", "pytest", str(COMBO_TESTER_DIR),
        f"--combos-root={root_dir}",
        f"--cece-root={settings.cece_root}",
        f"--image={settings.cece_image}",
        f"--junit-xml={junit_path}",   # temp file
    ],
    ...
)
```

where `COMBO_TESTER_DIR = Path(app.__file__).parent / "cece_combo_tester"` —
a path reference, not an import, so relocating the suite means updating one
constant. The route parses the JUnit XML (stdlib `xml.etree`) into
per-combination results and returns JSON:

```json
{
  "root_dir": "/abs/path/to/root",
  "ok": true,
  "runs": [
    {"config": "taxmode-cycle__tintalgo-linear", "passed": true},
    {"config": "taxmode-cycle__tintalgo-nearest", "passed": false}
  ]
}
```

`ok` mirrors the pytest exit code (0 = all passed). The full matrix runs by
default — no fail-fast — since the web user wants the complete pass/fail
picture; pytest exit codes ≥ 2 (usage/collection errors) surface as
`{"error": …}` with the captured stderr. Validation errors return
`{"error": "…"}` with status 400, matching the generator routes.

### UI

On the `combinatorial.html` results view (shown after a successful
`POST /combinatorial/generate`), add a **Run combinations** button. JS posts
the just-returned `root_dir` to `/combinatorial/run`, disables the button
while the request is in flight ("Running…"), and renders the per-config
list with pass/fail markers when the response arrives.

### Constraints

- **Synchronous v1.** The request blocks until pytest finishes, like the
  app's existing long-running dask computations. Fine for small products; a
  background subprocess + status-polling route is the natural upgrade if
  runs outgrow request timeouts.
- The Flask process must be able to run `docker` (i.e. the app runs on the
  host, not inside its own container — or the compose setup mounts the
  Docker socket).
- Remember the `sim_output_root` note below: configs generated for the
  button must be generated with container-visible output paths.

## Viewer-side tests (`tests/test_run_combinations.py`)

These test the viewer's glue and unit-test `runner.py` with mocked
`subprocess` — no Docker in CI. They import `runner` by inserting
`app/cece_combo_tester` into `sys.path` (the same sibling-import convention
the suite itself uses); they are viewer-repo-only and move or retire with
the suite.

- `test_find_configs_recursive` — finds `.yaml` and `.yml` in nested subdirs
- `test_find_configs_sorted` — deterministic ordering
- `test_find_configs_ignores_other_files` — non-YAML files skipped
- `test_build_docker_command` — exact argv: `--rm`, both mounts (`/configs`
  read-only), `-w /work`, both OMPI env vars, image, driver path,
  `/configs/{rel}` config path
- `test_run_combination_success` — one config → one `check_call` with the
  built argv; `ComboRun` with returncode 0
- `test_run_combination_failure_returns_code` — `CalledProcessError(3, …)`
  → `ComboRun` with returncode 3, no exception
- `test_run_route_success` — `POST /combinatorial/run` with mocked
  `subprocess.run` + canned JUnit XML → 200, `ok: true`, per-config runs
- `test_run_route_failure_reported` — canned XML with a failure → 200 with
  `ok: false` and `passed: false` on the failing entry
- `test_run_route_bad_root_400` — missing dir / no YAMLs → 400 with
  `{"error": …}`
- `test_run_route_pytest_error` — mocked exit code 4 → error JSON with
  stderr detail

The combo suite has no self-tests: its correctness is covered by the unit
tests above while it lives here, and by actually running combinations.

## Decisions

- **pytest is the only entrypoint**: no `main()`, no batch-loop function.
  Execution policy (fail-fast, subsetting, parallelism, reporting) is
  delegated to pytest flags instead of being re-implemented; the web app
  invokes pytest as a subprocess like any other user.
- **Portable directory, one-way dependency**: `app/cece_combo_tester/`
  depends on nothing in the viewer; the viewer references it only as a
  path (route) or via `sys.path` (its unit tests). Moving it to CECE is a
  directory move.
- **No `__init__.py`, sibling imports**: keeps the suite importable and
  runnable regardless of which repo it sits in; default collection is
  excluded via the existing `testpaths = ["tests"]`.
- **`run_combination` never raises on driver failure**: returns the exit
  code in `ComboRun`, so the test is a plain assertion and non-pytest
  harnesses can reuse the function.
- **Second mount instead of requiring configs inside the CECE tree**: the
  generator writes `--combos-root` anywhere on the host (typically in this
  repo's workspace, not the CECE checkout). Mounting it at `/configs:ro`
  avoids polluting the CECE git working tree and keeps the `/work` mount
  exactly as specified in `setup.sh`.
- **JUnit XML as the route's result channel**: stdlib-parseable, stable
  pytest feature, no plugin dependency; the param-slug test ids carry the
  combination identity through to the JSON response.
- **No image build**: unlike `setup.sh`, the suite never builds the image —
  a missing image is a hard error from `docker run`.

## Notes

- **Simulation output paths must be container paths.** The driver reads
  `output.directory` from the YAML *inside* the container, so host paths like
  `/Users/…` won't resolve. Generate the configs with `sim_output_root` set to
  a path under `/work` (e.g. `/work/cece_output/combos`) so each combination
  writes to `/work/cece_output/combos/{param_slug}`, which lands in the CECE
  checkout on the host via the mount. This is exactly the use case
  `sim_output_root` was added for in the generator design.
- Containers run as root (hence the `OMPI_ALLOW_RUN_AS_ROOT*` vars); output
  files created under `/work` may be root-owned on Linux hosts. On macOS
  (Docker Desktop) ownership is mapped to the host user, so this is a
  non-issue for the current environment.
- The driver is invoked with a relative path (`./build/cece_standalone_driver`)
  from `-w /work`, matching `cece-run-driver-combos.sh`.
- When the suite moves to CECE, the `--cece-root` default can become "the
  repo the suite lives in" and the viewer's `COMBO_TESTER_DIR` constant
  points at the CECE checkout instead.
