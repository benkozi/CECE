import shutil
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import pytest

from combos import build_config, enumerate_combos
from models.suite_config import SuiteConfig
from settings import Settings

# combo-test-runner/src/tests/conftest.py -> combo-test-runner/
_PROJECT_ROOT = Path(__file__).resolve().parents[2]

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
        default=str(_PROJECT_ROOT / "suite.yaml"),
        help="Suite YAML defining the enum sweep.",
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


def pytest_sessionstart(session: pytest.Session) -> None:
    config = session.config
    settings = Settings()
    suite = SuiteConfig.from_yaml(Path(config.getoption("--suite-config")))

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
    container_yamls: dict[str, PurePosixPath] = {}
    for combo in request.config._combos:  # type: ignore[attr-defined]
        combo_dir = combo_roots.host / combo.name
        combo_dir.mkdir(parents=True)
        container_dir = combo_roots.container / combo.name
        config = build_config(combo, output_directory=str(container_dir))
        config.to_yaml(combo_dir / f"{combo.name}.yaml")
        container_yamls[combo.name] = container_dir / f"{combo.name}.yaml"
    return container_yamls
