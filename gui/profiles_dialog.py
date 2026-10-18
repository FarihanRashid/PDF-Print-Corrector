"""
profiles_dialog.py

Dialog for managing named printer profiles: create, rename, delete,
and pick the default. Selecting a profile in the main window applies
its offsets to the horizontal/vertical/rotation fields.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from profiles.profile_manager import PrinterProfile, ProfileManager
from gui.widgets import HorizontalOffsetField, RotationField, VerticalOffsetField


class ProfilesDialog(QDialog):
    def __init__(self, manager: ProfileManager, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Printer Profiles")
        self.setMinimumSize(560, 420)
        self.manager = manager

        root = QHBoxLayout(self)

        # -- left: list -------------------------------------------------
        left = QVBoxLayout()
        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list_widget.currentRowChanged.connect(self._on_selection_changed)
        left.addWidget(self.list_widget)

        list_buttons = QHBoxLayout()
        add_btn = QPushButton("Create")
        add_btn.clicked.connect(self._create_profile)
        rename_btn = QPushButton("Rename")
        rename_btn.clicked.connect(self._rename_profile)
        delete_btn = QPushButton("Delete")
        delete_btn.setObjectName("dangerButton")
        delete_btn.clicked.connect(self._delete_profile)
        list_buttons.addWidget(add_btn)
        list_buttons.addWidget(rename_btn)
        list_buttons.addWidget(delete_btn)
        left.addLayout(list_buttons)

        self.default_btn = QPushButton("Select as Default")
        self.default_btn.clicked.connect(self._select_default)
        left.addWidget(self.default_btn)

        root.addLayout(left, 1)

        # -- right: editor ------------------------------------------------
        right = QVBoxLayout()
        self.editor_title = QLabel("No profile selected")
        self.editor_title.setProperty("role", "heading")
        right.addWidget(self.editor_title)

        self.h_field = HorizontalOffsetField()
        self.v_field = VerticalOffsetField()
        self.r_field = RotationField()
        for field in (self.h_field, self.v_field, self.r_field):
            field.valueChanged.connect(self._save_current_values)
            right.addWidget(field)

        right.addStretch(1)
        root.addLayout(right, 1)

        outer = QVBoxLayout()
        outer.addLayout(root)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        buttons.button(QDialogButtonBox.Close).clicked.connect(self.accept)
        self.layout().addWidget(buttons)

        self._refresh_list()

    def _refresh_list(self, select_name: str | None = None) -> None:
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        for profile in self.manager.profiles:
            label = profile.name
            if profile.name == self.manager.default_profile_name:
                label += "  (default)"
            item = QListWidgetItem(label)
            item.setData(1, profile.name)
            self.list_widget.addItem(item)
        self.list_widget.blockSignals(False)

        if select_name:
            for i in range(self.list_widget.count()):
                if self.list_widget.item(i).data(1) == select_name:
                    self.list_widget.setCurrentRow(i)
                    return
        if self.list_widget.count():
            self.list_widget.setCurrentRow(0)
        else:
            self.editor_title.setText("No profile selected")

    def _current_profile_name(self) -> str | None:
        item = self.list_widget.currentItem()
        return item.data(1) if item else None

    def _on_selection_changed(self, _row: int) -> None:
        name = self._current_profile_name()
        if not name:
            return
        profile = self.manager.get(name)
        if not profile:
            return
        self.editor_title.setText(profile.name)
        self.h_field.set_value(profile.horizontal_offset_mm)
        self.v_field.set_value(profile.vertical_offset_mm)
        self.r_field.set_value(profile.rotation_degrees)

    def _save_current_values(self, _value: float) -> None:
        name = self._current_profile_name()
        if not name:
            return
        self.manager.update(name, self.h_field.value(), self.v_field.value(), self.r_field.value())

    def _create_profile(self) -> None:
        name, ok = QInputDialog.getText(self, "Create Profile", "Profile name:")
        if not ok or not name.strip():
            return
        try:
            self.manager.add(PrinterProfile(name=name.strip(), horizontal_offset_mm=0.0, vertical_offset_mm=0.0, rotation_degrees=0.0))
        except ValueError as exc:
            QMessageBox.warning(self, "Cannot Create Profile", str(exc))
            return
        self._refresh_list(select_name=name.strip())

    def _rename_profile(self) -> None:
        name = self._current_profile_name()
        if not name:
            return
        new_name, ok = QInputDialog.getText(self, "Rename Profile", "New name:", text=name)
        if not ok or not new_name.strip():
            return
        try:
            self.manager.rename(name, new_name.strip())
        except ValueError as exc:
            QMessageBox.warning(self, "Cannot Rename Profile", str(exc))
            return
        self._refresh_list(select_name=new_name.strip())

    def _delete_profile(self) -> None:
        name = self._current_profile_name()
        if not name:
            return
        confirm = QMessageBox.question(self, "Delete Profile", f"Delete profile '{name}'?")
        if confirm != QMessageBox.Yes:
            return
        self.manager.delete(name)
        self._refresh_list()

    def _select_default(self) -> None:
        name = self._current_profile_name()
        if not name:
            return
        self.manager.set_default(name)
        self._refresh_list(select_name=name)
