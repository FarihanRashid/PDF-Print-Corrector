"""
main.py

Entry point for PDF Print Corrector. Sets up High-DPI support, loads
the main window, and starts the Qt event loop.
"""

from __future__ import annotations

import os
import sys

# Ensure the project root is importable both when run as a script and
# when frozen into a single-file PyInstaller executable.
if getattr(sys, "frozen", False):
    sys.path.insert(0, os.path.dirname(sys.executable))
else:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QStyleFactory

from gui.main_window import MainWindow
from utils.constants import APP_NAME, ORG_NAME
from utils.logger import log_info


def main() -> int:
    if hasattr(Qt, "AA_EnableHighDpiScaling"):
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    if hasattr(Qt, "AA_UseHighDpiPixmaps"):
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(ORG_NAME)

    # Force the Fusion style rather than the OS-native one. Native
    # styles (e.g. Windows' "windowsvista") compute spin box subcontrol
    # geometry -- the text field rect, the up/down button rects -- using
    # their own hardcoded platform metrics and only partially honour
    # custom QSS (like our padding-right reservation for the arrows).
    # That mismatch is exactly what caused the offset fields to render
    # correctly in development but clip/misalign on real Windows
    # machines. Fusion is Qt's own style and fully respects QSS-driven
    # geometry, so it renders identically on every platform.
    app.setStyle(QStyleFactory.create("Fusion"))

    icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources", "icons", "app.ico")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    log_info(f"{APP_NAME} starting up")

    window = MainWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
