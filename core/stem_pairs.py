"""Current, data-defined ensemble pair and mode identifiers."""

from __future__ import annotations

from .model_stem_manifest import StemPairDefinition, load_bundled_stem_semantics

_STEM_MODES = frozenset({"mode.four_stem", "mode.multi_stem"})


def stem_pair_definition(pair_id: str) -> StemPairDefinition | None:
    """Return a reviewed pair definition for one exact persisted id."""
    return load_bundled_stem_semantics().pairs.get(pair_id)


def is_stem_mode(pair_id: str) -> bool:
    """Whether ``pair_id`` is one of the supported non-pair ensemble modes."""
    return pair_id in _STEM_MODES


def normalize_stem_pair_id(value: object) -> str:
    """Accept only an exact current pair/mode id; every other value is choose."""
    if not isinstance(value, str):
        return ""
    pair_id = value
    if stem_pair_definition(pair_id) is not None or is_stem_mode(pair_id):
        return pair_id
    return ""
