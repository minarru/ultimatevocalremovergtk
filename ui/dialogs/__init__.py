"""GTK dialogs owned by the method views (Phase 3).

Contains the model-parameter dialogs that replace ``UVR.py``'s Tk popups:

* :func:`~ui.dialogs.model_params.make_unrecognized_handler` - builds the
  :attr:`core.ModelRepository.on_unrecognized_model` hook so an unknown
  model (its MD5 missing from the mapper JSONs) prompts for parameters and
  persists them next to the model-data cache.
* :func:`~ui.dialogs.model_params.show_change_defaults_dialog` - the
  change-model-defaults editor (edit / delete a model's stored parameters).
"""
