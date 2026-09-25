#!/usr/bin/env python3
"""Verify that Git submodules (including nested submodules) point to expected commits.

Recursively discovers all Git submodules in the repository, determines their target
upstream branches, queries the remote HEAD commits via `git ls-remote`, and verifies
that the local committed submodule pointers match upstream.

Adheres strictly to project guidelines: zero raw print() statements; uses standard
library logging exclusively.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, field
from enum import StrEnum, unique
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
from typing import Sequence


@unique
class VerificationStatus(StrEnum):
    """Enumeration of possible submodule verification states."""

    PENDING = "PENDING"
    OK = "OK"
    OUT_OF_SYNC = "OUT_OF_SYNC"
    UNINITIALIZED = "UNINITIALIZED"
    ERROR = "ERROR"


# Convenience alias
SubmoduleVerificationStatus = VerificationStatus

# Initialize module logger
logger = logging.getLogger("verify_submodules")


@dataclass(frozen=True)
class UpstreamTargetBranchConfig:
    """Source-of-truth mapping of expected target branches for upstream modules (hosted at bbakernoaa)."""

    branch_maps: dict[str, dict[str, str]] = field(
        default_factory=lambda: {
            "extern/helm": {"develop": "develop", "main": "main"},
            "extern/helm/libs/amio": {"develop": "develop", "main": "main"},
        }
    )


@dataclass
class SubmoduleStatus:
    """Represents the verification status of a single submodule."""

    path: str
    current_sha: str
    target_branch: str
    remote_url: str
    expected_sha: str | None = None
    status: VerificationStatus = VerificationStatus.PENDING
    detail: str = ""
    is_nested: bool = False

    def __post_init__(self) -> None:
        if isinstance(self.status, str) and not isinstance(
            self.status, VerificationStatus
        ):
            self.status = VerificationStatus(self.status)


def run_git_cmd(args: list[str], cwd: Path | None = None) -> tuple[int, str, str]:
    """Execute a git command using subprocess.check_output and return (exit_code, stdout, stderr)."""
    try:
        stdout = subprocess.check_output(
            ["git", *args],
            cwd=cwd,
            text=True,
            stderr=subprocess.PIPE,
        )
        return 0, stdout.strip(), ""
    except subprocess.CalledProcessError as exc:
        return exc.returncode, (exc.output or "").strip(), (exc.stderr or "").strip()


def get_repo_root(hint: Path | None = None) -> Path:
    """Find and return the root of the Git repository."""
    start_dir = hint or Path.cwd()
    code, out, err = run_git_cmd(["rev-parse", "--show-toplevel"], cwd=start_dir)
    if code != 0 or not out:
        logger.error(
            "Failed to determine Git repository root from %s: %s", start_dir, err
        )
        raise RuntimeError(f"Not inside a Git repository: {err}")
    return Path(out).resolve()


def parse_submodule_status_lines(status_output: str) -> list[tuple[str, str, str]]:
    """Parse output of `git submodule status --recursive`.

    Format per line: [ -+U]<sha1> <path> [(<describe>)]
    Returns list of (status_char, sha, relative_path).
    """
    entries: list[tuple[str, str, str]] = []
    for line in status_output.splitlines():
        trimmed = line.strip()
        if not trimmed:
            continue
        # Status character may be at index 0 of raw line or preceding sha
        status_char = " "
        if line[0] in (" ", "+", "-", "U"):
            status_char = line[0]

        parts = trimmed.split()
        if len(parts) >= 2:
            raw_sha = parts[0].lstrip("+-U ")
            sub_path = parts[1]
            entries.append((status_char, raw_sha, sub_path))
    return entries


def get_submodule_remote_url(repo_root: Path, sub_path: str) -> str:
    """Retrieve the remote URL for a given submodule path."""
    sub_dir = repo_root / sub_path
    if sub_dir.is_dir() and (sub_dir / ".git").exists():
        code, out, _ = run_git_cmd(
            ["config", "--get", "remote.origin.url"], cwd=sub_dir
        )
        if code == 0 and out:
            return out

    # Fallback to inspecting .gitmodules from repo root or parent directories
    # Check parent module .gitmodules for nested submodules
    parts = Path(sub_path).parts
    if len(parts) > 1:
        parent_dir = repo_root / Path(*parts[:-1])
        sub_name = parts[-1]
        code, out, _ = run_git_cmd(
            ["config", "-f", ".gitmodules", "--get", f"submodule.{sub_name}.url"],
            cwd=parent_dir,
        )
        if code == 0 and out:
            return out

    # Check top-level .gitmodules
    code, out, _ = run_git_cmd(
        ["config", "-f", ".gitmodules", "--get", f"submodule.{sub_path}.url"],
        cwd=repo_root,
    )
    if code == 0 and out:
        return out

    # If key lookup by path failed, search by value match
    code, out, _ = run_git_cmd(
        ["config", "-f", ".gitmodules", "--get-regexp", r"^submodule\..*\.path$"],
        cwd=repo_root,
    )
    if code == 0 and out:
        for line in out.splitlines():
            k_v = line.split(None, 1)
            if len(k_v) == 2 and k_v[1].strip() == sub_path:
                key_base = k_v[0].rsplit(".", 1)[0]
                c, url_out, _ = run_git_cmd(
                    ["config", "-f", ".gitmodules", "--get", f"{key_base}.url"],
                    cwd=repo_root,
                )
                if c == 0 and url_out:
                    return url_out

    raise ValueError(f"Could not determine remote URL for submodule '{sub_path}'")


def get_gitmodules_configured_branch(repo_root: Path, sub_path: str) -> str | None:
    """Retrieve the branch explicitly configured in .gitmodules for a submodule."""
    # Check if configured in top-level repo_root/.gitmodules
    code, out, _ = run_git_cmd(
        ["config", "-f", ".gitmodules", "--get", f"submodule.{sub_path}.branch"],
        cwd=repo_root,
    )
    if code == 0 and out.strip():
        return out.strip()

    # Search through parent directory .gitmodules (e.g. extern/helm/.gitmodules for libs/amio)
    sub_path_obj = Path(sub_path)
    for parent in sub_path_obj.parents:
        parent_dir = repo_root / parent
        if parent_dir != repo_root and (parent_dir / ".gitmodules").exists():
            rel_path = str(sub_path_obj.relative_to(parent))
            code, out, _ = run_git_cmd(
                [
                    "config",
                    "-f",
                    ".gitmodules",
                    "--get",
                    f"submodule.{rel_path}.branch",
                ],
                cwd=parent_dir,
            )
            if code == 0 and out.strip():
                return out.strip()

    return None


def resolve_submodule_target_branch(
    repo_root: Path,
    sub_path: str,
    remote_url: str,
    parent_target_branch: str,
    branch_map: dict[str, str],
    upstream_config: UpstreamTargetBranchConfig | None = None,
) -> str:
    """Determine the expected upstream target branch for a submodule.

    Precedence:
    1. Explicit branch map override (`--branch-map path=branch`).
    2. Verify dataclass source-of-truth expected branch.
    3. Branch configured in `.gitmodules` (if defined and validated).
    4. Parent target branch.
    """
    if sub_path in branch_map:
        mapped = branch_map[sub_path]
        logger.info("Submodule '%s' using mapped branch '%s'", sub_path, mapped)
        return mapped

    if upstream_config is None:
        upstream_config = UpstreamTargetBranchConfig()

    mapped_branch = upstream_config.branch_maps.get(sub_path, {}).get(
        parent_target_branch
    )
    if mapped_branch:
        logger.info(
            "Submodule '%s' using branch '%s' from verify dataclass for parent branch '%s'",
            sub_path,
            mapped_branch,
            parent_target_branch,
        )
        return mapped_branch

    # Inspect .gitmodules for explicit branch configuration
    gitmodules_branch = get_gitmodules_configured_branch(repo_root, sub_path)
    if gitmodules_branch:
        logger.info(
            "Submodule '%s' using branch '%s' from .gitmodules",
            sub_path,
            gitmodules_branch,
        )
        return gitmodules_branch

    return parent_target_branch


def get_remote_branch_head_sha(remote_url: str, branch: str) -> str | None:
    """Query the remote repository via `git ls-remote` for the HEAD SHA of the branch."""
    ref = f"refs/heads/{branch}"
    code, out, err = run_git_cmd(["ls-remote", remote_url, ref])
    if code != 0:
        logger.error("git ls-remote failed for %s (%s): %s", remote_url, ref, err)
        return None

    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == ref:
            return parts[0]

    # If exact ref didn't match, check if bare branch matched
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            return parts[0]

    logger.error("Branch '%s' not found on remote %s", branch, remote_url)
    return None


def is_ancestor_commit(
    repo_root: Path, sub_path: str, ancestor: str, descendant: str
) -> bool:
    """Check if `ancestor` commit is an ancestor of `descendant` in the local submodule repo."""
    sub_dir = repo_root / sub_path
    if not (sub_dir / ".git").exists():
        return False
    code, _, _ = run_git_cmd(
        ["merge-base", "--is-ancestor", ancestor, descendant],
        cwd=sub_dir,
    )
    return code == 0


def get_declared_submodules(repo_root: Path) -> set[str]:
    """Collect all submodule paths declared in .gitmodules files (including nested)."""
    declared: set[str] = set()
    root_gitmodules = repo_root / ".gitmodules"
    if not root_gitmodules.exists():
        return declared

    code, out, _ = run_git_cmd(
        ["config", "-f", ".gitmodules", "--get-regexp", r"^submodule\..*\.path$"],
        cwd=repo_root,
    )
    if code == 0 and out:
        for line in out.splitlines():
            parts = line.split(None, 1)
            if len(parts) == 2:
                declared.add(parts[1].strip())

    for sub_path in list(declared):
        sub_gitmodules = repo_root / sub_path / ".gitmodules"
        if sub_gitmodules.exists():
            c, nested_out, _ = run_git_cmd(
                [
                    "config",
                    "-f",
                    ".gitmodules",
                    "--get-regexp",
                    r"^submodule\..*\.path$",
                ],
                cwd=repo_root / sub_path,
            )
            if c == 0 and nested_out:
                for line in nested_out.splitlines():
                    parts = line.split(None, 1)
                    if len(parts) == 2:
                        declared.add(f"{sub_path}/{parts[1].strip()}")

    return declared


def verify_submodules(
    repo_root: Path,
    target_branch: str,
    branch_map: dict[str, str],
    allow_ancestor: bool = False,
    upstream_config: UpstreamTargetBranchConfig | None = None,
) -> list[SubmoduleStatus]:
    """Execute submodule verification for all submodules in the repository."""
    if upstream_config is None:
        upstream_config = UpstreamTargetBranchConfig()

    logger.info(
        "Verifying submodules in %s against target branch '%s'",
        repo_root,
        target_branch,
    )

    declared_paths = get_declared_submodules(repo_root)

    # 1. Run git submodule status --recursive
    code, status_out, err = run_git_cmd(
        ["submodule", "status", "--recursive"], cwd=repo_root
    )
    if code != 0:
        logger.error("Failed to query git submodule status: %s", err)
        raise RuntimeError(f"git submodule status failed: {err}")

    raw_entries = parse_submodule_status_lines(status_out)
    if not raw_entries and declared_paths:
        logger.error(
            "Repository has %d submodule(s) declared in .gitmodules, but none were detected by git submodule status.",
            len(declared_paths),
        )
        return [
            SubmoduleStatus(
                path=p,
                current_sha="",
                target_branch=target_branch,
                remote_url="",
                status=VerificationStatus.ERROR,
                detail="Declared in .gitmodules but missing from git submodule status (run 'git submodule update --init --recursive')",
            )
            for p in sorted(declared_paths)
        ]

    if not raw_entries:
        logger.info("No submodules found in repository.")
        return []

    logger.info("Discovered %d submodule(s) (direct and nested)", len(raw_entries))
    all_sub_paths = [entry[2] for entry in raw_entries]
    results: list[SubmoduleStatus] = []
    for status_char, current_sha, sub_path in raw_entries:
        is_nested = any(
            other != sub_path and sub_path.startswith(other + "/")
            for other in all_sub_paths
        )
        status_obj = SubmoduleStatus(
            path=sub_path,
            current_sha=current_sha,
            target_branch="",
            remote_url="",
            is_nested=is_nested,
        )

        if status_char == "-":
            status_obj.status = VerificationStatus.UNINITIALIZED
            status_obj.detail = "Submodule is not initialized locally"
            logger.warning("Submodule '%s' is not initialized.", sub_path)
            results.append(status_obj)
            continue

        try:
            remote_url = get_submodule_remote_url(repo_root, sub_path)
            status_obj.remote_url = remote_url
        except Exception as ex:
            status_obj.status = VerificationStatus.ERROR
            status_obj.detail = f"Failed to get remote URL: {ex}"
            logger.error("Error getting remote URL for '%s': %s", sub_path, ex)
            results.append(status_obj)
            continue

        # Validate that .gitmodules does not drift from verify dataclass source of truth
        expected_config_branch = upstream_config.branch_maps.get(sub_path, {}).get(
            target_branch, target_branch
        )
        gitmodules_branch = get_gitmodules_configured_branch(repo_root, sub_path)

        if gitmodules_branch and sub_path not in branch_map:
            if gitmodules_branch != expected_config_branch:
                status_obj.status = VerificationStatus.ERROR
                status_obj.target_branch = gitmodules_branch
                status_obj.detail = (
                    f".gitmodules branch '{gitmodules_branch}' "
                    f"differs from expected verify dataclass '{expected_config_branch}' for parent target branch '{target_branch}'"
                )
                logger.error(
                    "Submodule '%s' .gitmodules branch '%s' differs from expected verify dataclass '%s' for parent target branch '%s'",
                    sub_path,
                    gitmodules_branch,
                    expected_config_branch,
                    target_branch,
                )
                results.append(status_obj)
                continue

        sub_branch = resolve_submodule_target_branch(
            repo_root,
            sub_path,
            remote_url,
            target_branch,
            branch_map,
            upstream_config=upstream_config,
        )
        status_obj.target_branch = sub_branch

        expected_sha = get_remote_branch_head_sha(remote_url, sub_branch)
        status_obj.expected_sha = expected_sha

        if not expected_sha:
            status_obj.status = VerificationStatus.ERROR
            status_obj.detail = f"Could not find HEAD SHA for branch '{sub_branch}'"
            logger.error(
                "Could not find expected SHA for '%s' on %s", sub_path, remote_url
            )
            results.append(status_obj)
            continue

        if current_sha.lower() == expected_sha.lower():
            status_obj.status = VerificationStatus.OK
            status_obj.detail = "Pointers match upstream HEAD"
        else:
            if allow_ancestor and is_ancestor_commit(
                repo_root, sub_path, current_sha, expected_sha
            ):
                status_obj.status = VerificationStatus.OK
                status_obj.detail = "Committed commit is ancestor of upstream HEAD"
            else:
                status_obj.status = VerificationStatus.OUT_OF_SYNC
                # Check how many commits behind/ahead if objects exist locally
                sub_dir = repo_root / sub_path
                count_code, count_out, _ = run_git_cmd(
                    ["rev-list", "--count", f"{current_sha}..{expected_sha}"],
                    cwd=sub_dir,
                )
                if count_code == 0 and count_out.isdigit():
                    behind_count = int(count_out)
                    status_obj.detail = f"Behind upstream by {behind_count} commit(s)"
                else:
                    status_obj.detail = (
                        "Drift detected (different commit from upstream HEAD)"
                    )

        results.append(status_obj)

    # Cross-reference: verify every submodule declared in .gitmodules was checked
    checked_paths = {s.path for s in results}
    missing_paths = declared_paths - checked_paths
    for missing in sorted(missing_paths):
        is_nested = "/" in missing
        logger.error(
            "Submodule '%s' is declared in .gitmodules but was not checked by git submodule status.",
            missing,
        )
        results.append(
            SubmoduleStatus(
                path=missing,
                current_sha="",
                target_branch=target_branch,
                remote_url="",
                status=VerificationStatus.ERROR,
                detail="Declared in .gitmodules but missing from git submodule status (run 'git submodule update --init --recursive')",
                is_nested=is_nested,
            )
        )

    return results


def log_verification_report(
    statuses: list[SubmoduleStatus], target_branch: str
) -> bool:
    """Log formatted report table. Returns True if all passed."""
    sep = "=" * 88
    dash_sep = "-" * 88

    has_errors = any(s.status != VerificationStatus.OK for s in statuses)

    # Route header via appropriate log level
    log_func = logger.error if has_errors else logger.info

    log_func(sep)
    log_func("CECE Submodule Verification Report")
    log_func("Target Parent Branch: %s", target_branch)
    log_func(sep)
    log_func(
        "%-30s %-14s %-10s %-10s %-20s",
        "Path",
        "Target Branch",
        "Current",
        "Expected",
        "Status",
    )
    log_func(dash_sep)

    for s in statuses:
        cur_short = s.current_sha[:8] if s.current_sha else "none"
        exp_short = s.expected_sha[:8] if s.expected_sha else "unknown"
        status_display = (
            s.status.value
            if s.status == VerificationStatus.OK
            else f"{s.status.value} ({s.detail})"
        )

        item_log = logger.info if s.status == VerificationStatus.OK else logger.error
        item_log(
            "%-30s %-14s %-10s %-10s %-20s",
            s.path,
            s.target_branch or "-",
            cur_short,
            exp_short,
            status_display,
        )

    log_func(sep)

    if not has_errors:
        logger.info(
            "All %d submodule(s) are in sync with upstream target branches.",
            len(statuses),
        )
        return True

    mismatches = [s for s in statuses if s.status != VerificationStatus.OK]
    logger.error(
        "%d submodule pointer(s) are out of sync or in error state.", len(mismatches)
    )
    return False


def generate_step_summary(
    statuses: list[SubmoduleStatus], target_branch: str, summary_file: Path
) -> None:
    """Write GitHub Actions step summary markdown table to summary_file."""
    lines: list[str] = [
        "## Submodule Verification Report",
        "",
        f"**Target Parent Branch:** `{target_branch}`",
        "",
        "| Submodule Path | Target Branch | Current SHA | Expected SHA | Status | Details |",
        "|---|---|---|---|---|---|",
    ]

    for s in statuses:
        cur_short = f"`{s.current_sha[:8]}`" if s.current_sha else "`none`"
        exp_short = f"`{s.expected_sha[:8]}`" if s.expected_sha else "`unknown`"
        status_badge = (
            "✅ OK" if s.status == VerificationStatus.OK else f"❌ **{s.status.value}**"
        )
        lines.append(
            f"| `{s.path}` | `{s.target_branch or '-'}` | {cur_short} | {exp_short} | {status_badge} | {s.detail} |"
        )

    lines.append("")

    has_errors = any(s.status != VerificationStatus.OK for s in statuses)
    if has_errors:
        lines.append("> [!WARNING]")
        lines.append(
            "> One or more submodules are out of sync with their upstream tracking branches."
        )

    summary_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("GitHub Step Summary written to %s", summary_file)


def parse_branch_map_args(branch_map_raw: Sequence[str] | None) -> dict[str, str]:
    """Parse PATH=BRANCH command-line arguments into a dictionary."""
    mapping: dict[str, str] = {}
    if not branch_map_raw:
        return mapping
    for item in branch_map_raw:
        if "=" not in item:
            raise argparse.ArgumentTypeError(
                f"Invalid branch map format '{item}'. Expected PATH=BRANCH."
            )
        k, v = item.split("=", 1)
        mapping[k.strip()] = v.strip()
    return mapping


def parse_args(args: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Verify that Git submodules point to expected commits on upstream branches."
    )
    parser.add_argument(
        "--target-branch",
        "-b",
        default=os.environ.get("GITHUB_BASE_REF")
        or os.environ.get("GITHUB_REF_NAME")
        or "develop",
        help="Target branch for the parent repo (e.g. 'develop' or 'main'). Default: %(default)s",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Path to CECE repository root (default: auto-detected)",
    )
    parser.add_argument(
        "--branch-map",
        nargs="*",
        metavar="PATH=BRANCH",
        help="Custom branch mapping overrides (e.g. extern/helm=develop)",
    )
    parser.add_argument(
        "--allow-ancestor",
        action="store_true",
        help="Allow submodule commit to be an ancestor of upstream HEAD rather than exact match",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output JSON formatted status array to stdout",
    )
    parser.add_argument(
        "--step-summary",
        nargs="?",
        const=os.environ.get("GITHUB_STEP_SUMMARY"),
        help="Write GitHub Actions Step Summary markdown to file (default: $GITHUB_STEP_SUMMARY)",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress informational logs (sets level to ERROR)",
    )
    return parser.parse_args(args)


def main(argv: Sequence[str] | None = None) -> int:
    """Main entrypoint."""
    opts = parse_args(argv)

    # Configure logging level (INFO minimum; ERROR if quiet)
    log_level = logging.ERROR if opts.quiet else logging.INFO

    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )

    try:
        branch_map = parse_branch_map_args(opts.branch_map)
        repo_root = get_repo_root(opts.repo_root)

        statuses = verify_submodules(
            repo_root=repo_root,
            target_branch=opts.target_branch,
            branch_map=branch_map,
            allow_ancestor=opts.allow_ancestor,
        )

        all_ok = log_verification_report(statuses, opts.target_branch)

        # Output JSON if requested
        if opts.json:
            data = []
            for s in statuses:
                item = asdict(s)
                item["status"] = s.status.value
                data.append(item)
            sys.stdout.write(json.dumps(data, indent=2) + "\n")

        # Write Step Summary if configured
        if opts.step_summary:
            summary_path = Path(opts.step_summary)
            generate_step_summary(statuses, opts.target_branch, summary_path)

        return 0 if all_ok else 1

    except Exception as ex:
        logger.exception(
            "Submodule verification terminated with an unhandled exception: %s", ex
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
