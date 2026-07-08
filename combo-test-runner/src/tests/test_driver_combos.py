import pytest
from conftest import DriverRunResult

from assertions import assert_nc_file_count
from models.suite_config import Assertions


def test_driver_execution(driver_run: DriverRunResult) -> None:
    """The driver ran to completion with exit code 0."""
    if driver_run.error is not None:
        pytest.fail(f"driver run failed: {driver_run.error}")


def test_nc_file_count(driver_run: DriverRunResult, suite_assertions: Assertions) -> None:
    """The combo directory holds the expected number of NetCDF output files."""
    if driver_run.error is not None:
        pytest.skip(f"driver run failed: {driver_run.error}")
    assert_nc_file_count(
        driver_run.combo_dir,
        driver_run.config,
        suite_assertions.expected_nc_file_count,
    )
