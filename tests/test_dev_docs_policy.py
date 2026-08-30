from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_POLICY_SCRIPT = _ROOT / "scripts" / "dev_docs_policy.py"


class _GitRepository:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Dev Docs Policy Tests")
        self.git("config", "user.email", "dev-docs-policy@example.invalid")

    def git(self, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(self.root), *arguments],
            check=check,
            capture_output=True,
            text=True,
        )

    def write(self, relative: str, content: str) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def commit_all(self, message: str) -> None:
        self.git("add", "-A")
        self.git("commit", "-m", message)


def _run_policy(repo: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_POLICY_SCRIPT), "--repo", str(repo), *arguments],
        check=False,
        capture_output=True,
        text=True,
    )


class DevDocsCheckTests(unittest.TestCase):
    def test_check_accepts_repository_without_tracked_dev_docs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = _GitRepository(Path(temporary))
            repo.write("README.md", "public documentation\n")
            repo.commit_all("initial public tree")

            completed = _run_policy(repo.root, "check")

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout, "Dev-only documentation boundary is clean.\n")
        self.assertEqual(completed.stderr, "")

    def test_check_reports_every_tracked_dev_doc(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = _GitRepository(Path(temporary))
            violations = (
                "docs/superpowers/plans/example-plan.md",
                "docs/superpowers/specs/example-spec.md",
            )
            for relative in violations:
                repo.write(relative, f"# {Path(relative).stem}\n")
            repo.commit_all("add development documents")

            completed = _run_policy(repo.root, "check")

        self.assertEqual(completed.returncode, 1)
        self.assertEqual(completed.stdout, "")
        for relative in violations:
            self.assertIn(relative, completed.stderr)
        self.assertIn("must not be tracked on main", completed.stderr)


class DevDocsPrepareTests(unittest.TestCase):
    def _seed_repository(self, repo: _GitRepository) -> None:
        repo.write("README.md", "public documentation\n")
        repo.write("docs/superpowers/specs/historical.md", "# Historical design\n")
        repo.commit_all("initial main tree")

    def _add_dev_change(self, repo: _GitRepository) -> None:
        repo.git("switch", "-c", "dev")
        repo.write("application.txt", "development change\n")
        repo.write("docs/superpowers/plans/new-plan.md", "# New plan\n")
        repo.commit_all("develop feature")

    def test_prepare_stages_source_changes_without_dev_docs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = _GitRepository(Path(temporary))
            self._seed_repository(repo)
            self._add_dev_change(repo)
            repo.git("switch", "-c", "promote/dev-to-main", "main")

            completed = _run_policy(
                repo.root,
                "prepare",
                "--source",
                "dev",
                "--target",
                "main",
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)

            tracked_docs = repo.git(
                "ls-files",
                "--",
                "docs/superpowers/plans",
                "docs/superpowers/specs",
            ).stdout
            staged_application = repo.git("show", ":application.txt").stdout
            merge_head = repo.git("rev-parse", "--verify", "MERGE_HEAD", check=False)
            staged_names = repo.git("diff", "--cached", "--name-status").stdout

        self.assertEqual(tracked_docs, "")
        self.assertEqual(staged_application, "development change\n")
        self.assertEqual(merge_head.returncode, 0)
        self.assertIn("A\tapplication.txt", staged_names)
        self.assertIn("D\tdocs/superpowers/specs/historical.md", staged_names)
        self.assertIn("Review and commit the sanitized merge", completed.stdout)

    def test_prepare_rejects_source_and_target_branches(self) -> None:
        for branch in ("main", "dev"):
            with self.subTest(branch=branch), tempfile.TemporaryDirectory() as temporary:
                repo = _GitRepository(Path(temporary))
                self._seed_repository(repo)
                self._add_dev_change(repo)
                repo.git("switch", branch)

                completed = _run_policy(
                    repo.root,
                    "prepare",
                    "--source",
                    "dev",
                    "--target",
                    "main",
                )

                merge_head = repo.git("rev-parse", "--verify", "MERGE_HEAD", check=False)

            self.assertEqual(completed.returncode, 2)
            self.assertIn("separate promotion branch", completed.stderr)
            self.assertNotEqual(merge_head.returncode, 0)

    def test_prepare_rejects_dirty_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = _GitRepository(Path(temporary))
            self._seed_repository(repo)
            self._add_dev_change(repo)
            repo.git("switch", "-c", "promote/dev-to-main", "main")
            repo.write("untracked.txt", "do not overwrite me\n")

            completed = _run_policy(repo.root, "prepare")

            merge_head = repo.git("rev-parse", "--verify", "MERGE_HEAD", check=False)

        self.assertEqual(completed.returncode, 2)
        self.assertIn("worktree must be clean", completed.stderr)
        self.assertNotEqual(merge_head.returncode, 0)

    def test_prepare_requires_branch_to_start_exactly_at_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = _GitRepository(Path(temporary))
            self._seed_repository(repo)
            self._add_dev_change(repo)
            repo.git("switch", "-c", "promote/dev-to-main", "main")
            repo.write("promotion-only.txt", "unexpected branch change\n")
            repo.commit_all("change promotion branch before merge")

            completed = _run_policy(repo.root, "prepare")

            merge_head = repo.git("rev-parse", "--verify", "MERGE_HEAD", check=False)
            status = repo.git("status", "--porcelain").stdout

        self.assertEqual(completed.returncode, 2)
        self.assertIn("must start exactly at 'main'", completed.stderr)
        self.assertNotEqual(merge_head.returncode, 0)
        self.assertEqual(status, "")

    def test_prepare_resolves_protected_only_modify_delete_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = _GitRepository(Path(temporary))
            self._seed_repository(repo)
            repo.git("switch", "-c", "dev")
            repo.write("application.txt", "development change\n")
            repo.write("docs/superpowers/specs/historical.md", "# Revised design\n")
            repo.commit_all("revise development design")
            repo.git("switch", "main")
            repo.git("rm", "docs/superpowers/specs/historical.md")
            repo.git("commit", "-m", "remove development document")
            repo.git("switch", "-c", "promote/dev-to-main")

            completed = _run_policy(repo.root, "prepare")

            tracked_docs = repo.git(
                "ls-files",
                "--",
                "docs/superpowers/plans",
                "docs/superpowers/specs",
            ).stdout
            merge_head = repo.git("rev-parse", "--verify", "MERGE_HEAD", check=False)

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(tracked_docs, "")
        self.assertEqual(merge_head.returncode, 0)

    def test_prepare_aborts_non_protected_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = _GitRepository(Path(temporary))
            repo.write("application.txt", "base\n")
            repo.commit_all("initial main tree")
            repo.git("switch", "-c", "dev")
            repo.write("application.txt", "development\n")
            repo.write("docs/superpowers/specs/design.md", "# Design\n")
            repo.commit_all("develop conflicting change")
            repo.git("switch", "main")
            repo.write("application.txt", "main hotfix\n")
            repo.commit_all("apply main hotfix")
            repo.git("switch", "-c", "promote/dev-to-main")

            completed = _run_policy(repo.root, "prepare")

            merge_head = repo.git("rev-parse", "--verify", "MERGE_HEAD", check=False)
            application = (repo.root / "application.txt").read_text(encoding="utf-8")
            status = repo.git("status", "--porcelain").stdout

        self.assertEqual(completed.returncode, 2)
        self.assertIn("outside the dev-only documentation paths", completed.stderr)
        self.assertNotEqual(merge_head.returncode, 0)
        self.assertEqual(application, "main hotfix\n")
        self.assertEqual(status, "")


if __name__ == "__main__":
    unittest.main()
