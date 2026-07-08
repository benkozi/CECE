import shutil
import subprocess
import time
from pathlib import Path, PurePosixPath

import pytest
from pydantic import BaseModel, ConfigDict

from analysis import RunContext, concatenate_stats_csvs
from combos import Combo, build_config, enumerate_combos
from logs import configure_logging, get_logger
from models.cece_config import CeceConfig
from models.suite_config import Analysis, Assertions, RunManifest, SuiteConfig
from ulid import ULID
from resolution import resolve_output_roots, resolve_suite_path
from runner import DriverRunResult, run_driver
from settings import Settings

logger = get_logger("conftest")

# combo-test-runner/src/tests/conftest.py -> combo-test-runner/src/tests/
_TESTS_ROOT = Path(__file__).resolve().parent
_DEFAULT_SUITE = _TESTS_ROOT / "config" / "suite" / "simple-maccity-suite.yaml"

# Container-side mount point for the default (pytest tmp) output root, which
# lives outside the /work mount.
_CONTAINER_TMP_ROOT = PurePosixPath("/combo_runs")


class ComboRoots(BaseModel):
    model_config = ConfigDict(frozen=True)

    host: Path
    container: PurePosixPath
    needs_mount: bool  # True when the host root is outside the /work mount

    @property
    def output_mount(self) -> tuple[Path, PurePosixPath] | None:
        return (self.host, self.container) if self.needs_mount else None


class GeneratedCombo(BaseModel):
    """A combination's generated driver config and where it lives."""

    model_config = ConfigDict(frozen=True)

    host_dir: Path
    container_yaml: PurePosixPath
    config: CeceConfig


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


def pytest_sessionstart(session: pytest.Session) -> None:
    config = session.config
    settings = Settings()
    configure_logging(settings.log_level)
    suite_path = resolve_suite_path(config.getoption("--suite-config"), settings)
    try:
        suite = SuiteConfig.from_yaml(suite_path, config_search_path=settings.config_search_path)
    except FileNotFoundError as exc:
        raise pytest.UsageError(str(exc)) from exc

    # One ULID per test run, generated at runtime only — never configuration.
    run_id = str(ULID())
    logger.info("starting run %s (suite=%s, path=%s)", run_id, suite.name, suite_path)
    config._combo_run_id = run_id  # type: ignore[attr-defined]

    # An explicit output root is resolved and guarded here, before anything
    # runs. The default (pytest tmp) root is created lazily in combo_roots —
    # it is freshly created each session and can never pre-exist.
    option = config.getoption("--combo-output-root")
    if option is None:
        roots = None
    else:
        try:
            host_root, container_root = resolve_output_roots(option, settings.root)
        except ValueError as exc:
            raise pytest.UsageError(str(exc)) from exc
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


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Concatenate every per-combo stats CSV that exists into the suite-level
    descriptive_stats.csv at the output root."""
    config = session.config
    suite: SuiteConfig | None = getattr(config, "_combo_suite", None)
    roots: ComboRoots | None = getattr(config, "_combo_roots_realized", None)
    if suite is None or roots is None or not suite.analysis.compute_descriptive_stats:
        return
    combo_csvs = sorted(roots.host.glob("*/*-stats.csv"))
    if not combo_csvs:
        return
    concatenate_stats_csvs(combo_csvs, roots.host / "descriptive_stats.csv")


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if "driver_run" in metafunc.fixturenames:
        combos = metafunc.config._combos  # type: ignore[attr-defined]
        metafunc.parametrize("driver_run", combos, ids=[combo.name for combo in combos], indirect=True)


@pytest.fixture(scope="session")
def settings(request: pytest.FixtureRequest) -> Settings:
    return request.config._combo_settings  # type: ignore[attr-defined]


@pytest.fixture(scope="session")
def suite_assertions(request: pytest.FixtureRequest) -> Assertions:
    return request.config._combo_suite.assertions  # type: ignore[attr-defined]


@pytest.fixture(scope="session")
def suite_analysis(request: pytest.FixtureRequest) -> Analysis:
    return request.config._combo_suite.analysis  # type: ignore[attr-defined]


@pytest.fixture(scope="session")
def run_context(request: pytest.FixtureRequest) -> RunContext:
    return RunContext(
        run_id=request.config._combo_run_id,  # type: ignore[attr-defined]
        suite=request.config._combo_suite.name,  # type: ignore[attr-defined]
    )


@pytest.fixture(scope="session")
def dask_client(settings: Settings):
    """Session distributed client for the analysis computations. Requested
    lazily (request.getfixturevalue) so disabled-analysis runs never pay
    cluster startup. dask_nworkers unset -> all available cores."""
    from dask.distributed import Client, LocalCluster

    cluster_kwargs: dict[str, object] = {"dashboard_address": None}
    if settings.dask_nworkers is not None:
        cluster_kwargs["n_workers"] = settings.dask_nworkers
    cluster = LocalCluster(**cluster_kwargs)  # type: ignore[arg-type]
    client = Client(cluster)
    logger.info("started dask client with %s worker(s)", len(cluster.workers))
    yield client
    client.close()
    cluster.close()


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
    # Stash the realized roots for pytest_sessionfinish (hooks cannot request
    # fixtures; the tmp-default root only exists once this fixture has run).
    request.config._combo_roots_realized = roots  # type: ignore[attr-defined]

    # Write the run manifest as soon as the root is realized, so even a run
    # that dies mid-way leaves a record of what ran.
    roots.host.mkdir(parents=True, exist_ok=True)
    manifest = RunManifest(
        run_id=request.config._combo_run_id,  # type: ignore[attr-defined]
        suite=request.config._combo_suite,  # type: ignore[attr-defined]
    )
    manifest.to_yaml(roots.host / "run.yaml")
    return roots


@pytest.fixture(scope="session")
def generated_combos(request: pytest.FixtureRequest, combo_roots: ComboRoots) -> dict[str, GeneratedCombo]:
    """Generate every combo's driver config up front; map combo name to its
    generated config and paths."""
    suite = request.config._combo_suite  # type: ignore[attr-defined]
    generated: dict[str, GeneratedCombo] = {}
    for combo in request.config._combos:  # type: ignore[attr-defined]
        combo_dir = combo_roots.host / combo.name
        combo_dir.mkdir(parents=True)
        container_dir = combo_roots.container / combo.name
        config = build_config(combo, output_directory=str(container_dir), config_path=suite.config_path)
        config.to_yaml(combo_dir / f"{combo.name}.yaml")
        generated[combo.name] = GeneratedCombo(
            host_dir=combo_dir,
            container_yaml=container_dir / f"{combo.name}.yaml",
            config=config,
        )
    return generated


@pytest.fixture(scope="session")
def driver_run(
    request: pytest.FixtureRequest,
    combo_roots: ComboRoots,
    generated_combos: dict[str, GeneratedCombo],
    settings: Settings,
    run_timeout_s: int,
) -> DriverRunResult:
    """Run the driver once per combination (session-scoped, combo-parameterized)
    and capture the outcome without raising."""
    combo: Combo = request.param
    generated = generated_combos[combo.name]
    out_path = generated.host_dir / f"{combo.name}.out"

    logger.info("running combo %s (timeout=%ss)", combo.name, run_timeout_s)
    start = time.monotonic()
    error: Exception | None = None
    try:
        run_driver(
            settings,
            container_yaml=generated.container_yaml,
            out_path=out_path,
            timeout_s=run_timeout_s,
            output_mount=combo_roots.output_mount,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
        error = exc
    duration = time.monotonic() - start
    if error is None:
        logger.info("combo %s completed in %.1fs", combo.name, duration)
    else:
        logger.error("combo %s FAILED after %.1fs: %s", combo.name, duration, type(error).__name__)

    return DriverRunResult(
        combo=combo,
        combo_dir=generated.host_dir,
        out_path=out_path,
        config=generated.config,
        error=error,
    )
