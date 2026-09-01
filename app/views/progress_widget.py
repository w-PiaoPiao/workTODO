"""
进度条目展示组件

始终只显示最新一条进度，点击展开显示全部，点击其他地方收起。
展开模式下每条进度支持双击编辑（弹出输入框）和删除操作。

添加进度采用行内就地编辑：点击最新进度行右侧悬浮的"＋"或
空进度提示行"＋ 添加进度..."，原行原地变为同高度输入框，
Enter / 失焦提交，Esc 取消——不占用常驻竖向空间。
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.models.todo_item import ProgressEntry
from app.views.elided_label import ElidedLabel
from app.views.theme import AppTheme


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
        if event.button() == Qt.LeftButton:
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() == Qt.LeftButton:
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self._on_double_click:
            self._on_double_click(event)
        else:
            super().mouseDoubleClickEvent(event)


class _ClickLabel(QLabel):
    """可点击的提示标签（左键按下即触发）"""

    clicked = Signal()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            event.accept()
            self.clicked.emit()
        else:
            super().mousePressEvent(event)


class _AddInput(QLineEdit):
    """添加进度输入框：Esc 触发取消（editingFinished 不覆盖 Esc）"""

    esc_pressed = Signal()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self.esc_pressed.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class _HoverRow(QWidget):
    """进度行容器：鼠标进入时按条件揭示控件（如"＋"按钮），离开时隐藏

    can_reveal 为条件回调，用于添加模式激活期间禁止重新揭示。
    """

    def __init__(self, reveal: QWidget | None = None,
                 can_reveal: Callable[[], bool] | None = None, parent=None):
        super().__init__(parent)
        self._reveal = reveal
        self._can_reveal = can_reveal or (lambda: True)

    def enterEvent(self, event) -> None:
        if self._reveal is not None and self._can_reveal():
            self._reveal.setVisible(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        if self._reveal is not None:
            self._reveal.setVisible(False)
        super().leaveEvent(event)


class ProgressWidget(QWidget):
    """进度条目列表 — 点击展开/收起，展开模式支持编辑和删除，行内就地添加"""

    signal_show_all_changed = Signal(bool)
    signal_progress_added = Signal(str)  # 新进度文本（item_id 由 TodoCard 包装）
    signal_progress_edited = Signal(str, str)  # entry_id, new_text
    signal_progress_deleted = Signal(str)  # entry_id

    def __init__(self, parent=None):
        super().__init__(parent)
        self._entries: list[ProgressEntry] = []
        self._show_all = False
        self._add_enabled = True
        self._add_input: _AddInput | None = None  # 当前添加模式的输入框
        self._generation = 0  # 行重建代数：提交后判断是否已被外部刷新重建
        self._build_ui()
        self._refresh()  # 默认渲染空状态（有 entries 时由 set_entries 覆盖）

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

    def set_add_enabled(self, enabled: bool) -> None:
        """启用/禁用添加进度入口（已完成卡片禁用；不变时无副作用）"""
        if self._add_enabled == enabled:
            return
        self._add_enabled = enabled
        if not enabled and self._add_input is not None:
            self._add_input = None  # 禁用时静默丢弃进行中的输入
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
        self._generation += 1
        self._add_input = None  # 行被重建时添加模式随之失效
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
            if self._add_enabled:
                self._layout.addWidget(self._make_add_hint_row())
            self._layout.addWidget(self._make_toggle_btn("收起 ▲"))
        else:
            self._build_collapsed_row()

    def _build_collapsed_row(self) -> None:
        """构建折叠模式行：时间 + 最新一条文本 + hover 揭示的添加按钮"""
        add_btn: QPushButton | None = None
        if self._add_enabled:
            add_btn = QPushButton("＋")
            add_btn.setFixedSize(18, 18)
            add_btn.setToolTip("添加进度")
            add_btn.setCursor(Qt.PointingHandCursor)
            add_btn.setStyleSheet(AppTheme.icon_btn("12px"))
            add_btn.clicked.connect(self._on_add_button_clicked)
            add_btn.hide()  # hover 揭示

        row = _HoverRow(
            add_btn,
            lambda: self._add_enabled and self._add_input is None,
        )
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
        time_label.setMinimumWidth(50)

        text_label = ElidedLabel(entry.text)
        text_label.setStyleSheet(f"""
            font: {AppTheme.FONT["small"]};
            color: {AppTheme.C["text_secondary"]};
            background: transparent;
        """)

        layout.addWidget(time_label)
        layout.addWidget(text_label, stretch=1)
        if add_btn is not None:
            layout.addWidget(add_btn)
        row.setLayout(layout)
        self._layout.addWidget(row)

    def _show_empty(self) -> None:
        if self._add_enabled:
            # 可点击提示行：点击后就地进入添加模式
            self._layout.addWidget(self._make_add_hint_row())
            return
        label = QLabel("暂无进度")
        label.setStyleSheet(f"""
            font: {AppTheme.FONT["small"]};
            color: {AppTheme.C["text_disabled"]};
            padding: 2px 0;
            background: transparent;
        """)
        self._layout.addWidget(label)

    def _make_add_hint_row(self) -> QWidget:
        """创建"＋ 添加进度..."提示行（空状态与展开模式共用）"""
        hint = _ClickLabel("＋ 添加进度...")
        hint.setCursor(Qt.PointingHandCursor)
        hint.setStyleSheet(AppTheme.progress_add_hint_style())

        row = _HoverRow()
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(hint)
        row.setLayout(layout)
        hint.clicked.connect(lambda: self._enter_add_mode_in_row(row))
        return row

    # ── 行内添加模式 ──────────────────────────────────────

    def _on_add_button_clicked(self) -> None:
        """点击折叠行的"＋"：最新进度行就地进入添加模式"""
        if not self._add_enabled or self._add_input is not None:
            return
        row_item = self._layout.itemAt(0)
        if row_item is None:
            return
        self._enter_add_mode_in_row(row_item.widget())

    def _enter_add_mode_in_row(self, row: QWidget | None) -> None:
        """将指定行就地变为添加模式：隐藏展示控件，原位插入同高度输入框"""
        if (not self._add_enabled or self._add_input is not None
                or row is None or row.layout() is None):
            return

        inp = self._make_add_input()
        self._add_input = inp

        layout = row.layout()
        for i in range(layout.count()):
            w = layout.itemAt(i).widget()
            if w is not None:
                w.setVisible(False)
        layout.insertWidget(0, inp, stretch=1)
        inp.setFocus()

    def _make_add_input(self) -> _AddInput:
        """创建添加进度输入框（Enter/失焦提交，Esc 取消）"""
        inp = _AddInput()
        inp.setPlaceholderText("添加进度...")
        inp.setStyleSheet(AppTheme.progress_input_style())
        inp.setToolTip("Enter 提交，Esc 取消")
        inp.editingFinished.connect(self._commit_add)
        inp.esc_pressed.connect(self._cancel_add)
        return inp

    def _commit_add(self) -> None:
        """提交新进度（Enter / 失焦触发）；空文本静默退出"""
        inp = self._add_input
        if inp is None:
            return
        text = inp.text().strip()
        self._add_input = None

        if not text:
            self._refresh()
            return

        gen = self._generation
        self.signal_progress_added.emit(text)
        # emit 链路中的数据刷新可能已重建行（generation 变化），避免二次重建
        if self._generation == gen:
            self._refresh()

    def _cancel_add(self) -> None:
        """取消添加模式（Esc / 程序化重建），恢复显示"""
        if self._add_input is None:
            return
        self._add_input = None
        self._refresh()

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
        time_label.setMinimumWidth(50)

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
        delete_btn.setStyleSheet(AppTheme.danger_btn("10px"))
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
