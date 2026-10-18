"""
preview_dialog.py

Optional "before / after" preview. IMPORTANT: this dialog rasterizes
pages purely to draw them on screen as a QPixmap -- Qt widgets can
only display raster images. This has nothing to do with the actual
conversion, which stays 100% vector; the preview is a read-only aid so
the user can sanity-check an offset before committing to a batch run.

Requires PyMuPDF (fitz) only for this optional preview; the core
engine (engine/pdf_engine.py) never imports it and never rasterizes.
"""

from __future__ import annotations

import tempfile
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from engine.pdf_engine import TranslationOptions, translate_pdf


class PreviewDialog(QDialog):
    def __init__(self, input_path: str, options: TranslationOptions, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Preview - Before / After")
        self.resize(900, 760)
        self._input_path = input_path
        self._options = options
        self._zoom = 1.4
        self._showing_after = True

        layout = QVBoxLayout(self)

        toolbar = QHBoxLayout()
        self.toggle_btn = QPushButton("Show Original")
        self.toggle_btn.clicked.connect(self._toggle)
        toolbar.addWidget(self.toggle_btn)

        toolbar.addWidget(QLabel("Zoom"))
        self.zoom_slider = QSlider(Qt.Horizontal)
        self.zoom_slider.setRange(50, 300)
        self.zoom_slider.setValue(140)
        self.zoom_slider.valueChanged.connect(self._on_zoom_changed)
        toolbar.addWidget(self.zoom_slider)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)

        self.applied_label = QLabel("")
        self.applied_label.setProperty("role", "muted")
        self.applied_label.setWordWrap(True)
        layout.addWidget(self.applied_label)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.image_label = QLabel("Rendering preview...")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.scroll_area.setWidget(self.image_label)
        layout.addWidget(self.scroll_area)

        self._corrected_path: Optional[str] = None
        self._render_after()

    def _render_after(self) -> None:
        try:
            tmp = tempfile.NamedTemporaryFile(suffix="_preview.pdf", delete=False)
            tmp.close()
            result = translate_pdf(self._input_path, tmp.name, self._options)
            self._corrected_path = tmp.name
            self._update_applied_label(result)
        except Exception as exc:  # noqa: BLE001
            self.image_label.setText(f"Could not render preview: {exc}")
            return
        self._render_current()

    def _update_applied_label(self, result) -> None:
        o = self._options
        lines = [
            f"Requested: X = {o.horizontal_offset_mm:+.2f} mm, Y = {o.vertical_offset_mm:+.2f} mm, "
            f"Rotation = {o.rotation_degrees:.2f}\u00b0, Scale = {o.scale_percent:.1f}%"
        ]
        if o.translation_mode == "smart" and result.page_reports:
            first = result.page_reports[0]
            if first.was_adjusted:
                lines.append(
                    f"Applied to page 1: X = {first.applied_dx_mm:+.2f} mm, Y = {first.applied_dy_mm:+.2f} mm, "
                    f"Scale = {first.applied_scale_percent:.1f}%  "
                    f"({'fully avoided clipping' if first.fully_avoided_clipping else 'could not fully avoid clipping'})"
                )
            else:
                lines.append("Smart Translation: no adjustment needed for page 1.")
        elif o.translation_mode == "strict":
            lines.append("Strict mode: applied exactly as requested (may clip).")
        self.applied_label.setText("\n".join(lines))

    def _render_current(self) -> None:
        path = self._corrected_path if self._showing_after else self._input_path
        if not path:
            return
        try:
            import fitz  # local import: optional preview-only dependency

            doc = fitz.open(path)
            page = doc[0]
            pix = page.get_pixmap(matrix=fitz.Matrix(self._zoom, self._zoom))
            image_bytes = pix.tobytes("png")
            pixmap = QPixmap()
            pixmap.loadFromData(image_bytes, "PNG")
            self.image_label.setPixmap(pixmap)
            doc.close()
        except Exception as exc:  # noqa: BLE001
            self.image_label.setText(f"Could not render preview: {exc}")

    def _toggle(self) -> None:
        self._showing_after = not self._showing_after
        self.toggle_btn.setText("Show Original" if self._showing_after else "Show Corrected")
        self._render_current()

    def _on_zoom_changed(self, value: int) -> None:
        self._zoom = value / 100.0
        self._render_current()
