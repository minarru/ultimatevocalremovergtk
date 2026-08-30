# Design docs (`dev` branch)

Plans, specs, and design notes under `plans/` and `specs/` are kept on the
**`dev`** branch. They are gitignored so a feature branch that targets `main`
does not pick them up with a normal `git add`. Once force-added, they are normal
tracked files: `.gitignore` alone does not prevent a merge from carrying them.

On `dev`, record a new document with:

```bash
git add -f docs/superpowers/specs/<file>.md
# or
git add -f docs/superpowers/plans/<file>.md
```

## Promote `dev` without its design notes

Do not open a PR directly from `dev` to `main`. Prepare a separate branch based
exactly on the current local `main`; the policy tool merges `dev`, removes both
protected directories from the index, resolves conflicts confined to those
directories, and leaves the sanitized merge staged for review:

```bash
git worktree add .worktrees/promote-dev-to-main \
  -b promote/dev-to-main main
.venv/bin/python scripts/dev_docs_policy.py \
  --repo .worktrees/promote-dev-to-main \
  prepare --source dev --target main
git -C .worktrees/promote-dev-to-main status --short
git -C .worktrees/promote-dev-to-main diff --cached --check
git -C .worktrees/promote-dev-to-main commit \
  -m "chore: promote dev without development docs"
```

The command refuses a dirty worktree, `dev` or `main` itself, a promotion branch
that is not exactly at `main`, and any merge conflict outside the protected
directories. It never commits, pushes, or updates `main`. After inspection,
push the promotion branch and open its PR to `main` through the normal review
workflow.

The existing `unittest` CI job runs this read-only guard for pushes to `main`
and PRs whose base is `main`:

```bash
python3 scripts/dev_docs_policy.py check
```

The release workflow runs the same guard for version tags. A direct `dev` PR
therefore fails until it is replaced by a sanitized promotion branch. The
one-time boundary cleanup removes historical plans/specs that predate this
convention; future promotions keep the boundary clean.

## Branch direction after promotion

Treat synchronization as one-way: normal changes flow from `dev` to `main`
through a promotion branch. Do **not** merge or fast-forward `main` back into
`dev`, because the production tree intentionally records the design-note
removals. If an emergency fix lands on `main` first, cherry-pick that specific
commit into `dev`.
