# Feature: base CECE config as a file, referenced from the suite config

## Goal

Make the base driver configuration a checked-in YAML file selected by the
suite config, instead of a `CeceConfig` hardcoded in `combos.py`. A suite
file then fully describes a run — *which base scenario* (`config_path`) plus
*which sweep* — and new scenarios become new YAML files rather than code
changes.

## Current behavior

- `combos.py:base_config()` constructs the baseline `CeceConfig` in code
  (single species `co`, single MACCITY stream); the suite config only carries
  the sweep.
- The suite file lives at `combo-test-runner/suite.yaml` (project root), which
  is also the `--suite-config` default.

## Design

### `config_path` on the suite config

`SuiteConfig` gains a required `config_path: Path` field naming the base
CECE driver config:

```yaml
# simple-maccity-suite.yaml
config_path: ../cece/simple-maccity.yaml
sweep:
  mapalgo: [bilinear, consd, passthrough]
```

**Relative paths resolve against the suite file's own directory** (not the
process cwd), so the suite file and the configs it references move together
as a unit. `SuiteConfig.from_yaml(path)` resolves `config_path` to an
absolute host path at load time and fails immediately (pydantic validation)
if the file does not exist — before any containers run.

### Base config loading

`combos.build_config()` starts from `CeceConfig.from_yaml(config_path)`
instead of the in-code `base_config()`, which is deleted. Loading per combo
(or one load + `model_copy(deep=True)` per combo) keeps combos isolated.
This stays inside the existing hard requirement: the file is read via
`CeceConfig.from_yaml()` and mutated/written only through the model — the
YAML file *is* validated pydantic input, not a template to string-edit.

The initial base config file is the current in-code baseline serialized to
`simple-maccity.yaml` — behavior of the initial suite is unchanged.

### File layout and moves

```
combo-test-runner/src/tests/config/
  cece/
    simple-maccity.yaml         # base driver config (was combos.base_config())
  suite/
    simple-maccity-suite.yaml   # was combo-test-runner/suite.yaml
```

- `suite.yaml` moves to `src/tests/config/suite/simple-maccity-suite.yaml`.
- The `--suite-config` default becomes that path.
- The `-suite` filename suffix distinguishes suite files from driver configs
  at a glance; the shared `simple-maccity` stem ties the pair together.

Both subdirectories share the `src/tests/config/` parent (resolved: `config`
over `cfg`), giving the tidy relative reference `../cece/simple-maccity.yaml`
from the suite file.

### Ripple effects

- `conftest.py`: only the `--suite-config` default changes.
- Main `design.md` needs updating: the "Base configuration" section currently
  states the base config is defined in code with zero runtime dependency on
  files elsewhere in the repo. The zero-dependency rationale is preserved —
  the config file lives inside `combo-test-runner/` — but the mechanism
  changes to file-based; the suite-configuration section gains `config_path`.
- README: mention `config_path` and the new default suite path.

## Non-goals

- No per-combo or per-dimension base-config overrides (still future work in
  the main design doc).
- No search path / config directory scanning — `config_path` is an explicit
  reference, one base config per suite file.

## Acceptance criteria

- `uv run pytest` (no options) uses
  `src/tests/config/suite/simple-maccity-suite.yaml`, which references
  `src/tests/config/cece/simple-maccity.yaml` relatively, and **all tests pass**
  with unchanged behavior (same combos, same generated configs).
- A suite file with a missing/typo'd `config_path` fails at session start
  with a clear validation error, before any docker runs.
- `combo-test-runner/suite.yaml` no longer exists; `combos.base_config()` is
  removed.
