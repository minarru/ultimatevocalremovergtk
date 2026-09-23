"""Live typed/legacy ownership, including the run-local OOM override."""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from bundled.constants import CHOOSE_MODEL, MDX_ARCH_TYPE, VR_ARCH_TYPE
from core.model_config import ModelConfig
from core.settings import Settings


def partial_model(family: str = MDX_ARCH_TYPE) -> ModelConfig:
    repo = MagicMock()
    repo.mdx_name_select_MAPPER = {}
    repo.model_hash_table = {}
    return ModelConfig(Settings(), repo, CHOOSE_MODEL, family, is_dry_check=True)


class ModelOptionParityTests(unittest.TestCase):
    def test_segment_writes_share_one_value(self):
        model = partial_model()
        assert model.mdx_options is not None
        model.mdx_segment_size = 128
        self.assertEqual(model.mdx_options.mdx_segment_size, 128)
        model.mdx_options.mdx_segment_size = 64
        self.assertEqual(model.mdx_segment_size, 64)

    def test_device_aliases_share_one_value(self):
        model = partial_model()
        assert model.mdx_options is not None
        model.device_options.use_gpu = True
        self.assertIs(model.use_gpu, True)
        self.assertIs(model.is_gpu_conversion, True)
        model.is_gpu_conversion = False
        self.assertIs(model.device_options.use_gpu, False)

    def test_native_list_mutation_and_replacement_preserve_references(self):
        model = partial_model()
        assert model.mdx_options is not None
        original = model.mdx_model_stems
        original.append('vocals')
        self.assertEqual(model.stem_routing.mdx_model_stems, ('vocals',))
        self.assertEqual(model.mdx_options.mdx_model_stems, ('vocals',))
        replacement = ['drums', 'bass']
        model.mdx_model_stems = replacement
        self.assertIs(model.mdx_model_stems, replacement)
        self.assertEqual(original, ['vocals'])
        model.mdx_options.mdx_model_stems = ('other',)
        self.assertEqual(replacement, ['drums', 'bass'])
        self.assertEqual(model.mdx_model_stems, ['other'])
        self.assertEqual(model.stem_routing.mdx_model_stems, ('other',))

    def test_sequence_owners_keep_legacy_lists_and_typed_tuples(self):
        model = partial_model()
        assert model.mdx_options is not None
        for field, owner in (
            ('mdxnet_stems_selected', model.mdx_options),
            ('secondary_model_4_stem', model.secondary_chain),
            ('secondary_model_4_stem_scale', model.secondary_chain),
            ('secondary_model_4_stem_names', model.secondary_chain),
        ):
            with self.subTest(field=field):
                old = getattr(model, field)
                old.append(None)
                self.assertEqual(getattr(owner, field), (None,))
                setattr(owner, field, ('replacement',))
                self.assertEqual(old, [None])
                self.assertEqual(getattr(model, field), ['replacement'])

    def test_routing_export_identity_and_family_options_are_live(self):
        model = partial_model(VR_ARCH_TYPE)
        assert model.vr_options is not None
        model.identity.model_status = True
        model.export_options.save_format = 'FLAC'
        model.vr_options.window_size = 1024
        model.stem_routing.primary_stem = 'vocals'
        self.assertTrue(model.model_status)
        self.assertEqual(model.save_format, 'FLAC')
        self.assertEqual(model.window_size, 1024)
        self.assertEqual(model.primary_stem, 'vocals')
        self.assertIsNone(model.mdx_options)
        self.assertIsNone(model.demucs_options)

    def test_oom_override_is_live_and_does_not_write_settings(self):
        from core.separator_run import apply_segment_override

        model = partial_model()
        assert model.mdx_options is not None
        settings_segment = model.settings.mdx.segment_size
        apply_segment_override(SimpleNamespace(_mdx_segment_override=96), model)
        self.assertEqual(model.mdx_options.mdx_segment_size, 96)
        self.assertFalse(model.mdx_options.is_mdx_c_seg_def)
        self.assertEqual(model.settings.mdx.segment_size, settings_segment)

    def test_dry_partial_configuration_has_shared_and_selected_family_groups(self):
        model = partial_model()
        assert model.mdx_options is not None
        self.assertFalse(model.identity.model_status)
        self.assertIsNotNone(model.mdx_options)
        self.assertIsNone(model.vr_options)
        model.repo.on_unrecognized_model.assert_not_called()


class TypedOptionConstructorCompatibilityTests(unittest.TestCase):
    def test_family_inventory_constructor_keywords_are_preserved(self):
        from core.model_config import DemucsOptions, MDXOptions

        mdx = MDXOptions(mdx_model_stems=('vocals',))
        demucs = DemucsOptions(demucs_source_list=('bass', 'vocals'))
        self.assertEqual(mdx.mdx_model_stems, ('vocals',))
        self.assertEqual(demucs.demucs_source_list, ('bass', 'vocals'))

    def test_secondary_chain_original_positional_parameters_keep_order(self):
        from core.model_config import SecondaryChain

        pre_proc = object()
        vocal_split = object()
        chain = SecondaryChain(None, None, (), (), pre_proc, vocal_split, True, True, True)
        self.assertIs(chain.pre_proc_model, pre_proc)
        self.assertIs(chain.vocal_split_model, vocal_split)
        self.assertTrue(chain.is_secondary_model_activated)
