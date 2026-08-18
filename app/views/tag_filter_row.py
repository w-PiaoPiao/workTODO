"""
标签筛选行

独立组件：横向可滚动的标签 chips（全部 / #标签）。
- signal_tag_clicked(tag)：tag 为空表示「全部」
- 无标签时自动隐藏
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QPushButton,
    QScrollArea,
    QWidget,
)

from app.views.theme import AppTheme


class TagFilterRow(QWidget):
    """标签筛选行"""

    signal_tag_clicked = Signal(str)  # tag（空=全部）

    def __init__(self, parent=None):
        super().__init__(parent)

        self._all_tags: list[str] = []
        self._active_tag = ""

        self.setFixedHeight(32)
        self._build_ui()
        self.hide()

    # ── UI 构建 ──────────────────────────────────────────

    def _build_ui(self) -> None:
        """创建标签筛选行（横向可滚动，无标签时隐藏）"""
        self.setStyleSheet(f"""
            background: {AppTheme.C["bg_primary"]};
            border-bottom: 1px solid {AppTheme.C["border"]};
        """)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._tag_scroll = QScrollArea()
        self._tag_scroll.setWidgetResizable(True)
        self._tag_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._tag_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._tag_scroll.setFixedHeight(32)
        self._tag_scroll.setStyleSheet(
            "QScrollArea { border: none; background: transparent; }")

        self._tag_container = QWidget()
        self._tag_container.setStyleSheet("background: transparent;")
        self._tag_layout = QHBoxLayout()
        self._tag_layout.setContentsMargins(12, 2, 12, 2)
        self._tag_layout.setSpacing(6)
        self._tag_container.setLayout(self._tag_layout)
        self._tag_scroll.setWidget(self._tag_container)

        outer.addWidget(self._tag_scroll)

    # ── 公开接口 ──────────────────────────────────────────

    def update_tags(self, tags: list[str], active_tag: str) -> None:
        """更新标签筛选 chips（由 ExpandedView 转调）"""
        self._all_tags = list(tags)
        self._active_tag = active_tag

        # 清空旧 chips
        while self._tag_layout.count():
            item = self._tag_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        if not tags:
            self.hide()
            return

        def _make_btn(text: str, tag: str):
            btn = QPushButton(text)
            btn.setStyleSheet(AppTheme.tag_filter_btn(tag == active_tag))
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(
                lambda checked, t=tag: self.signal_tag_clicked.emit(t))
            return btn

        self._tag_layout.addWidget(_make_btn("全部", ""))
        for tag in tags:
            self._tag_layout.addWidget(_make_btn(f"#{tag}", tag))
        self.show()

    def reapply_theme(self) -> None:
        """重新应用当前主题样式（主题切换时调用）"""
        self.setStyleSheet(f"""
            background: {AppTheme.C["bg_primary"]};
            border-bottom: 1px solid {AppTheme.C["border"]};
        """)
        for i in range(self._tag_layout.count()):
            w = self._tag_layout.itemAt(i).widget()
            if isinstance(w, QPushButton):
                w.setStyleSheet(AppTheme.tag_filter_btn(
                    w.text() == ("全部" if not self._active_tag
                                 else f"#{self._active_tag}")))
