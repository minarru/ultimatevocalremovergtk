from .platform_info import LICENSE_OS_SPECIFIC_TEXT

NO_CONNECTION = 'No Internet Connection'

LEGACY_ADDITIONAL_REPO_SELECTION = 'VIP:'

NO_NEW_MODELS = 'All Available Models Downloaded'

NO_MODEL = 'No Model Selected'

CHOOSE_MODEL = 'Choose Model'

IS_BV_MODEL_REBAL = "is_bv_model_rebalanced"

STOP_PROCESSING = 'Halting process, please wait...'

LICENSE_TEXT = lambda a, u:f'Current Application Version: Ultimate Vocal Remover GTK {a}\n' +\
               f'Based on upstream UVR {u}\n\n' +\
               'Copyright (c) 2022 Ultimate Vocal Remover\n\n' +\
               'UVR is free and open-source, but MIT licensed. Please credit us if you use our\n' +\
               f'models or code for projects unrelated to UVR.\n\n{LICENSE_OS_SPECIFIC_TEXT}' +\
               'This bundle contains the UVR interface, Python, PyTorch, and other\n' +\
               'dependencies needed to run the application effectively.\n\n' +\
               'Website Links: This application, System or Service(s) may contain links to\n' +\
               'other websites and downloads, and they are solely provided to you as an\n' +\
               'additional convenience. You understand and acknowledge that by clicking\n' +\
               'or activating such links you are accessing a site or service outside of\n' +\
               'this application, and that we do not screen, review, approve, or otherwise\n' +\
               'endorse any content or information contained in these linked websites.\n' +\
               'You acknowledge and agree that we, our affiliates and partners are not\n' +\
               'responsible for the contents of any of these linked websites, including\n' +\
               'the accuracy or availability of information provided by the linked websites,\n' +\
               'and we make no representations or warranties regarding your use of\n' +\
               'the linked websites.\n\n' +\
               'This application is MIT Licensed\n\n' +\
               'Permission is hereby granted, free of charge, to any person obtaining a copy\n' +\
               'of this software and associated documentation files (the "Software"), to deal\n' +\
               'in the Software without restriction, including without limitation the rights\n' +\
               'to use, copy, modify, merge, publish, distribute, sublicense, and/or sell\n' +\
               'copies of the Software, and to permit persons to whom the Software is\n' +\
               'furnished to do so, subject to the following conditions:\n\n' +\
               'The above copyright notice and this permission notice shall be included in all\n' +\
               'copies or substantial portions of the Software.\n\n' +\
               'THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR\n' +\
               'IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,\n' +\
               'FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE\n' +\
               'AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER\n' +\
               'LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,\n' +\
               'OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE\n' +\
               'SOFTWARE.'

APOLLO_MODEL_PARAMETERS_TEXT = 'Apollo Model Parameters'

APOLLO_MODEL_FAIL_TEXT = 'Apollo model not valid.\n'

STOP_PROCESS_CONFIRM = 'Confirmation', 'You are about to stop all active processes.\n\nAre you sure you wish to continue?'

QUIT_WHILE_PROCESSING_CONFIRM = (
    'Stop Processing?',
    'Processing is still in progress. Stop and quit the application?',
)

# Separation Text
LOADING_MODEL = 'Loading model...'

INFERENCE_STEP_1 = 'Running inference...'

INFERENCE_STEP_1_SEC = 'Running inference (secondary model)...'

INFERENCE_STEP_1_PRE = 'Running inference (pre-process model)...'

INFERENCE_STEP_1_VOC_S = 'Splitting vocals...'

INFERENCE_STEP_2_PRE = lambda pm, m:f'Loading pre-process model ({pm}: {m})...'

INFERENCE_STEP_2_SEC = lambda pm, m:f'Loading secondary model ({pm}: {m})...'

INFERENCE_STEP_2_VOC_S = lambda pm, m:f'Loading vocal splitter model ({pm}: {m})...'

INFERENCE_STEP_2_SEC_CACHED_MODOEL = lambda pm, m:f'Secondary model ({pm}: {m}) cache loaded.\n'

INFERENCE_STEP_2_PRE_CACHED_MODOEL = lambda pm, m:f'Pre-process model ({pm}: {m}) cache loaded.\n'

INFERENCE_STEP_2_PRIMARY_CACHED = ' Model cache loaded.\n'

INFERENCE_STEP_DEVERBING = ' Deverbing...'

DONE = ' Done!\n'

NONE_SELECTED = 'None Selected'

CHANGE_MODEL_DEFAULTS_TEXT = 'Change Model Defaults'

DEFINED_PARAMETERS_DELETED_TEXT = 'Defined Parameters Deleted'

DELETE_PARAMETERS_TEXT = 'Delete Parameters'

ROFORMER_MODEL_TEXT = 'Roformer Model'

VERIFY_INPUTS_TEXT = 'Verify Inputs'

AUDIO_INPUT_TOTAL_TEXT = 'Audio Input Total'

LOADING_VERSION_INFO_TEXT = 'Loading version information...'

INFO_UNAVAILABLE_TEXT = "Information unavailable."

PROCESS_STOPPED_BY_USER = '\n\nProcess stopped by user.\n'
