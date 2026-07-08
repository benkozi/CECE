from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# combo-test-runner/src/settings.py -> CECE repo root is two levels up from src/
_REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Environment-derived configuration. The CECE_ prefix is deliberately not
    runner-specific so this class can host other variable groups later."""

    model_config = SettingsConfigDict(env_prefix="CECE_")

    docker_image: str = "deckyfre/cece-dev"
    root: Path = _REPO_ROOT
    driver_path: str = "./build/cece_standalone_driver"
    run_timeout_s: int = 300
    log_level: str = "INFO"
    # None -> LocalCluster sizes itself to all available cores.
    dask_nworkers: int | None = Field(None, gt=0)
    # When set, prepended to relative config paths (kept whole, so nested and
    # ../ paths work); absolute provided paths are always used as-is.
    config_search_path: Path | None = None  # applies to the suite's config_path
    suite_config_search_path: Path | None = None  # applies to --suite-config
