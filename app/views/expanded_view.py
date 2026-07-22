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

from PySide6.QtCore import Signal, Qt, QTimer, QEvent, QPoint, QRect, QPropertyAnimation, QEasingCurve
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QScrollArea, QFrame, QSizePolicy, QSizeGrip, QApplication, QSlider,
)
from app.config import AppConfig
from app.views.theme import AppTheme
from app.models.todo_item import TodoItem
from app.views.todo_card import TodoCard
from app.views.title_bar import TitleBar
from app.views.drag_drop_manager import DragDropManager


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
    signal_opacity_changed = Signal(float)  # 0.0 ~ 1.0

    def __init__(self, parent=None):
        super().__init__(parent)

        self._items: list[TodoItem] = []
        self._card_map: dict[str, TodoCard] = {}  # item_id → TodoCard（避免每次刷新重建）
        self._search_active = False
        self._search_query = ""
        self._pinned = True  # 默认置顶
        self._progress_expanded_card_id: str | None = None  # 当前展开进度的卡片 item_id
        self._drag_mgr = DragDropManager()
        self._drag_mgr.signal_reorder_items.connect(self.signal_reorder_items.emit)
        self._autostart = False  # 开机自启状态
        self._all_collapsed = False  # 全部卡片折叠状态
        self._opacity = AppConfig.WINDOW_OPACITY_DEFAULT

        # 搜索防抖 —— 复用单个 timer，避免每次按键创建新对象
        self._search_timer = QTimer()
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self._on_search_flush)

        self._built = False  # 标记是否已完成构造，防止 _build_ui 中事件过滤器访问未初始化的属性
        self._build_ui()
        AppTheme.register(self.reapply_theme)

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
        self._title_bar = TitleBar()
        self._title_bar.signal_collapse_clicked.connect(self.signal_collapse_clicked.emit)
        self._title_bar.signal_autostart_toggled.connect(self.signal_autostart_toggled.emit)
        self._title_bar.signal_theme_toggled.connect(self.signal_theme_toggled.emit)
        self._title_bar.signal_search_clicked.connect(self._toggle_search)
        self._title_bar.signal_toggle_pin.connect(self.signal_toggle_pin.emit)
        self._title_bar.signal_collapse_cards_toggled.connect(self._toggle_collapse_cards)
        self._title_bar.signal_opacity_clicked.connect(self._toggle_opacity_panel)
        main_layout.addWidget(self._title_bar)

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
        self._list_container.installEventFilter(self)  # 监听外部点击收起进度
        # 滚动区域视口也要监听拖拽事件（scroll area 的视口会拦截事件）
        self._scroll_area.viewport().installEventFilter(self)
        self._scroll_area.setWidget(self._list_container)

        # 安装拖放排序管理器
        self._drag_mgr.install(
            self._list_container, self._list_layout, self._scroll_area,
            iter_cards=self._iter_cards,
            is_searching=lambda: bool(self._search_query),
        )

        main_layout.addWidget(self._scroll_area, stretch=1)

        # ── 页脚 ──────────────────────────────────────────
        self._footer = self._make_footer()
        main_layout.addWidget(self._footer)

        self.setLayout(main_layout)

        # ── 透明度滑块面板 ────────────────────────────
        self._opacity_panel = self._make_opacity_panel()

        # ── 应用主题样式 ──────────────────────────────────
        self.reapply_theme()

        self._built = True

    # ── 标题栏（提取到 TitleBar 独立组件） ─────────────────

    def set_autostart(self, enabled: bool) -> None:
        """同步开机自启状态（由控制器调用）"""
        self._autostart = enabled
        self._title_bar.set_autostart(enabled)

    def set_opacity_value(self, value: float) -> None:
        """设置透明度值并同步滑块（由控制器调用，恢复持久化值）"""
        self._opacity = value
        self._opacity_slider.setValue(int(value * 100))

    def _toggle_collapse_cards(self) -> None:
        """切换全部卡片的折叠/展开"""
        self._all_collapsed = not self._all_collapsed
        self._title_bar.set_collapse_cards_state(self._all_collapsed)
        for w in self._iter_cards():
            w.set_all_collapsed(self._all_collapsed)

    # ── 透明度控制 ─────────────────────────────────────────

    def _make_opacity_panel(self) -> QFrame:
        """创建透明度滑块弹出面板"""
        panel = QFrame(self)
        panel.setFixedSize(180, 44)
        panel.setStyleSheet(f"""
            QFrame {{
                background: {AppTheme.C["bg_card"]};
                border: 1px solid {AppTheme.C["border"]};
                border-radius: 6px;
            }}
        """)
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.setSpacing(8)

        self._opacity_label = QLabel("100%")
        self._opacity_label.setStyleSheet(f"""
            font: {AppTheme.FONT["small"]};
            color: {AppTheme.C["text_primary"]};
            background: transparent;
            min-width: 36px;
        """)

        self._opacity_slider = QSlider(Qt.Horizontal)
        self._opacity_slider.setRange(
            int(AppConfig.WINDOW_OPACITY_MIN * 100),
            int(AppConfig.WINDOW_OPACITY_MAX * 100),
        )
        self._opacity_slider.setValue(int(self._opacity * 100))
        self._opacity_slider.setFixedWidth(110)
        self._opacity_slider.valueChanged.connect(self._on_opacity_slider_changed)

        layout.addWidget(self._opacity_label)
        layout.addWidget(self._opacity_slider)
        panel.hide()
        return panel

    def _on_opacity_slider_changed(self, value: int) -> None:
        """滑块值变化时实时更新透明度和显示"""
        opacity = value / 100.0
        self._opacity = opacity
        self._opacity_label.setText(f"{value}%")
        self.signal_opacity_changed.emit(opacity)

    def _toggle_opacity_panel(self) -> None:
        """切换透明度面板的显示/隐藏"""
        if self._opacity_panel.isVisible():
            self._hide_opacity_panel()
            return

        btn_rect = self._title_bar.opacity_btn_global_rect()
        panel_x = btn_rect.right() - self._opacity_panel.width()
        panel_y = btn_rect.bottom() + 2
        self._opacity_panel.move(panel_x, panel_y)
        self._opacity_panel.show()
        self._opacity_panel.raise_()
        QApplication.instance().installEventFilter(self)

    def _hide_opacity_panel(self) -> None:
        """隐藏透明度面板并清理事件过滤器"""
        self._opacity_panel.hide()
        QApplication.instance().removeEventFilter(self)

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
        self._add_btn.setStyleSheet(AppTheme.accent_fill_btn())
        self._add_btn.clicked.connect(self._on_add_submit)

        layout.addWidget(self._add_input)
        layout.addWidget(self._add_btn)
        bar.setLayout(layout)

        # 搜索栏（默认隐藏）
        self._search_bar = QLineEdit()
        self._search_bar.setPlaceholderText("搜索待办事项...")
        self._search_bar.setVisible(False)
        self._search_bar.setStyleSheet(AppTheme.search_bar_style())
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

    def _create_card(self, item: TodoItem) -> TodoCard:
        """创建一张新卡片并连接信号"""
        card = TodoCard(item, self)
        card.setProperty("todo_item_id", item.id)
        card.signal_completed.connect(self.signal_item_completed.emit)
        card.signal_deleted.connect(self.signal_item_deleted.emit)
        card.signal_progress_added.connect(self.signal_progress_added.emit)
        card.signal_sticky_toggled.connect(self.signal_sticky_toggled.emit)
        card.signal_title_changed.connect(self.signal_title_changed.emit)
        card.signal_progress_edited.connect(self.signal_progress_edited.emit)
        card.signal_progress_deleted.connect(self.signal_progress_deleted.emit)
        card.progress_toggled_signal.connect(
            lambda show_all, c=card: self._on_progress_toggle(c, show_all),
        )
        if self._all_collapsed:
            card.set_all_collapsed(True)
        self._card_map[item.id] = card
        return card

    def refresh(self, items: list[TodoItem], search_query: str = "") -> None:
        """差异化刷新待办列表（避免销毁重建已有卡片）"""
        self._items = items
        self._search_query = search_query

        # 过滤 + 排序活跃项
        active = [i for i in items if i.is_active]
        if not active:
            self._clear_list()
            if search_query:
                self._show_no_results()
            else:
                self._show_empty_state()
            return

        active.sort(key=lambda i: (not i.sticky, i.position if i.position else 0, i.created_at))

        # ── 计算需要展示的卡片 ────────────────────────────
        shown_ids = set()
        card_order: list[TodoCard] = []

        for item in active:
            card = self._card_map.get(item.id)
            if card:
                card.update_item(item)
            else:
                card = self._create_card(item)
            shown_ids.add(item.id)
            card_order.append(card)

        # ── 移除不再展示的卡片 ────────────────────────────
        for id_, card in list(self._card_map.items()):
            if id_ not in shown_ids:
                if self._progress_expanded_card_id == id_:
                    self._progress_expanded_card_id = None
                card.deleteLater()
                del self._card_map[id_]

        self._drag_mgr.clear()

        # ── 清理布局中的非卡片 widget（状态标签等） ────────
        for i in range(self._list_layout.count() - 1, -1, -1):
            item = self._list_layout.itemAt(i)
            w = item.widget()
            if w and not isinstance(w, TodoCard):
                self._list_layout.takeAt(i)
                w.deleteLater()

        # ── 按排序后的顺序排列卡片 ────────────────────────
        insert_idx = 0
        for card in card_order:
            current_idx = self._list_layout.indexOf(card)
            if current_idx != insert_idx:
                if current_idx >= 0:
                    self._list_layout.removeWidget(card)
                self._list_layout.insertWidget(insert_idx, card)
            insert_idx += 1

    def _clear_list(self) -> None:
        """移除列表中所有卡片和状态提示（完全重建时使用）"""
        self._progress_expanded_card_id = None
        self._drag_mgr.clear()
        for card in self._card_map.values():
            try:
                card.deleteLater()
            except RuntimeError:
                pass
        self._card_map.clear()
        while self._list_layout.count() > 1:
            item = self._list_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

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
        card_id = card.property("todo_item_id")
        if show_all:
            # 先收起其他卡片的进度
            if (self._progress_expanded_card_id
                    and self._progress_expanded_card_id != card_id):
                other = self._find_card(self._progress_expanded_card_id)
                if other:
                    try:
                        other.collapse_progress()
                    except RuntimeError:
                        pass
            self._progress_expanded_card_id = card_id
        else:
            if self._progress_expanded_card_id == card_id:
                self._progress_expanded_card_id = None

    def _collapse_expanded_progress(self) -> None:
        """收起当前展开的进度（点击外部时调用）"""
        if not self._progress_expanded_card_id:
            return
        card = self._find_card(self._progress_expanded_card_id)
        if card:
            try:
                card.collapse_progress()
            except RuntimeError:
                pass
        self._progress_expanded_card_id = None

    # ── 事件过滤器：点击外部收起进度 + 拖放排序 ──────────

    def eventFilter(self, obj, event) -> bool:
        """合并事件路由：标题栏双击折叠 + 透明度面板关闭 + 点击外部收起进度 + 拖放排序"""
        # 构造完成前所有事件直接透传（_build_ui 中事件可能先于属性初始化触发）
        if not self._built:
            return super().eventFilter(obj, event)

        # 透明度面板：点击外部区域关闭
        if (event.type() == QEvent.MouseButtonPress
                and self._opacity_panel.isVisible()):
            global_pos = event.globalPosition().toPoint()
            panel_rect = QRect(
                self._opacity_panel.mapToGlobal(QPoint(0, 0)),
                self._opacity_panel.size(),
            )
            btn_rect = self._title_bar.opacity_btn_global_rect()
            btn_rect.moveTopLeft(self.mapToGlobal(btn_rect.topLeft()))
            if not panel_rect.contains(global_pos) and not btn_rect.contains(global_pos):
                self._hide_opacity_panel()

        is_container = obj is self._list_container
        is_viewport = obj is self._scroll_area.viewport()

        if is_container and event.type() == QEvent.MouseButtonPress:
            return self._handle_container_click(event)
        if not (is_container or is_viewport):
            return super().eventFilter(obj, event)

        # 拖放排序事件 → 委托给 DragDropManager
        mgr = self._drag_mgr
        if event.type() == QEvent.DragEnter:
            return mgr.handle_drag_enter(event) or super().eventFilter(obj, event)
        if event.type() == QEvent.DragMove:
            return mgr.handle_drag_move(event, is_viewport) or super().eventFilter(obj, event)
        if event.type() == QEvent.DragLeave:
            return mgr.handle_drag_leave() or super().eventFilter(obj, event)
        if event.type() == QEvent.Drop:
            return mgr.handle_drag_drop(event, is_viewport) or super().eventFilter(obj, event)
        return super().eventFilter(obj, event)

    def _handle_container_click(self, event) -> bool:
        """点击容器空白区域收起展开的进度"""
        if self._progress_expanded_card_id is not None:
            card = self._find_card(self._progress_expanded_card_id)
            if card:
                click_pos = event.position().toPoint()
                card_tl = card.mapTo(self._list_container, QPoint(0, 0))
                card_rect = QRect(card_tl, card.size())
                if not card_rect.contains(click_pos):
                    self._collapse_expanded_progress()
        return super().eventFilter(self._list_container, event)

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
        self.refresh(todos, self._search_query)

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
        self._archive_btn.setStyleSheet(AppTheme.text_link_btn())
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
        self._title_bar.set_pinned(pinned)

    # ── 主题重载 ──────────────────────────────────────────

    def reapply_theme(self) -> None:
        """重新应用当前主题样式（初始化 / 主题切换时调用）

        注：TitleBar 通过 AppTheme.register 自行处理样式更新。
        """
        C = AppTheme.C

        # ── 自身 ──────────────────────────────────────────
        self.setStyleSheet(f"""
            ExpandedView {{
                background: {C["bg_primary"]};
                border: 1px solid {C["border"]};
                border-radius: 8px;
            }}
        """)

        # ── 快速添加栏 ────────────────────────────────────
        self._add_bar.setStyleSheet(f"""
            background: {C["bg_card"]};
            border-bottom: 1px solid {C["border"]};
        """)
        self._add_btn.setStyleSheet(AppTheme.accent_fill_btn())
        self._search_bar.setStyleSheet(AppTheme.search_bar_style())

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
        self._quit_btn.setStyleSheet(AppTheme.danger_fill_btn())

        # ── 透明度面板 ──────────────────────────────────
        self._opacity_panel.setStyleSheet(f"""
            QFrame {{
                background: {C["bg_card"]};
                border: 1px solid {C["border"]};
                border-radius: 6px;
            }}
        """)
        self._opacity_label.setStyleSheet(f"""
            font: {AppTheme.FONT["small"]};
            color: {C["text_primary"]};
            background: transparent;
            min-width: 36px;
        """)

        # ── 更新卡片主题（无需重建，保留进度展开状态） ──
        has_cards = False
        for w in self._iter_cards():
            w.reapply_theme()
            has_cards = True

        if not has_cards:
            # 空状态 / 无结果状态：需重建状态标签
            self.refresh(self._items, self._search_query)


