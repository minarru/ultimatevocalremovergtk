"""Strict model-identity lookup shared by command-line consumers."""

from __future__ import annotations

from typing import Any, Iterable

from core.model_identity import (
    ModelIdentityService,
    ModelRecord,
    parse_stored_model_id,
)

_CANONICAL_ID_ERROR = (
    "expected canonical model ID family:basename; run 'uvr models list' "
    "for installed IDs or 'uvr models catalog' for downloadable models"
)


class CliModelLookup:
    """Parse CLI identities strictly and resolve them through one exact index."""

    def __init__(self, repo: Any):
        self._service = ModelIdentityService(repo)

    def lookup(
        self,
        reference: str,
        *,
        family: str | None = None,
        allowed_families: Iterable[str] | None = None,
    ) -> ModelRecord:
        try:
            parsed = parse_stored_model_id(reference)
        except ValueError:
            raise ValueError(_CANONICAL_ID_ERROR) from None
        record = self._service.index.lookup(parsed.value)
        if family is not None and record.family != family:
            raise ValueError(
                f"model {record.id!r} does not belong to required family {family}"
            )
        if allowed_families is not None and record.family not in allowed_families:
            raise ValueError(f"model {record.id!r} is not eligible for this setting")
        return record


__all__ = ["CliModelLookup"]
