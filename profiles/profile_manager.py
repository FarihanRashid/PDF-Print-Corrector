"""
profile_manager.py

Manages named "printer profiles" -- saved (horizontal, vertical,
rotation) presets a user can switch between when they print on
different printers with different alignment quirks.

Two built-in example profiles ship by default so the list isn't empty
on first run; they are ordinary profiles and can be renamed or deleted
like any other.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from typing import Dict, List, Optional

from settings.settings_manager import _app_dir, _fallback_dir  # reuse portable-path logic
from utils.constants import PROFILES_FILE_NAME


def _profiles_path() -> str:
    app_dir = _app_dir()
    candidate = os.path.join(app_dir, PROFILES_FILE_NAME)
    if os.access(app_dir, os.W_OK):
        return candidate
    return os.path.join(_fallback_dir(), PROFILES_FILE_NAME)


@dataclass
class PrinterProfile:
    name: str
    horizontal_offset_mm: float
    vertical_offset_mm: float
    rotation_degrees: float = 0.0
    scale_percent: float = 100.0

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> "PrinterProfile":
        return cls(
            name=data.get("name", "Untitled Profile"),
            horizontal_offset_mm=float(data.get("horizontal_offset_mm", 0.0)),
            vertical_offset_mm=float(data.get("vertical_offset_mm", 0.0)),
            rotation_degrees=float(data.get("rotation_degrees", 0.0)),
            scale_percent=float(data.get("scale_percent", 100.0)),
        )


_DEFAULT_PROFILES = [
    PrinterProfile(name="Samsung ML-1860", horizontal_offset_mm=4.0, vertical_offset_mm=5.0, rotation_degrees=0.0),
    PrinterProfile(name="Brother HL-L2320", horizontal_offset_mm=0.0, vertical_offset_mm=0.0, rotation_degrees=0.0),
]


class ProfileManager:
    def __init__(self) -> None:
        self.path = _profiles_path()
        self.profiles: List[PrinterProfile] = []
        self.default_profile_name: Optional[str] = None
        self._load()

    def _load(self) -> None:
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                self.profiles = [PrinterProfile.from_dict(p) for p in data.get("profiles", [])]
                self.default_profile_name = data.get("default_profile")
                # The file exists and parsed fine -- respect it exactly,
                # even if the user has deleted every profile. Only a
                # missing/corrupt file falls through to the seed below.
                return
            except (json.JSONDecodeError, OSError, TypeError):
                pass
        # First run, or a corrupt/unreadable file -- seed with examples
        # and write immediately so the file reliably exists from now on
        # (previously it stayed in-memory-only until the first add/
        # rename/delete, so a force-quit before that point looked like
        # "profiles don't save" even though nothing had gone wrong yet).
        self.profiles = list(_DEFAULT_PROFILES)
        self.default_profile_name = self.profiles[0].name
        self.save()

    def save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as fh:
                json.dump(
                    {
                        "profiles": [p.to_dict() for p in self.profiles],
                        "default_profile": self.default_profile_name,
                    },
                    fh,
                    indent=2,
                )
        except OSError:
            pass

    def get(self, name: str) -> Optional[PrinterProfile]:
        return next((p for p in self.profiles if p.name == name), None)

    def add(self, profile: PrinterProfile) -> None:
        if self.get(profile.name):
            raise ValueError(f"A profile named '{profile.name}' already exists.")
        self.profiles.append(profile)
        self.save()

    def rename(self, old_name: str, new_name: str) -> None:
        if old_name == new_name:
            return
        if self.get(new_name):
            raise ValueError(f"A profile named '{new_name}' already exists.")
        profile = self.get(old_name)
        if not profile:
            raise ValueError(f"Profile '{old_name}' not found.")
        profile.name = new_name
        if self.default_profile_name == old_name:
            self.default_profile_name = new_name
        self.save()

    def update(
        self, name: str, horizontal_offset_mm: float, vertical_offset_mm: float,
        rotation_degrees: float, scale_percent: float = 100.0,
    ) -> None:
        profile = self.get(name)
        if not profile:
            raise ValueError(f"Profile '{name}' not found.")
        profile.horizontal_offset_mm = horizontal_offset_mm
        profile.vertical_offset_mm = vertical_offset_mm
        profile.rotation_degrees = rotation_degrees
        profile.scale_percent = scale_percent
        self.save()

    def delete(self, name: str) -> None:
        self.profiles = [p for p in self.profiles if p.name != name]
        if self.default_profile_name == name:
            self.default_profile_name = self.profiles[0].name if self.profiles else None
        self.save()

    def set_default(self, name: str) -> None:
        if not self.get(name):
            raise ValueError(f"Profile '{name}' not found.")
        self.default_profile_name = name
        self.save()
