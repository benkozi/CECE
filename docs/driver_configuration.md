# CECE Standalone NUOPC Driver Configuration Guide

## Overview

The CECE standalone NUOPC driver (`cece_nuopc_app`) executes the CECE emissions component for a configurable number of timesteps with proper clock management, grid/mesh creation, and synchronization. It runs both standalone (config-driven) and coupled (under a NUOPC_Driver framework).

### Shared Orchestration Contract

The NUOPC cap and the C++ standalone driver (`cece_standalone_driver`) are two entry
points onto the **same** C++ orchestration core. Both call the shared `CeceSimulation`
facade (`include/cece/cece_simulation.hpp`) through the C ABI in
`include/cece/cece_sim_c_abi.h`:

| Phase | C ABI entry | What it runs |
|-------|-------------|--------------|
| Create | `cece_sim_create_from_yaml` / `cece_sim_create_from_esmf` | grid resolution, core init, export-field registration, orchestrator, writer |
| Step | `cece_sim_step` | ingest at step-start, regrid, physics, stacking, write stamped at step-end |
| Finalize | `cece_sim_finalize` | resource cleanup |

Consequences for configuration: every option in the YAML config is honored identically
by both drivers, and the cap exports every configured output field. Both drivers also
use the same time convention — **ingest at step-start, stamp at step-end** (for a step
`T -> T + dt`, the stream is read at `T` and the file is stamped `T + dt`). See
[NUOPC Cap Parity](nuopc_cap_parity.md) for the parity test suite.

## Configuration Methods

### 1. YAML Configuration File (Recommended)

The driver reads an optional `driver` section from the CECE YAML configuration file. This is the recommended approach for reproducible simulations.

**Default config file**: `cece_config.yaml`

**Command-line override**: pass the config path as the first positional argument:

```bash
./cece_nuopc_app /path/to/config.yaml
mpirun -np 4 ./cece_nuopc_app /path/to/config.yaml
```

The C++ standalone driver takes the same positional form (`./cece_standalone_driver
/path/to/config.yaml`). The `CECE_CONFIG` environment variable is consulted by the
NUOPC app when no argument is given.

### 2. Two-Argument Form (NUOPC app only, legacy)

`cece_nuopc_app` additionally accepts a second positional argument selecting a NUOPC
driver configuration file (`config.yaml driver.cfg` order is auto-detected). The
driver.cfg is unused on the standalone path and is retained for framework-coupling
experiments.

## YAML Configuration Reference

### Minimal Configuration

If the `driver` section is omitted, all default values are used:

```yaml
species:
  CO:
    - operation: add
      field: CO_anthro
      hierarchy: 0
      scale: 1.0

physics_schemes:
  - name: native_example
    language: cpp
```

### Full Configuration

```yaml
driver:
  # Simulation start time (ISO8601 format: YYYY-MM-DDTHH:MM:SS)
  # Default: "2020-01-01T00:00:00"
  start_time: "2020-06-01T00:00:00"

  # Simulation end time (ISO8601 format: YYYY-MM-DDTHH:MM:SS)
  # Default: "2020-01-02T00:00:00"
  end_time: "2020-06-02T00:00:00"

  # Timestep duration in seconds (must be positive)
  # Default: 3600 (1 hour)
  timestep_seconds: 1800

  # Path to ESMF GRIDSPEC NetCDF file (optional)
  # If specified, the driver loads the grid from this file and skips grid generation.
  # Generate one with: python scripts/cece_make_gridspec.py <config.yaml>
  # If null or absent, a structured grid is generated from grid.nx/ny/nz.
  # Default: null (generate grid)
  gridspec_file: null

  # Grid configuration for generated structured grid
  # Only used if gridspec_file is null or absent
  grid:
    # Grid points in X direction (must be positive)
    # Default: 4
    nx: 4

    # Grid points in Y direction (must be positive)
    # Default: 4
    ny: 4
```

## Configuration Parameters

### start_time

**Type**: String (ISO8601 format)

**Format**: `YYYY-MM-DDTHH:MM:SS`

**Default**: `2020-01-01T00:00:00`

**Description**: The simulation start time. Must be before `end_time`.

**Examples**:
- `2020-01-01T00:00:00` - January 1, 2020 at midnight UTC
- `2020-06-15T14:30:45` - June 15, 2020 at 2:30:45 PM UTC

### end_time

**Type**: String (ISO8601 format)

**Format**: `YYYY-MM-DDTHH:MM:SS`

**Default**: `2020-01-02T00:00:00`

**Description**: The simulation end time. Must be after `start_time`.

**Examples**:
- `2020-01-02T00:00:00` - January 2, 2020 at midnight UTC
- `2020-06-16T00:00:00` - June 16, 2020 at midnight UTC

### timestep_seconds

**Type**: Integer

**Default**: `3600`

**Description**: The duration of each timestep in seconds. Must be positive. The driver will execute `(end_time - start_time) / timestep_seconds` timesteps.

**Examples**:
- `3600` - 1 hour timesteps
- `1800` - 30 minute timesteps
- `86400` - 1 day timesteps

**Validation**:
- Must be > 0
- A warning is logged if `(end_time - start_time) % timestep_seconds != 0`

### gridspec_file

**Type**: String (file path) or null

**Default**: `null`

**Description**: Path to an ESMF GRIDSPEC NetCDF file. If set, the grid is loaded from this file instead of being generated from `grid.nx`/`ny`/`nz`. Create one with `scripts/cece_make_gridspec.py`.

**Examples**:
- `"/data/grids/global_0p1deg.nc"` - Use pre-generated GRIDSPEC file
- `null` - Generate structured grid (default)

### grid.nx

**Type**: Integer

**Default**: `4`

**Description**: Number of grid points in the X direction for generated structured grids. Only used if `gridspec_file` is null or absent. Must be positive.

**Examples**:
- `4` - 4x4 grid (16 points)
- `360` - 360x180 grid (64,800 points)

**Validation**: Must be > 0

### grid.ny

**Type**: Integer

**Default**: `4`

**Description**: Number of grid points in the Y direction for generated structured grids. Only used if `gridspec_file` is null or absent. Must be positive.

**Examples**:
- `4` - 4x4 grid (16 points)
- `180` - 360x180 grid (64,800 points)

**Validation**: Must be > 0

## Grid/Mesh Selection Logic

Grid resolution runs inside the shared C++ core (`GridSpec::from_yaml`), so both drivers
resolve the target grid by identical rules:

1. **If `grid_name` is specified** (e.g. `F360`, `R360`): generate the mesh via AXIS
   and extract 1-D center coordinates (rectilinear). Declared `nx`/`ny` must match the
   named grid's expected dimensions.
2. **If `gridspec_file` is specified and valid**: load the coordinates from the
   GRIDSPEC/UGRID NetCDF file (CF packing unpacked, radians converted, longitudes
   wrapped) and classify the topology from the coordinate shapes — 1-D -> rectilinear,
   2-D flattened `nx*ny` -> curvilinear, `ny = 1` node arrays -> unstructured. A
   specified file that fails to load aborts the run; there is no silent substitution.
3. **Otherwise**: generate a uniform grid from `grid.nx`/`ny`/`nz` and the lon/lat
   extents (`ny = 1` yields a flattened unstructured node row).

## Execution Modes

### Standalone Mode

When the driver is executed directly (not invoked by a NUOPC_Driver framework):

- Reads timing and grid/mesh parameters from CECE config file
- Builds the simulation through the shared `CeceSimulation` facade
- Creates a uniform ESMF grid spanning the resolved extents and associates it with the
  component, so metadata consumers see the correct geometry
- Executes CECE component through all NUOPC phases
- Manually manages clock advancement (if needed)

### Coupled Mode

When the cap is invoked by a NUOPC_Driver framework, the export grid comes from one of
three sources, tried in this order at `InitializeRealize`:

1. **Host field.** The driver names a sibling component and one of its export fields
   with `CECE_SetHostGeometry(host_comp, field_name, rc)`; the cap reads that field's
   `ESMF_Grid` and realizes its exports on the same grid object.
2. **Parent grid.** An `ESMF_Grid` or `ESMF_Mesh` the host attached to the CECE
   component (`ESMF_GridCompSet`).
3. **Config grid.** The YAML grid, when neither of the above is present.

A host field and a parent grid set together are an error naming both; the cap does not
choose between them.

**Why the host-field source exists.** A host model such as an atmosphere creates its
grid inside its own initialization, so the driver never holds it and cannot attach it
to CECE. NUOPC's geometry transfer cannot deliver it either: CECE provides its export
fields, a providing field must be realized before `label_RealizeProvided` returns, and a
geometry accepted from another component only arrives in the later accept phases (NUOPC
reference manual, section 2.4.7). Reading the grid off the host's already realized field
closes that gap, and it guarantees that CECE and every consumer of the host's field
(for example a chemistry component that takes its grid from the host's tracer array)
run on one grid with one decomposition.

**Ordering requirement.** The driver runs each initialize phase over its children in the
order they were added, and the cap reads the host's field at the start of its own
realize phase. The host must therefore be added before CECE. If it is not, the cap
stops with

```
[Cap] host geometry field <name> of <host> is not realized; the host must precede CECE in the driver's component list
```

```fortran
call NUOPC_DriverAddComp(driver, "ATM", atmSS, comp=atm_comp, rc=rc)
call NUOPC_DriverAddComp(driver, "CECE", CECE_SetServices, comp=cece_comp, rc=rc)
call CECE_SetHostGeometry(atm_comp, "inst_tracer_mass_frac", rc)
```

The setter only records the source; it may be called any time before the driver
initializes its children. A second call replaces the first.

**Which source was used** is logged once per PET:

| Source | Log line |
| --- | --- |
| Host field | `[Cap] grid source: host field <host>/<field> (tileCount=<n>, local DE <d> of tile <t>)` |
| Parent grid | `[Cap] Parent grid: tileCount=...` on a multi-tile grid; a single-tile parent grid has no line of its own (neither of the other two appears) |
| Config grid | warning `[Cap] No parent grid or mesh associated with the component; resolving the target grid from the CECE config.` |

A host-field grid and a parent grid are treated alike from there on:

- A **multi-tile grid** (a cubed sphere) takes the host-block path: each PET's single DE,
  with the grid's own CORNER-stagger cell corners, is the core's whole local grid. This
  needs exactly one DE per PET and a DE that owns a closed corner ring, i.e. one DE per
  tile; `output.enabled` and `local_time.enabled` are refused on it.
- Clock is provided by framework (cap skips clock creation)
- **Single-tile grids**: if the host associates an `ESMF_Grid` or `ESMF_Mesh` with
  the component, the cap extracts its global coordinates across PETs and builds the
  simulation on that grid (rectilinear from 1-D coords, curvilinear from flattened 2-D
  GRIDSPEC coords, unstructured from mesh node lists). Radians are converted and
  longitudes wrapped in the shared C++ code; unsupported shapes fail loudly with a
  named diagnostic — never a uniform-grid fallback.
- When a host-field or parent grid and a YAML grid both exist, the former wins and a
  single warning names the ignored YAML grid; the sources are never merged.
- `nz` always comes from `driver.grid.nz` in the config, never from the flat 2-D grid.
- With no host field and no parent grid, the cap falls back to the config-built path — the exact same
  YAML grid resolution the C++ driver runs.
- Driver operates normally without a driver configuration section (documented defaults)

## Default Values

When driver configuration is missing from the config file, the following defaults are used:

| Parameter | Default Value |
|-----------|---------------|
| `start_time` | `2020-01-01T00:00:00` |
| `end_time` | `2020-01-02T00:00:00` |
| `timestep_seconds` | `3600` |
| `gridspec_file` | `null` (generate grid) |
| `grid.nx` | `4` |
| `grid.ny` | `4` |

## Validation Rules

The driver validates configuration parameters and exits with status 1 if validation fails:

### ISO8601 Format Validation

- Format must be exactly `YYYY-MM-DDTHH:MM:SS`
- Year must be 4 digits
- Month must be 2 digits (01-12)
- Day must be 2 digits (01-31)
- Hour must be 2 digits (00-23)
- Minute must be 2 digits (00-59)
- Second must be 2 digits (00-59)

**Error message**: `ERROR: [Driver] Invalid ISO8601 format: {value}`

### Time Ordering Validation

- `start_time` must be strictly before `end_time`

**Error message**: `ERROR: [Driver] Start time must be before end time`

### Timestep Validation

- `timestep_seconds` must be > 0

**Error message**: `ERROR: [Driver] Timestep must be positive`

### Grid Dimension Validation

- `grid.nx` must be > 0
- `grid.ny` must be > 0

**Error message**: `ERROR: [Driver] Grid dimensions must be positive`

### GRIDSPEC File Validation

- If `gridspec_file` is specified, it must be a valid ESMF GRIDSPEC NetCDF file

**Error message**: `ERROR: [CECE] ESMF_GridCreate from gridspec_file failed: rc={rc}`

## Logging and Diagnostics

The driver logs all configuration values during initialization:

```
INFO: [Driver] Config file:   cece_config.yaml
INFO: [Driver] Start time:    2020-01-01T00:00:00
INFO: [Driver] End time:      2020-01-02T00:00:00
INFO: [Driver] Time step (s): 3600
INFO: [Driver] Grid size:     4 x 4
INFO: [Driver] Clock: 2020-01-01 -> 2020-01-02 dt=3600s
```

For large grids (>50k points), the driver logs the synchronization level:

```
INFO: [Driver] Large grid (64800 points) - enhanced synchronization...
```

## Examples

### Example 1: Minimal Configuration (All Defaults)

```yaml
species:
  CO:
    - operation: add
      field: CO_anthro
      hierarchy: 0
      scale: 1.0

physics_schemes:
  - name: native_example
    language: cpp
```

**Result**:
- Simulation from 2020-01-01 to 2020-01-02 (24 hours)
- 3600-second (1-hour) timesteps = 24 timesteps
- 4x4 Gaussian grid (16 points)

### Example 2: Custom Timing and Grid

```yaml
driver:
  start_time: "2020-06-01T00:00:00"
  end_time: "2020-06-02T00:00:00"
  timestep_seconds: 1800
  grid:
    nx: 8
    ny: 8

species:
  CO:
    - operation: add
      field: CO_anthro
      hierarchy: 0
      scale: 1.0

physics_schemes:
  - name: native_example
    language: cpp
```

**Result**:
- Simulation from 2020-06-01 to 2020-06-02 (24 hours)
- 1800-second (30-minute) timesteps = 48 timesteps
- 8x8 Gaussian grid (64 points)

### Example 3: Using a GRIDSPEC File

```yaml
driver:
  start_time: "2020-01-01T00:00:00"
  end_time: "2020-01-02T00:00:00"
  timestep_seconds: 3600
  gridspec_file: "/data/grid.nc"

species:
  CO:
    - operation: add
      field: CO_anthro
      hierarchy: 0
      scale: 1.0

physics_schemes:
  - name: native_example
    language: cpp
```

**Result**:
- Simulation from 2020-01-01 to 2020-01-02 (24 hours)
- 3600-second (1-hour) timesteps = 24 timesteps
- Grid loaded from `/data/grid.nc` (GRIDSPEC file)

## Large Grid Synchronization

For grids larger than 50,000 points, the driver applies grid-size-dependent synchronization during finalization to prevent race conditions:

| Grid Size | Synchronization Strategy |
|-----------|--------------------------|
| ≤ 50,000 points | Single VM barrier |
| 50,001 - 100,000 points | Enhanced: 2 VM barriers |
| 100,001 - 500,000 points | Extended: 3 VM barriers |
| > 500,000 points | Maximum: 4 VM barriers |

## Error Handling

The driver implements comprehensive error handling:

### Fatal Errors (Exit with status 1)

- Invalid ISO8601 format
- Start time >= end time
- Non-positive timestep
- Non-positive grid dimensions
- Missing or invalid GRIDSPEC file
- ESMF operation failures
- CECE component failures

### Non-Fatal Errors (Log warning, continue)

- VM barrier failures during cleanup
- Resource destruction failures

## See Also

- [CECE Configuration Guide](configuration.md)
- [CECE Developer Guide](developer_guide.md)
- [NUOPC Reference Manual](https://earthsystemmodeling.org/docs/release/latest/NUOPC_refdoc)
