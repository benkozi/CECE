"""Docker invocation of cece_standalone_driver for a single combination."""

from __future__ import annotations

import subprocess
from pathlib import Path, PurePosixPath

from settings import Settings


def build_command(
    settings: Settings,
    container_yaml: PurePosixPath,
    output_mount: tuple[Path, PurePosixPath] | None = None,
) -> list[str]:
    command = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{settings.root}:/work",  # bind mount: <host path>:<container path>
    ]
    if output_mount is not None:
        # Output root outside the /work mount (the pytest tmp default) needs
        # its own bind mount so artifacts survive --rm.
        host_root, container_root = output_mount
        command += ["-v", f"{host_root}:{container_root}"]
    command += [
        "-w",
        "/work",
        "-e",
        "OMPI_ALLOW_RUN_AS_ROOT=1",
        "-e",
        "OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1",
        settings.docker_image,
        settings.driver_path,
        str(container_yaml),
    ]
    return command


def run_driver(
    settings: Settings,
    container_yaml: PurePosixPath,
    out_path: Path,
    output_mount: tuple[Path, PurePosixPath] | None = None,
) -> None:
    """Run one driver invocation in a fresh container.

    Combined stdout/stderr is written to out_path whether the run passes or
    fails; a nonzero exit re-raises CalledProcessError to fail the test.
    """
    command = build_command(settings, container_yaml, output_mount=output_mount)
    try:
        output = subprocess.check_output(command, stderr=subprocess.STDOUT, timeout=settings.run_timeout_s)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        out_path.write_bytes(exc.output or b"")
        raise
    out_path.write_bytes(output)
