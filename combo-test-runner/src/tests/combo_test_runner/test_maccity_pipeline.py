"""The full maccity-suite flow — enumeration, config generation, driver
invocation, assertions — with the process call mocked. No docker."""

from pathlib import Path, PurePosixPath

from pytest_mock import MockerFixture

from assertions import assert_nc_file_count, assert_nc_filenames
from combos import build_config, enumerate_combos
from models.cece_config import CeceConfig
from models.suite_config import SuiteConfig
from runner import run_driver
from settings import Settings


def test_maccity_pipeline_runs_all_combos_mocked(
    mocker: MockerFixture, tmp_path: Path, suite_path: Path
) -> None:
    check_output = mocker.patch(
        "runner.subprocess.check_output",
        return_value=b"INFO: CECE Finalize completed successfully\n",
    )
    settings = Settings(root=tmp_path)
    suite = SuiteConfig.from_yaml(suite_path)
    combos = enumerate_combos(suite.sweep)
    assert [combo.name for combo in combos] == ["map-bilinear", "map-consd", "map-passthrough"]

    container_root = PurePosixPath("/combo_runs")
    effective_timeout = min(suite.timeout_s, settings.run_timeout_s)

    for combo in combos:
        combo_dir = tmp_path / combo.name
        combo_dir.mkdir()
        container_dir = container_root / combo.name

        config = build_config(combo, output_directory=str(container_dir), config_path=suite.config_path)
        yaml_path = combo_dir / f"{combo.name}.yaml"
        config.to_yaml(yaml_path)

        # The generated yaml round-trips through the model and carries the
        # combo's swept value and output directory.
        reloaded = CeceConfig.from_yaml(yaml_path)
        assert reloaded.cece_data.streams[0].mapalgo.value == combo.name.removeprefix("map-")
        assert reloaded.output is not None
        assert reloaded.output.directory == str(container_dir)

        out_path = combo_dir / f"{combo.name}.out"
        run_driver(
            settings,
            container_yaml=container_dir / f"{combo.name}.yaml",
            out_path=out_path,
            timeout_s=effective_timeout,
            output_mount=(tmp_path, container_root),
        )
        assert out_path.read_bytes() == b"INFO: CECE Finalize completed successfully\n"

        # Fabricate the file a *correct* driver would produce (first write at
        # hour 1), then run the suite's assertions in derived mode.
        (combo_dir / "cece_20100101_010000.nc").touch()
        assert_nc_file_count(combo_dir, config, suite.assertions.expected_nc_file_count)
        assert suite.assertions.validate_filenames
        assert_nc_filenames(combo_dir, config)

    assert check_output.call_count == 3
    for call in check_output.call_args_list:
        command = call.args[0]
        assert command[:3] == ["docker", "run", "--rm"]
        assert f"{tmp_path}:/combo_runs" in command
        assert call.kwargs["timeout"] == effective_timeout
