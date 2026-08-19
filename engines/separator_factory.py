"""Canonical engine construction for primary and nested separation passes."""

from __future__ import annotations

import typing

from bundled.constants import DEMUCS_ARCH_TYPE, MDX_ARCH_TYPE, VR_ARCH_TYPE


def _engine_classes():
    from .demucs_engine import SeperateDemucs
    from .mdx import SeperateMDX
    from .mdx_c_engine import SeperateMDXC
    from .vr import SeperateVR

    return SeperateVR, SeperateMDX, SeperateMDXC, SeperateDemucs


def build_seperator(
    model: typing.Any,
    process_data: typing.Any,
    *,
    main_model_primary_stem_4_stem: typing.Any = None,
    main_process_method: typing.Any = None,
    is_return_dual: typing.Any = True,
    main_model_primary: typing.Any = None,
    vocal_stem_path: typing.Any = None,
    master_inst_source: typing.Any = None,
    master_vocal_source: typing.Any = None,
) -> typing.Any:
    """Construct a ``Seperate*`` engine for ``model`` and ``process_data``."""
    SeperateVR, SeperateMDX, SeperateMDXC, SeperateDemucs = _engine_classes()
    method = model.process_method
    if method == VR_ARCH_TYPE:
        if vocal_stem_path is not None:
            return SeperateVR(
                model,
                process_data,
                vocal_stem_path=vocal_stem_path,
                master_inst_source=master_inst_source,
                master_vocal_source=master_vocal_source,
            )
        return SeperateVR(
            model,
            process_data,
            main_model_primary_stem_4_stem=main_model_primary_stem_4_stem,
            main_process_method=main_process_method,
            main_model_primary=main_model_primary,
        )
    if method == MDX_ARCH_TYPE:
        if vocal_stem_path is not None:
            if model.is_mdx_c:
                return SeperateMDXC(
                    model,
                    process_data,
                    vocal_stem_path=vocal_stem_path,
                    master_inst_source=master_inst_source,
                    master_vocal_source=master_vocal_source,
                )
            return SeperateMDX(
                model,
                process_data,
                vocal_stem_path=vocal_stem_path,
                master_inst_source=master_inst_source,
                master_vocal_source=master_vocal_source,
            )
        if model.is_mdx_c:
            return SeperateMDXC(
                model,
                process_data,
                main_model_primary_stem_4_stem=main_model_primary_stem_4_stem,
                main_process_method=main_process_method,
                is_return_dual=is_return_dual,
                main_model_primary=main_model_primary,
            )
        return SeperateMDX(
            model,
            process_data,
            main_model_primary_stem_4_stem=main_model_primary_stem_4_stem,
            main_process_method=main_process_method,
            main_model_primary=main_model_primary,
        )
    if method == DEMUCS_ARCH_TYPE:
        if vocal_stem_path is not None:
            return SeperateDemucs(
                model,
                process_data,
                vocal_stem_path=vocal_stem_path,
                master_inst_source=master_inst_source,
                master_vocal_source=master_vocal_source,
            )
        return SeperateDemucs(
            model,
            process_data,
            main_model_primary_stem_4_stem=main_model_primary_stem_4_stem,
            main_process_method=main_process_method,
            is_return_dual=is_return_dual,
            main_model_primary=main_model_primary,
        )
    raise NotImplementedError(f"engine for '{method}' is not available")


__all__ = ["build_seperator"]
