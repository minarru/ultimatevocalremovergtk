# Progress reporting

How separation and Audio Tools drive the log-panel progress bar.

Dispatch and GTK backlog issues use `latest_main_thread` in [ui/dispatch.py](../../../ui/dispatch.py). This page is about **engine/tool ticks** and the live ETA.

## Pipeline

```
engine / tool
  set_progress_bar(step, inference_iterations=0)
    JobRunner / AudioToolRunner  →  fraction in [0, 1]
      JobCallbacks.progress(...)
        gtk_job_callbacks  (latest-value idle)
          RunControl._on_progress
            LogPanel.set_progress_fraction / set_progress_text
```

Hops fill **10% → 80%**. Extra work in the same pass (match-mix, Denoise Model) continues through **80% → 89%** via [core/progress_ticks.py](../../../core/progress_ticks.py) so the bar never rewinds and stays under the 0.90 save cutoff. `JobRunner` maps that onto a slice of the global bar using `true_model_count` × long-file chunks.

Save uses `save_progress_local_step` (0.90–0.96). The UI paints those ticks instead of holding the last inference fill. Load with no prior fill still pulses.

ETA remaining time is `t * (1 - p) / p` after about **2 seconds** of inference-only elapsed (`ProgressEtaTracker` in [core/run_estimate.py](../../../core/run_estimate.py)). The infer clock pauses during save.

## What ticks during inference

| Path | Ticks | Where |
|------|--------|--------|
| VR | Per patch batch | `SeperateVR.inference_vr` |
| Classic MDX (ONNX / Conv-TDF) | Per hop (×2 when Standard denoise) | `SeperateMDX.demix` → `running_inference_progress_bar` |
| MDX23C (TFC-TDF, not Roformer) | Per hop chunk | `SeperateMDXC.demix` |
| Roformer / SCNet / Bandit | Per window | `SeperateMDXC.demix_roformer` |
| Denoise Model (`UVR-DeNoise-Lite`) | Per patch batch | `vr_denoiser` via `denoise_progress_callback` |
| Match frequency / invert-spec | Per hop (continues the counter) | `demix(..., is_match_mix=True)` |
| Demucs v1–v4 with **Split** on | Per chunk × shifts × bag | `vendor/demucs/apply.py` / `utils.py` |
| Demucs Split off | Start + end of the one forward | Non-split leaf in `apply.py` / `utils.py` |
| Ensemble members | As above per member | then combine ticks in `JobRunner` |
| Apollo restore (Audio Tools) | Per chunk | `ml/apollo_inference.py` |
| Align inputs | During alignment | `ml/spec_utils.align_audio` |
| Matchering | Pair start + pair complete | `AudioToolRunner._run_dual` |
| Pitch / time stretch | File start + file complete | `AudioToolRunner._run_pitch_time` |
| Manual ensemble | Load / combine / write | `ensemble_inputs` / `combine_audio` |

## Honesty vs cost hints

`cost_factor_hints` / `compute_run_cost_units` treat **Denoise Model** as extra cost on MDX/ensemble. **Standard** denoise is counted only for classic MDX when the resolved model is not MDX-C/Roformer. Unresolved architecture still shows the hint (ensemble without a member list).

Roformer Denoise Model is still not wired (the option does not run). That is a behavior gap, not a progress freeze.

## Related

- [tracked-issues.md](../../tracked-issues.md) **F24** — closed by this work.
