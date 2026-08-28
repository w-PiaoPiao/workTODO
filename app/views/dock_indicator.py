"""
贴顶隐藏位置提示条（DockIndicator）

桌宠被拖到屏幕顶部执行"贴顶吸附隐藏"后，窗口只露出底部 6px、几乎不可见。
本组件提供一个独立的置顶小条，常驻在桌宠隐藏位置（从屏幕顶边垂下的圆角胶囊），
让用户一眼就知道桌宠藏在哪里、怎么找回：

- 中央 ▾ 箭头 + 待办计数角标（accent 底白字，0 隐藏，99+ 封顶）
- 单击 → 展开完整列表；悬停 → 临时唤出桌宠（复用顶部热区机制）；右键 → 展开/退出
- 首次出现做一次呼吸闪烁（透明度脉动），便于第一时间发现
- 仅在整个应用可见且处于"贴顶隐藏"时由 MainWindow 显示，其余状态一律隐藏

外观与 PetCanvas 一致采用 QPainter 自绘，颜色直接读 AppTheme.C，随主题切换即时更新。
"""

from __future__ import annotations

import logging

from PySide6.QtCore import (
    Property,
    QAbstractAnimation,
    QEasingCurve,
    QEvent,
    QObject,
    QPropertyAnimation,
    QRect,
    QRectF,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QFont,
    QFontMetrics,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QMenu, QWidget

from app.config import AppConfig
from app.views.theme import AppTheme

logger = logging.getLogger(__name__)


class _PulseValue(QObject):
    """供 QPropertyAnimation 驱动"绘制透明度"的占位对象（避免改 windowOpacity）"""

    valueChanged = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = 1.0

    def _get(self) -> float:
        return self._value

    def _set(self, value: float) -> None:
        self._value = float(value)
        self.valueChanged.emit(self._value)

    value = Property(float, _get, _set)


class DockIndicator(QWidget):
    """贴顶隐藏时的位置提示条（独立置顶顶层窗口）"""

    signal_clicked = Signal()          # 左键单击
    signal_hovered = Signal()          # 鼠标进入
    signal_expand_clicked = Signal()   # 菜单"展开"
    signal_quit_requested = Signal()   # 菜单"退出"

    _SIDE_PAD = 6      # 胶囊左右留白（像素）
    _CORNER_R = 9      # 胶囊底角圆角半径

    def __init__(self, parent=None):
        super().__init__(
            parent,
            Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint,
        )
        # 不抢焦点、不进任务栏/Alt-Tab、透明背景
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(
            AppConfig.DOCK_INDICATOR_WIDTH, AppConfig.DOCK_INDICATOR_HEIGHT)

        self._count = 0
        self._pulse_alpha = 1.0
        self._pulse_holder = _PulseValue(self)
        self._pulse_holder.valueChanged.connect(self._on_pulse_alpha)
        self._pulse_anim: QPropertyAnimation | None = None

        # ── 右键菜单 ──────────────────────────────────────
        self._menu = QMenu(self)
        self._menu.setStyleSheet(AppTheme.menu_style())
        act_expand = QAction("展开", self._menu)
        act_quit = QAction("退出", self._menu)
        self._menu.addAction(act_expand)
        self._menu.addSeparator()
        self._menu.addAction(act_quit)
        act_expand.triggered.connect(self.signal_expand_clicked.emit)
        act_quit.triggered.connect(self.signal_quit_requested.emit)

        # 主题切换时重绘 + 刷新菜单样式
        AppTheme.register(self.reapply_theme)

    # ── 对外接口 ──────────────────────────────────────────

    def position_at(self, screen_geo: QRect, win_x: int, win_w: int) -> None:
        """定位到隐藏窗口水平中心对应的屏幕顶部，x 夹取在屏幕内"""
        w = self.width()
        center = win_x + win_w // 2
        x = center - w // 2
        x = max(screen_geo.left() + 4, min(x, screen_geo.right() - w - 4))
        self.move(x, screen_geo.top())

    def set_count(self, count: int) -> None:
        """更新待办计数角标（0 不画角标）"""
        if count != self._count:
            self._count = count
            self.update()

    def start_pulse(self) -> None:
        """首次出现的呼吸闪烁（1.0 → 0.4 → 1.0），提示用户注意"""
        if self._pulse_anim is not None and \
                self._pulse_anim.state() == QAbstractAnimation.Running:
            return
        if self._pulse_anim is None:
            # 复用单个动画实例：每次贴顶都新建会在 self 上累积子对象
            anim = QPropertyAnimation(self._pulse_holder, b"value", self)
            anim.setDuration(AppConfig.DOCK_INDICATOR_PULSE_MS)
            anim.setStartValue(1.0)
            anim.setKeyValueAt(0.5, 0.4)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QEasingCurve.InOutSine)
            self._pulse_anim = anim
        self._pulse_holder.value = 1.0
        self._pulse_anim.start()

    # ── 绘制 ──────────────────────────────────────────────

    def _on_pulse_alpha(self, value: float) -> None:
        self._pulse_alpha = value
        self.update()

    def _pill_path(self) -> QPainterPath:
        """胶囊外形：顶边贴窗（屏幕顶边），仅底角圆角"""
        w, h = self.width(), self.height()
        x1 = self._SIDE_PAD
        x2 = w - self._SIDE_PAD
        r = self._CORNER_R
        path = QPainterPath()
        path.moveTo(x1, 0)
        path.lineTo(x2, 0)
        path.lineTo(x2, h - r)
        path.arcTo(QRectF(x2 - 2 * r, h - 2 * r, 2 * r, 2 * r), 0, 90)
        path.lineTo(x1 + r, h)
        path.arcTo(QRectF(x1, h - 2 * r, 2 * r, 2 * r), 90, 90)
        path.lineTo(x1, 0)
        path.closeSubpath()
        return path

    def paintEvent(self, event) -> None:
        C = AppTheme.C
        w, h = self.width(), self.height()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setOpacity(self._pulse_alpha)

        # ── 胶囊底（主题背景色 + 边框） ──
        pill = self._pill_path()
        painter.fillPath(pill, QColor(C["bg_card"]))
        pen = QPen(QColor(C["border"]), 1.0)
        painter.setPen(pen)
        painter.drawPath(pill)

        # ── ▾ 箭头（accent 色，居中） ──
        cy = h // 2 + 2
        arrow_pen = QPen(QColor(AppTheme.C["accent"]), 2.2)
        arrow_pen.setCapStyle(Qt.RoundCap)
        arrow_pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(arrow_pen)
        path = QPainterPath()
        path.moveTo(w / 2 - 6, cy - 5)
        path.lineTo(w / 2, cy + 1)
        path.lineTo(w / 2 + 6, cy - 5)
        painter.strokePath(path, arrow_pen)

        # ── 计数角标（accent 底白字，靠右，0 时省略） ──
        if self._count > 0:
            text = "99+" if self._count > 99 else str(self._count)
            font = QFont(AppTheme.FONT_FAMILY, 8)
            font.setBold(True)
            fm = QFontMetrics(font)
            bw = max(fm.horizontalAdvance(text) + 8, 16)
            bh = 16
            bx = w - self._SIDE_PAD - bw - 4
            by = (h - bh) // 2
            painter.setBrush(QColor(C["accent"]))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(QRectF(bx, by, bw, bh), bh // 2, bh // 2)
            painter.setPen(QColor("white"))
            painter.setFont(font)
            painter.drawText(
                QRectF(bx, by, bw, bh), Qt.AlignCenter, text)

        painter.end()

    # ── 鼠标 / 悬停 ───────────────────────────────────────

    def enterEvent(self, event: QEvent) -> None:
        self.signal_hovered.emit()
        super().enterEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.RightButton:
            # 从提示条下方弹出（提示条贴屏幕顶，向下展开不会超出屏幕）
            self._menu.exec(self.mapToGlobal(self.rect().bottomLeft()))
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.signal_clicked.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    # ── 主题 ──────────────────────────────────────────────

    def reapply_theme(self) -> None:
        """主题切换：重绘 + 刷新菜单样式"""
        self._menu.setStyleSheet(AppTheme.menu_style())
        self.update()
