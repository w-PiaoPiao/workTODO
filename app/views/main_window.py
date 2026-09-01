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

import logging

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QPoint,
    QPropertyAnimation,
    QRect,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QCursor, QMouseEvent, QScreen
from PySide6.QtWidgets import QApplication, QStackedWidget, QVBoxLayout, QWidget

from app.config import AppConfig
from app.views.dock_indicator import DockIndicator
from app.views.theme import AppTheme

logger = logging.getLogger(__name__)


class MainWindow(QWidget):
    """无边框置顶主窗口"""

    # ── 外部信号 ──────────────────────────────────────────
    signal_mode_changed = Signal(str)  # "collapsed" | "expanded"
    signal_close_requested = Signal()
    signal_dock_quit_requested = Signal()  # 贴顶指示条右键"退出"

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
        self._expanding = False  # expand() 约束设置→动画结束期间为 True，屏蔽中间态 resize
        self._expand_anchor = "top_left"  # 最近一次展开的锚点（折叠时反向收缩）

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

        # ── 贴顶隐藏位置提示条 ────────────────────────────
        self._dock_indicator = DockIndicator()
        self._dock_indicator.signal_clicked.connect(self.expand)
        self._dock_indicator.signal_hovered.connect(
            self._on_dock_indicator_hovered)
        self._dock_indicator.signal_expand_clicked.connect(self.expand)
        self._dock_indicator.signal_quit_requested.connect(
            self.signal_dock_quit_requested.emit)

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
        self._expanded_size = self._load_expanded_size()

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
        # 记忆尺寸钳制到当前屏幕（换显示器/改分辨率自适应）
        target = self._effective_expanded_size()
        # 选择展开锚点（右侧/下方受限时锚定对应边缘，向屏幕内侧展开，不瞬移）
        self._expand_anchor = self._choose_expand_anchor(target)
        base_geo = self.geometry()  # 桌宠态矩形（改尺寸约束前记录）
        self._mode = "expanded"
        self._expanding = True  # 屏蔽 setMinimumSize 触发的中间态 resize

        # 先解除固定尺寸，再切换视图，最后动画展开
        self.setFixedSize(QSize(16777215, 16777215))
        self.setMinimumSize(AppConfig.EXPANDED_MIN_WIDTH, AppConfig.EXPANDED_MIN_HEIGHT)
        self.setMaximumSize(AppConfig.EXPANDED_MAX_WIDTH, AppConfig.EXPANDED_MAX_HEIGHT)
        self._stack.setCurrentWidget(self._expanded_view)
        self._animate_size(
            target.width(), target.height(),
            anchor=self._expand_anchor, base_geo=base_geo)
        self.signal_mode_changed.emit("expanded")

    def collapse(self) -> None:
        """折叠为紧凑条"""
        if self._mode == "collapsed" or self._animation_running:
            return
        if self._stuck_to_top:
            self._full_unstick()
        base_geo = self.geometry()  # 面板矩形（改尺寸约束前记录）
        self._mode = "collapsed"

        # 先动画缩小，动画结束后再切换视图并固定尺寸
        self.setMaximumSize(16777215, 16777215)
        self.setMinimumSize(0, 0)
        self.setFixedSize(QSize(16777215, 16777215))
        # 用与展开相同的锚点反向收缩 → 桌宠回到原位，可逆无瞬移
        self._animate_size(
            self._collapsed_size.width(), self._collapsed_size.height(),
            anchor=self._expand_anchor, base_geo=base_geo)
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

    def resizeEvent(self, event) -> None:
        """采集展开态用户调整的尺寸并即时持久化

        守卫排除三类非用户 resize：
        - 折叠态（mode 守卫）；
        - 展开/折叠动画帧（_animation_running）；
        - expand() 约束设置阶段 setMinimumSize 触发的中间态钳制（_expanding）。
        QSettings setValue 为内存缓存惰性落盘，逐次写入开销可接受，
        即时保存可覆盖"调整后直接托盘退出"（quit 不经 closeEvent）等路径。
        """
        if (self._mode == "expanded"
                and not self._animation_running
                and not self._expanding):
            self._expanded_size = self.size()
            AppConfig.settings().setValue("window/expanded_size", self._expanded_size)
        super().resizeEvent(event)

    # ── 键盘事件 ──────────────────────────────────────────

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape and self._mode == "expanded":
            self.collapse()
        else:
            super().keyPressEvent(event)

    # ── 动画 ──────────────────────────────────────────────

    def _animate_size(self, target_w: int, target_h: int,
                      anchor: str = "top_left", base_geo: QRect | None = None) -> None:
        """带动画改变窗口大小，指定固定不动的锚点角。

        base_geo：锚点计算的基准矩形（必须是改尺寸约束前的几何，
        因为 setMinimumSize 等会触发中间态 resize，基于中间态计算会错位）。
        """
        self._animation_running = True
        self.anim = QPropertyAnimation(self, b"geometry")
        self.anim.setDuration(AppConfig.ANIMATION_MS)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)

        base = base_geo if base_geo is not None else self.geometry()
        x, y = base.x(), base.y()
        if anchor in ("top_right", "bottom_right"):
            x = base.x() + base.width() - target_w
        if anchor in ("bottom_left", "bottom_right"):
            y = base.y() + base.height() - target_h
        self.anim.setStartValue(self.geometry())
        self.anim.setEndValue(QRect(x, y, target_w, target_h))
        self.anim.finished.connect(self._on_animation_finished)
        self.anim.start()

    def _on_animation_finished(self) -> None:
        self._animation_running = False
        self._expanding = False

        # 动画结束后，应用尺寸约束
        if self._mode == "collapsed":
            self._stack.setCurrentWidget(self._collapsed_view)
            self.setFixedSize(self._collapsed_size)
            self._set_pet_idle(True)
        # 展开模式不锁固定尺寸，允许用户拖拽缩放

    def _choose_expand_anchor(self, size: QSize) -> str:
        """根据桌宠位置选择展开锚点，保证面板完整可见且不瞬移。

        - 默认左上：向右下展开
        - 右侧受限：锚定右上角，向左下展开
        - 下方受限：锚定左下角，向右上展开
        - 双侧受限：锚定右下角，向左上展开
        """
        screen = self._current_screen()
        if not screen:
            return "top_left"
        geo = screen.availableGeometry()
        margin = AppConfig.SCREEN_MARGIN
        w, h = size.width(), size.height()

        over_right = self.x() + w > geo.right() - margin
        over_bottom = self.y() + h > geo.bottom() - margin
        if over_right and over_bottom:
            return "bottom_right"
        if over_right:
            return "top_right"
        if over_bottom:
            return "bottom_left"
        return "top_left"

    # ── 窗口管理 ──────────────────────────────────────────

    def _apply_collapsed_size(self) -> None:
        self.setFixedSize(self._collapsed_size)

    # ── 展开尺寸记忆 ──────────────────────────────────────

    def _load_expanded_size(self) -> QSize:
        """读取上次用户调整的展开尺寸；无记录/非法值回退默认尺寸

        与 window/pos 同模式：isinstance 校验 + 配置上下限钳制，
        防 QSettings 残留异常值或版本间配置变更。
        """
        settings = AppConfig.settings()
        size = settings.value("window/expanded_size")
        if isinstance(size, QSize):
            w = max(AppConfig.EXPANDED_MIN_WIDTH,
                    min(size.width(), AppConfig.EXPANDED_MAX_WIDTH))
            h = max(AppConfig.EXPANDED_MIN_HEIGHT,
                    min(size.height(), AppConfig.EXPANDED_MAX_HEIGHT))
            return QSize(w, h)
        return QSize(AppConfig.EXPANDED_WIDTH, AppConfig.EXPANDED_HEIGHT)

    def _effective_expanded_size(self) -> QSize:
        """本次展开实际使用的尺寸：记忆值钳制到当前屏幕可用区域与配置上下限"""
        w = self._expanded_size.width()
        h = self._expanded_size.height()
        screen = self._current_screen()
        if screen:
            geo = screen.availableGeometry()
            margin = AppConfig.SCREEN_MARGIN
            w = min(w, geo.width() - margin * 2)
            h = min(h, geo.height() - margin * 2)
        w = max(AppConfig.EXPANDED_MIN_WIDTH, min(w, AppConfig.EXPANDED_MAX_WIDTH))
        h = max(AppConfig.EXPANDED_MIN_HEIGHT, min(h, AppConfig.EXPANDED_MAX_HEIGHT))
        return QSize(w, h)

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
        settings = AppConfig.settings()
        settings.setValue("window/pos", self.pos())

    def _restore_position(self) -> bool:
        """从 QSettings 恢复窗口位置，成功返回 True

        校验恢复位置在屏幕范围内：换显示器/改分辨率/QSettings 残留异常坐标时，
        小窗口可能整体落在屏幕外，而托盘"显示"只 raise 不重定位、
        贴顶指示条也不可用——用户将找不到任何入口找回窗口。
        无效时回退默认位置（由调用方处理）。
        """
        settings = AppConfig.settings()
        pos = settings.value("window/pos")
        if pos is not None and isinstance(pos, QPoint):
            self.move(pos)
            if QApplication.screenAt(self.geometry().center()) is not None:
                return True
            logger.warning("恢复的窗口位置超出屏幕范围，回退默认位置: %s", pos)
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

        self._sync_dock_indicator()
        self._maybe_show_stick_tip()

    def _full_unstick(self) -> None:
        """彻底取消贴顶隐藏（不移动窗口），拖拽时调用"""
        if not self._stuck_to_top:
            return
        self._stuck_to_top = False
        self._temporarily_visible = False
        self._show_pending = False
        self._stick_hover_timer.stop()
        self._hide_timer.stop()
        self._sync_dock_indicator()

    # ── 贴顶提示条 ────────────────────────────────────────

    def _sync_dock_indicator(self) -> None:
        """按当前状态同步贴顶指示条：贴顶隐藏时显示，其余状态隐藏

        显示条件 = 应用可见 且 处于贴顶 且 未临时唤出。
        """
        visible = (self.isVisible() and self._stuck_to_top
                   and not self._temporarily_visible)
        self._dock_indicator.setVisible(visible)
        if visible:
            self._dock_indicator.setWindowOpacity(self.windowOpacity())
            self._dock_indicator.position_at(
                self._stuck_screen_geo, self.x(), self.width())
            self._dock_indicator.raise_()
            self._dock_indicator.start_pulse()

    def _on_dock_indicator_hovered(self) -> None:
        """鼠标进入提示条 → 临时唤出桌宠（复用顶部热区机制）"""
        if self._stuck_to_top and not self._temporarily_visible:
            self._temporarily_show()
            self._sync_dock_indicator()

    def _maybe_show_stick_tip(self) -> None:
        """首次贴顶隐藏时用 tooltip 提示找回方式（一次性，QSettings 去重）"""
        settings = AppConfig.settings()
        key = "notify/stick_tip_shown"
        if settings.value(key, False, type=bool):
            return
        settings.setValue(key, True)
        try:
            from app.views.custom_tooltip import CustomTooltip
            pos = self._dock_indicator.pos() + self._dock_indicator.rect().bottomLeft()
            CustomTooltip().show_tip(
                "桌宠已贴顶隐藏 · 鼠标移到屏幕顶部或点击下方指示条即可展开",
                pos=pos, timeout_ms=4000)
        except Exception as e:  # 提示失败不影响功能
            logger.warning("贴顶提示 tooltip 显示失败: %s", e)

    def _temporarily_show(self) -> None:
        """临时展开窗口（鼠标悬停触发，离开后再次隐藏）"""
        if not self._stuck_to_top or self._temporarily_visible:
            return
        self._temporarily_visible = True
        self.move(self._restore_rect.topLeft())
        self._set_pet_idle(True)
        self._sync_dock_indicator()

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
        self._sync_dock_indicator()

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

    def update_dock_count(self, count: int) -> None:
        """把待办计数转发到贴顶指示条角标（控制器刷新视图时调用）"""
        self._dock_indicator.set_count(count)

    def set_opacity(self, value: float) -> None:
        """设置窗口透明度 (0.0 ~ 1.0)，同步到贴顶指示条保持一致"""
        self.setWindowOpacity(value)
        self._dock_indicator.setWindowOpacity(value)

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_dock_indicator()

    def hideEvent(self, event):
        # 最小化到托盘等场景：不残留孤儿提示条
        self._dock_indicator.hide()
        super().hideEvent(event)

    def closeEvent(self, event):
        if self._stuck_to_top:
            settings = AppConfig.settings()
            settings.setValue("window/pos", self._restore_rect.topLeft())
            self._full_unstick()
        else:
            self._save_position()
        self.signal_close_requested.emit()
        event.ignore()  # 不真正关闭，由控制器处理
