"""GTK tooltip copy for the UVR interface.

Strings here are passed verbatim to :func:`ui.hints.set_tooltip` — edit them
in final display form; there is no runtime normalization layer.

Style guide
-----------
* Do not end a line with a full stop (``.``), except inside quoted phrases
  (e.g. ``"Download Center."``) or abbreviations (``e.g.``, ``i.e.``, ``etc.``).
* Use ``•`` for top-level bullets and two spaces plus ``-`` for sub-bullets.
* Separate sections with a single blank line; avoid trailing blank lines.
* Plain text only — GTK tooltips do not render Markdown (no ``**bold**``).
* Prefer single-line strings for short prose — GTK wraps at the tooltip width
* Keep tooltips at or below 240 characters, except ensemble algorithm
  reference lists (``ENSEMBLE_TYPE_HELP``)
* Use ``\\n\\n`` only between distinct sections (title and body, notes, bullet lists)
* Do not embed mid-sentence line breaks in source; each forced ``\\n`` becomes a hard wrap

See :func:`validate_help_text` and ``tests/test_help_text.py``.
"""

from __future__ import annotations

import re
import sys
from typing import Dict, Iterator, List

# Abbreviations / phrases that may end with a period mid-line.
_ALLOWED_PERIOD_SUFFIXES = ("etc.", "e.g.", "i.e.", "vs.", "U.S.")
MAX_HELP_TEXT_CHARS = 240
_LENGTH_EXEMPT_NAMES = frozenset({"ENSEMBLE_TYPE_HELP"})


def validate_help_text(text: str, *, name: str = "") -> List[str]:
    """Return style violations for tooltip copy (empty list means OK)."""
    issues: List[str] = []
    prefix = f"{name}: " if name else ""
    if not text:
        issues.append(f"{prefix}empty tooltip text")
        return issues
    if name not in _LENGTH_EXEMPT_NAMES and len(text) > MAX_HELP_TEXT_CHARS:
        issues.append(
            f"{prefix}{len(text)} characters exceeds the {MAX_HELP_TEXT_CHARS}-character limit"
        )
    if text != text.strip():
        issues.append(f"{prefix}leading or trailing whitespace on the full string")
    if text.startswith("**") or "***" in text:
        issues.append(f"{prefix}markdown emphasis is not rendered in GTK tooltips")
    lines = text.splitlines()
    if lines and lines[-1] == "":
        issues.append(f"{prefix}trailing blank line")
    for index, raw_line in enumerate(lines, start=1):
        line = raw_line.rstrip()
        if not line.strip():
            if index < len(lines) and lines[index] == "":
                issues.append(f"{prefix}line {index}: consecutive blank lines")
            continue
        if raw_line != raw_line.lstrip() and not raw_line.startswith("  "):
            issues.append(f"{prefix}line {index}: use two spaces before sub-bullets, not other indentation")
        if "\t" in raw_line or raw_line.startswith("\t"):
            issues.append(f"{prefix}line {index}: use spaces, not tabs")
        if line.endswith(".") and not line.endswith("..."):
            if not any(line.endswith(suffix) for suffix in _ALLOWED_PERIOD_SUFFIXES):
                if not re.search(r'["\']\.["\']\s*$', line):
                    issues.append(f"{prefix}line {index}: trailing period")
    return issues


def iter_help_strings() -> Iterator[tuple[str, str]]:
    """Yield ``(name, text)`` for every module-level tooltip constant."""
    import ui.help_text as mod

    names = [n for n in dir(mod) if n.isupper() and (n.endswith("_HELP") or n.endswith("_HINT"))]
    for name in sorted(names):
        value = getattr(mod, name)
        if isinstance(value, str):
            yield name, value
        elif isinstance(value, dict):
            for key, item in value.items():
                if isinstance(item, str):
                    yield f"{name}[{key!r}]", item


# --- Shared hints (including compatibility names from the former Tk UI) ---

STOP_HELP = "Stop the current task after confirmation"

SETTINGS_HELP = "Open Preferences or the Download Center"

COMMAND_TEXT_HELP = "Processing log with status, progress, warnings, and errors"

PITCH_SHIFT_HELP = (
    "Shift pitch in semitones: positive values raise pitch and negative values lower it. "
    "Enable Time correction to preserve duration"
)

AGGRESSION_SETTING_HELP = (
    "Controls extraction strength from 0 to 50. Higher values extract more "
    "aggressively and may muddy non-vocal stems; 5 is the usual starting point"
)

WINDOW_SIZE_HELP = (
    "Balance speed and detail: 1024 is fastest, 512 is balanced, and 320 is "
    "slowest but may preserve more detail"
)

MDX_SEGMENT_SIZE_HELP = (
    "Segment size balances memory use and quality. Classic MDX-Net defaults to "
    "256; MDX-C models can use Default to read the YAML configuration"
)

DEMUCS_STEMS_HELP = "Choose a Demucs stem focus or export every native stem"

SEGMENT_HELP = (
    "Demucs segment length. Smaller values use less memory; larger values may "
    "improve quality but use more memory. Default lets the model choose"
)

ENSEMBLE_MAIN_STEM_HELP = (
    "Choose compatible stem outputs to combine. No X means mixture minus X; "
    "the lead-vocal pair keeps backing vocals in its instrumental side. "
    "4-stem and multi-stem modes combine each matching native stem"
)

ENSEMBLE_TYPE_HELP = """How member outputs are combined

Dual-stem ensembles use a Primary and a Secondary algorithm (saved as Primary/Secondary). 4-stem and multi-stem ensembles use one algorithm for every stem

• Max Spec — strongest magnitude per bin (fuller; can add artifacts)
• Min Spec — weakest magnitude per bin (cleaner; can sound muddy)
• Average — mean of member waveforms
• Median Spec — per-bin median of complex spectrograms (robust with 3+ models)
• Soft Spec — softmax blend with automatic magnitude-agreement weights
• Max Mag / Avg Phase — Max Spec magnitudes with a stable average phase
• Hybrid Spec — average of Max Spec and Min Spec
• Chunk Min — time-domain: quietest chunk from any member

Default dual-stem pair is Max Spec / Min Spec"""

ENSEMBLE_LISTBOX_HELP = "List models compatible with the chosen main stem pair"

IS_TIME_CORRECTION_HELP = "Preserve the input duration while shifting pitch"

SAVE_STEM_ONLY_HELP = (
    "Choose outputs to write. Choices depend on the selected model or ensemble stem pair"
)

RUN_WORKLOAD_HINT = (
    "Relative workload: passes = inferences, outputs = files written, "
    "Fastest/Typical/Slower = export and run cost. Cost factors name heavy "
    "settings such as TTA, shifts, or high overlap"
)

PROGRESS_ETA_HINT = (
    "The bar pulses while loading, then fills during inference, save, and "
    "deverb. Ensemble combine shows Combining i/n. Time left appears a couple "
    "of seconds after inference starts and pauses outside inference"
)

IS_NORMALIZATION_HELP = "Scale peaks above 1.0 down to prevent clipping"

IS_MATCH_MIX_LEVEL_HELP = (
    "Apply one shared gain so two or more exported stems sum to the input mix "
    "level without changing their relative balance"
)

IS_PREVENT_EXPORT_CLIPPING_HELP = (
    "Scale PCM, FLAC, and MP3 exports to fit their range. Multi-stem exports "
    "share one gain to preserve balance. Skipped for 32-bit and 64-bit float WAV"
)

AMPLIFICATION_THRESHOLD_HELP = (
    "Raise quiet outputs to the selected peak level from 0 to 1. Set 0 to "
    "disable. This applies after peak reduction and independently of Normalize output"
)

LONG_FILE_CHUNK_HELP = (
    "Split long inputs into overlapping time slices before separation. Set 0 "
    "to disable; 600 gives 10-minute slices. This is separate from model segment size"
)

LONG_FILE_CHUNK_OVERLAP_HELP = (
    "Crossfade length between long-file slices. Longer overlaps can smooth "
    "boundaries; the value is kept below half the chunk duration"
)

IS_CUDA_SELECT_HELP = "Choose which detected GPU to use for processing"

CROP_SIZE_HELP = (
    "Legacy VR crop-size setting retained for saved-profile compatibility; "
    "current VR inference does not use it"
)

IS_TTA_HELP = (
    "Run test-time augmentation and average the predictions. This may improve "
    "separation quality but increases processing time"
)

IS_POST_PROCESS_HELP = (
    "Try to remove residual instrumental artifacts from vocal outputs. Results "
    "vary by track and may sound worse, so use this as a last resort"
)

IS_HIGH_END_PROCESS_HELP = "Mirror the output's missing high-frequency range"

SHIFTS_HELP = (
    "Average predictions from randomly shifted inputs. More shifts may improve "
    "quality but increase processing time, especially on CPU"
)

OVERLAP_HELP = (
    "Overlap between Demucs prediction windows. Higher values may improve joins "
    "but increase runtime; choices are 0.25, 0.50, 0.75, and 0.99"
)

MDX_OVERLAP_HELP = (
    "Overlap between prediction windows. Classic MDX-Net offers Default, 0.25, "
    "0.50, 0.75, or 0.99; MDX-C models use values from 2 to 50"
)

OVERLAP_23_HELP = (
    "Overlap between MDX-C prediction windows. Higher values may improve joins "
    "but increase runtime and memory use"
)

IS_SEGMENT_DEFAULT_HELP = (
    "For MDX-C models, Default reads the segment size from the YAML configuration"
)

IS_SPLIT_MODE_HELP = (
    "Process the track in segments to reduce memory use. Demucs v4 always "
    "enables this; the switch affects older Demucs models only"
)

IS_DEMUCS_COMBINE_STEMS_HELP = (
    "Create the complement by adding the remaining native stems instead of "
    "subtracting the primary stem from the mixture"
)

COMPENSATE_HELP = (
    "Classic MDX-Net only: scale the primary output before deriving its complement"
)

IS_DENOISE_HELP = (
    "Standard averages positive and negative classic MDX-Net predictions. "
    "Denoise Model runs UVR-DeNoise-Lite on supported vocal outputs. Both add processing time"
)

VOC_SPLIT_MODEL_SELECT_HELP = (
    "Choose the lead/backing-vocal model used to process generated vocal stems"
)

IS_VOC_SPLIT_INST_SAVE_SELECT_HELP = (
    "When the main instrumental is available, also save Instrumental with Lead "
    "Vocals and Instrumental with Backing Vocals; skipped for Vocals-only export"
)

IS_VOC_SPLIT_MODEL_SELECT_HELP = (
    "Split generated vocals into lead and backing vocals with the selected "
    "model. Adds two vocal outputs and another inference pass"
)

IS_DEVERB_OPT_HELP = "Choose which generated vocal stems are de-reverberated"

IS_DEVERB_VOC_HELP = (
    "Also save de-reverberated and reverb-only versions of selected vocal "
    "outputs. Requires UVR-DeEcho-DeReverb"
)

IS_FREQUENCY_MATCH_HELP = (
    "With pitch shift and Spectral inversion active for classic vocals/instrumental "
    "MDX-Net runs, align the mixture cutoff before deriving the complement; otherwise no effect"
)

CLEAR_CACHE_HELP = "Edit or delete saved defaults for a model"

IS_SAVE_ALL_OUTPUTS_ENSEMBLE_HELP = "Keep every member-model output after combining the ensemble"

IS_APPEND_ENSEMBLE_NAME_HELP = "Add the ensemble name to final output filenames"

IS_WAV_ENSEMBLE_HELP = (
    "Use waveform-domain Max Spec or Min Spec when supported. Spectral-only "
    "algorithms ignore this setting; Average and Chunk Min already use waveforms"
)

DONATE_HELP = "Open the official UVR donation page in the default browser"

IS_INVERT_SPEC_HELP = (
    "Derive the complement by subtracting spectrograms instead of waveforms. "
    "This is slower and may improve some outputs"
)

IS_TESTING_AUDIO_HELP = "Add a timestamp to output names to avoid overwrites"

IS_MODEL_TESTING_AUDIO_HELP = "Append the model name to output filenames so you can compare models"

IS_ACCEPT_ANY_INPUT_HELP = (
    "Allow files outside the supported audio extensions. Experimental; invalid "
    "or unreadable files can still fail verification"
)

DELETE_YOUR_SETTINGS_HELP = "Delete the selected saved profile after confirmation"

SET_STEM_NAME_HELP = "Primary stem this model produces"

IS_CREATE_MODEL_FOLDER_HELP = (
    "Write outputs into a model folder and a track folder under the export "
    "directory (export / <model> / <track> / file(s))"
)

MDX_DIM_T_SET_HELP = "Internal time-dimension setting — leave the default unless you know the training value"

MDX_DIM_F_SET_HELP = "Internal frequency-dimension setting — leave the default unless you know the training value"

MDX_N_FFT_SCALE_SET_HELP = "N_FFT size used when the model was trained — leave the default unless you know it"

POPUP_COMPENSATE_HELP = (
    "Select the appropriate volume compensation for the chosen model\n\n"
    f"Reminder: {COMPENSATE_HELP}"
)

VR_MODEL_PARAM_HELP = "Parameter file required to run this VR model"

CHOSEN_ENSEMBLE_HELP = (
    "Load a curated recipe or saved ensemble. Save and delete apply only to "
    "your presets; curated recipes are read-only"
)

CHOSEN_PROCESS_METHOD_HELP = (
    "Choose VR Architecture, MDX-Net, or Demucs for separation; Ensemble to "
    "combine models; or Audio Tools for alignment, restoration, and transforms"
)

INPUT_FOLDER_ENTRY_HELP = (
    "Choose audio files to process. Batches above 100 files may take a long "
    "time; at most 500 files are accepted"
)

OUTPUT_FOLDER_ENTRY_HELP = "Choose where processed files are saved"

INPUT_FOLDER_BUTTON_HELP = "Open the selected input file's folder"

OUTPUT_FOLDER_BUTTON_HELP = "Open the selected output folder"

CHOOSE_MODEL_HELP = "Choose an installed model for the selected processing method"

FORMAT_SETTING_HELP = "Choose the saved audio format"

SECONDARY_MODEL_ACTIVATE_HELP = (
    "Run the configured secondary model and blend its result with the primary model"
)

SECONDARY_MODEL_HELP = "Choose the secondary model for this stem pair"

INPUT_SEC_FIELDS_HELP = "Choose the paired primary and secondary inputs"

SECONDARY_MODEL_SCALE_HELP = (
    "Primary-model influence in the blend: 0.9 means 90% primary and 10% "
    "secondary; 0.5 gives both models equal weight"
)

PRE_PROC_MODEL_ACTIVATE_HELP = (
    "Run a VR or MDX vocal model first, then separate non-vocal stems from its "
    "instrumental output. Demucs only; may reduce vocal bleed but adds an inference pass"
)

PRE_PROC_MODEL_HELP = (
    "Choose the VR or MDX vocal model whose instrumental output is fed into "
    "Demucs when separating non-vocal stems"
)

AUDIO_TOOLS_HELP = (
    "Combine files, change speed or pitch, align paired tracks, match a target "
    "to a reference, or restore codec-damaged audio with Apollo"
)

APOLLO_CHUNK_SIZE_HELP = (
    "Processing chunk size. Smaller values use less memory; larger values may "
    "improve quality but use more memory. Default is 10"
)

APOLLO_OVERLAP_HELP = (
    "Overlap between Apollo prediction windows. Higher values may improve "
    "quality but increase runtime and memory use. Default is 5"
)

CHOOSE_APOLLO_MODEL_HELP = "Choose an installed Apollo restoration model"

ROFORMER_MODEL_HELP = (
    "Enable for BS-Roformer, Mel-Band Roformer, SCNet, or Bandit checkpoints so "
    "the engine uses the configured network instead of the standard TFC-TDF model"
)

PRE_PROC_MODEL_INST_MIX_HELP = (
    "Also save the mixture of remaining instrumental stems, excluding vocals "
    "and the selected focus stem"
)

MODEL_SAMPLE_MODE_HELP = (
    "Process only the beginning of each input. Set the clip duration in "
    "Preferences → Processing → Sample mode"
)

POST_PROCESS_THREASHOLD_HELP = (
    "Mask threshold used by Post-process. Lower values affect more time regions; "
    "higher values are more selective"
)

BATCH_SIZE_HELP = (
    "Number of segments processed per inference batch. Higher values use more "
    "memory and may run faster; output quality is unchanged. Roformer models use their YAML batch size"
)

VR_MODEL_NOUT_HELP = (
    "Internal VR 5.1 model width. Keep the detected value unless checkpoint "
    "documentation specifies another"
)

VR_MODEL_NOUT_LSTM_HELP = (
    "Internal VR 5.1 LSTM width. Keep the detected value unless checkpoint "
    "documentation specifies another"
)

IS_PHASE_HELP = "Choose the secondary input phase; Automatic is recommended"

IS_ALIGN_TRACK_HELP = "Save the aligned secondary track as an additional output"

IS_MATCH_SILENCE_HELP = (
    "Match the secondary input's leading silence to the primary input. Avoid "
    "this when the primary begins with vocals alone"
)

IS_MATCH_SPEC_HELP = (
    "Blend alignment candidates in the spectrogram domain. This may improve "
    "some pairs and increases processing work"
)

TIME_WINDOW_ALIGN_HELP = (
    "Window length used for fine alignment. Smaller windows and Shifts presets "
    "test more candidates and take longer; None disables fine time correction"
)

INTRO_ANALYSIS_ALIGN_HELP = (
    "Choose where to sample the track for initial alignment. Default samples "
    "at 10% of the duration; Shifts presets test several positions and take longer"
)

VOLUME_ANALYSIS_ALIGN_HELP = (
    "Search gain offsets for the secondary input. Higher presets search a wider "
    "or finer dB range and take longer; None keeps the original level"
)

PHASE_SHIFTS_ALIGN_HELP = (
    "Try multiple phase offsets for the secondary input during time-window "
    "alignment. More offsets take longer; Maximum tests all 360 positions"
)

if sys.platform == "darwin":
    IS_GPU_CONVERSION_HELP = (
        "Use Apple Metal (MPS) when available and fall back to CPU otherwise. "
        "GPU support varies by model architecture"
    )
else:
    IS_GPU_CONVERSION_HELP = (
        "Use an available GPU and fall back to CPU otherwise. CUDA supports "
        "NVIDIA GPUs; DirectML supports compatible Windows AMD/Intel PyTorch models"
    )

IS_AUTOCAST_HELP = (
    "Use CUDA FP16 for faster VR, MDX-Net, and Roformer inference. This has no "
    "effect on Demucs or CPU and may slightly affect quality; UVR_AUTOCAST overrides it"
)


# --- GTK shell ---

PROCESS_METHOD_HINT = """
Choose the separation architecture:

• VR Architecture — magnitude spectrogram source separation
• MDX-Net — spectrogram-based models, including MDX-C and Roformer
• Demucs v3/4 — hybrid waveform/spectrogram models with multi-stem support
""".strip()

VIEW_TAB_HINTS: Dict[str, str] = {
    "separation": (
        "Separate vocals, instrumentals, and other stems using VR, MDX-Net, or Demucs models"
    ),
    "ensemble": (
        "Combine outputs from multiple compatible models with selectable algorithms"
    ),
    "audio_tools": (
        "Time stretch, change pitch, align tracks, matchering, manual ensemble, and Apollo audio restoration"
    ),
}

OUTPUT_FORMAT_HINT = "Choose the audio format for saved output files (WAV, FLAC, or MP3)"

# --- Separation / method views ---

MDX_OVERLAP_HINT = (
    "Overlap between prediction windows. Classic MDX-Net offers Default, 0.25, "
    "0.50, 0.75, or 0.99; MDX-C models use values from 2 to 50"
)

MDX_SEGMENT_SIZE_HINT = (
    "Segment size balances memory use and quality. Classic MDX-Net uses 32 to "
    "4000; MDX-C models can use Default to read the YAML configuration"
)

MDX_STEMS_HINT = (
    "Choose native stems to export, or use the Instrumental and Vocals shortcuts. "
    "Include complement also writes No X for a single custom stem"
)

DEMUCS_STEMS_SAVE_HELP = (
    "Choose a stem focus and which files to write. All stems writes every native "
    "output; other focuses can write the stem, its complement, or both"
)

QUICK_EXPORT_INSTRUMENTAL_HINT = (
    "Export a single derived Instrumental file (mixture minus vocals)"
)

QUICK_EXPORT_VOCALS_HINT = (
    "Export a single native Vocals stem file"
)

SAVE_STEMS_NO_MODEL_HELP = "Choose a model to configure stem export"

MDX_INCLUDE_COMPLEMENT_HELP = (
    "When a single custom stem is selected, also write the derived No <stem> complement "
    "alongside the native stem file"
)

DEMUCS_CHUNK_HINT = "Process the audio in chunks to reduce memory usage (legacy option)"

# --- Ensemble page ---

ENSEMBLE_SAVED_PRESET_HINT = (
    "Load a curated recipe or saved ensemble. Save and delete apply only to "
    "your presets; curated recipes are read-only"
)
ENSEMBLE_SAVE_BUTTON_HINT = "Save current ensemble"
ENSEMBLE_DELETE_BUTTON_HINT = "Delete selected saved ensemble"

# --- Audio tools page ---

MANUAL_ENSEMBLE_ALGORITHM_HINT = (
    "Choose how files are combined. Average and Chunk Min always use waveforms; "
    "other methods use frequency bins unless waveform mode supports them. Combine Inputs adds tracks"
)
PLAYBACK_RATE_HINT = (
    "Playback rate multiplier: values below 1 slow the track down, values above 1 speed it up"
)
WAV_TYPE_HINT = "Bit depth / sample encoding used when saving WAV output"
FLAC_BIT_DEPTH_HINT = "Bit depth used when saving FLAC output (16-bit or 24-bit)"

# --- Main window chrome ---

MAIN_MENU_HINT = "Main menu"
VIEW_INPUTS_BUTTON_HINT = "Review and verify inputs"
MODEL_OPTIONS_BUTTON_HINT = "Open inference, extra-model, and model-maintenance options"
MODEL_OPTIONS_ROW_HINT = "Open inference, extra-model, and model-maintenance options for each architecture"
ENSEMBLE_MEMBER_MODEL_OPTIONS_HINT = (
    "Adjust architecture-level inference and extra-model options used by selected ensemble members"
)

# --- Preferences / download / inputs ---

REMOVE_PROFILE_HINT = "Remove profile"
VIP_DOWNLOAD_CODE_HINT = "Enter VIP download code"
ADD_INPUT_FILES_HINT = "Add input files"
CLEAR_ALL_INPUTS_HINT = "Clear all inputs"
REMOVE_INPUT_HINT = "Remove this input"
CLEAR_INPUT_FILES_HINT = "Clear all input files"
SELECT_INPUT_FILES_HINT = "Select input audio files"
REMOVE_FROM_LIST_HINT = "Remove from list"
SELECT_OUTPUT_FOLDER_HINT = "Select output folder"

# --- Dual batch editor ---

DUAL_BATCH_MOVE_UP_HINT = "Move selected up"
DUAL_BATCH_MOVE_DOWN_HINT = "Move selected down"
DUAL_BATCH_REMOVE_HINT = "Remove selected"
DUAL_BATCH_CLEAR_HINT = "Clear all"

DUAL_INPUTS_HINT = (
    "Edit paired inputs. Alignment usually uses a primary mix and secondary "
    "instrumental; Matchering uses a target and reference"
)

OPEN_EXTERNAL_LINK_HINT = "Open in default browser"
OPEN_INSTALL_FOLDER_HINT = "Open install folder"

# --- Stem-only toggles ---

STEM_ONLY_ALL_HINT = "Export every stem this model produces"


def stem_only_tooltip(stem: str) -> str:
    from ui.widgets.stem_only import stem_display_label

    return f"Export only {stem_display_label(stem)}; skip the other output file"


def primary_stem_only_tooltip() -> str:
    return "Export only the model's primary stem; skip the secondary output"


def secondary_stem_only_tooltip() -> str:
    return "Export only the model's secondary stem; skip the primary output"
