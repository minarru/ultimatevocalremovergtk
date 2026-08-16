"""Stable device requests shared by GUI settings, planning, and CLI flags."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class DeviceInfo:
    id: str
    label: str
    available: bool = True
    selected_by_auto: bool = False


@dataclass(frozen=True)
class DeviceRequest:
    id: str = "auto"

    @classmethod
    def parse(cls, value: str | None) -> "DeviceRequest":
        token = str(value or "auto").strip().casefold()
        valid = (
            token in {"auto", "cpu", "mps", "directml"}
            or token.startswith("cuda:")
            or token.startswith("directml:")
        )
        if not valid:
            raise ValueError(
                f"invalid device {value!r}; expected auto, cpu, cuda:N, mps, or directml:N"
            )
        if token.startswith(("cuda:", "directml:")):
            suffix = token.partition(":")[2]
            if not suffix.isdigit():
                raise ValueError(f"device index must be numeric: {value!r}")
        return cls(token)

    @classmethod
    def from_settings(cls, process: Any) -> "DeviceRequest":
        if not bool(process.use_gpu):
            return cls("cpu")
        device = str(process.device or "").strip()
        if bool(process.use_directml):
            if device.isdigit():
                return cls(f"directml:{device}")
            return cls("directml")
        if device == "mps":
            return cls("mps")
        if device.isdigit():
            return cls(f"cuda:{device}")
        return cls("auto")

    def settings_overrides(self, inventory: tuple[DeviceInfo, ...] | None = None) -> list[tuple[str, Any]]:
        token = self.id
        if token == "auto":
            devices = inventory if inventory is not None else list_devices()
            selected = next((item.id for item in devices if item.selected_by_auto), "cpu")
            return DeviceRequest.parse(selected).settings_overrides(devices)
        if token == "cpu":
            return [
                ("process.use_gpu", False), ("process.device", None),
                ("process.use_directml", False),
            ]
        if token.startswith("cuda:"):
            return [
                ("process.use_gpu", True), ("process.device", token.partition(":")[2]),
                ("process.use_directml", False),
            ]
        if token == "mps":
            return [
                ("process.use_gpu", True), ("process.device", "mps"),
                ("process.use_directml", False),
            ]
        suffix = token.partition(":")[2]
        return [
            ("process.use_gpu", True), ("process.device", suffix or "directml"),
            ("process.use_directml", True),
        ]


def list_devices() -> tuple[DeviceInfo, ...]:
    from .gpu import list_gpu_devices

    rows = [DeviceInfo("cpu", "CPU")]
    for ident, label in list_gpu_devices():
        if ident == "mps":
            stable = "mps"
        elif ident == "directml":
            stable = "directml"
        else:
            stable = f"cuda:{ident}"
        rows.append(DeviceInfo(stable, label))
    selected = rows[1].id if len(rows) > 1 else "cpu"
    return tuple(
        DeviceInfo(item.id, item.label, item.available, item.id == selected)
        for item in rows
    )


def resolve_device_request(value: Optional[str]) -> list[tuple[str, Any]]:
    return DeviceRequest.parse(value).settings_overrides()

