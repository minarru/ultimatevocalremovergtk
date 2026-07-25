from .platform_info import OPERATING_SYSTEM
from .stems import BASS_STEM, CHOOSE_STEM_PAIR, DRUM_STEM, INST_STEM, NO_BASS_STEM, NO_DRUM_STEM, NO_OTHER_STEM, NO_WIND_INST_STEM, OTHER_STEM, VOCAL_STEM

#Model Types
VR_ARCH_TYPE = 'VR Arc'

MDX_ARCH_TYPE = 'MDX-Net'

DEMUCS_ARCH_TYPE = 'Demucs'

#: Apollo restoration models. Not a separation architecture — these are used by
#: the Audio Tools restore path — but the Download Center keys its catalogues by
#: "arch type", so Apollo gets one to appear as its own network.
APOLLO_ARCH_TYPE = 'Apollo'

VR_ARCH_PM = 'VR Architecture'

ENSEMBLE_MODE = 'Ensemble Mode'

ENSEMBLE_STEM_CHECK = 'Ensemble Stem'

DEMUCS_6_STEM_MODEL = 'htdemucs_6s'

DEFAULT = "Default"

DEMUCS_V3_ARCH_TYPE = 'Demucs v3'

DEMUCS_V4_ARCH_TYPE = 'Demucs v4'

DEMUCS_NEWER_ARCH_TYPES = [DEMUCS_V3_ARCH_TYPE, DEMUCS_V4_ARCH_TYPE]

DEMUCS_V1 = 'v1'

DEMUCS_V2 = 'v2'

DEMUCS_V3 = 'v3'

DEMUCS_V4 = 'v4'

DEMUCS_V1_TAG = 'v1 | '

DEMUCS_V2_TAG = 'v2 | '

DEMUCS_V3_TAG = 'v3 | '

DEMUCS_V4_TAG = 'v4 | '

DEMUCS_VERSION_MAPPER = {
            DEMUCS_V1:DEMUCS_V1_TAG,
            DEMUCS_V2:DEMUCS_V2_TAG,
            DEMUCS_V3:DEMUCS_V3_TAG,
            DEMUCS_V4:DEMUCS_V4_TAG}

ENSEMBLE_PARTITION = ': '

IS_KARAOKEE = "is_karaoke"

IS_BV_MODEL = "is_bv_model"

#Menu Options

AUTO_SELECT = 'Auto'

#Menu Dropdowns

VOCAL_PAIR = f'{VOCAL_STEM}/{INST_STEM}'

OTHER_PAIR = f'{OTHER_STEM}/{NO_OTHER_STEM}'

DRUM_PAIR = f'{DRUM_STEM}/{NO_DRUM_STEM}'

BASS_PAIR = f'{BASS_STEM}/{NO_BASS_STEM}'

FOUR_STEM_ENSEMBLE = '4 Stem Ensemble'

MULTI_STEM_ENSEMBLE = 'Multi-stem Ensemble'

ENSEMBLE_MAIN_STEM = (CHOOSE_STEM_PAIR, VOCAL_PAIR, OTHER_PAIR, DRUM_PAIR, BASS_PAIR, FOUR_STEM_ENSEMBLE, MULTI_STEM_ENSEMBLE)

MIN_SPEC = 'Min Spec'

MAX_SPEC = 'Max Spec'

AUDIO_AVERAGE = 'Average'

MEDIAN_SPEC = 'Median Spec'

SOFT_SPEC = 'Soft Spec'

MAX_MAG_AVG_PHASE = 'Max Mag / Avg Phase'

HYBRID_SPEC = 'Hybrid Spec'

CHUNK_MIN = 'Chunk Min'

ENSEMBLE_ALGORITHMS = (
    MAX_SPEC,
    MIN_SPEC,
    AUDIO_AVERAGE,
    MEDIAN_SPEC,
    SOFT_SPEC,
    MAX_MAG_AVG_PHASE,
    HYBRID_SPEC,
    CHUNK_MIN,
)

MAX_MIN = f'{MAX_SPEC}/{MIN_SPEC}'

MAX_MAX = f'{MAX_SPEC}/{MAX_SPEC}'

MAX_AVE = f'{MAX_SPEC}/{AUDIO_AVERAGE}'

MIN_MAX = f'{MIN_SPEC}/{MAX_SPEC}'

MIN_MIX = f'{MIN_SPEC}/{MIN_SPEC}'

MIN_AVE = f'{MIN_SPEC}/{AUDIO_AVERAGE}'

AVE_MAX = f'{AUDIO_AVERAGE}/{MAX_SPEC}'

AVE_MIN = f'{AUDIO_AVERAGE}/{MIN_SPEC}'

AVE_AVE = f'{AUDIO_AVERAGE}/{AUDIO_AVERAGE}'

# Legacy dual-stem pair labels (migration / defaults). UI uses ENSEMBLE_ALGORITHMS.
ENSEMBLE_TYPE = (MAX_MIN, MAX_MAX, MAX_AVE, MIN_MAX, MIN_MIX, MIN_AVE, AVE_MAX, AVE_MIN, AVE_AVE)

ENSEMBLE_TYPE_4_STEM = ENSEMBLE_ALGORITHMS

DEF_OPT = 'Default'

CHUNKS = (AUTO_SELECT, '1', '5', '10', '15', '20', 
          '25', '30', '35', '40', '45', '50', 
          '55', '60', '65', '70', '75', '80', 
          '85', '90', '95', 'Full')

BATCH_SIZE = (DEF_OPT, '2', '3', '4', '5', 
          '6', '7', '8', '9', '10')

VOL_COMPENSATION = (AUTO_SELECT, '1.035', '1.08')

MANUAL_ENSEMBLE = 'Manual Ensemble'

TIME_STRETCH = 'Time Stretch'

CHANGE_PITCH = 'Change Pitch'

ALIGN_INPUTS = 'Align Inputs'

MATCH_INPUTS = 'Matchering'

APOLLO_RESTORE = 'Apollo Restore'

COMBINE_INPUTS = 'Combine Inputs'

if OPERATING_SYSTEM == 'Windows' or OPERATING_SYSTEM == 'Darwin':  
   AUDIO_TOOL_OPTIONS = (MANUAL_ENSEMBLE, TIME_STRETCH, CHANGE_PITCH, ALIGN_INPUTS, MATCH_INPUTS, APOLLO_RESTORE)
else:
   AUDIO_TOOL_OPTIONS = (MANUAL_ENSEMBLE, ALIGN_INPUTS, MATCH_INPUTS, APOLLO_RESTORE)

MANUAL_ENSEMBLE_OPTIONS = ENSEMBLE_ALGORITHMS + (COMBINE_INPUTS,)

DEMUCS_SEGMENTS = (DEF_OPT, '1', '5', '10', '15', '20', 
                  '25', '30', '35', '40', '45', '50', 
                  '55', '60', '65', '70', '75', '80', 
                  '85', '90', '95', '100')

DEMUCS_SHIFTS = (0, 1, 2, 3, 4, 5, 
                 6, 7, 8, 9, 10, 11, 
                 12, 13, 14, 15, 16, 17, 
                 18, 19, 20)

NOUT_SEL = (8, 16, 32, 48, 64)

NOUT_LSTM_SEL = (64, 128)

DEMUCS_OVERLAP = (0.25, 0.50, 0.75, 0.99)

MDX_OVERLAP = (DEF_OPT, 0.25, 0.50, 0.75, 0.99)

MDX23_OVERLAP = range(2, 51)

VR_AGGRESSION = range(0, 51)

TIME_WINDOW_MAPPER = {
            "None": None,
            "1": [0.0625],
            "2": [0.125],
            "3": [0.25],
            "4": [0.5],
            "5": [0.75],
            "6": [1],
            "7": [2],
            "Shifts: Low": [0.0625, 0.5],
            "Shifts: Medium": [0.0625, 0.125, 0.5],
            "Shifts: High": [0.0625, 0.125, 0.25, 0.5]
            #"Shifts: Very High": [0.0625, 0.125, 0.25, 0.5, 0.75, 1],
}

INTRO_MAPPER = {
            "Default": [10],
            "1": [8],
            "2": [6],
            "3": [4],
            "4": [2],
            "Shifts: Low": [1, 10],
            "Shifts: Medium": [1, 10, 8],
            "Shifts: High": [1, 10, 8, 6, 4]
            }

VOLUME_MAPPER = {
            "None": (0, [0]),
            "Low": (-4, range(0, 8)),
            "Medium": (-6, range(0, 12)),
            "High": (-6, [x * 0.5 for x in range(0, 25)]),
            "Very High": (-10, [x * 0.5 for x in range(0, 41)])}

NONE_P = "None"

VLOW_P = "Shifts: Very Low"

LOW_P = "Shifts: Low"

MED_P = "Shifts: Medium"

HIGH_P = "Shifts: High"

VHIGH_P = "Shifts: Very High"

VMAX_P = "Shifts: Maximum"

PHASE_SHIFTS_OPT = {
                     NONE_P:190,
                     VLOW_P:180,
                     LOW_P:90,
                     MED_P:45,
                     HIGH_P:20,
                     VHIGH_P:10,
                     VMAX_P:1,}

VR_WINDOW = ('320', '512','1024')

VR_CROP = ('256', '512', '1024')

POST_PROCESSES_THREASHOLD_VALUES = ('0.1', '0.2', '0.3')

MDX_POP_NFFT = ('4096', '5120', '6144', '7680', '8192', '16384')

MDX_POP_DIMF = ('2048', '3072', '4096')

DENOISE_NONE, DENOISE_S, DENOISE_M = 'None', 'Standard', 'Denoise Model'

MDX_DENOISE_OPTION = [DENOISE_NONE, DENOISE_S, DENOISE_M]

MDX_SEGMENTS = list(range(32, 4000+1, 32))

CHOOSE_ENSEMBLE_OPTION = 'Choose Option'

ALL_TYPES = 'ALL'

ENSEMBLE_CHECK = 'ensemble check'

KARAOKEE_CHECK = 'kara check'

AUTO_PHASE = "Automatic"

POSITIVE_PHASE = "Positive Phase"

NEGATIVE_PHASE = "Negative Phase"

OFF_PHASE = "Native Phase"

ALIGN_PHASE_OPTIONS = [AUTO_PHASE, POSITIVE_PHASE, NEGATIVE_PHASE, OFF_PHASE]

SAMPLE_MODE_CHECKBOX = lambda v:f'Sample Mode ({v}s)'

GPU_DEVICE_NUM_OPTS = (DEFAULT, '0', '1', '2', '3', '4', '5', '6', '7', '8')

WOOD_INST_MODEL_HASH = '0ec76fd9e65f81d8b4fbd13af4826ed8'

WOOD_INST_PARAMS = {
    "vr_model_param": "4band_v3",
    "primary_stem": NO_WIND_INST_STEM
}
