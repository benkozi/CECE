import shutil
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import pytest

from combos import build_config, enumerate_combos
from models.suite_config import SuiteConfig
from settings import Settings

# combo-test-runner/src/tests/conftest.py -> combo-test-runner/src/tests/
_TESTS_ROOT = Path(__file__).resolve().parent
_DEFAULT_SUITE = _TESTS_ROOT / "config" / "suite" / "simple-maccity-suite.yaml"

_CONTAINER_WORK = PurePosixPath("/work")
# Container-side mount point for the default (pytest tmp) output root, which
# lives outside the /work mount.
_CONTAINER_TMP_ROOT = PurePosixPath("/combo_runs")


@dataclass(frozen=True)
class ComboRoots:
    host: Path
    container: PurePosixPath
    needs_mount: bool  # True when the host root is outside the /work mount

    @property
    def output_mount(self) -> tuple[Path, PurePosixPath] | None:
        return (self.host, self.container) if self.needs_mount else None


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("combo", "combinatorial driver test runner")
    group.addoption(
        "--suite-config",
        default=str(_DEFAULT_SUITE),
        help=(
            "Suite YAML defining the base config and enum sweep. Relative paths "
            "resolve under CECE_SUITE_CONFIG_SEARCH_PATH when set."
        ),
    )
    group.addoption(
        "--combo-output-root",
        default=None,
        help=(
            "Root artifact directory; relative paths resolve against /work in the "
            "container. Default: a pytest-managed temporary directory."
        ),
    )
    group.addoption(
        "--combo-clean-root",
        action="store_true",
        help="Remove an existing output root before running (default: existing root is an error).",
    )


def _resolve_output_roots(option: str, cece_root: Path) -> tuple[Path, PurePosixPath]:
    """Map an explicit --combo-output-root to (host path, container path)."""
    given = PurePosixPath(option)
    if given.is_absolute():
        if not given.is_relative_to(_CONTAINER_WORK):
            raise pytest.UsageError(
                f"--combo-output-root must be relative or under {_CONTAINER_WORK}, got {option!r}"
            )
        relative = given.relative_to(_CONTAINER_WORK)
    else:
        relative = given
    return cece_root / relative, _CONTAINER_WORK / relative


def _resolve_suite_path(option: str, settings: Settings) -> Path:
    """A set search path is prepended to relative --suite-config values, kept
    whole (nested and ../ paths work); absolute values are used as-is."""
    given = Path(option)
    if given.is_absolute():
        return given
    if settings.suite_config_search_path is not None:
        return settings.suite_config_search_path / given
    return given


def pytest_sessionstart(session: pytest.Session) -> None:
    config = session.config
    settings = Settings()
    suite_path = _resolve_suite_path(config.getoption("--suite-config"), settings)
    try:
        suite = SuiteConfig.from_yaml(suite_path, config_search_path=settings.config_search_path)
    except FileNotFoundError as exc:
        raise pytest.UsageError(str(exc)) from exc

    # An explicit output root is resolved and guarded here, before anything
    # runs. The default (pytest tmp) root is created lazily in combo_roots —
    # it is freshly created each session and can never pre-exist.
    option = config.getoption("--combo-output-root")
    if option is None:
        roots = None
    else:
        host_root, container_root = _resolve_output_roots(option, settings.root)
        if host_root.exists():
            if config.getoption("--combo-clean-root"):
                shutil.rmtree(host_root)
            else:
                raise pytest.UsageError(
                    f"output root {host_root} already exists; move it aside or pass --combo-clean-root"
                )
        roots = ComboRoots(host=host_root, container=container_root, needs_mount=False)

    config._combo_settings = settings  # type: ignore[attr-defined]
    config._combo_suite = suite  # type: ignore[attr-defined]
    config._combo_roots = roots  # type: ignore[attr-defined]
    config._combos = enumerate_combos(suite.sweep)  # type: ignore[attr-defined]


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if "combo" in metafunc.fixturenames:
        combos = metafunc.config._combos  # type: ignore[attr-defined]
        metafunc.parametrize("combo", combos, ids=[combo.name for combo in combos])


@pytest.fixture(scope="session")
def settings(request: pytest.FixtureRequest) -> Settings:
    return request.config._combo_settings  # type: ignore[attr-defined]


@pytest.fixture(scope="session")
def run_timeout_s(request: pytest.FixtureRequest, settings: Settings) -> int:
    """Effective per-combination timeout: the suite value, capped by the
    run_timeout_s setting when that is smaller."""
    suite = request.config._combo_suite  # type: ignore[attr-defined]
    return min(suite.timeout_s, settings.run_timeout_s)


@pytest.fixture(scope="session")
def combo_roots(
    request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory
) -> ComboRoots:
    roots = request.config._combo_roots  # type: ignore[attr-defined]
    if roots is None:
        # Default: all test-generated data goes to a pytest temp directory,
        # bind-mounted into the container at a fixed path.
        roots = ComboRoots(
            host=tmp_path_factory.mktemp("combo_runs"),
            container=_CONTAINER_TMP_ROOT,
            needs_mount=True,
        )
    return roots


@pytest.fixture(scope="session")
def generated_yamls(request: pytest.FixtureRequest, combo_roots: ComboRoots) -> dict[str, PurePosixPath]:
    """Generate every combo's driver config up front; map combo name to the
    config's container-side path."""
    suite = request.config._combo_suite  # type: ignore[attr-defined]
    container_yamls: dict[str, PurePosixPath] = {}
    for combo in request.config._combos:  # type: ignore[attr-defined]
        combo_dir = combo_roots.host / combo.name
        combo_dir.mkdir(parents=True)
        container_dir = combo_roots.container / combo.name
        config = build_config(combo, output_directory=str(container_dir), config_path=suite.config_path)
        config.to_yaml(combo_dir / f"{combo.name}.yaml")
        container_yamls[combo.name] = container_dir / f"{combo.name}.yaml"
    return container_yamls
