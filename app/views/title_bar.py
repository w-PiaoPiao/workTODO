"""
标题栏组件

ExpandedView 顶部的标题栏，包含应用标题、高频按钮与「⋯」溢出菜单。
高频按钮：搜索、设置、折叠；其余功能收纳进溢出菜单。
所有按钮使用 SVG 图标（AppIcons），随主题变色。
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Signal
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMenu, QPushButton, QSizePolicy, QWidget

from app.views.icons import AppIcons
from app.views.theme import AppTheme


class TitleBar(QWidget):
    """标题栏：标题 + 高频按钮 + 溢出菜单"""

    signal_collapse_clicked = Signal()
    signal_autostart_toggled = Signal(bool)
    signal_theme_mode_selected = Signal(str)  # "light" | "dark" | "auto"
    signal_search_clicked = Signal()
    signal_toggle_pin = Signal()
    signal_collapse_cards_toggled = Signal()
    signal_settings_clicked = Signal()
    signal_stats_requested = Signal()
    signal_backup_clicked = Signal()
    signal_quit_requested = Signal()

    # 主题模式图标 / 提示 / 标签
    THEME_ICONS = {"light": "theme-light", "dark": "theme-dark", "auto": "theme-auto"}
    THEME_TIPS = {"light": "浅色模式", "dark": "深色模式", "auto": "跟随系统"}

    _ICON_SIZE = 18

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._autostart = False
        self._all_collapsed = False
        self._pinned = True
        self._theme_mode = "light"
        self._build_ui()
        self._apply_style()
        AppTheme.register(self._apply_style)

    def _build_ui(self) -> None:
        self.setFixedHeight(40)

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

        self._search_btn = self._make_icon_btn("search", "搜索")
        self._search_btn.clicked.connect(self.signal_search_clicked.emit)

        self._settings_btn = self._make_icon_btn("settings", "设置（透明度 / 字号）")
        self._settings_btn.clicked.connect(self.signal_settings_clicked.emit)

        self._collapse_btn = self._make_icon_btn("collapse", "折叠")
        self._collapse_btn.clicked.connect(self.signal_collapse_clicked.emit)

        self._more_btn = self._make_icon_btn("more", "更多功能")
        self._more_btn.clicked.connect(self._show_more_menu)

        layout.addWidget(title)
        layout.addWidget(spacer)
        layout.addWidget(self._search_btn)
        layout.addWidget(self._settings_btn)
        layout.addWidget(self._collapse_btn)
        layout.addWidget(self._more_btn)
        self.setLayout(layout)

    def _make_icon_btn(self, name: str, tooltip: str) -> QPushButton:
        """创建带 SVG 图标的图标按钮"""
        btn = QPushButton()
        btn.setFixedSize(28, 28)
        btn.setIconSize(QSize(self._ICON_SIZE, self._ICON_SIZE))
        btn.setIcon(AppIcons.get(name, self._ICON_SIZE))
        btn.setToolTip(tooltip)
        btn.setStyleSheet(AppTheme.icon_btn())
        return btn

    # ── 溢出菜单 ──────────────────────────────────────────

    def _show_more_menu(self) -> None:
        """弹出「⋯」溢出菜单（临时构建，checkable 状态取自当前内部状态）"""
        menu = QMenu(self)
        menu.setStyleSheet(AppTheme.menu_style())

        pin_action = menu.addAction(AppIcons.get("pin"), "置顶")
        pin_action.setCheckable(True)
        pin_action.setChecked(self._pinned)
        pin_action.triggered.connect(self.signal_toggle_pin.emit)

        collapse_action = menu.addAction(AppIcons.get("collapse-cards"), "收起全部卡片")
        collapse_action.setCheckable(True)
        collapse_action.setChecked(self._all_collapsed)
        collapse_action.triggered.connect(self.signal_collapse_cards_toggled.emit)

        stats_action = menu.addAction(AppIcons.get("stats"), "统计")
        stats_action.triggered.connect(self.signal_stats_requested.emit)

        # 主题子菜单（三选一）
        theme_menu = menu.addMenu(AppIcons.get(self.THEME_ICONS.get(self._theme_mode, "theme-auto")), "主题")
        theme_group = QActionGroup(theme_menu)
        theme_group.setExclusive(True)
        for mode in ("light", "dark", "auto"):
            act = QAction(self.THEME_TIPS[mode], theme_menu)
            act.setCheckable(True)
            act.setChecked(mode == self._theme_mode)
            act.triggered.connect(
                lambda checked, m=mode: self.signal_theme_mode_selected.emit(m))
            theme_group.addAction(act)
            theme_menu.addAction(act)

        autostart_action = menu.addAction(AppIcons.get("autostart"), "开机自启")
        autostart_action.setCheckable(True)
        autostart_action.setChecked(self._autostart)
        autostart_action.triggered.connect(self.signal_autostart_toggled.emit)

        menu.addSeparator()

        backup_action = menu.addAction(AppIcons.get("backup"), "数据备份")
        backup_action.triggered.connect(self.signal_backup_clicked.emit)

        quit_action = menu.addAction(AppIcons.get("quit"), "退出")
        quit_action.triggered.connect(self.signal_quit_requested.emit)

        pos = self._more_btn.mapToGlobal(QPoint(0, self._more_btn.height() + 4))
        menu.exec(pos)

    # ── 公共方法（状态同步，供菜单初始化） ────────────────

    def set_autostart(self, enabled: bool) -> None:
        self._autostart = enabled

    def set_theme_mode(self, mode: str) -> None:
        """同步主题模式（light/dark/auto）"""
        self._theme_mode = mode

    def set_pinned(self, pinned: bool) -> None:
        self._pinned = pinned

    def set_collapse_cards_state(self, all_collapsed: bool) -> None:
        self._all_collapsed = all_collapsed

    def settings_btn_rect(self) -> QRect:
        """返回设置按钮在父窗口坐标系中的区域（设置面板锚定）"""
        tl = self._settings_btn.mapTo(self.parent(), QPoint(0, 0))
        return QRect(tl, self._settings_btn.size())

    def more_btn_rect(self) -> QRect:
        """返回 ⋯ 按钮在父窗口坐标系中的区域（统计面板锚定）"""
        tl = self._more_btn.mapTo(self.parent(), QPoint(0, 0))
        return QRect(tl, self._more_btn.size())

    # ── 主题 ──────────────────────────────────────────────

    def _apply_style(self) -> None:
        C = AppTheme.C
        self.setStyleSheet(f"""
            TitleBar {{
                background: {C["bg_primary"]};
                border-bottom: 1px solid {C["border"]};
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
            }}
        """)
        self._search_btn.setStyleSheet(AppTheme.icon_btn())
        self._settings_btn.setStyleSheet(AppTheme.icon_btn())
        self._collapse_btn.setStyleSheet(AppTheme.icon_btn())
        self._more_btn.setStyleSheet(AppTheme.icon_btn())
        # 主题/字号变化 → 颜色变化 → 重新生成图标
        self._refresh_icons()

    def _refresh_icons(self) -> None:
        """按当前主题色重新设置按钮图标"""
        self._search_btn.setIcon(AppIcons.get("search", self._ICON_SIZE))
        self._settings_btn.setIcon(AppIcons.get("settings", self._ICON_SIZE))
        self._collapse_btn.setIcon(AppIcons.get("collapse", self._ICON_SIZE))
        self._more_btn.setIcon(AppIcons.get("more", self._ICON_SIZE))

    # ── 事件 ──────────────────────────────────────────────

    def mouseDoubleClickEvent(self, event) -> None:
        self.signal_collapse_clicked.emit()
        event.accept()
        super().mouseDoubleClickEvent(event)
