"""Short selector labels and explanations without changing export identities."""

from collections.abc import Iterable

from core.model_stem_manifest import load_bundled_stem_semantics
from core.stem_roles import StemRoleId
from core.stems import StemRoute


def stem_label(route: StemRoute) -> str:
    return {
        "vocal.backing": "BGV",
        "vocal.backing.removed": "BGV Removed",
        "mix.instrumental_with_backing_vocals": "Instrumental + BGV",
    }.get(route.concept, route.label)


def stem_tooltip(route: StemRoute) -> str:
    descriptions = {
        "vocal.vocals": "Vocals separated from the accompaniment.",
        "vocal.lead": "Lead vocals: the main vocal performance.",
        "vocal.backing": "Backing vocals (BGV): supporting vocals and harmonies.",
        "mix.instrumental": "Instrumental accompaniment without vocals.",
        "mix.instrumental_with_backing_vocals": "Instrumental accompaniment and backing vocals (BGV) together in one file; lead vocals are excluded.",
        "mix.instrumental_with_lead_vocals": "Instrumental accompaniment and lead vocals together in one file; backing vocals are excluded.",
        "residual.other": "Residual audio not assigned to the model's other stems.",
    }
    if route.concept == "mix.instrumental" and route.derived_from:
        roles = load_bundled_stem_semantics().roles
        parts = ", ".join(roles[r].display for r in route.derived_from if r in roles)
        return f"Combine the non-vocal stems into one Instrumental file: {parts}."
    if route.concept in descriptions:
        return descriptions[route.concept]
    if isinstance(route.role, StemRoleId):
        roles = load_bundled_stem_semantics().roles
        definition = roles.get(route.role)
        if (
            definition is not None
            and definition.removed_of is not None
            and definition.removed_of in roles
        ):
            removed = roles[definition.removed_of].display
            return f"Audio with {removed.lower()} removed."
        return f"Save the separated {route.label.lower()} audio."
    return f"Save the model's {route.label} output."


def selection_tooltips(routes: Iterable[tuple[str, StemRoute]]) -> tuple[tuple[str, str], ...]:
    inventory = tuple(routes)
    defaults = [route.label for _, route in inventory if route.selected_by_default]
    return (
        ("all", f"Save all default outputs as separate files: {', '.join(defaults)}."),
        (
            "separate_non_vocal",
            "Save each non-vocal stem as a separate file, without combining them.",
        ),
        (
            "separate_backing_instrumental",
            "Save backing vocals (BGV) and Instrumental as two separate files.",
        ),
        *((ident, stem_tooltip(route)) for ident, route in inventory),
    )
