"""Bind reviewed stem roles to installed output keys without changing configs.

Review describes what an identified model produces. Runtime metadata describes
how to address its arrays. A compatibility failure retains the former and blocks
execution; it never turns a reviewed declaration into unreviewed raw stems.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Sequence

from .mdx_runtime_contract import ReconciledMdxRuntimeSignature
from .model_stem_manifest import load_bundled_stem_semantics, resolve_model_stem_semantics
from .model_stem_semantics import resolve_catalogue_stem_semantics
from .stem_roles import ModelStemSemantics, StemId, StemProcessingContext


def reconcile_stem_roles(
    model_id: str,
    *,
    native_stems: Sequence[str],
    backend_primary: str,
    backend_target: str,
    context: StemProcessingContext,
    runtime: ReconciledMdxRuntimeSignature | None = None,
    artifact_digest: str = '',
    has_runtime_config: bool = False,
    training_instruments: Sequence[str] = (),
) -> ModelStemSemantics:
    registry = load_bundled_stem_semantics()
    declaration = registry.models.get(model_id)
    if declaration is None or context not in declaration.contexts:
        return resolve_catalogue_stem_semantics(
            model_id,
            native_stems=native_stems,
            backend_primary=backend_primary,
            backend_target=backend_target,
            context=context,
        )

    reviewed = resolve_model_stem_semantics(
        model_id,
        native_stems=declaration.native_signature,
        context=context,
        registry=registry,
    )
    actual = tuple(StemId(name) for name in native_stems)
    expected = tuple(StemId(name) for name in declaration.native_signature)
    actual_by_key = {name.casefold(): name for name in actual}
    contract = runtime.contract if runtime is not None else None
    verified = contract is not None and any(
        item.uvr_md5 == artifact_digest for item in contract.artifact_evidence
    )
    reason = ''
    if contract is not None and contract.artifact_evidence and not verified:
        reason = 'The checkpoint does not match the reviewed model identity.'
    elif (
        contract is not None
        and contract.backend == "classic_onnx"
        and not StemId(contract.primary_native).matches(backend_primary)
    ):
        reason = "The configuration reverses the reviewed checkpoint target."
    elif (
        contract is not None
        and has_runtime_config
        and (
            (contract.backend == 'mdx_c_target' and not backend_target)
            or (contract.backend != 'mdx_c_target' and backend_target)
            or contract.backend == 'classic_onnx'
        )
    ):
        reason = 'The configuration output layout differs from the reviewed model.'

    if contract is not None and contract.backend == 'mdx_c_multi' and has_runtime_config:
        # Dictionary order is irrelevant to role lookup, but the config list
        # assigns names to tensor slots. Reordering those slots can swap audio.
        source_order = tuple(StemId(name).casefold() for name in training_instruments)
        expected_orders = {
            tuple(StemId(name).casefold() for name in evidence.training_instruments)
            for evidence in contract.config_evidence.values()
        }
        if source_order not in expected_orders:
            reason = reason or 'The configuration changes the reviewed tensor source order.'

    mapping: dict[str, StemId] = {}
    if len(actual_by_key) == len(actual) == len(expected) and set(actual_by_key) == {
        name.casefold() for name in expected
    }:
        mapping = {name.casefold(): actual_by_key[name.casefold()] for name in expected}
    elif (
        verified
        and contract is not None
        and contract.backend == 'mdx_c_target'
        and len(actual) == len(expected) == 1
        and backend_target
        and actual[0].matches(backend_target)
        and actual[0].matches(backend_primary)
    ):
        # A verified checkpoint with one target has exactly one native role.
        # This is not a global alias: "other" on a different model stays other.
        mapping = {expected[0].casefold(): actual[0]}
    else:
        reason = reason or 'The configuration source names cannot be mapped to reviewed stem roles.'

    if reason:
        return replace(
            reviewed,
            runtime_error=f'Model configuration conflict: {reason}',
            warning=runtime.warning if runtime is not None else reason,
        )
    return replace(
        reviewed,
        outputs=tuple(
            replace(
                output,
                native=mapping[output.native.casefold()] if output.native is not None else None,
                backend_primary=output.native is not None
                and mapping[output.native.casefold()].matches(backend_primary),
            )
            for output in reviewed.outputs
        ),
        warning=runtime.warning if runtime is not None else '',
        reconciled_native_stems=tuple(native_stems),
    )
