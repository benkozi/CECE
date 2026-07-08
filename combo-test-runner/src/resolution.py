"""Pure path-resolution rules for suite files and output roots.

Kept free of pytest so the rules are unit-testable; the integration conftest
converts errors to pytest.UsageError at the boundary.
"""

from pathlib import Path, PurePosixPath

from settings import Settings

CONTAINER_WORK = PurePosixPath("/work")


def resolve_output_roots(option: str, cece_root: Path) -> tuple[Path, PurePosixPath]:
    """Map an explicit --combo-output-root to (host path, container path).

    Relative paths resolve against /work; absolute paths must lie under
    /work (ValueError otherwise).
    """
    given = PurePosixPath(option)
    if given.is_absolute():
        if not given.is_relative_to(CONTAINER_WORK):
            raise ValueError(
                f"--combo-output-root must be relative or under {CONTAINER_WORK}, got {option!r}"
            )
        relative = given.relative_to(CONTAINER_WORK)
    else:
        relative = given
    return cece_root / relative, CONTAINER_WORK / relative


def resolve_suite_path(option: str, settings: Settings) -> Path:
    """A set search path is prepended to relative --suite-config values, kept
    whole (nested and ../ paths work); absolute values are used as-is."""
    given = Path(option)
    if given.is_absolute():
        return given
    if settings.suite_config_search_path is not None:
        return settings.suite_config_search_path / given
    return given
