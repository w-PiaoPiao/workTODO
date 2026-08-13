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

from PySide6.QtCore import Signal, Qt, QTimer, QEvent, QPoint, QRect, QPropertyAnimation, QEasingCurve, QSize
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QScrollArea, QFrame, QSizePolicy, QSizeGrip, QApplication, QSlider,
    QStackedWidget, QTabBar,
)
from PySide6.QtGui import QIcon, QPixmap
from app.config import AppConfig
from app.views.theme import AppTheme
from app.models.todo_item import TodoItem
from app.views.todo_card import TodoCard
from app.views.title_bar import TitleBar
from app.views.drag_drop_manager import DragDropManager
from app.views.note_view import NoteView
from app.views.ui_utils import clear_layout


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
    signal_theme_mode_clicked = Signal()  # 主题三态轮换
    signal_autostart_toggled = Signal(bool)  # enabled=True
    signal_opacity_changed = Signal(float)  # 0.0 ~ 1.0（实时窗口）
    signal_opacity_committed = Signal(float)  # 0.0 ~ 1.0（松手持久化）
    signal_font_scale_changed = Signal(float)  # 字号缩放（松手应用+持久化）
    signal_due_date_set = Signal(str, str)  # item_id, due_date（空=清除）
    signal_tab_changed = Signal(str)  # "todo" | "notes"
    signal_tag_filter_clicked = Signal(str)  # tag（空=全部）
    signal_stats_requested = Signal()
    signal_backup_clicked = Signal()
    signal_notes_added = Signal(str, str)  # content, color
    signal_note_updated = Signal(str, str, str)  # note_id, content, color
    signal_note_deleted = Signal(str)  # note_id
    signal_pet_selected = Signal(str)  # 桌宠形象 id

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
        self._active_tag = ""  # 当前标签筛选（空=全部）
        self._all_tags: list[str] = []
        self._pets: list[dict] = []  # 桌宠形象 [{id, name, path}]
        self._pet_buttons: dict[str, QPushButton] = {}  # pet_id → 缩略图按钮
        self._pet_thumb_icons: dict[str, QIcon] = {}  # pet_id → 缩略图图标缓存

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
        self._title_bar.signal_theme_mode_clicked.connect(self.signal_theme_mode_clicked.emit)
        self._title_bar.signal_search_clicked.connect(self._toggle_search)
        self._title_bar.signal_toggle_pin.connect(self.signal_toggle_pin.emit)
        self._title_bar.signal_collapse_cards_toggled.connect(self._toggle_collapse_cards)
        self._title_bar.signal_settings_clicked.connect(self._toggle_settings_panel)
        self._title_bar.signal_stats_clicked.connect(self.signal_stats_requested.emit)
        main_layout.addWidget(self._title_bar)

        # ── 待办 / 便签切换标签栏 ─────────────────────────
        self._tab_bar = QTabBar()
        self._tab_bar.addTab("📋 待办")
        self._tab_bar.addTab("📝 便签")
        self._tab_bar.setStyleSheet(AppTheme.tab_bar_style())
        self._tab_bar.setExpanding(True)
        self._tab_bar.currentChanged.connect(self._on_tab_changed)
        main_layout.addWidget(self._tab_bar)

        # ── 页面容器（待办页 + 便签页） ────────────────────
        self._pages = QStackedWidget()
        self._todo_page = QWidget()
        self._todo_layout = QVBoxLayout()
        self._todo_layout.setContentsMargins(0, 0, 0, 0)
        self._todo_layout.setSpacing(0)
        self._todo_page.setLayout(self._todo_layout)
        self._note_view = NoteView()
        self._note_view.signal_notes_added.connect(self.signal_notes_added.emit)
        self._note_view.signal_note_updated.connect(self.signal_note_updated.emit)
        self._note_view.signal_note_deleted.connect(self.signal_note_deleted.emit)
        self._pages.addWidget(self._todo_page)
        self._pages.addWidget(self._note_view)
        main_layout.addWidget(self._pages, stretch=1)

        # ── 快速添加栏 ────────────────────────────────────
        self._add_bar = self._make_add_bar()
        self._todo_layout.addWidget(self._add_bar)

        # ── 标签筛选行 ────────────────────────────────────
        self._tag_row = self._make_tag_row()
        self._todo_layout.addWidget(self._tag_row)

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

        self._todo_layout.addWidget(self._scroll_area, stretch=1)

        # ── 页脚 ──────────────────────────────────────────
        self._footer = self._make_footer()
        self._todo_layout.addWidget(self._footer)

        self.setLayout(main_layout)

        # ── 设置面板 / 统计面板 ────────────────────────
        self._settings_panel = self._make_settings_panel()
        self._stats_panel = self._make_stats_panel()

        # ── 应用主题样式 ──────────────────────────────────
        self.reapply_theme()

        self._built = True

    # ── 标签页切换 ──────────────────────────────────────────

    def _on_tab_changed(self, index: int) -> None:
        """待办/便签页切换"""
        self._pages.setCurrentIndex(index)
        self.signal_tab_changed.emit("todo" if index == 0 else "notes")

    def current_tab(self) -> str:
        """当前标签页"""
        return "todo" if self._tab_bar.currentIndex() == 0 else "notes"

    def switch_tab(self, tab: str) -> None:
        """切换到指定标签页"""
        self._tab_bar.setCurrentIndex(0 if tab == "todo" else 1)

    def set_notes(self, notes) -> None:
        """同步便签列表（由控制器调用）"""
        self._note_view.refresh(notes)

    def focus_note_add(self) -> None:
        """聚焦便签添加入口"""
        self.switch_tab("notes")
        self._note_view.focus_add()

    # ── 标题栏（提取到 TitleBar 独立组件） ─────────────────

    def set_autostart(self, enabled: bool) -> None:
        """同步开机自启状态（由控制器调用）"""
        self._autostart = enabled
        self._title_bar.set_autostart(enabled)

    def set_theme_mode(self, mode: str) -> None:
        """同步主题模式按钮状态（由控制器调用）"""
        self._title_bar.set_theme_mode(mode)

    def set_opacity_value(self, value: float) -> None:
        """设置透明度值并同步滑块（由控制器调用，恢复持久化值）"""
        self._opacity = value
        self._opacity_slider.setValue(int(value * 100))

    def set_font_scale_value(self, scale: float) -> None:
        """设置字号缩放并同步滑块（由控制器调用，恢复持久化值）"""
        self._font_slider.setValue(int(scale * 100))
        self._font_label.setText(f"{int(scale * 100)}%")

    def _toggle_collapse_cards(self) -> None:
        """切换全部卡片的折叠/展开"""
        self._all_collapsed = not self._all_collapsed
        self._title_bar.set_collapse_cards_state(self._all_collapsed)
        for w in self._iter_cards():
            w.set_all_collapsed(self._all_collapsed)

    # ── 设置面板（透明度 + 字号） ──────────────────────────

    def _make_settings_panel(self) -> QFrame:
        """创建设置弹出面板（透明度滑块 + 字号滑块 + 桌宠形象）"""
        panel = QFrame(self)
        panel.setFixedWidth(220)
        panel.setStyleSheet(AppTheme.popup_panel_style())
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(4)

        opacity_row = QHBoxLayout()
        opacity_row.setSpacing(8)
        opacity_label = QLabel("透明度")
        opacity_label.setStyleSheet(AppTheme.panel_label_style())
        opacity_label.setFixedWidth(44)

        self._opacity_label = QLabel("100%")
        self._opacity_label.setStyleSheet(AppTheme.panel_label_style())
        self._opacity_label.setMinimumWidth(36)

        self._opacity_slider = QSlider(Qt.Horizontal)
        self._opacity_slider.setRange(
            int(AppConfig.WINDOW_OPACITY_MIN * 100),
            int(AppConfig.WINDOW_OPACITY_MAX * 100),
        )
        self._opacity_slider.setValue(int(self._opacity * 100))
        self._opacity_slider.valueChanged.connect(self._on_opacity_slider_changed)
        self._opacity_slider.sliderReleased.connect(self._on_opacity_committed)

        opacity_row.addWidget(opacity_label)
        opacity_row.addWidget(self._opacity_slider, stretch=1)
        opacity_row.addWidget(self._opacity_label)

        font_row = QHBoxLayout()
        font_row.setSpacing(8)
        font_label = QLabel("字号")
        font_label.setStyleSheet(AppTheme.panel_label_style())
        font_label.setFixedWidth(44)

        self._font_label = QLabel("100%")
        self._font_label.setStyleSheet(AppTheme.panel_label_style())
        self._font_label.setMinimumWidth(36)

        self._font_slider = QSlider(Qt.Horizontal)
        self._font_slider.setRange(
            int(AppConfig.FONT_SCALE_MIN * 100),
            int(AppConfig.FONT_SCALE_MAX * 100),
        )
        self._font_slider.setValue(int(AppTheme.font_scale() * 100))
        self._font_slider.valueChanged.connect(self._on_font_slider_changed)
        self._font_slider.sliderReleased.connect(self._on_font_committed)

        font_row.addWidget(font_label)
        font_row.addWidget(self._font_slider, stretch=1)
        font_row.addWidget(self._font_label)

        pet_row = QHBoxLayout()
        pet_row.setSpacing(6)
        pet_label = QLabel("宠物")
        pet_label.setStyleSheet(AppTheme.panel_label_style())
        pet_label.setFixedWidth(44)
        self._pet_thumbs_row = QHBoxLayout()
        self._pet_thumbs_row.setSpacing(4)
        pet_row.addWidget(pet_label)
        pet_row.addLayout(self._pet_thumbs_row, stretch=1)

        layout.addLayout(opacity_row)
        layout.addLayout(font_row)
        layout.addLayout(pet_row)
        panel.adjustSize()
        panel.hide()
        return panel

    def set_pets(self, pets: list[dict], selected_id: str) -> None:
        """设置桌宠形象列表并构建缩略图按钮（由控制器调用）"""
        self._pets = pets
        while self._pet_thumbs_row.count():
            item = self._pet_thumbs_row.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._pet_buttons.clear()
        self._pet_thumb_icons.clear()

        for pet in pets:
            pixmap = QPixmap(str(pet["path"]))
            icon = QIcon(pixmap.scaled(
                26, 26, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self._pet_thumb_icons[pet["id"]] = icon

            btn = QPushButton()
            btn.setFixedSize(30, 30)
            btn.setIconSize(QSize(26, 26))
            btn.setIcon(icon)
            btn.setToolTip(pet["name"])
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(AppTheme.pet_thumb_btn(pet["id"] == selected_id))
            btn.clicked.connect(
                lambda checked=False, pid=pet["id"]: self._on_pet_thumb_clicked(pid))
            self._pet_thumbs_row.addWidget(btn)
            self._pet_buttons[pet["id"]] = btn

    def set_selected_pet(self, pet_id: str) -> None:
        """高亮当前选中的桌宠形象（由控制器调用）"""
        for pid, btn in self._pet_buttons.items():
            btn.setStyleSheet(AppTheme.pet_thumb_btn(pid == pet_id))

    def _on_pet_thumb_clicked(self, pet_id: str) -> None:
        """桌宠形象缩略图点击"""
        self.set_selected_pet(pet_id)
        self.signal_pet_selected.emit(pet_id)

    def _on_opacity_slider_changed(self, value: int) -> None:
        """滑块值变化时实时更新窗口透明度"""
        opacity = value / 100.0
        self._opacity = opacity
        self._opacity_label.setText(f"{value}%")
        self.signal_opacity_changed.emit(opacity)

    def _on_opacity_committed(self) -> None:
        """松手后持久化透明度（避免拖动时高频写注册表）"""
        self.signal_opacity_committed.emit(self._opacity)

    def _on_font_slider_changed(self, value: int) -> None:
        """字号滑块变化：仅更新显示，松手才应用"""
        self._font_label.setText(f"{value}%")

    def _on_font_committed(self) -> None:
        """字号滑块松手：应用缩放并持久化"""
        scale = self._font_slider.value() / 100.0
        self.signal_font_scale_changed.emit(scale)

    def _toggle_settings_panel(self) -> None:
        """切换设置面板的显示/隐藏"""
        if self._settings_panel.isVisible():
            self._hide_settings_panel()
            return

        btn_rect = self._title_bar.settings_btn_global_rect()
        panel_x = btn_rect.right() - self._settings_panel.width()
        panel_y = btn_rect.bottom() + 2
        self._settings_panel.move(panel_x, panel_y)
        self._settings_panel.show()
        self._settings_panel.raise_()
        QApplication.instance().installEventFilter(self)

    def _hide_settings_panel(self) -> None:
        """隐藏设置面板并清理事件过滤器"""
        if self._settings_panel.isVisible():
            self._settings_panel.hide()
        if not self._stats_panel.isVisible():
            QApplication.instance().removeEventFilter(self)

    # ── 统计面板 ──────────────────────────────────────────

    def _make_stats_panel(self) -> QFrame:
        """创建统计弹出面板"""
        panel = QFrame(self)
        panel.setFixedSize(180, 110)
        panel.setStyleSheet(AppTheme.popup_panel_style())
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(3)

        self._stats_labels: list[QLabel] = []
        for _ in range(5):
            label = QLabel("")
            label.setStyleSheet(AppTheme.panel_label_style())
            layout.addWidget(label)
            self._stats_labels.append(label)
        panel.hide()
        return panel

    def show_stats(self, stats: dict) -> None:
        """显示统计面板（由控制器提供数据后调用）"""
        lines = [
            f"待办 {stats['active_count']} 项",
            f"今日完成 {stats['today_completed']} 项",
            f"本周完成 {stats['week_completed']} 项",
            f"累计完成 {stats['total_completed']} 项",
            f"归档 {stats['archived_count']} 条",
        ]
        for label, text in zip(self._stats_labels, lines):
            label.setText(text)

        if not self._stats_panel.isVisible():
            btn_rect = self._title_bar.stats_btn_global_rect()
            panel_x = btn_rect.right() - self._stats_panel.width()
            panel_y = btn_rect.bottom() + 2
            self._stats_panel.move(panel_x, panel_y)
            self._stats_panel.show()
            self._stats_panel.raise_()
            QApplication.instance().installEventFilter(self)

    def _hide_stats_panel(self) -> None:
        """隐藏统计面板并清理事件过滤器"""
        if self._stats_panel.isVisible():
            self._stats_panel.hide()
        if not self._settings_panel.isVisible():
            QApplication.instance().removeEventFilter(self)

    # ── 标签筛选行 ────────────────────────────────────────

    def _make_tag_row(self) -> QWidget:
        """创建标签筛选行（无标签时隐藏）"""
        row = QWidget()
        row.setFixedHeight(32)
        row.setStyleSheet(f"""
            background: {AppTheme.C["bg_primary"]};
            border-bottom: 1px solid {AppTheme.C["border"]};
        """)
        self._tag_layout = QHBoxLayout()
        self._tag_layout.setContentsMargins(12, 2, 12, 2)
        self._tag_layout.setSpacing(6)
        row.setLayout(self._tag_layout)
        row.hide()
        return row

    def update_tag_filters(self, tags: list[str], active_tag: str) -> None:
        """更新标签筛选 chips（由控制器调用）"""
        self._all_tags = tags
        self._active_tag = active_tag
        # 清空旧 chips
        while self._tag_layout.count():
            item = self._tag_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        if not tags:
            self._tag_row.hide()
            return

        def _make_btn(text: str, tag: str):
            btn = QPushButton(text)
            btn.setStyleSheet(AppTheme.tag_filter_btn(tag == active_tag))
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(
                lambda checked, t=tag: self.signal_tag_filter_clicked.emit(t))
            return btn

        self._tag_layout.addWidget(_make_btn("全部", ""))
        for tag in tags:
            self._tag_layout.addWidget(_make_btn(f"#{tag}", tag))
        self._tag_layout.addStretch(1)
        self._tag_row.show()

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
        card.signal_due_date_set.connect(self.signal_due_date_set.emit)
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
        clear_layout(self._list_layout)

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
        """合并事件路由：弹出面板关闭 + 点击外部收起进度 + 拖放排序"""
        # 构造完成前所有事件直接透传（_build_ui 中事件可能先于属性初始化触发）
        if not self._built:
            return super().eventFilter(obj, event)

        # 弹出面板：点击外部区域关闭
        if event.type() == QEvent.MouseButtonPress:
            global_pos = event.globalPosition().toPoint()
            if self._settings_panel.isVisible():
                panel_rect = QRect(
                    self._settings_panel.mapToGlobal(QPoint(0, 0)),
                    self._settings_panel.size(),
                )
                btn_rect = self._title_bar.settings_btn_global_rect()
                btn_rect.moveTopLeft(self.mapToGlobal(btn_rect.topLeft()))
                if not panel_rect.contains(global_pos) and not btn_rect.contains(global_pos):
                    self._hide_settings_panel()
            if self._stats_panel.isVisible():
                panel_rect = QRect(
                    self._stats_panel.mapToGlobal(QPoint(0, 0)),
                    self._stats_panel.size(),
                )
                btn_rect = self._title_bar.stats_btn_global_rect()
                btn_rect.moveTopLeft(self.mapToGlobal(btn_rect.topLeft()))
                if not panel_rect.contains(global_pos) and not btn_rect.contains(global_pos):
                    self._hide_stats_panel()

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

        self._backup_btn = QPushButton("💾 备份")
        self._backup_btn.setStyleSheet(AppTheme.text_link_btn())
        self._backup_btn.setToolTip("导出 / 导入数据备份")
        self._backup_btn.clicked.connect(self.signal_backup_clicked.emit)

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
        layout.addWidget(self._backup_btn)
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
        self._archive_btn.setStyleSheet(AppTheme.text_link_btn())
        self._backup_btn.setStyleSheet(AppTheme.text_link_btn())

        # ── 弹出面板 ────────────────────────────────────
        self._settings_panel.setStyleSheet(AppTheme.popup_panel_style())
        self._stats_panel.setStyleSheet(AppTheme.popup_panel_style())
        self._opacity_label.setStyleSheet(AppTheme.panel_label_style())
        self._font_label.setStyleSheet(AppTheme.panel_label_style())
        for label in self._stats_labels:
            label.setStyleSheet(AppTheme.panel_label_style())

        # ── 标签筛选行 ────────────────────────────────────
        self._tag_row.setStyleSheet(f"""
            background: {C["bg_primary"]};
            border-bottom: 1px solid {C["border"]};
        """)
        for i in range(self._tag_layout.count()):
            w = self._tag_layout.itemAt(i).widget()
            if isinstance(w, QPushButton):
                w.setStyleSheet(AppTheme.tag_filter_btn(
                    w.text() == ("全部" if not self._active_tag else f"#{self._active_tag}")))

        # ── 待办/便签标签栏 ──────────────────────────────
        self._tab_bar.setStyleSheet(AppTheme.tab_bar_style())

        # ── 便签页 ────────────────────────────────────────
        self._note_view.reapply_theme()

        # ── 更新卡片主题（无需重建，保留进度展开状态） ──
        has_cards = False
        for w in self._iter_cards():
            w.reapply_theme()
            has_cards = True

        if not has_cards:
            # 空状态 / 无结果状态：需重建状态标签
            self.refresh(self._items, self._search_query)


