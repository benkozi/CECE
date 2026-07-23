"""Tests for repo scripts and the example tooling.

The example-tooling tests target examples/common.py: mapping sanity
and CLI validation run offline; the S3 HEAD checks touch the network and
document which mapped keys are known-missing (CAMS-TEMPO).
"""

import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "examples"))

from common import (  # noqa: E402
    CONFIG,
    Bucket,
    Example,
    build_parser,
    download,
    needs_fetch,
    resolve_examples,
)

# CAMS-TEMPO has no public source yet; these keys are aspirational by design.
KNOWN_MISSING_SUBSTRING = "CAMS-TEMPO"


def test_every_example_has_mapping_and_config():
    for example in Example:
        assert example in CONFIG.example_data
        assert CONFIG.config_path(example).is_file(), f"missing config for {example}"


def test_mapping_keys_well_formed():
    for files in CONFIG.example_data.values():
        for file in files:
            assert isinstance(file.bucket, Bucket)
            assert file.key and not file.key.startswith("/")
            assert file.filename.endswith(".nc")


def test_cli_requires_exactly_one_selection():
    parser = build_parser("test")
    with pytest.raises(SystemExit):
        resolve_examples(parser, parser.parse_args([]))
    with pytest.raises(SystemExit):
        resolve_examples(parser, parser.parse_args(["--all", "--example", "ex1"]))
    with pytest.raises(SystemExit):
        resolve_examples(parser, parser.parse_args(["--example", "nope"]))


def test_cli_selection_forms():
    parser = build_parser("test")
    assert resolve_examples(parser, parser.parse_args(["--example", "ex1,ex7"])) == [
        Example.EX1,
        Example.EX7,
    ]
    assert resolve_examples(parser, parser.parse_args(["--all"])) == list(Example)


def test_cache_guard_skips_only_non_empty(tmp_path):
    missing = tmp_path / "missing.nc"
    empty = tmp_path / "empty.nc"
    empty.touch()
    full = tmp_path / "full.nc"
    full.write_bytes(b"data")
    assert needs_fetch(missing)
    assert needs_fetch(empty)  # truncated files re-fetch
    assert not needs_fetch(full)


def test_download_skips_cached_files(tmp_path):
    file = CONFIG.example_data[Example.EX3][0]
    (tmp_path / file.filename).write_bytes(b"cached")
    (outcome,) = download((file,), tmp_path)
    assert outcome.ok and outcome.detail == "cached"


@pytest.mark.skipif(
    os.environ.get("CECE_EXAMPLES_SKIP_NETWORK_TESTS") == "1",
    reason="network tests disabled",
)
def test_mapped_keys_exist_in_s3_except_known_missing():
    """Every mapped key HEADs 200, except the documented CAMS gaps."""
    seen: set[str] = set()
    for files in CONFIG.example_data.values():
        for file in files:
            if file.url in seen:
                continue
            seen.add(file.url)
            request = urllib.request.Request(file.url, method="HEAD")
            try:
                with urllib.request.urlopen(request) as response:
                    status = response.status
            except urllib.error.HTTPError as exc:
                status = exc.code
            if KNOWN_MISSING_SUBSTRING in file.key:
                assert status == 404, (
                    f"{file.key}: expected known-missing, got {status}"
                )
            else:
                assert status == 200, f"{file.key}: expected available, got {status}"


def test_hemco_to_cece_cli_error():
    script = str(REPO_ROOT / "scripts" / "hemco_to_cece.py")

    # Test missing argument
    result = subprocess.run([sys.executable, script], capture_output=True, text=True)
    assert result.returncode != 0
    assert "the following arguments are required" in result.stderr


def test_visualize_stack_cli(tmp_path):
    script = str(REPO_ROOT / "scripts" / "visualize_stack.py")

    # Create a dummy config
    config = tmp_path / "test_config.yaml"
    config.write_text(
        "species:\n  NO2:\n    - operation: add\n      hierarchy: 1\n      field: f1\n"
    )

    # Test CLI execution
    result = subprocess.run(
        [sys.executable, script, str(config)], capture_output=True, text=True
    )
    assert result.returncode == 0
    assert "--- Stacking Plan for NO2 ---" in result.stdout
    assert "Saved stacking plan visualization" in result.stdout
