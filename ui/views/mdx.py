"""MDX-Net method view.

Covers both classic MDX-Net (``.onnx`` / ``.ckpt``) and MDX23C / MDX-C
(``config_yaml``) models: the latter live in the same model directory and are
auto-detected by :class:`core.ModelData` (``is_mdx_c``), so the
:class:`core.JobRunner` selects ``SeperateMDXC`` vs ``SeperateMDX`` at run
time. There is therefore one MDX model dropdown here, exactly as in the Tk app.
"""

from bundled.constants import (
    ALL_STEMS,
    BASS_STEM,
    BATCH_SIZE,
    BATCH_SIZE_HELP,
    COMPENSATE_HELP,
    DRUM_STEM,
    INST_STEM,
    IS_DEMUCS_COMBINE_STEMS_HELP,
    IS_DENOISE_HELP,
    IS_FREQUENCY_MATCH_HELP,
    IS_INVERT_SPEC_HELP,
    IS_SEGMENT_DEFAULT_HELP,
    MDX23_OVERLAP,
    MDX_ARCH_TYPE,
    MDX_DENOISE_OPTION,
    MDX_OVERLAP,
    MDX_SEGMENT_SIZE_HELP,
    OTHER_STEM,
    VOCAL_STEM,
    VOL_COMPENSATION,
)

from gi.repository import Adw, Gtk

from .base import MethodView, register_method_view
from ..help_text import MDX_OVERLAP_HINT, MDX_STEMS_HINT
from ..hints import set_tooltip
from ..widgets.rows import (
    get_scale_row_value,
    make_combo_row,
    reconfigure_discrete_scale,
    reconfigure_numeric_scale,
    set_combo_value,
    set_scale_row_value,
)
# Full stem universe presented in the UI. The backend intersects this with the
# selected model's actual stems, so checking a stem a model does not produce is
# simply ignored (resolving per-model stems here would require model hashing).
_MDX_STEM_OPTIONS = (
    VOCAL_STEM,
    INST_STEM,
    OTHER_STEM,
    BASS_STEM,
    DRUM_STEM,
    "Speech",
    "Music",
    "Sfx",
    "Effects",
)


@register_method_view
class MDXView(MethodView):
    method_key = MDX_ARCH_TYPE
    model_key = "mdx_net_model"
    stack_name = "mdx"
    title = "MDX-Net"
    secondary_prefix = "mdx"

    def list_models(self):
        return self.context.repo.list_mdx_models()

    def name_mapper(self):
        return self.context.repo.mdx_name_select_MAPPER

    def build_options(self, group):
        self.add_option_scale(
            group,
            "mdx_segment_size",
            "Segment size",
            lower=32,
            upper=4000,
            step=32,
            hint=MDX_SEGMENT_SIZE_HELP,
        )
        # Overlap range follows the selected model type: classic MDX-Net uses a
        # small discrete set, MDX23C models use integers 2-50.
        self._overlap_is_mdx_c = False
        from ..widgets.rows import make_discrete_scale_row

        self.overlap_row = make_discrete_scale_row("Overlap", [str(v) for v in MDX_OVERLAP])
        self.overlap_row._uvr_scale.connect("value-changed", self._on_overlap_changed)
        group.add(self.overlap_row)
        self.hints.register(self.overlap_row, MDX_OVERLAP_HINT)

    def _overlap_key(self):
        return "overlap_mdx23" if self._overlap_is_mdx_c else "overlap_mdx"

    def _on_overlap_changed(self, *_args):
        if self._loading:
            return
        value = get_scale_row_value(self.overlap_row)
        if value is not None:
            self.settings.set(self._overlap_key(), value)
            self._on_settings_changed()

    def _refresh_overlap(self):
        """Reconfigure the overlap slider for the current model type."""
        stored = self.settings.get(self._overlap_key())
        was_loading = self._loading
        self._loading = True
        try:
            if self._overlap_is_mdx_c:
                reconfigure_numeric_scale(self.overlap_row, 2, max(MDX23_OVERLAP), step=1, digits=0)
            else:
                reconfigure_discrete_scale(self.overlap_row, [str(v) for v in MDX_OVERLAP])
            if stored is None or not set_scale_row_value(self.overlap_row, str(stored)):
                if self._overlap_is_mdx_c:
                    set_scale_row_value(self.overlap_row, "2")
                else:
                    set_scale_row_value(self.overlap_row, str(MDX_OVERLAP[0]))
        finally:
            self._loading = was_loading

    def _on_model_resolved(self, model):
        self._overlap_is_mdx_c = bool(model and getattr(model, "is_mdx_c", False))
        self._refresh_overlap()
        stems = list(getattr(model, "mdx_model_stems", []) or []) if model else []
        # Match upstream UVR ``update_button_states_mdx``: 2-stem models use the
        # primary stem name in ``mdx_stems``, not ``All Stems`` (that value is
        # only meaningful for 3+ stem MDX23C models).
        if 0 < len(stems) < 3:
            self.settings.set("mdx_stems", stems[0])
        elif len(stems) >= 3 and self.settings.get("mdx_stems") not in (*stems, ALL_STEMS):
            self.settings.set("mdx_stems", ALL_STEMS)
        self._rebuild_stem_toggles(model)

    def build_stem_options(self, group):
        # The save-stem toggles are built dynamically from the *selected model's*
        # actual stems (see _rebuild_stem_toggles, driven by _on_model_resolved):
        # one ``Gtk.ToggleButton`` per stem the model produces, laid out in an
        # ``Adw.WrapBox`` so they reflow on narrow windows. For classic / 2-stem
        # MDX models (or no model) the multi-select doesn't apply and the box is
        # hidden -- the primary/secondary "Only" toggles above cover those.
        # ``self._stem_switches`` maps stem name -> ``Gtk.ToggleButton`` (whose
        # change signal is ``"toggled"``).
        self._stem_switches = {}
        self._stem_box = Adw.WrapBox()
        self._stem_box.set_child_spacing(6)
        self._stem_box.set_line_spacing(6)
        self._stem_box.set_margin_top(6)
        self._stem_box.set_margin_bottom(6)
        self._stem_box.set_margin_start(12)
        self._stem_box.set_margin_end(12)
        self._stem_box.set_visible(False)
        group.add(self._stem_box)
        self.hints.register(self._stem_box, MDX_STEMS_HINT)

    def _stored_selected_stems(self):
        selected = self.settings.get("mdx_stems_selected") or []
        # Backward compat: no subset stored but a specific legacy stem chosen.
        if not selected:
            legacy = self.settings.get("mdx_stems")
            if legacy and legacy != ALL_STEMS:
                selected = [legacy]
        return set(selected)

    def _rebuild_stem_toggles(self, model):
        """Rebuild the save-stem toggles for the resolved model's stems.

        Only multi-stem MDX23C models expose a meaningful subset choice; for
        anything else the toggle box is cleared and hidden.
        """
        stems = list(getattr(model, "mdx_model_stems", []) or []) if model else []
        # Order known stems consistently, then append any extras (e.g. guitar).
        ordered = [s for s in _MDX_STEM_OPTIONS if s in stems]
        ordered += [s for s in stems if s not in _MDX_STEM_OPTIONS]

        child = self._stem_box.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self._stem_box.remove(child)
            child = nxt
        self._stem_switches = {}

        # The per-stem multi-select only applies to true multi-stem models
        # (>2 stems), matching the backend's subset path (separate.py). It is
        # mutually exclusive with the primary/secondary "Only" switches: a
        # multi-stem model is governed by the per-stem selection, a <=2-stem /
        # classic model by the "Only" switches. Showing both at once would be
        # contradictory (and the backend ignores the "Only" flags on the
        # all/subset export path), so only one set is visible at a time.
        multi = len(ordered) > 2
        self.stem_only.set_visible(not multi)

        if not multi:
            self._stem_box.set_visible(False)
            return

        selected = self._stored_selected_stems()
        was_loading = self._loading
        self._loading = True
        try:
            for stem in ordered:
                button = Gtk.ToggleButton(label=stem, valign=Gtk.Align.CENTER)
                set_tooltip(button, MDX_STEMS_HINT)
                button.set_active(stem in selected)
                button.connect("toggled", self._on_stem_switch)
                self._stem_box.append(button)
                self._stem_switches[stem] = button
        finally:
            self._loading = was_loading
        self._stem_box.set_visible(True)

    def _selected_stems(self):
        return [stem for stem, row in self._stem_switches.items() if row.get_active()]

    def _on_stem_switch(self, *_args):
        if self._loading:
            return
        selected = self._selected_stems()
        self.settings.set("mdx_stems_selected", selected)
        self.settings.set("mdx_stems", selected[0] if len(selected) == 1 else ALL_STEMS)
        self._on_settings_changed()

    def load_options(self):
        super().load_options()
        # The stem toggles are (re)built by _on_model_resolved once the selected
        # model is dry-resolved (at the end of MethodView.load()).

    def save_options(self):
        super().save_options()
        # Only persist the subset when the multi-select is actually shown for the
        # current model; otherwise leave the stored selection untouched so it is
        # not wiped by switching to a classic/2-stem model.
        if self._stem_switches:
            selected = self._selected_stems()
            self.settings.set("mdx_stems_selected", selected)
            self.settings.set("mdx_stems", selected[0] if len(selected) == 1 else ALL_STEMS)
        overlap_value = get_scale_row_value(self.overlap_row)
        if overlap_value is not None:
            self.settings.set(self._overlap_key(), overlap_value)

    def build_advanced(self, expander):
        self.add_advanced_scale("mdx_batch_size", "Batch size", values=BATCH_SIZE, hint=BATCH_SIZE_HELP)
        self.add_option_combo(expander, "denoise_option", "Denoise", MDX_DENOISE_OPTION, hint=IS_DENOISE_HELP)
        self.add_option_scale(expander, "compensate", "Volume compensation", values=VOL_COMPENSATION, hint=COMPENSATE_HELP)
        self.add_option_switch(expander, "is_match_frequency_pitch", "Match frequency cut-off", hint=IS_FREQUENCY_MATCH_HELP)
        self.add_option_switch(expander, "is_invert_spec", "Spectral inversion", hint=IS_INVERT_SPEC_HELP)
        self.add_option_switch(expander, "is_mdx_c_seg_def", "MDX-C default segment size", hint=IS_SEGMENT_DEFAULT_HELP)
        self.add_option_switch(expander, "is_mdx23_combine_stems", "Combine stems (MDX23C)", hint=IS_DEMUCS_COMBINE_STEMS_HELP)
