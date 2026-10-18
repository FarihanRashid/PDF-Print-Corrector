"""
drop_zone.py

The large drag-and-drop target on the main window. Accepts single
PDFs, multiple PDFs, or entire folders (folders are expanded
recursively by the caller via utils.file_utils.discover_pdfs).
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDropEvent
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout

from utils.constants import OBJ_DROP_ZONE, OBJ_PRIMARY_BUTTON


class DropZone(QFrame):
    filesDropped = Signal(list)   # list[str] of file/folder paths
    browseClicked = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName(OBJ_DROP_ZONE)
        self.setAcceptDrops(True)
        self.setMinimumHeight(220)
        self.setProperty("dragActive", "false")

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(10)

        icon_label = QLabel("\U0001F4C4")
        icon_label.setAlignment(Qt.AlignCenter)
        icon_label.setStyleSheet("font-size: 40pt;")
        layout.addWidget(icon_label)

        title = QLabel("Drag PDF(s) Here")
        title.setAlignment(Qt.AlignCenter)
        title.setProperty("role", "heading")
        layout.addWidget(title)

        subtitle = QLabel("Single files, multiple files, or entire folders")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setProperty("role", "muted")
        layout.addWidget(subtitle)

        self.browse_button = QPushButton("Browse Files")
        self.browse_button.setObjectName(OBJ_PRIMARY_BUTTON)
        self.browse_button.setFixedWidth(160)
        self.browse_button.clicked.connect(self.browseClicked.emit)
        layout.addWidget(self.browse_button, alignment=Qt.AlignCenter)

    # -- drag and drop -----------------------------------------------

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._set_drag_active(True)
        else:
            event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self._set_drag_active(False)

    def dropEvent(self, event: QDropEvent) -> None:
        self._set_drag_active(False)
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            self.filesDropped.emit(paths)
        event.acceptProposedAction()

    def _set_drag_active(self, active: bool) -> None:
        self.setProperty("dragActive", "true" if active else "false")
        self.style().unpolish(self)
        self.style().polish(self)
