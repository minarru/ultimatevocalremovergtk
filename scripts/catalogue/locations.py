"""Locations for the one-snapshot catalogue publication pipeline."""

from __future__ import annotations

import os

from core import paths

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


OUTPUT_PATH = os.path.join(ROOT, "docs", "models-catalogue.md")


REFERENCE_TSV_PATH = os.path.join(ROOT, "docs", "model_intent_reference.tsv")


DISPLAY_REFERENCE_TSV_PATH = os.path.join(ROOT, "docs", "model_display_reference.tsv")


STEM_SEMANTICS_REFERENCE_TSV_PATH = os.path.join(ROOT, "docs", "model_stem_semantics_reference.tsv")


# Ephemeral supplements live under CACHE_DIR; docs holds deliberate output.
_CACHE_ROOT = os.path.join(paths.CACHE_DIR, "models_catalogue")


YAML_CACHE_DIR = os.path.join(_CACHE_ROOT, "yaml")


COMMUNITY_CACHE_DIR = os.path.join(_CACHE_ROOT, "community")


# Checked-in seeds are publication inputs. Installed configs under UVR_DATA_DIR
# are user state and must never change a strict publication candidate.
_BUNDLED_MDX_YAML_DIR = os.path.join(
    ROOT, "models", "MDX_Net_Models", "model_data", "mdx_c_configs"
)


# A TTL prevents regenerate-after-update from silently reusing stale supplements.
CACHE_MAX_AGE_SECONDS = 24 * 60 * 60
