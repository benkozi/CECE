#!/usr/bin/env python3
"""Build CECE and run its C++ tests in the dev container."""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

# scripts/build-and-test-container.py -> CECE repo root is one level up.
REPO_ROOT = Path(__file__).resolve().parent.parent

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("build-and-test-container")


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
        "--target",
        action="append",
        default=None,
        metavar="NAME",
        help=(
            "build only this CMake target (repeatable, e.g. "
            "--target cece_standalone_driver skips the whole test stack); "
            "default: the 'all' target"
        ),
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=os.cpu_count(),
        metavar="N",
        help=(
            "parallel build jobs; bounded by default — an unbounded -j "
            "thrashes memory on small machines (default: %(default)s)"
        ),
    )
    parser.add_argument(
        "--test-filter",
        default=None,
        metavar="STRING",
        help="run only matching CECE tests (ctest -R STRING); default: the full registered suite",
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
            logger.info("removing %s", target)
            shutil.rmtree(target)


def build(image: str, mount: str, targets: list[str] | None, jobs: int | None) -> None:
    logger.info(
        "build phase: image=%s mount=%s targets=%s jobs=%s",
        image,
        mount,
        targets or ["<all>"],
        jobs,
    )
    configure = (
        f"[ -f {mount}/build/CMakeCache.txt ] || cmake -S {mount} -B {mount}/build"
    )
    # Default "all" target: the driver plus every registered test executable.
    # --target subsets that (e.g. cece_standalone_driver alone never compiles
    # the googletest/rapidcheck test stack).
    build_command = f"cmake --build {mount}/build -j {jobs}"
    for target in targets or []:
        build_command += f" --target {target}"
    run_in_container(image, mount, f"{configure} && {build_command}")


def test(image: str, mount: str, test_filter: str | None) -> None:
    logger.info("test phase: filter=%s", test_filter or "<none: full suite>")
    ctest_command = f"ctest --test-dir {mount}/build --output-on-failure"
    if test_filter:
        ctest_command += f" -R '{test_filter}'"
    run_in_container(image, mount, ctest_command)


def main() -> int:
    args = parse_args()
    if args.clean:
        clean()
    if not args.no_build:
        build(args.image, args.mount, args.target, args.jobs)
    if not args.no_test:
        test(args.image, args.mount, args.test_filter)
    logger.info("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
