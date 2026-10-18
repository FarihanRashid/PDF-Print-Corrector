"""
file_utils.py

Helpers for turning whatever the user dropped or browsed to (files,
multiple files, or entire folders) into a flat list of PDF paths, plus
small validation helpers shared by the GUI.
"""

from __future__ import annotations

import os
import sys
from typing import List, Tuple

from utils.constants import SUPPORTED_EXTENSIONS


def discover_pdfs(paths: List[str]) -> List[Tuple[str, str]]:
    """Expand a list of files/folders into (pdf_path, base_dir) pairs.

    base_dir is the folder the PDF was discovered under (the dropped
    folder itself for folder drops, or the file's own parent for
    single-file drops) -- used later to preserve folder structure in
    batch mode.
    """
    results: List[Tuple[str, str]] = []
    for path in paths:
        if os.path.isdir(path):
            base_dir = path
            for root, _dirs, files in os.walk(path):
                for name in sorted(files):
                    if name.lower().endswith(SUPPORTED_EXTENSIONS):
                        results.append((os.path.join(root, name), base_dir))
        elif os.path.isfile(path) and path.lower().endswith(SUPPORTED_EXTENSIONS):
            results.append((path, os.path.dirname(path)))
    return results


def human_readable_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def resources_dir() -> str:
    """Absolute path to the resources/ folder, in dev mode or frozen.

    PyInstaller's --onefile build unpacks bundled data (see the
    ``datas`` entry in PDFPrintCorrector.spec) into a temporary
    folder at sys._MEIPASS at runtime; running from source, it's just
    the folder next to this file's project root.
    """
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "resources")
