"""Nested default factories for typed settings."""

from __future__ import annotations

from bundled.constants import (
    ALL_STEMS,
    AUDIO_TOOL_OPTIONS,
    AUTO_PHASE,
    AUTO_SELECT,
    CHOOSE_ENSEMBLE_OPTION,
    CHOOSE_MODEL,
    CHOOSE_STEM_PAIR,
    CHUNKS,
    DEFAULT,
    DEF_OPT,
    DEMUCS_OVERLAP,
    DEMUCS_SEGMENTS,
    MANUAL_ENSEMBLE_OPTIONS,
    MAX_MIN,
    MDX_ARCH_TYPE,
    MDX_OVERLAP,
    NO_MODEL,
    WAV,
)

SETTINGS_SCHEMA_VERSION = 1


def default_process() -> dict:
    return {
        "method": MDX_ARCH_TYPE,
        "use_gpu": False,
        "autocast": False,
        "use_directml": False,
        "device": DEFAULT,
        "primary_stem_only": False,
        "secondary_stem_only": False,
        "testing_audio": False,
        "add_model_name": False,
        "accept_any_input": False,
        "normalization": False,
        "match_mix_level": False,
        "prevent_export_clipping": False,
        "amplification_threshold": 0.0,
        "create_model_folder": False,
        "auto_update_model_params": True,
        "save_format": WAV,
        "wav_type": "PCM_16",
        "mp3_bitrate": "320k",
        "flac_bit_depth": "16-bit",
        "export_path": "",
        "input_paths": [],
        "last_dir": None,
        "sample_mode": False,
        "sample_mode_duration": 30,
        "long_file_chunk_seconds": 0.0,
        "long_file_chunk_overlap_seconds": 2.0,
        "semitone_shift": "0",
        "user_code": "",
        "model_hash_table": {},
        "vocal_splitter": NO_MODEL,
        "vocal_splitter_enabled": False,
        "save_inst_vocal_splitter": False,
        "deverb_vocals": False,
        "deverb_vocal_opt": "Main Vocals Only",
        "voc_split_save_opt": "Lead Only",
    }


def default_vr() -> dict:
    return {
        "model": CHOOSE_MODEL,
        "aggression_setting": 5,
        "window_size": 512,
        "batch_size": DEF_OPT,
        "crop_size": 256,
        "is_tta": False,
        "is_output_image": False,
        "is_post_process": False,
        "is_high_end_process": False,
        "post_process_threshold": 0.2,
        "voc_inst_secondary_model": NO_MODEL,
        "other_secondary_model": NO_MODEL,
        "bass_secondary_model": NO_MODEL,
        "drums_secondary_model": NO_MODEL,
        "is_secondary_model_activate": False,
        "voc_inst_secondary_model_scale": 0.9,
        "other_secondary_model_scale": 0.7,
        "bass_secondary_model_scale": 0.5,
        "drums_secondary_model_scale": 0.5,
    }


def default_mdx() -> dict:
    return {
        "model": CHOOSE_MODEL,
        "segment_size": 256,
        "overlap_mdx": MDX_OVERLAP[0],
        "overlap_mdx23": "8",
        "is_chunk_mdxnet": False,
        "is_mdx23_combine_stems": True,
        "is_mdx_include_stem_complement": False,
        "chunks": CHUNKS[0],
        "margin": 44100,
        "compensate": AUTO_SELECT,
        "is_denoise": False,
        "denoise_option": "None",
        "phase_option": AUTO_PHASE,
        "phase_shifts": "None",
        "is_save_align": False,
        "is_match_frequency_pitch": True,
        "is_match_silence": True,
        "is_spec_match": False,
        "is_mdx_c_seg_def": False,
        "is_invert_spec": False,
        "is_mixer_mode": False,
        "batch_size": DEF_OPT,
        "voc_inst_secondary_model": NO_MODEL,
        "other_secondary_model": NO_MODEL,
        "bass_secondary_model": NO_MODEL,
        "drums_secondary_model": NO_MODEL,
        "is_secondary_model_activate": False,
        "voc_inst_secondary_model_scale": 0.9,
        "other_secondary_model_scale": 0.7,
        "bass_secondary_model_scale": 0.5,
        "drums_secondary_model_scale": 0.5,
        "stems": ALL_STEMS,
        "stems_selected": [],
    }


def default_demucs() -> dict:
    return {
        "model": CHOOSE_MODEL,
        "segment": DEMUCS_SEGMENTS[0],
        "overlap": DEMUCS_OVERLAP[0],
        "shifts": 2,
        "chunks_demucs": CHUNKS[0],
        "margin_demucs": 44100,
        "is_chunk_demucs": False,
        "is_primary_stem_only": False,
        "is_secondary_stem_only": False,
        "is_split_mode": True,
        "is_demucs_combine_stems": True,
        "voc_inst_secondary_model": NO_MODEL,
        "other_secondary_model": NO_MODEL,
        "bass_secondary_model": NO_MODEL,
        "drums_secondary_model": NO_MODEL,
        "is_secondary_model_activate": False,
        "voc_inst_secondary_model_scale": 0.9,
        "other_secondary_model_scale": 0.7,
        "bass_secondary_model_scale": 0.5,
        "drums_secondary_model_scale": 0.5,
        "stems": ALL_STEMS,
        "pre_proc_model": NO_MODEL,
        "is_pre_proc_model_activate": False,
        "is_pre_proc_model_inst_mix": False,
    }


def default_ensemble() -> dict:
    return {
        "main_stem": CHOOSE_STEM_PAIR,
        "type": MAX_MIN,
        "selected_models": [],
        "chosen_ensemble": CHOOSE_ENSEMBLE_OPTION,
        "save_all_outputs": True,
        "append_ensemble_name": False,
        "wav_ensemble": False,
        "cleanup_temps": True,
    }


def default_audio_tools() -> dict:
    return {
        "chosen_audio_tool": AUDIO_TOOL_OPTIONS[0],
        "choose_algorithm": MANUAL_ENSEMBLE_OPTIONS[0],
        "time_stretch_rate": 2.0,
        "pitch_rate": 2.0,
        "apollo_overlap": "5",
        "apollo_chunk_size": "10",
        "apollo_model": CHOOSE_MODEL,
        "is_time_correction": True,
        "time_window": "3",
        "intro_analysis": DEFAULT,
        "db_analysis": "Medium",
        "file_one_entry": "",
        "file_one_entry_full": "",
        "file_two_entry": "",
        "file_two_entry_full": "",
        "dual_batch_input_paths": [],
    }


def default_ui() -> dict:
    return {
        "color_scheme": "auto",
        "window_width": 1040,
        "window_height": 720,
        "window_maximized": False,
        "notify_process_complete": True,
        "notify_process_failed": True,
        "notify_download_complete": True,
        "notify_download_failed": True,
    }


def default_settings_dict() -> dict:
    return {
        "schema_version": SETTINGS_SCHEMA_VERSION,
        "process": default_process(),
        "vr": default_vr(),
        "mdx": default_mdx(),
        "demucs": default_demucs(),
        "ensemble": default_ensemble(),
        "audio_tools": default_audio_tools(),
        "ui": default_ui(),
    }
