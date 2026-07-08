# Feature: post-run assertions — NetCDF file count — plus logging

## Goal

Start the evaluation step promised in the main design: after each driver run,
assert on what the run actually produced instead of trusting exit code 0
alone. The first assertion is **NetCDF output file count**
(`expected_nc_file_count`); the structure it lands in must accommodate the
further assertions that will follow. Alongside it, introduce a proper logger
for the runner with an environment-controlled level.

## Current behavior

- A test passes iff the driver exits 0 within the timeout. A driver that
  exits cleanly having written nothing (or written too much) still passes.
- No logging; visibility is limited to the printed driver output.

## Design

### Assertions block in the suite config

Assertions are suite-level configuration, grouped under an `assertions` key
so future assertions have an obvious home (the notes call for multiple
assertions eventually):

```yaml
# simple-maccity-suite.yaml
config_path: ../cece/simple-maccity.yaml
timeout_s: 10
assertions:
  expected_nc_file_count: null   # null/absent = derive from the combo config
sweep:
  mapalgo: [bilinear, consd, passthrough]
```

```python
class Assertions(BaseModel):
    expected_nc_file_count: int | None = Field(None, ge=0)

class SuiteConfig(BaseModel):
    config_path: Path
    timeout_s: int
    assertions: Assertions = Assertions()   # section optional; defaults apply
    sweep: Sweep
```

**Every test runs the assertion step** — there is no opt-out flag; the
"derive" default makes it meaningful without configuration.

### `expected_nc_file_count` modes

- **`None` (default) — derived.** The expected count is computed from the
  *generated combo config* (the `CeceConfig` the driver actually ran):

  ```
  n_steps  = (end_time - start_time) / timestep_seconds
  expected = n_steps // output.frequency_steps
  ```

  using `driver.start_time`, `driver.end_time`, `driver.timestep_seconds`
  (ISO-8601 strings parsed with `datetime.fromisoformat`), and
  `output.frequency_steps`. If the `output` section is absent or
  `output.enabled` is false, the derived expectation is 0.

  For the initial suite: 1 hour / 3600 s = 1 step, `frequency_steps: 1` →
  1 file, which matches observed driver behavior (one
  `cece_20100101_000000.nc` per combo).

- **Explicit int.** The count is asserted exactly as given; `0` means *no*
  NetCDF files are expected.

**Found count** = the number of `*.nc` files directly in that combination's
output directory (no recursion — everything the driver writes for a combo
lands flat in its directory).

The assertion runs after a successful driver call; a timed-out or nonzero
run already fails the test before assertions and asserts nothing new.

### Assertion module

New `src/assertions.py`, keeping test bodies thin and giving future
assertions a home:

```python
def assert_nc_file_count(combo_dir: Path, config: CeceConfig, expected: int | None) -> None
```

Derives `expected` when `None`, counts, logs (below), then asserts equality
with a pytest-friendly failure message naming the combo directory, expected,
and found counts.

### Logging

- Standard `logging` with per-module loggers under a shared
  `combo_test_runner` namespace.
- **Level from the environment**: new setting `log_level`
  (`CECE_LOG_LEVEL`, default `INFO`) on `settings.py`, e.g. `DEBUG` vs
  `INFO`. Applied once at session start (conftest) when configuring the
  namespace logger's handler.
- **Format includes a timestamp with seconds** (`%(asctime)s`), plus level
  and logger name.
- What gets logged:
  - the assertion itself, INFO, in the form from the notes:
    `testing expected_nc_file_count=1, found 1 files`
  - the derivation inputs when deriving, including the **timestep in
    seconds** — e.g.
    `deriving expected_nc_file_count: timestep_seconds=3600 n_steps=1 frequency_steps=1`
    (INFO; finer detail may sit at DEBUG as assertions grow).
- Visibility follows pytest's log capture: failure reports include
  "Captured log call" automatically; live output via `-s` or pytest's
  `log_cli` options.

## Non-goals

- No per-combination assertion overrides (suite-level only; per-combo
  expectations can come with the richer suite configuration future work).
- No content inspection of the NetCDF files or `.out` parsing — count only.
  Later assertions extend the `Assertions` model.

## Acceptance criteria

- Plain `uv run pytest`: all combos pass, each test log showing
  `testing expected_nc_file_count=1, found 1 files` (derived mode).
- A suite with `expected_nc_file_count: 0` fails against a driver run that
  produces files, with a clear assertion message (and passes when nothing is
  produced, e.g. output disabled).
- `CECE_LOG_LEVEL=DEBUG` raises verbosity; default INFO stays concise.
- Timeout/nonzero-exit behavior is unchanged.

## Resolved

- **Derivation formula confirmed**: `n_steps // frequency_steps`, no `+1`.
  The driver writes one file per `frequency_steps` timesteps — for the
  initial suite, exactly one file at the end of the first (only) timestep.
  The observed `cece_20100101_000000.nc` stamp does *not* indicate a t=0
  write: it is a **known bug in the driver under test** — that file should
  be stamped at hour 1 (`cece_20100101_010000.nc`, start time + one
  timestep). File *count* is unaffected, so this assertion passes despite
  the bug.

## Next assertion (planned, not this feature)

Output **timestamp verification**: assert the `.nc` filenames carry the
expected timestamps (first file at `start_time + timestep_seconds`, then
every `frequency_steps × timestep_seconds`). Against the current driver this
assertion is expected to *fail* on the hour-0 stamp, catching the bug above —
that is its purpose. It slots into the `Assertions` model as a second field.
