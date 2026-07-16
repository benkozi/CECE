"""Baseline comparison of combination NetCDF output, modeled on nccmp.

Structural checks (file sets, formats, dimensions, variables, attributes)
are always exact; data compares bit-for-bit (atol=0) or within an absolute
tolerance (atol>0, no scaling by the baseline's magnitude). Per-variable
reductions are dask graphs gathered into one dask.compute per file pair,
executed on the active distributed client.
"""

from __future__ import annotations

from pathlib import Path

import dask
import dask.array as dsa
import netCDF4
import numpy as np
import xarray as xr
import yaml
from pydantic import ConfigDict, Field

from logs import get_logger
from models.base import StrictModel

logger = get_logger("comparison")


class VariableComparison(StrictModel):
    """Comparison outcome for one variable of one file pair."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(description="Variable name")
    dtype_match: bool = Field(description="Whether realization and baseline dtypes are identical")
    data_match: bool = Field(description="Whether the data matched (bit-for-bit or within atol)")
    attributes_match: bool = Field(description="Whether the variable attribute dictionaries are identical")
    max_abs_diff: float | None = Field(
        None, description="Maximum absolute elementwise difference; None when shapes/dtypes prevented comparison"
    )
    detail: str | None = Field(None, description="Human-readable mismatch detail; None when everything matched")

    @property
    def passed(self) -> bool:
        return self.dtype_match and self.data_match and self.attributes_match


class FileComparison(StrictModel):
    """Comparison outcome for one realization/baseline file pair."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    file: str = Field(description="NetCDF filename (identical on both sides)")
    format_match: bool = Field(description="Whether the NetCDF data models (e.g. NETCDF4) are identical")
    dimensions_match: bool = Field(description="Whether dimension names and sizes are identical")
    variables_match: bool = Field(description="Whether the variable name sets are identical")
    global_attributes_match: bool = Field(description="Whether the global attribute dictionaries are identical")
    variables: list[VariableComparison] = Field(description="Per-variable outcomes for the common variables")
    passed: bool = Field(description="Whether every check for this file pair passed")


class BaselineComparisonResult(StrictModel):
    """The full comparison record for one combination, written as YAML."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str = Field(description="Session ULID of the run that produced the realization")
    combo: str = Field(description="Canonical combination name")
    combo_id: str = Field(description="Content-hash combination id")
    baseline_ulid: str = Field(description="ULID identifying the baseline")
    atol: float = Field(description="Absolute data tolerance used (0 = bit-for-bit)")
    file_names_match: bool = Field(description="Whether the NetCDF file name sets are identical")
    files: list[FileComparison] = Field(description="Per-file outcomes for the common files")
    passed: bool = Field(description="Whether the whole comparison passed")

    def to_yaml(self, path: Path) -> None:
        with open(path, "w") as f:
            yaml.dump(self.model_dump(mode="json"), f, default_flow_style=False, sort_keys=False)

    def failure_summary(self) -> str:
        parts: list[str] = []
        if not self.file_names_match:
            parts.append("file name sets differ")
        for file in self.files:
            if file.passed:
                continue
            checks = [
                name
                for flag, name in (
                    (file.format_match, "format"),
                    (file.dimensions_match, "dimensions"),
                    (file.variables_match, "variables"),
                    (file.global_attributes_match, "global attributes"),
                )
                if not flag
            ]
            checks += [
                f"{variable.name} ({variable.detail})" for variable in file.variables if not variable.passed
            ]
            parts.append(f"{file.file}: " + ", ".join(checks))
        return "; ".join(parts) or "passed"


def validate_baseline_names(baselines: dict[str, str], combo_names: set[str]) -> None:
    """Every baselines key must name an enumerated combination (fails before
    any container runs, like sweep selectors)."""
    unknown = sorted(set(baselines) - combo_names)
    if unknown:
        raise ValueError(
            f"baseline_comparison.baselines names unknown combination(s) {unknown}; "
            f"enumerated combinations: {sorted(combo_names)}"
        )


def _stringified_attrs(attrs: dict) -> dict[str, str]:
    return {str(key): str(value) for key, value in attrs.items()}


def _compare_variable(
    name: str, realization: xr.DataArray, baseline: xr.DataArray, atol: float
) -> VariableComparison:
    dtype_match = realization.dtype == baseline.dtype
    attrs_real = _stringified_attrs(realization.attrs)
    attrs_base = _stringified_attrs(baseline.attrs)
    attributes_match = attrs_real == attrs_base
    detail_parts: list[str] = []
    if not dtype_match:
        detail_parts.append(f"dtype {realization.dtype} != {baseline.dtype}")
    if not attributes_match:
        detail_parts.append(f"attributes {attrs_real} != {attrs_base}")

    if realization.dims != baseline.dims or realization.shape != baseline.shape:
        detail_parts.append(
            f"shape {realization.dims}{realization.shape} != {baseline.dims}{baseline.shape}"
        )
        return VariableComparison(
            name=name,
            dtype_match=dtype_match,
            data_match=False,
            attributes_match=attributes_match,
            max_abs_diff=None,
            detail="; ".join(detail_parts),
        )

    real = dsa.asarray(realization.data)
    base = dsa.asarray(baseline.data)
    if np.issubdtype(realization.dtype, np.floating) and np.issubdtype(baseline.dtype, np.floating):
        nan_positions_equal = dsa.isnan(real) == dsa.isnan(base)
        both_nan = dsa.isnan(real) & dsa.isnan(base)
        if atol == 0.0:
            values_equal = (real == base) | both_nan
        else:
            values_equal = (abs(real - base) <= atol) | both_nan
        equal_graph = (values_equal & nan_positions_equal).all()
        diff_graph = dsa.nanmax(abs(real - base))
    else:
        equal_graph = (real == base).all() if atol == 0.0 else (abs(real - base) <= atol).all()
        diff_graph = abs(real - base).max()

    equal, max_diff = dask.compute(equal_graph, diff_graph)
    data_match = bool(equal) and dtype_match
    max_abs_diff = float(max_diff) if np.isfinite(max_diff) else None
    if not bool(equal):
        detail_parts.append(f"data differs (max abs diff {max_abs_diff})")

    return VariableComparison(
        name=name,
        dtype_match=dtype_match,
        data_match=data_match,
        attributes_match=attributes_match,
        max_abs_diff=max_abs_diff,
        detail="; ".join(detail_parts) or None,
    )


def _netcdf_data_model(path: Path) -> str:
    with netCDF4.Dataset(path) as ds:
        return str(ds.data_model)


def _compare_file(realization_path: Path, baseline_path: Path, atol: float) -> FileComparison:
    format_match = _netcdf_data_model(realization_path) == _netcdf_data_model(baseline_path)

    open_kwargs = dict(engine="netcdf4", chunks="auto", decode_cf=False, decode_coords=False)
    with (
        xr.open_dataset(realization_path, **open_kwargs) as real,
        xr.open_dataset(baseline_path, **open_kwargs) as base,
    ):
        dimensions_match = dict(real.sizes) == dict(base.sizes)
        real_vars = set(map(str, real.variables))
        base_vars = set(map(str, base.variables))
        variables_match = real_vars == base_vars
        global_attributes_match = _stringified_attrs(real.attrs) == _stringified_attrs(base.attrs)

        variables = [
            _compare_variable(name, real[name], base[name], atol)
            for name in sorted(real_vars & base_vars)
        ]

    passed = (
        format_match
        and dimensions_match
        and variables_match
        and global_attributes_match
        and all(variable.passed for variable in variables)
    )
    comparison = FileComparison(
        file=realization_path.name,
        format_match=format_match,
        dimensions_match=dimensions_match,
        variables_match=variables_match,
        global_attributes_match=global_attributes_match,
        variables=variables,
        passed=passed,
    )
    logger.info("compared %s: %s", realization_path.name, "passed" if passed else "FAILED")
    return comparison


def compare_with_baseline(
    combo_dir: Path,
    baseline_dir: Path,
    atol: float,
    run_id: str,
    combo: str,
    combo_id: str,
    baseline_ulid: str,
) -> BaselineComparisonResult:
    """Compare every NetCDF of a combination against its baseline."""
    logger.info(
        "comparing combo %s against baseline %s (atol=%s)", combo, baseline_ulid, atol
    )
    real_names = {path.name for path in combo_dir.glob("*.nc")}
    base_names = {path.name for path in baseline_dir.glob("*.nc")}
    file_names_match = real_names == base_names
    if not file_names_match:
        logger.error(
            "file sets differ for combo %s: missing %s, unexpected %s",
            combo,
            sorted(base_names - real_names),
            sorted(real_names - base_names),
        )

    files = [
        _compare_file(combo_dir / name, baseline_dir / name, atol)
        for name in sorted(real_names & base_names)
    ]
    passed = file_names_match and all(file.passed for file in files)
    result = BaselineComparisonResult(
        run_id=run_id,
        combo=combo,
        combo_id=combo_id,
        baseline_ulid=baseline_ulid,
        atol=atol,
        file_names_match=file_names_match,
        files=files,
        passed=passed,
    )
    if passed:
        logger.info("comparison passed for combo %s", combo)
    else:
        logger.error("comparison FAILED for combo %s: %s", combo, result.failure_summary())
    return result
