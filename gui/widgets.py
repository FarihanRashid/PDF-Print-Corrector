"""
widgets.py

Small, reusable widgets shared across the main window and dialogs.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from utils.constants import (
    MAX_OFFSET_MM,
    MAX_ROTATION_DEG,
    MAX_SCALE_PERCENT,
    MIN_OFFSET_MM,
    MIN_ROTATION_DEG,
    MIN_SCALE_PERCENT,
)


class NoScrollDoubleSpinBox(QDoubleSpinBox):
    """A QDoubleSpinBox that only responds to the mouse wheel while it
    has keyboard focus (i.e. after being clicked into).

    By default, Qt spin boxes react to the mouse wheel just from being
    hovered over -- so scrolling the panel to see checkboxes below can
    silently change an offset value without the user ever clicking
    anything. Requiring focus first matches how most desktop apps
    behave and prevents that accidental drift.

    Native step buttons are disabled here (see LabeledOffsetField)
    in favour of plain QToolButtons placed alongside it in an
    ordinary layout. Qt's built-in spin box arrows are positioned via
    internal "subcontrol" geometry that a custom stylesheet has to
    override by hand, and that calculation has proven unreliable
    across Windows display-scaling settings and window resizes --
    text has ended up misaligned or clipped inside the field in ways
    that don't reproduce in every environment. Plain buttons in a
    plain QHBoxLayout sidestep that: ordinary Qt layout math is not
    in doubt the way its internal spin box subcontrol rendering has
    been.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setButtonSymbols(QDoubleSpinBox.NoButtons)

    def wheelEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


class _StepButton(QToolButton):
    """A small fixed-size up/down step button, styled via objectName
    rather than a spin-box subcontrol selector."""

    def __init__(self, glyph: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("stepButton")
        self.setText(glyph)
        self.setFixedSize(26, 17)
        self.setAutoRepeat(True)
        self.setAutoRepeatInterval(60)
        self.setAutoRepeatDelay(350)
        self.setFocusPolicy(Qt.NoFocus)
        self.setCursor(Qt.PointingHandCursor)


class LabeledOffsetField(QWidget):
    """A titled numeric field with a unit suffix, e.g. 'Horizontal Offset  [ 4.00 ] mm'."""

    valueChanged = Signal(float)

    def __init__(
        self,
        title: str,
        unit: str,
        minimum: float,
        maximum: float,
        decimals: int = 2,
        step: float = 0.25,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        title_label = QLabel(title)
        title_label.setProperty("role", "muted")
        layout.addWidget(title_label)

        row = QHBoxLayout()
        row.setSpacing(6)

        self.spin_box = NoScrollDoubleSpinBox()
        self.spin_box.setRange(minimum, maximum)
        self.spin_box.setDecimals(decimals)
        self.spin_box.setSingleStep(step)
        self.spin_box.setSuffix(f" {unit}")
        self.spin_box.setAlignment(Qt.AlignRight)
        self.spin_box.setMinimumHeight(38)
        self.spin_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.spin_box.valueChanged.connect(self.valueChanged.emit)
        row.addWidget(self.spin_box, 1)

        button_column = QVBoxLayout()
        button_column.setSpacing(0)
        self.up_button = _StepButton("\u25B2")
        self.down_button = _StepButton("\u25BC")
        self.up_button.clicked.connect(self.spin_box.stepUp)
        self.down_button.clicked.connect(self.spin_box.stepDown)
        button_column.addWidget(self.up_button)
        button_column.addWidget(self.down_button)
        row.addLayout(button_column)

        layout.addLayout(row)

    def value(self) -> float:
        return self.spin_box.value()

    def set_value(self, value: float) -> None:
        self.spin_box.setValue(value)


class HorizontalOffsetField(LabeledOffsetField):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Horizontal Offset", "mm", MIN_OFFSET_MM, MAX_OFFSET_MM, parent=parent)


class VerticalOffsetField(LabeledOffsetField):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Vertical Offset", "mm", MIN_OFFSET_MM, MAX_OFFSET_MM, parent=parent)


class RotationField(LabeledOffsetField):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Rotation", "\u00b0", MIN_ROTATION_DEG, MAX_ROTATION_DEG, step=0.1, parent=parent)


class ScaleField(LabeledOffsetField):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            "Scale", "%", MIN_SCALE_PERCENT, MAX_SCALE_PERCENT, decimals=1, step=0.1, parent=parent
        )
