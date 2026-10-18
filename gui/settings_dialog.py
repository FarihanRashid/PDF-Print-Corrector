"""
settings_dialog.py

Dialog for app-wide settings that aren't part of the per-job offset
controls on the main window: theme, default output folder, and
filename behaviour.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from settings.settings_manager import AppSettings
from utils.constants import OBJ_CARD


class SettingsDialog(QDialog):
    def __init__(self, settings: AppSettings, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(440)
        self._settings = settings

        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(12)

        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["Dark", "Light"])
        self.theme_combo.setCurrentIndex(0 if settings.theme == "dark" else 1)
        form.addRow("Theme", self.theme_combo)

        output_row = QHBoxLayout()
        self.output_edit = QLineEdit(settings.output_folder or "")
        self.output_edit.setPlaceholderText("Same folder as input (default)")
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_output)
        output_row.addWidget(self.output_edit)
        output_row.addWidget(browse_btn)
        form.addRow("Default output folder", output_row)

        layout.addLayout(form)

        # -- Smart Translation ------------------------------------------
        smart_card = QFrame()
        smart_card.setObjectName(OBJ_CARD)
        smart_layout = QVBoxLayout(smart_card)
        smart_layout.setContentsMargins(14, 14, 14, 14)
        smart_layout.setSpacing(10)

        smart_heading = QLabel("Smart Translation")
        smart_heading.setProperty("role", "heading")
        smart_layout.addWidget(smart_heading)

        smart_form = QFormLayout()
        smart_form.setSpacing(10)

        self.min_scale_spin = QDoubleSpinBox()
        self.min_scale_spin.setRange(50.0, 100.0)
        self.min_scale_spin.setDecimals(1)
        self.min_scale_spin.setSingleStep(0.5)
        self.min_scale_spin.setSuffix(" %")
        self.min_scale_spin.setValue(settings.smart_min_scale_percent)
        self.min_scale_spin.setToolTip("Smart Translation will never shrink a page below this scale.")
        smart_form.addRow("Minimum allowed scale", self.min_scale_spin)

        self.max_reduction_spin = QDoubleSpinBox()
        self.max_reduction_spin.setRange(0.0, 50.0)
        self.max_reduction_spin.setDecimals(1)
        self.max_reduction_spin.setSingleStep(0.5)
        self.max_reduction_spin.setSuffix(" %")
        self.max_reduction_spin.setValue(settings.smart_max_scale_reduction_percent)
        self.max_reduction_spin.setToolTip(
            "The largest single automatic scale reduction Smart Translation\n"
            "will apply on top of your requested scale."
        )
        smart_form.addRow("Maximum automatic reduction", self.max_reduction_spin)

        self.safety_margin_spin = QDoubleSpinBox()
        self.safety_margin_spin.setRange(0.0, 50.0)
        self.safety_margin_spin.setDecimals(1)
        self.safety_margin_spin.setSingleStep(0.5)
        self.safety_margin_spin.setSuffix(" mm")
        self.safety_margin_spin.setValue(settings.smart_safety_margin_mm)
        self.safety_margin_spin.setToolTip(
            "If content would land within this distance of any edge after\n"
            "translation, Smart Translation treats that as clipping and\n"
            "corrects for it."
        )
        smart_form.addRow("Safety margin", self.safety_margin_spin)

        smart_layout.addLayout(smart_form)

        smart_hint = QLabel(
            "These only take effect when Translation Mode is set to Smart on the main window."
        )
        smart_hint.setProperty("role", "muted")
        smart_hint.setWordWrap(True)
        smart_layout.addWidget(smart_hint)

        layout.addWidget(smart_card)

        hint = QLabel("Per-job page offsets and preserve options live on the main window.")
        hint.setProperty("role", "muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _browse_output(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose default output folder")
        if folder:
            self.output_edit.setText(folder)

    def apply_to(self, settings: AppSettings) -> None:
        settings.theme = "dark" if self.theme_combo.currentIndex() == 0 else "light"
        settings.output_folder = self.output_edit.text().strip() or None
        settings.smart_min_scale_percent = self.min_scale_spin.value()
        settings.smart_max_scale_reduction_percent = self.max_reduction_spin.value()
        settings.smart_safety_margin_mm = self.safety_margin_spin.value()
