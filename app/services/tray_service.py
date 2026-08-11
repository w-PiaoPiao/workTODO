"""
系统托盘服务

职责：托盘图标绘制、右键菜单、气泡通知。
与业务逻辑解耦：菜单动作只发信号（signal_show_requested / signal_quit_requested），
通知通过 show_notification() 提供，由控制器决定何时调用。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QObject, Signal
from PySide6.QtGui import QAction, QIcon, QPainter, QPainterPath, QPen, QColor, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from app.config import AppConfig


class TrayService(QObject):
    """系统托盘：图标、菜单、气泡通知"""

    signal_show_requested = Signal()
    signal_quit_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self._tray = QSystemTrayIcon(parent)

        # 美观的多分辨率托盘图标（剪切板 ✓）
        self._tray.setIcon(self._create_icon())
        self._tray.setToolTip("待办事项和便签")

        # 右键菜单
        menu = QMenu()
        show_action = QAction("显示/隐藏", menu)
        show_action.triggered.connect(self.signal_show_requested)
        menu.addAction(show_action)
        menu.addSeparator()
        quit_action = QAction("退出", menu)
        quit_action.triggered.connect(self.signal_quit_requested)
        menu.addAction(quit_action)

        self._tray.setContextMenu(menu)

        # 双击托盘恢复
        self._tray.activated.connect(self._on_activated)

        self._tray.show()

    # ── 对外接口 ──────────────────────────────────────────

    @property
    def tray(self) -> QSystemTrayIcon:
        """底层 QSystemTrayIcon（测试注入用）"""
        return self._tray

    def supports_messages(self) -> bool:
        """系统是否支持托盘气泡通知"""
        return self._tray.supportsMessages()

    def show_notification(self, message: str) -> None:
        """显示短暂的通知消息（托盘气泡，不支持时静默）"""
        if self._tray.supportsMessages():
            self._tray.showMessage(
                "待办事项和便签",
                message,
                QSystemTrayIcon.Information,
                AppConfig.NOTIFICATION_DURATION_MS,
            )

    def hide(self) -> None:
        """隐藏托盘图标（退出时调用）"""
        self._tray.hide()

    # ── 内部实现 ──────────────────────────────────────────

    def _on_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.DoubleClick:
            self.signal_show_requested.emit()

    @staticmethod
    def _create_icon() -> QIcon:
        """创建美观的多分辨率托盘图标（剪切板 ✓）"""
        icon = QIcon()

        for size in (48, 32, 24, 16):
            pixmap = QPixmap(size, size)
            pixmap.fill(QColor(0, 0, 0, 0))
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setRenderHint(QPainter.SmoothPixmapTransform)

            s = size  # shorthand
            m = max(1, s // 16)  # outer margin
            inner = s - 2 * m

            # ── 背景：蓝色圆角方块 ──
            painter.setBrush(QColor("#0078D4"))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(m, m, inner, inner, inner // 4, inner // 4)

            # ── 顶部高光（2px 浅色渐变条） ──
            highlight = QColor(255, 255, 255, 40)
            painter.setBrush(highlight)
            painter.drawRoundedRect(m, m, inner, inner // 3, inner // 4, inner // 4)
            painter.drawRect(m, m + inner // 6, inner, inner // 6)

            if s >= 24:
                # ── 剪切板纸张 ──
                pm = s // 4          # paper margin ≈ 8@32, 6@24
                pw = s - 2 * pm - 1  # paper width
                ph = pw + 2          # paper height (slightly taller)
                px = pm
                py = pm + 1
                radius = max(1, s // 10)
                painter.setBrush(QColor(255, 255, 255, 235))
                painter.drawRoundedRect(px, py, pw, ph, radius, radius)

                # ── 回形针 ──
                cw = max(3, s // 8)     # clip width
                ch = max(2, s // 6)     # clip height
                cx = (s - cw) // 2
                cy = py - 1
                painter.setBrush(QColor("#0078D4"))
                painter.drawRoundedRect(cx, cy, cw, ch, 1, 1)

                # ── 勾号 ✓（蓝色） ──
                pen = QPen(QColor("#0078D4"), max(1.5, s / 11))
                pen.setCapStyle(Qt.RoundCap)
                pen.setJoinStyle(Qt.RoundJoin)
                painter.setPen(pen)

                left_x = px + pw * 0.18
                mid_x = px + pw * 0.48
                mid_y = py + ph * 0.62
                right_x = px + pw * 0.82
                top_y = py + ph * 0.28

                path = QPainterPath()
                path.moveTo(left_x, mid_y)
                path.lineTo(mid_x, py + ph * 0.76)
                path.lineTo(right_x, top_y)
                painter.strokePath(path, pen)
            else:
                # ── 小尺寸（16px）：简洁白色勾号 ──
                pen = QPen(QColor(255, 255, 255, 240), 2.0)
                pen.setCapStyle(Qt.RoundCap)
                pen.setJoinStyle(Qt.RoundJoin)
                painter.setPen(pen)

                path = QPainterPath()
                path.moveTo(s * 0.25, s * 0.52)
                path.lineTo(s * 0.44, s * 0.70)
                path.lineTo(s * 0.75, s * 0.35)
                painter.strokePath(path, pen)

            painter.end()
            icon.addPixmap(pixmap)

        return icon
