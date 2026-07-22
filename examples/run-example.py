#!/usr/bin/env python3
"""Download the data for and run one or more CECE examples.

Thin wrapper over examples/common.py (stdlib only). Executes the
driver binary directly — never docker — so it runs unchanged inside the dev
container or natively (e.g. on HPC; set CECE_EXAMPLES_DRIVER_PATH for
nonstandard build locations). Download failures do not abort the run phase:
the driver then fails honestly on any missing input. Exits non-zero if any
selected example failed.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    EXAMPLE_DATA,
    build_parser,
    configure_logging,
    download,
    resolve_examples,
    run_example,
)


def main() -> int:
    configure_logging()
    parser = build_parser("Download data for and run CECE examples.")
    args = parser.parse_args()
    examples = resolve_examples(parser, args)

    files = tuple(
        file for example in examples for file in EXAMPLE_DATA[example]
    )
    download(files, args.dst_dir)  # cache-aware; failures surface in the run

    failures: list[str] = []
    for example in examples:
        returncode = run_example(example)
        status = "PASS" if returncode == 0 else f"FAIL (exit {returncode})"
        print(f"{example.value}: {status}")
        if returncode != 0:
            failures.append(example.value)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
