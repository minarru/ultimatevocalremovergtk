"""Architecture filters must open the corresponding model storage folder."""

import unittest

from bundled.constants import APOLLO_ARCH_TYPE, DEMUCS_ARCH_TYPE, MDX_ARCH_TYPE, VR_ARCH_TYPE
from core.downloads import DownloadManager
from core.model_scores import family_arch_for_network_filter


class ModelFolderRoutingTests(unittest.TestCase):
    def test_presentation_filters_route_like_backend_families(self):
        for filter_id, family in (
            ("vr", VR_ARCH_TYPE),
            ("demucs", DEMUCS_ARCH_TYPE),
            ("apollo", APOLLO_ARCH_TYPE),
            ("bs_polarformer", MDX_ARCH_TYPE),
        ):
            with self.subTest(filter_id=filter_id):
                self.assertEqual(
                    DownloadManager.model_directory(family_arch_for_network_filter(filter_id)),
                    DownloadManager.model_directory(family),
                )
