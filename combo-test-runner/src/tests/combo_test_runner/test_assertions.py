from pathlib import Path

import pytest

from assertions import (
    assert_nc_file_count,
    assert_nc_filenames,
    derive_expected_nc_file_count,
    expected_nc_filenames,
)
from models.cece_config import CeceConfig


@pytest.fixture()
def maccity_config(cece_config_path: Path) -> CeceConfig:
    return CeceConfig.from_yaml(cece_config_path)


def test_derived_count_for_maccity_is_one(maccity_config: CeceConfig) -> None:
    assert derive_expected_nc_file_count(maccity_config) == 1


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


def test_assert_passes_with_derived_count(tmp_path: Path, maccity_config: CeceConfig) -> None:
    (tmp_path / "cece_20100101_000000.nc").touch()
    assert_nc_file_count(tmp_path, maccity_config, expected=None)


def test_assert_fails_when_files_missing(tmp_path: Path, maccity_config: CeceConfig) -> None:
    with pytest.raises(AssertionError, match="expected 1 NetCDF"):
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


def test_expected_filenames_maccity_first_write_at_hour_one(maccity_config: CeceConfig) -> None:
    assert expected_nc_filenames(maccity_config) == {"cece_20100101_010000.nc"}


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


def test_assert_filenames_passes_with_expected_file(tmp_path: Path, maccity_config: CeceConfig) -> None:
    (tmp_path / "cece_20100101_010000.nc").touch()
    assert_nc_filenames(tmp_path, maccity_config)


def test_assert_filenames_fails_on_hour_zero_stamp(tmp_path: Path, maccity_config: CeceConfig) -> None:
    # The known driver bug scenario: file stamped at hour 0 instead of hour 1.
    (tmp_path / "cece_20100101_000000.nc").touch()
    with pytest.raises(AssertionError) as excinfo:
        assert_nc_filenames(tmp_path, maccity_config)
    assert "missing ['cece_20100101_010000.nc']" in str(excinfo.value)
    assert "unexpected ['cece_20100101_000000.nc']" in str(excinfo.value)
