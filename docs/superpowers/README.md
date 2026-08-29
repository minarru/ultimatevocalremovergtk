# Design docs (`dev` branch)

Plans, specs, and design notes under `plans/` and `specs/` are kept on the
**`dev`** branch. They are gitignored so a feature branch that targets `main`
does not pick them up with a normal `git add`.

On `dev`, record a new document with:

```bash
git add -f docs/superpowers/specs/<file>.md
# or
git add -f docs/superpowers/plans/<file>.md
```

When merging `dev` into `main`, drop the directories before finishing the merge:

```bash
git merge --no-commit --no-ff dev
git rm -rf --ignore-unmatch docs/superpowers/plans docs/superpowers/specs
git commit
```
