# Fix: driver emits wrong units (`mol mol-1`) on output fields

## Bug, located

`src/driver/cece_standalone_writer.cpp` (lines ~265–273) generates the AMIO
output manifest and **hardcodes, for every output field**:

```
units: "mol mol-1"
long_name: "mole_fraction_of_<name>_in_air"
```

The output fields are stacked **emission fluxes** (the MACCity input
variable carries `kg/m2/s`), so both attributes are factually wrong — this
is exactly what `test_species_units` has been failing on
(`expected 'kg m-2 s-1', found 'mol mol-1'`, per
`design/feat/20260713-1049-expected-output-units.md`).

**Finding vs. the original note**: no `extern/helm/libs/conf` ↔
`extern/helm/libs/amio` changes are needed. AMIO already carries arbitrary
per-variable attributes from the manifest (parsed by helm's `conf`) through
to the NetCDF — the proof is that the wrong hardcoded values arrive intact
in the output. The fix is entirely CECE-side: the config parser and the
writer's manifest generation.

## Fix design

### Config-driven field attributes

The CECE yaml `output:` block gains an optional per-field attribute map:

```yaml
output:
  enabled: true
  directory: ...
  fields: [co]
  field_attributes:
    co:
      units: kg m-2 s-1
      long_name: carbon_monoxide_emission_flux
```

- `CeceOutputConfig` (include/cece/cece_config.hpp) gains
  `std::map<std::string, std::map<std::string, std::string>>
  field_attributes;` parsed in `src/core/cece_config_parser.cpp` from the
  `output.field_attributes` node.
- The writer's manifest loop emits the configured attributes for each field
  (plus the structural `coordinates: "lon lat"` it already writes). **When a
  field has no configured attributes, it gets none** — absence over
  fabrication; a wrong default is precisely the bug being fixed, and the
  units assertion's `null` semantics can verify absence.
- The hardcoded `units`/`long_name` lines are deleted.

### Units value for the checked-in config

The MACCity input variable says `kg/m2/s`; the checked-in
`simple-maccity.yaml` will configure the CF-canonical spelling
**`kg m-2 s-1`** (matching what the suite assertion already expects — exact
string philosophy: the config states it, the driver echoes it, the
assertion verifies the echo).

### Runner-side ripple (forced by StrictModel)

- `combo-test-runner/src/models/cece_config.py`: the `Output` model gains
  `field_attributes: dict[str, dict[str, str]] | None = None` — without it,
  the new key would be rejected at load.
- `src/tests/config/cece/simple-maccity.yaml` sets
  `field_attributes.co.units: kg m-2 s-1` (and an honest `long_name`).
- Expected outcome: the three `test_species_units` tests **flip green**, the
  same automatic flip the filename tests demonstrated. All other tests
  unchanged. The suite-file "known bug" comment for units is removed.
- Harness: model round-trip of `field_attributes` (StrictModel accepts the
  new key; generated combo yamls carry it through `build_config`).
- Driver-side tests: check `tests/` for any writer/manifest expectations
  pinned to the old hardcode and update alongside.

### C++ regression test in CECE (red before the fix, green after)

A new GTest executable, `tests/test_standalone_writer_attributes.cpp`
(registered in `CMakeLists.txt` + ctest like the existing
`test_driver_configuration`), exercising the real writer end to end:
construct `CeceStandaloneWriter`, `Initialize`, `WriteTimeStep` with a small
field, `Finalize`, then read the produced NetCDF back (netcdf-c API,
available in the image) and assert on the variable's attributes. Two tests,
sequenced deliberately:

1. **`DefaultConfigEmitsNoFabricatedAttributes`** — written and run
   **before** the fix, against the unchanged `CeceOutputConfig` (so it
   compiles pre-fix): a field with no configured attributes must have **no
   `units` attribute**. Pre-fix this is **RED** — the writer stamps
   `mol mol-1` on everything. The fix turns it green.
2. **`ConfiguredFieldAttributesReachTheOutput`** — lands *with* the fix (it
   needs the new `field_attributes` member to compile): configure
   `co -> {units: "kg m-2 s-1", long_name: ...}`, assert both arrive in the
   NetCDF verbatim. This is the permanent regression lock for the feature.

The demonstrated pre-fix failure of test 1 is part of the acceptance
evidence, per the TDD requirement.

### Build-and-test script: `scripts/build-and-test-container.py`

`setup.sh` stays untouched — its job is setting up a development
environment, nothing more. A new **Python** script (argparse +
`subprocess.check_call` throughout) lives in the existing `scripts/` directory:

```sh
./scripts/build-and-test-container.py               # build + test (the default)
./scripts/build-and-test-container.py --clean       # remove build/ and cmake-build-debug/ first
./scripts/build-and-test-container.py --no-build    # test only
./scripts/build-and-test-container.py --no-test     # build only
./scripts/build-and-test-container.py --mount /work # container-side mount point (default)
./scripts/build-and-test-container.py --image cece/cece-dev  # container image (default)
```

- **Host repo root is derived from the script's own location, never the
  cwd**: `Path(__file__).resolve().parent.parent` (the script lives in
  `scripts/`, directly under the repo root) — the same pattern the runner's
  `settings.py` uses. The script works identically invoked from anywhere;
  no assumption about executing from `scripts/` or the repo root, and no git
  dependency.
- `--mount` (default `/work`): the **container-side** path the host repo
  root is mounted at; all in-container paths (`<mount>/build`, ctest
  invocations) derive from it.
- `--image` (default `cece/cece-dev`): the container image — the
  default matches the image `setup.sh` builds/uses, so the script runs in
  the same environment as interactive development without configuration.
- `--clean` (off by default): removes the `build/` **and**
  `cmake-build-debug/` directories before anything else.
- `--no-build` / `--no-test`: independently disable a phase; both phases
  run by default.
- `--test-filter STRING`: run a single C++ test or subset — the test binary
  receives `--gtest_filter=*STRING*` (substring match; zero matches exit 0).
- **Container lifecycle**: each containerized step is its own
  `docker run --rm` against `cece/cece-dev` with
  `-v <derived-host-root>:<mount> -w <mount>` and the standard env
  (mirroring `setup.sh`'s invocation, without modifying it) — spun up and
  removed per execution, no reuse.
- **Build phase** (in container): CMake configure into `<mount>/build` when
  needed (always after `--clean`), then build `cece_standalone_driver` and
  the C++ test executables.
- **Test phase**: the C++ tests (the writer-attributes test and ctest
  peers) run **in the container**, where the toolchain and netcdf-c live.
  **The combo-test-runner suite is deliberately out of the script's scope**
  — it is run separately on the host (`uv run pytest` in
  `combo-test-runner/`), where it orchestrates its own per-combo
  containers. The script is the C++ build/test loop, nothing more.
- `check_call` semantics give the script its exit contract for free: the
  first failing step aborts with a nonzero exit — the one-command
  verification loop for driver fixes like this one (`README.md` gains it).

(Python per the requirement; stdlib-only — argparse/subprocess/shutil/
logging — so it runs with any `python3`, no uv environment needed. Script
output goes through python `logging`, deliberately minimal: `basicConfig`
with a timestamped format, everything at INFO for now.)

## Acceptance criteria

- **Pre-fix red demonstrated**: the new C++ test
  `DefaultConfigEmitsNoFabricatedAttributes` fails against the unfixed
  writer (finds `mol mol-1`), establishing the TDD baseline.
- Post-fix, `./scripts/build-and-test-container.py` is green (invoked from an
  arbitrary cwd, proving the `__file__`-derived root works): both C++
  writer-attribute tests pass in the container. **Separately**,
  `uv run pytest` in `combo-test-runner/` passes on the host — output
  NetCDFs carry `units: kg m-2 s-1` on `co` and `test_species_units` passes
  for all three combos.
- `--clean` removes and rebuilds from scratch successfully; `--no-build`
  and `--no-test` each skip exactly their phase; `setup.sh` is unchanged.
- A driver config without `field_attributes` produces output with **no**
  units/long_name attributes on data fields (verifiable with the assertion's
  `units: null` mode).
- Runner harness passes; `simple-maccity.yaml` round-trips through
  `CeceConfig` with the new key.
- `design.md` documents `field_attributes` in the base-config description;
  `README.md` documents `./setup.sh -t`.

## Non-goals

- No propagation of units from *input stream* attributes through the
  stacking engine (config-declared attributes only — the config is the
  statement of intent).
- No conf/amio (helm) changes.
- No unit conversion or validation of unit strings.
