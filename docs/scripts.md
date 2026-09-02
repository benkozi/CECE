# CECE Scripts and Utilities

CECE provides several Python scripts to facilitate data management, configuration migration, and visualization of the emission stacking process.

## Example Data Management

Example data download and execution live under `examples/` (see
`examples/README.md` for details). Both entrypoints are stdlib-only Python
and share `--example <id[,id...]>` / `--all` / `--dst-dir <path>` arguments;
the example → data mapping lives in `examples/common.py`.

### `examples/download-example-data.py`
Downloads the input data for one or more examples from public S3 buckets
into `data/` (cached; non-empty existing files are skipped).
```bash
python3 examples/download-example-data.py --example ex1,ex7
python3 examples/download-example-data.py --all
```

### `examples/run-example.py`
Downloads (cache-aware) and runs one or more examples by executing the
driver binary directly — no docker required, so it also works on HPC
platforms (`CECE_EXAMPLES_DRIVER_PATH` overrides the default
`build/cece_standalone_driver` location).
```bash
python3 examples/run-example.py --example ex3
```

---

## Configuration Migration

### `hemco_to_cece.py`
Converts legacy HEMCO `.rc` configuration files to the CECE YAML format. It handles:
- Recursive includes (`>>>include`)
- `$ROOT` token replacement
- Mapping scale factors and masks to CECE layers
- Parsing grid and diagnostic definitions from auxiliary files

```bash
python scripts/hemco_to_cece.py HEMCO_Config.rc -o cece_config.yaml
```

---

## Visualization

### `visualize_stack.py`
Generates a visual representation (graph) of the emission stacking hierarchy defined in an CECE configuration file. This is useful for verifying that layers, masks, and scale factors are correctly prioritized.
```bash
python scripts/visualize_stack.py --config cece_config.yaml --output stacking_plan.png
```

### `visualize_optimized_stack.py`
Similar to `visualize_stack.py`, but specifically visualizes the fused kernel plan used by the optimized CECE engine.
```bash
python scripts/visualize_optimized_stack.py --config cece_config.yaml --output optimized_plan.png
```
