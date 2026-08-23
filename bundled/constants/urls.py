#LINKS
DOWNLOAD_CHECKS = "https://raw.githubusercontent.com/TRvlvr/application_data/main/filelists/download_checks.json"

MDX_MODEL_DATA_LINK = "https://raw.githubusercontent.com/TRvlvr/application_data/main/mdx_model_data/model_data_new.json"

MDX23_CONFIG_CHECKS = "https://raw.githubusercontent.com/TRvlvr/application_data/main/mdx_model_data/mdx_c_configs/"

VR_MODEL_DATA_LINK = "https://raw.githubusercontent.com/TRvlvr/application_data/main/vr_model_data/model_data_new.json"

POLITREES_RAW_BASE = "https://raw.githubusercontent.com/Politrees/UVR_resources/main"

POLITREES_CONFIG_SUBDIRS = (
    "Roformer/BandSplit",
    "Roformer/MelBand",
    "MDX23C",
    "SCnet",
    "Bandit",
    "demucs",
)

POLITREES_MODEL_LINKS_URL = f"{POLITREES_RAW_BASE}/UVR_resources/model_list_links.json"

#: Machine-readable MVSEP-less resource catalogue (checkpoint + config URLs).
MVSEPLESS_MODELS_JSON_URL = (
    "https://huggingface.co/noblebarkrr/mvsepless_resources/resolve/main/models.json"
)

#: Benchmarked per-stem SDR scores, keyed by checkpoint filename.
MODEL_SCORES_URL = (
    "https://raw.githubusercontent.com/nomadkaraoke/python-audio-separator"
    "/main/audio_separator/models-scores.json"
)

BULLETIN_CHECK = "https://raw.githubusercontent.com/TRvlvr/application_data/main/bulletin.txt"

DEMUCS_MODEL_NAME_DATA_LINK = "https://raw.githubusercontent.com/TRvlvr/application_data/main/demucs_model_data/model_name_mapper.json"

MDX_MODEL_NAME_DATA_LINK = "https://raw.githubusercontent.com/TRvlvr/application_data/main/mdx_model_data/model_name_mapper.json"

DONATE_LINK_BMAC = "https://www.buymeacoffee.com/uvr5"

DONATE_LINK_PATREON = "https://www.patreon.com/uvr"

#DOWNLOAD REPOS
NORMAL_REPO = "https://github.com/TRvlvr/model_repo/releases/download/all_public_uvr_models/"

ADDITIONAL_MODEL_REPO = (
    "https://github.com/Anjok0109/ai_magic/releases/download/v5/"
)

FORK_RELEASE_JSON_URL = (
    "https://raw.githubusercontent.com/minarru/ultimatevocalremovergtk/main/packaging/release.json"
)

FORK_RELEASE_PAGE = "https://github.com/minarru/ultimatevocalremovergtk/releases"

FORK_ISSUE_URL = "https://github.com/minarru/ultimatevocalremovergtk/issues/new"

ISSUE_LINK = FORK_ISSUE_URL
