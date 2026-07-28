# Tracked issues backlog

Fork-specific tracking for **upstream-applicable** bugs (shared `core/`, `engines/`, `ml/`, `vendor/`) and **product gaps** called out in upstream demand. These are not duplicates of every open GitHub thread — they are the items we actively watch or plan to address on [Codeberg](https://codeberg.org/jawlet/ultimatevocalremovergtk/issues).

**How to use this file**

1. Before filing a bug, search [Codeberg issues](https://codeberg.org/jawlet/ultimatevocalremovergtk/issues) and this list.
2. When work starts, open a Codeberg issue and put its number in the **Fork** column below.
3. Update **Status** as work progresses: `open` → `in progress` → `done` / `wontfix`.

Suggested labels on Codeberg: `backend`, `gpu`, `roformer`, `audio`, `roadmap`, `upstream-parity`.

---

## Backend / ML (items 1–7)

| ID | Topic | Status | Priority | Upstream | Fork | Notes |
|----|--------|--------|----------|----------|------|-------|
| **1** | PyTorch `weights_only` / `UnpicklingError` | open | **high** | [#2290](https://github.com/Anjok07/ultimatevocalremovergui/issues/2290), [#1910](https://github.com/Anjok07/ultimatevocalremovergui/issues/1910), [#2262](https://github.com/Anjok07/ultimatevocalremovergui/issues/2262) | [#1](https://codeberg.org/jawlet/ultimatevocalremovergtk/issues/1) | PyTorch ≥2.6 defaults `weights_only=True`. Bare `torch.load` in `engines/demucs_engine.py`, `engines/vr.py`, `engines/mdx.py`, `engines/vr_utils.py`, `ml/mdxnet.py`, `ml/apollo_model_data/base_model.py`, `vendor/demucs/states.py`. **No `weights_only` handling in tree yet.** |
| **2** | RTX 50-series / new NVIDIA GPUs | open | high | [#1812](https://github.com/Anjok07/ultimatevocalremovergui/issues/1812), [#1752](https://github.com/Anjok07/ultimatevocalremovergui/issues/1752), [#1889](https://github.com/Anjok07/ultimatevocalremovergui/issues/1889), [#1900](https://github.com/Anjok07/ultimatevocalremovergui/issues/1900) | [#2](https://codeberg.org/jawlet/ultimatevocalremovergtk/issues/2) | CUDA 12.9 / driver 576.x / Blackwell-class hangs and slow runs. `core/cuda_runtime_fix.py` helps ORT find CUDA libs; torch/onnx wheel compatibility still environment-dependent. |
| **3** | MDX-Net not using GPU on Linux | open | medium | [#500](https://github.com/Anjok07/ultimatevocalremovergui/issues/500), [#1204](https://github.com/Anjok07/ultimatevocalremovergui/issues/1204), [#880](https://github.com/Anjok07/ultimatevocalremovergui/issues/880) | [#3](https://codeberg.org/jawlet/ultimatevocalremovergtk/issues/3) | MDX uses **ONNX Runtime**; GPU needs `onnxruntime-gpu` via `./install_packages.sh --cuda`. VR/Demucs use PyTorch GPU separately. Track docs + verify ORT actually selects CUDA. |
| **4** | librosa API breakage | open | medium | [#2226](https://github.com/Anjok07/ultimatevocalremovergui/issues/2226) | [#4](https://codeberg.org/jawlet/ultimatevocalremovergtk/issues/4) | Venv pins `librosa==0.11.0` in `requirements.txt`. Risk if system librosa is mixed in or venv is upgraded ad hoc. Heavy use in `engines/vr.py`, `ml/spec_utils.py`. |
| **5** | High-pitched / wrong-speed output (Linux) | open | medium | [#715](https://github.com/Anjok07/ultimatevocalremovergui/issues/715), [#926](https://github.com/Anjok07/ultimatevocalremovergui/issues/926) | [#5](https://codeberg.org/jawlet/ultimatevocalremovergtk/issues/5) | Sample-rate / resampling class of bugs; same audio pipeline as upstream, not GTK-specific. Needs repro on fork with file format + model combo. |
| **6** | Roformer / BS-Roformer errors | open | high | [#2255](https://github.com/Anjok07/ultimatevocalremovergui/issues/2255), [#2148](https://github.com/Anjok07/ultimatevocalremovergui/issues/2148), [#2062](https://github.com/Anjok07/ultimatevocalremovergui/issues/2062) | [#6](https://codeberg.org/jawlet/ultimatevocalremovergtk/issues/6) | Fork **ships** roformer support; these are direct bug reports (config, checkpoint load, denoise models), not missing features. Overlaps with item **1** for checkpoint loading. |
| **7** | GPU OOM / wrong device / suspend | open | medium | [#1676](https://github.com/Anjok07/ultimatevocalremovergui/issues/1676), [#1119](https://github.com/Anjok07/ultimatevocalremovergui/issues/1119), [#2243](https://github.com/Anjok07/ultimatevocalremovergui/issues/2243) | [#7](https://codeberg.org/jawlet/ultimatevocalremovergtk/issues/7) | Shared inference and device selection. `core/gpu_backend.py` and cleanup paths may differ from upstream but same user-facing failure modes. |

### Acceptance hints (for Codeberg issues)

**1 — weights_only:** All trusted checkpoint loads pass `weights_only=False` (or equivalent safe globals) on PyTorch 2.6+; Demucs, VR, MDX, Apollo, and roformer smoke tests pass.

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
| **F1** | Model-options sheet auto-expand hashes checkpoints synchronously | open | medium | n/a — fork-only (feature not in upstream) | — | `ui/views/base.py`'s `load()` (via `_sync_expander_summaries`) calls `Adw.ExpanderRow.set_expanded(True)` for every section whose activate switch was already on, to restore the user's last session. `set_expanded(True)` synchronously emits `notify::expanded`, which is bound to `_ensure_model_combos_populated` in `ui/views/base.py` and `_populate_models` in `ui/widgets/vocal_split_row.py` — both deliberately lazy (they hash every installed checkpoint) per the CLAUDE.md "heavy work stays lazy" invariant. Measured: `MainWindow()` construction goes from 94ms (no sections enabled) to 635ms (6.8x) with every auto-expanding section enabled, all synchronous on the main loop during window build. Found during the `model-options-sheet` branch's final review; deliberately not fixed there to avoid late churn. Suggested fix: when the expand happens during `load()`, defer the populate call via `idle_on_main` (`ui/dispatch.py`) instead of running it inline — the row still opens immediately (visual auto-expand preserved), but the hashing moves off the synchronous construction path. |
| **F2** | `parent_window_width` calls a GTK3 method that does not exist in GTK4 | open | medium | n/a — fork-only (helper has no upstream equivalent) | — | `ui/dialogs/utils.py:80` calls `parent.get_default_width()`. That method does not exist on `Gtk.Window` in GTK4 — the replacement is `get_default_size()`, which returns a `(width, height)` tuple. Verified: `hasattr(Gtk.Window, "get_default_width")` is `False`, `hasattr(Gtk.Window, "get_default_size")` is `True`. The line is only reached when `parent.get_width() <= 1`, i.e. an unrealized or not-yet-mapped parent window, so it raises `AttributeError` rather than mis-sizing. Live callers: `ui/errorlog.py:135` and `ui/download.py:409,490` (the latter two via `configure_dialog_width`). The `model-options-sheet` branch removed the model-options sheet's two call sites as a side effect of dropping parent-width tracking, but did not fix the helper. Suggested fix: use `get_default_size()[0]` and fall back to the caller's supplied default when it returns 0. Needs its own change with a test that exercises the unrealized-parent path, since no current test reaches it. |

---

## Product gaps (roadmap)

| ID | Topic | Status | Priority | Upstream | Fork | Notes |
|----|--------|--------|----------|----------|------|-------|
| **P1** | CLI / headless batch automation | open | medium | [#678](https://github.com/Anjok07/ultimatevocalremovergui/issues/678), [#359](https://github.com/Anjok07/ultimatevocalremovergui/issues/359), [#1288](https://github.com/Anjok07/ultimatevocalremovergui/issues/1288) | [#8](https://codeberg.org/jawlet/ultimatevocalremovergtk/issues/8) | No CLI in fork today. Valid roadmap item if users want scripted runs without GTK. |
| **P2** | Flatpak distribution | open | low | [#854](https://github.com/Anjok07/ultimatevocalremovergui/issues/854) | [#9](https://codeberg.org/jawlet/ultimatevocalremovergtk/issues/9) | Skeleton manifest: `packaging/org.uvr.UltimateVocalRemover.yaml`. Not published to Flathub or Codeberg releases as Flatpak yet. |
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

## FAQ / support threads (link only, not tracked)

- **#344, #206, #469** — model/settings recommendations  
- **#593** — renamed / VIP model names  
- **#541, #1066** — models missing from Download Center (catalogue / naming)  
- **#1647** — manual model download (supported in fork)

---

*Last reviewed: 2026-07-05 — upstream sample ~v5.6 base, fork v1.0.0.*
