from pathlib import Path, PurePosixPath

import pytest

from resolution import resolve_output_roots, resolve_suite_path
from settings import Settings


def test_relative_output_root_maps_under_work() -> None:
    host, container = resolve_output_roots("combo_runs", Path("/host/cece"))
    assert host == Path("/host/cece/combo_runs")
    assert container == PurePosixPath("/work/combo_runs")


def test_absolute_output_root_under_work_is_mapped() -> None:
    host, container = resolve_output_roots("/work/nested/runs", Path("/host/cece"))
    assert host == Path("/host/cece/nested/runs")
    assert container == PurePosixPath("/work/nested/runs")


def test_absolute_output_root_outside_work_raises() -> None:
    with pytest.raises(ValueError, match="/work"):
        resolve_output_roots("/elsewhere/runs", Path("/host/cece"))


def test_suite_path_absolute_used_as_is() -> None:
    settings = Settings(suite_config_search_path=Path("/library/suite"))
    assert resolve_suite_path("/abs/suite.yaml", settings) == Path("/abs/suite.yaml")


def test_suite_path_search_path_prepends_whole_relative_path() -> None:
    settings = Settings(suite_config_search_path=Path("/library/suite"))
    assert resolve_suite_path("nightly/s.yaml", settings) == Path(
        "/library/suite/nightly/s.yaml"
    )


def test_suite_path_without_search_path_is_unchanged() -> None:
    settings = Settings(suite_config_search_path=None)
    assert resolve_suite_path("nightly/s.yaml", settings) == Path("nightly/s.yaml")
