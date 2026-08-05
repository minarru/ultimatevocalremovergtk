# UI Metadata Cache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cache karaoke/BV eligibility, persist trusted checkpoint hashes across sessions, and memoize `format_tag_title` so dry UI model lists stop re-reading multi-GB weights after the first warm pass.

**Architecture:** Three small `core/` caches with shared invalidation. (1) Session karaoke tag list keyed like `stem_check`. (2) Settings-backed path→hash with mtime/size guards, flattened into `repo.model_hash_table` for existing callers. (3) Per-tag display-title memo keyed by `_display_generation`. No settings identity migration to hashes; `ui` only wires seed/save.

**Tech Stack:** Python 3.x, stdlib `unittest`, basedpyright (`standard`), existing `Settings` JSON + `ModelRepository` / `model_display`.

**Spec:** [docs/superpowers/specs/2026-08-05-ui-metadata-cache-design.md](../specs/2026-08-05-ui-metadata-cache-design.md)

## Global Constraints

- **Tests are stdlib `unittest`, never pytest.** Run with `.venv/bin/python -m unittest ...`.
- **No tkinter.** No new `torch` / `onnxruntime` / `engines` imports at `core` import time.
- **Never run unscoped `git checkout -- .`, `git restore .`, `git reset --hard`, `git stash` or `git clean`.** Stage explicitly; never `git add -A` (local `models/*/model_data/` dirt is common).
- **Catalogue tests** that reach `_merged_for_display` must neutralise **both** `UVR_DISABLE_POLITREES` and `UVR_DISABLE_MVSEPLESS` (or patch both loaders) and call `clear_display_cache()` after replacing source data.
- **Type checking:** `.venv/bin/python -m basedpyright` clean for touched modules.
- **Search with `rg`**, not `grep`.
- **Baseline:** `.venv/bin/python -m unittest discover -s tests` green before claiming done.

## File map

| File | Role |
|---|---|
| `core/model_data.py` | Karaoke cache; hash remember/lookup helpers used by `get_model_hash` |
| `core/model_hash_cache.py` | **Create** — coerce settings entries ↔ flat map, stat guard |
| `core/model_display.py` | `format_tag_title` memo + clear with `clear_display_cache` |
| `ui/context.py` | Seed repo hash table from settings on first `repo` access |
| `core/settings/model.py` | Docstring only if needed; field already exists |
| `tests/test_karaoke_model_cache.py` | **Create** |
| `tests/test_model_hash_cache.py` | **Create** |
| `tests/test_format_tag_title_cache.py` | **Create** |
| `docs/tracked-issues.md` | Note F-follow-up / close the gap row when shipping |

---

### Task 1: Karaoke list session cache

**Files:**
- Modify: `core/model_data.py` (`__init__`, `invalidate_stem_check`, `karaoke_model_list`)
- Test: `tests/test_karaoke_model_cache.py` (create)

**Interfaces:**
- Consumes: existing `default_change_model_tags()`, `ModelConfig(..., is_dry_check=True)`, `invalidate_stem_check` call sites.
- Produces: `ModelRepository._karaoke_cache: Optional[Tuple[Tuple[str, ...], List[str]]]`; `karaoke_model_list` returns the same `List[str]` as today; `invalidate_stem_check` clears both stem and karaoke caches.

- [ ] **Step 1: Write the failing test**

Create `tests/test_karaoke_model_cache.py`:

```python
"""karaoke_model_list must not rebuild dry ModelConfigs on a warm cache hit."""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

from bundled.constants import ENSEMBLE_PARTITION, MDX_ARCH_TYPE, VR_ARCH_TYPE
from core.model_data import ModelConfig, ModelRepository
from core.settings import Settings


class KaraokeModelCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        os.environ["UVR_DATA_DIR"] = self._tmp.name
        self.addCleanup(lambda: os.environ.pop("UVR_DATA_DIR", None))
        self.settings = Settings()
        self.repo = ModelRepository()
        self.repo.invalidate_stem_check()

    def test_second_call_reuses_cached_tags(self) -> None:
        tags = (
            f"{VR_ARCH_TYPE}{ENSEMBLE_PARTITION}Fake VR",
            f"{MDX_ARCH_TYPE}{ENSEMBLE_PARTITION}Fake MDX",
        )
        builds: list[str] = []

        def fake_tags() -> list[str]:
            return list(tags)

        real_init = ModelConfig.__init__

        def counting_init(self, settings, repo, model_name, **kwargs):
            builds.append(str(model_name))
            real_init(self, settings, repo, model_name, **kwargs)
            self.model_status = True
            self.is_karaoke = str(model_name).endswith("Fake VR")
            self.is_bv_model = False
            self.model_and_process_tag = str(model_name)

        with mock.patch.object(ModelRepository, "default_change_model_tags", fake_tags):
            with mock.patch.object(ModelConfig, "__init__", counting_init):
                first = self.repo.karaoke_model_list(self.settings)
                second = self.repo.karaoke_model_list(self.settings)

        self.assertEqual(first, second)
        self.assertEqual(first, [tags[0]])
        self.assertEqual(len(builds), 2, "warm hit must not construct ModelConfigs again")

    def test_invalidate_stem_check_clears_karaoke_cache(self) -> None:
        tags = (f"{VR_ARCH_TYPE}{ENSEMBLE_PARTITION}Fake VR",)
        builds: list[str] = []

        def fake_tags() -> list[str]:
            return list(tags)

        real_init = ModelConfig.__init__

        def counting_init(self, settings, repo, model_name, **kwargs):
            builds.append(str(model_name))
            real_init(self, settings, repo, model_name, **kwargs)
            self.model_status = True
            self.is_karaoke = True
            self.is_bv_model = False
            self.model_and_process_tag = str(model_name)

        with mock.patch.object(ModelRepository, "default_change_model_tags", fake_tags):
            with mock.patch.object(ModelConfig, "__init__", counting_init):
                self.repo.karaoke_model_list(self.settings)
                self.repo.invalidate_stem_check()
                self.repo.karaoke_model_list(self.settings)

        self.assertEqual(len(builds), 2)


if __name__ == "__main__":
    unittest.main()
```

If patching `ModelConfig.__init__` proves too invasive (real `__init__` still hashes), prefer constructing a stub class and patching `core.model_data.ModelConfig` to a lightweight stand-in that only sets the four attributes above — keep the same assertions.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_karaoke_model_cache -v`

Expected: FAIL — second call still constructs two `ModelConfig`s (`len(builds) == 4`).

- [ ] **Step 3: Implement the cache**

In `ModelRepository.__init__`, next to `_stem_check_cache`:

```python
self._karaoke_cache = None
```

Replace `karaoke_model_list` with:

```python
def karaoke_model_list(self, settings: Settings) -> List[str]:
    """Build the dry-check vocal-split model pool."""
    tags = tuple(self.default_change_model_tags())
    if self._karaoke_cache is not None and self._karaoke_cache[0] == tags:
        return list(self._karaoke_cache[1])
    model_list: List[str] = []
    for tag in tags:
        model = ModelConfig(settings, self, tag, is_dry_check=True)
        if model.model_status and (model.is_karaoke or model.is_bv_model):
            model_list.append(model.model_and_process_tag)
    self._karaoke_cache = (tags, model_list)
    return list(model_list)
```

In `invalidate_stem_check`:

```python
def invalidate_stem_check(self) -> None:
    from .debug_log import debug

    debug("model", "invalidate_stem_check")
    self._stem_check_cache = None
    self._karaoke_cache = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.test_karaoke_model_cache -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/model_data.py tests/test_karaoke_model_cache.py
git commit -m "$(cat <<'EOF'
perf(core): cache karaoke_model_list dry-check results

Vocal-split expand rebuilt a ModelConfig per VR/MDX tag on every call;
reuse a tag-keyed session cache cleared with invalidate_stem_check.
EOF
)"
```

---

### Task 2: Hash-table coerce + mtime guard helpers

**Files:**
- Create: `core/model_hash_cache.py`
- Test: `tests/test_model_hash_cache.py` (create)

**Interfaces:**
- Consumes: `os.stat` on checkpoint paths.
- Produces:
  - `HashEntry` TypedDict or small dataclass with `hash: str`, `mtime_ns: int`, `size: int`
  - `flatten_trusted(table: dict, *, stat=os.stat) -> Dict[str, str]`
  - `remember(table: dict, path: str, digest: str, *, stat=os.stat) -> None` (mutates settings-shaped dict)
  - `lookup_trusted(table: dict, path: str, *, stat=os.stat) -> Optional[str]`

- [ ] **Step 1: Write the failing test**

Create `tests/test_model_hash_cache.py`:

```python
"""Durable model hash entries must ignore stale mtime/size."""

from __future__ import annotations

import os
import tempfile
import unittest
from types import SimpleNamespace

from core import model_hash_cache as mhc


class ModelHashCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "model.ckpt")
        with open(self.path, "wb") as handle:
            handle.write(b"abc")
        st = os.stat(self.path)
        self.entry = {
            "hash": "deadbeef",
            "mtime_ns": st.st_mtime_ns,
            "size": st.st_size,
        }

    def test_flatten_trusted_keeps_matching_entry(self) -> None:
        table = {self.path: dict(self.entry)}
        self.assertEqual(mhc.flatten_trusted(table), {self.path: "deadbeef"})

    def test_flatten_trusted_drops_stale_mtime(self) -> None:
        stale = dict(self.entry)
        stale["mtime_ns"] = self.entry["mtime_ns"] - 1
        table = {self.path: stale}
        self.assertEqual(mhc.flatten_trusted(table), {})

    def test_legacy_string_is_not_trusted_until_remembered(self) -> None:
        table = {self.path: "deadbeef"}
        self.assertEqual(mhc.flatten_trusted(table), {})

    def test_remember_writes_stat_fields(self) -> None:
        table: dict = {}
        mhc.remember(table, self.path, "cafebabe")
        stored = table[self.path]
        self.assertEqual(stored["hash"], "cafebabe")
        st = os.stat(self.path)
        self.assertEqual(stored["mtime_ns"], st.st_mtime_ns)
        self.assertEqual(stored["size"], st.st_size)

    def test_lookup_trusted_returns_hash(self) -> None:
        table = {self.path: dict(self.entry)}
        self.assertEqual(mhc.lookup_trusted(table, self.path), "deadbeef")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_model_hash_cache -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'core.model_hash_cache'`.

- [ ] **Step 3: Implement helpers**

Create `core/model_hash_cache.py`:

```python
"""Trusted path→hash entries for dry model checks across sessions."""

from __future__ import annotations

import os
from typing import Any, Callable, Dict, Mapping, MutableMapping, Optional

StatFn = Callable[[str], os.stat_result]


def _as_entry(value: Any) -> Optional[Dict[str, Any]]:
    if isinstance(value, Mapping) and "hash" in value:
        digest = value.get("hash")
        if isinstance(digest, str) and digest:
            return {
                "hash": digest,
                "mtime_ns": int(value.get("mtime_ns") or 0),
                "size": int(value.get("size") or -1),
            }
    return None


def lookup_trusted(
    table: Mapping[str, Any],
    path: str,
    *,
    stat: StatFn = os.stat,
) -> Optional[str]:
    raw = table.get(path)
    entry = _as_entry(raw)
    if entry is None:
        return None
    try:
        st = stat(path)
    except OSError:
        return None
    if st.st_mtime_ns != entry["mtime_ns"] or st.st_size != entry["size"]:
        return None
    return entry["hash"]


def flatten_trusted(
    table: Mapping[str, Any],
    *,
    stat: StatFn = os.stat,
) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for path in table:
        digest = lookup_trusted(table, path, stat=stat)
        if digest is not None:
            out[path] = digest
    return out


def remember(
    table: MutableMapping[str, Any],
    path: str,
    digest: str,
    *,
    stat: StatFn = os.stat,
) -> None:
    st = stat(path)
    table[path] = {
        "hash": digest,
        "mtime_ns": st.st_mtime_ns,
        "size": st.st_size,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.test_model_hash_cache -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/model_hash_cache.py tests/test_model_hash_cache.py
git commit -m "$(cat <<'EOF'
feat(core): add mtime-guarded model hash table helpers

Settings can store path→{hash,mtime_ns,size}; only matching stats flatten
into the session path→hash map used by ModelConfig.
EOF
)"
```

---

### Task 3: Wire durable hashes into ModelConfig + AppContext

**Files:**
- Modify: `core/model_data.py` (`get_model_hash`)
- Modify: `ui/context.py` (`repo` property)
- Test: extend `tests/test_model_hash_cache.py` with a thin integration test using `ModelRepository` + `Settings` (no GTK)

**Interfaces:**
- Consumes: `flatten_trusted`, `remember`, `lookup_trusted` from Task 2; `settings.process.model_hash_table`.
- Produces: `AppContext.repo` seeds `repo.model_hash_table` from trusted settings entries; `ModelConfig.get_model_hash` updates both `repo.model_hash_table` and `settings.process.model_hash_table` when it computes a digest.

- [ ] **Step 1: Write the failing integration test**

Add to `tests/test_model_hash_cache.py`:

```python
class ModelHashWireTests(unittest.TestCase):
    def test_get_model_hash_remembers_into_settings(self) -> None:
        import tempfile
        from unittest import mock

        from core.model_data import ModelConfig, ModelRepository
        from core.settings import Settings

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "w.ckpt")
        with open(path, "wb") as handle:
            handle.write(b"payload")

        settings = Settings()
        repo = ModelRepository()
        repo.model_hash_table = {}

        cfg = ModelConfig.__new__(ModelConfig)
        cfg.settings = settings
        cfg.repo = repo
        cfg.model_path = path
        cfg.model_status = True
        cfg.model_hash = None
        cfg.is_dry_check = True

        with mock.patch(
            "core.model_data.compute_checkpoint_hash", return_value="abc123"
        ):
            cfg.get_model_hash()

        self.assertEqual(repo.model_hash_table[path], "abc123")
        self.assertEqual(settings.process.model_hash_table[path]["hash"], "abc123")
```

Also add:

```python
    def test_appcontext_seeds_trusted_hashes(self) -> None:
        import tempfile

        from ui.context import AppContext

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        os.environ["UVR_DATA_DIR"] = tmp.name
        self.addCleanup(lambda: os.environ.pop("UVR_DATA_DIR", None))

        path = os.path.join(tmp.name, "w.ckpt")
        with open(path, "wb") as handle:
            handle.write(b"payload")
        st = os.stat(path)

        # Write a minimal settings.json the way Settings.load expects, or
        # construct Settings and assign before first repo access:
        ctx = AppContext()
        ctx.settings.process.model_hash_table = {
            path: {"hash": "seeded", "mtime_ns": st.st_mtime_ns, "size": st.st_size}
        }
        # Force repo rebuild if already created — AppContext creates lazily:
        ctx._repo = None
        self.assertEqual(ctx.repo.model_hash_table.get(path), "seeded")
```

Adjust `AppContext` seeding so the second test can pass (seed on every `ModelRepository()` construction inside the property).

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.test_model_hash_cache -v`

Expected: FAIL — settings table not updated / repo not seeded.

- [ ] **Step 3: Wire `get_model_hash`**

Replace the body of `ModelConfig.get_model_hash` so it:

1. Tries `lookup_trusted(settings.process.model_hash_table, self.model_path)` first (optional fast path).
2. Else uses existing `repo.model_hash_table` path→hash scan / compute.
3. On compute success: `repo.model_hash_table[path] = digest` and `remember(settings.process.model_hash_table, path, digest)`.

Keep behaviour when the file is missing (`model_status = False`). Prefer a direct dict get over the current linear scan of `cache.items()` while touching this.

Minimal shape:

```python
def get_model_hash(self):
    from .model_hash_cache import lookup_trusted, remember

    self.model_hash = None
    if not os.path.isfile(self.model_path):
        self.model_status = False
        return
    path = self.model_path
    trusted = lookup_trusted(self.settings.process.model_hash_table, path)
    if trusted:
        self.model_hash = trusted
        self.repo.model_hash_table[path] = trusted
        return
    cached = self.repo.model_hash_table.get(path)
    if cached:
        self.model_hash = cached
        return
    self.model_hash = compute_checkpoint_hash(path)
    if self.model_hash:
        self.repo.model_hash_table[path] = self.model_hash
        remember(self.settings.process.model_hash_table, path, self.model_hash)
```

- [ ] **Step 4: Seed from AppContext**

In `ui/context.py` `repo` property:

```python
@property
def repo(self) -> ModelRepository:
    if self._repo is None:
        from core.model_hash_cache import flatten_trusted

        self._repo = ModelRepository()
        self._repo.model_hash_table = flatten_trusted(
            self.settings.process.model_hash_table
        )
        self._install_unrecognized_model_hook()
    return self._repo
```

Ensure CLI / tests that construct `ModelRepository()` alone still work (empty table). Headless code that loads `Settings` and wants persistence should either use `AppContext` or call `flatten_trusted` the same way — document in a one-line comment on `ModelRepository.model_hash_table`.

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python -m unittest tests.test_model_hash_cache tests.test_karaoke_model_cache -v`

Expected: PASS.

Also run any existing model-hash / stem-check tests:

Run: `.venv/bin/python -m unittest discover -s tests -p 'test_*model*' -v`

- [ ] **Step 6: Commit**

```bash
git add core/model_data.py ui/context.py tests/test_model_hash_cache.py
git commit -m "$(cat <<'EOF'
perf(core): persist trusted checkpoint hashes in settings

Seed ModelRepository from process.model_hash_table on AppContext.repo
and remember mtime-guarded entries when get_model_hash computes a digest.
EOF
)"
```

---

### Task 4: Memoize `format_tag_title`

**Files:**
- Modify: `core/model_display.py` (`format_tag_title`, `clear_display_cache`)
- Test: `tests/test_format_tag_title_cache.py` (create)

**Interfaces:**
- Consumes: `_display_generation`, `clear_display_cache`, `parse_model_tag`, `display_name_for_model`.
- Produces: module cache cleared whenever display generation bumps; `format_tag_title(tag, repo)` unchanged signature.

- [ ] **Step 1: Write the failing test**

Create `tests/test_format_tag_title_cache.py`:

```python
"""format_tag_title should hit a generation-keyed memo after the first call."""

from __future__ import annotations

import os
import unittest
from unittest import mock

from bundled.constants import ENSEMBLE_PARTITION, MDX_ARCH_TYPE
from core import model_display as md


class FormatTagTitleCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["UVR_DISABLE_POLITREES"] = "1"
        os.environ["UVR_DISABLE_MVSEPLESS"] = "1"
        self.addCleanup(lambda: os.environ.pop("UVR_DISABLE_POLITREES", None))
        self.addCleanup(lambda: os.environ.pop("UVR_DISABLE_MVSEPLESS", None))
        md.clear_display_cache()

    def test_second_call_does_not_reenter_display_name(self) -> None:
        tag = f"{MDX_ARCH_TYPE}{ENSEMBLE_PARTITION}Example"
        repo = mock.Mock()
        calls = {"n": 0}
        real = md.display_name_for_model

        def counted(arch, name, r):
            calls["n"] += 1
            return real(arch, name, r)

        with mock.patch.object(md, "display_name_for_model", side_effect=counted):
            first = md.format_tag_title(tag, repo)
            second = md.format_tag_title(tag, repo)

        self.assertEqual(first, second)
        self.assertEqual(calls["n"], 1)

    def test_clear_display_cache_busts_memo(self) -> None:
        tag = f"{MDX_ARCH_TYPE}{ENSEMBLE_PARTITION}Example"
        repo = mock.Mock()
        calls = {"n": 0}

        def counted(arch, name, r):
            calls["n"] += 1
            return f"label-{calls['n']}"

        with mock.patch.object(md, "display_name_for_model", side_effect=counted):
            md.format_tag_title(tag, repo)
            md.clear_display_cache()
            md.format_tag_title(tag, repo)

        self.assertEqual(calls["n"], 2)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_format_tag_title_cache -v`

Expected: FAIL — `calls["n"] == 2` on the first test.

- [ ] **Step 3: Implement memo**

In `core/model_display.py`, near `_display_generation`:

```python
_format_tag_title_cache: dict[tuple[str, int], str] = {}
```

In `clear_display_cache`:

```python
def clear_display_cache() -> None:
    global _display_generation
    _display_generation += 1
    _merged_for_display_at.cache_clear()
    _format_tag_title_cache.clear()
```

Replace `format_tag_title` with:

```python
def format_tag_title(tag: str, repo: "ModelRepository") -> str:
    """Return the friendly model label for a full arch tag."""
    key = (tag, _display_generation)
    cached = _format_tag_title_cache.get(key)
    if cached is not None:
        return cached
    arch, model_name = parse_model_tag(tag)
    if not arch:
        result = model_name
    else:
        result = display_name_for_model(arch, model_name, repo)
    _format_tag_title_cache[key] = result
    return result
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m unittest tests.test_format_tag_title_cache tests.test_model_display_cache -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/model_display.py tests/test_format_tag_title_cache.py
git commit -m "$(cat <<'EOF'
perf(core): memoize format_tag_title by display generation

Combo populate calls this per tag; reuse labels until clear_display_cache.
EOF
)"
```

---

### Task 5: Persist hash table on settings save + docs

**Files:**
- Modify: `docs/tracked-issues.md` (short note under fork-only or performance follow-ups)
- Verify: `Settings.save` already serializes `process.model_hash_table` via `to_dict` — confirm with a round-trip test if missing

**Interfaces:**
- Consumes: Task 3 remember into `settings.process.model_hash_table`.
- Produces: documented behaviour; round-trip test proving JSON survives reload.

- [ ] **Step 1: Write round-trip test**

Add to `tests/test_model_hash_cache.py`:

```python
class ModelHashPersistTests(unittest.TestCase):
    def test_settings_round_trip_keeps_entry_shape(self) -> None:
        import tempfile

        from core.settings import Settings

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "settings.json")
        ckpt = os.path.join(tmp.name, "m.ckpt")
        with open(ckpt, "wb") as handle:
            handle.write(b"x")
        st = os.stat(ckpt)

        settings = Settings()
        settings.path = path
        settings.process.model_hash_table = {
            ckpt: {"hash": "zz", "mtime_ns": st.st_mtime_ns, "size": st.st_size}
        }
        settings.save(path)

        loaded = Settings.load(path)
        self.assertEqual(
            loaded.process.model_hash_table[ckpt]["hash"],
            "zz",
        )
```

Confirm `Settings.load` accepts an explicit path (if not, write via the same mechanism existing settings tests use — mirror `tests/test_settings*.py`).

- [ ] **Step 2: Run test**

Run: `.venv/bin/python -m unittest tests.FAKESECRET_i2j3k4l5m6n7o8p9q0r1 -v`

Expected: PASS (or FAIL only if load path API differs — fix test to match existing Settings API, do not invent a new save format).

- [ ] **Step 3: Update tracked-issues**

Add one row or a short bullet under performance / fork-only: karaoke cache + durable hash table + `format_tag_title` memo (link this plan). Mark as done only after Tasks 1–4 land in the same PR/branch.

- [ ] **Step 4: Full verification**

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m basedpyright
```

Expected: all tests PASS; basedpyright clean for touched paths.

- [ ] **Step 5: Commit**

```bash
git add tests/test_model_hash_cache.py docs/tracked-issues.md
git commit -m "$(cat <<'EOF'
docs: note UI metadata cache follow-ups

Cover settings round-trip for process.model_hash_table and point at the
2026-08-05 metadata cache plan.
EOF
)"
```

---

## Out of scope (do not implement in this plan)

- Sidecar `.uvr-hash.json` next to checkpoints.
- Background-thread hashing beyond F1 idle deferral.
- Storing model selection as MD5 in settings.
- Third generic `eligibility_tags` helper until another menu needs it.

## Spec coverage checklist

| Spec item | Task |
|---|---|
| A. Karaoke session cache | Task 1 |
| B. Durable hash + mtime guard | Tasks 2–3, 5 |
| C. `format_tag_title` memo | Task 4 |
| D. Ensemble via existing stem_check | no code (documented non-goal / reuse) |
| Invalidation with `invalidate_stem_check` / `clear_display_cache` | Tasks 1, 4 |
| Tests without live catalogue HTTP | Tasks 1, 4 env/patches |

## Placeholder scan

No TBD / “add tests later” / “similar to Task N” without inlined code.
