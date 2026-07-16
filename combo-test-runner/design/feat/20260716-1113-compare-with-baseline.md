# Feature: baseline comparison of combination NetCDF output

## Goal

Optionally compare each combination's NetCDF output against a **baseline** —
the payoff the stats/ids groundwork has been building toward. Pairing is at
the **combination** level (not every combination has a baseline), baselines
are identified by **ULID**, and the comparison models `nccmp`: bit-for-bit
by default, tolerance-based on request, with structural checks (files,
formats, dimensions, variables, attributes) always exact. Every comparison
produces a YAML results artifact from a pydantic model.

## Design

### Suite config: the `baseline_comparison` block

```yaml
baseline_comparison:
  atol: 0.0                                # default: bit-for-bit; > 0 = absolute tolerance
  baselines:                               # combination name -> baseline ULID
    MACCITY.map-bilinear: 01K0AAAAAAAAAAAAAAAAAAAAAA
    MACCITY.map-consd:    01K0BBBBBBBBBBBBBBBBBBBBBB
```

```python
class BaselineComparison(StrictModel):
    atol: float = Field(0.0, ge=0, description="0 = bit-for-bit; > 0 = absolute tolerance for data comparison")
    baselines: dict[str, str] = Field(default_factory=dict, description="Combination name -> baseline ULID")

class SuiteConfig(StrictModel):
    ...
    baseline_comparison: BaselineComparison | None = Field(None, description="Baseline comparison; None disables it entirely")
```

- Keys are **combination names** (human-readable, deterministic, stable
  across runs — the established cross-run join key). Validated at session
  start against the enumerated combinations, like sweep selectors: an
  unknown name fails before any container runs.
- Combinations without an entry skip the comparison test (the "optional"
  in the requirement); `baseline_comparison: null`/absent disables it for
  the suite.
- `atol` is suite-level for now (per-combination overrides are future work)
  and pydantic-validated `ge=0`. **Absolute** tolerance, deliberately: no
  tolerance scaling by the baseline's magnitude.

### Setting and baseline layout

| Setting             | Env var                  | Default                |
|---------------------|--------------------------|------------------------|
| `baseline_root_dir` | `CECE_BASELINE_ROOT_DIR` | `None` → cwd           |

A baseline lives at `<baseline_root_dir>/<ulid>/` and contains exactly the
`*.nc` files of the combination run it was captured from (flat, same
filenames the driver produced). A **configured baseline that cannot be
found is a test failure, not a skip** — a declared expectation that cannot
be evaluated must be loud. Future work replaces local lookup with online
retrieval plus a manifest linking ULIDs to combination names and metadata;
nothing in this design depends on the directory carrying metadata today.

### Comparison engine (`src/comparison.py`, modeled on nccmp)

Per combination, given the combo dir and the baseline dir:

1. **File sets**: `*.nc` names and counts must match exactly (missing and
   unexpected files reported by name).
2. Per matched file pair, all checked and reported:
   - **NetCDF format** exact (e.g. `NETCDF4` vs classic — via the
     underlying file `data_model`).
   - **Dimensions**: names and sizes exact.
   - **Variables**: names and counts exact.
   - **Global attributes**: exact (raw, undecoded — same
     `decode_cf=False` rationale as the species-attributes assertion).
   - **Per-variable attributes**: exact, raw.
   - **Data**: `atol == 0` → bit-for-bit (dtypes equal; values identical
     with NaNs required in identical positions); `atol > 0` →
     `|realization - baseline| <= atol` elementwise — absolute tolerance,
     no scaling by the baseline's magnitude (NaN positions still
     identical). Always-exact attributes are per the requirement —
     tolerance applies to data only.
3. **Parallel xarray**: datasets open with `chunks="auto"`; per-variable
   comparison reductions (equality / max-abs-diff) are gathered into a
   single `dask.compute` executed on the existing session `dask_client` —
   the same batching pattern as the stats step.
4. **Logging** goes through the runner's logging system
   (`logs.get_logger("comparison")`, level via `CECE_LOG_LEVEL`), in the
   established style: an INFO line when a combination's comparison starts
   (combo, baseline ULID, atol), one per file pair with its outcome, and a
   summary line (`comparison passed`/`FAILED` with the failing checks);
   mismatch details additionally at ERROR so they stand out at any level.

### Results: pydantic model → YAML artifact

```python
class VariableComparison(StrictModel):   # frozen; every field described
    name, dtype_match, data_match, attributes_match, max_abs_diff, detail

class FileComparison(StrictModel):
    file, format_match, dimensions_match, variables_match,
    global_attributes_match, variables: list[VariableComparison], passed

class BaselineComparisonResult(StrictModel):
    run_id, combo, combo_id, baseline_ulid, atol,
    file_names_match, files: list[FileComparison], passed
```

Written to `<combo-dir>/<combo_id>-comparison.yaml` via the `to_yaml`
convention **whether the comparison passes or fails** (like `.out`), so a
failed comparison leaves its full diff record. The test then asserts
`result.passed`, with the failure message summarizing the offending
files/variables/checks.

### Test structure

A new unwrapped test on the shared fixture, standard skip ladder:

- `test_baseline_comparison[<combo>]` — skips when the driver run failed;
  skips with `no baseline configured for this combination` when the combo
  has no `baselines` entry (or the block is absent); otherwise compares and
  asserts. Missing baseline directory → **failure** (see above).

### Initial baseline generation (implementation step)

With the current fixed driver and checked-in config:

1. Run the suite; for each of the three combinations, copy its `*.nc` into
   `/Users/bkoziol/Library/CloudStorage/Dropbox/rlps/rsandbox/cece-baselines/<new ULID>/`
   (one freshly generated ULID per combination).
2. Wire those ULIDs into the checked-in suite's `baseline_comparison.baselines` and
   set `CECE_BASELINE_ROOT_DIR` to the Dropbox path when running locally.

**Portability caveat, accepted**: the checked-in suite then references
baselines that exist only where `CECE_BASELINE_ROOT_DIR` points at this
store; elsewhere the comparison tests fail loudly (missing baseline). The
future manifest/online-retrieval work resolves this properly.

## TDD plan (red first)

Harness tests against fabricated NetCDF pairs, written before
`comparison.py` exists:

- identical pair → passes bit-for-bit; a single perturbed value → fails at
  `atol=0`, passes at a covering `atol`, fails at a tighter one
- NaN-position mismatch fails even under tolerance
- changed variable attribute / global attribute → fails (attributes are
  always exact)
- dimension size change, variable added/removed, file added/removed/renamed,
  format mismatch (`to_netcdf(format="NETCDF4"/"NETCDF3_CLASSIC")`) → each
  fails naming the check
- results YAML written on both pass and fail and round-trips through the
  model
- suite parsing: `atol` validation (`-0.5` rejected), unknown baseline
  combination name rejected at session start

## Ripples (standing process rules)

- **`design.md`**: suite-configuration example gains the
  `baseline_comparison` block; settings table gains `baseline_root_dir`; the artifacts layout
  gains `<combo_id>-comparison.yaml`; the "no baseline comparison yet"
  non-goal is removed.
- **`README.md`**: env var table (`CECE_BASELINE_ROOT_DIR`), test list
  gains `test_baseline_comparison`, results layout gains the comparison
  yaml.
- Pydantic models with described fields, never dataclasses.

## Non-goals

- No online baseline retrieval, no baseline manifest (ULID → combination
  metadata), no baseline *creation* tooling in the runner — capture is a
  manual/scripted step this iteration.
- No per-combination `atol` overrides; no relative-tolerance (`rtol` /
  scaled) mode — absolute only.
- No statistics-CSV comparison — this feature compares the NetCDF files
  themselves.

## Acceptance criteria

- Harness passes without docker, covering the matrix above.
- Integration with the generated baselines and
  `CECE_BASELINE_ROOT_DIR` set: all `test_baseline_comparison` tests pass
  bit-for-bit against the freshly captured baselines; each combo dir
  contains its `<combo_id>-comparison.yaml` with `passed: true`.
- Removing a combination's `baselines` entry skips its comparison test with
  the explicit reason; pointing at a nonexistent ULID fails it.
- All other tests keep their outcomes.
