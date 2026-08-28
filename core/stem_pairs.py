"""Current, data-defined ensemble pair and mode identifiers."""

from __future__ import annotations

from bundled.constants import FOUR_STEM_ENSEMBLE, MULTI_STEM_ENSEMBLE

from .model_stem_manifest import StemPairDefinition, load_bundled_stem_semantics

_STEM_MODES = frozenset({"mode.four_stem", "mode.multi_stem"})
_STEM_PAIR_ORDER = (
    "pair.vocals_instrumental",
    "pair.karaoke",
    "pair.backing_vocals",
    "pair.center_side",
)
_STEM_MODE_DISPLAYS = {
    "mode.four_stem": FOUR_STEM_ENSEMBLE,
    "mode.multi_stem": MULTI_STEM_ENSEMBLE,
}
_CHOOSE_DISPLAY = "Choose Stem Pair"


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


def stem_pair_display(pair_id: str) -> str:
    """Return presentation text for one exact pair/mode ID."""
    if not pair_id:
        return _CHOOSE_DISPLAY
    definition = stem_pair_definition(pair_id)
    if definition is not None:
        return definition.display
    return _STEM_MODE_DISPLAYS.get(pair_id, "")


def stem_pair_halves(pair_id: str) -> tuple[str, str]:
    """Return the two reviewed role labels for an exact pair ID."""
    definition = stem_pair_definition(pair_id)
    if definition is None or len(definition.roles) != 2:
        return "", ""
    registry = load_bundled_stem_semantics()
    primary = registry.roles.get(definition.roles[0])
    secondary = registry.roles.get(definition.roles[1])
    if primary is None or secondary is None:
        return "", ""
    return primary.display, secondary.display


def ensemble_pair_choices() -> tuple[tuple[str, str], ...]:
    """Return exact stored IDs and labels for the ensemble pair combo."""
    registry = load_bundled_stem_semantics()
    ordered_pairs = tuple(pair_id for pair_id in _STEM_PAIR_ORDER if pair_id in registry.pairs)
    residual_pairs = tuple(
        sorted(
            (pair_id for pair_id in registry.pairs if pair_id not in _STEM_PAIR_ORDER),
            key=lambda pair_id: (pair_id.casefold(), pair_id),
        )
    )
    return (
        ("", _CHOOSE_DISPLAY),
        *(
            (pair_id, registry.pairs[pair_id].display)
            for pair_id in (*ordered_pairs, *residual_pairs)
        ),
        ("mode.four_stem", _STEM_MODE_DISPLAYS["mode.four_stem"]),
        ("mode.multi_stem", _STEM_MODE_DISPLAYS["mode.multi_stem"]),
    )


def exclusive_flags_for_stem_pair(focus: str, pair_id: str) -> tuple[bool, bool] | None:
    """Resolve an exact role or positional focus against one reviewed pair."""
    if not str(focus or "").strip():
        return None
    definition = stem_pair_definition(pair_id)
    if definition is None or len(definition.roles) != 2:
        return False, False
    if focus == "primary":
        return True, False
    if focus == "secondary":
        return False, True
    if focus == definition.roles[0].value:
        return True, False
    if focus == definition.roles[1].value:
        return False, True
    return False, False
