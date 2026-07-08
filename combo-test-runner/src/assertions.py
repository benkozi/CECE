"""Post-run assertions evaluated against a combination's output directory."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from logs import get_logger
from models.cece_config import CeceConfig

logger = get_logger("assertions")


def _render_filename_pattern(pattern: str, when: datetime) -> str:
    return (
        pattern.replace("{YYYY}", f"{when.year:04d}")
        .replace("{MM}", f"{when.month:02d}")
        .replace("{DD}", f"{when.day:02d}")
        .replace("{HH}", f"{when.hour:02d}")
        .replace("{mm}", f"{when.minute:02d}")
        .replace("{ss}", f"{when.second:02d}")
    )


def derive_expected_nc_file_count(config: CeceConfig) -> int:
    """Expected NetCDF output file count from the generated combo config:
    one file per output.frequency_steps timesteps; 0 when output is disabled
    or absent."""
    if config.output is None or not config.output.enabled:
        return 0
    start = datetime.fromisoformat(config.driver.start_time)
    end = datetime.fromisoformat(config.driver.end_time)
    n_steps = int((end - start).total_seconds()) // config.driver.timestep_seconds
    logger.info(
        "deriving expected_nc_file_count: timestep_seconds=%s n_steps=%s frequency_steps=%s",
        config.driver.timestep_seconds,
        n_steps,
        config.output.frequency_steps,
    )
    return n_steps // config.output.frequency_steps


def assert_nc_file_count(combo_dir: Path, config: CeceConfig, expected: int | None) -> None:
    """Assert the number of NetCDF files in the combo directory (non-recursive).

    expected=None derives the count from the combo config; an explicit 0
    asserts that no NetCDF files were produced.
    """
    if expected is None:
        expected = derive_expected_nc_file_count(config)
    found = len(list(combo_dir.glob("*.nc")))
    logger.info("testing expected_nc_file_count=%s, found %s files", expected, found)
    assert found == expected, f"expected {expected} NetCDF file(s) in {combo_dir}, found {found}"


def expected_nc_filenames(config: CeceConfig) -> set[str]:
    """Expected NetCDF filenames: filename_pattern rendered at each write
    time, the first at start_time + frequency_steps * timestep_seconds (the
    end of the first output interval, not t=0)."""
    if config.output is None or not config.output.enabled:
        return set()
    count = derive_expected_nc_file_count(config)
    start = datetime.fromisoformat(config.driver.start_time)
    interval = timedelta(seconds=config.output.frequency_steps * config.driver.timestep_seconds)
    return {
        _render_filename_pattern(config.output.filename_pattern, start + k * interval)
        for k in range(1, count + 1)
    }


def assert_nc_filenames(combo_dir: Path, config: CeceConfig) -> None:
    """Assert the NetCDF filenames in the combo directory (non-recursive)
    exactly match the expected set rendered from filename_pattern."""
    expected = expected_nc_filenames(config)
    found = {path.name for path in combo_dir.glob("*.nc")}
    logger.info("testing expected filenames=%s, found %s", sorted(expected), sorted(found))
    missing = sorted(expected - found)
    unexpected = sorted(found - expected)
    assert found == expected, (
        f"NetCDF filenames in {combo_dir} do not match: missing {missing}, unexpected {unexpected}"
    )
