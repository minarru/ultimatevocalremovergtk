"""MDX-C yaml helpers and hash-map JSON IO.

:class:`~core.model_repository.ModelRepository` discovers checkpoints.
Per-run :class:`~core.model_config.ModelConfig` assembly lives in
:mod:`core.model_config`. Nothing here imports ``tkinter``.
"""
import typing

import json
from typing import Any

from bundled.constants import *  # noqa: F401,F403 - mirrors UVR.py's flat constant namespace

from .model_stem_semantics import (
    is_vocal_target,
)

_MDX_C_YAML_LOADER = None


def load_mdx_c_config(path: str) -> dict:
    """Load a bundled MDX-C / Roformer yaml config.

    Shipped configs use ``!!python/tuple`` for a few list fields; this extends
    :class:`yaml.SafeLoader` with only that tag so we avoid ``FullLoader`` while
    still parsing the trusted local files under ``mdx_c_configs/``. It also
    widens the float resolver: PyYAML's default one requires a ``.`` in the
    mantissa, so a bare-exponent value like ``1e-3`` (no shipped config uses
    this, but externally-sourced yamls — e.g. vendored Demucs's own configs —
    commonly do) silently loads as the string ``"1e-3"`` instead of ``0.001``.
    """
    import re

    import yaml

    global _MDX_C_YAML_LOADER
    if _MDX_C_YAML_LOADER is None:

        class MdxCYamlLoader(yaml.SafeLoader):
            pass

        def _construct_python_tuple(loader: typing.Any, node: typing.Any):
            return tuple(loader.construct_sequence(node))

        yaml.add_constructor(
            "tag:yaml.org,2002:python/tuple",
            _construct_python_tuple,
            Loader=MdxCYamlLoader,
        )
        MdxCYamlLoader.add_implicit_resolver(
            "tag:yaml.org,2002:float",
            re.compile(
                r"""^(?:
                 [-+]?(?:[0-9][0-9_]*)\.[0-9_]*(?:[eE][-+]?[0-9]+)?
                |[-+]?(?:[0-9][0-9_]*)(?:[eE][-+]?[0-9]+)
                |\.[0-9_]+(?:[eE][-+][0-9]+)?
                |[-+]?[0-9][0-9_]*(?::[0-5]?[0-9])+\.[0-9_]*
                |[-+]?\.(?:inf|Inf|INF)
                |\.(?:nan|NaN|NAN))$""",
                re.VERBOSE,
            ),
            list("-+0123456789."),
        )
        _MDX_C_YAML_LOADER = MdxCYamlLoader

    with open(path) as config_file:
        return yaml.load(config_file, Loader=_MDX_C_YAML_LOADER)


def _mdx_c_training(config: typing.Any) -> Any:
    """Return the ``training`` section from an MDX-C yaml config object."""
    training = getattr(config, "training", None)
    if training is None and isinstance(config, dict):
        training = config.get("training")
    return training


def _mdx_c_primary_for_select(instruments: list, stem_select: Any) -> Any:
    """Pick a primary stem that actually exists on a multi-stem MDX-C model."""
    if stem_select and stem_select != ALL_STEMS:
        if stem_select in instruments:
            return stem_select
        from .model_stem_semantics import resolve_stem_dict_key

        # Treat instruments as a key set so Title Case UI picks match yaml case.
        matched = resolve_stem_dict_key({str(s): s for s in instruments}, str(stem_select))
        if matched is not None:
            return matched
    for stem in instruments:
        if is_vocal_target(str(stem)):
            return stem
    return instruments[0] if instruments else stem_select


def _mdx_c_secondary_for_pair(instruments: list, primary: Any, mapped: Any) -> Any:
    """Complement stem for a 2-stem MDX-C model.

    ``secondary_stem`` only knows UVR's pair table, so a model trained on any
    other pair (``center``/``wide``) gets the synthetic ``No <stem>`` label
    back. A 2-stem model *emits* its complement, so that label names nothing in
    the demixed sources and export dies with a ``KeyError``. Use the model's own
    other instrument instead. Real pair labels (``Instrumental``) and models that
    genuinely emit a ``No <stem>`` stem are left alone.
    """
    if not instruments or not str(mapped).startswith(NO_STEM):
        return mapped

    from .model_stem_semantics import resolve_stem_dict_key

    if resolve_stem_dict_key({str(s): s for s in instruments}, str(mapped)) is not None:
        return mapped
    others = [stem for stem in instruments if str(stem) != str(primary)]
    return others[0] if others else mapped


def load_model_hash_data(dictionary: str) -> dict:
    """Load one of the model-data / name-mapper JSON files."""
    with open(dictionary, "r") as d:
        return json.load(d)
