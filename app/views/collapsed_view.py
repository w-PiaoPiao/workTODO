"""
折叠模式视图

紧凑条模式，始终显示：
- 图标 + 待办计数
- 快速添加按钮
- 展开按钮
"""

from __future__ import annotations

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QPushButton, QFrame, QSizePolicy,
)
from app.config import AppConfig
from app.views.theme import AppTheme


class CollapsedView(QFrame):
    """紧凑模式视图"""

    signal_expand_clicked = Signal()
    signal_quick_add_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setFixedHeight(AppConfig.COLLAPSED_HEIGHT)
        self.setStyleSheet(self._make_style())

        # ── 构建 UI ───────────────────────────────────────
        layout = QHBoxLayout()
        layout.setContentsMargins(12, 0, 8, 0)
        layout.setSpacing(6)

        # 图标
        self._icon_label = QLabel("📋")
        self._icon_label.setStyleSheet("font-size: 16px; background: transparent;")

        # 计数标签
        self._count_label = QLabel("没有待办事项")
        self._count_label.setStyleSheet(f"""
            font: {AppTheme.FONT["body"]};
            color: {AppTheme.C["text_primary"]};
            background: transparent;
        """)

        # 弹簧
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        spacer.setStyleSheet("background: transparent;")

        # 快速添加按钮
        self._quick_add_btn = QPushButton("＋")
        self._quick_add_btn.setFixedSize(28, 28)
        self._quick_add_btn.setToolTip("快速添加待办")
        self._quick_add_btn.setStyleSheet(self._btn_style())
        self._quick_add_btn.clicked.connect(self.signal_quick_add_clicked.emit)

        # 展开按钮
        self._expand_btn = QPushButton("⤢")
        self._expand_btn.setFixedSize(28, 28)
        self._expand_btn.setToolTip("展开")
        self._expand_btn.setStyleSheet(self._btn_style())
        self._expand_btn.clicked.connect(self.signal_expand_clicked.emit)

        # 组装
        layout.addWidget(self._icon_label)
        layout.addWidget(self._count_label)
        layout.addWidget(spacer)
        layout.addWidget(self._quick_add_btn)
        layout.addWidget(self._expand_btn)

        self.setLayout(layout)

    # ── 更新 ──────────────────────────────────────────────

    def update_count(self, count: int) -> None:
        """更新待办计数显示"""
        if count == 0:
            self._count_label.setText("没有待办事项")
        elif count > 99:
            self._count_label.setText("99+ 项待办")
        else:
            self._count_label.setText(f"{count} 项待办")

    # ── 样式 ──────────────────────────────────────────────

    def _make_style(self) -> str:
        C = AppTheme.C
        return f"""
            CollapsedView {{
                background: {C["bg_primary"]};
                border: 1px solid {C["border"]};
                border-radius: 8px;
            }}
        """

    @staticmethod
    def _btn_style() -> str:
        C = AppTheme.C
        return f"""
            QPushButton {{
                font-size: 16px;
                color: {C["text_secondary"]};
                border-radius: 4px;
                padding: 2px;
                background: transparent;
            }}
            QPushButton:hover {{
                background: {C["bg_hover"]};
                color: {C["accent"]};
            }}
        """
