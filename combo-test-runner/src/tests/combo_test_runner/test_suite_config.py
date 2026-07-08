import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from models.suite_config import SuiteConfig


def test_config_path_resolves_relative_to_suite_file(suite_path: Path) -> None:
    suite = SuiteConfig.from_yaml(suite_path)
    assert suite.config_path == (suite_path.parent / ".." / "cece" / "simple-maccity.yaml").resolve()
    assert suite.config_path.is_file()


def test_config_search_path_prepends_whole_path(tmp_path: Path, suite_path: Path, cece_config_path: Path) -> None:
    # Mirror the config tree layout under a search directory; the suite's
    # ../cece reference walks out of the search dir (accepted behavior).
    (tmp_path / "suite").mkdir()
    (tmp_path / "cece").mkdir()
    shutil.copy(suite_path, tmp_path / "suite" / "copied-suite.yaml")
    shutil.copy(cece_config_path, tmp_path / "cece" / "simple-maccity.yaml")

    suite = SuiteConfig.from_yaml(tmp_path / "suite" / "copied-suite.yaml", config_search_path=tmp_path / "suite")
    assert suite.config_path == (tmp_path / "cece" / "simple-maccity.yaml").resolve()


def test_absolute_config_path_ignores_search_path(tmp_path: Path, cece_config_path: Path) -> None:
    suite_file = tmp_path / "abs-suite.yaml"
    suite_file.write_text(
        f"config_path: {cece_config_path}\ntimeout_s: 5\nsweep:\n  mapalgo: [consd]\n"
    )
    suite = SuiteConfig.from_yaml(suite_file, config_search_path=tmp_path)
    assert suite.config_path == cece_config_path


def test_missing_config_path_raises(tmp_path: Path) -> None:
    suite_file = tmp_path / "broken-suite.yaml"
    suite_file.write_text("config_path: nope.yaml\ntimeout_s: 5\nsweep:\n  mapalgo: [consd]\n")
    with pytest.raises(FileNotFoundError, match="nope.yaml"):
        SuiteConfig.from_yaml(suite_file)


def test_assertions_default_when_section_absent(tmp_path: Path, cece_config_path: Path) -> None:
    suite_file = tmp_path / "no-assertions-suite.yaml"
    suite_file.write_text(
        f"config_path: {cece_config_path}\ntimeout_s: 5\nsweep:\n  mapalgo: [consd]\n"
    )
    suite = SuiteConfig.from_yaml(suite_file)
    assert suite.assertions.expected_nc_file_count is None
    assert suite.assertions.validate_filenames is True


def test_invalid_sweep_value_fails_at_load(tmp_path: Path, cece_config_path: Path) -> None:
    suite_file = tmp_path / "typo-suite.yaml"
    suite_file.write_text(
        f"config_path: {cece_config_path}\ntimeout_s: 5\nsweep:\n  mapalgo: [bilinnear]\n"
    )
    with pytest.raises(ValidationError):
        SuiteConfig.from_yaml(suite_file)
