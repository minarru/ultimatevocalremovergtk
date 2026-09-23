"""Captured constructor inputs for ordered family construction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Mapping, Optional

from ...settings import Settings

if TYPE_CHECKING:
    from ...model_identity import ModelRecord
    from ...model_repository import ModelRepository


@dataclass(frozen=True)
class ModelBuildInputs:
    settings: Settings
    repo: ModelRepository
    model_name: str
    selected_process_method: str
    is_secondary_model: bool
    primary_model_primary_stem: Optional[str]
    is_pre_proc_model: bool
    is_dry_check: bool
    is_change_def: bool
    is_get_hash_dir_only: bool
    is_vocal_split_model: bool
    identity: ModelRecord | None
    model_dependencies: Mapping[str, 'ModelRecord'] | None
