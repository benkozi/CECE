"""--dry-run: the full session minus driver execution, exercised through a
real pytest subprocess against the integration suite — no docker, no mocking.
Session artifacts (run.yaml, combos.csv, every generated config) and the
all-skipped test-report.csv must exist; nothing the driver would produce may.
"""

import os
import subprocess
import sys
from pathlib import Path

import pandas as pd

_RUNNER_ROOT = Path(__file__).resolve().parents[3]  # combo-test-runner/


def test_dry_run_generates_everything_but_never_executes(tmp_path: Path) -> None:
    env = os.environ | {"CECE_ROOT": str(tmp_path)}
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "src/tests/test_driver_combos.py",
            "--dry-run",
            "--combo-output-root=combo_runs",
            "-q",
            "-p",
            "no:cacheprovider",
        ],
        cwd=_RUNNER_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    root = tmp_path / "combo_runs"
    assert (root / "run.yaml").is_file()

    combos = pd.read_csv(root / "combos.csv")
    combo_ids = set(combos["combo_id"])
    assert len(combo_ids) == 3  # simple-maccity: mapalgo x 3
    for combo_id in combo_ids:
        assert (root / combo_id / f"{combo_id}.yaml").is_file()

    # The driver never ran: no captured output, no NetCDF, anywhere.
    assert not list(root.rglob("*.out"))
    assert not list(root.rglob("*.nc"))

    report = pd.read_csv(root / "test-report.csv")
    assert list(report.columns) == ["pytest_name", "combo_id", "combo", "result"]
    assert set(report["result"]) == {"skipped"}
    assert set(report["combo_id"]) == combo_ids
    # Six combo-parameterized tests per combination (execution, file count,
    # filenames, species attributes for co, baseline comparison, stats).
    assert len(report) == 6 * 3
