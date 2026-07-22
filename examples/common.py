"""Shared machinery for the example entrypoints (stdlib only).

Holds the example/bucket enums, one frozen ExamplesConfig dataclass (paths,
tunables, and the example -> data-file mapping) exposed as the single CONFIG
instance, the blocking download machinery, direct driver execution (no
docker — the entrypoints run unchanged inside the dev container or
natively, e.g. on HPC), and logging configuration.
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from enum import StrEnum, unique
from pathlib import Path

logger = logging.getLogger("cece.examples")


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


def _repo_root() -> Path:
    # examples/common.py -> repo root is one level above examples/.
    return Path(__file__).resolve().parents[1]


def _example_data() -> dict[Example, tuple[DataFile, ...]]:
    maccity = DataFile(Bucket.GEOS_CHEM, "HEMCO/MACCITY/v2014-07/MACCity_4x5.nc")
    noaa_htap = (
        "experiment-user-cases/release-public-v3.0.0/fix/fix_emis/HTAP/v2015-03/NO"
    )
    htap_sectors = tuple(
        DataFile(
            Bucket.NOAA_UFS_SRW_PDS,
            f"{noaa_htap}/EDGAR_HTAP_NO_{sector}.generic.01x01.nc",
        )
        for sector in ("TRANSPORT", "SHIPS", "RESIDENTIAL", "INDUSTRY", "ENERGY")
    )
    # CAMS-TEMPO has no public download source yet: these geos-chem keys are
    # aspirational and EXPECTED TO FAIL (404) until the data is published
    # there. Local copies in data/ are honored (the cache guard skips
    # present files).
    cams_weights = tuple(
        DataFile(
            Bucket.GEOS_CHEM,
            "HEMCO/CAMS-TEMPO/v3.1-2021/"
            f"CAMS-GLOB-TEMPO_Glb_0.1x0.1_tmp_weights_v3.1_{kind}.nc",
        )
        for kind in ("hourly", "weekly", "monthly")
    )
    return {
        Example.EX1: htap_sectors + cams_weights,
        Example.EX2: (
            maccity,
            DataFile(
                Bucket.GEOS_CHEM,
                "HEMCO/CEDS/v2020-08/1970/CO-em-total-anthro_CEDS_1970.nc",
            ),
            DataFile(Bucket.GEOS_CHEM, "HEMCO/MASKS/v2014-07/Canada_mask.gen.1x1.nc"),
        ),
        Example.EX3: (maccity,),
        Example.EX4: (
            DataFile(
                Bucket.GEOS_CHEM, "HEMCO/HTAPv3/v2022-12/2018/HTAPv3_NO_0.1x0.1_2018.nc"
            ),
        ),
        Example.EX5: (
            maccity,
            DataFile(
                Bucket.GEOS_CHEM,
                "HEMCO/MACCITY/v2014-07/MACCity_anthro_NOx_2000-2010_16080.nc",
            ),
        ),
        Example.EX6: (
            DataFile(
                Bucket.GEOS_CHEM, "HEMCO/EDGARv43/v2016-11/EDGAR_v43.NOx.POW.0.1x0.1.nc"
            ),
            DataFile(
                Bucket.GEOS_CHEM,
                "HEMCO/CEDS/v2020-08/1970/ALK4_butanes-em-total-anthro_CEDS_1970.nc",
            ),
        ),
        Example.EX7: htap_sectors + cams_weights,
        # advanced/megan3 reference /data/inventories/... paths with no public
        # S3 mapping; nothing to download until sources are identified.
        Example.ADVANCED: (),
        Example.MEGAN3: (),
    }


@dataclass(frozen=True)
class ExamplesConfig:
    """All example-tooling configuration in one place; functions read the
    module-level CONFIG instance rather than scattered globals."""

    repo_root: Path = field(default_factory=_repo_root)
    chunk_bytes: int = 1024 * 1024
    driver_path_env: str = "CECE_EXAMPLES_DRIVER_PATH"
    log_level_env: str = "CECE_EXAMPLES_LOG_LEVEL"
    example_data: dict[Example, tuple[DataFile, ...]] = field(
        default_factory=_example_data
    )

    @property
    def config_dir(self) -> Path:
        return self.repo_root / "examples" / "config"

    @property
    def default_dst_dir(self) -> Path:
        return self.repo_root / "data"

    def config_path(self, example: Example) -> Path:
        return self.config_dir / f"cece_config_{example.value}.yaml"

    def driver_path(self) -> Path:
        return self.repo_root / os.environ.get(
            self.driver_path_env, "build/cece_standalone_driver"
        )

    def log_level(self) -> str:
        return os.environ.get(self.log_level_env, "INFO").upper()


CONFIG = ExamplesConfig()


def configure_logging() -> None:
    """Basic stdlib logging for the entrypoints; level via
    CONFIG.log_level_env (default INFO)."""
    logging.basicConfig(
        level=CONFIG.log_level(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


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
    parser.add_argument("--all", action="store_true", help="Select every example.")
    parser.add_argument(
        "--dst-dir",
        type=Path,
        default=CONFIG.default_dst_dir,
        help=f"Data directory, created if missing (default: {CONFIG.default_dst_dir}).",
    )
    return parser


def resolve_examples(
    parser: argparse.ArgumentParser, args: argparse.Namespace
) -> list[Example]:
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
        while chunk := response.read(CONFIG.chunk_bytes):
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


def run_example(example: Example) -> int:
    """Execute one example by running the driver binary directly (never
    docker — this works inside the dev container and natively, e.g. HPC).
    Returns the driver's exit code."""
    driver = CONFIG.driver_path()
    config = CONFIG.config_path(example)
    if not driver.is_file():
        logger.error(
            "driver not found at %s (override with %s)",
            driver,
            CONFIG.driver_path_env,
        )
        return 1
    if not config.is_file():
        logger.error("config not found at %s", config)
        return 1
    env = os.environ | {
        # Required when running as root in the dev container; harmless natively.
        "OMPI_ALLOW_RUN_AS_ROOT": "1",
        "OMPI_ALLOW_RUN_AS_ROOT_CONFIRM": "1",
    }
    relative_config = config.relative_to(CONFIG.repo_root)
    logger.info("running %s: %s %s", example.value, driver, relative_config)
    completed = subprocess.run(
        [str(driver), str(relative_config)], cwd=CONFIG.repo_root, env=env
    )
    return completed.returncode
