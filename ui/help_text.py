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


def validate_help_text(text: str, *, name: str = "") -> List[str]:
    """Return style violations for tooltip copy (empty list means OK)."""
    issues: List[str] = []
    prefix = f"{name}: " if name else ""
    if not text:
        return issues
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


# --- Upstream UVR hints (ported from the original Tk help strings) ---

STOP_HELP = """Stops ongoing tasks

• A confirmation pop-up will appear before stopping"""

SETTINGS_HELP = "Accesses the main settings and the \"Download Center.\""

COMMAND_TEXT_HELP = "Shows the status and progress of ongoing tasks"

PITCH_SHIFT_HELP = """Choose the pitch for processing tracks:

• Whole numbers indicate semitones
• Using higher pitches may cut the upper bandwidth, even in high-quality models
• Upping the pitch can be better for tracks with deeper vocals
• Dropping the pitch may take more processing time but works well for tracks with high-pitched vocals"""

AGGRESSION_SETTING_HELP = """Adjust the intensity of primary stem extraction:

• It ranges from -100 - 100
• Bigger values mean deeper extractions
• Typically, it's set to 5 for vocals & instrumentals
• Values beyond 5 might muddy the sound for non-vocal models"""

WINDOW_SIZE_HELP = """Select window size to balance quality and speed:

• 1024 - Quick but lesser quality
• 512 - Medium speed and quality
• 320 - Takes longer but may offer better quality"""

MDX_SEGMENT_SIZE_HELP = """Pick a segment size to balance speed, resource use, and quality:
• Smaller sizes consume less resources
• Bigger sizes consume more resources, but may provide better results
• Default size is 256. Quality can change based on your pick"""

DEMUCS_STEMS_HELP = """Select a stem for extraction with the chosen model:

• All Stems - Extracts all available stems
• Vocals - Only the "vocals" stem
• Other - Only the "other" stem
• Bass - Only the "bass" stem
• Drums - Only the "drums" stem"""

SEGMENT_HELP = """Adjust segments to manage RAM or V-RAM usage:

• Smaller sizes consume less resources
• Bigger sizes consume more resources, but may provide better results
• "Default" picks the optimal size"""

ENSEMBLE_MAIN_STEM_HELP = """Select the stem type for ensembling:

• Vocals/Instrumental:
  - Primary Stem: Vocals
  - Secondary Stem: Instrumental (mixture minus vocals)

• Other/No Other:
  - Primary Stem: Other
  - Secondary Stem: No Other (mixture minus "other")

• Bass/No Bass:
  - Primary Stem: Bass
  - Secondary Stem: No Bass (mixture minus bass)

• Drums/No Drums:
  - Primary Stem: Drums
  - Secondary Stem: No Drums (mixture minus drums)

• 4 Stem Ensemble:
  - Gathers all 4-stem Demucs models and ensembles all outputs

• Multi-stem Ensemble:
  - The "Jungle Ensemble" gathers all models and ensembles any related outputs"""

ENSEMBLE_TYPE_HELP = """Choose the ensemble algorithm for generating the final output:

• Max Spec/Min Spec:
  - Primary stem processed with "Max Spec" algorithm
  - Secondary stem processed with "Min Spec" algorithm

Note: For the "4 Stem Ensemble" option, only one algorithm will be displayed

Algorithm Details:
• Max Spec:
  - Produces the highest possible output
  - Ideal for vocal stems for a fuller sound, but might introduce unwanted artifacts
  - Works well with instrumental stems, but avoid using VR Arch models in the ensemble

• Min Spec:
  - Produces the lowest possible output
  - Ideal for instrumental stems for a cleaner result. Might result in a "muddy" sound

• Average:
  - Averages all results together for the final output"""

ENSEMBLE_LISTBOX_HELP = "Displays all available models for the chosen main stem pair"

IS_TIME_CORRECTION_HELP = "When checked, the output will retain the original BPM of the input"

SAVE_STEM_ONLY_HELP = """Choose which stems are written to disk. All Stems exports every output file; selecting a single stem saves only that file"""

IS_NORMALIZATION_HELP = "Normalizes output to prevent clipping"

IS_CUDA_SELECT_HELP = """If you have more than one GPU, you can pick which one to use for processing"""

CROP_SIZE_HELP = """Only compatible with select models only!

Setting should match training crop-size value. Leave as is if unsure"""

IS_TTA_HELP = """This option performs Test-Time-Augmentation to improve the separation quality

Note: Having this selected will increase the time it takes to complete a conversion"""

IS_POST_PROCESS_HELP = """This option can potentially identify leftover instrumental artifacts within the vocal outputs

This option may improve the separation of some songs

Note: Selecting this option can adversely affect the conversion process, depending on the track. Because of this, it is only recommended as a last resort"""

IS_HIGH_END_PROCESS_HELP = "The application will mirror the missing frequency range of the output"

SHIFTS_HELP = """Performs multiple predictions with random shifts of the input and averages them

• The higher number of shifts, the longer the prediction will take
  - Not recommended unless you have a GPU"""

OVERLAP_HELP = """• This option controls the amount of overlap between prediction windows
  - Higher values can provide better results, but will lead to longer processing times
  - You can choose between 0.001-0.999"""

MDX_OVERLAP_HELP = """• This option controls the amount of overlap between prediction windows
  - Higher values can provide better results, but will lead to longer processing times
  - For Non-MDX23C models: You can choose between 0.001-0.999"""

OVERLAP_23_HELP = """• This option controls the amount of overlap between prediction windows
  - Higher values can provide better results, but will lead to longer processing times"""

IS_SEGMENT_DEFAULT_HELP = """• The segment size is set based on the value provided in a chosen model's associated config file (yaml)"""

IS_SPLIT_MODE_HELP = """• Enables "Segments"
• Deselecting this option is only recommended for those with powerful PCs"""

IS_DEMUCS_COMBINE_STEMS_HELP = "The application will create the secondary stem by combining the remaining stems instead of inverting the primary stem with the mixture"

COMPENSATE_HELP = """Compensates the audio of the primary stems to allow for a better secondary stem"""

IS_DENOISE_HELP = """• Standard: This setting reduces the noise created by MDX-Net models
  - This option only reduces noise in non-MDX23 models
• Denoise Model: This setting employs a special denoise model to eliminate noise produced by any MDX-Net model
  - This option works on all MDX-Net models
  - You must have the "UVR-DeNoise-Lite" VR Arch model installed to use this option
• Please Note: Both options will increase separation time"""

VOC_SPLIT_MODEL_SELECT_HELP = """• Select a model from the list of lead and backing vocal models to run through vocal stems automatically"""

IS_VOC_SPLIT_INST_SAVE_SELECT_HELP = """• When activated, you will receive extra instrumental outputs that include: one with just the lead vocals and another with only the backing vocals"""

IS_VOC_SPLIT_MODEL_SELECT_HELP = """• When activated, this option auto-processes generated vocal stems, using either a karaoke model to remove lead vocals or another to remove backing vocals
  - This option splits the vocal track into two separate parts: lead vocals and backing vocals, providing two extra vocal outputs
  - The results will be organized in the same way, whether you use a karaoke model or a background vocal model
  - This option does not work in ensemble mode at this time"""

IS_DEVERB_OPT_HELP = """• Select the vocal type you wish to deverb automatically
  - Example: Choosing "Lead Vocals Only" will only remove reverb from a lead vocal stem"""

IS_DEVERB_VOC_HELP = """• This option removes reverb from a vocal stem
  - You must have the "UVR-DeEcho-DeReverb" VR Arch model installed to use this option
  - This option does not work in ensemble mode at this time"""

IS_FREQUENCY_MATCH_HELP = """Matches the frequency cut-off of the primary stem to that of the secondary stem"""

CLEAR_CACHE_HELP = "Clears settings for unrecognized models chosen by the user"

IS_SAVE_ALL_OUTPUTS_ENSEMBLE_HELP = "If enabled, all individual ensemble-generated outputs are retained"

IS_APPEND_ENSEMBLE_NAME_HELP = "When enabled, the ensemble name is added to the final output"

IS_WAV_ENSEMBLE_HELP = """Processes ensemble algorithms with waveforms instead of spectrograms when activated:
• Might lead to increased distortion
• Waveform ensembling is faster than spectrogram ensembling"""

DONATE_HELP = """Opens official UVR "Buy Me a Coffee" external link for project donations!"""

IS_INVERT_SPEC_HELP = """Potentially enhances the secondary stem quality:
• Inverts primary stem using spectrograms, instead of waveforms
• Slightly slower inversion method"""

IS_TESTING_AUDIO_HELP = "Appends a 10-digit number to saved files to avoid accidental overwrites"

IS_MODEL_TESTING_AUDIO_HELP = "Appends the model name to outputs for comparison across different models"

IS_ACCEPT_ANY_INPUT_HELP = """Allows all types of inputs when enabled, even non-audio formats

For experimental use only. Not recommended for regular use"""

DELETE_YOUR_SETTINGS_HELP = """Contains your saved settings. Confirmation will be requested before deleting a selected setting"""

SET_STEM_NAME_HELP = "Select the primary stem for the given model"

IS_CREATE_MODEL_FOLDER_HELP = """Two new directories will be generated for the outputs in the export directory after each conversion

• Example:
─ Export Directory
└── First Directory (Named after the model)
└── Second Directory (Named after the track)
└── Output File(s)"""

MDX_DIM_T_SET_HELP = "This is an internal model setting — avoid changing it unless you're certain about it!"

MDX_DIM_F_SET_HELP = "This is an internal model setting — avoid changing it unless you're certain about it!"

MDX_N_FFT_SCALE_SET_HELP = "Specify the N_FFT size used during model training"

POPUP_COMPENSATE_HELP = (
    "Select the appropriate volume compensation for the chosen model\n\n"
    f"Reminder: {COMPENSATE_HELP}"
)

VR_MODEL_PARAM_HELP = "Select the required parameters to run the chosen model"

CHOSEN_ENSEMBLE_HELP = """Default Ensemble Selections:
• Save the current ensemble configuration
• Clear all selected models

Note: You can also select previously saved ensembles"""

CHOSEN_PROCESS_METHOD_HELP = """Choose a Processing Method:

Select from various AI networks and algorithms to process your track:

• VR Architecture: Uses magnitude spectrograms for source separation
• MDX-Net: Employs a Hybrid Spectrogram network for source separation
• Demucs v3: Also utilizes a Hybrid Spectrogram network for source separation
• Ensemble Mode: Combine results from multiple models and networks for optimal results
• Audio Tools: Additional utilities for added convenience"""

INPUT_FOLDER_ENTRY_HELP = """Select Input:

Choose the audio file(s) you want to process"""

OUTPUT_FOLDER_ENTRY_HELP = """Select Output:

Choose the directory where the processed files will be saved"""

INPUT_FOLDER_BUTTON_HELP = """Open Input Folder Button:

Open the directory containing the selected input audio file(s)"""

OUTPUT_FOLDER_BUTTON_HELP = """Open Output Folder Button:

Open the selected output folder"""

CHOOSE_MODEL_HELP = "Each processing method has its own set of options and models — choose the model for the selected processing method"

FORMAT_SETTING_HELP = "Save Outputs As:"

SECONDARY_MODEL_ACTIVATE_HELP = """When enabled, the application will perform an additional inference using the selected model(s) above"""

SECONDARY_MODEL_HELP = """Choose the Secondary Model:

Select the secondary model associated with the stem you want to process with the current method"""

INPUT_SEC_FIELDS_HELP = "Right click here to choose your inputs!"

SECONDARY_MODEL_SCALE_HELP = """The scale determines how the final audio outputs will be averaged between the primary and secondary models

For example:

• 10% - 10 percent of the main model result will be factored into the final result
• 50% - The results from the main and secondary models will be averaged evenly
• 90% - 90 percent of the main model result will be factored into the final result"""

PRE_PROC_MODEL_ACTIVATE_HELP = """When enabled, the application will use the selected model to isolate the instrumental stem

Subsequently, all non-vocal stems will be extracted from this generated instrumental

Key Points:
• This feature can significantly reduce vocal bleed in non-vocal stems
• Available exclusively in the Demucs tool
• Compatible only with non-vocal and non-instrumental stem outputs
• Expect an increase in total processing time
• Only the VR or MDX-Net Vocal Instrumental/Vocals models can be chosen for this process"""

AUDIO_TOOLS_HELP = """Select from various audio tools to process your track:

• Manual Ensemble: Requires 2 or more selected files as inputs. This allows tracks to be processed using the algorithms from Ensemble Mode
• Time Stretch: Adjust the playback speed of the selected inputs to be faster or slower
• Change Pitch: Modify the pitch of the selected inputs
• Align Inputs: Choose 2 audio file and the application will align them and provide the difference in alignment
  - This tool provides similar functionality to "Utagoe."
  - Primary Audio: This is usually a mixture
  - Secondary Audio: This is usually an instrumental
• Matchering: Choose 2 audio files. The matchering algorithm will master the target audio to have the same RMS, FR, peak amplitude, and stereo width as the reference audio
• Apollo Restore: Apollo is a music restoration AI that fixes distortions and artifacts from audio codecs, especially at low bitrates. It effectively restores MP3s at 32 kbps and above, improving audio quality across compression levels"""

APOLLO_CHUNK_SIZE_HELP = """Pick a chunk size to balance speed, resource use, and quality:
• Smaller sizes consume less resources
• Bigger sizes consume more resources, but may provide better results
• Default size is 10. Quality can change based on your pick"""

APOLLO_OVERLAP_HELP = """This option controls the amount of overlap between prediction windows

• Higher values increase quality but slow processing and use more resources
• Default value is 5"""

CHOOSE_APOLLO_MODEL_HELP = "Choose the Apollo model to use to restore audio"

ROFORMER_MODEL_HELP = """Enable for BS-Roformer / Mel-Band Roformer checkpoints. They use the MDX-C yaml-config flow but require this flag so the engine builds the Roformer network instead of the standard TFC-TDF net"""

PRE_PROC_MODEL_INST_MIX_HELP = """When enabled, the application will generate a third output without the selected stem and vocals"""

MODEL_SAMPLE_MODE_HELP = """Allows the user to process only part of a track to sample settings or a model without running a full conversion

Notes:

• The number in the parentheses is the current number of seconds the generated sample will be
• You can choose the number of seconds to extract from the track in the "Additional Settings" menu"""

POST_PROCESS_THREASHOLD_HELP = """Allows the user to control the intensity of the Post_process option

Notes:

• Higher values potentially remove more artifacts. However, bleed might increase
• Lower values limit artifact removal"""

BATCH_SIZE_HELP = """Specify the number of batches to be processed at a time

Notes:

• Higher values mean more RAM usage but slightly faster processing times
• Lower values mean less RAM usage but slightly longer processing times
• Batch size value has no effect on output quality"""

VR_MODEL_NOUT_HELP = ""

VR_MODEL_NOUT_LSTM_HELP = ""

IS_PHASE_HELP = """Select the phase for the secondary audio

• Note: Using the "Automatic" option is strongly recommended"""

IS_ALIGN_TRACK_HELP = "Enable this to save the secondary track once aligned"

IS_MATCH_SILENCE_HELP = """Aligns the initial silence of the secondary audio with the primary audio

• Note: Avoid using this option if the primary audio begins solely with vocals"""

IS_MATCH_SPEC_HELP = """Align the secondary audio based on the primary audio's spectrogram

• Note: This may enhance alignment in specific cases"""

TIME_WINDOW_ALIGN_HELP = """This setting determines the window size for alignment analysis, especially for pairs with minor timing variations:

• None: Disables time window analysis
• 1: Analyzes pair by 0.0625-second windows
• 2: Analyzes pair by 0.125-second windows
• 3: Analyzes pair by 0.25-second windows
• 4: Analyzes pair by 0.50-second windows
• 5: Analyzes pair by 0.75-second windows
• 6: Analyzes pair by 1-second windows
• 7: Analyzes pair by 2-second windows

Shifts Options:
• Low: Cycles through 0.0625 and 0.5-second windows to find an optimal match
• Medium: Cycles through 0.0625, 0.125, and 0.5-second windows to find an optimal match
• High: Cycles through 0.0625, 0.125, 0.25, and 0.5-second windows to find an optimal match

Important Points to Consider:
  - Using the "Shifts" option may require more processing time and might not guarantee better results
  - Opting for smaller analysis windows can increase processing times
  - The best settings are likely to vary based on the specific tracks being processed"""

INTRO_ANALYSIS_ALIGN_HELP = """This setting determines the portion of the audio input to be analyzed for initial alignment

• Default: Analyzes 10% (or 1/10th) of the audio's total length
• 1: Analyzes 12.5% (or 1/8th) of the audio's total length
• 2: Analyzes 16.67% (or 1/6th) of the audio's total length
• 3: Analyzes 25% (or 1/4th) of the audio's total length
• 4: Analyzes 50% (or half) of the audio's total length

Shifts Options:
• Low: Cycles through 2 intro analysis values
• Medium: Cycles through 3 intro analysis values
• High: Cycles through 5 intro analysis values

Important Points to Consider:
  - Using the "Shifts" option will require more processing time and might not guarantee better results
  - Optimal settings may vary depending on the specific tracks being processed"""

VOLUME_ANALYSIS_ALIGN_HELP = """This setting specifies the volume adjustments to be made on the secondary input:

• None: No volume adjustments are made
• Low: Analyzes the audio within a 4dB range, adjusting in 1dB increments
• Medium: Analyzes the audio within a 6dB range, adjusting in 1dB increments
• High: Analyzes the audio within a 6dB range, adjusting in 0.5dB increments
• Very High: Analyzes the audio within a 10dB range, adjusting in 0.5dB increments

Important Points to Consider:
  - Selecting more extensive analysis options (e.g., High, Very High) will lead to longer processing times
  - Optimal settings might vary based on the specific tracks being processed"""

PHASE_SHIFTS_ALIGN_HELP = """This setting specifies the phase adjustments to be made on the secondary input:

Shifts Options:
• None: No phase adjustments are made
• Very Low: Analyzes the audio within range of 2 different phase positions
• Low: Analyzes the audio within range of 4 different phase positions
• Medium: Analyzes the audio within range of 8 different phase positions
• High: Analyzes the audio within range of 18 different phase positions
• Very High: Analyzes the audio within range of 36 different phase positions
• Maximum: Analyzes the audio in all 360 phase positions

Important Points to Consider:
  - This option only works with time correction
  - This option can be helpful if one of the inputs were from an analog source
  - Selecting more extensive analysis options (e.g., High, Very High) will lead to longer processing times
  - Selecting "Maximum" can take hours to process
  - Optimal settings might vary based on the specific tracks being processed"""

if sys.platform == "darwin":
    IS_GPU_CONVERSION_HELP = """• Use GPU for Processing (if available):
  - If checked, the application will attempt to use your GPU for faster processing
  - If a GPU is not detected, it will default to CPU processing
  - GPU processing for MacOS only works with VR Arch models

• Please Note:
  - CPU processing is significantly slower than GPU processing
  - Only Macs with M1 chips can be used for GPU processing"""
else:
    IS_GPU_CONVERSION_HELP = """• Use GPU for Processing (if available):
  - If checked, the application will attempt to use your GPU for faster processing
  - If a GPU is not detected, it will default to CPU processing

• Please Note:
  - CPU processing is significantly slower than GPU processing
  - NVIDIA GPUs use CUDA; on Windows, enable DirectML for AMD/Intel GPUs
  - DirectML accelerates PyTorch models only; classic MDX ONNX models stay on CPU"""


# --- GTK shell ---

PROCESS_METHOD_HINT = """
Choose the separation algorithm:

• VR Architecture — magnitude spectrogram source separation
• MDX-Net — hybrid spectrogram network
• Demucs v3/4 — hybrid spectrogram network (multi-stem capable)
""".strip()

VIEW_TAB_HINTS: Dict[str, str] = {
    "separation": (
        "Separate vocals, instrumentals, and other stems using VR, MDX-Net, or Demucs models"
    ),
    "ensemble": (
        "Combine outputs from multiple models and algorithms for higher-quality results"
    ),
    "audio_tools": (
        "Time stretch, change pitch, align tracks, matchering, manual ensemble, and Apollo audio restoration"
    ),
}

OUTPUT_FORMAT_HINT = "Choose the audio format for saved output files (WAV, FLAC, or MP3)"

# --- Separation / method views ---

MDX_OVERLAP_HINT = (
    "Overlap between prediction windows — available values follow the selected model: "
    "classic MDX-Net uses the Default/0.25-0.99 scale, while MDX23C models use 2-50"
)

MDX_STEMS_HINT = (
    "Choose which stems to save — applies to multi-stem MDX23C models; "
    "for 2-stem models the 'Only' toggles above apply"
)

DEMUCS_CHUNK_HINT = "Process the audio in chunks to reduce memory usage (legacy option)"

# --- Ensemble page ---

ENSEMBLE_SAVED_PRESET_HINT = (
    "Load a previously saved ensemble preset, or save / delete one with the buttons"
)
ENSEMBLE_SAVE_BUTTON_HINT = "Save current ensemble"
ENSEMBLE_DELETE_BUTTON_HINT = "Delete selected saved ensemble"

# --- Audio tools page ---

MANUAL_ENSEMBLE_ALGORITHM_HINT = (
    "Choose how the selected files are combined (e.g. Min/Max, Average, or Combine Inputs)"
)
PLAYBACK_RATE_HINT = (
    "Playback rate multiplier: values below 1 slow the track down, values above 1 speed it up"
)
WAV_TYPE_HINT = "Bit depth / sample encoding used when saving WAV output"
FLAC_BIT_DEPTH_HINT = "Bit depth used when saving FLAC output (16-bit or 24-bit)"

# --- Main window chrome ---

MAIN_MENU_HINT = "Main menu"
VIEW_INPUTS_BUTTON_HINT = "View or verify selected inputs"

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
    "Paired audio files processed together — for align, primary is usually the mixture "
    "and secondary is usually the instrumental"
)

# --- Stem-only toggles ---

STEM_ONLY_ALL_HINT = "Export every stem this model produces (default)"


def stem_only_tooltip(stem: str) -> str:
    return f"Export only the {stem} stem; the other output file is skipped"


def primary_stem_only_tooltip() -> str:
    return "Export only the model's primary stem; skip the secondary output"


def secondary_stem_only_tooltip() -> str:
    return "Export only the model's secondary stem; skip the primary output"

