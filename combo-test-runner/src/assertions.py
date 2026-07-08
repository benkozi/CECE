"""Post-run assertions evaluated against a combination's output directory."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from logs import get_logger
from models.cece_config import CeceConfig

logger = get_logger("assertions")


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
