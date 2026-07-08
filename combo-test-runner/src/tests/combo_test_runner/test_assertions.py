from pathlib import Path

import pytest

from assertions import assert_nc_file_count, derive_expected_nc_file_count
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
