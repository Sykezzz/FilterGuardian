"""
widgets.py — Reusable custom widgets for both GUI apps
=======================================================
"""

from PySide6.QtWidgets import (
    QWidget, QFrame, QLabel, QVBoxLayout, QHBoxLayout, QPushButton,
    QGraphicsDropShadowEffect, QSizePolicy, QSpacerItem, QDialog,
    QScrollArea, QMessageBox,
)
from PySide6.QtCore import Qt, QSize, Signal, QPropertyAnimation, QEasingCurve, QTimer
from PySide6.QtGui import QFont, QColor, QPainter, QIcon, QPixmap

from theme import (
    BG_SECONDARY, BG_TERTIARY, BG_ELEVATED,
    TEXT_PRIMARY, TEXT_SECONDARY,
    ACCENT_BLUE, ACCENT_GREEN, ACCENT_YELLOW, ACCENT_RED, ACCENT_CYAN,
    BORDER_LIGHT, SPACE_SM, SPACE_MD, SPACE_LG, SPACE_XL,
    FONT_SIZE_DISPLAY, FONT_SIZE_TITLE, FONT_SIZE_HEADING, FONT_SIZE_BODY,
    FONT_SIZE_SMALL, RADIUS_MD, RADIUS_LG,
)


# ══════════════════════════════════════════════════════════════════════════════
#  LABELS
# ══════════════════════════════════════════════════════════════════════════════

class Label(QLabel):
    """Label with semantic variants. Use `variant` to pick the style."""
    def __init__(self, text="", variant="body", parent=None):
        super().__init__(text, parent)
        self.setObjectName(variant)
        self.setWordWrap(True)
        # Prevent Qt from painting the widget background, which can create
        # dark boxes ("black bars") when a label sits on a styled panel.
        self.setAutoFillBackground(False)


class Badge(QLabel):
    """A small colored pill for status indicators."""
    def __init__(self, text="", variant="info", parent=None):
        super().__init__(f"  {text}  ", parent)
        self.setObjectName(f"badge_{variant}")
        self.setAlignment(Qt.AlignCenter)
        self.setMaximumHeight(22)


# ══════════════════════════════════════════════════════════════════════════════
#  CARDS
# ══════════════════════════════════════════════════════════════════════════════

class Card(QFrame):
    """Container card with dark bg, border, rounded corners."""
    def __init__(self, parent=None, elevated=False):
        super().__init__(parent)
        self.setObjectName("card_elevated" if elevated else "card")
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(SPACE_LG, SPACE_LG, SPACE_LG, SPACE_LG)
        self.layout.setSpacing(SPACE_MD)

    def add_title(self, text: str, subtitle: str = None):
        """Add a title bar with optional subtitle at the top of the card."""
        title = Label(text, variant="heading")
        self.layout.addWidget(title)
        if subtitle:
            sub = Label(subtitle, variant="subtitle")
            self.layout.addWidget(sub)


class MetricCard(QFrame):
    """Large-number display card. Use for 'total changes today', etc."""
    def __init__(self, label: str, value: str = "—", color: str = TEXT_PRIMARY,
                 icon: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setMinimumHeight(110)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE_LG, SPACE_MD, SPACE_LG, SPACE_MD)
        layout.setSpacing(SPACE_SM)

        header = QHBoxLayout()
        header.setSpacing(SPACE_SM)
        if icon:
            icon_lbl = QLabel(icon)
            icon_lbl.setStyleSheet(f"font-size: 16px; color: {TEXT_SECONDARY};")
            header.addWidget(icon_lbl)
        label_lbl = Label(label.upper(), variant="caption")
        label_lbl.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: {FONT_SIZE_SMALL}px; "
            f"letter-spacing: 0.8px; font-weight: 600;"
        )
        header.addWidget(label_lbl)
        header.addStretch(1)
        layout.addLayout(header)

        self.value_label = QLabel(str(value))
        self.value_label.setAutoFillBackground(False)
        self.value_label.setStyleSheet(
            f"color: {color}; font-size: {FONT_SIZE_DISPLAY}px; "
            f"font-weight: 700; background-color: transparent;"
        )
        layout.addWidget(self.value_label)
        layout.addStretch(1)

    def set_value(self, value):
        self.value_label.setText(str(value))

    def set_color(self, color: str):
        self.value_label.setStyleSheet(
            f"color: {color}; font-size: {FONT_SIZE_DISPLAY}px; "
            f"font-weight: 700; background-color: transparent;"
        )


# ══════════════════════════════════════════════════════════════════════════════
#  BUTTONS
# ══════════════════════════════════════════════════════════════════════════════

class PrimaryButton(QPushButton):
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setObjectName("primary")
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(36)


class SecondaryButton(QPushButton):
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(36)


class DangerButton(QPushButton):
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setObjectName("danger")
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(36)


class GhostButton(QPushButton):
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setObjectName("ghost")
        self.setCursor(Qt.PointingHandCursor)


class NavButton(QPushButton):
    """Sidebar navigation item."""
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setObjectName("sidebar_nav")
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(40)


# ══════════════════════════════════════════════════════════════════════════════
#  TOAST / NOTIFICATION
# ══════════════════════════════════════════════════════════════════════════════

class Toast(QFrame):
    """Non-blocking notification that fades in/out from the bottom-right."""
    def __init__(self, parent, message: str, variant: str = "info", duration_ms: int = 3500):
        super().__init__(parent)
        self.setObjectName("card_elevated")
        self.setAttribute(Qt.WA_ShowWithoutActivating)

        # Accent stripe color by variant
        variant_map = {
            "success": ACCENT_GREEN,
            "error":   ACCENT_RED,
            "warning": ACCENT_YELLOW,
            "info":    ACCENT_BLUE,
        }
        color = variant_map.get(variant, ACCENT_BLUE)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, SPACE_LG, 0)
        layout.setSpacing(0)

        stripe = QFrame()
        stripe.setFixedWidth(4)
        stripe.setStyleSheet(f"background-color: {color}; border-radius: 2px;")
        layout.addWidget(stripe)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(SPACE_MD, SPACE_SM, SPACE_SM, SPACE_SM)
        text_layout.setSpacing(0)
        msg_label = QLabel(message)
        msg_label.setStyleSheet(
            f"color: {TEXT_PRIMARY}; font-size: {FONT_SIZE_BODY}px; font-weight: 500;"
        )
        msg_label.setWordWrap(True)
        text_layout.addWidget(msg_label)
        layout.addLayout(text_layout)

        self.setMinimumWidth(320)
        self.setMaximumWidth(420)

        # Drop shadow
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(0, 0, 0, 180))
        self.setGraphicsEffect(shadow)

        self._duration = duration_ms

    def show_toast(self):
        parent = self.parent()
        if parent:
            # Position at bottom-right with margin
            self.adjustSize()
            x = parent.width() - self.width() - SPACE_XL
            y = parent.height() - self.height() - SPACE_XL
            self.move(x, y)
        self.show()
        self.raise_()
        QTimer.singleShot(self._duration, self._fade_out)

    def _fade_out(self):
        self.hide()
        self.deleteLater()


def show_toast(parent, message: str, variant: str = "info"):
    """Convenience fn — stack toasts if multiple are shown in rapid succession."""
    toast = Toast(parent, message, variant=variant)
    toast.show_toast()


# ══════════════════════════════════════════════════════════════════════════════
#  SECTION / DIVIDER
# ══════════════════════════════════════════════════════════════════════════════

class Section(QWidget):
    """Page section with title and body area."""
    def __init__(self, title: str, subtitle: str = None, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(SPACE_SM)

        title_row = QHBoxLayout()
        title_row.setSpacing(SPACE_MD)
        self.title_label = Label(title, variant="title")
        title_row.addWidget(self.title_label)
        title_row.addStretch(1)
        self.actions_row = title_row   # expose so subclasses can add buttons
        self.layout.addLayout(title_row)

        if subtitle:
            self.subtitle_label = Label(subtitle, variant="subtitle")
            self.layout.addWidget(self.subtitle_label)

        self.body = QVBoxLayout()
        self.body.setSpacing(SPACE_MD)
        self.layout.addLayout(self.body)


class Divider(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.HLine)
        self.setStyleSheet(f"color: {BORDER_LIGHT}; background: {BORDER_LIGHT}; max-height: 1px;")


# ══════════════════════════════════════════════════════════════════════════════
#  CONFIRM DIALOG
# ══════════════════════════════════════════════════════════════════════════════

def confirm(parent, title: str, message: str, danger: bool = False) -> bool:
    """Modal confirmation dialog. Returns True if user confirmed."""
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(message)
    box.setIcon(QMessageBox.Warning if danger else QMessageBox.Question)
    box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
    box.setDefaultButton(QMessageBox.No if danger else QMessageBox.Yes)
    result = box.exec()
    return result == QMessageBox.Yes


# ══════════════════════════════════════════════════════════════════════════════
#  EMPTY STATE
# ══════════════════════════════════════════════════════════════════════════════

class EmptyState(QWidget):
    """Placeholder for empty lists/tables."""
    def __init__(self, icon: str, title: str, subtitle: str = "",
                 action_button: QPushButton = None, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(SPACE_MD)

        icon_lbl = QLabel(icon)
        icon_lbl.setAlignment(Qt.AlignCenter)
        icon_lbl.setStyleSheet(f"font-size: 48px; color: {TEXT_SECONDARY};")
        layout.addWidget(icon_lbl)

        title_lbl = Label(title, variant="heading")
        title_lbl.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_lbl)

        if subtitle:
            sub_lbl = Label(subtitle, variant="subtitle")
            sub_lbl.setAlignment(Qt.AlignCenter)
            layout.addWidget(sub_lbl)

        if action_button:
            btn_row = QHBoxLayout()
            btn_row.addStretch(1)
            btn_row.addWidget(action_button)
            btn_row.addStretch(1)
            layout.addLayout(btn_row)


# ══════════════════════════════════════════════════════════════════════════════
#  SCROLL WHEEL FORWARDING
# ══════════════════════════════════════════════════════════════════════════════

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QAbstractScrollArea, QAbstractItemView


class _WheelForwarder(QObject):
    """Event filter that forwards wheel events to the parent scroll area
    UNLESS the widget actually needs its own scroll (content larger than view)."""
    def eventFilter(self, obj, event):
        if event.type() != QEvent.Wheel:
            return False
        # Find the target scroll bar on `obj` (QTableWidget, QTextEdit, etc.)
        try:
            v_bar = obj.verticalScrollBar()
            if v_bar is None or v_bar.maximum() == v_bar.minimum():
                # Widget doesn't need to scroll — forward to parent
                self._forward_to_parent(obj, event)
                return True
            # Widget does need to scroll. Forward to parent only if we're
            # at the top/bottom edge and the wheel direction would overscroll.
            delta = event.angleDelta().y()
            at_top    = v_bar.value() == v_bar.minimum()
            at_bottom = v_bar.value() == v_bar.maximum()
            if (delta > 0 and at_top) or (delta < 0 and at_bottom):
                self._forward_to_parent(obj, event)
                return True
        except Exception:
            pass
        return False

    def _forward_to_parent(self, obj, event):
        # Walk up looking for a QScrollArea and send the event there
        parent = obj.parent()
        while parent is not None:
            if isinstance(parent, QScrollArea):
                parent.wheelEvent(event)
                return
            parent = parent.parent()


_GLOBAL_WHEEL_FORWARDER = _WheelForwarder()


def forward_wheel(widget):
    """Install the wheel forwarder on a widget so it doesn't steal scroll events
    from parent QScrollArea when it doesn't need to scroll itself."""
    try:
        widget.installEventFilter(_GLOBAL_WHEEL_FORWARDER)
        # For QAbstractItemView (tables/lists), also install on the viewport
        if isinstance(widget, QAbstractItemView):
            widget.viewport().installEventFilter(_GLOBAL_WHEEL_FORWARDER)
    except Exception:
        pass


def install_wheel_forwarding_recursive(root_widget):
    """Walk the widget tree and install wheel-forwarding on every table / text
    edit / list / combobox. Call this once per page after UI construction.
    Safe to call multiple times (event filter only installed once per widget).
    """
    from PySide6.QtWidgets import QTextEdit, QPlainTextEdit, QListWidget, QComboBox
    try:
        for child in root_widget.findChildren(QAbstractItemView):
            forward_wheel(child)
        for cls in (QTextEdit, QPlainTextEdit, QListWidget, QComboBox):
            for child in root_widget.findChildren(cls):
                forward_wheel(child)
    except Exception:
        pass
