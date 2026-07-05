"""Model-parameter dialogs (GTK4 / libadwaita port of UVR's Tk popups).

Two flows from ``UVR.py`` are reproduced here, both writing to the *same*
``model_data`` cache the Tk app uses (``<hash>.json`` inside the per-arch
``model_data`` directory):

* **Unrecognized model** - when a model's MD5 is not in the mapper JSON,
  :func:`make_unrecognized_handler` returns the callable installed on
  :attr:`core.ModelRepository.on_unrecognized_model`. It prompts for the
  architecture-specific parameters (VR: stem / param file / 5.1 channels;
  MDX-Net: stem / dim_f / dim_t / n_fft / compensate; MDX-C: config yaml),
  persists them, and returns the dict ``ModelData`` expects.
* **Change model defaults** - :func:`show_change_defaults_dialog` lets the user
  pick a known model and edit or delete its stored parameters.

The parameter dialog is synchronous (it returns the chosen parameters to the
``ModelData`` constructor). It uses :class:`Adw.Dialog` with a nested
:class:`GLib.MainLoop`; when the request originates on the separation worker
thread it is marshalled onto the GTK main loop and the worker blocks until the
user responds.
"""

import json
import os
import threading

from gi.repository import Adw, GLib, Gtk

from bundled.constants import (
    BALANCE_VALUES,
    CHANGE_MODEL_DEFAULTS_TEXT,
    CKPT,
    DEFINED_PARAMETERS_DELETED_TEXT,
    DELETE_PARAMETERS_TEXT,
    IS_BV_MODEL,
    IS_BV_MODEL_REBAL,
    IS_KARAOKEE,
    INST_STEM,
    MDX_ARCH_TYPE,
    MDX_POP_DIMF,
    MDX_POP_NFFT,
    NO_MODEL,
    NONE_SELECTED,
    NOUT_LSTM_SEL,
    NOUT_SEL,
    ROFORMER_MODEL_HELP,
    ROFORMER_MODEL_TEXT,
    STEM_SET_MENU,
    VOCAL_STEM,
    VR_ARCH_TYPE,
)

from core import paths
from core.model_data import ModelData
from ..hints import set_tooltip
from .utils import present_modal_dialog, run_blocking_dialog, set_dialog_content, set_form_dialog_content
from ..widgets.rows import (
    get_combo_value,
    get_scale_row_value,
    make_combo_row,
    make_discrete_scale_row,
    set_combo_value,
    set_scale_row_value,
)


# ---------------------------------------------------------------------------
# Thread marshalling
# ---------------------------------------------------------------------------

def _run_on_main(func):
    """Run ``func`` on the GTK main loop and return its result (blocking)."""
    if threading.current_thread() is threading.main_thread():
        return func()

    box = {}
    done = threading.Event()

    def invoke():
        try:
            box["value"] = func()
        finally:
            done.set()
        return GLib.SOURCE_REMOVE

    GLib.idle_add(invoke)
    done.wait()
    return box.get("value")


# ---------------------------------------------------------------------------
# Existing-parameter lookup (for change-defaults prefill)
# ---------------------------------------------------------------------------

def _hash_dir_for(process_method):
    if process_method == VR_ARCH_TYPE:
        return paths.VR_HASH_DIR
    if process_method == MDX_ARCH_TYPE:
        return paths.MDX_HASH_DIR
    return None


def _existing_params(context, model_data):
    """Return the model's currently-stored parameters, if any."""
    hash_dir = _hash_dir_for(model_data.process_method)
    if not hash_dir or not model_data.model_hash:
        return None
    json_path = os.path.join(hash_dir, f"{model_data.model_hash}.json")
    if os.path.isfile(json_path):
        try:
            with open(json_path, "r") as handle:
                return json.load(handle)
        except (ValueError, OSError):
            return None
    mapper = context.repo.vr_hash_MAPPER if model_data.process_method == VR_ARCH_TYPE else context.repo.mdx_hash_MAPPER
    for stored_hash, stored in mapper.items():
        if model_data.model_hash in stored_hash:
            return stored
    return None


def _write_params(model_data, params):
    """Persist ``params`` to ``<hash>.json`` next to the model-data cache."""
    hash_dir = _hash_dir_for(model_data.process_method)
    if not hash_dir or not model_data.model_hash:
        return
    os.makedirs(hash_dir, exist_ok=True)
    with open(os.path.join(hash_dir, f"{model_data.model_hash}.json"), "w") as handle:
        handle.write(json.dumps(params, indent=4))


def _list_param_files(directory, extension):
    if not os.path.isdir(directory):
        return []
    return sorted(os.path.splitext(name)[0] for name in os.listdir(directory) if name.endswith(extension))


# ---------------------------------------------------------------------------
# Parameter dialog
# ---------------------------------------------------------------------------

class _ParamDialog:
    """Modal parameter editor returning the chosen params dict (or ``None``)."""

    def __init__(self, context, parent, model_data, existing=None):
        self.context = context
        self.parent = parent
        self.model_data = model_data
        self.existing = existing or {}

        self.dialog = Adw.Dialog()
        self.dialog.set_title("Specify Model Parameters")
        self.dialog.set_content_width(440)
        self.dialog.set_follows_content_size(True)

        page = Adw.PreferencesPage()
        self._build(page)
        self._content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._content.set_margin_top(12)
        self._content.set_margin_bottom(12)
        self._content.set_margin_start(12)
        self._content.set_margin_end(12)
        self._content.append(page)

    # -- Layout -------------------------------------------------------------

    def _build(self, page):
        method = self.model_data.process_method
        is_ckpt = getattr(self.model_data, "is_mdx_ckpt", False) or str(self.model_data.model_path).endswith(CKPT)
        group = Adw.PreferencesGroup(
            title=f"{self.model_data.model_name}",
            description="This model's parameters could not be detected automatically.",
        )
        page.add(group)

        if method == VR_ARCH_TYPE:
            self._build_vr(group)
        elif method == MDX_ARCH_TYPE and is_ckpt:
            self._build_mdx_c(group)
        else:
            self._build_mdx(group)

    def _add_stem_row(self, group):
        self.stem_row = make_combo_row("Primary stem", list(STEM_SET_MENU))
        set_combo_value(self.stem_row, self.existing.get("primary_stem", VOCAL_STEM))
        group.add(self.stem_row)

    def _add_karaoke_rows(self, group):
        self.kara_row = Adw.SwitchRow(title="Karaoke model")
        self.kara_row.set_active(bool(self.existing.get(IS_KARAOKEE, False)))
        group.add(self.kara_row)
        self.bv_row = Adw.SwitchRow(title="Backing-vocal model")
        self.bv_row.set_active(bool(self.existing.get(IS_BV_MODEL, False)))
        group.add(self.bv_row)
        self.balance_row = make_discrete_scale_row("BV rebalance", [str(v) for v in BALANCE_VALUES])
        set_scale_row_value(self.balance_row, str(self.existing.get(IS_BV_MODEL_REBAL, 0)))
        group.add(self.balance_row)

    def _build_vr(self, group):
        self._add_stem_row(group)
        params = _list_param_files(paths.VR_PARAM_DIR, ".json") or [NONE_SELECTED]
        self.vr_param_row = make_combo_row("Model parameters", params)
        set_combo_value(self.vr_param_row, self.existing.get("vr_model_param", params[0]))
        group.add(self.vr_param_row)

        self.is_51_row = Adw.SwitchRow(title="VR 5.1 model")
        self.is_51_row.set_active("nout" in self.existing)
        group.add(self.is_51_row)
        self.nout_row = make_discrete_scale_row("Out channels", [str(v) for v in NOUT_SEL])
        set_scale_row_value(self.nout_row, str(self.existing.get("nout", 32)))
        group.add(self.nout_row)
        self.nout_lstm_row = make_discrete_scale_row("Out channels (LSTM)", [str(v) for v in NOUT_LSTM_SEL])
        set_scale_row_value(self.nout_lstm_row, str(self.existing.get("nout_lstm", 128)))
        group.add(self.nout_lstm_row)

        self._add_karaoke_rows(group)

    def _build_mdx(self, group):
        self._add_stem_row(group)
        detected = self._detect_mdx_shapes()
        self.dim_f_row = self._entry_row("Dim_f", self.existing.get("mdx_dim_f_set", detected.get("dim_f", MDX_POP_DIMF[0])))
        group.add(self.dim_f_row)
        self.dim_t_row = self._entry_row("Dim_t", self.existing.get("mdx_dim_t_set", detected.get("dim_t", "8")))
        group.add(self.dim_t_row)
        self.n_fft_row = self._entry_row("N_FFT scale", self.existing.get("mdx_n_fft_scale_set", detected.get("n_fft", MDX_POP_NFFT[2])))
        group.add(self.n_fft_row)
        self.compensate_row = self._entry_row("Volume compensation", self.existing.get("compensate", "1.035"))
        group.add(self.compensate_row)
        self._add_karaoke_rows(group)

    def _build_mdx_c(self, group):
        yamls = _list_param_files(paths.MDX_C_CONFIG_PATH, ".yaml") or [NONE_SELECTED]
        self.mdx_c_row = make_combo_row("Model configuration", yamls)
        existing_yaml = self.existing.get("config_yaml", "")
        if existing_yaml:
            set_combo_value(self.mdx_c_row, os.path.splitext(existing_yaml)[0])
        group.add(self.mdx_c_row)
        # BS-Roformer / Mel-Band Roformer models share the MDX-C yaml-config flow
        # but need ``is_roformer`` set so the engine builds the roformer net.
        self.is_roformer_row = Adw.SwitchRow(title=ROFORMER_MODEL_TEXT)
        set_tooltip(self.is_roformer_row, ROFORMER_MODEL_HELP)
        self.is_roformer_row.set_active(bool(self.existing.get("is_roformer", False)))
        group.add(self.is_roformer_row)
        self.stem_row = None  # not used for MDX-C

    @staticmethod
    def _entry_row(title, value):
        row = Adw.EntryRow(title=title)
        row.set_text(str(value))
        return row

    def _detect_mdx_shapes(self):
        """Best-effort prefill of MDX-Net shapes from the ONNX graph."""
        try:
            import math

            import onnx

            model = onnx.load(self.model_data.model_path)
            shapes = [[d.dim_value for d in inp.type.tensor_type.shape.dim] for inp in model.graph.input][0]
            return {"dim_f": str(shapes[2]), "dim_t": str(int(math.log(shapes[3], 2))), "n_fft": "6144"}
        except Exception:
            return {}

    # -- Collection ---------------------------------------------------------

    def _collect(self):
        method = self.model_data.process_method
        is_ckpt = getattr(self.model_data, "is_mdx_ckpt", False) or str(self.model_data.model_path).endswith(CKPT)
        if method == VR_ARCH_TYPE:
            return self._collect_vr()
        if method == MDX_ARCH_TYPE and is_ckpt:
            return self._collect_mdx_c()
        return self._collect_mdx()

    def _karaoke_values(self):
        try:
            balance = float(get_scale_row_value(self.balance_row) or 0)
        except (TypeError, ValueError):
            balance = 0.0
        return {
            IS_KARAOKEE: bool(self.kara_row.get_active()),
            IS_BV_MODEL: bool(self.bv_row.get_active()),
            IS_BV_MODEL_REBAL: balance,
        }

    def _collect_vr(self):
        param = get_combo_value(self.vr_param_row)
        if not param or param == NONE_SELECTED:
            return None
        params = {"vr_model_param": param, "primary_stem": get_combo_value(self.stem_row)}
        if self.is_51_row.get_active():
            nout = get_scale_row_value(self.nout_row)
            nout_lstm = get_scale_row_value(self.nout_lstm_row)
            if nout is None or nout_lstm is None:
                return None
            params["nout"] = int(nout)
            params["nout_lstm"] = int(nout_lstm)
        params.update(self._karaoke_values())
        return params

    def _collect_mdx(self):
        try:
            params = {
                "compensate": float(self.compensate_row.get_text()),
                "mdx_dim_f_set": int(self.dim_f_row.get_text()),
                "mdx_dim_t_set": int(self.dim_t_row.get_text()),
                "mdx_n_fft_scale_set": int(self.n_fft_row.get_text()),
                "primary_stem": get_combo_value(self.stem_row),
            }
        except (TypeError, ValueError):
            return None
        params.update(self._karaoke_values())
        return params

    def _collect_mdx_c(self):
        selected = get_combo_value(self.mdx_c_row)
        if not selected or selected == NONE_SELECTED:
            return None
        return {"config_yaml": f"{selected}.yaml", "is_roformer": bool(self.is_roformer_row.get_active())}

    def run(self):
        result = run_blocking_dialog(
            self.dialog,
            self.parent,
            content=self._content,
            collect=self._collect,
        )
        if result is not None:
            _write_params(self.model_data, result)
        return result


def _run_param_dialog(context, parent, model_data):
    existing = _existing_params(context, model_data)
    dialog = _ParamDialog(context, parent, model_data, existing=existing)
    result = dialog.run()
    if result is not None:
        context.repo.invalidate_stem_check()
    return result


def make_unrecognized_handler(context, get_parent):
    """Build the ``on_unrecognized_model`` hook (runs the dialog on the UI loop)."""

    def handler(model_data):
        return _run_on_main(lambda: _run_param_dialog(context, get_parent(), model_data))

    return handler


# ---------------------------------------------------------------------------
# Apollo (music restoration) unrecognized-model dialog
# ---------------------------------------------------------------------------

class _ApolloParamDialog:
    """Modal picker mapping an unrecognized Apollo model to a config yaml.

    Returns ``{"config_yaml": "<name>.yaml"}`` on confirm, or ``None`` on
    cancel. The backend (:class:`core.apollo.ApolloModelData`) persists the
    returned dict to ``<hash>.json`` so the model is recognised next time.
    """

    def __init__(self, parent, apollo_model_data):
        from bundled.constants import (
            APOLLO_MODEL_PARAMETERS_TEXT,
            NONE_SELECTED,
            YAML,
        )
        from core.apollo import list_config_files

        self._yaml_ext = YAML
        self._none = NONE_SELECTED
        self.parent = parent

        self.dialog = Adw.Dialog()
        self.dialog.set_title(APOLLO_MODEL_PARAMETERS_TEXT)
        self.dialog.set_content_width(440)
        self.dialog.set_follows_content_size(True)

        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup(
            title=apollo_model_data.apollo_model_name,
            description="This model's parameters could not be detected automatically.",
        )
        page.add(group)

        configs = list_config_files() or [self._none]
        self.config_row = make_combo_row("Model configuration", configs)
        group.add(self.config_row)

        self._content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._content.set_margin_top(12)
        self._content.set_margin_bottom(12)
        self._content.set_margin_start(12)
        self._content.set_margin_end(12)
        self._content.append(page)

    def _collect(self):
        selected = get_combo_value(self.config_row)
        if not selected or selected == self._none:
            return None
        return {"config_yaml": f"{selected}{self._yaml_ext}"}

    def run(self):
        return run_blocking_dialog(
            self.dialog,
            self.parent,
            content=self._content,
            collect=self._collect,
        )


def make_apollo_unrecognized_handler(get_parent):
    """Build the Apollo ``on_unrecognized`` hook (runs the dialog on the UI loop)."""

    def handler(apollo_model_data):
        return _run_on_main(lambda: _ApolloParamDialog(get_parent(), apollo_model_data).run())

    return handler


# ---------------------------------------------------------------------------
# Change-model-defaults dialog
# ---------------------------------------------------------------------------

def show_change_defaults_dialog(context, parent):
    """Modal editor to change or delete a known model's stored parameters."""
    repo = context.repo
    settings = context.settings

    dialog = Adw.Dialog()
    dialog.set_title(CHANGE_MODEL_DEFAULTS_TEXT)
    dialog.set_content_width(440)
    dialog.set_follows_content_size(True)

    toast_overlay = Adw.ToastOverlay()

    description = Gtk.Label(
        label="Select a VR or MDX-Net model to edit or delete its stored parameters.",
        wrap=True,
        xalign=0.0,
    )
    description.add_css_class("dim-label")

    page = Adw.PreferencesPage()

    model_group = Adw.PreferencesGroup()
    model_tags = repo.default_change_model_tags()
    model_row = make_combo_row("Model", [NO_MODEL, *model_tags])
    model_group.add(model_row)
    page.add(model_group)

    button_group = Adw.PreferencesGroup()
    page.add(button_group)

    def toast(message: str) -> None:
        toast_overlay.add_toast(Adw.Toast.new(message))

    def selected_model_data(is_get_hash_dir_only=False):
        tag = get_combo_value(model_row)
        if not tag or tag == NO_MODEL:
            return None
        return ModelData(settings, repo, tag, is_dry_check=True, is_get_hash_dir_only=is_get_hash_dir_only)

    def on_change(_button):
        model_data = selected_model_data()
        if model_data is None:
            toast("Select a model first.")
            return
        params = _run_param_dialog(context, parent, model_data)
        if params:
            toast("Model parameters changed.")
        else:
            toast("No changes made.")

    def on_delete(_button):
        model_data = selected_model_data(is_get_hash_dir_only=True)
        if model_data is None:
            toast("Select a model first.")
            return
        hash_file = model_data.model_hash_dir
        if hash_file and os.path.isfile(hash_file):
            os.remove(hash_file)
            repo.invalidate_stem_check()
            toast(DEFINED_PARAMETERS_DELETED_TEXT)
        else:
            toast("No defined parameters found.")

    change_row = Adw.ActionRow(title="Change parameters")
    change_button = Gtk.Button(label="Change\u2026", valign=Gtk.Align.CENTER)
    change_button.add_css_class("suggested-action")
    change_button.connect("clicked", on_change)
    change_row.add_suffix(change_button)
    change_row.set_activatable_widget(change_button)
    button_group.add(change_row)

    delete_row = Adw.ActionRow(title=DELETE_PARAMETERS_TEXT)
    delete_button = Gtk.Button(label="Delete", valign=Gtk.Align.CENTER)
    delete_button.add_css_class("destructive-action")
    delete_button.connect("clicked", on_delete)
    delete_row.add_suffix(delete_button)
    delete_row.set_activatable_widget(delete_button)
    button_group.add(delete_row)

    content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    content.set_margin_top(12)
    content.set_margin_bottom(12)
    content.set_margin_start(12)
    content.set_margin_end(12)
    content.append(description)
    content.append(page)

    toast_overlay.set_child(content)

    set_dialog_content(dialog, toast_overlay)
    present_modal_dialog(dialog, parent)
