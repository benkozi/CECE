# Feature: opt-in example execution (`--run-examples`)

## Goal

Let the pytest suite execute the driver's shipped example configs
(`scripts/examples/cece_config_ex*.yaml`) as first-class tests, **off by
default** behind a `--run-examples` flag, with the required input data
fetched via `scripts/data_download/download_ex*.sh`. Examples are run
**verbatim** — they are external artifacts under test ("do the shipped
examples actually work?"), and honest failures are expected and reported,
never masked.

## Pre-design audit of the example/download landscape

What's actually on disk shapes every choice below:

1. **`scripts/examples/` uses a schema the driver no longer reads.** All
   six configs declare their streams under `cdeps_inline_config:`; the
   parser reads only `cece_data:` (`cece_config_parser.cpp:283`). They also
   have no `driver:` block (no times, no grid) and no `output:` block.
   Expectation: these run vacuously or fail — exactly the note's "all
   examples might not pass". The suite's job is to document that truth,
   not fix the configs (config fixes are driver-repo work, surfaced
   separately).
2. **`scripts/examples/` and the repo-root `examples/` have fully
   diverged.** The root set is current-schema (`cece_data`, driver/output
   blocks) but references absolute `/gpfs/...` HPC paths no download
   script can satisfy, and its README describes contents that no longer
   match its files. The note scopes this feature to `scripts/examples/`;
   the root set is out of scope (surfaced as a driver-repo doc/content
   issue).
3. **Known data gap**: `cece_config_ex1/ex2.yaml` reference
   `data/hourly.nc` (HOURLY_SCALFACT), which **no download script
   fetches** — a permanent "might not work" unless a source is found.
4. **Duplicate download scripts**: `scripts/download_ex*.sh` duplicates
   `scripts/data_download/download_ex*.sh` (the ex1 copies differ). Per
   the note, `scripts/data_download/` is authoritative; the duplicates are
   surfaced as cleanup, not touched here.
5. Download scripts `cd`-assume the **repo root** (`./scripts/...`,
   `mkdir -p data`) and fetch from the public geos-chem S3 bucket via
   `curl -f`; targets land in `data/` (already gitignored via `data/*.nc`,
   already partially populated).

## Design

### Test module: `src/tests/test_examples.py`

- **Discovery**: glob `scripts/examples/*.yaml` under `settings.root` at
  collection time, parameterized with the file stem as the test id
  (`test_example_execution[cece_config_ex3]`). Six today; new example
  files join automatically.
- **One test per example**: run the driver in docker against the example
  file verbatim — `<driver> /work/scripts/examples/<name>.yaml`, working
  directory `/work` (matching the scripts' repo-root assumption and the
  configs' relative `data/...` paths). Exit 0 is the sole pass criterion.
  Captured stdout/stderr goes to `<output-root>/examples/<stem>.out`
  (same `.out` conventions as combos; the `examples/` subdirectory keeps
  combo-id directories unambiguous).
- **Verbatim means no pydantic**: example configs are inputs under test,
  deliberately *not* loaded through `CeceConfig` (they would fail strict
  validation — see audit #1 — and the point is to test the driver against
  its own shipped files). This is an explicit, documented exception to the
  "all config construction goes through cece_config.py" rule, which
  governs *generated* configs only.
- **Gating**, in order:
  - no `--run-examples` → skip: "examples disabled; pass --run-examples"
    (visible-but-skipped matches the template's "only run examples when
    requested").
  - `--dry-run` → skip: "dry run: driver execution skipped" (dry-run wins;
    all suites and example runs must pass `--dry-run` without docker).
- **No expected-failure masking**: examples that fail, fail red (the
  note's "all examples might not pass" is reporting honesty, not xfail).
  They are combo-independent and carry no combo_id, so they do **not**
  appear in `test-report.csv` (combo-keyed by design); pytest's own
  report covers them.
- **Timeout**: `settings.run_timeout_s` per example (no suite-level
  timeout applies — examples are suite-independent; the combo suite's
  `timeout_s` governs combos only).

### Data download: `examples.py` + session fixture

New `src/examples.py` module (logic testable without docker):

- `discover_examples(root) -> list[Path]` — the glob, sorted.
- `download_example_data(root) -> list[DownloadResult]` — run every
  `scripts/data_download/download_ex*.sh` from the repo root via
  `subprocess.run` (capture output, never raise), returning one
  `DownloadResult` pydantic model per script: `{script, returncode,
  output}`. Failures **log at WARNING and do not abort** — a broken
  download script must not hide the other examples' results (the affected
  example then fails or passes on its own merits).
- A session-scoped `example_data` fixture (requested only by example
  tests, so combo-only runs never pay for it) calls
  `download_example_data` once when `--run-examples` is active and not
  `--dry-run`. The `curl -f -o` fetches overwrite unconditionally;
  script-level caching is left to the scripts (surfaced as a possible
  later improvement, not built here — the datasets are modest and a
  re-fetch keeps them current).

### Download-script repair (implementation-time task)

Per the note: run each of the six scripts during implementation, inspect
output, and fix what is fixable **inside `scripts/data_download/`** (e.g.
a moved S3 path). Unfixable gaps (e.g. `hourly.nc`, which has no download
source at all) are recorded in this doc's implementation notes and left as
honest example failures — not worked around in the runner.

## TDD plan (red first)

- `discover_examples` finds the six checked-in yamls, sorted, by stem.
- `download_example_data` (mocked `subprocess.run`): invokes every
  `download_ex*.sh` from the repo root; a nonzero script yields a
  `DownloadResult` with its output and a WARNING log, and later scripts
  still run; nothing raises.
- Gating via a pytest subprocess (no mocking, mirrors the dry-run harness
  test): `test_examples.py` **without** `--run-examples` → all example
  tests skip, no docker, no downloads; **with** `--run-examples
  --dry-run` → still all skips, no downloads.
- `DownloadResult` model: described fields, unknown-key rejection.

Real example execution (docker + downloads) happens only when explicitly
requested, per the template's testing rules; integration verification for
this feature is the harness plus a real `simple-maccity-suite.yaml` run.

## Ripples (standing process rules)

- **`design.md`**: `--run-examples` in the pytest-options list; the
  example tests and the `examples/` output subdirectory in the layout;
  `examples.py` in the code layout; the verbatim-execution exception noted
  beside the config-construction rule.
- **`README.md`**: `--run-examples` in Options with the data-download
  behavior and the "examples may legitimately fail" caveat; the example
  invocation in Running.
- Driver-repo issues surfaced (not fixed here): stale
  `cdeps_inline_config` schema in `scripts/examples/`, diverged root
  `examples/` + stale README, duplicate download scripts at `scripts/`
  root, missing `hourly.nc` source.
- Pydantic models with described fields; TDD red-green.

## Acceptance criteria

- `uv run pytest src/tests/test_examples.py` (no flag) collects the six
  example tests and skips them all without touching docker or the network.
- `--run-examples --dry-run` also skips everything, download included.
- `uv run pytest src/tests/test_examples.py --run-examples` (run only when
  requested) downloads what the scripts can fetch, executes all six
  examples in docker, writes `examples/<stem>.out` under the output root,
  and reports pass/fail honestly — failures expected per the audit.
- Download-script outcomes from the implementation-time repair pass are
  recorded in this doc; any script fixes live in `scripts/data_download/`.
- Harness green without docker; combo behavior unchanged.

---

# appendix: original notes

## always do

- include updating design.md as part of the implementation
- update combo-test-runner tests in addition to any changes to test_driver_combos.py
- update README.md with any necessary documentation changes in case of an api adjustment
- use pydantic models as opposed to dataclasses
  - all pydantic fields should include a description like `... = Field(description="<description content here>", ...`
- do *not* add driver bugs to known bugs in `README.md` unless explicitly told to do so
- use a test-driven development, red-green-refactor approach for all fixes and features (when possible)
- maintain original `always do` and `requirements` sections when refining design docs

### testing

- *all* suites should pass `--dry-run`
- run `simple-maccity-suite.yaml` without `--dry-run` for integration testing with the driver
- only run examples when requested to do so
- no need to run tests for spikes/documentation-only tasks

## requirements

- provide an option to run examples located in scripts/examples as part of the pytest suite
  - maybe a flag `--run-examples` that is off by default
- data will need to be downloaded using `scripts/data_download`
  - note some scripts might not work so inspect the script output
  - attempt to fix download scripts if possible
- all examples might not pass
