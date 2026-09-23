"""Immutable main-loop snapshot passed to the framework-independent error store."""

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class RunErrorContext:
    process: str
    input_files: tuple[str, ...] = ()
    non_default_settings: tuple[str, ...] = ()
    models: tuple[str, ...] | None = None
    tool: str | None = None

    @classmethod
    def from_fields(cls, fields: Mapping[str, Any]) -> 'RunErrorContext':
        return cls(
            fields['process'],
            tuple(fields.get('input_files', ())),
            tuple(fields.get('non_default_settings', ())),
            tuple(fields['models']) if 'models' in fields else None,
            fields.get('tool'),
        )

    def fields(self) -> dict[str, object]:
        fields: dict[str, object] = dict(
            process=self.process,
            input_files=list(self.input_files),
            non_default_settings=list(self.non_default_settings),
        )
        if self.models is not None:
            fields['models'] = list(self.models)
        if self.tool is not None:
            fields['tool'] = self.tool
        return fields
