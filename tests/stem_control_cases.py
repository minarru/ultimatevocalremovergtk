"""Offline semantic fixtures shared by the direct stem-control contracts.

The decision oracle pins semantics; runtime routes always come from the existing
manifest resolver. These helpers never assemble checkpoints or fetch configs.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from bundled.constants import ALL_STEMS, secondary_stem
from core.mdx_runtime_contract import load_bundled_mdx_runtime_contracts
from core.model_config.config import ModelConfig
from core.model_data import _mdx_c_primary_for_select, _mdx_c_secondary_for_pair
from core.model_stem_manifest import load_bundled_stem_semantics, resolve_model_stem_semantics
from core.settings import Settings
from core.stem_roles import StemProcessingContext
from core.stem_selection import StemSelectionState
from core.stems import StemRoute, _semantic_routes

ORACLE = Path(__file__).parent / "fixtures" / "stem_manifest_decisions.json"
KARAOKE_THREE = "mdx:bs_karaoke_3stem_giantailab"
NATIVE_THREE = "mdx:bandit_30_zfturbo"
NATIVE_FOUR = "mdx:SCNet-large_starrytong_fixed"
NATIVE_FIVE = "mdx:mdx23c_drumsep_5stem_aufr33_jarredou"
NATIVE_FIFTY_THREE = "mdx:bs_mega_53stem_full_mvsep"
PAIR_MODELS = (
    "mdx:UVR_MDXNET_Main",
    "mdx:Kim_Inst",
    "mdx:UVR_MDXNET_KARA_2",
    "mdx:bs_karaoke_anvuew",
    "mdx:mbr_bve_gonzaluigi",
    "mdx:mbr_bgm_jasper",
    "mdx:Reverb_HQ_By_FoxJoy",
    "mdx:UVR-MDX-NET_Crowd_HQ_1",
    "mdx:mbr_lead_rhythm_guitar_listra92",
    "vr:UVR-DeEcho-DeReverb",
    "vr:UVR-BVE-4B_SN-44100-1",
    "demucs:UVR_Demucs_Model_1",
)


def manifest_case(model_id: str, context: str = "full_mix") -> dict[str, Any]:
    """Read the checked-in decision for one exact model/context."""
    return json.loads(ORACLE.read_text(encoding="utf-8"))["models"][model_id]["contexts"][context]


def route_ids(routes: tuple[StemRoute, ...]) -> tuple[str, ...]:
    """Exact identities without label/filename presentation fields."""
    return tuple(
        json.dumps(
            [
                route.concept,
                route.native.raw if route.native is not None else None,
                route.selection_scope,
                route.kind.value,
            ],
            separators=(",", ":"),
        )
        for route in routes
    )


def manifest_routes(model_id: str, context: str = "full_mix") -> tuple[StemRoute, ...]:
    registry = load_bundled_stem_semantics()
    declaration = registry.models[model_id]
    signature = declaration.native_signature
    semantics = resolve_model_stem_semantics(
        model_id,
        native_stems=signature,
        backend_primary=signature[0] if signature else "",
        context=StemProcessingContext(context),
        registry=registry,
    )
    return _semantic_routes(semantics)


def selection_state(model_id: str) -> StemSelectionState:
    routes = manifest_routes(model_id)
    natives = [route.native.raw for route in routes if route.native is not None]
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
            primary_stem=natives[0],
            secondary_stem=secondary_stem(natives[0]),
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
        )
    # Same resolved-route handoff used by the UI; configure's legacy labels are
    # deliberately not treated as a semantic authority.
    state.routes = routes
    if state.mode == "demucs":
        state.demucs_focus_map.update({r.concept: r.native.raw for r in routes if r.native})
    return state


def resolved_mdx_model(model_id: str, settings: Settings) -> Any:
    """Run ModelConfig's real focus overlay over a no-checkpoint builder fixture."""
    signature = list(load_bundled_stem_semantics().models[model_id].native_signature)
    primary = (
        signature[0]
        if len(signature) <= 2
        else _mdx_c_primary_for_select(signature, settings.mdx.stems)
    )
    secondary = secondary_stem(primary)
    if len(signature) == 2:
        secondary = _mdx_c_secondary_for_pair(signature, primary, secondary)
    contract = load_bundled_mdx_runtime_contracts().contracts.get(model_id)
    artifact = contract.artifact_evidence[0] if contract and contract.artifact_evidence else None
    model = SimpleNamespace(
        model_hash=artifact.uvr_md5 if artifact else "",
        mdx_hash_record_source=artifact.hash_record_source if artifact else "",
        canonical_id=model_id,
        process_method="MDX-Net",
        settings=settings,
        mdx_model_stems=signature,
        mdxnet_stems_selected=list(settings.mdx.stems_selected),
        mdxnet_stem_select=settings.mdx.stems,
        mdx_stem_count=len(signature),
        demucs_source_list=[],
        demucs_stem_count=0,
        primary_stem=primary,
        primary_stem_native=primary,
        secondary_stem=secondary,
        is_vocal_split_model=False,
        is_ensemble_mode=False,
        is_mdx_include_stem_complement=settings.mdx.is_mdx_include_stem_complement,
    )
    ModelConfig._apply_stem_focus(model)  # type: ignore[arg-type]
    return model


def resolved_demucs_model(model_id: str, settings: Settings) -> ModelConfig:
    """Use the full constructor and real layout builder with an injected identity."""
    from unittest.mock import MagicMock

    from bundled.constants import DEMUCS_ARCH_TYPE
    from core.model_identity import DemucsSpec, ModelArtifacts, ModelRecord

    basename = model_id.partition(":")[2]
    count = len(load_bundled_stem_semantics().models[model_id].native_signature)
    record = ModelRecord(
        id=model_id,
        family="demucs",
        basename=basename,
        display="Demucs contract fixture",
        backend_name=basename,
        artifacts=ModelArtifacts(f"{basename}.yaml"),
        installed=True,
        demucs=DemucsSpec("v4", "6_stem" if count == 6 else "2_stem" if count == 2 else "4_stem"),
    )
    return ModelConfig(
        settings, MagicMock(), model_id, DEMUCS_ARCH_TYPE, is_dry_check=True, identity=record
    )
