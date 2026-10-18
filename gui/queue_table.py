"""
queue_table.py

The conversion queue: a table showing each PDF's filename, page
count, status, computed output filename, and a per-row progress bar.
"""

from __future__ import annotations

import os
from typing import List

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHeaderView, QProgressBar, QTableWidget, QTableWidgetItem

from engine.batch_worker import QueueItem

COL_FILENAME = 0
COL_PAGES = 1
COL_STATUS = 2
COL_OUTPUT = 3
COL_PROGRESS = 4

STATUS_COLORS = {
    "Queued": "#9aa0ae",
    "Converting...": "#5b8cff",
    "Done": "#4cc38a",
    "Error": "#e5636b",
}


class QueueTable(QTableWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(0, 5, parent)
        self.setHorizontalHeaderLabels(["Filename", "Pages", "Status", "Output Filename", "Progress"])
        self.setEditTriggers(QTableWidget.NoEditTriggers)
        self.setSelectionBehavior(QTableWidget.SelectRows)
        self.verticalHeader().setVisible(False)
        header = self.horizontalHeader()
        header.setSectionResizeMode(COL_FILENAME, QHeaderView.Stretch)
        header.setSectionResizeMode(COL_PAGES, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(COL_STATUS, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(COL_OUTPUT, QHeaderView.Stretch)
        header.setSectionResizeMode(COL_PROGRESS, QHeaderView.Fixed)
        self.setColumnWidth(COL_PROGRESS, 130)

    def load_items(self, items: List[QueueItem]) -> None:
        self.setRowCount(0)
        for item in items:
            self.append_item(item)

    def append_item(self, item: QueueItem) -> None:
        row = self.rowCount()
        self.insertRow(row)
        self.setItem(row, COL_FILENAME, QTableWidgetItem(os.path.basename(item.input_path)))
        self.setItem(row, COL_PAGES, QTableWidgetItem("--"))
        self.set_status(row, item.status)
        self.setItem(row, COL_OUTPUT, QTableWidgetItem(os.path.basename(item.output_path)))

        progress = QProgressBar()
        progress.setRange(0, 100)
        progress.setValue(0)
        progress.setTextVisible(False)
        progress.setFixedHeight(14)
        self.setCellWidget(row, COL_PROGRESS, progress)

    def set_status(self, row: int, status: str) -> None:
        item = QTableWidgetItem(status)
        color = STATUS_COLORS.get(status, "#9aa0ae")
        item.setForeground(Qt.GlobalColor.white)
        item.setData(Qt.ForegroundRole, None)
        self.setItem(row, COL_STATUS, item)
        cell = self.item(row, COL_STATUS)
        if cell:
            cell.setForeground(_qcolor(color))

    def set_pages(self, row: int, pages: int) -> None:
        self.setItem(row, COL_PAGES, QTableWidgetItem(str(pages)))

    def set_progress(self, row: int, current: int, total: int) -> None:
        widget = self.cellWidget(row, COL_PROGRESS)
        if isinstance(widget, QProgressBar) and total > 0:
            widget.setValue(int(current / total * 100))

    def clear_queue(self) -> None:
        self.setRowCount(0)


def _qcolor(hex_str: str):
    from PySide6.QtGui import QColor

    return QColor(hex_str)
