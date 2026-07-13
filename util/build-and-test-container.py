#!/usr/bin/env python3
"""Build CECE and run its C++ tests in the dev container.

The combo-test-runner suite is deliberately out of scope: run it separately
on the host (uv run pytest in combo-test-runner/), where it orchestrates its
own per-combo containers.

Stdlib-only (argparse/subprocess/shutil): runs with any python3. The host repo
root is derived from this file's location, never the cwd. setup.sh remains the
interactive dev-environment entry point; this script is the C++ build/test
loop, nothing more.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

# util/build-and-test-container.py -> CECE repo root is one level up.
REPO_ROOT = Path(__file__).resolve().parent.parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--clean",
        action="store_true",
        help="remove the build/ and cmake-build-debug/ directories before anything else",
    )
    parser.add_argument("--no-build", action="store_true", help="skip the build phase")
    parser.add_argument("--no-test", action="store_true", help="skip the test phase")
    parser.add_argument(
        "--test-filter",
        default=None,
        metavar="STRING",
        help="run only matching C++ tests (--gtest_filter=*STRING*, substring match)",
    )
    parser.add_argument(
        "--mount",
        default="/work",
        help="container-side path the host repo root is mounted at (default: %(default)s)",
    )
    parser.add_argument(
        "--image",
        default="cece/cece-dev",
        help="container image; the default matches setup.sh (default: %(default)s)",
    )
    return parser.parse_args()


def run_in_container(image: str, mount: str, command: str) -> None:
    """One docker run --rm per step: spun up and removed per execution."""
    subprocess.check_call(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{REPO_ROOT}:{mount}",
            "-w",
            mount,
            "-e",
            "OMPI_ALLOW_RUN_AS_ROOT=1",
            "-e",
            "OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1",
            image,
            "/bin/bash",
            "-c",
            command,
        ]
    )


def clean() -> None:
    for name in ("build", "cmake-build-debug"):
        target = REPO_ROOT / name
        if target.exists():
            print(f"[build-and-test] removing {target}")
            shutil.rmtree(target)


def build(image: str, mount: str) -> None:
    configure = f"[ -f {mount}/build/CMakeCache.txt ] || cmake -S {mount} -B {mount}/build"
    targets = "cece_standalone_driver test_standalone_writer_attributes"
    run_in_container(image, mount, f"{configure} && cmake --build {mount}/build -j --target {targets}")


def test(image: str, mount: str, test_filter: str | None) -> None:
    # C++ tests run in the container, where the toolchain and netcdf-c live.
    # The combo-test-runner suite is out of scope: run it separately on the host.
    gtest_command = f"{mount}/build/test_standalone_writer_attributes"
    if test_filter:
        gtest_command += f" --gtest_filter='*{test_filter}*'"  # zero matches exit 0
    run_in_container(image, mount, gtest_command)


def main() -> int:
    args = parse_args()
    if args.clean:
        clean()
    if not args.no_build:
        build(args.image, args.mount)
    if not args.no_test:
        test(args.image, args.mount, args.test_filter)
    print("[build-and-test] done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
