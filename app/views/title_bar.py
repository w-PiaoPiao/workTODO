"""
标题栏组件

ExpandedView 顶部的标题栏，包含应用标题和所有功能按钮。
"""

from __future__ import annotations

from PySide6.QtCore import Signal, QPoint, QRect
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton, QSizePolicy
from app.views.theme import AppTheme


class TitleBar(QWidget):
    """标题栏：标题 + 功能按钮组"""

    signal_collapse_clicked = Signal()
    signal_autostart_toggled = Signal(bool)
    signal_theme_toggled = Signal(bool)
    signal_search_clicked = Signal()
    signal_toggle_pin = Signal()
    signal_collapse_cards_toggled = Signal()
    signal_opacity_clicked = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._autostart = False
        self._all_collapsed = False
        self._pinned = True
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

        self._autostart_btn = QPushButton("⚡")
        self._autostart_btn.setFixedSize(28, 28)
        self._autostart_btn.setToolTip("点击开启开机自启")
        self._autostart_btn.setStyleSheet(AppTheme.toggle_btn(False))
        self._autostart_btn.clicked.connect(self._on_autostart_clicked)

        self._theme_btn = QPushButton("🌙" if not AppTheme.is_dark() else "☀️")
        self._theme_btn.setFixedSize(28, 28)
        self._theme_btn.setToolTip("切换深色模式" if not AppTheme.is_dark() else "切换浅色模式")
        self._theme_btn.setStyleSheet(AppTheme.icon_btn())
        self._theme_btn.clicked.connect(self._on_theme_clicked)

        self._search_btn = QPushButton("🔍")
        self._search_btn.setFixedSize(28, 28)
        self._search_btn.setToolTip("搜索")
        self._search_btn.setStyleSheet(AppTheme.icon_btn())
        self._search_btn.clicked.connect(self.signal_search_clicked.emit)

        self._pin_btn = QPushButton("📌")
        self._pin_btn.setFixedSize(28, 28)
        self._pin_btn.setToolTip("点击切换置顶")
        self._pin_btn.setStyleSheet(AppTheme.pin_btn_style(True))
        self._pin_btn.clicked.connect(self.signal_toggle_pin.emit)

        self._collapse_cards_btn = QPushButton("⊟")
        self._collapse_cards_btn.setFixedSize(28, 28)
        self._collapse_cards_btn.setToolTip("收起全部卡片")
        self._collapse_cards_btn.setStyleSheet(AppTheme.icon_btn())
        self._collapse_cards_btn.clicked.connect(self._on_collapse_cards_clicked)

        self._opacity_btn = QPushButton("🔮")
        self._opacity_btn.setFixedSize(28, 28)
        self._opacity_btn.setToolTip("调整窗口透明度")
        self._opacity_btn.setStyleSheet(AppTheme.icon_btn())
        self._opacity_btn.clicked.connect(self.signal_opacity_clicked.emit)

        self._collapse_btn = QPushButton("━")
        self._collapse_btn.setFixedSize(28, 28)
        self._collapse_btn.setToolTip("折叠")
        self._collapse_btn.setStyleSheet(AppTheme.icon_btn())
        self._collapse_btn.clicked.connect(self.signal_collapse_clicked.emit)

        layout.addWidget(title)
        layout.addWidget(spacer)
        layout.addWidget(self._autostart_btn)
        layout.addWidget(self._theme_btn)
        layout.addWidget(self._search_btn)
        layout.addWidget(self._pin_btn)
        layout.addWidget(self._collapse_cards_btn)
        layout.addWidget(self._opacity_btn)
        layout.addWidget(self._collapse_btn)
        self.setLayout(layout)

    # ── 公共方法 ──────────────────────────────────────────

    def set_autostart(self, enabled: bool) -> None:
        self._autostart = enabled
        self._autostart_btn.setText("⚡" if enabled else "🔌")
        self._autostart_btn.setStyleSheet(AppTheme.toggle_btn(enabled))
        self._autostart_btn.setToolTip(
            "点击关闭开机自启" if enabled else "点击开启开机自启")

    def set_pinned(self, pinned: bool) -> None:
        self._pinned = pinned
        self._pin_btn.setText("📌" if pinned else "📍")
        self._pin_btn.setStyleSheet(AppTheme.pin_btn_style(pinned))
        self._pin_btn.setToolTip("点击取消置顶" if pinned else "点击置顶")

    def set_collapse_cards_state(self, all_collapsed: bool) -> None:
        self._all_collapsed = all_collapsed
        self._collapse_cards_btn.setText("⊞" if all_collapsed else "⊟")
        self._collapse_cards_btn.setToolTip(
            "展开全部卡片" if all_collapsed else "收起全部卡片")

    def opacity_btn_global_rect(self) -> QRect:
        """返回透明度按钮在父窗口坐标系中的区域"""
        tl = self._opacity_btn.mapTo(self.parent(), QPoint(0, 0))
        return QRect(tl, self._opacity_btn.size())

    # ── 内部处理 ──────────────────────────────────────────

    def _on_autostart_clicked(self) -> None:
        self.signal_autostart_toggled.emit(not self._autostart)

    def _on_theme_clicked(self) -> None:
        self.signal_theme_toggled.emit(not AppTheme.is_dark())

    def _on_collapse_cards_clicked(self) -> None:
        self.signal_collapse_cards_toggled.emit()

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
        self._theme_btn.setText("🌙" if not AppTheme.is_dark() else "☀️")
        self._theme_btn.setToolTip(
            "切换深色模式" if not AppTheme.is_dark() else "切换浅色模式")
        self._autostart_btn.setStyleSheet(AppTheme.toggle_btn(self._autostart))
        self._theme_btn.setStyleSheet(AppTheme.icon_btn())
        self._search_btn.setStyleSheet(AppTheme.icon_btn())
        self._pin_btn.setStyleSheet(AppTheme.pin_btn_style(self._pinned))
        self._collapse_cards_btn.setStyleSheet(AppTheme.icon_btn())
        self._opacity_btn.setStyleSheet(AppTheme.icon_btn())
        self._collapse_btn.setStyleSheet(AppTheme.icon_btn())

    # ── 事件 ──────────────────────────────────────────────

    def mouseDoubleClickEvent(self, event) -> None:
        self.signal_collapse_clicked.emit()
        event.accept()
        super().mouseDoubleClickEvent(event)
