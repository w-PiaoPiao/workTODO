"""
进度条目展示组件

始终只显示最新一条进度，点击展开显示全部，点击其他地方收起。
"""

from __future__ import annotations

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton, QHBoxLayout,
)
from app.views.theme import AppTheme
from app.views.elided_label import ElidedLabel
from app.models.todo_item import ProgressEntry


class ProgressWidget(QWidget):
    """进度条目列表 — 点击展开/收起"""

    signal_show_all_changed = Signal(bool)  # True=显示全部, False=只显示最新

    def __init__(self, parent=None):
        super().__init__(parent)
        self._entries: list[ProgressEntry] = []
        self._show_all = False

        self._build_ui()

    # ── 公开接口 ──────────────────────────────────────────

    def collapse(self) -> None:
        """收起，只显示最新一条"""
        if self._show_all:
            self._show_all = False
            self._refresh()
            self.signal_show_all_changed.emit(False)

    def expand(self) -> None:
        """展开，显示全部"""
        if not self._show_all:
            self._show_all = True
            self._refresh()
            self.signal_show_all_changed.emit(True)

    def set_entries(self, entries: list[ProgressEntry]) -> None:
        """设置进度条目（重置为收起状态）"""
        self._entries = list(entries)
        self._show_all = False
        self._refresh()

    def add_entry(self, entry: ProgressEntry) -> None:
        """追加一条新进度（保留当前展开/收起状态，避免 O(N²) 重建）"""
        self._entries.append(entry)
        if self._show_all:
            # 展开模式：只需追加一行，不用全量重建
            self._layout.insertWidget(
                self._layout.count() - 1,  # 插入到「收起 ▲」按钮之前
                self._make_entry_row(entry),
            )
        else:
            self._refresh()

    def reapply_theme(self) -> None:
        """重新应用主题样式（主题切换时调用，轻量重建）"""
        self._refresh()

    # ── UI 构建 ──────────────────────────────────────────

    def _build_ui(self) -> None:
        self._layout = QVBoxLayout()
        self._layout.setContentsMargins(0, 2, 0, 2)
        self._layout.setSpacing(2)
        self.setLayout(self._layout)

    def _clear_rows(self) -> None:
        """清空布局中所有行（供 _refresh 使用）"""
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def _refresh(self) -> None:
        """刷新显示"""
        self._clear_rows()

        if not self._entries:
            self._show_empty()
            return

        if self._show_all:
            # ── 展开模式：显示全部 ──────────────────────
            for entry in self._entries:
                self._layout.addWidget(self._make_entry_row(entry))
            self._layout.addWidget(self._make_toggle_btn("收起 ▲"))
        else:
            # ── 折叠模式：只显示最新一条，切换按钮放在时间前 ──
            row = QWidget()
            row.setStyleSheet("background: transparent;")
            layout = QHBoxLayout()
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(6)

            if len(self._entries) > 1:
                toggle = self._make_toggle_btn("▼")
                toggle.setToolTip(f"查看全部 {len(self._entries)} 条进度")
                layout.addWidget(toggle)

            entry = self._entries[-1]
            time_label = QLabel(entry.time_display)
            time_label.setStyleSheet(f"""
                font: {AppTheme.FONT["small"]};
                color: {AppTheme.C["text_disabled"]};
                background: transparent;
            """)
            time_label.setFixedWidth(50)

            text_label = ElidedLabel(entry.text)
            text_label.setStyleSheet(f"""
                font: {AppTheme.FONT["small"]};
                color: {AppTheme.C["text_secondary"]};
                background: transparent;
            """)

            layout.addWidget(time_label)
            layout.addWidget(text_label, stretch=1)
            row.setLayout(layout)
            self._layout.addWidget(row)

    def _show_empty(self) -> None:
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

    def _make_toggle_btn(self, text: str) -> QPushButton:
        """创建可点击的展开/收起按钮（QPushButton，支持键盘可访问）"""
        btn = QPushButton(text)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(f"""
            QPushButton {{
                font: {AppTheme.FONT["small"]};
                color: {AppTheme.C["accent"]};
                padding: 2px 0;
                border: none;
                background: transparent;
                text-align: left;
            }}
            QPushButton:hover {{
                color: {AppTheme.C["accent_hover"]};
            }}
        """)
        btn.clicked.connect(self._on_toggle)
        return btn

    def _on_toggle(self) -> None:
        """切换展开/收起状态"""
        self._show_all = not self._show_all
        self._refresh()
        self.signal_show_all_changed.emit(self._show_all)
