"""
无边框主窗口

功能：
- 无边框、始终置顶、可拖拽
- 折叠/展开双模式切换（带动画）
- 自动吸附屏幕边缘
- 位置持久化（QSettings）
- 贴顶隐藏：拖拽到屏幕顶部自动收起，鼠标靠近后恢复
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QPropertyAnimation, QRect, QEasingCurve, Signal, QPoint, QSize, QSettings, QTimer, QEvent
from PySide6.QtWidgets import QWidget, QVBoxLayout, QStackedWidget, QApplication
from PySide6.QtGui import QMouseEvent, QScreen, QCursor

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
        # 透明背景：桌宠形态透明浮于桌面（展开面板自带背景色，不受影响）
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        # ── 状态 ──────────────────────────────────────────
        self._mode = "collapsed"  # "collapsed" | "expanded"
        self._drag_pos = QPoint()
        self._is_dragging = False
        self._animation_running = False

        # ── 贴顶隐藏状态 ──────────────────────────────────
        self._stuck_to_top = False         # 是否处于贴顶模式
        self._temporarily_visible = False  # 贴顶模式下是否临时展开
        self._show_pending = False         # 是否有待执行的展开
        self._restore_rect = QRect()       # 贴顶前的位置
        self._stuck_screen_geo = QRect()   # 贴顶时的屏幕信息
        self._stick_hover_timer = QTimer()
        self._stick_hover_timer.setInterval(100)
        self._stick_hover_timer.timeout.connect(self._on_stick_hover_check)
        self._hide_timer = QTimer()
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setInterval(AppConfig.STICK_HIDE_DELAY_MS)
        self._hide_timer.timeout.connect(self._do_hide)

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

        # ── 应用全局样式 + 注册主题监听 ──────────────────
        self.setStyleSheet(AppTheme.global_qss())
        AppTheme.register(lambda: self.setStyleSheet(AppTheme.global_qss()))

        # ── 默认尺寸 ──────────────────────────────────────
        self._collapsed_size = QSize(AppConfig.PET_WIDTH, AppConfig.PET_HEIGHT)
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

    def _set_pet_idle(self, active: bool) -> None:
        """启停桌宠空闲动画（贴顶/拖拽/展开时停止，避免互相干扰）"""
        view = self._collapsed_view
        if view is None or self._mode != "collapsed":
            return
        handler = getattr(view, "start_idle" if active else "stop_idle", None)
        if handler is None:
            return
        if active and not self._animation_running:
            handler()
        elif not active:
            handler()

    def start_collapsed_idle(self) -> None:
        """启动折叠态空闲动画（应用启动后由控制器调用一次）"""
        self._set_pet_idle(True)

    def expand(self) -> None:
        """展开为完整列表"""
        if self._mode == "expanded" or self._animation_running:
            return
        self._set_pet_idle(False)
        if self._stuck_to_top:
            self._full_unstick()
            self.move(self._restore_rect.topLeft())
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
        if self._stuck_to_top:
            self._full_unstick()
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
            self._set_pet_idle(False)
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._is_dragging = True
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._is_dragging and event.buttons() == Qt.LeftButton:
            if self._stuck_to_top:
                self._full_unstick()
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self._is_dragging = False
            if not self._check_and_stick_to_top():
                self._snap_to_screen_edge()
                self._save_position()
                self._set_pet_idle(True)
            event.accept()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        # 双击切换模式的功能已由具体视图（CollapsedView / 标题栏）各自处理
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
            self._set_pet_idle(True)
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

    def _current_screen(self) -> QScreen | None:
        """获取窗口当前所在屏幕（而非 primaryScreen）"""
        screen = QApplication.screenAt(self.geometry().center())
        if screen is None:
            # fallback：遍历所有屏幕
            for s in QApplication.screens():
                if s.geometry().intersects(self.geometry()):
                    return s
            screen = QApplication.primaryScreen()
        return screen

    def _snap_to_screen_edge(self) -> None:
        """确保窗口不超出当前屏幕边界（支持多显示器）"""
        screen = self._current_screen()
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

    # ── 贴顶隐藏 ──────────────────────────────────────────

    def _check_and_stick_to_top(self) -> bool:
        """检查窗口是否靠近屏幕顶部边缘，是则贴顶隐藏"""
        screen = self._current_screen()
        if not screen:
            return False
        geo = screen.availableGeometry()
        if self.pos().y() <= geo.top() + AppConfig.STICK_TO_TOP_THRESHOLD:
            self._stick_to_top()
            return True
        return False

    def _stick_to_top(self) -> None:
        """贴顶部并隐藏（只露出底部一小条）"""
        if self._stuck_to_top:
            return
        screen = self._current_screen()
        if not screen:
            return
        geo = screen.availableGeometry()
        # 保存恢复位置，y 距屏幕顶部留出间隙确保标题栏完整可见
        restore_y = max(self.y(), geo.top() + AppConfig.STICK_RESTORE_Y_MARGIN)
        self._restore_rect = QRect(self.x(), restore_y, self.width(), self.height())
        self._stuck_screen_geo = geo
        self._stuck_to_top = True
        self._temporarily_visible = False
        self._set_pet_idle(False)

        new_y = geo.top() - self.height() + AppConfig.STICK_TO_TOP_PEEK_HEIGHT
        x = max(geo.left(), min(self.x(), geo.right() - self.width()))
        self.move(x, new_y)

        self._stick_hover_timer.start()

    def _full_unstick(self) -> None:
        """彻底取消贴顶隐藏（不移动窗口），拖拽时调用"""
        if not self._stuck_to_top:
            return
        self._stuck_to_top = False
        self._temporarily_visible = False
        self._show_pending = False
        self._stick_hover_timer.stop()
        self._hide_timer.stop()

    def _temporarily_show(self) -> None:
        """临时展开窗口（鼠标悬停触发，离开后再次隐藏）"""
        if not self._stuck_to_top or self._temporarily_visible:
            return
        self._temporarily_visible = True
        self.move(self._restore_rect.topLeft())
        self._set_pet_idle(True)

    def _schedule_hide(self) -> None:
        """安排隐藏计时（鼠标离开窗口时调用）"""
        if self._stuck_to_top and self._temporarily_visible:
            self._hide_timer.start()

    def _cancel_hide(self) -> None:
        """取消待处理的隐藏"""
        self._hide_timer.stop()

    def _do_hide(self) -> None:
        """执行隐藏回顶部"""
        if not self._stuck_to_top or not self._temporarily_visible:
            return
        self._temporarily_visible = False
        self._set_pet_idle(False)
        geo = self._stuck_screen_geo
        restore_pos = self._restore_rect.topLeft()
        new_y = geo.top() - self._restore_rect.height() + AppConfig.STICK_TO_TOP_PEEK_HEIGHT
        self.move(restore_pos.x(), new_y)

    def _on_stick_hover_check(self) -> None:
        """定时检测鼠标位置，管理隐藏/展开状态"""
        if not self._stuck_to_top or not self.isVisible():
            return

        cursor = QCursor.pos()
        geo = self._stuck_screen_geo

        if self._temporarily_visible:
            # 临时展开状态：鼠标是否仍在窗口区域内
            win_rect = QRect(self._restore_rect.topLeft(), self._restore_rect.size())
            if win_rect.contains(cursor):
                self._cancel_hide()
            else:
                self._schedule_hide()
        else:
            # 隐藏状态：鼠标是否进入顶部热区（延迟展开，避免误触）
            if self._is_in_hot_zone(cursor, geo):
                if not self._show_pending:
                    self._show_pending = True
                    QTimer.singleShot(AppConfig.STICK_HOVER_DELAY_MS, self._do_show)
            else:
                self._show_pending = False

    def _is_in_hot_zone(self, cursor: QPoint, geo: QRect) -> bool:
        """判断鼠标是否在屏幕顶部热区内"""
        hot_zone_max_y = geo.top() + AppConfig.STICK_TO_TOP_PEEK_HEIGHT + 20
        return (geo.top() - 5 <= cursor.y() <= hot_zone_max_y and
                geo.left() <= cursor.x() <= geo.right())

    def _do_show(self) -> None:
        """延迟后执行展开（由定时器触发）"""
        self._show_pending = False
        if not self._stuck_to_top or self._temporarily_visible:
            return
        cursor = QCursor.pos()
        if self._is_in_hot_zone(cursor, self._stuck_screen_geo):
            self._temporarily_show()

    def enterEvent(self, event: QEvent) -> None:
        """鼠标进入窗口可见区域时临时展开"""
        if self._stuck_to_top and not self._temporarily_visible:
            if not self._show_pending:
                self._show_pending = True
                QTimer.singleShot(AppConfig.STICK_HOVER_DELAY_MS, self._do_show)
        elif self._stuck_to_top and self._temporarily_visible:
            self._cancel_hide()
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        """鼠标离开窗口时安排隐藏"""
        if self._stuck_to_top and self._temporarily_visible:
            self._schedule_hide()
        elif self._stuck_to_top and not self._temporarily_visible:
            self._show_pending = False
        super().leaveEvent(event)

    def ensure_visible(self) -> None:
        """确保窗口可见（若处于贴顶隐藏则彻底恢复）"""
        if self._stuck_to_top:
            self._full_unstick()
            self.move(self._restore_rect.topLeft())
        self._set_pet_idle(True)

    def set_opacity(self, value: float) -> None:
        """设置窗口透明度 (0.0 ~ 1.0)"""
        self.setWindowOpacity(value)

    def closeEvent(self, event):
        if self._stuck_to_top:
            settings = QSettings("Personal", "待办事项和便签")
            settings.setValue("window/pos", self._restore_rect.topLeft())
            self._full_unstick()
        else:
            self._save_position()
        self.signal_close_requested.emit()
        event.ignore()  # 不真正关闭，由控制器处理
