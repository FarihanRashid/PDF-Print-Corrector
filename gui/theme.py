"""
theme.py

Dark and light QSS themes. Kept in one place so the whole app can be
re-skinned by editing colours here rather than hunting through widget
code. Uses rounded corners, flat "modern" buttons, and a restrained
accent colour.
"""

from __future__ import annotations

import os

from utils.file_utils import resources_dir

DARK = {
    "bg": "#1b1d23",
    "bg_alt": "#22252c",
    "surface": "#262a33",
    "surface_hover": "#2e333e",
    "border": "#383d4a",
    "text": "#e8e9ee",
    "text_muted": "#9aa0ae",
    "accent": "#5b8cff",
    "accent_hover": "#7aa0ff",
    "accent_pressed": "#4a76e0",
    "success": "#4cc38a",
    "warning": "#e5a94c",
    "danger": "#e5636b",
    "danger_hover": "#f07981",
}

LIGHT = {
    "bg": "#f4f5f7",
    "bg_alt": "#ffffff",
    "surface": "#ffffff",
    "surface_hover": "#eef0f4",
    "border": "#d8dbe2",
    "text": "#20222a",
    "text_muted": "#666b78",
    "accent": "#3465e0",
    "accent_hover": "#4a78f0",
    "accent_pressed": "#2a52c0",
    "success": "#2f9e6b",
    "warning": "#b9791f",
    "danger": "#d1414b",
    "danger_hover": "#e35760",
}


def build_stylesheet(palette: dict) -> str:
    p = palette
    # Qt QSS url() wants forward slashes even on Windows, and is much
    # more reliable with an absolute path than a relative one (which
    # resolves against an unpredictable working directory once frozen
    # into an exe).
    check_icon_path = os.path.join(resources_dir(), "icons", "check.png").replace("\\", "/")
    return f"""
    * {{
        font-family: "Segoe UI", "Inter", sans-serif;
        font-size: 10.5pt;
        color: {p['text']};
    }}

    QMainWindow, QDialog {{
        background-color: {p['bg']};
    }}

    QLabel {{
        background: transparent;
    }}

    QLabel[role="muted"] {{
        color: {p['text_muted']};
        font-size: 9.5pt;
    }}

    QLabel[role="heading"] {{
        font-size: 13pt;
        font-weight: 600;
    }}

    QFrame#card {{
        background-color: {p['surface']};
        border: 1px solid {p['border']};
        border-radius: 10px;
    }}

    QFrame#dropZone {{
        background-color: {p['bg_alt']};
        border: 2px dashed {p['border']};
        border-radius: 14px;
    }}

    QFrame#dropZone[dragActive="true"] {{
        border: 2px dashed {p['accent']};
        background-color: {p['surface_hover']};
    }}

    QPushButton {{
        background-color: {p['surface']};
        border: 1px solid {p['border']};
        border-radius: 8px;
        padding: 8px 16px;
        color: {p['text']};
    }}

    QPushButton:hover {{
        background-color: {p['surface_hover']};
    }}

    QPushButton:disabled {{
        color: {p['text_muted']};
        background-color: {p['bg_alt']};
    }}

    QPushButton#primaryButton {{
        background-color: {p['accent']};
        border: 1px solid {p['accent']};
        color: #ffffff;
        font-weight: 600;
    }}

    QPushButton#primaryButton:hover {{
        background-color: {p['accent_hover']};
    }}

    QPushButton#primaryButton:pressed {{
        background-color: {p['accent_pressed']};
    }}

    QPushButton#dangerButton {{
        color: {p['danger']};
    }}

    QPushButton#dangerButton:hover {{
        background-color: {p['danger']};
        color: #ffffff;
    }}

    QDoubleSpinBox, QSpinBox, QLineEdit, QComboBox {{
        background-color: {p['bg_alt']};
        border: 1px solid {p['border']};
        border-radius: 6px;
        padding: 6px 8px;
        selection-background-color: {p['accent']};
    }}

    QDoubleSpinBox:focus, QSpinBox:focus, QLineEdit:focus, QComboBox:focus {{
        border: 1px solid {p['accent']};
    }}

    /* QDoubleSpinBox/QSpinBox/QComboBox each contain their own
       internal QLineEdit for text editing. Because the rule above
       targets "QLineEdit" generically, it was also matching that
       INTERNAL line edit -- applying a second border/background/
       padding nested inside the outer one it already has. The
       compounded padding squeezed the visible text area down to a
       sliver. Resetting the internal line edit to no border/padding
       of its own fixes it: only the outer control's box model
       applies now. */
    QDoubleSpinBox QLineEdit, QSpinBox QLineEdit, QComboBox QLineEdit {{
        border: none;
        background: transparent;
        padding: 0px;
        margin: 0px;
        selection-background-color: {p['accent']};
    }}

    /* The offset fields' up/down step buttons are plain QToolButtons
       (see gui/widgets.py), not Qt's native spin box arrows -- styled
       here by objectName like any other button, with no subcontrol
       geometry to fight with on resize/DPI changes. */
    QToolButton#stepButton {{
        background-color: {p['surface']};
        border: 1px solid {p['border']};
        border-radius: 4px;
        padding: 0px;
        font-size: 7pt;
        color: {p['text_muted']};
    }}

    QToolButton#stepButton:hover {{
        background-color: {p['surface_hover']};
        color: {p['text']};
    }}

    QToolButton#stepButton:pressed {{
        background-color: {p['accent']};
        color: #ffffff;
    }}

    QCheckBox {{
        spacing: 8px;
        padding: 2px 0;
    }}

    QCheckBox::indicator {{
        width: 17px;
        height: 17px;
        border-radius: 4px;
        border: 1px solid {p['border']};
        background: {p['bg_alt']};
    }}

    QCheckBox::indicator:checked {{
        background: {p['accent']};
        border: 1px solid {p['accent']};
        image: url({check_icon_path});
    }}

    QCheckBox::indicator:hover {{
        border: 1px solid {p['accent']};
    }}

    QTableWidget {{
        background-color: {p['bg_alt']};
        border: 1px solid {p['border']};
        border-radius: 8px;
        gridline-color: {p['border']};
        selection-background-color: {p['surface_hover']};
    }}

    QHeaderView::section {{
        background-color: {p['surface']};
        color: {p['text_muted']};
        padding: 6px;
        border: none;
        border-bottom: 1px solid {p['border']};
        font-weight: 600;
    }}

    QProgressBar {{
        background-color: {p['bg_alt']};
        border: 1px solid {p['border']};
        border-radius: 6px;
        text-align: center;
        height: 16px;
    }}

    QProgressBar::chunk {{
        background-color: {p['accent']};
        border-radius: 5px;
    }}

    QStatusBar {{
        background-color: {p['surface']};
        border-top: 1px solid {p['border']};
    }}

    QTabWidget::pane {{
        border: 1px solid {p['border']};
        border-radius: 8px;
        top: -1px;
    }}

    QTabBar::tab {{
        background: transparent;
        padding: 8px 14px;
        color: {p['text_muted']};
    }}

    QTabBar::tab:selected {{
        color: {p['text']};
        border-bottom: 2px solid {p['accent']};
    }}

    QScrollBar:vertical {{
        background: transparent;
        width: 10px;
    }}

    QScrollBar::handle:vertical {{
        background: {p['border']};
        border-radius: 5px;
        min-height: 24px;
    }}

    QToolTip {{
        background-color: {p['surface']};
        color: {p['text']};
        border: 1px solid {p['border']};
        padding: 4px 8px;
        border-radius: 4px;
    }}
    """


def stylesheet_for(theme_name: str) -> str:
    return build_stylesheet(DARK if theme_name == "dark" else LIGHT)
