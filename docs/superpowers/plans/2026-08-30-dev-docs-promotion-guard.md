# Dev-Only Documentation Promotion Guard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep Superpowers plans and specs tracked on `dev` and its descendants while making it mechanically difficult for those paths to enter `main`.

**Architecture:** A small standard-library Python command owns the protected path list and exposes `check` and `prepare` commands. CI calls `check` for `main` pushes and PRs targeting `main`; maintainers run `prepare` from a clean promotion branch based exactly on `main` to merge `dev`, resolve protected-path conflicts by removal, and leave a sanitized merge staged for review and commit. The one-time local `main` cleanup applies only this policy patch and the protected-path deletions; it must not promote unrelated in-progress `dev` commits.

**Tech Stack:** Python 3.12+ standard library, Git CLI, stdlib `unittest`, GitHub Actions YAML, Markdown.

**Spec:** `docs/superpowers/README.md`

## Global Constraints

- `docs/superpowers/plans/` and `docs/superpowers/specs/` remain tracked on `dev` and branches derived from `dev`.
- A tree proposed for `main` must contain no tracked files below either protected directory.
- Promotion automation must never push, commit, or update `main` itself; it prepares a reviewable merge on a separate branch.
- A failed promotion must abort and restore the initially clean promotion worktree when a conflict exists outside the protected directories.
- Do not merge `main` back into `dev`; cherry-pick any main-only hotfix into `dev`.
- Use only the Python standard library and Git already required by the repository.

---

### Task 1: Protected-path checker

**Files:**
- Create: `scripts/dev_docs_policy.py`
- Create: `tests/test_dev_docs_policy.py`

**Interfaces:**
- Produces: CLI `python scripts/dev_docs_policy.py [--repo PATH] check`
- Produces: `protected_paths(repo: Path) -> tuple[str, ...]`

- [ ] **Step 1: Write failing checker tests**

Create temporary Git repositories and assert that `check` exits zero without protected files, exits one when either protected directory contains a tracked file, and prints every violating path.

- [ ] **Step 2: Verify the checker tests fail**

Run: `.venv/bin/python -m unittest tests.test_dev_docs_policy.DevDocsCheckTests -v`

Expected: failure because `scripts/dev_docs_policy.py` does not exist.

- [ ] **Step 3: Implement the minimal checker**

Use `git -C <repo> ls-files -- docs/superpowers/plans docs/superpowers/specs`; report violations on stderr and return one, otherwise print a clean-boundary message and return zero.

- [ ] **Step 4: Verify the checker tests pass**

Run: `.venv/bin/python -m unittest tests.test_dev_docs_policy.DevDocsCheckTests -v`

Expected: all checker tests pass.

### Task 2: Safe promotion preparation

**Files:**
- Modify: `scripts/dev_docs_policy.py`
- Modify: `tests/test_dev_docs_policy.py`

**Interfaces:**
- Consumes: the protected path constants and checker from Task 1
- Produces: CLI `python scripts/dev_docs_policy.py [--repo PATH] prepare --source dev --target main`

- [ ] **Step 1: Write failing promotion tests**

Cover a clean promotion branch based exactly on `main`, rejection when invoked on `main` or `dev`, rejection of a dirty worktree, removal of historical and newly added protected documents, preservation of normal source changes, automatic resolution of protected-only modify/delete conflicts, and abort/restoration for a conflict outside protected paths.

- [ ] **Step 2: Verify the promotion tests fail**

Run: `.venv/bin/python -m unittest tests.test_dev_docs_policy.DevDocsPrepareTests -v`

Expected: failure because the `prepare` subcommand is absent.

- [ ] **Step 3: Implement minimal promotion preparation**

Validate the branch, clean worktree, source ref, and exact target HEAD. Run `git merge --no-commit --no-ff <source>`, remove both protected directories from the merge index, allow only protected-path conflicts, run the boundary and `git diff --cached --check`, then leave `MERGE_HEAD` and the staged sanitized tree for human review. Abort the merge before returning an error for any non-protected conflict or failed postcondition.

- [ ] **Step 4: Verify all policy tests pass**

Run: `.venv/bin/python -m unittest tests.test_dev_docs_policy -v`

Expected: all checker and promotion tests pass without warnings.

### Task 3: CI enforcement and repository guidance

**Files:**
- Modify: `.github/workflows/test.yml`
- Modify: `.github/workflows/release.yml`
- Modify: `docs/superpowers/README.md`
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: `scripts/dev_docs_policy.py check` and `prepare`
- Produces: an enforced check in the existing `unittest` job for main pushes/PRs, a release-tag check, and exact maintainer commands

- [ ] **Step 1: Add CI calls and update guidance**

Add the conditional checker step to the existing `unittest` job and an unconditional release checker step. Replace the manual merge recipe with promotion-branch commands, document that CI is the backstop, and document one-way synchronization plus cherry-picking main-only hotfixes.

- [ ] **Step 2: Review the workflow diff against event behavior**

Confirm from the staged YAML that the normal checker step runs only when `github.ref == 'refs/heads/main'` or `github.base_ref == 'main'`, remains inside the existing required `unittest` job, and that the release checker is unconditional. This configuration and human-facing prose do not receive source-text tests; the checker behavior they invoke is covered by Tasks 1 and 2.

- [ ] **Step 3: Verify focused behavior and static quality**

Run:

```bash
.venv/bin/python -m unittest tests.test_dev_docs_policy tests.test_model_manifest -v
.venv/bin/ruff check scripts/dev_docs_policy.py tests/test_dev_docs_policy.py
.venv/bin/python -m basedpyright scripts/dev_docs_policy.py tests/test_dev_docs_policy.py
bash -n install_packages.sh run_uvr.sh compile_resources.sh install-desktop.sh uvr
```

Expected: every command exits zero.

### Task 4: Record on dev and sanitize local main

**Files:**
- Force-add: `docs/superpowers/plans/2026-08-30-dev-docs-promotion-guard.md`
- Commit all verified implementation files on `dev`
- Create temporary worktree: `.worktrees/main-dev-docs-boundary`

**Interfaces:**
- Consumes: the verified implementation commit and read-only `check` command
- Produces: a dev implementation commit and a scoped local `main` cleanup commit whose tree contains no protected documents

- [ ] **Step 1: Run complete verification on dev**

Run the focused suite, full stdlib test discovery through the private GTK environment, basedpyright, Ruff on touched Python files, workflow/document whitespace checks, and `git diff --check`.

- [ ] **Step 2: Commit the focused dev change**

Force-add the ignored plan, stage only the files named by this plan, inspect the cached diff, and commit with `ci: enforce dev-only documentation boundary`.

- [ ] **Step 3: Apply only the policy patch to a main cleanup branch**

Create a temporary `cleanup/main-dev-docs-boundary` branch from local `main`. Apply the dev implementation commit without committing, remove `docs/superpowers/plans/` and `docs/superpowers/specs/`, and verify the staged patch contains only the policy implementation plus deletion of historical protected documents—not unrelated `dev` work. Commit as `ci: enforce dev-only documentation boundary on main`.

- [ ] **Step 4: Update local main and clean temporary state**

Fast-forward local `main` to the verified cleanup commit, remove the temporary worktree and cleanup branch, and do not push.

- [ ] **Step 5: Verify both branch invariants**

On `dev`, verify plans/specs including this plan and the maintainability assessment are tracked. On local `main`, run `scripts/dev_docs_policy.py check`, verify those paths are absent, and verify `dev` remains unchanged and clean.
