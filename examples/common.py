"""Shared machinery for the example entrypoints (stdlib only).

Holds the example/bucket enums, the example -> data-file mapping, the
blocking download machinery, direct driver execution (no docker — the
entrypoints run unchanged inside the dev container or natively, e.g. on
HPC), and logging configuration.
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from enum import StrEnum, unique
from pathlib import Path

logger = logging.getLogger("cece.examples")

# examples/common.py -> repo root is one level above examples/.
REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = REPO_ROOT / "examples" / "config"
DEFAULT_DST_DIR = REPO_ROOT / "data"
_CHUNK_BYTES = 1024 * 1024
_DRIVER_PATH_ENV = "CECE_EXAMPLES_DRIVER_PATH"
_LOG_LEVEL_ENV = "CECE_EXAMPLES_LOG_LEVEL"


def configure_logging() -> None:
    """Basic stdlib logging for the entrypoints; level via
    CECE_EXAMPLES_LOG_LEVEL (default INFO)."""
    logging.basicConfig(
        level=os.environ.get(_LOG_LEVEL_ENV, "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


@unique
class Example(StrEnum):
    """One member per shipped example config (cece_config_<value>.yaml)."""

    EX1 = "ex1"
    EX2 = "ex2"
    EX3 = "ex3"
    EX4 = "ex4"
    EX5 = "ex5"
    EX6 = "ex6"
    EX7 = "ex7"
    ADVANCED = "advanced"
    MEGAN3 = "megan3"


@unique
class Bucket(StrEnum):
    """Public S3 buckets the example data comes from."""

    GEOS_CHEM = "geos-chem"
    NOAA_UFS_SRW_PDS = "noaa-ufs-srw-pds"

    @property
    def base_url(self) -> str:
        return f"https://{self.value}.s3.amazonaws.com"


@dataclass(frozen=True)
class DataFile:
    """One downloadable input: an S3 bucket and the object key within it."""

    bucket: Bucket
    key: str

    @property
    def filename(self) -> str:
        return self.key.rsplit("/", 1)[-1]

    @property
    def url(self) -> str:
        return f"{self.bucket.base_url}/{self.key}"


@dataclass(frozen=True)
class DownloadOutcome:
    """Result of one fetch attempt (or cache skip)."""

    file: DataFile
    ok: bool
    detail: str


_MACCITY = DataFile(Bucket.GEOS_CHEM, "HEMCO/MACCITY/v2014-07/MACCity_4x5.nc")
_NOAA_HTAP = "experiment-user-cases/release-public-v3.0.0/fix/fix_emis/HTAP/v2015-03/NO"
_HTAP_SECTORS = tuple(
    DataFile(Bucket.NOAA_UFS_SRW_PDS, f"{_NOAA_HTAP}/EDGAR_HTAP_NO_{sector}.generic.01x01.nc")
    for sector in ("TRANSPORT", "SHIPS", "RESIDENTIAL", "INDUSTRY", "ENERGY")
)
# CAMS-TEMPO has no public download source yet: these geos-chem keys are
# aspirational and EXPECTED TO FAIL (404) until the data is published there.
# Local copies in data/ are honored (the cache guard skips present files).
_CAMS_WEIGHTS = tuple(
    DataFile(
        Bucket.GEOS_CHEM,
        f"HEMCO/CAMS-TEMPO/v3.1-2021/CAMS-GLOB-TEMPO_Glb_0.1x0.1_tmp_weights_v3.1_{kind}.nc",
    )
    for kind in ("hourly", "weekly", "monthly")
)

EXAMPLE_DATA: dict[Example, tuple[DataFile, ...]] = {
    Example.EX1: _HTAP_SECTORS + _CAMS_WEIGHTS,
    Example.EX2: (
        _MACCITY,
        DataFile(Bucket.GEOS_CHEM, "HEMCO/CEDS/v2020-08/1970/CO-em-total-anthro_CEDS_1970.nc"),
        DataFile(Bucket.GEOS_CHEM, "HEMCO/MASKS/v2014-07/Canada_mask.gen.1x1.nc"),
    ),
    Example.EX3: (_MACCITY,),
    Example.EX4: (
        DataFile(Bucket.GEOS_CHEM, "HEMCO/HTAPv3/v2022-12/2018/HTAPv3_NO_0.1x0.1_2018.nc"),
    ),
    Example.EX5: (
        _MACCITY,
        DataFile(
            Bucket.GEOS_CHEM,
            "HEMCO/MACCITY/v2014-07/MACCity_anthro_NOx_2000-2010_16080.nc",
        ),
    ),
    Example.EX6: (
        DataFile(Bucket.GEOS_CHEM, "HEMCO/EDGARv43/v2016-11/EDGAR_v43.NOx.POW.0.1x0.1.nc"),
        DataFile(
            Bucket.GEOS_CHEM,
            "HEMCO/CEDS/v2020-08/1970/ALK4_butanes-em-total-anthro_CEDS_1970.nc",
        ),
    ),
    Example.EX7: _HTAP_SECTORS + _CAMS_WEIGHTS,
    # advanced/megan3 reference /data/inventories/... paths with no public
    # S3 mapping; nothing to download until sources are identified.
    Example.ADVANCED: (),
    Example.MEGAN3: (),
}


def config_path(example: Example) -> Path:
    return CONFIG_DIR / f"cece_config_{example.value}.yaml"


def build_parser(description: str) -> argparse.ArgumentParser:
    """Shared CLI: --example/--all/--dst-dir (both entrypoints)."""
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--example",
        help=(
            "Comma-separated example id(s) to select "
            f"({', '.join(member.value for member in Example)})"
        ),
    )
    parser.add_argument(
        "--all", action="store_true", help="Select every example."
    )
    parser.add_argument(
        "--dst-dir",
        type=Path,
        default=DEFAULT_DST_DIR,
        help=f"Data directory, created if missing (default: {DEFAULT_DST_DIR}).",
    )
    return parser


def resolve_examples(parser: argparse.ArgumentParser, args: argparse.Namespace) -> list[Example]:
    """Validated selection from --example/--all (exactly one required)."""
    if args.all == bool(args.example):
        parser.error("provide exactly one of --example or --all")
    if args.all:
        return list(Example)
    selected: list[Example] = []
    for raw in args.example.split(","):
        token = raw.strip()
        try:
            selected.append(Example(token))
        except ValueError:
            parser.error(
                f"unknown example id {token!r}; valid ids: "
                f"{', '.join(member.value for member in Example)}"
            )
    return selected


def needs_fetch(target: Path) -> bool:
    """Cache guard: fetch unless the target exists and is non-empty (a
    truncated file is re-fetched)."""
    return not (target.is_file() and target.stat().st_size > 0)


def _fetch(url: str, target: Path) -> None:
    with urllib.request.urlopen(url) as response, open(target, "wb") as sink:
        while chunk := response.read(_CHUNK_BYTES):
            sink.write(chunk)


def download(files: tuple[DataFile, ...], dst_dir: Path) -> list[DownloadOutcome]:
    """Sequentially fetch every file into dst_dir (created if missing),
    skipping present non-empty targets. Every file is attempted even after
    failures; partial files are removed so retries stay live."""
    dst_dir.mkdir(parents=True, exist_ok=True)
    outcomes: list[DownloadOutcome] = []
    seen: set[str] = set()
    for file in files:
        if file.filename in seen:
            continue
        seen.add(file.filename)
        target = dst_dir / file.filename
        if not needs_fetch(target):
            logger.info("cached: %s", file.filename)
            outcomes.append(DownloadOutcome(file, True, "cached"))
            continue
        logger.info("fetching %s", file.url)
        try:
            _fetch(file.url, target)
        except (urllib.error.URLError, OSError) as exc:
            target.unlink(missing_ok=True)
            logger.error("FAILED %s: %s", file.filename, exc)
            outcomes.append(DownloadOutcome(file, False, str(exc)))
        else:
            logger.info("fetched %s", file.filename)
            outcomes.append(DownloadOutcome(file, True, "downloaded"))
    return outcomes


def run_example(example: Example, repo_root: Path = REPO_ROOT) -> int:
    """Execute one example by running the driver binary directly (never
    docker — this works inside the dev container and natively, e.g. HPC).
    Returns the driver's exit code."""
    driver = repo_root / os.environ.get(
        _DRIVER_PATH_ENV, "build/cece_standalone_driver"
    )
    config = config_path(example)
    if not driver.is_file():
        logger.error("driver not found at %s (override with %s)", driver, _DRIVER_PATH_ENV)
        return 1
    if not config.is_file():
        logger.error("config not found at %s", config)
        return 1
    env = os.environ | {
        # Required when running as root in the dev container; harmless natively.
        "OMPI_ALLOW_RUN_AS_ROOT": "1",
        "OMPI_ALLOW_RUN_AS_ROOT_CONFIRM": "1",
    }
    relative_config = config.relative_to(repo_root)
    logger.info("running %s: %s %s", example.value, driver, relative_config)
    completed = subprocess.run(
        [str(driver), str(relative_config)], cwd=repo_root, env=env
    )
    return completed.returncode
