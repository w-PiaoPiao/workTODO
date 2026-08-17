"""
自定义 Tooltip 系统

Windows 原生 QToolTip 会忽略 QSS background 和 QPalette，导致黑底看不清。
本模块通过拦截所有窗口的 QEvent.ToolTip，用自定义 QFrame 显示白底 tooltip。

用法：
    在 main.py 创建 QApplication 后调用：
        from app.views.custom_tooltip import install_custom_tooltip
        install_custom_tooltip(app)

此后所有 QWidget.toolTip() 都会由 CustomTooltip 显示，而不是原生 tooltip。
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QVBoxLayout, QWidget


class CustomTooltip(QFrame):
    """白底自定义 tooltip 窗口（单例）"""

    _instance: CustomTooltip | None = None
    _default_timeout_ms = 8000  # tooltip 显示 8 秒后自动隐藏

    def __new__(cls, parent=None):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, parent=None):
        # 避免重复初始化（单例模式在 PySide6 中需要手动保护）
        if hasattr(self, "_initialized"):
            return
        self._initialized = True

        super().__init__(
            parent,
            Qt.ToolTip | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint,
        )
        # 不获取焦点、不参与 Alt-Tab、置顶
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TranslucentBackground, False)

        self._build_ui()
        self._apply_style()

        # 自动隐藏计时器
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(0)

        self._label = QLabel()
        self._label.setWordWrap(True)
        self._label.setMaximumWidth(4000)
        self._label.setTextInteractionFlags(Qt.NoTextInteraction)
        layout.addWidget(self._label)

    def _apply_style(self) -> None:
        """亮底暗字高可读性样式（跟随当前主题）"""
        from app.views.theme import AppTheme
        C = AppTheme.C
        self.setStyleSheet(f"""
            QFrame {{
                background: {C["bg_card"]};
                color: {C["text_primary"]};
                border: 1px solid {C["border"]};
                border-radius: 4px;
            }}
            QLabel {{
                color: {C["text_primary"]};
                background: transparent;
                font-size: 10pt;
            }}
        """)

    @classmethod
    def apply_theme_style(cls) -> None:
        """应用当前主题样式到 tooltip 单例（供外部主题切换时调用）"""
        instance = cls()
        instance._apply_style()

    def show_tip(self, text: str, pos: QPoint | None = None, timeout_ms: int | None = None) -> None:
        """显示 tooltip 在指定位置（默认鼠标位置右下方），并限制在屏幕内"""
        if not text:
            self.hide()
            return

        self._label.setText(text)

        # 计算文本实际宽度，取文本宽度与最大宽度较小值
        fm = self._label.fontMetrics()
        tw = fm.horizontalAdvance(text)
        mw = min(max(tw + 20, 40), 4000)
        rect = fm.boundingRect(
            QRect(0, 0, mw, 10000),
            Qt.TextWordWrap,
            text,
        )
        self._label.setFixedSize(min(rect.width(), mw) + 8,
                                 rect.height() + 8)
        self.adjustSize()

        if pos is None:
            pos = QCursor.pos() + QPoint(12, 16)

        # 限制 tooltip 不超出主屏幕
        screen = QApplication.primaryScreen()
        if screen:
            sg = screen.availableGeometry()
            size = self.size()
            x = max(sg.left() + 4, min(pos.x(), sg.right() - size.width() - 4))
            y = max(sg.top() + 4, min(pos.y(), sg.bottom() - size.height() - 4))
            pos = QPoint(x, y)

        self.move(pos)
        try:
            self.show()
            self.raise_()
        except RuntimeError:
            return

        if timeout_ms is None:
            timeout_ms = self._default_timeout_ms
        try:
            self._hide_timer.start(timeout_ms)
        except RuntimeError:
            pass

    def hide_tip(self) -> None:
        try:
            self._hide_timer.stop()
        except RuntimeError:
            pass
        try:
            self.hide()
        except RuntimeError:
            pass


class _TooltipEventFilter(QObject):
    """全局 tooltip 事件过滤器"""

    def __init__(self, app: QApplication, parent=None):
        super().__init__(parent)
        self._app = app
        self._tooltip = CustomTooltip()
        self._last_widget: QWidget | None = None

    def eventFilter(self, obj, event) -> bool:
        # 我们只关心 QWidget 的 tooltip 事件
        if not isinstance(obj, QWidget):
            return False

        etype = event.type()

        if etype == QEvent.ToolTip:
            text = obj.toolTip()
            # 跳过空 tooltip 或实际不可见的 widget（例如在滚动区域视口外）
            if not text or not obj.isVisible() or obj.visibleRegion().isEmpty():
                return False

            # 阻止原生 tooltip，改由自定义窗口显示
            self._tooltip.show_tip(text)
            self._last_widget = obj
            return True

        if etype in (QEvent.Leave, QEvent.Hide, QEvent.Close):
            if obj is self._last_widget:
                self._tooltip.hide_tip()
                self._last_widget = None
            return False

        if etype in (QEvent.MouseMove, QEvent.MouseButtonPress,
                     QEvent.MouseButtonDblClick, QEvent.Wheel):
            # 鼠标在 widget 内移动时保持 tooltip；按键/滚轮时隐藏
            if etype != QEvent.MouseMove and obj is self._last_widget:
                self._tooltip.hide_tip()
                self._last_widget = None
            return False

        if etype in (QEvent.KeyPress, QEvent.WindowDeactivate):
            self._tooltip.hide_tip()
            self._last_widget = None
            return False

        return False


def install_custom_tooltip(app: QApplication) -> None:
    """在 QApplication 上安装自定义 tooltip 事件过滤器"""
    from app.views.theme import AppTheme

    # 必须保留 Python 引用，否则 PySide6 wrapper 可能被 GC，
    # 导致 installEventFilter 注册的 C++ 对象失效。
    f = _TooltipEventFilter(app)
    _installed_filters.append(f)
    app.installEventFilter(f)

    # 注册主题监听
    AppTheme.register(CustomTooltip.apply_theme_style)


# 模块级容器，保持已安装的 filter 对象存活
_installed_filters: list[_TooltipEventFilter] = []
