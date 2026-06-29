"""
无边框主窗口

功能：
- 无边框、始终置顶、可拖拽
- 折叠/展开双模式切换（带动画）
- 自动吸附屏幕边缘
- 位置持久化（QSettings）
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QPropertyAnimation, QRect, QEasingCurve, Signal, QPoint, QSize, QSettings
from PySide6.QtWidgets import QWidget, QVBoxLayout, QStackedWidget, QApplication
from PySide6.QtGui import QMouseEvent, QScreen

from app.config import AppConfig
from app.views.theme import AppTheme


class MainWindow(QWidget):
    """无边框置顶主窗口"""

    # ── 外部信号 ──────────────────────────────────────────
    signal_mode_changed = Signal(str)  # "collapsed" | "expanded"
    signal_close_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        # ── 窗口标志 ──────────────────────────────────────
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool  # 不在任务栏显示
        )
        self.setAttribute(Qt.WA_ShowWithoutActivating, False)

        # ── 状态 ──────────────────────────────────────────
        self._mode = "collapsed"  # "collapsed" | "expanded"
        self._drag_pos = QPoint()
        self._is_dragging = False
        self._animation_running = False

        # ── 子视图占位（由外部注入）───────────────────────
        self._collapsed_view: QWidget = None
        self._expanded_view: QWidget = None

        # ── UI 搭建 ───────────────────────────────────────
        self._stack = QStackedWidget()
        self._stack.setCurrentIndex(0)

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._stack)
        self.setLayout(layout)

        # ── 应用全局样式 ──────────────────────────────────
        self.setStyleSheet(AppTheme.global_qss())

        # ── 默认尺寸 ──────────────────────────────────────
        self._collapsed_size = QSize(AppConfig.COLLAPSED_WIDTH, AppConfig.COLLAPSED_HEIGHT)
        self._expanded_size = QSize(AppConfig.EXPANDED_WIDTH, AppConfig.EXPANDED_HEIGHT)

        # ── 初始位置（右上角） ────────────────────────────
        self._move_to_default_position()

    # ── 视图注入 ──────────────────────────────────────────

    def set_views(self, collapsed_view: QWidget, expanded_view: QWidget) -> None:
        """设置折叠和展开视图（在创建后调用）"""
        self._collapsed_view = collapsed_view
        self._expanded_view = expanded_view
        self._stack.addWidget(collapsed_view)
        self._stack.addWidget(expanded_view)
        self._apply_collapsed_size()

    # ── 模式切换 ──────────────────────────────────────────

    @property
    def mode(self) -> str:
        return self._mode

    def toggle_mode(self) -> None:
        """切换折叠/展开"""
        if self._animation_running:
            return
        if self._mode == "collapsed":
            self.expand()
        else:
            self.collapse()

    def expand(self) -> None:
        """展开为完整列表"""
        if self._mode == "expanded" or self._animation_running:
            return
        self._mode = "expanded"

        # 先解除固定尺寸，再切换视图，最后动画展开
        self.setFixedSize(QSize(16777215, 16777215))
        self.setMinimumSize(AppConfig.EXPANDED_MIN_WIDTH, AppConfig.EXPANDED_MIN_HEIGHT)
        self.setMaximumSize(AppConfig.EXPANDED_MAX_WIDTH, AppConfig.EXPANDED_MAX_HEIGHT)
        self._stack.setCurrentWidget(self._expanded_view)
        self._animate_size(self._expanded_size.width(), self._expanded_size.height())
        self.signal_mode_changed.emit("expanded")

    def collapse(self) -> None:
        """折叠为紧凑条"""
        if self._mode == "collapsed" or self._animation_running:
            return
        self._mode = "collapsed"

        # 先动画缩小，动画结束后再切换视图并固定尺寸
        self.setMaximumSize(16777215, 16777215)
        self.setMinimumSize(0, 0)
        self.setFixedSize(QSize(16777215, 16777215))
        self._animate_size(self._collapsed_size.width(), self._collapsed_size.height())
        self.signal_mode_changed.emit("collapsed")

    # ── 窗口拖拽 ──────────────────────────────────────────

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._is_dragging = True
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._is_dragging and event.buttons() == Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self._is_dragging = False
            self._snap_to_screen_edge()
            self._save_position()
            event.accept()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        # 双击空白区域切换模式
        self.toggle_mode()
        super().mouseDoubleClickEvent(event)

    # ── 键盘事件 ──────────────────────────────────────────

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape and self._mode == "expanded":
            self.collapse()
        else:
            super().keyPressEvent(event)

    # ── 动画 ──────────────────────────────────────────────

    def _animate_size(self, target_w: int, target_h: int) -> None:
        """带动画改变窗口大小"""
        self._animation_running = True
        self.anim = QPropertyAnimation(self, b"geometry")
        self.anim.setDuration(AppConfig.ANIMATION_MS)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)

        current = self.geometry()
        self.anim.setStartValue(current)
        self.anim.setEndValue(QRect(current.x(), current.y(), target_w, target_h))
        self.anim.finished.connect(self._on_animation_finished)
        self.anim.start()

    def _on_animation_finished(self) -> None:
        self._animation_running = False

        # 动画结束后，应用尺寸约束
        if self._mode == "collapsed":
            self._stack.setCurrentWidget(self._collapsed_view)
            self.setFixedSize(self._collapsed_size)
        # 展开模式不锁固定尺寸，允许用户拖拽缩放

    # ── 窗口管理 ──────────────────────────────────────────

    def _apply_collapsed_size(self) -> None:
        self.setFixedSize(self._collapsed_size)

    def _move_to_default_position(self) -> None:
        """恢复上次位置或置于屏幕右上角"""
        # 先尝试恢复已保存的位置
        if self._restore_position():
            return
        # 无已保存位置 → 默认右上角
        screen = QApplication.primaryScreen()
        if screen:
            geometry = screen.availableGeometry()
            x = geometry.right() - self._collapsed_size.width() - AppConfig.SCREEN_MARGIN
            y = geometry.top() + AppConfig.SCREEN_MARGIN
            self.move(x, y)

    def _save_position(self) -> None:
        """保存窗口位置到 QSettings"""
        settings = QSettings("Personal", "待办事项和便签")
        settings.setValue("window/pos", self.pos())

    def _restore_position(self) -> bool:
        """从 QSettings 恢复窗口位置，成功返回 True"""
        settings = QSettings("Personal", "待办事项和便签")
        pos = settings.value("window/pos")
        if pos is not None and isinstance(pos, QPoint):
            self.move(pos)
            return True
        return False

    def set_always_on_top(self, enabled: bool) -> None:
        """切换窗口是否置顶（通过 QWindow.setFlag 避免窗口重建闪烁）"""
        handle = self.windowHandle()
        if handle:
            handle.setFlag(Qt.WindowStaysOnTopHint, enabled)

    def _snap_to_screen_edge(self) -> None:
        """确保窗口不超出屏幕边界"""
        screen = QApplication.primaryScreen()
        if not screen:
            return
        geo = screen.availableGeometry()
        pos = self.pos()
        w = self.width()
        h = self.height()
        margin = AppConfig.SCREEN_MARGIN

        new_x = max(geo.left() + margin, min(pos.x(), geo.right() - w - margin))
        new_y = max(geo.top() + margin, min(pos.y(), geo.bottom() - h - margin))
        if new_x != pos.x() or new_y != pos.y():
            self.move(new_x, new_y)

    def closeEvent(self, event):
        # 关闭时保存位置
        self._save_position()
        # 发射信号，让控制器决定是退出还是最小化到托盘
        self.signal_close_requested.emit()
        event.ignore()  # 不真正关闭，由控制器处理
