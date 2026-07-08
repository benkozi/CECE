"""Harness-test fixtures: paths to the checked-in maccity configs."""

from pathlib import Path

import pytest

_CONFIG_ROOT = Path(__file__).resolve().parents[1] / "config"


@pytest.fixture()
def cece_config_path() -> Path:
    return _CONFIG_ROOT / "cece" / "simple-maccity.yaml"


@pytest.fixture()
def suite_path() -> Path:
    return _CONFIG_ROOT / "suite" / "simple-maccity-suite.yaml"
