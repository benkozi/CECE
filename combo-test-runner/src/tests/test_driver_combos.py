import pytest

from analysis import RunContext, compute_file_stats, write_combo_stats_csv
from assertions import assert_nc_file_count, assert_nc_filenames
from models.suite_config import Analysis, Assertions
from runner import DriverRunResult


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


def test_nc_filenames(driver_run: DriverRunResult, suite_assertions: Assertions) -> None:
    """The NetCDF filenames match filename_pattern at the expected write times."""
    if driver_run.error is not None:
        pytest.skip(f"driver run failed: {driver_run.error}")
    if not suite_assertions.validate_filenames:
        pytest.skip("filename validation disabled by suite config")
    assert_nc_filenames(driver_run.combo_dir, driver_run.config)


def test_descriptive_stats(
    request: pytest.FixtureRequest,
    driver_run: DriverRunResult,
    suite_analysis: Analysis,
    run_context: RunContext,
) -> None:
    """Descriptive statistics for every NetCDF the combo produced, written to
    the combo's stats CSV. No value assertions yet — baselines come later."""
    if driver_run.error is not None:
        pytest.skip(f"driver run failed: {driver_run.error}")
    if not suite_analysis.compute_descriptive_stats:
        pytest.skip("descriptive stats disabled by suite config")
    # Lazy: only analysis runs pay dask cluster startup.
    request.getfixturevalue("dask_client")

    nc_files = sorted(driver_run.combo_dir.glob("*.nc"))
    stats = [
        entry
        for nc_file in nc_files
        for entry in compute_file_stats(nc_file, combo=driver_run.combo.name, run=run_context)
    ]
    csv_path = driver_run.combo_dir / f"{driver_run.combo.name}-stats.csv"
    frame = write_combo_stats_csv(stats, csv_path)

    assert csv_path.is_file()
    assert set(frame["file"]) == {nc_file.name for nc_file in nc_files}
    assert len(frame) >= len(nc_files)
