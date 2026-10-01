from widgets import Label, Badge, Card, MetricCard, PrimaryButton, SecondaryButton, DangerButton, GhostButton, NavButton, show_toast, Section, Divider, confirm, EmptyState, forward_wheel, install_wheel_forwarding_recursive

from PySide6.QtWidgets import QWidget, QVBoxLayout, QPushButton
from PySide6.QtCore import Qt

class NavCategory(QWidget):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        
        self.btn = QPushButton(f"▼  {title}")
        self.btn.setStyleSheet("text-align: left; font-weight: bold; font-size: 11px; padding: 6px 8px; color: #8F95B2; background: transparent; border: none; letter-spacing: 1px;")
        self.btn.setCursor(Qt.PointingHandCursor)
        self.btn.clicked.connect(self.toggle)
        self.layout.addWidget(self.btn)
        
        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(12, 0, 0, 0)
        self.content_layout.setSpacing(2)
        self.layout.addWidget(self.content)
        
    def addWidget(self, w):
        self.content_layout.addWidget(w)
        
    def toggle(self):
        if self.content.isVisible():
            self.content.hide()
            self.btn.setText(self.btn.text().replace("▼", "▶"))
        else:
            self.content.show()
            self.btn.setText(self.btn.text().replace("▶", "▼"))
