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

from PySide6.QtCore import Signal, Qt, QTimer, QEvent, QRect, QPropertyAnimation, QEasingCurve
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QScrollArea, QFrame, QSizePolicy, QSizeGrip, QApplication,
)
from app.config import AppConfig
from app.views.theme import AppTheme
from app.models.todo_item import TodoItem
from app.views.todo_card import TodoCard


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
    signal_toggle_pin = Signal()  # 置顶切换（无参数，控制器管理状态）
    signal_sticky_toggled = Signal(str)  # 待办置顶切换（item_id）
    signal_reorder_items = Signal(list)  # 卡片拖动排序 [item_id, ...]
    signal_title_changed = Signal(str, str)  # item_id, new_title
    signal_progress_edited = Signal(str, str, str)  # item_id, entry_id, new_text
    signal_progress_deleted = Signal(str, str)  # item_id, entry_id
    signal_theme_toggled = Signal(bool)  # dark=True
    signal_autostart_toggled = Signal(bool)  # enabled=True

    def __init__(self, parent=None):
        super().__init__(parent)

        self._items: list[TodoItem] = []
        self._search_active = False
        self._search_query = ""
        self._pinned = True  # 默认置顶
        self._progress_expanded_card: QWidget | None = None  # 当前展开进度的卡片
        self._drop_indicator: QFrame | None = None  # 拖拽插入指示线
        self._drop_local_pos: QPoint | None = None  # 拖拽事件在容器坐标系下的位置（避免 monkey-patch event 对象）
        self._autostart = False  # 开机自启状态
        self._all_collapsed = False  # 全部卡片折叠状态

        # 搜索防抖 —— 复用单个 timer，避免每次按键创建新对象
        self._search_timer = QTimer()
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self._on_search_flush)

        self._built = False  # 标记是否已完成构造，防止 _build_ui 中事件过滤器访问未初始化的属性
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
        self._title_bar = self._make_title_bar()
        main_layout.addWidget(self._title_bar)

        # ── 快速添加栏 ────────────────────────────────────
        self._add_bar = self._make_add_bar()
        main_layout.addWidget(self._add_bar)

        # ── 待办列表区域 ──────────────────────────────────
        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self._list_container = QWidget()
        self._list_container.setAcceptDrops(True)  # 接受拖放排序
        self._list_layout = QVBoxLayout()
        self._list_layout.setContentsMargins(12, 8, 12, 8)
        self._list_layout.setSpacing(6)
        self._list_layout.addStretch()
        self._list_container.setLayout(self._list_layout)
        self._list_container.installEventFilter(self)  # 监听外部点击收起进度
        # 滚动区域视口也要监听拖拽事件（scroll area 的视口会拦截事件）
        self._scroll_area.viewport().installEventFilter(self)
        self._scroll_area.setWidget(self._list_container)

        main_layout.addWidget(self._scroll_area, stretch=1)

        # ── 页脚 ──────────────────────────────────────────
        self._footer = self._make_footer()
        main_layout.addWidget(self._footer)

        self.setLayout(main_layout)

        # ── 应用主题样式 ──────────────────────────────────
        self.reapply_theme()

        self._built = True

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
        # 先在实例变量中保存引用，再安装事件过滤器（防止 setLayout 触发布局事件时 eventFilter 访问未初始化的 self._title_bar）
        self._title_bar = bar
        bar.installEventFilter(self)

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

        # 开机自启按钮（在主题切换按钮左边）
        self._autostart_btn = QPushButton("⚡")
        self._autostart_btn.setFixedSize(28, 28)
        self._autostart_btn.setToolTip("点击开启开机自启")
        self._autostart_btn.setStyleSheet(self._autostart_btn_style(False))
        self._autostart_btn.clicked.connect(self._on_autostart_clicked)

        # 主题切换按钮（在搜索按钮左边）
        self._theme_btn = QPushButton("🌙" if not AppTheme.is_dark() else "☀️")
        self._theme_btn.setFixedSize(28, 28)
        self._theme_btn.setToolTip("切换深色模式" if not AppTheme.is_dark() else "切换浅色模式")
        self._theme_btn.setStyleSheet(self._icon_btn_style())
        self._theme_btn.clicked.connect(self._on_theme_clicked)

        # 搜索按钮
        self._search_btn = QPushButton("🔍")
        self._search_btn.setFixedSize(28, 28)
        self._search_btn.setToolTip("搜索")
        self._search_btn.setStyleSheet(self._icon_btn_style())
        self._search_btn.clicked.connect(self._toggle_search)

        # 置顶切换按钮
        self._pin_btn = QPushButton("📌")
        self._pin_btn.setFixedSize(28, 28)
        self._pin_btn.setToolTip("点击切换置顶")
        self._pin_btn.setStyleSheet(AppTheme.pin_btn_style(True))
        self._pin_btn.clicked.connect(self.signal_toggle_pin.emit)

        # 收起全部卡片按钮
        self._collapse_cards_btn = QPushButton("⊟")
        self._collapse_cards_btn.setFixedSize(28, 28)
        self._collapse_cards_btn.setToolTip("收起全部卡片")
        self._collapse_cards_btn.setStyleSheet(self._icon_btn_style())
        self._collapse_cards_btn.clicked.connect(self._toggle_collapse_cards)

        # 折叠按钮
        self._collapse_btn = QPushButton("━")
        self._collapse_btn.setFixedSize(28, 28)
        self._collapse_btn.setToolTip("折叠")
        self._collapse_btn.setStyleSheet(self._icon_btn_style())
        self._collapse_btn.clicked.connect(self.signal_collapse_clicked.emit)

        layout.addWidget(title)
        layout.addWidget(spacer)
        layout.addWidget(self._autostart_btn)
        layout.addWidget(self._theme_btn)
        layout.addWidget(self._search_btn)
        layout.addWidget(self._pin_btn)
        layout.addWidget(self._collapse_cards_btn)
        layout.addWidget(self._collapse_btn)
        bar.setLayout(layout)
        return bar

    def _on_theme_clicked(self) -> None:
        """主题按钮点击处理"""
        self.signal_theme_toggled.emit(not AppTheme.is_dark())

    def _on_autostart_clicked(self) -> None:
        """开机自启按钮点击处理"""
        self.signal_autostart_toggled.emit(not self._autostart)

    def set_autostart(self, enabled: bool) -> None:
        """同步开机自启状态（由控制器调用）"""
        self._autostart = enabled
        self._autostart_btn.setText("⚡" if enabled else "🔌")
        self._autostart_btn.setStyleSheet(self._autostart_btn_style(enabled))
        self._autostart_btn.setToolTip("点击关闭开机自启" if enabled else "点击开启开机自启")

    def _toggle_collapse_cards(self) -> None:
        """切换全部卡片的折叠/展开"""
        self._all_collapsed = not self._all_collapsed
        btn = self._collapse_cards_btn
        if self._all_collapsed:
            btn.setText("⊞")
            btn.setToolTip("展开全部卡片")
        else:
            btn.setText("⊟")
            btn.setToolTip("收起全部卡片")
        for w in self._iter_cards():
            w.set_all_collapsed(self._all_collapsed)

    # ── 搜索栏 ──────────────────────────────────────────────

    def focus_add_input(self) -> None:
        """聚焦快速添加输入框"""
        self._add_input.setFocus()
        self._add_input.selectAll()

    def focus_search(self) -> None:
        """打开并聚焦搜索栏"""
        if not self._search_active:
            self._toggle_search()
        else:
            self._search_bar.setFocus()
            self._search_bar.selectAll()

    def _toggle_search(self) -> None:
        """切换搜索栏显示"""
        self._search_active = not self._search_active
        self._search_bar.setVisible(self._search_active)
        if self._search_active:
            self._search_bar.setFocus()
            self._search_bar.setText(self._search_query)
        else:
            # 先阻止防抖 timer 触发，再手动发射一次空查询
            self._search_timer.stop()
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
        """搜索防抖：记录查询，重启 timer"""
        self._search_query = text
        self._search_timer.start(AppConfig.SEARCH_DEBOUNCE_MS)

    def _on_search_flush(self) -> None:
        """防抖到期后刷新搜索结果"""
        self.signal_search_changed.emit(self._search_query)

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

        # 置顶项排前面，同优先级按 position 和创建时间
        active.sort(key=lambda i: (not i.sticky, i.position if i.position else 0, i.created_at))

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
        for item in active:
            card = TodoCard(item, self)
            card.setProperty("todo_item_id", item.id)  # 用于拖放识别
            card.signal_completed.connect(self.signal_item_completed.emit)
            card.signal_deleted.connect(self.signal_item_deleted.emit)
            card.signal_progress_added.connect(self.signal_progress_added.emit)
            card.signal_sticky_toggled.connect(self.signal_sticky_toggled.emit)
            card.signal_title_changed.connect(self.signal_title_changed.emit)
            card.signal_progress_edited.connect(self.signal_progress_edited.emit)
            card.signal_progress_deleted.connect(self.signal_progress_deleted.emit)
            # 进度展开/收起监听
            card.progress_toggled_signal.connect(
                lambda show_all, c=card: self._on_progress_toggle(c, show_all),
            )
            # 全部卡片折叠模式
            if self._all_collapsed:
                card.set_all_collapsed(True)
            self._list_layout.insertWidget(self._list_layout.count() - 1, card)

    def _clear_list(self) -> None:
        """移除列表中所有卡片和状态提示"""
        self._progress_expanded_card = None
        while self._list_layout.count() > 1:  # 保留最后的 stretch
            item = self._list_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def _iter_cards(self):
        """遍历列表中的所有 TodoCard（跳过 stretch 和状态标签）"""
        for i in range(self._list_layout.count()):
            w = self._list_layout.itemAt(i).widget()
            if isinstance(w, TodoCard):
                yield w

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

    # ── 进度展开/收起管理 ──────────────────────────────────

    def _on_progress_toggle(self, card: QWidget, show_all: bool) -> None:
        """卡片进度展开/收起回调"""
        if show_all:
            # 先收起其他卡片的进度
            if self._progress_expanded_card and self._progress_expanded_card is not card:
                try:
                    self._progress_expanded_card.collapse_progress()
                except RuntimeError:
                    pass
            self._progress_expanded_card = card
        else:
            if self._progress_expanded_card is card:
                self._progress_expanded_card = None

    def _collapse_expanded_progress(self) -> None:
        """收起当前展开的进度（点击外部时调用）"""
        if self._progress_expanded_card:
            try:
                self._progress_expanded_card.collapse_progress()
            except RuntimeError:
                pass
            self._progress_expanded_card = None

    # ── 事件过滤器：点击外部收起进度 + 拖放排序 ──────────

    def eventFilter(self, obj, event) -> bool:
        """合并事件路由：标题栏双击折叠 + 点击外部收起进度 + 拖放排序"""
        # 构造完成前所有事件直接透传（_build_ui 中事件可能先于属性初始化触发）
        if not self._built:
            return super().eventFilter(obj, event)

        # 标题栏双击 → 折叠
        if obj is self._title_bar and event.type() == QEvent.MouseButtonDblClick:
            self.signal_collapse_clicked.emit()
            return True

        is_container = obj is self._list_container
        is_viewport = obj is self._scroll_area.viewport()

        if is_container and event.type() == QEvent.MouseButtonPress:
            return self._handle_container_click(event)
        if not (is_container or is_viewport):
            return super().eventFilter(obj, event)
        if event.type() == QEvent.DragEnter:
            return self._handle_drag_enter(event)
        if event.type() == QEvent.DragMove:
            return self._handle_drag_move(event, is_viewport)
        if event.type() == QEvent.DragLeave:
            return self._handle_drag_leave()
        if event.type() == QEvent.Drop:
            return self._handle_drag_drop(event, is_viewport)
        return super().eventFilter(obj, event)

    def _handle_container_click(self, event) -> bool:
        """点击容器空白区域收起展开的进度"""
        if self._progress_expanded_card is not None:
            click_pos = event.position().toPoint()
            card_tl = self._progress_expanded_card.mapTo(
                self._list_container, QPoint(0, 0)
            )
            card_rect = QRect(card_tl, self._progress_expanded_card.size())
            if not card_rect.contains(click_pos):
                self._collapse_expanded_progress()
        return super().eventFilter(self._list_container, event)

    def _is_valid_drag(self, event) -> bool:
        """检查是否为有效的卡片拖放事件"""
        if self._search_query:
            return False
        mime = event.mimeData()
        return mime.hasText() and mime.text().startswith("todo-card:")

    def _drag_local_pos(self, event, is_viewport: bool) -> QPoint:
        """获取容器坐标系下的拖放位置"""
        if is_viewport:
            return self._list_container.mapFrom(
                self._scroll_area.viewport(), event.position().toPoint())
        return event.position().toPoint()

    def _handle_drag_enter(self, event) -> bool:
        if not self._is_valid_drag(event):
            return super().eventFilter(self._list_container, event)
        event.acceptProposedAction()
        self._show_drop_indicator(event)
        return True

    def _handle_drag_move(self, event, is_viewport: bool) -> bool:
        if not self._is_valid_drag(event):
            return super().eventFilter(self._list_container, event)
        self._drop_local_pos = self._drag_local_pos(event, is_viewport)
        event.acceptProposedAction()
        self._update_drop_indicator(event)
        self._scroll_during_drag(event)
        return True

    def _handle_drag_leave(self) -> bool:
        self._hide_drop_indicator()
        return True

    def _handle_drag_drop(self, event, is_viewport: bool) -> bool:
        if not self._is_valid_drag(event):
            return super().eventFilter(self._list_container, event)
        self._drop_local_pos = self._drag_local_pos(event, is_viewport)
        self._hide_drop_indicator()
        self._handle_drop(event)
        event.acceptProposedAction()
        return True

    # ── 拖放指示器 ──────────────────────────────────────

    def _show_drop_indicator(self, event) -> None:
        """创建插入指示线"""
        if self._drop_indicator is None:
            self._drop_indicator = QFrame(self._list_container)
            margin = self._list_layout.contentsMargins()
            w = self._list_container.width() - margin.left() - margin.right()
            if w < 10:
                w = 200  # fallback
            self._drop_indicator.setFixedSize(int(w), 3)
            self._drop_indicator.setStyleSheet(f"""
                background: {AppTheme.C["accent"]};
                border-radius: 1px;
            """)
            self._drop_indicator.hide()
        self._update_drop_indicator(event)
        self._drop_indicator.raise_()
        self._drop_indicator.show()

    def _update_drop_indicator(self, event) -> None:
        """更新指示线位置到最近的卡片间隙"""
        if self._drop_indicator is None:
            return
        y = self._drop_position_y(event)
        margin = self._list_layout.contentsMargins()
        self._drop_indicator.move(margin.left(), y)

    def _drop_pos(self, event) -> QPoint:
        """从事件中提取容器坐标系下的位置"""
        if self._drop_local_pos is not None:
            return self._drop_local_pos
        return event.position().toPoint()

    def _drop_position_y(self, event) -> int:
        """计算指示线应放置的 Y 坐标"""
        margin = self._list_layout.contentsMargins()
        mouse_y = self._drop_pos(event).y()
        y = margin.top()

        for w in self._iter_cards():
            if not w.isVisible():
                continue
            card_rect = w.geometry()
            mid = card_rect.top() + card_rect.height() // 2
            if mouse_y <= mid:
                return card_rect.top()
            y = card_rect.bottom() + 1

        return y

    def _hide_drop_indicator(self) -> None:
        """隐藏插入指示线"""
        if self._drop_indicator:
            self._drop_indicator.hide()

    # ── 拖拽自动滚动 ────────────────────────────────────

    def _scroll_during_drag(self, event) -> None:
        """拖拽时根据鼠标位置自动滚动"""
        viewport = self._scroll_area.viewport()
        pos = viewport.mapFrom(self._list_container, self._drop_pos(event))
        scrollbar = self._scroll_area.verticalScrollBar()
        scroll_step = 20
        margin = 30  # 距离边缘 px

        if pos.y() < margin:
            scrollbar.setValue(scrollbar.value() - scroll_step)
        elif pos.y() > viewport.height() - margin:
            scrollbar.setValue(scrollbar.value() + scroll_step)

    # ── 拖放完成 ────────────────────────────────────────

    def _handle_drop(self, event) -> None:
        """处理拖放完成——重新排序并发送信号"""
        text = event.mimeData().text()
        if not text.startswith("todo-card:"):
            return
        dragged_id = text.replace("todo-card:", "")

        mouse_pos = self._drop_pos(event)
        ordered: list[str] = []
        inserted = False

        for w in self._iter_cards():
            if not w.isVisible():
                continue
            card_id = w.property("todo_item_id")
            if card_id == dragged_id:
                continue
            card_rect = w.geometry()
            mid = card_rect.top() + card_rect.height() // 2
            if not inserted and mouse_pos.y() <= mid:
                ordered.append(dragged_id)
                inserted = True
            ordered.append(card_id)

        if not inserted:
            ordered.append(dragged_id)

        if ordered:
            self.signal_reorder_items.emit(ordered)

    # ── 卡片查找 ────────────────────────────────────────

    def _find_card(self, item_id: str):
        """按 item_id 查找卡片 widget"""
        for w in self._iter_cards():
            if w.property("todo_item_id") == item_id:
                return w
        return None

    # ── 置顶动画 ────────────────────────────────────────

    def animate_sticky(self, item_id: str, todos: list[TodoItem]) -> None:
        """置顶切换动画：卡片从当前位置飞入列表顶部"""
        # 清理前序动画（防止快速连续点击导致幽灵泄漏）
        if hasattr(self, '_sticky_anim') and self._sticky_anim:
            try:
                self._sticky_anim.stop()
            except RuntimeError:
                pass
            self._sticky_anim = None

        # 记录旧卡片位置（refresh 会销毁旧卡片）
        old_card = self._find_card(item_id)
        old_geo = QRect(old_card.geometry()) if old_card else None

        # 重建视图（卡片已在新位置）
        self._items = todos
        self.refresh(todos)

        # 找到新卡片
        new_card = self._find_card(item_id)
        if not new_card or not old_geo:
            return

        new_geo = new_card.geometry()
        vertical_dist = abs(new_geo.y() - old_geo.y())
        if vertical_dist < 5:
            return  # 无需动画

        # 创建幽灵覆盖层（抓取新卡片外观，从旧位置飞入）
        pixmap = new_card.grab()
        ghost = QLabel(self._list_container)
        ghost.setPixmap(pixmap)
        ghost.setFixedSize(new_card.size())
        ghost.setGeometry(old_geo)
        ghost.raise_()
        ghost.show()

        # 动画：从旧位置飞到新位置
        anim = QPropertyAnimation(ghost, b"geometry")
        anim.setDuration(int(300 * min(1.0, vertical_dist / 500 + 0.3)))
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.setStartValue(old_geo)
        anim.setEndValue(new_geo)
        anim.finished.connect(lambda: ghost.deleteLater())
        anim.start()
        self._sticky_anim = anim

    # ── 页脚 ──────────────────────────────────────────────

    def _make_footer(self) -> QWidget:
        footer = QWidget()
        footer.setFixedHeight(40)
        footer.setStyleSheet(f"""
            background: {AppTheme.C["bg_primary"]};
            border-top: 1px solid {AppTheme.C["border"]};
            border-bottom-left-radius: 8px;
            border-bottom-right-radius: 8px;
        """)

        layout = QHBoxLayout()
        layout.setContentsMargins(12, 0, 4, 0)
        layout.setSpacing(4)

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

        # 退出按钮
        self._quit_btn = QPushButton("✕  退出")
        self._quit_btn.setFixedHeight(26)
        self._quit_btn.clicked.connect(self.signal_quit_requested.emit)

        # 缩放手柄（右下角三角图案）
        grip = QSizeGrip(footer)
        grip.setFixedSize(20, 20)
        grip.setStyleSheet("""
            QSizeGrip {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0.65 transparent, stop:0.66 #999999,
                    stop:0.68 #999999, stop:0.69 transparent,
                    stop:0.75 transparent, stop:0.76 #999999,
                    stop:0.78 #999999, stop:0.79 transparent,
                    stop:0.85 transparent, stop:0.86 #999999,
                    stop:0.88 #999999, stop:0.89 transparent);
                border: none;
            }
        """)

        layout.addWidget(self._archive_btn)
        layout.addWidget(spacer)
        layout.addWidget(self._stats_label)
        layout.addWidget(self._quit_btn)
        layout.addWidget(grip)
        footer.setLayout(layout)
        return footer

    def update_stats(self, active_count: int, archived_count: int) -> None:
        """更新底部统计"""
        self._stats_label.setText(f"共 {active_count} 项")
        self._archive_btn.setText(f"📦 查看归档 ({archived_count})")

    def set_pinned(self, pinned: bool) -> None:
        """同步置顶按钮样式（由控制器调用）"""
        self._pinned = pinned
        self._pin_btn.setText("📌" if pinned else "📍")
        self._pin_btn.setStyleSheet(AppTheme.pin_btn_style(pinned))
        self._pin_btn.setToolTip("点击取消置顶" if pinned else "点击置顶")

    # ── 主题重载 ──────────────────────────────────────────

    def reapply_theme(self) -> None:
        """重新应用当前主题样式（初始化 / 主题切换时调用）"""
        C = AppTheme.C

        # ── 自身 ──────────────────────────────────────────
        self.setStyleSheet(f"""
            ExpandedView {{
                background: {C["bg_primary"]};
                border: 1px solid {C["border"]};
                border-radius: 8px;
            }}
        """)

        # ── 标题栏 ────────────────────────────────────────
        self._title_bar.setStyleSheet(f"""
            background: {C["bg_primary"]};
            border-bottom: 1px solid {C["border"]};
            border-top-left-radius: 8px;
            border-top-right-radius: 8px;
        """)

        # ── 标题文字 ──────────────────────────────────────
        title_label = self._title_bar.findChild(QLabel)
        if title_label:
            title_label.setStyleSheet(f"""
                font: {AppTheme.FONT["title"]};
                background: transparent;
            """)

        # ── 标题栏按钮 ────────────────────────────────────
        self._autostart_btn.setStyleSheet(self._autostart_btn_style(self._autostart))
        self._theme_btn.setStyleSheet(self._icon_btn_style())
        self._theme_btn.setText("🌙" if not AppTheme.is_dark() else "☀️")
        self._theme_btn.setToolTip("切换深色模式" if not AppTheme.is_dark() else "切换浅色模式")
        self._search_btn.setStyleSheet(self._icon_btn_style())
        self._pin_btn.setStyleSheet(AppTheme.pin_btn_style(self._pinned))
        self._collapse_cards_btn.setStyleSheet(self._icon_btn_style())
        self._collapse_btn.setStyleSheet(self._icon_btn_style())

        # ── 快速添加栏 ────────────────────────────────────
        self._add_bar.setStyleSheet(f"""
            background: {C["bg_card"]};
            border-bottom: 1px solid {C["border"]};
        """)
        self._add_btn.setStyleSheet(f"""
            QPushButton {{
                font-size: 18px;
                color: {C["accent"]};
                border-radius: 4px;
                padding: 2px;
                background: {C["bg_hover"]};
            }}
            QPushButton:hover {{
                background: {C["accent"]};
                color: white;
            }}
        """)
        self._search_bar.setStyleSheet(f"""
            QLineEdit {{
                border: 1px solid {C["accent"]};
                border-radius: 4px;
                padding: 6px 10px;
                background: {C["bg_card"]};
            }}
        """)

        # ── 页脚 ────────────────────────────────────────────
        self._footer.setStyleSheet(f"""
            background: {C["bg_primary"]};
            border-top: 1px solid {C["border"]};
            border-bottom-left-radius: 8px;
            border-bottom-right-radius: 8px;
        """)
        self._stats_label.setStyleSheet(f"""
            font: {AppTheme.FONT["small"]};
            color: {C["text_secondary"]};
            background: transparent;
        """)
        self._quit_btn.setStyleSheet(f"""
            QPushButton {{
                font: {AppTheme.FONT["small"]};
                color: {C["text_disabled"]};
                border-radius: 4px;
                padding: 2px 8px;
                background: transparent;
            }}
            QPushButton:hover {{
                background: {C["danger"]}; color: white;
            }}
        """)

        # ── 更新卡片主题（无需重建，保留进度展开状态） ──
        has_cards = False
        for w in self._iter_cards():
            w.reapply_theme()
            has_cards = True

        if not has_cards:
            # 空状态 / 无结果状态：需重建状态标签
            self.refresh(self._items)

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
    def _autostart_btn_style(enabled: bool = False) -> str:
        C = AppTheme.C
        color = C["accent"] if enabled else C["text_disabled"]
        hov_color = C["accent"] if enabled else C["text_secondary"]
        return f"""
            QPushButton {{
                font-size: 14px;
                color: {color};
                border-radius: 4px;
                padding: 2px;
                background: transparent;
            }}
            QPushButton:hover {{
                background: {C["bg_hover"]};
                color: {hov_color};
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
