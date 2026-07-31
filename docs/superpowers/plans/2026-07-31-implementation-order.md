# Implementation order

Sequencing for the two plans:

- **A** = [2026-07-31-model-catalog-naming-and-scores.md](2026-07-31-model-catalog-naming-and-scores.md) (7 tasks)
- **B** = [2026-07-31-ensemble-stem-semantics.md](2026-07-31-ensemble-stem-semantics.md) (8 tasks)

## Dependency graph

```
B1 ensemble_stem_bucket ──┬─→ B2 ─→ B3
   (pure, no deps)        ├─→ B4
                          ├─→ A2 ─┐
                          └─→ A6 ─┤
A1 model_naming ──┐              │
                  ├─→ A4 ─→ A5   │
A3 mvsepless meta ┘      └─→ A6 ─┴─→ A7 / B8
```

`B1` unblocks the most and depends on nothing, so it goes first regardless of
which plan you care about more.

## Order

### Phase 1 — Foundation + the reported bug (PR 1)

| # | Task | Why here |
| --- | --- | --- |
| 1 | **B1** stem bucket resolver | Pure, dependency-free, unblocks five downstream tasks in both plans |
| 2 | **A1** canonical model naming | Pure, dependency-free |
| 3 | **A3** mvsepless metadata sidecar | Pure data retention, no consumers yet |
| 4 | **A4** `catalog_sources` | Needs A1 + A3 |
| 5 | **A5** runtime display-name fix | Needs A4. **This is the originally reported bug** |

Ships the actual complaint — mvsepless and extras models no longer show as raw
basenames — with no user-visible behaviour change beyond that. Everything in
this phase is either pure or additive, which makes it the safest thing to land
first and the easiest to review.

Gate: `A5 Step 6` prints `still raw: []` against the real installed models.

### Phase 2 — Scores and Download Center (PR 2)

| # | Task | Why here |
| --- | --- | --- |
| 6 | **A2** SDR scores backend | Needs B1. Write `primary_sdr` in its final form (with `stem_count`) |
| 7 | **A6** Download Center presentation | Needs A2 + A4 + B1 |
| 8 | **A7** plan A verification | — |

Because B1 landed in phase 1, A2 and A6 are written correctly the first time
and **B7 becomes a no-op verification** rather than a rewrite. That is the whole
reason B1 goes first.

Gate: `A7 Step 4` reports roughly `scored 98/461 = 21.3%`.

### Phase 3 — Ensemble semantics (PR 3)

| # | Task | Why here |
| --- | --- | --- |
| 9 | **B2** karaoke stem pair | Needs B1 |
| 10 | **B3** selection compares buckets | Needs B1 + B2. First user-visible list change |
| 11 | **B4** combining uses buckets | Needs B1. **Highest-risk task — see below** |
| 12 | **B5** presets degrade gracefully | Must land with B3, which is what makes members ineligible |
| 13 | **B6** UI copy | Needs B2 |
| 14 | **B7** integration check | Should be a no-op if phase 2 followed the plan; verify, don't rewrite |
| 15 | **B8** full verification | — |

Gate: `B8 Step 4` runs a real two-member ensemble and confirms two stems are
written, not a single-member passthrough.

## Risk notes

**B4 is the one to be careful with.** It changes export filenames for karaoke
ensemble members. If a bucket tag is wrong, `get_files_to_ensemble_for_stem`
silently collects nothing, the ensemble emits one member's audio, and **every
unit test still passes**. Two guards exist and both must actually be run:
`B1 Step 6` (deliberately break the constant, watch `FilenameSafetyTests` fail,
revert) and `B8 Step 4` (real ensemble run). Do not skip either as "obviously
fine".

**B3 is the most user-visible.** Models appear in and disappear from ensemble
lists. Six karaoke models leave `Vocals/Instrumental`; five previously-excluded
models join it. Anyone with saved presets sees the difference, which is why B5
is in the same PR — landing B3 without it turns a stale preset into an
exception.

**A5 deletes nothing but touches the display path everywhere.** Its guard is
the `rg` sweep in `A5 Step 4`: the `sanitize_*` helpers stay, because
`core/ensemble_presets.py` matches on them.

## Parallelism

Only worth it in phase 1, and only in one place: **A1 and A3 are independent of
B1 and of each other**, so three agents can run concurrently on B1 + A1 + A3.
Everything after that is a chain — A4 needs both, A5 needs A4, and phases 2 and
3 are strictly sequential.

If running tasks through subagents, review between tasks rather than between
phases. The two boundaries worth a careful human look are A4→A5 (where a wrong
merge assumption would surface) and B3→B4 (where the filename contract is).

## Branch layout

Current branch is `feat/mvsepless-catalog`, which already carries the two
commits this work builds on.

```
main
 └── feat/mvsepless-catalog        (current; specs + plans committed here)
      ├── feat/catalog-naming      PR 1 — phase 1
      ├── feat/model-scores        PR 2 — phase 2, off PR 1
      └── feat/ensemble-semantics  PR 3 — phase 3, off PR 2
```

Stacked rather than parallel, because each phase consumes the previous one's
interfaces. If you would rather ship phase 1 alone and sit on it, that works —
it is self-contained and fixes the reported bug on its own.

Per the root CLAUDE.md: push to `origin` only, prefer `gh pr create` /
`gh pr merge`, and never stage with `git add -A` — this tree carries long-lived
uncommitted edits under `models/*/model_data/`.

## If you only want one thing

Phase 1 alone. It fixes what was reported, is five tasks, and every change in
it is pure or additive.
