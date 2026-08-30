#!/usr/bin/env python3
"""Enforce and prepare the dev-only Superpowers documentation boundary."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Sequence

PROTECTED_DIRECTORIES = (
    "docs/superpowers/plans",
    "docs/superpowers/specs",
)


class PolicyError(RuntimeError):
    """A branch or worktree does not satisfy the promotion contract."""


def _git(
    repo: Path,
    *arguments: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *arguments],
        check=check,
        capture_output=True,
        text=True,
    )


def protected_paths(repo: Path) -> tuple[str, ...]:
    """Return tracked paths that are forbidden from the main branch tree."""
    completed = _git(repo, "ls-files", "--", *PROTECTED_DIRECTORIES)
    return tuple(line for line in completed.stdout.splitlines() if line)


def _check(repo: Path) -> int:
    violations = protected_paths(repo)
    if violations:
        print("Dev-only documentation must not be tracked on main:", file=sys.stderr)
        for path in violations:
            print(f"  {path}", file=sys.stderr)
        return 1

    print("Dev-only documentation boundary is clean.")
    return 0


def _current_branch(repo: Path) -> str:
    completed = _git(repo, "symbolic-ref", "--quiet", "--short", "HEAD", check=False)
    if completed.returncode != 0:
        raise PolicyError("promotion requires a checked-out branch, not detached HEAD")
    return completed.stdout.strip()


def _commit(repo: Path, reference: str) -> str:
    completed = _git(repo, "rev-parse", "--verify", f"{reference}^{{commit}}", check=False)
    if completed.returncode != 0:
        raise PolicyError(f"Git reference does not resolve to a commit: {reference}")
    return completed.stdout.strip()


def _merge_in_progress(repo: Path) -> bool:
    return _git(repo, "rev-parse", "--verify", "-q", "MERGE_HEAD", check=False).returncode == 0


def _unresolved_paths(repo: Path) -> tuple[str, ...]:
    completed = _git(repo, "diff", "--name-only", "--diff-filter=U", "-z")
    return tuple(path for path in completed.stdout.split("\0") if path)


def _is_protected(path: str) -> bool:
    return any(
        path == directory or path.startswith(f"{directory}/") for directory in PROTECTED_DIRECTORIES
    )


def _abort_merge(repo: Path) -> None:
    if _merge_in_progress(repo):
        _git(repo, "merge", "--abort")


def _prepare(repo: Path, *, source: str, target: str) -> int:
    branch = _current_branch(repo)
    if branch in {source, target}:
        raise PolicyError(f"prepare must run from a separate promotion branch, not {branch!r}")

    status = _git(repo, "status", "--porcelain", "--untracked-files=all").stdout
    if status:
        raise PolicyError("promotion worktree must be clean before prepare")

    source_commit = _commit(repo, source)
    target_commit = _commit(repo, target)
    head_commit = _commit(repo, "HEAD")
    if head_commit != target_commit:
        raise PolicyError(f"promotion branch must start exactly at {target!r} ({target_commit})")

    try:
        merge = _git(repo, "merge", "--no-commit", "--no-ff", source, check=False)
        if not _merge_in_progress(repo):
            detail = (merge.stderr or merge.stdout).strip()
            raise PolicyError(f"Git did not start a promotion merge: {detail}")

        outside_conflicts = tuple(
            path for path in _unresolved_paths(repo) if not _is_protected(path)
        )
        if outside_conflicts:
            formatted = "\n".join(f"  {path}" for path in outside_conflicts)
            raise PolicyError(
                f"promotion has conflicts outside the dev-only documentation paths:\n{formatted}"
            )

        _git(repo, "rm", "-rf", "--ignore-unmatch", "--", *PROTECTED_DIRECTORIES)

        unresolved = _unresolved_paths(repo)
        if unresolved:
            formatted = "\n".join(f"  {path}" for path in unresolved)
            raise PolicyError(f"promotion still has unresolved paths:\n{formatted}")

        violations = protected_paths(repo)
        if violations:
            formatted = "\n".join(f"  {path}" for path in violations)
            raise PolicyError(f"promotion still tracks dev-only documents:\n{formatted}")

        whitespace = _git(repo, "diff", "--cached", "--check", check=False)
        if whitespace.returncode != 0:
            raise PolicyError(f"staged promotion has whitespace errors:\n{whitespace.stdout}")
    except (PolicyError, subprocess.CalledProcessError):
        _abort_merge(repo)
        raise

    print(f"Prepared {source_commit[:12]} from {source!r} for {target!r} on {branch!r}.")
    print("Review and commit the sanitized merge; this command never commits or pushes.")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo",
        type=Path,
        default=Path.cwd(),
        help="Git worktree to inspect (default: current directory)",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("check", help="fail if dev-only documents are tracked")
    prepare = subcommands.add_parser(
        "prepare",
        help="stage a sanitized dev merge on a separate promotion branch",
    )
    prepare.add_argument("--source", default="dev", help="development branch (default: dev)")
    prepare.add_argument("--target", default="main", help="production branch (default: main)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "check":
            return _check(arguments.repo)
        if arguments.command == "prepare":
            return _prepare(arguments.repo, source=arguments.source, target=arguments.target)
    except PolicyError as error:
        print(f"Policy error: {error}", file=sys.stderr)
        return 2
    except subprocess.CalledProcessError as error:
        detail = error.stderr or str(error)
        print(f"Git command failed: {detail.strip()}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
