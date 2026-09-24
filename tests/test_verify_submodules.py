"""Unit tests for scripts/verify_submodules.py."""

from __future__ import annotations

import ast
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

# Add scripts directory to sys.path
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from verify_submodules import (  # noqa: E402
    SubmoduleStatus,
    VerificationStatus,
    generate_step_summary,
    get_declared_submodules,
    log_verification_report,
    parse_branch_map_args,
    parse_submodule_status_lines,
    resolve_submodule_target_branch,
)


class TestVerifySubmodules(unittest.TestCase):
    """Test suite for submodule verification functions."""

    def test_parse_submodule_status_lines(self) -> None:
        raw_output = """
 9e2f6751c3e276fa9c50b8443f4601c846bc3efd extern/helm (remotes/benkozi/HEAD-6-g9e2f675)
+d21b5278508a5aca4ed3ea59403cc03538b40c7d extern/helm/libs/amio (v0.1.0-53-gd21b527)
-1234567890abcdef1234567890abcdef12345678 uninitialized/submod
"""
        entries = parse_submodule_status_lines(raw_output)
        self.assertEqual(len(entries), 3)

        self.assertEqual(
            entries[0], (" ", "9e2f6751c3e276fa9c50b8443f4601c846bc3efd", "extern/helm")
        )
        self.assertEqual(
            entries[1],
            ("+", "d21b5278508a5aca4ed3ea59403cc03538b40c7d", "extern/helm/libs/amio"),
        )
        self.assertEqual(
            entries[2],
            ("-", "1234567890abcdef1234567890abcdef12345678", "uninitialized/submod"),
        )

    def test_parse_branch_map_args(self) -> None:
        # Empty or None
        self.assertEqual(parse_branch_map_args(None), {})
        self.assertEqual(parse_branch_map_args([]), {})

        # Valid mappings
        mapped = parse_branch_map_args(["extern/helm=develop", "libs/amio=main"])
        self.assertEqual(mapped, {"extern/helm": "develop", "libs/amio": "main"})

        # Invalid format raises exception
        with self.assertRaises(Exception) as ctx:
            parse_branch_map_args(["invalid_format"])
        self.assertIn("Invalid branch map format", str(ctx.exception))

    def test_resolve_submodule_target_branch_map_override(self) -> None:
        branch_map = {"extern/helm": "feature/custom"}
        resolved = resolve_submodule_target_branch(
            repo_root=Path("/fake/repo"),
            sub_path="extern/helm",
            remote_url="https://github.com/example/helm.git",
            parent_target_branch="develop",
            branch_map=branch_map,
        )
        self.assertEqual(resolved, "feature/custom")

    def test_resolve_submodule_target_branch_remote_match(self) -> None:
        with patch("verify_submodules.run_git_cmd") as mock_git:
            # Mock ls-remote finding develop
            mock_git.return_value = (0, "c4d2b5ab refs/heads/develop", "")
            resolved = resolve_submodule_target_branch(
                repo_root=Path("/fake/repo"),
                sub_path="extern/helm",
                remote_url="https://github.com/example/helm.git",
                parent_target_branch="develop",
                branch_map={},
            )
            self.assertEqual(resolved, "develop")

    def test_log_verification_report_all_ok(self) -> None:
        statuses = [
            SubmoduleStatus(
                path="extern/helm",
                current_sha="c4d2b5ab1234",
                expected_sha="c4d2b5ab1234",
                target_branch="develop",
                remote_url="https://github.com/example/helm.git",
                status="OK",
                detail="Pointers match",
            ),
            SubmoduleStatus(
                path="extern/helm/libs/amio",
                current_sha="d21b52785678",
                expected_sha="d21b52785678",
                target_branch="develop",
                remote_url="https://github.com/example/amio.git",
                status="OK",
                detail="Pointers match",
                is_nested=True,
            ),
        ]

        all_ok = log_verification_report(statuses, target_branch="develop")
        self.assertTrue(all_ok)

    def test_log_verification_report_mismatch(self) -> None:
        statuses = [
            SubmoduleStatus(
                path="extern/helm",
                current_sha="9e2f67510000",
                expected_sha="c4d2b5ab0000",
                target_branch="develop",
                remote_url="https://github.com/example/helm.git",
                status="OUT_OF_SYNC",
                detail="Behind by 1 commit",
            )
        ]

        all_ok = log_verification_report(statuses, target_branch="develop")
        self.assertFalse(all_ok)

    def test_verification_status_strenum(self) -> None:
        """Test that VerificationStatus is a StrEnum and behaves correctly with SubmoduleStatus."""
        # Enum values
        self.assertEqual(VerificationStatus.PENDING, "PENDING")
        self.assertEqual(VerificationStatus.OK, "OK")
        self.assertEqual(VerificationStatus.OUT_OF_SYNC, "OUT_OF_SYNC")
        self.assertEqual(VerificationStatus.UNINITIALIZED, "UNINITIALIZED")
        self.assertEqual(VerificationStatus.ERROR, "ERROR")

        # Subclass of str
        self.assertIsInstance(VerificationStatus.OK, str)

        # Unique enum members (verified by @unique)
        self.assertEqual(len(VerificationStatus), 5)
        self.assertEqual(len({s.value for s in VerificationStatus}), 5)

        # Initialized with enum
        s1 = SubmoduleStatus(
            path="sub1",
            current_sha="1111",
            target_branch="develop",
            remote_url="http://example.com",
            status=VerificationStatus.OK,
        )
        self.assertIs(s1.status, VerificationStatus.OK)
        self.assertEqual(s1.status, "OK")

        # Coerced from string
        s2 = SubmoduleStatus(
            path="sub2",
            current_sha="2222",
            target_branch="develop",
            remote_url="http://example.com",
            status="OUT_OF_SYNC",
        )
        self.assertIs(s2.status, VerificationStatus.OUT_OF_SYNC)
        self.assertEqual(s2.status, "OUT_OF_SYNC")

    def test_generate_step_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            summary_file = Path(tmp_dir) / "step_summary.md"
            statuses = [
                SubmoduleStatus(
                    path="extern/helm",
                    current_sha="9e2f6751",
                    expected_sha="c4d2b5ab",
                    target_branch="develop",
                    remote_url="https://github.com/example/helm.git",
                    status="OUT_OF_SYNC",
                    detail="Behind by 1 commit",
                )
            ]

            generate_step_summary(statuses, "develop", summary_file)
            self.assertTrue(summary_file.exists())
            content = summary_file.read_text(encoding="utf-8")
            self.assertIn("## Submodule Verification Report", content)
            self.assertIn("`extern/helm`", content)
            self.assertIn("OUT_OF_SYNC", content)
            self.assertIn("[!WARNING]", content)

    def test_no_raw_print_statements(self) -> None:
        """Audit scripts/verify_submodules.py AST to enforce zero print() calls."""
        script_path = SCRIPTS_DIR / "verify_submodules.py"
        source = script_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(script_path))

        print_calls: list[int] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id == "print":
                    print_calls.append(node.lineno)

        self.assertFalse(
            print_calls,
            f"Raw print() found on line(s): {print_calls}. Use logging instead.",
        )

    def test_no_subprocess_run(self) -> None:
        """Audit scripts/verify_submodules.py AST to enforce zero subprocess.run() calls."""
        script_path = SCRIPTS_DIR / "verify_submodules.py"
        source = script_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(script_path))

        run_calls: list[int] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute) and node.func.attr == "run":
                    if (
                        isinstance(node.func.value, ast.Name)
                        and node.func.value.id == "subprocess"
                    ):
                        run_calls.append(node.lineno)

        self.assertFalse(
            run_calls,
            f"subprocess.run() found on line(s): {run_calls}. Use subprocess.check_output instead.",
        )

    def test_no_debug_logging(self) -> None:
        """Audit scripts/verify_submodules.py AST to enforce zero debug logging calls."""
        script_path = SCRIPTS_DIR / "verify_submodules.py"
        source = script_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(script_path))

        debug_calls: list[int] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if (
                    isinstance(node.func, ast.Attribute)
                    and node.func.attr == "debug"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id in ("logger", "logging")
                ):
                    debug_calls.append(node.lineno)

        self.assertFalse(
            debug_calls,
            f"debug logging found on line(s): {debug_calls}. Logging must be INFO minimum.",
        )

    def test_cli_help(self) -> None:
        """Test CLI --help exits with 0 using subprocess.check_output."""
        script_path = SCRIPTS_DIR / "verify_submodules.py"
        stdout = subprocess.check_output(
            [sys.executable, str(script_path), "--help"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        self.assertIn("Verify that Git submodules", stdout)
        self.assertIn("--target-branch", stdout)
        self.assertIn("--allow-ancestor", stdout)

    def test_get_declared_submodules_live_repo(self) -> None:
        """Verify get_declared_submodules finds both direct and nested submodules in CECE."""
        repo_root = SCRIPTS_DIR.parent
        declared = get_declared_submodules(repo_root)
        self.assertIn("extern/helm", declared)
        self.assertIn("extern/helm/libs/amio", declared)

    def test_get_declared_submodules_empty_when_no_gitmodules(self) -> None:
        """Verify get_declared_submodules returns empty set if .gitmodules is absent."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            declared = get_declared_submodules(Path(tmp_dir))
            self.assertEqual(declared, set())


if __name__ == "__main__":
    unittest.main()
