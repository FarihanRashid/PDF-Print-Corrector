"""
settings_manager.py

Loads and saves application settings as JSON. Settings live next to
the portable executable by default (so the app stays fully portable
with no installer / no registry writes), but fall back to the user's
AppData folder if the app directory is not writable (e.g. running from
a read-only mounted drive or Program Files).
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from utils.constants import (
    DEFAULT_HORIZONTAL_OFFSET_MM,
    DEFAULT_ROTATION_DEGREES,
    DEFAULT_VERTICAL_OFFSET_MM,
    ORG_NAME,
    SETTINGS_FILE_NAME,
)


def _app_dir() -> str:
    """Directory the executable/script is running from (portable mode)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _fallback_dir() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    path = os.path.join(base, ORG_NAME)
    os.makedirs(path, exist_ok=True)
    return path


def _settings_path() -> str:
    app_dir = _app_dir()
    candidate = os.path.join(app_dir, SETTINGS_FILE_NAME)
    if os.access(app_dir, os.W_OK):
        return candidate
    return os.path.join(_fallback_dir(), SETTINGS_FILE_NAME)


@dataclass
class AppSettings:
    horizontal_offset_mm: float = DEFAULT_HORIZONTAL_OFFSET_MM
    vertical_offset_mm: float = DEFAULT_VERTICAL_OFFSET_MM
    rotation_degrees: float = DEFAULT_ROTATION_DEGREES
    scale_percent: float = 100.0

    preserve_metadata: bool = True
    preserve_bookmarks: bool = True
    preserve_hyperlinks: bool = True
    preserve_annotations: bool = True
    preserve_form_fields: bool = True
    preserve_vector_quality: bool = True
    keep_original_filename: bool = False
    add_suffix: bool = True
    remember_last_settings: bool = True

    theme: str = "dark"
    window_width: int = 1180
    window_height: int = 820

    output_folder: Optional[str] = None  # None => alongside input
    default_profile: Optional[str] = None
    last_profile: Optional[str] = None  # profile selected in the main window, restored on relaunch

    landscape_compensation: bool = False
    landscape_direction: str = "cw"  # "cw" or "ccw" -- see engine/pdf_engine.py
    normalize_landscape_to_portrait: bool = False
    normalize_direction: str = "cw"  # "cw" or "ccw"

    # "strict" applies offsets/rotation/scale exactly as entered, even
    # if that clips content. "smart" analyses each page and reduces
    # translation/scale only as much as needed to avoid clipping.
    # Defaults to "strict" so existing users see no behavior change
    # unless they explicitly switch modes.
    translation_mode: str = "strict"
    smart_min_scale_percent: float = 99.0
    smart_max_scale_reduction_percent: float = 2.0
    smart_safety_margin_mm: float = 2.0

    recent_files: List[str] = field(default_factory=list)
    recent_folders: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AppSettings":
        valid_keys = {f for f in cls.__dataclass_fields__}
        filtered = {k: v for k, v in data.items() if k in valid_keys}
        return cls(**filtered)


class SettingsManager:
    MAX_RECENT = 10

    def __init__(self) -> None:
        self.path = _settings_path()
        self.settings = self._load()

    def _load(self) -> AppSettings:
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                return AppSettings.from_dict(data)
            except (json.JSONDecodeError, OSError, TypeError):
                pass
        settings = AppSettings()
        self.settings = settings
        self.save()
        return settings

    def save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as fh:
                json.dump(self.settings.to_dict(), fh, indent=2)
        except OSError:
            pass  # settings persistence is best-effort; never crash the app

    def add_recent_file(self, path: str) -> None:
        files = self.settings.recent_files
        if path in files:
            files.remove(path)
        files.insert(0, path)
        self.settings.recent_files = files[: self.MAX_RECENT]

    def add_recent_folder(self, path: str) -> None:
        folders = self.settings.recent_folders
        if path in folders:
            folders.remove(path)
        folders.insert(0, path)
        self.settings.recent_folders = folders[: self.MAX_RECENT]
