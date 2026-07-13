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

### Build-and-test script

Third requirement, investigated: the suite itself launches `docker run` per
combination, so it cannot run *inside* the container (docker-in-docker).
The natural split, packaged as a new `setup.sh` mode:

```sh
./setup.sh -t    # build the driver in the container, then run the suite
```

1. **Build in container** (reusing `-c` machinery):
   `docker run ... deckyfre/cece-dev cmake --build build --target
   cece_standalone_driver -j` — same image, `/work` mount, and env as every
   other invocation.
2. **Test on host**: `cd combo-test-runner && uv run pytest` — the suite
   then orchestrates its own per-combo containers as always.

The script exits nonzero if either phase fails, making it the one-command
verification loop for driver fixes like this one (`README.md` gains it).

## Acceptance criteria

- Rebuilt driver (`./setup.sh -t`): output NetCDFs carry
  `units: kg m-2 s-1` on `co`; `test_species_units` passes for all three
  combos; the full suite is green.
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
