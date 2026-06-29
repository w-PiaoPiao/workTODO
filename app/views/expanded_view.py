"""
展开模式视图

完整待办列表，包含：
- 标题栏（标签 + 折叠按钮）
- 快速添加输入行
- 可滚动待办卡片列表
- 空状态 / 错误状态显示
- 底部归档入口
"""

from __future__ import annotations

from PySide6.QtCore import Signal, Qt, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QScrollArea, QFrame, QSizePolicy,
)
from app.config import AppConfig
from app.views.theme import AppTheme
from app.models.todo_item import TodoItem


class ExpandedView(QFrame):
    """展开模式视图"""

    signal_collapse_clicked = Signal()
    signal_item_added = Signal(str)  # title
    signal_item_completed = Signal(str)  # item_id
    signal_item_deleted = Signal(str)  # item_id
    signal_progress_added = Signal(str, str)  # item_id, text
    signal_search_changed = Signal(str)  # query
    signal_archive_view_requested = Signal()
    signal_quit_requested = Signal()  # 退出应用
    signal_toggle_pin = Signal(bool)  # 置顶切换

    def __init__(self, parent=None):
        super().__init__(parent)

        self._items: list[TodoItem] = []
        self._search_active = False
        self._search_query = ""

        self._build_ui()

    def _build_ui(self) -> None:
        # ── 自身样式 ──────────────────────────────────────
        self.setStyleSheet(f"""
            ExpandedView {{
                background: {AppTheme.C["bg_primary"]};
                border: 1px solid {AppTheme.C["border"]};
                border-radius: 8px;
            }}
        """)

        # ── 主布局 ────────────────────────────────────────
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ── 标题栏 ────────────────────────────────────────
        title_bar = self._make_title_bar()
        main_layout.addWidget(title_bar)

        # ── 快速添加栏 ────────────────────────────────────
        self._add_bar = self._make_add_bar()
        main_layout.addWidget(self._add_bar)

        # ── 待办列表区域 ──────────────────────────────────
        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self._list_container = QWidget()
        self._list_layout = QVBoxLayout()
        self._list_layout.setContentsMargins(12, 8, 12, 8)
        self._list_layout.setSpacing(6)
        self._list_layout.addStretch()
        self._list_container.setLayout(self._list_layout)
        self._scroll_area.setWidget(self._list_container)

        main_layout.addWidget(self._scroll_area, stretch=1)

        # ── 页脚 ──────────────────────────────────────────
        footer = self._make_footer()
        main_layout.addWidget(footer)

        self.setLayout(main_layout)

        # ── 初始显示空状态 ────────────────────────────────
        self._show_empty_state()

    # ── 标题栏 ────────────────────────────────────────────

    def _make_title_bar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(40)
        bar.setStyleSheet(f"""
            background: {AppTheme.C["bg_primary"]};
            border-bottom: 1px solid {AppTheme.C["border"]};
            border-top-left-radius: 8px;
            border-top-right-radius: 8px;
        """)

        layout = QHBoxLayout()
        layout.setContentsMargins(12, 0, 8, 0)

        title = QLabel("待办事项")
        title.setStyleSheet(f"""
            font: {AppTheme.FONT["title"]};
            background: transparent;
        """)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        spacer.setStyleSheet("background: transparent;")

        # 搜索按钮
        self._search_btn = QPushButton("🔍")
        self._search_btn.setFixedSize(28, 28)
        self._search_btn.setToolTip("搜索")
        self._search_btn.setStyleSheet(self._icon_btn_style())
        self._search_btn.clicked.connect(self._toggle_search)

        # 置顶切换按钮
        self._pin_btn = QPushButton("📌")
        self._pin_btn.setFixedSize(28, 28)
        self._pin_btn.setToolTip("窗口置顶（点击切换）")
        self._pin_btn.setCheckable(True)
        self._pin_btn.setChecked(True)
        self._pin_btn.setStyleSheet(self._pin_btn_style())
        self._pin_btn.toggled.connect(self.signal_toggle_pin.emit)

        # 折叠按钮
        collapse_btn = QPushButton("━")
        collapse_btn.setFixedSize(28, 28)
        collapse_btn.setToolTip("折叠")
        collapse_btn.setStyleSheet(self._icon_btn_style())
        collapse_btn.clicked.connect(self.signal_collapse_clicked.emit)

        # 退出按钮
        quit_btn = QPushButton("✕")
        quit_btn.setFixedSize(28, 28)
        quit_btn.setToolTip("退出")
        quit_btn.setStyleSheet(f"""
            QPushButton {{
                font-size: 14px;
                color: {AppTheme.C["text_disabled"]};
                border-radius: 4px;
                padding: 2px;
                background: transparent;
            }}
            QPushButton:hover {{
                background: {AppTheme.C["danger"]}; color: white;
            }}
        """)
        quit_btn.clicked.connect(self.signal_quit_requested.emit)

        layout.addWidget(title)
        layout.addWidget(spacer)
        layout.addWidget(self._search_btn)
        layout.addWidget(self._pin_btn)
        layout.addWidget(collapse_btn)
        layout.addWidget(quit_btn)
        bar.setLayout(layout)
        return bar

    # ── 搜索栏 ──────────────────────────────────────────────

    def _toggle_search(self) -> None:
        """切换搜索栏显示"""
        self._search_active = not self._search_active
        self._search_bar.setVisible(self._search_active)
        if self._search_active:
            self._search_bar.setFocus()
            self._search_bar.setText(self._search_query)
        else:
            self._search_bar.clear()
            self._search_query = ""
            self.signal_search_changed.emit("")

    # ── 快速添加栏 ────────────────────────────────────────

    def _make_add_bar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(42)
        bar.setStyleSheet(f"""
            background: {AppTheme.C["bg_card"]};
            border-bottom: 1px solid {AppTheme.C["border"]};
        """)

        layout = QHBoxLayout()
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(8)

        self._add_input = QLineEdit()
        self._add_input.setPlaceholderText("快速添加新待办...")
        self._add_input.returnPressed.connect(self._on_add_submit)

        self._add_btn = QPushButton("＋")
        self._add_btn.setFixedSize(30, 30)
        self._add_btn.setToolTip("添加")
        self._add_btn.setStyleSheet(f"""
            QPushButton {{
                font-size: 18px;
                color: {AppTheme.C["accent"]};
                border-radius: 4px;
                padding: 2px;
                background: {AppTheme.C["bg_hover"]};
            }}
            QPushButton:hover {{
                background: {AppTheme.C["accent"]};
                color: white;
            }}
        """)
        self._add_btn.clicked.connect(self._on_add_submit)

        layout.addWidget(self._add_input)
        layout.addWidget(self._add_btn)
        bar.setLayout(layout)

        # 搜索栏（默认隐藏）
        self._search_bar = QLineEdit()
        self._search_bar.setPlaceholderText("搜索待办事项...")
        self._search_bar.setVisible(False)
        self._search_bar.setStyleSheet(f"""
            QLineEdit {{
                border: 1px solid {AppTheme.C["accent"]};
                border-radius: 4px;
                padding: 6px 10px;
                background: {AppTheme.C["bg_card"]};
            }}
        """)
        self._search_bar.textChanged.connect(self._on_search_debounced)

        layout.addWidget(self._search_bar)
        bar.setLayout(layout)
        return bar

    def _on_add_submit(self) -> None:
        title = self._add_input.text().strip()
        if title:
            self.signal_item_added.emit(title)
            self._add_input.clear()
        else:
            # 空输入提示（输入框闪红）
            self._add_input.setStyleSheet(
                f"border: 1px solid {AppTheme.C['danger']};"
            )
            QTimer.singleShot(300, self._reset_add_input_style)

    def _reset_add_input_style(self) -> None:
        self._add_input.setStyleSheet("")

    # ── 搜索防抖 ──────────────────────────────────────────

    def _on_search_debounced(self, text: str) -> None:
        self._search_query = text
        try:
            self._search_timer.timeout.disconnect()
        except (AttributeError, RuntimeError):
            pass
        self._search_timer = QTimer()
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(
            lambda: self.signal_search_changed.emit(self._search_query)
        )
        self._search_timer.start(AppConfig.SEARCH_DEBOUNCE_MS)

    # ── 待办列表 ──────────────────────────────────────────

    def refresh(self, items: list[TodoItem]) -> None:
        """刷新整个待办列表"""
        self._items = items

        # 清空现有卡片
        self._clear_list()

        # 过滤活跃项
        active = [i for i in items if i.is_active]

        if not active:
            self._show_empty_state()
            return

        # 如果搜索激活，进一步过滤
        if self._search_query:
            q = self._search_query.lower()
            active = [
                i for i in active
                if q in i.title.lower()
                or any(q in p.text.lower() for p in i.progress)
            ]

        if not active:
            self._show_no_results()
            return

        # 动态创建卡片
        from app.views.todo_card import TodoCard
        for item in active:
            card = TodoCard(item, self)
            card.signal_completed.connect(self.signal_item_completed.emit)
            card.signal_deleted.connect(self.signal_item_deleted.emit)
            card.signal_progress_added.connect(self.signal_progress_added.emit)
            self._list_layout.insertWidget(self._list_layout.count() - 1, card)

    def _clear_list(self) -> None:
        """移除列表中所有卡片和状态提示"""
        while self._list_layout.count() > 1:  # 保留最后的 stretch
            item = self._list_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    # ── 状态显示 ──────────────────────────────────────────

    def _show_empty_state(self) -> None:
        """显示空状态"""
        label = QLabel("还没有待办事项\n点击上方 [＋] 快速添加第一条待办")
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet(f"""
            font: {AppTheme.FONT["body"]};
            color: {AppTheme.C["text_disabled"]};
            padding: 40px 20px;
            background: transparent;
        """)
        self._list_layout.insertWidget(0, label)

    def _show_no_results(self) -> None:
        """搜索无结果"""
        label = QLabel(f"没有找到包含「{self._search_query}」的待办事项")
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet(f"""
            font: {AppTheme.FONT["body"]};
            color: {AppTheme.C["text_disabled"]};
            padding: 40px 20px;
            background: transparent;
        """)
        self._list_layout.insertWidget(0, label)

    # ── 页脚 ──────────────────────────────────────────────

    def _make_footer(self) -> QWidget:
        footer = QWidget()
        footer.setFixedHeight(36)
        footer.setStyleSheet(f"""
            background: {AppTheme.C["bg_primary"]};
            border-top: 1px solid {AppTheme.C["border"]};
            border-bottom-left-radius: 8px;
            border-bottom-right-radius: 8px;
        """)

        layout = QHBoxLayout()
        layout.setContentsMargins(12, 0, 12, 0)

        self._archive_btn = QPushButton("📦 查看归档")
        self._archive_btn.setStyleSheet(self._footer_btn_style())
        self._archive_btn.clicked.connect(self.signal_archive_view_requested.emit)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        spacer.setStyleSheet("background: transparent;")

        self._stats_label = QLabel("共 0 项")
        self._stats_label.setStyleSheet(f"""
            font: {AppTheme.FONT["small"]};
            color: {AppTheme.C["text_secondary"]};
            background: transparent;
        """)

        layout.addWidget(self._archive_btn)
        layout.addWidget(spacer)
        layout.addWidget(self._stats_label)
        footer.setLayout(layout)
        return footer

    def update_stats(self, active_count: int, archived_count: int) -> None:
        """更新底部统计"""
        self._stats_label.setText(f"共 {active_count} 项")
        self._archive_btn.setText(f"📦 查看归档 ({archived_count})")

    def set_pinned(self, pinned: bool) -> None:
        """同步置顶按钮状态（由控制器调用）"""
        self._pin_btn.setChecked(pinned)

    # ── 样式辅助 ──────────────────────────────────────────

    @staticmethod
    def _icon_btn_style() -> str:
        C = AppTheme.C
        return f"""
            QPushButton {{
                font-size: 14px;
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

    @staticmethod
    def _pin_btn_style() -> str:
        C = AppTheme.C
        return f"""
            QPushButton {{
                font-size: 13px;
                color: {C["text_disabled"]};
                border-radius: 4px;
                padding: 2px;
                background: transparent;
            }}
            QPushButton:hover {{
                background: {C["bg_hover"]};
            }}
            QPushButton:checked {{
                color: {C["danger"]};
            }}
        """

    @staticmethod
    def _footer_btn_style() -> str:
        C = AppTheme.C
        return f"""
            QPushButton {{
                font: {AppTheme.FONT["small"]};
                color: {C["accent"]};
                padding: 4px 8px;
                border-radius: 4px;
                background: transparent;
            }}
            QPushButton:hover {{
                background: {C["bg_hover"]};
            }}
        """
