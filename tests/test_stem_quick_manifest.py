"""Exercise every declared stem context through the shared quick-selection owner."""

import unittest

import numpy as np

from bundled.constants import ALL_STEMS
from core.model_stem_manifest import load_bundled_stem_semantics, resolve_model_stem_semantics
from core.settings import Settings
from core.stem_roles import StemProcessingContext
from core.stem_selection import StemSelectionState
from core.stems import _semantic_routes
from engines.demucs_export import DemucsExportRequest, DemucsNativeResult, plan_demucs_export
from tests.stem_control_cases import resolved_demucs_model, resolved_mdx_model
from tests.test_stem_control_contract import mdxc_plan, scheduled_routes
from ui.stem_controls import StemControls


def controls_for(model_id: str, context: StemProcessingContext) -> StemControls:
    registry = load_bundled_stem_semantics()
    declaration = registry.models[model_id]
    signature = declaration.native_signature
    semantics = resolve_model_stem_semantics(
        model_id,
        native_stems=signature,
        backend_primary=signature[0] if signature else "",
        context=context,
        registry=registry,
    )
    routes = _semantic_routes(semantics)
    natives = [r.native.raw for r in routes if r.native]
    state = StemSelectionState()
    if model_id.startswith("demucs:") and len(natives) > 2:
        state.configure_demucs(
            focus_stems=[ALL_STEMS, *natives],
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
        )
    elif len(natives) > 2:
        state.configure_subset(
            stems=natives,
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
        )
    else:
        state.configure_exclusive(
            primary_stem=natives[0] if natives else "",
            secondary_stem="",
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
        )
    state.routes = routes
    controls = StemControls(state, model_id=model_id)
    controls.sync_from_settings(Settings.defaults())
    return controls


class ManifestQuickSelectionTests(unittest.TestCase):
    def test_every_context_action_round_trips_without_changing_selected_outputs(self):
        registry = load_bundled_stem_semantics()
        for model_id, declaration in registry.models.items():
            for context in declaration.contexts:
                initial = controls_for(model_id, context).snapshot()
                self.assertLessEqual(len(initial.presets), 3, model_id)
                tooltips = dict(initial.tooltips)
                for ident, label in (*initial.presets, *initial.selection_actions):
                    with self.subTest(model=model_id, context=context.value, action=label):
                        self.assertTrue(tooltips.get(ident), "Selection needs an explanation")
                        controls = controls_for(model_id, context)
                        settings = Settings.defaults()
                        self.assertTrue(controls.choose_preset(ident))
                        selected = controls.snapshot().selected_ids
                        self.assertTrue(selected)
                        controls.persist_to_settings(settings)
                        controls.sync_from_settings(settings)
                        self.assertFalse(controls.snapshot().review_required)
                        self.assertEqual(controls.snapshot().selected_ids, selected)
                        if ident == "separate_non_vocal":
                            self.assertTrue(
                                all(
                                    c.route.native is not None
                                    and not c.route.concept.startswith("vocal.")
                                    for c in controls.snapshot().choices
                                    if c.selected
                                )
                            )

    def test_every_full_mix_instrumental_shortcut_reaches_one_export(self):
        for model_id in load_bundled_stem_semantics().models:
            controls = controls_for(model_id, StemProcessingContext.FULL_MIX)
            ident = next(
                (i for i, label in controls.snapshot().presets if label == "Instrumental mix"), None
            )
            if ident is None:
                continue
            with self.subTest(model=model_id):
                settings = Settings.defaults()
                self.assertTrue(controls.choose_preset(ident))
                controls.persist_to_settings(settings)
                if model_id.startswith("demucs:"):
                    model = resolved_demucs_model(model_id, settings)
                    mapping = model.demucs_source_map
                    sources = np.stack([np.full((2, 8), i + 1.0) for i in range(len(mapping))])
                    plan = plan_demucs_export(
                        DemucsExportRequest(
                            native=DemucsNativeResult(sources, None, mapping),
                            routes=model.selected_stem_routes,
                            available_routes=model.available_stem_routes,
                            write_all_sources=True,
                            blend=lambda src, secondary=None: src,
                            blended_sources={
                                name: sources[index].T for name, index in mapping.items()
                            },
                        )
                    )
                else:
                    model = resolved_mdx_model(model_id, settings)
                    plan = mdxc_plan(model, combine=True, invert=False)
                self.assertEqual(len(model.selected_stem_routes), 1)
                self.assertEqual(model.selected_stem_routes[0].concept, "mix.instrumental")
                self.assertEqual(scheduled_routes(model, plan), model.selected_stem_routes)
