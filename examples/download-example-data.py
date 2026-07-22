#!/usr/bin/env python3
"""Download the input data for one or more CECE examples.

Thin wrapper over examples/common.py (stdlib only). Exits non-zero
if any fetch failed — every file is attempted regardless.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    CONFIG,
    build_parser,
    configure_logging,
    download,
    logger,
    resolve_examples,
)


def main() -> int:
    configure_logging()
    parser = build_parser("Download the input data for CECE examples.")
    args = parser.parse_args()
    examples = resolve_examples(parser, args)
    files = tuple(
        file for example in examples for file in CONFIG.example_data[example]
    )
    outcomes = download(files, args.dst_dir)
    failed = [outcome for outcome in outcomes if not outcome.ok]
    for outcome in failed:
        logger.error("FAILED: %s (%s)", outcome.file.url, outcome.detail)
    if not failed:
        logger.info("all %s file(s) present", len(outcomes))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
