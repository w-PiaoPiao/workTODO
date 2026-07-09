"""
进度条目展示组件

始终只显示最新一条进度，点击展开显示全部，点击其他地方收起。
展开模式下每条进度支持双击编辑（弹出输入框）和删除操作。
"""

from __future__ import annotations

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton, QHBoxLayout, QInputDialog, QLineEdit,
)
from app.views.theme import AppTheme
from app.views.elided_label import ElidedLabel
from app.models.todo_item import ProgressEntry


class ClickableElidedLabel(ElidedLabel):
    """可双击编辑的 ElidedLabel

    ElidedLabel 默认开启 WA_TransparentForMouseEvents 以便 TodoCard 标题拖拽透传。
    本类关闭该属性，并主动接受鼠标事件，防止事件冒泡到 MainWindow 触发窗口拖拽。
    双击时调用传入的 on_double_click 回调。
    """

    def __init__(self, text: str = "", parent=None, on_double_click=None):
        super().__init__(text, parent)
        self._on_double_click = on_double_click
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.setCursor(Qt.IBeamCursor)

    def mousePressEvent(self, event) -> None:
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        event.accept()

    def mouseDoubleClickEvent(self, event) -> None:
        if self._on_double_click:
            self._on_double_click(event)
        else:
            event.accept()


class ProgressWidget(QWidget):
    """进度条目列表 — 点击展开/收起，展开模式支持编辑和删除"""

    signal_show_all_changed = Signal(bool)
    signal_progress_edited = Signal(str, str)  # entry_id, new_text
    signal_progress_deleted = Signal(str)  # entry_id

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
        """追加一条新进度"""
        self._entries.append(entry)
        if self._show_all:
            self._layout.insertWidget(
                self._layout.count() - 1,
                self._make_expanded_row(entry),
            )
        else:
            self._refresh()

    def reapply_theme(self) -> None:
        """重新应用主题样式"""
        self._refresh()

    # ── UI 构建 ──────────────────────────────────────────

    def _build_ui(self) -> None:
        self._layout = QVBoxLayout()
        self._layout.setContentsMargins(0, 2, 0, 2)
        self._layout.setSpacing(2)
        self.setLayout(self._layout)

    def _clear_rows(self) -> None:
        """清空布局中所有行"""
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
            for entry in self._entries:
                self._layout.addWidget(self._make_expanded_row(entry))
            self._layout.addWidget(self._make_toggle_btn("收起 ▲"))
        else:
            self._build_collapsed_row()

    def _build_collapsed_row(self) -> None:
        """构建折叠模式行"""
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

    # ── 展开模式行 ────────────────────────────────────────

    def _make_expanded_row(self, entry: ProgressEntry) -> QWidget:
        """创建展开模式下的一条进度行"""
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

        text_label = ClickableElidedLabel(entry.text)
        text_label._on_double_click = lambda e: self._on_edit_entry(text_label, e)
        text_label.setProperty("entry_id", entry.id)
        text_label.setStyleSheet(f"""
            ClickableElidedLabel {{
                font: {AppTheme.FONT["small"]};
                color: {AppTheme.C["text_secondary"]};
                background: transparent;
                padding: 1px 2px;
                border: 1px solid transparent;
                border-radius: 2px;
            }}
            ClickableElidedLabel:hover {{
                border: 1px solid {AppTheme.C["accent"]};
            }}
        """)

        delete_btn = QPushButton("✕")
        delete_btn.setFixedSize(18, 18)
        delete_btn.setToolTip("删除此进度")
        delete_btn.setProperty("entry_id", entry.id)
        delete_btn.setStyleSheet(f"""
            QPushButton {{
                font-size: 10px;
                color: {AppTheme.C["text_disabled"]};
                border: none;
                padding: 0;
                background: transparent;
            }}
            QPushButton:hover {{
                color: {AppTheme.C["danger"]};
            }}
        """)
        delete_btn.clicked.connect(self._on_delete_entry)

        layout.addWidget(time_label)
        layout.addWidget(text_label, stretch=1)
        layout.addWidget(delete_btn)
        row.setLayout(layout)
        return row

    # ── 编辑交互 ──────────────────────────────────────────

    def _on_edit_entry(self, text_label: ClickableElidedLabel, event) -> None:
        """双击进度文本 → 弹出输入框编辑"""
        entry_id = text_label.property("entry_id")
        if not entry_id:
            event.accept()
            return

        # 找到对应的 ProgressEntry
        entry = next((p for p in self._entries if p.id == entry_id), None)
        if not entry:
            event.accept()
            return

        # 弹出编辑对话框（QInputDialog 进入嵌套事件循环，此时搜索防抖定时器等可能触发并销毁卡片）
        new_text, ok = QInputDialog.getText(
            self.window() or self,
            "编辑进度",
            "进度内容：",
            QLineEdit.Normal,
            entry.text,
        )
        if ok and new_text.strip() and new_text.strip() != entry.text:
            try:
                # 防御：嵌套事件循环期间 text_label 可能已被 deleteLater 销毁
                text_label.setFullText(new_text.strip())
                self.signal_progress_edited.emit(entry_id, new_text.strip())
            except RuntimeError:
                # widget 已被销毁，由控制器后续的 _refresh_views 刷新
                pass

        event.accept()

    # ── 删除交互 ──────────────────────────────────────────

    def _on_delete_entry(self) -> None:
        """处理删除按钮点击"""
        btn = self.sender()
        if not btn:
            return
        entry_id = btn.property("entry_id")
        if entry_id:
            self.signal_progress_deleted.emit(entry_id)

    # ── 通用 ──────────────────────────────────────────────

    def _make_toggle_btn(self, text: str) -> QPushButton:
        """创建可点击的展开/收起按钮"""
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
