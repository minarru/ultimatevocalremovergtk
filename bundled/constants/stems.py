ALL_STEMS = 'All Stems'

VOCAL_STEM = 'Vocals'

INST_STEM = 'Instrumental'

OTHER_STEM = 'Other'

BASS_STEM = 'Bass'

DRUM_STEM = 'Drums'

GUITAR_STEM = 'Guitar'

PIANO_STEM = 'Piano'

SYNTH_STEM = 'Synthesizer'

STRINGS_STEM = 'Strings'

WOODWINDS_STEM = 'Woodwinds'

BRASS_STEM = 'Brass'

WIND_INST_STEM = 'Wind Inst'

NO_OTHER_STEM = 'No Other'

NO_BASS_STEM = 'No Bass'

NO_DRUM_STEM = 'No Drums'

NO_GUITAR_STEM = 'No Guitar'

NO_PIANO_STEM = 'No Piano'

NO_WIND_INST_STEM = 'No Wind Inst'

PRIMARY_STEM = 'Primary Stem'

SECONDARY_STEM = 'Secondary Stem'

LEAD_VOCAL_STEM = 'lead_only'

BV_VOCAL_STEM = 'backing_only'

LEAD_VOCAL_STEM_LABEL = 'Lead Vocals'

BV_VOCAL_STEM_LABEL = 'Backing Vocals'

INST_WITH_LEAD_VOCALS_STEM = 'Instrumental (With Lead Vocals)'

INST_WITH_BACKING_VOCALS_STEM = 'Instrumental (With Backing Vocals)'

# Filename-safe ensemble bucket tags. These are written into export filenames
# as ``({tag})``, so they must contain no parentheses: the ensemble collection
# regex in core/job_runner.py is ``\(([^()]+)\)\.(wav|flac|mp3)$`` and rejects
# nested parens. The human-readable labels above stay for UI display only.
INST_WITH_BACKING_VOCALS_TAG = 'Instrumental_WithBackingVocals'

INST_WITH_LEAD_VOCALS_TAG = 'Instrumental_WithLeadVocals'

LEAD_VOCALS_TAG = 'Lead_Vocals'

BACKING_VOCALS_TAG = 'Backing_Vocals'

VOCAL_STEM_ONLY = f'{VOCAL_STEM} Only'

INST_STEM_ONLY = f'{INST_STEM} Only'

IS_SAVE_INST_ONLY = f'save_only_inst'

IS_SAVE_VOC_ONLY = f'save_only_voc'

DEVERB_MAPPER = {'Main Vocals Only':VOCAL_STEM, 
                 'Lead Vocals Only':LEAD_VOCAL_STEM_LABEL, 
                 'Backing Vocals Only':BV_VOCAL_STEM_LABEL, 
                 'All Vocal Types':'ALL'}

BALANCE_VALUES = [0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]

#Other Constants
DEMUCS_2_SOURCE = ["instrumental", "vocals"]

DEMUCS_4_SOURCE = ["drums", "bass", "other", "vocals"]

DEMUCS_6_SOURCE = ["drums", "bass", "other", "vocals", "guitar", "piano"]

DEMUCS_2_SOURCE_MAPPER = {
                        INST_STEM: 0,
                        VOCAL_STEM: 1}

DEMUCS_4_SOURCE_MAPPER = {
                        BASS_STEM: 0,
                        DRUM_STEM: 1,
                        OTHER_STEM: 2,
                        VOCAL_STEM: 3}

DEMUCS_6_SOURCE_MAPPER = {
                        BASS_STEM:0,
                        DRUM_STEM:1,
                        OTHER_STEM:2,
                        VOCAL_STEM:3,
                        GUITAR_STEM:4,
                        PIANO_STEM:5}

DEMUCS_4_SOURCE_LIST = [BASS_STEM, DRUM_STEM, OTHER_STEM, VOCAL_STEM]

DEMUCS_UVR_MODEL = 'UVR_Model'

CHOOSE_STEM_PAIR = 'Choose Stem Pair'

STEM_SET_MENU = (VOCAL_STEM, 
                 INST_STEM, 
                 OTHER_STEM, 
                 BASS_STEM, 
                 DRUM_STEM, 
                 GUITAR_STEM, 
                 PIANO_STEM, 
                 SYNTH_STEM, 
                 STRINGS_STEM, 
                 WOODWINDS_STEM, 
                 BRASS_STEM, 
                 WIND_INST_STEM)

STEM_PAIR_MAPPER = {
            VOCAL_STEM: INST_STEM,
            INST_STEM: VOCAL_STEM,
            LEAD_VOCAL_STEM: BV_VOCAL_STEM,
            BV_VOCAL_STEM: LEAD_VOCAL_STEM,
            PRIMARY_STEM: SECONDARY_STEM}

NO_STEM = "No "

NON_ACCOM_STEMS = (
            VOCAL_STEM,
            OTHER_STEM,
            BASS_STEM,
            DRUM_STEM,
            GUITAR_STEM,
            PIANO_STEM,
            SYNTH_STEM,
            STRINGS_STEM,
            WOODWINDS_STEM,
            BRASS_STEM,
            WIND_INST_STEM)

MDX_NET_FREQ_CUT = [VOCAL_STEM, INST_STEM]

DEMUCS_4_STEM_OPTIONS = (ALL_STEMS, VOCAL_STEM, OTHER_STEM, BASS_STEM, DRUM_STEM)

DEMUCS_6_STEM_OPTIONS = (ALL_STEMS, VOCAL_STEM, OTHER_STEM, BASS_STEM, DRUM_STEM, GUITAR_STEM, PIANO_STEM)

SAVING_STEM = 'Saving ', ' stem...'

def secondary_stem(stem:str):
    """Determines secondary stem.

    Yaml configs often use lowercase ``vocals`` / ``instrumental`` while UVR's
    pair table is Title Case. Match case-insensitively so ``secondary_stem("vocals")``
    returns ``Instrumental`` rather than the bogus complement ``No vocals``.
    """
    stem = stem if stem else NO_STEM

    mapped = STEM_PAIR_MAPPER.get(stem)
    if mapped is None:
        stem_cf = stem.casefold()
        for key, value in STEM_PAIR_MAPPER.items():
            if key.casefold() == stem_cf:
                return value
        return stem.replace(NO_STEM, "") if NO_STEM in stem else f"{NO_STEM}{stem}"
    return mapped
