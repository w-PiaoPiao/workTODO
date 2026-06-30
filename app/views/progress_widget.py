"""
进度条目展示组件

用于在待办卡片中展示进度历史，支持展开/折叠。
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton, QHBoxLayout,
)
from app.config import AppConfig
from app.views.theme import AppTheme
from app.views.elided_label import ElidedLabel
from app.models.todo_item import ProgressEntry


class ProgressWidget(QWidget):
    """进度条目列表"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._entries: list[ProgressEntry] = []
        self._collapsed = True
        self._threshold = AppConfig.MAX_PROGRESS_COLLAPSED

        self._build_ui()

    def _build_ui(self) -> None:
        self._layout = QVBoxLayout()
        self._layout.setContentsMargins(28, 2, 0, 2)
        self._layout.setSpacing(2)

        # 进度条目将动态插入
        self._toggle_btn = QPushButton()
        self._toggle_btn.setStyleSheet(f"""
            QPushButton {{
                font: {AppTheme.FONT["small"]};
                color: {AppTheme.C["accent"]};
                border: none;
                padding: 2px 0;
                text-align: left;
                background: transparent;
            }}
            QPushButton:hover {{
                color: {AppTheme.C["accent_hover"]};
            }}
        """)
        self._toggle_btn.clicked.connect(self._on_toggle)

        self.setLayout(self._layout)

    def set_entries(self, entries: list[ProgressEntry]) -> None:
        """设置进度条目"""
        self._entries = entries
        self._refresh()

    def add_entry(self, entry: ProgressEntry) -> None:
        """追加一条新进度"""
        self._entries.append(entry)
        self._refresh()

    def _refresh(self) -> None:
        """刷新显示"""
        # 清空
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        if not self._entries:
            self._show_empty()
            return

        # 确定显示哪些条目
        show_entries = self._entries
        if self._collapsed and len(self._entries) > self._threshold:
            show_entries = self._entries[-self._threshold:]

        # 渲染进度条目
        for entry in show_entries:
            row = self._make_entry_row(entry)
            self._layout.addWidget(row)

        # 折叠/展开按钮
        if len(self._entries) > self._threshold:
            hidden = len(self._entries) - self._threshold
            if self._collapsed:
                self._toggle_btn.setText(f"查看全部 {len(self._entries)} 条进度 ▼")
            else:
                self._toggle_btn.setText(f"收起 ▲")
            self._layout.addWidget(self._toggle_btn)

    def _show_empty(self) -> None:
        """显示暂无进度"""
        label = QLabel("暂无进度")
        label.setStyleSheet(f"""
            font: {AppTheme.FONT["small"]};
            color: {AppTheme.C["text_disabled"]};
            padding: 2px 0;
            background: transparent;
        """)
        self._layout.addWidget(label)

    def _make_entry_row(self, entry: ProgressEntry) -> QWidget:
        """创建单条进度显示行"""
        row = QWidget()
        row.setStyleSheet("background: transparent;")
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        time_label = QLabel(entry.time_display)
        time_label.setStyleSheet(f"""
            font: {AppTheme.FONT["small"]};
            color: {AppTheme.C["text_disabled"]};
            background: transparent;
        """)
        time_label.setFixedWidth(50)

        # ElidedLabel 内部 paintEvent 实时算省略，无需 eventFilter/singleShot
        text_label = ElidedLabel(entry.text)
        text_label.setStyleSheet(f"""
            font: {AppTheme.FONT["small"]};
            color: {AppTheme.C["text_secondary"]};
            background: transparent;
        """)

        layout.addWidget(time_label)
        layout.addWidget(text_label, stretch=1)
        row.setLayout(layout)
        return row

    def _on_toggle(self) -> None:
        self._collapsed = not self._collapsed
        self._refresh()
