from pathlib import Path

import pytest

import numpy as np
import xarray as xr

from assertions import (
    assert_nc_file_count,
    assert_nc_filenames,
    assert_species_units,
    derive_expected_nc_file_count,
    expected_nc_filenames,
)
from models.cece_config import CeceConfig


def _write_species_nc(path: Path, variable: str = "co", units: str | None = None) -> None:
    dataset = xr.Dataset({variable: (("lat", "lon"), np.ones((2, 3)))})
    if units is not None:
        dataset[variable].attrs["units"] = units
    dataset.to_netcdf(path, engine="netcdf4")


@pytest.fixture()
def maccity_config(cece_config_path: Path) -> CeceConfig:
    return CeceConfig.from_yaml(cece_config_path)


def test_derived_count_for_maccity(maccity_config: CeceConfig, maccity_n_timesteps: int) -> None:
    assert derive_expected_nc_file_count(maccity_config) == maccity_n_timesteps


def test_derived_count_zero_when_output_disabled(maccity_config: CeceConfig) -> None:
    assert maccity_config.output is not None
    maccity_config.output.enabled = False
    assert derive_expected_nc_file_count(maccity_config) == 0


def test_derived_count_zero_when_output_absent(maccity_config: CeceConfig) -> None:
    maccity_config.output = None
    assert derive_expected_nc_file_count(maccity_config) == 0


def test_derived_count_multi_step(maccity_config: CeceConfig) -> None:
    # 6 hours at 3600s = 6 steps; one write per 2 steps -> 3 files
    maccity_config.driver.end_time = "2010-01-01T06:00:00"
    assert maccity_config.output is not None
    maccity_config.output.frequency_steps = 2
    assert derive_expected_nc_file_count(maccity_config) == 3


def test_assert_passes_with_derived_count(
    tmp_path: Path, maccity_config: CeceConfig, maccity_expected_filenames: set[str]
) -> None:
    for name in maccity_expected_filenames:
        (tmp_path / name).touch()
    assert_nc_file_count(tmp_path, maccity_config, expected=None)


def test_assert_fails_when_files_missing(
    tmp_path: Path, maccity_config: CeceConfig, maccity_n_timesteps: int
) -> None:
    with pytest.raises(AssertionError, match=f"expected {maccity_n_timesteps} NetCDF"):
        assert_nc_file_count(tmp_path, maccity_config, expected=None)


def test_explicit_zero_expects_no_files(tmp_path: Path, maccity_config: CeceConfig) -> None:
    assert_nc_file_count(tmp_path, maccity_config, expected=0)
    (tmp_path / "unexpected.nc").touch()
    with pytest.raises(AssertionError, match="expected 0 NetCDF"):
        assert_nc_file_count(tmp_path, maccity_config, expected=0)


def test_count_is_non_recursive(tmp_path: Path, maccity_config: CeceConfig) -> None:
    (tmp_path / "cece_20100101_000000.nc").touch()
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "ignored.nc").touch()
    assert_nc_file_count(tmp_path, maccity_config, expected=1)


def test_species_units_exact_match_passes(tmp_path: Path) -> None:
    _write_species_nc(tmp_path / "a.nc", units="kg m-2 s-1")
    _write_species_nc(tmp_path / "b.nc", units="kg m-2 s-1")
    assert_species_units(tmp_path, "co", expected="kg m-2 s-1")


def test_species_units_mismatch_fails_naming_files(tmp_path: Path) -> None:
    _write_species_nc(tmp_path / "a.nc", units="kg m-2 s-1")
    _write_species_nc(tmp_path / "b.nc", units="mol mol-1")  # the driver-bug shape
    with pytest.raises(AssertionError) as excinfo:
        assert_species_units(tmp_path, "co", expected="kg m-2 s-1")
    message = str(excinfo.value)
    assert "b.nc: expected 'kg m-2 s-1', found 'mol mol-1'" in message
    assert "a.nc" not in message  # the matching file is not reported


def test_species_units_none_expects_absent_attribute(tmp_path: Path) -> None:
    _write_species_nc(tmp_path / "a.nc", units=None)
    assert_species_units(tmp_path, "co", expected=None)


def test_species_units_none_fails_on_present_attribute(tmp_path: Path) -> None:
    _write_species_nc(tmp_path / "a.nc", units="")  # empty string counts as present
    with pytest.raises(AssertionError, match="expected None, found ''"):
        assert_species_units(tmp_path, "co", expected=None)


def test_species_units_missing_variable_fails(tmp_path: Path) -> None:
    _write_species_nc(tmp_path / "a.nc", variable="nox", units="kg m-2 s-1")
    with pytest.raises(AssertionError, match="variable 'co' not present"):
        assert_species_units(tmp_path, "co", expected="kg m-2 s-1")


def test_expected_filenames_maccity(
    maccity_config: CeceConfig, maccity_expected_filenames: set[str]
) -> None:
    # First write at hour 1, then hourly through the run's end.
    assert expected_nc_filenames(maccity_config) == maccity_expected_filenames


def test_expected_filenames_multi_step(maccity_config: CeceConfig) -> None:
    # 6 hours at 3600s, one write per 2 steps -> files at hours 2, 4, 6
    maccity_config.driver.end_time = "2010-01-01T06:00:00"
    assert maccity_config.output is not None
    maccity_config.output.frequency_steps = 2
    assert expected_nc_filenames(maccity_config) == {
        "cece_20100101_020000.nc",
        "cece_20100101_040000.nc",
        "cece_20100101_060000.nc",
    }


def test_expected_filenames_empty_when_output_disabled(maccity_config: CeceConfig) -> None:
    assert maccity_config.output is not None
    maccity_config.output.enabled = False
    assert expected_nc_filenames(maccity_config) == set()


def test_expected_filenames_empty_when_output_absent(maccity_config: CeceConfig) -> None:
    maccity_config.output = None
    assert expected_nc_filenames(maccity_config) == set()


def test_assert_filenames_passes_with_expected_files(
    tmp_path: Path, maccity_config: CeceConfig, maccity_expected_filenames: set[str]
) -> None:
    for name in maccity_expected_filenames:
        (tmp_path / name).touch()
    assert_nc_filenames(tmp_path, maccity_config)


def test_assert_filenames_fails_on_hour_zero_stamps(
    tmp_path: Path, maccity_config: CeceConfig, maccity_n_timesteps: int
) -> None:
    # The known driver bug scenario: stamps shifted to start at hour 0, so the
    # run's final hour is missing and hour 0 is unexpected.
    for hour in range(maccity_n_timesteps):
        (tmp_path / f"cece_20100101_{hour:02d}0000.nc").touch()
    with pytest.raises(AssertionError) as excinfo:
        assert_nc_filenames(tmp_path, maccity_config)
    assert f"missing ['cece_20100101_{maccity_n_timesteps:02d}0000.nc']" in str(excinfo.value)
    assert "unexpected ['cece_20100101_000000.nc']" in str(excinfo.value)
