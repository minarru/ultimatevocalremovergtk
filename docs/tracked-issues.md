# Tracked issues backlog

Fork-specific tracking for **upstream-applicable** bugs (shared `core/`, `engines/`, `ml/`, `vendor/`) and **product gaps** called out in upstream demand. These are not duplicates of every open upstream GitHub thread — they are the items we actively watch or plan to address on [GitHub Issues](https://github.com/minarru/ultimatevocalremovergtk/issues).

**How to use this file**

1. Before filing a bug, search [GitHub issues](https://github.com/minarru/ultimatevocalremovergtk/issues) and this list.
2. When work starts, open a GitHub issue and put its number in the **Fork** column below (or replace an archived Codeberg link).
3. Update **Status** as work progresses: `open` → `in progress` → `done` / `wontfix`.

Suggested labels: `backend`, `gpu`, `roformer`, `audio`, `roadmap`, `upstream-parity`.

The **Fork** column may still link to historical Codeberg issues from before the host cutover; those IDs are archival only.

---

## Backend / ML (items 1–7)

| ID | Topic | Status | Priority | Upstream | Fork | Notes |
|----|--------|--------|----------|----------|------|-------|
| **1** | PyTorch `weights_only` / `UnpicklingError` | done | **high** | [#2290](https://github.com/Anjok07/ultimatevocalremovergui/issues/2290), [#1910](https://github.com/Anjok07/ultimatevocalremovergui/issues/1910), [#2262](https://github.com/Anjok07/ultimatevocalremovergui/issues/2262) | [#1](https://codeberg.org/jawlet/ultimatevocalremovergtk/issues/1) | Fixed via [core/torch_checkpoint.py](../core/torch_checkpoint.py) (`weights_only=False` on PyTorch 2.6+, with a TypeError fallback for older builds). Demucs, VR, MDX, Apollo, and `vendor/demucs/states.py` all load through `load_torch_checkpoint`; no bare `torch.load` remains on those paths. Covered by [tests/test_torch_checkpoint.py](../tests/test_torch_checkpoint.py). |
| **2** | RTX 50-series / new NVIDIA GPUs | open | high | [#1812](https://github.com/Anjok07/ultimatevocalremovergui/issues/1812), [#1752](https://github.com/Anjok07/ultimatevocalremovergui/issues/1752), [#1889](https://github.com/Anjok07/ultimatevocalremovergui/issues/1889), [#1900](https://github.com/Anjok07/ultimatevocalremovergui/issues/1900) | [#2](https://codeberg.org/jawlet/ultimatevocalremovergtk/issues/2) | CUDA 12.9 / driver 576.x / Blackwell-class hangs and slow runs. `core/cuda_runtime_fix.py` helps ORT find CUDA libs; torch/onnx wheel compatibility still environment-dependent. |
| **3** | MDX-Net not using GPU on Linux | open | medium | [#500](https://github.com/Anjok07/ultimatevocalremovergui/issues/500), [#1204](https://github.com/Anjok07/ultimatevocalremovergui/issues/1204), [#880](https://github.com/Anjok07/ultimatevocalremovergui/issues/880) | [#3](https://codeberg.org/jawlet/ultimatevocalremovergtk/issues/3) | MDX uses **ONNX Runtime**; GPU needs `onnxruntime-gpu` via `./install_packages.sh --cuda`. VR/Demucs use PyTorch GPU separately. Track docs + verify ORT actually selects CUDA. |
| **4** | librosa API breakage | open | medium | [#2226](https://github.com/Anjok07/ultimatevocalremovergui/issues/2226) | [#4](https://codeberg.org/jawlet/ultimatevocalremovergtk/issues/4) | Venv pins `librosa==0.11.0` in `requirements.txt`. Risk if system librosa is mixed in or venv is upgraded ad hoc. Heavy use in `engines/vr.py`, `ml/spec_utils.py`. |
| **5** | High-pitched / wrong-speed output (Linux) | open | medium | [#715](https://github.com/Anjok07/ultimatevocalremovergui/issues/715), [#926](https://github.com/Anjok07/ultimatevocalremovergui/issues/926) | [#5](https://codeberg.org/jawlet/ultimatevocalremovergtk/issues/5) | Sample-rate / resampling class of bugs; same audio pipeline as upstream, not GTK-specific. Needs repro on fork with file format + model combo. |
| **6** | Roformer / BS-Roformer errors | open | high | [#2255](https://github.com/Anjok07/ultimatevocalremovergui/issues/2255), [#2148](https://github.com/Anjok07/ultimatevocalremovergui/issues/2148), [#2062](https://github.com/Anjok07/ultimatevocalremovergui/issues/2062) | [#6](https://codeberg.org/jawlet/ultimatevocalremovergtk/issues/6) | Fork **ships** roformer support; these are direct bug reports (config, checkpoint load, denoise models), not missing features. Checkpoint `weights_only` side is covered by item **1** (`done`); remaining reports are model/config specific. |
| **7** | GPU OOM / wrong device / suspend | open | medium | [#1676](https://github.com/Anjok07/ultimatevocalremovergui/issues/1676), [#1119](https://github.com/Anjok07/ultimatevocalremovergui/issues/1119), [#2243](https://github.com/Anjok07/ultimatevocalremovergui/issues/2243) | [#7](https://codeberg.org/jawlet/ultimatevocalremovergtk/issues/7) | Shared inference and device selection. `core/gpu_backend.py` and cleanup paths may differ from upstream but same user-facing failure modes. |

### Acceptance hints (for Codeberg issues)

**1 — weights_only:** Met (`done`). Trusted loads go through `load_torch_checkpoint` with `weights_only=False` on PyTorch 2.6+.

**2 — RTX 50-series:** Document tested driver/CUDA/torch/onnxruntime matrix; no indefinite hang on stop; basic separation completes on reported hardware.

**3 — MDX GPU:** With `--cuda`, log or UI shows ONNX using CUDA execution provider; README troubleshooting covers CPU-only MDX.

**4 — librosa:** `./install_packages.sh` venv is self-contained; clear error if wrong librosa version is detected.

**5 — high pitch:** Repro case documented; fix verified on Linux with same input that fails upstream.

**6 — roformer:** Named model + settings repro; ensemble path included where relevant.

**7 — GPU OOM:** Graceful error or guidance; device selection respects user GPU choice; no leak across repeated runs.

---

## Fork-only technical debt (items F1–)

Deferred issues found in fork-specific (`ui/`) code during our own review, with
no upstream Tkinter equivalent -- so no GitHub issue to link.

| ID | Topic | Status | Priority | Upstream | Fork | Notes |
|----|--------|--------|----------|----------|------|-------|
| **F1** | Model-options sheet auto-expand hashes checkpoints synchronously | done | medium | n/a — fork-only (feature not in upstream) | — | Fixed: `_sync_expander_summaries` / vocal-split restore set a defer flag so `notify::expanded` schedules populate via `idle_on_main` ([ui/views/base.py](../ui/views/base.py), [ui/widgets/vocal_split_row.py](../ui/widgets/vocal_split_row.py)). Visual expand stays synchronous; hashing runs after first paint. Covered by [tests/test_defer_combo_populate.py](../tests/test_defer_combo_populate.py). |
| **F2** | `parent_window_width` calls a GTK3 method that does not exist in GTK4 | done | medium | n/a — fork-only (helper has no upstream equivalent) | — | Fixed in [ui/dialogs/utils.py](../ui/dialogs/utils.py): unrealized parents use `get_default_size()[0]`, falling back to the caller default when that returns 0. (`hasattr(Gtk.Window, "get_default_width")` is still `False` on GTK4.) Unrealized-parent path covered by [tests/test_errorlog.py](../tests/test_errorlog.py). |
| **F3** | Repeated model-list metadata work | done | medium | n/a — fork-only (feature not in upstream) | — | Closed by the [UI metadata cache plan](superpowers/plans/2026-08-05-ui-metadata-cache.md): karaoke/BV eligibility is cached per tag set, checkpoint hashes persist as mtime/size-guarded settings entries, and `format_tag_title` is memoized per display generation. |

---

## Product gaps (roadmap)

| ID | Topic | Status | Priority | Upstream | Fork | Notes |
|----|--------|--------|----------|----------|------|-------|
| **P1** | CLI / headless batch automation | done | medium | [#678](https://github.com/Anjok07/ultimatevocalremovergui/issues/678), [#359](https://github.com/Anjok07/ultimatevocalremovergui/issues/359), [#1288](https://github.com/Anjok07/ultimatevocalremovergui/issues/1288) | [#8](https://codeberg.org/jawlet/ultimatevocalremovergtk/issues/8) | Shipped as `python -m core.cli separate` / `bench-ab` ([core/cli.py](../core/cli.py)). Further CLI polish is ordinary feature work, not a missing-roadmap gap. |
| **P2** | Flatpak distribution | open | low | [#854](https://github.com/Anjok07/ultimatevocalremovergui/issues/854) | [#9](https://codeberg.org/jawlet/ultimatevocalremovergtk/issues/9) | Skeleton manifest: `packaging/org.uvr.UltimateVocalRemover.yaml`. Not published to Flathub or GitHub releases as Flatpak yet. |
| **P3** | Linux update UX | partial | low | [#707](https://github.com/Anjok07/ultimatevocalremovergui/issues/707) | [#10](https://codeberg.org/jawlet/ultimatevocalremovergtk/issues/10) | Fork uses `release.json` + source upgrade (README **Upgrading**), not upstream patch zips. Remaining gap: packaged install paths (e.g. Flatpak) if we ship them later. |

---

## Explicitly out of scope (do not mirror)

| Theme | Examples | Why |
|--------|-----------|-----|
| macOS / MPS | #888, #877, #863 | Linux GTK port only |
| Windows-only | DirectML, Intel ARC installer #2096 | Gated or N/A on Linux |
| Tk / splash / OpenGL | #756, #527 | No Tkinter in fork |
| Upstream `.exe` / `.dmg` installers | various | Source + `run_uvr.sh` |
| Meta / support noise | #1312 | Not a bug |

---

## Already better in the fork (reference)

| Upstream | Fork status |
|----------|-------------|
| #2108, #765, #2107 — old deps / Python install | Modern `requirements.txt`, `install_packages.sh`, Python 3.13+ |
| #383, #855, #1674 — Linux how-to | README + upgrade docs |
| #1702 — Linux roformer | Supported |
| #1242 — license clarity | Root `LICENSE` added |

---

## UI performance follow-ups (from the 2026-08-04 startup/console pass)

Originally deferred during [docs/superpowers/plans/2026-08-04-ui-performance.md](superpowers/plans/2026-08-04-ui-performance.md); closed in the 2026-08-05 follow-up pass unless noted.

| Item | Where | Status |
|------|-------|--------|
| Cross-thread `clear_display_cache()` / in-flight `lru_cache` miss | [core/model_display.py](../core/model_display.py) | **done** — generation-keyed `_merged_for_display_at` |
| `clear_mvsepless_cache` / `clear_extra_catalog_cache` skip merge invalidation | mvsepless / extra catalog | **done** — both call `clear_display_cache()` |
| Refresh clears merge even when payload unchanged | politrees / mvsepless | **done** — clear only when `data != previous` |
| Startup win conditional on in-TTL disk cache | both catalogue modules | **done** — stale-while-revalidate: any readable disk entry served immediately; BG refresh when expired |
| No `Gtk.ListBox.set_sort_func` wiring test | [ui/download_center.py](../ui/download_center.py) | **done** — [tests/test_download_center_sort.py](../tests/test_download_center_sort.py) |
| No test for two unmapped appends → one map handler | [ui/widgets/console.py](../ui/widgets/console.py) | **done** — [tests/test_console_scroll.py](../tests/test_console_scroll.py) |
| No test for `reload_mappers` display-cache hook | [core/model_data.py](../core/model_data.py) | **done** — [tests/test_model_display_cache.py](../tests/test_model_display_cache.py) |
| Unsupported rows sort via `canonical_display_name` | [ui/download_center.py](../ui/download_center.py) | **done** (shipped in PR #13; behavioural note only) |
| One idle per unmapped `append` while parked on map | [ui/widgets/console.py](../ui/widgets/console.py) | **done** — early-out on `_map_handler_id` |
| `.desktop` / `run_uvr.sh` GTK health-probe tax | [run_uvr.sh](../run_uvr.sh) | **done** — cheap `-x` by default; full probe on stamp miss/stale, rebuild, or `UVR_FORCE_VENV_CHECK`; desktop entry `--update` from installer |

---

## FAQ / support threads (link only, not tracked)

- **#344, #206, #469** — model/settings recommendations  
- **#593** — renamed / VIP model names  
- **#541, #1066** — models missing from Download Center (catalogue / naming)  
- **#1647** — manual model download (supported in fork)

---

*Last reviewed: 2026-08-05 — UI performance follow-ups + F1 closed (generation cache, SWR, run_uvr stamp, deferred combo populate).*
