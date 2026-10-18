"""
main_window.py

The main application window. Composes the drop zone, offset/rotation
controls, preserve-options checkboxes, action buttons, conversion
queue, and status bar, and wires them to the engine via a background
BatchWorker thread so the UI never freezes.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from typing import List, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from engine.batch_worker import BatchWorker, QueueItem, build_output_path, resolve_unique_output_path
from engine.layouts.booklet_worker import BookletWorker
from engine.layouts.layout_engine import BookletOptions, build_booklet
from engine.layouts.nup import build_nup
from engine.pdf_engine import TranslationOptions
from engine.smart_translate import SmartTranslateSettings
from gui.drop_zone import DropZone
from gui.preview_dialog import PreviewDialog
from gui.profiles_dialog import ProfilesDialog
from gui.queue_table import QueueTable
from gui.settings_dialog import SettingsDialog
from gui.theme import stylesheet_for
from gui.widgets import HorizontalOffsetField, RotationField, ScaleField, VerticalOffsetField
from profiles.profile_manager import ProfileManager
from settings.settings_manager import SettingsManager
from utils.constants import (
    APP_NAME,
    APP_VERSION,
    OBJ_CARD,
    OBJ_DANGER_BUTTON,
    OBJ_PRIMARY_BUTTON,
    OBJ_SECONDARY_BUTTON,
    STATUS_CONVERTING,
    STATUS_ERRORS,
    STATUS_FINISHED,
    STATUS_READY,
)
from utils.file_utils import discover_pdfs
from utils.logger import log_conversion, log_error, log_info


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{APP_NAME}  v{APP_VERSION}")

        self.settings_manager = SettingsManager()
        self.profile_manager = ProfileManager()
        self._settings = self.settings_manager.settings
        self.resize(self._settings.window_width, self._settings.window_height)

        self._queue_items: List[QueueItem] = []
        self._worker: Optional[BatchWorker] = None
        self._job_start_time: float = 0.0
        self._applying_profile = False
        self._last_report_path: Optional[str] = None

        # Debounced auto-save: fields change frequently while typing or
        # dragging spin box arrows, so we wait for a short pause in
        # activity rather than writing settings.json on every keystroke.
        # This also means offsets/options are no longer only saved on a
        # clean window close -- they persist within ~½ second of any
        # change, so a crash or force-quit won't lose them.
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(500)
        self._autosave_timer.timeout.connect(self._persist_settings)

        self._build_ui()
        self._wire_shortcuts()
        self._apply_theme()
        self._load_settings_into_ui()
        self._wire_autosave()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(12)

        splitter = QSplitter(Qt.Horizontal)
        outer.addWidget(splitter, 1)

        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_right_panel())
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        self._build_status_bar()

    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setSpacing(12)
        layout.setContentsMargins(0, 0, 0, 0)

        self.drop_zone = DropZone()
        self.drop_zone.filesDropped.connect(self._on_paths_added)
        self.drop_zone.browseClicked.connect(self._on_browse_clicked)
        layout.addWidget(self.drop_zone)

        queue_label = QLabel("Conversion Queue")
        queue_label.setProperty("role", "heading")
        layout.addWidget(queue_label)

        self.queue_table = QueueTable()
        layout.addWidget(self.queue_table, 1)

        # Overall progress row
        progress_row = QHBoxLayout()
        self.overall_progress_label = QLabel("")
        self.overall_progress_label.setProperty("role", "muted")
        progress_row.addWidget(self.overall_progress_label)
        progress_row.addStretch(1)
        self.eta_label = QLabel("")
        self.eta_label.setProperty("role", "muted")
        progress_row.addWidget(self.eta_label)
        layout.addLayout(progress_row)

        # Action buttons
        button_row = QHBoxLayout()
        self.browse_btn = QPushButton("Browse")
        self.browse_btn.clicked.connect(self._on_browse_clicked)
        self.convert_btn = QPushButton("Convert")
        self.convert_btn.setObjectName(OBJ_PRIMARY_BUTTON)
        self.convert_btn.clicked.connect(self._on_convert_clicked)
        self.open_folder_btn = QPushButton("Open Output Folder")
        self.open_folder_btn.clicked.connect(self._on_open_output_folder)
        self.open_pdf_btn = QPushButton("Open Output PDF")
        self.open_pdf_btn.clicked.connect(self._on_open_output_pdf)
        self.open_report_btn = QPushButton("Open Report")
        self.open_report_btn.clicked.connect(self._on_open_report)
        self.open_report_btn.setEnabled(False)
        self.clear_btn = QPushButton("Clear Queue")
        self.clear_btn.setObjectName(OBJ_DANGER_BUTTON)
        self.clear_btn.clicked.connect(self._on_clear_queue)

        for btn in (
            self.browse_btn, self.convert_btn, self.open_folder_btn,
            self.open_pdf_btn, self.open_report_btn, self.clear_btn,
        ):
            button_row.addWidget(btn)
        layout.addLayout(button_row)

        return panel

    def _build_right_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setSpacing(12)
        layout.setContentsMargins(0, 0, 0, 0)

        tabs = QTabWidget()
        tabs.addTab(self._build_transform_tab(), "Transform")
        tabs.addTab(self._build_landscape_smart_tab(), "Landscape / Smart")
        tabs.addTab(self._build_profiles_tab(), "Profiles")
        tabs.addTab(self._build_preserve_options_tab(), "Preserve Options")
        tabs.addTab(self._build_booklet_tab(), "Booklet")
        layout.addWidget(tabs, 1)

        settings_btn = QPushButton("Settings")
        settings_btn.clicked.connect(self._on_open_settings)
        layout.addWidget(settings_btn)

        return panel

    def _build_transform_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        heading_row = QHBoxLayout()
        heading = QLabel("Page Offset")
        heading.setProperty("role", "heading")
        heading_row.addWidget(heading)
        heading_row.addStretch(1)
        self.reset_btn = QPushButton("Reset Offsets")
        self.reset_btn.clicked.connect(self._on_reset_offsets)
        heading_row.addWidget(self.reset_btn)
        layout.addLayout(heading_row)

        self.h_field = HorizontalOffsetField()
        self.v_field = VerticalOffsetField()
        self.r_field = RotationField()
        self.scale_field = ScaleField()
        layout.addWidget(self.h_field)
        layout.addWidget(self.v_field)
        layout.addWidget(self.r_field)
        layout.addWidget(self.scale_field)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Translation Mode"))
        self.mode_group = QButtonGroup(self)
        self.radio_strict = QRadioButton("Strict")
        self.radio_smart = QRadioButton("Smart")
        self.radio_strict.setToolTip("Apply offset, rotation, and scale exactly as entered. May clip content.")
        self.radio_smart.setToolTip(
            "Analyse each page's actual content and reduce scale, if needed, to fit\n"
            "the full requested shift without clipping. The shift itself is never\n"
            "reduced -- every page moves by the same amount you requested."
        )
        self.mode_group.addButton(self.radio_strict)
        self.mode_group.addButton(self.radio_smart)
        mode_row.addWidget(self.radio_strict)
        mode_row.addWidget(self.radio_smart)
        mode_row.addStretch(1)
        layout.addLayout(mode_row)

        self.smart_mode_hint = QLabel(
            "Smart mode never clips content unless it's mathematically unavoidable -- "
            "see the Landscape / Smart tab and Settings for the allowed range."
        )
        self.smart_mode_hint.setProperty("role", "muted")
        self.smart_mode_hint.setWordWrap(True)
        layout.addWidget(self.smart_mode_hint)
        self.radio_smart.toggled.connect(self.smart_mode_hint.setVisible)

        preview_btn = QPushButton("Preview Before / After")
        preview_btn.clicked.connect(self._on_preview_clicked)
        layout.addWidget(preview_btn)

        layout.addStretch(1)
        return tab

    def _build_landscape_smart_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        normalize_heading = QLabel("Normalize to Portrait")
        normalize_heading.setProperty("role", "heading")
        layout.addWidget(normalize_heading)

        self.chk_normalize_landscape = QCheckBox("Rotate landscape pages to portrait")
        self.chk_normalize_landscape.setToolTip(
            "Physically rotates any landscape page's content and reshapes\n"
            "its page size so it becomes portrait, like every other page.\n"
            "Useful to visually confirm a mixed-orientation document before\n"
            "printing, and as prep for booklet layout."
        )
        layout.addWidget(self.chk_normalize_landscape)

        normalize_direction_row = QHBoxLayout()
        normalize_direction_row.addWidget(QLabel("Rotate Direction"))
        self.normalize_direction_combo = QComboBox()
        self.normalize_direction_combo.addItem("Clockwise", "cw")
        self.normalize_direction_combo.addItem("Counter-clockwise", "ccw")
        normalize_direction_row.addWidget(self.normalize_direction_combo, 1)
        layout.addLayout(normalize_direction_row)

        normalize_hint = QLabel(
            "This changes the page itself (content + page size), unlike Landscape "
            "Compensation below, which only re-orients the print offset."
        )
        normalize_hint.setProperty("role", "muted")
        normalize_hint.setWordWrap(True)
        layout.addWidget(normalize_hint)

        divider0 = QFrame()
        divider0.setFrameShape(QFrame.HLine)
        layout.addWidget(divider0)

        landscape_heading = QLabel("Landscape Compensation")
        landscape_heading.setProperty("role", "heading")
        layout.addWidget(landscape_heading)

        landscape_row = QHBoxLayout()
        self.chk_landscape = QCheckBox("Auto-compensate for landscape pages")
        self.chk_landscape.setToolTip(
            "Treat the offsets on the Transform tab as calibrated on a\n"
            "portrait page. Landscape pages (by shape or by rotation) get\n"
            "the same offset re-oriented automatically, so you don't have\n"
            "to work out the sign flip by hand."
        )
        landscape_row.addWidget(self.chk_landscape)
        layout.addLayout(landscape_row)

        direction_row = QHBoxLayout()
        direction_row.addWidget(QLabel("Rotation Direction"))
        self.landscape_direction_combo = QComboBox()
        self.landscape_direction_combo.addItem("Clockwise", "cw")
        self.landscape_direction_combo.addItem("Counter-clockwise", "ccw")
        self.landscape_direction_combo.setToolTip(
            "If a landscape page comes out shifted the wrong way,\n"
            "flip this and re-run (or check with Preview first)."
        )
        direction_row.addWidget(self.landscape_direction_combo, 1)
        layout.addLayout(direction_row)

        landscape_hint = QLabel(
            "Applies your offset as if every page were portrait, automatically "
            "re-oriented for pages that render landscape."
        )
        landscape_hint.setProperty("role", "muted")
        landscape_hint.setWordWrap(True)
        layout.addWidget(landscape_hint)

        divider = QFrame()
        divider.setFrameShape(QFrame.HLine)
        layout.addWidget(divider)

        smart_heading = QLabel("Smart Translation")
        smart_heading.setProperty("role", "heading")
        layout.addWidget(smart_heading)

        smart_hint = QLabel(
            "Switch modes on the Transform tab. Fine-tune the allowed scale "
            "range and safety margin in Settings."
        )
        smart_hint.setProperty("role", "muted")
        smart_hint.setWordWrap(True)
        layout.addWidget(smart_hint)

        layout.addStretch(1)
        return tab

    def _build_profiles_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        heading = QLabel("Printer Profile")
        heading.setProperty("role", "heading")
        layout.addWidget(heading)

        self.profile_combo = QComboBox()
        self.profile_combo.currentTextChanged.connect(self._on_profile_selected)
        layout.addWidget(self.profile_combo)

        button_row = QHBoxLayout()
        save_profile_btn = QPushButton("Save as Profile...")
        save_profile_btn.clicked.connect(self._on_save_as_profile)
        button_row.addWidget(save_profile_btn)
        manage_profiles_btn = QPushButton("Manage...")
        manage_profiles_btn.clicked.connect(self._on_manage_profiles)
        button_row.addWidget(manage_profiles_btn)
        layout.addLayout(button_row)

        hint = QLabel(
            "Selecting a profile applies its offset, rotation, and scale to the "
            "Transform tab. Editing a value afterward switches back to \"(Custom)\"."
        )
        hint.setProperty("role", "muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        layout.addStretch(1)
        return tab

    def _build_preserve_options_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        options_scroll = QScrollArea()
        options_scroll.setWidgetResizable(True)
        options_scroll.setFrameShape(QFrame.NoFrame)
        options_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        options_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        options_container = QWidget()
        options_layout = QVBoxLayout(options_container)
        options_layout.setContentsMargins(16, 12, 16, 16)
        options_layout.setSpacing(10)

        self.chk_metadata = QCheckBox("Preserve metadata")
        self.chk_bookmarks = QCheckBox("Preserve bookmarks")
        self.chk_hyperlinks = QCheckBox("Preserve hyperlinks")
        self.chk_annotations = QCheckBox("Preserve annotations")
        self.chk_form_fields = QCheckBox("Preserve form fields")
        self.chk_vector_quality = QCheckBox("Preserve vector quality")
        self.chk_vector_quality.setEnabled(False)  # always on -- never rasterized
        self.chk_vector_quality.setToolTip("Always enabled: this app never rasterizes pages.")
        self.chk_keep_filename = QCheckBox("Keep original filename")
        self.chk_add_suffix = QCheckBox('Create "_corrected" suffix')
        self.chk_remember_settings = QCheckBox("Remember last settings")

        for chk in (
            self.chk_metadata,
            self.chk_bookmarks,
            self.chk_hyperlinks,
            self.chk_annotations,
            self.chk_form_fields,
            self.chk_vector_quality,
            self.chk_keep_filename,
            self.chk_add_suffix,
            self.chk_remember_settings,
        ):
            options_layout.addWidget(chk)
        options_layout.addStretch(1)

        options_scroll.setWidget(options_container)
        layout.addWidget(options_scroll, 1)
        return tab

    def _build_booklet_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        heading = QLabel("Layout")
        heading.setProperty("role", "heading")
        layout.addWidget(heading)

        type_row = QHBoxLayout()
        type_row.addWidget(QLabel("Layout Type"))
        self.layout_type_combo = QComboBox()
        self.layout_type_combo.addItem("Booklet (fold + staple)", "booklet")
        self.layout_type_combo.addItem("2-Up (2 pages per sheet, no folding)", "twoup")
        type_row.addWidget(self.layout_type_combo, 1)
        layout.addLayout(type_row)

        self.layout_type_hint = QLabel("")
        self.layout_type_hint.setProperty("role", "muted")
        self.layout_type_hint.setWordWrap(True)
        layout.addWidget(self.layout_type_hint)

        divider = QFrame()
        divider.setFrameShape(QFrame.HLine)
        layout.addWidget(divider)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Duplex Mode"))
        self.booklet_duplex_combo = QComboBox()
        self.booklet_duplex_combo.addItem("Single File - Long Edge (standard)", "long")
        self.booklet_duplex_combo.addItem("Single File - Short Edge", "short")
        self.booklet_duplex_combo.addItem("Two Files (fully manual) - Long Edge", "twojob_long")
        self.booklet_duplex_combo.addItem("Two Files (fully manual) - Short Edge", "twojob_short")
        mode_row.addWidget(self.booklet_duplex_combo, 1)
        layout.addLayout(mode_row)

        self.booklet_mode_hint = QLabel("")
        self.booklet_mode_hint.setProperty("role", "muted")
        self.booklet_mode_hint.setWordWrap(True)
        layout.addWidget(self.booklet_mode_hint)

        self.layout_type_combo.currentIndexChanged.connect(self._update_layout_type_hint)
        self.booklet_duplex_combo.currentIndexChanged.connect(self._update_booklet_mode_hint)
        self._update_layout_type_hint()
        self._update_booklet_mode_hint()

        create_booklet_btn = QPushButton("Create Layout from Queue")
        create_booklet_btn.setObjectName(OBJ_PRIMARY_BUTTON)
        create_booklet_btn.clicked.connect(self._on_create_booklet_clicked)
        layout.addWidget(create_booklet_btn)

        layout.addStretch(1)
        return tab

    def _update_layout_type_hint(self) -> None:
        mode = self.layout_type_combo.currentData()
        hints = {
            "booklet": "Reorders pages so folded, stapled sheets read in order 1, 2, 3... "
                       "Use this only if you're physically folding the output in half.",
            "twoup": "Keeps pages in normal order (1,2 on sheet 1; 3,4 on sheet 2...), "
                     "scaled to the largest size that fits -- for a normal stapled/bound "
                     "stack, not folding. This is what you want for everyday page-saving.",
        }
        self.layout_type_hint.setText(hints.get(mode, ""))

    def _update_booklet_mode_hint(self) -> None:
        mode = self.booklet_duplex_combo.currentData()
        hints = {
            "long": "One PDF, fronts and backs interleaved. Use with a real auto-duplex "
                    "printer, OR with Acrobat/Reader's own \"Print on both sides "
                    "(manually)\" option -- flip the printed stack the standard book-style "
                    "way (long edge) when it prompts you.",
            "short": "One PDF, fronts and backs interleaved, with back sides pre-rotated "
                     "180\u00b0 to compensate. Use with a real auto-duplex printer set to "
                     "short-edge flip, OR with Acrobat/Reader's \"Print on both sides "
                     "(manually)\" option if you'll flip the stack short-edge (calendar-style) "
                     "-- the result reads correctly either way, as if printed automatically.",
            "twojob_long": "Two separate PDFs (fronts, backs) for a fully manual two-pass "
                           "print -- no duplex-assist feature involved. Print fronts, flip "
                           "the stack long-edge by hand, print backs.",
            "twojob_short": "Two separate PDFs (fronts, backs) for a fully manual two-pass "
                            "print. Print fronts, flip the stack short-edge by hand, print "
                            "backs. Do a short test print first -- exactly how a stack "
                            "re-feeds varies by printer.",
        }
        self.booklet_mode_hint.setText(hints.get(mode, ""))

    def _build_status_bar(self) -> None:
        self.statusBar().showMessage(STATUS_READY)

    def _wire_shortcuts(self) -> None:
        open_action = QAction(self)
        open_action.setShortcut(QKeySequence("Ctrl+O"))
        open_action.triggered.connect(self._on_browse_clicked)
        self.addAction(open_action)

        drop_action = QAction(self)
        drop_action.setShortcut(QKeySequence("Ctrl+D"))
        drop_action.triggered.connect(self._on_clear_queue)
        self.addAction(drop_action)

        convert_action = QAction(self)
        convert_action.setShortcut(QKeySequence("Ctrl+Return"))
        convert_action.triggered.connect(self._on_convert_clicked)
        self.addAction(convert_action)

    # ------------------------------------------------------------------
    # Settings <-> UI
    # ------------------------------------------------------------------
    def _load_settings_into_ui(self) -> None:
        s = self._settings
        self.h_field.set_value(s.horizontal_offset_mm)
        self.v_field.set_value(s.vertical_offset_mm)
        self.r_field.set_value(s.rotation_degrees)
        self.scale_field.set_value(s.scale_percent)

        if s.translation_mode == "smart":
            self.radio_smart.setChecked(True)
        else:
            self.radio_strict.setChecked(True)
        self.smart_mode_hint.setVisible(s.translation_mode == "smart")

        self.chk_metadata.setChecked(s.preserve_metadata)
        self.chk_bookmarks.setChecked(s.preserve_bookmarks)
        self.chk_hyperlinks.setChecked(s.preserve_hyperlinks)
        self.chk_annotations.setChecked(s.preserve_annotations)
        self.chk_form_fields.setChecked(s.preserve_form_fields)
        self.chk_vector_quality.setChecked(True)
        self.chk_keep_filename.setChecked(s.keep_original_filename)
        self.chk_add_suffix.setChecked(s.add_suffix)
        self.chk_remember_settings.setChecked(s.remember_last_settings)

        self.chk_landscape.setChecked(s.landscape_compensation)
        direction_index = self.landscape_direction_combo.findData(s.landscape_direction)
        self.landscape_direction_combo.setCurrentIndex(max(0, direction_index))

        self.chk_normalize_landscape.setChecked(s.normalize_landscape_to_portrait)
        normalize_index = self.normalize_direction_combo.findData(s.normalize_direction)
        self.normalize_direction_combo.setCurrentIndex(max(0, normalize_index))

        self._refresh_profile_combo()

        # Restore whichever profile was active last time, so the combo
        # doesn't silently reset to "(Custom)" on every relaunch even
        # though a profile was clearly selected before. _on_profile_selected
        # (already wired in _build_right_panel) applies its own offsets.
        if s.last_profile:
            index = self.profile_combo.findText(s.last_profile)
            if index >= 0:
                self.profile_combo.setCurrentIndex(index)

    def _wire_autosave(self) -> None:
        self.h_field.valueChanged.connect(self._on_offset_field_edited)
        self.v_field.valueChanged.connect(self._on_offset_field_edited)
        self.r_field.valueChanged.connect(self._on_offset_field_edited)
        self.scale_field.valueChanged.connect(self._on_offset_field_edited)
        self.h_field.valueChanged.connect(self._schedule_autosave)
        self.v_field.valueChanged.connect(self._schedule_autosave)
        self.r_field.valueChanged.connect(self._schedule_autosave)
        self.scale_field.valueChanged.connect(self._schedule_autosave)
        self.radio_strict.toggled.connect(self._schedule_autosave)
        self.chk_landscape.toggled.connect(self._schedule_autosave)
        self.landscape_direction_combo.currentIndexChanged.connect(self._schedule_autosave)
        self.chk_normalize_landscape.toggled.connect(self._schedule_autosave)
        self.normalize_direction_combo.currentIndexChanged.connect(self._schedule_autosave)
        for chk in (
            self.chk_metadata,
            self.chk_bookmarks,
            self.chk_hyperlinks,
            self.chk_annotations,
            self.chk_form_fields,
            self.chk_keep_filename,
            self.chk_add_suffix,
            self.chk_remember_settings,
        ):
            chk.toggled.connect(self._schedule_autosave)

    def _schedule_autosave(self, *_args) -> None:
        self._autosave_timer.start()

    def _refresh_profile_combo(self) -> None:
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        self.profile_combo.addItem("(Custom)")
        for profile in self.profile_manager.profiles:
            self.profile_combo.addItem(profile.name)
        self.profile_combo.blockSignals(False)

    def _persist_settings(self) -> None:
        s = self._settings
        if not s.remember_last_settings:
            return
        s.horizontal_offset_mm = self.h_field.value()
        s.vertical_offset_mm = self.v_field.value()
        s.rotation_degrees = self.r_field.value()
        s.scale_percent = self.scale_field.value()
        s.translation_mode = "smart" if self.radio_smart.isChecked() else "strict"
        self.smart_mode_hint.setVisible(self.radio_smart.isChecked())
        s.preserve_metadata = self.chk_metadata.isChecked()
        s.preserve_bookmarks = self.chk_bookmarks.isChecked()
        s.preserve_hyperlinks = self.chk_hyperlinks.isChecked()
        s.preserve_annotations = self.chk_annotations.isChecked()
        s.preserve_form_fields = self.chk_form_fields.isChecked()
        s.keep_original_filename = self.chk_keep_filename.isChecked()
        s.add_suffix = self.chk_add_suffix.isChecked()
        s.remember_last_settings = self.chk_remember_settings.isChecked()
        s.landscape_compensation = self.chk_landscape.isChecked()
        s.landscape_direction = self.landscape_direction_combo.currentData()
        s.normalize_landscape_to_portrait = self.chk_normalize_landscape.isChecked()
        s.normalize_direction = self.normalize_direction_combo.currentData()
        current_profile = self.profile_combo.currentText()
        s.last_profile = current_profile if current_profile != "(Custom)" else None
        s.window_width = self.width()
        s.window_height = self.height()
        self.settings_manager.save()

    def _apply_theme(self) -> None:
        self.setStyleSheet(stylesheet_for(self._settings.theme))

    def _current_options(self) -> TranslationOptions:
        s = self._settings
        return TranslationOptions(
            horizontal_offset_mm=self.h_field.value(),
            vertical_offset_mm=self.v_field.value(),
            rotation_degrees=self.r_field.value(),
            scale_percent=self.scale_field.value(),
            preserve_metadata=self.chk_metadata.isChecked(),
            preserve_bookmarks=self.chk_bookmarks.isChecked(),
            preserve_hyperlinks=self.chk_hyperlinks.isChecked(),
            preserve_annotations=self.chk_annotations.isChecked(),
            preserve_form_fields=self.chk_form_fields.isChecked(),
            landscape_compensation=self.chk_landscape.isChecked(),
            landscape_direction=self.landscape_direction_combo.currentData(),
            normalize_landscape_to_portrait=self.chk_normalize_landscape.isChecked(),
            normalize_direction=self.normalize_direction_combo.currentData(),
            translation_mode="smart" if self.radio_smart.isChecked() else "strict",
            smart_settings=SmartTranslateSettings(
                prevent_clipping=True,
                minimum_scale_percent=s.smart_min_scale_percent,
                maximum_scale_reduction_percent=s.smart_max_scale_reduction_percent,
                safety_margin_mm=s.smart_safety_margin_mm,
            ),
        )

    # ------------------------------------------------------------------
    # Queue management
    # ------------------------------------------------------------------
    def _on_browse_clicked(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Select PDF files", "", "PDF Files (*.pdf)")
        if paths:
            self._on_paths_added(paths)

    def _on_paths_added(self, paths: List[str]) -> None:
        discovered = discover_pdfs(paths)
        if not discovered:
            QMessageBox.information(self, "No PDFs Found", "No PDF files were found in the selected item(s).")
            return

        # Seed with paths already in the queue so a second drag-and-drop
        # batch can't collide with the first one either.
        reserved_output_paths = {item.output_path for item in self._queue_items}

        for pdf_path, base_dir in discovered:
            base_output_path = build_output_path(
                pdf_path,
                self._settings.output_folder,
                base_dir if len(discovered) > 1 else None,
                self.chk_keep_filename.isChecked(),
                self.chk_add_suffix.isChecked(),
            )
            output_path = resolve_unique_output_path(base_output_path, reserved_output_paths)
            item = QueueItem(
                input_path=pdf_path, output_path=output_path, base_dir=base_dir,
                base_output_path=base_output_path,
            )
            self._queue_items.append(item)
            self.queue_table.append_item(item)
            self.settings_manager.add_recent_file(pdf_path)

        self.settings_manager.save()
        self.statusBar().showMessage(f"{len(discovered)} file(s) added to queue")

    def _on_clear_queue(self) -> None:
        self._queue_items.clear()
        self.queue_table.clear_queue()
        self.statusBar().showMessage(STATUS_READY)

    def _on_reset_offsets(self) -> None:
        from utils.constants import (
            DEFAULT_HORIZONTAL_OFFSET_MM,
            DEFAULT_ROTATION_DEGREES,
            DEFAULT_SCALE_PERCENT,
            DEFAULT_VERTICAL_OFFSET_MM,
        )

        self.h_field.set_value(DEFAULT_HORIZONTAL_OFFSET_MM)
        self.v_field.set_value(DEFAULT_VERTICAL_OFFSET_MM)
        self.r_field.set_value(DEFAULT_ROTATION_DEGREES)
        self.scale_field.set_value(DEFAULT_SCALE_PERCENT)
        self.profile_combo.setCurrentIndex(0)

    # ------------------------------------------------------------------
    # Profiles
    # ------------------------------------------------------------------
    def _on_profile_selected(self, name: str) -> None:
        if not name or name == "(Custom)":
            return
        profile = self.profile_manager.get(name)
        if not profile:
            return
        self._applying_profile = True
        try:
            self.h_field.set_value(profile.horizontal_offset_mm)
            self.v_field.set_value(profile.vertical_offset_mm)
            self.r_field.set_value(profile.rotation_degrees)
            self.scale_field.set_value(profile.scale_percent)
        finally:
            self._applying_profile = False
        self._schedule_autosave()

    def _on_offset_field_edited(self, *_args) -> None:
        # If the user tweaks a value directly while a named profile is
        # showing, the fields no longer match that profile -- fall back
        # to "(Custom)" rather than silently keeping a stale profile
        # name selected, which previously made it look like profile
        # changes weren't sticking.
        if self._applying_profile:
            return
        if self.profile_combo.currentText() != "(Custom)":
            self._applying_profile = True
            try:
                self.profile_combo.setCurrentIndex(0)
            finally:
                self._applying_profile = False

    def _on_save_as_profile(self) -> None:
        from PySide6.QtWidgets import QInputDialog

        suggested = self.profile_combo.currentText()
        if suggested == "(Custom)":
            suggested = ""
        name, ok = QInputDialog.getText(self, "Save as Profile", "Profile name:", text=suggested)
        if not ok or not name.strip():
            return
        name = name.strip()

        existing = self.profile_manager.get(name)
        if existing:
            confirm = QMessageBox.question(
                self, "Overwrite Profile", f"A profile named '{name}' already exists. Overwrite it?"
            )
            if confirm != QMessageBox.Yes:
                return
            self.profile_manager.update(
                name, self.h_field.value(), self.v_field.value(), self.r_field.value(), self.scale_field.value()
            )
        else:
            from profiles.profile_manager import PrinterProfile

            self.profile_manager.add(
                PrinterProfile(
                    name=name,
                    horizontal_offset_mm=self.h_field.value(),
                    vertical_offset_mm=self.v_field.value(),
                    rotation_degrees=self.r_field.value(),
                    scale_percent=self.scale_field.value(),
                )
            )

        self._refresh_profile_combo()
        self._applying_profile = True
        try:
            index = self.profile_combo.findText(name)
            if index >= 0:
                self.profile_combo.setCurrentIndex(index)
        finally:
            self._applying_profile = False
        self._schedule_autosave()
        self.statusBar().showMessage(f"Saved profile '{name}'")

    def _on_manage_profiles(self) -> None:
        dialog = ProfilesDialog(self.profile_manager, self)
        dialog.exec()
        self._refresh_profile_combo()

    # ------------------------------------------------------------------
    # Preview
    # ------------------------------------------------------------------
    def _on_preview_clicked(self) -> None:
        if not self._queue_items:
            QMessageBox.information(self, "Nothing to Preview", "Add a PDF to the queue first.")
            return
        dialog = PreviewDialog(self._queue_items[0].input_path, self._current_options(), self)
        dialog.exec()

    # ------------------------------------------------------------------
    # Conversion
    # ------------------------------------------------------------------
    def _on_convert_clicked(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(self, "Conversion in Progress", "Please wait for the current job to finish.")
            return
        if not self._queue_items:
            QMessageBox.information(self, "Queue is Empty", "Drag PDF files onto the window, or click Browse.")
            return

        self._persist_settings()
        options = self._current_options()

        # Recompute output paths only where the *intended* target has
        # actually changed (output folder / suffix / filename option).
        # If it hasn't, keep the item's existing resolved path as-is --
        # otherwise converting the same unchanged queue a second time
        # would see its own prior output file on disk, mistake that for
        # a collision, and silently bump to _1, _2, ... every click,
        # even with nothing different about the request.
        reserved_output_paths = set()
        for item in self._queue_items:
            new_base = build_output_path(
                item.input_path,
                self._settings.output_folder,
                item.base_dir if len(self._queue_items) > 1 else None,
                self.chk_keep_filename.isChecked(),
                self.chk_add_suffix.isChecked(),
            )
            if new_base == item.base_output_path and item.output_path:
                # Target is unchanged from last time -- reuse the same
                # resolved path (overwrite our own prior output) rather
                # than re-running collision detection against ourselves.
                reserved_output_paths.add(item.output_path)
            else:
                item.output_path = resolve_unique_output_path(new_base, reserved_output_paths)
                item.base_output_path = new_base

        self.convert_btn.setEnabled(False)
        self.statusBar().showMessage(STATUS_CONVERTING)
        self._job_start_time = time.monotonic()

        self._worker = BatchWorker(self._queue_items, options)
        self._worker.file_started.connect(self._on_file_started)
        self._worker.file_progress.connect(self._on_file_progress)
        self._worker.file_finished.connect(self._on_file_finished)
        self._worker.file_failed.connect(self._on_file_failed)
        self._worker.overall_progress.connect(self._on_overall_progress)
        self._worker.time_remaining.connect(self.eta_label.setText)
        self._worker.report_ready.connect(self._on_report_ready)
        self._worker.all_finished.connect(self._on_all_finished)
        self._worker.start()

    def _on_file_started(self, row: int) -> None:
        self.queue_table.set_status(row, "Converting...")

    def _on_file_progress(self, row: int, current: int, total: int) -> None:
        self.queue_table.set_pages(row, total)
        self.queue_table.set_progress(row, current, total)

    def _on_file_finished(self, row: int, output_path: str) -> None:
        self.queue_table.set_status(row, "Done")
        item = self._queue_items[row]
        elapsed = time.monotonic() - self._job_start_time
        log_conversion(
            item.input_path, output_path,
            self.h_field.value(), self.v_field.value(), self.r_field.value(),
            elapsed,
        )

    def _on_file_failed(self, row: int, message: str) -> None:
        self.queue_table.set_status(row, "Error")
        log_error(self._queue_items[row].input_path, message)

    def _on_overall_progress(self, completed: int, total: int) -> None:
        self.overall_progress_label.setText(f"{completed} / {total} complete")

    def _on_all_finished(self, succeeded: int, failed: int) -> None:
        self.convert_btn.setEnabled(True)
        if failed == 0:
            self.statusBar().showMessage(STATUS_FINISHED)
        else:
            self.statusBar().showMessage(STATUS_ERRORS)
            failed_items = [i for i in self._queue_items if i.status == "Error"]
            details = "\n".join(f"- {os.path.basename(i.input_path)}: {i.error}" for i in failed_items[:8])
            QMessageBox.warning(
                self,
                "Some Files Could Not Be Converted",
                f"{succeeded} succeeded, {failed} failed.\n\n{details}",
            )

    def _on_report_ready(self, report_path: str) -> None:
        self._last_report_path = report_path or None
        self.open_report_btn.setEnabled(bool(report_path))

    # ------------------------------------------------------------------
    # Booklet
    # ------------------------------------------------------------------
    def _on_create_booklet_clicked(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(self, "Conversion in Progress", "Please wait for the current job to finish.")
            return
        if not self._queue_items:
            QMessageBox.information(self, "Queue is Empty", "Drag PDF files onto the window, or click Browse.")
            return

        layout_type = self.layout_type_combo.currentData()
        gui_duplex = self.booklet_duplex_combo.currentData()  # "long" | "short" | "twojob_long" | "twojob_short"

        input_paths = [item.input_path for item in self._queue_items]
        output_paths = []
        reserved = set()
        for item in self._queue_items:
            base, ext = os.path.splitext(item.output_path)
            suffix = "_booklet" if layout_type == "booklet" else "_2up"
            candidate = f"{base}{suffix}{ext}"
            output_paths.append(resolve_unique_output_path(candidate, reserved))

        if layout_type == "booklet":
            # BookletOptions expects "auto_long" / "auto_short" / "manual_long" / "manual_short".
            booklet_duplex = {
                "long": "auto_long", "short": "auto_short",
                "twojob_long": "manual_long", "twojob_short": "manual_short",
            }[gui_duplex]
            options = BookletOptions(duplex_mode=booklet_duplex)

            def job_fn(in_path: str, out_path: str) -> list:
                return build_booklet(in_path, out_path, options).output_paths

        else:
            # build_nup expects "single_long" / "single_short" / "twojob_long" / "twojob_short".
            nup_duplex = {
                "long": "single_long", "short": "single_short",
                "twojob_long": "twojob_long", "twojob_short": "twojob_short",
            }[gui_duplex]
            # Use the queued file's own first-page size as the target sheet size --
            # matches "fit 2 pages onto a normal sheet" rather than assuming a fixed paper size.
            import pikepdf as _pikepdf
            first_input = input_paths[0]
            with _pikepdf.open(first_input) as _probe:
                _box = _probe.pages[0].mediabox
                sheet_w = float(_box[2]) - float(_box[0])
                sheet_h = float(_box[3]) - float(_box[1])

            def job_fn(in_path: str, out_path: str) -> list:
                return build_nup(in_path, out_path, n=2, base_sheet_w=sheet_w, base_sheet_h=sheet_h, duplex_mode=nup_duplex).output_paths

        self.statusBar().showMessage("Creating layout(s)...")
        self._booklet_worker = BookletWorker(input_paths, output_paths, job_fn, parent=self)
        self._booklet_worker.file_finished.connect(self._on_booklet_finished)
        self._booklet_worker.file_failed.connect(self._on_booklet_failed)
        self._booklet_worker.all_finished.connect(self._on_booklet_all_finished)
        self._booklet_worker.start()

    def _on_booklet_finished(self, row: int, output_paths: list) -> None:
        item = self._queue_items[row]
        log_info(f"Layout created for {item.input_path}: {output_paths}")

    def _on_booklet_failed(self, row: int, message: str) -> None:
        item = self._queue_items[row]
        log_error(item.input_path, f"Layout creation failed: {message}")

    def _on_booklet_all_finished(self, succeeded: int, failed: int) -> None:
        if failed == 0:
            self.statusBar().showMessage(f"Layout(s) created: {succeeded} succeeded")
        else:
            self.statusBar().showMessage(f"Layout(s) created with errors: {succeeded} succeeded, {failed} failed")
            QMessageBox.warning(
                self, "Some Layouts Could Not Be Created",
                f"{succeeded} succeeded, {failed} failed. Check log.txt for details.",
            )

    # ------------------------------------------------------------------
    # File system helpers
    # ------------------------------------------------------------------
    def _on_open_output_folder(self) -> None:
        done_items = [i for i in self._queue_items if i.status == "Done"]
        if not done_items:
            QMessageBox.information(self, "No Output Yet", "Convert a file first.")
            return
        folder = os.path.dirname(done_items[-1].output_path)
        self._open_path(folder)

    def _on_open_output_pdf(self) -> None:
        done_items = [i for i in self._queue_items if i.status == "Done"]
        if not done_items:
            QMessageBox.information(self, "No Output Yet", "Convert a file first.")
            return
        self._open_path(done_items[-1].output_path)

    def _on_open_report(self) -> None:
        if not self._last_report_path:
            QMessageBox.information(self, "No Report Yet", "Convert a file first.")
            return
        self._open_path(self._last_report_path)

    @staticmethod
    def _open_path(path: str) -> None:
        try:
            if sys.platform == "win32":
                os.startfile(path)  # noqa: S606 -- Windows-only, by design
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except OSError as exc:
            log_info(f"Could not open path {path}: {exc}")

    # ------------------------------------------------------------------
    # Settings dialog
    # ------------------------------------------------------------------
    def _on_open_settings(self) -> None:
        dialog = SettingsDialog(self._settings, self)
        if dialog.exec():
            dialog.apply_to(self._settings)
            self.settings_manager.save()
            self._apply_theme()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        self._persist_settings()
        super().closeEvent(event)
