from pathlib import Path

import numpy as np
import pytest
import xarray as xr
import yaml
from pydantic import ValidationError

from comparison import (
    BaselineComparisonResult,
    compare_with_baseline,
    validate_baseline_names,
)
from models.suite_config import BaselineComparison, SuiteConfig


def _write_nc(
    path: Path,
    values: np.ndarray,
    var: str = "co",
    var_attrs: dict | None = None,
    global_attrs: dict | None = None,
    fmt: str = "NETCDF4",
    extra_var: bool = False,
) -> None:
    dataset = xr.Dataset({var: (("time", "lat", "lon"), values)})
    if extra_var:
        dataset["surprise"] = (("time", "lat", "lon"), values)
    dataset[var].attrs.update(
        var_attrs if var_attrs is not None else {"units": "kg m-2 s-1"}
    )
    dataset.attrs.update(
        global_attrs if global_attrs is not None else {"title": "CECE test"}
    )
    encoding = {name: {"_FillValue": None} for name in dataset.data_vars}
    dataset.to_netcdf(path, format=fmt, engine="netcdf4", encoding=encoding)


def _values() -> np.ndarray:
    rng = np.random.default_rng(11)
    return rng.random((2, 3, 4))


@pytest.fixture()
def pair_dirs(tmp_path: Path) -> tuple[Path, Path]:
    realization = tmp_path / "realization"
    baseline = tmp_path / "baseline"
    realization.mkdir()
    baseline.mkdir()
    return realization, baseline


def _compare(realization: Path, baseline: Path, atol: float = 0.0) -> BaselineComparisonResult:
    return compare_with_baseline(
        realization,
        baseline,
        atol=atol,
        run_id="01JTESTRUN",
        combo="MACCITY.map-consd",
        combo_id="deadbeefdeadbeef",
        baseline_ulid="01JTESTBASELINE",
    )


def test_identical_pair_passes_bit_for_bit(pair_dirs: tuple[Path, Path]) -> None:
    realization, baseline = pair_dirs
    values = _values()
    _write_nc(realization / "cece_a.nc", values)
    _write_nc(baseline / "cece_a.nc", values)

    result = _compare(realization, baseline)

    assert result.passed
    assert result.file_names_match
    assert result.files[0].passed
    assert result.files[0].variables[0].data_match


def test_perturbed_value_respects_absolute_tolerance(pair_dirs: tuple[Path, Path]) -> None:
    realization, baseline = pair_dirs
    values = _values()
    perturbed = values.copy()
    perturbed[0, 0, 0] += 1e-6
    _write_nc(realization / "cece_a.nc", perturbed)
    _write_nc(baseline / "cece_a.nc", values)

    assert not _compare(realization, baseline, atol=0.0).passed  # bit-for-bit
    assert _compare(realization, baseline, atol=1e-5).passed  # covering atol
    assert not _compare(realization, baseline, atol=1e-7).passed  # tighter atol

    result = _compare(realization, baseline, atol=0.0)
    (variable,) = [v for f in result.files for v in f.variables]
    assert variable.max_abs_diff == pytest.approx(1e-6, rel=1e-3)


def test_nan_position_mismatch_fails_even_under_tolerance(pair_dirs: tuple[Path, Path]) -> None:
    realization, baseline = pair_dirs
    values = _values()
    with_nan = values.copy()
    with_nan[0, 1, 1] = np.nan
    _write_nc(realization / "cece_a.nc", values)
    _write_nc(baseline / "cece_a.nc", with_nan)

    assert not _compare(realization, baseline, atol=1.0).passed


def test_changed_variable_attribute_fails(pair_dirs: tuple[Path, Path]) -> None:
    realization, baseline = pair_dirs
    values = _values()
    _write_nc(realization / "cece_a.nc", values, var_attrs={"units": "mol mol-1"})
    _write_nc(baseline / "cece_a.nc", values, var_attrs={"units": "kg m-2 s-1"})

    result = _compare(realization, baseline, atol=1.0)  # attributes are always exact
    assert not result.passed
    assert not result.files[0].variables[0].attributes_match


def test_changed_global_attribute_fails(pair_dirs: tuple[Path, Path]) -> None:
    realization, baseline = pair_dirs
    values = _values()
    _write_nc(realization / "cece_a.nc", values, global_attrs={"title": "changed"})
    _write_nc(baseline / "cece_a.nc", values)

    result = _compare(realization, baseline)
    assert not result.passed
    assert not result.files[0].global_attributes_match


def test_dimension_size_change_fails(pair_dirs: tuple[Path, Path]) -> None:
    realization, baseline = pair_dirs
    _write_nc(realization / "cece_a.nc", _values()[:, :2, :])  # lat 2 vs 3
    _write_nc(baseline / "cece_a.nc", _values())

    result = _compare(realization, baseline)
    assert not result.passed
    assert not result.files[0].dimensions_match


def test_variable_added_fails(pair_dirs: tuple[Path, Path]) -> None:
    realization, baseline = pair_dirs
    values = _values()
    _write_nc(realization / "cece_a.nc", values, extra_var=True)
    _write_nc(baseline / "cece_a.nc", values)

    result = _compare(realization, baseline)
    assert not result.passed
    assert not result.files[0].variables_match


def test_file_set_mismatch_fails(pair_dirs: tuple[Path, Path]) -> None:
    realization, baseline = pair_dirs
    values = _values()
    _write_nc(realization / "cece_a.nc", values)
    _write_nc(baseline / "cece_a.nc", values)
    _write_nc(baseline / "cece_b.nc", values)  # baseline has an extra file

    result = _compare(realization, baseline)
    assert not result.passed
    assert not result.file_names_match


def test_format_mismatch_fails(pair_dirs: tuple[Path, Path]) -> None:
    realization, baseline = pair_dirs
    values = _values()
    _write_nc(realization / "cece_a.nc", values, fmt="NETCDF3_CLASSIC")
    _write_nc(baseline / "cece_a.nc", values, fmt="NETCDF4")

    result = _compare(realization, baseline)
    assert not result.passed
    assert not result.files[0].format_match


def test_result_yaml_round_trips_on_failure(pair_dirs: tuple[Path, Path], tmp_path: Path) -> None:
    realization, baseline = pair_dirs
    values = _values()
    _write_nc(realization / "cece_a.nc", values + 1.0)
    _write_nc(baseline / "cece_a.nc", values)

    result = _compare(realization, baseline)
    assert not result.passed

    yaml_path = tmp_path / "comparison.yaml"
    result.to_yaml(yaml_path)
    reloaded = BaselineComparisonResult.model_validate(yaml.safe_load(yaml_path.read_text()))
    assert reloaded == result


def test_baseline_comparison_model_validation() -> None:
    block = BaselineComparison()
    assert block.atol == 0.0
    assert block.baselines == {}
    with pytest.raises(ValidationError):
        BaselineComparison(atol=-0.5)


def test_unknown_baseline_combination_name_rejected() -> None:
    with pytest.raises(ValueError, match="NOPE"):
        validate_baseline_names({"NOPE.map-consd": "01JZZ"}, {"MACCITY.map-consd"})
    validate_baseline_names({"MACCITY.map-consd": "01JZZ"}, {"MACCITY.map-consd"})


def test_suite_parses_baseline_comparison_block(tmp_path: Path, cece_config_path: Path) -> None:
    suite_file = tmp_path / "baseline-suite.yaml"
    suite_file.write_text(
        f"name: baseline-suite\nconfig_path: {cece_config_path}\ntimeout_s: 5\n"
        "baseline_comparison:\n  atol: 0.001\n  baselines:\n"
        "    MACCITY.map-consd: 01JZZZZZZZZZZZZZZZZZZZZZZZ\n"
        "sweep:\n  cece_data:\n    streams:\n      - name: MACCITY\n        mapalgo: [consd]\n"
    )
    suite = SuiteConfig.from_yaml(suite_file)
    assert suite.baseline_comparison is not None
    assert suite.baseline_comparison.atol == 0.001
    assert suite.baseline_comparison.baselines == {
        "MACCITY.map-consd": "01JZZZZZZZZZZZZZZZZZZZZZZZ"
    }
