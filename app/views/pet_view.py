"""
桌宠视图（折叠模式）

折叠后窗口变为桌面宠物形象：
- PNG/JPG/GIF 素材（内置 resources/pets + 用户 data/pets，用户目录优先）
- 白底素材自动去除背景（floodfill 边缘连通白色，内部白色保留），结果缓存
- 程序驱动空闲动画：漂浮 + 呼吸 + 随机小动作（歪头/跳跃）+ 悬停弹跳
- 右上角待办计数角标
- 单击展开，右键菜单（展开 / 快速添加 / 置顶 / 退出）
"""

from __future__ import annotations

import logging
import random
import zlib
from pathlib import Path

from PySide6.QtCore import (
    Property,
    QAbstractAnimation,
    QEasingCurve,
    QEvent,
    QPoint,
    QPropertyAnimation,
    QSequentialAnimationGroup,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QMouseEvent,
    QMovie,
    QPainter,
    QPixmap,
)
from PySide6.QtWidgets import (
    QLabel,
    QMenu,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.config import AppConfig
from app.views.theme import AppTheme

logger = logging.getLogger(__name__)

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif"}
_MAGIC_BG = (255, 0, 255)  # floodfill 标记背景用的品红色


def discover_pets() -> list[dict]:
    """扫描内置 + 用户桌宠素材，返回 [{id, name, path}]（用户目录优先）"""
    found: dict[str, Path] = {}

    def _scan(directory: Path) -> None:
        try:
            for f in sorted(directory.iterdir()):
                if f.is_file() and f.suffix.lower() in _IMAGE_EXTS:
                    found[f.stem] = f
        except OSError as e:
            logger.warning("扫描桌宠素材失败 %s: %s", directory, e)

    _scan(AppConfig.resource_path("app/resources/pets"))
    _scan(AppConfig.pets_dir())

    result = []
    for pet_id, path in found.items():
        result.append({"id": pet_id, "name": pet_id, "path": path})
    return result


def ensure_transparent(src: Path) -> Path:
    """确保素材有透明背景；无透明的 JPG/PNG 自动去白底并缓存。

    返回可直接加载的图片路径（原图或缓存 PNG）。
    算法：从四边种子点 floodfill 把连通到边缘的白色背景标记为透明，
    内部不连通的白色（衣服/高光等）不受影响。
    """
    from PIL import Image, ImageChops, ImageDraw

    try:
        img = Image.open(src)
    except Exception as e:
        logger.warning("桌宠素材打开失败 %s: %s", src, e)
        return src

    # 已有真实透明像素 → 直接用原图
    if img.mode in ("RGBA", "LA", "PA"):
        lo, _hi = img.convert("RGBA").getchannel("A").getextrema()
        if lo < 250:
            return src

    # 缓存命中（比源文件新）→ 直接用
    cache_dir = AppConfig.pets_dir() / "_processed"
    cache = cache_dir / (_cache_key(src) + ".png")
    try:
        if cache.exists() and cache.stat().st_mtime >= src.stat().st_mtime:
            return cache
    except OSError:
        pass

    try:
        img = img.convert("RGB")
        img.thumbnail(
            (AppConfig.PET_PROCESSED_SIZE, AppConfig.PET_PROCESSED_SIZE),
            Image.LANCZOS)
        w, h = img.size

        # 1) 从四边种子点把连通白色背景 floodfill 成品红
        def _near_white(pixel) -> bool:
            return all(c >= AppConfig.PET_WHITE_SEED_THRESHOLD for c in pixel[:3])

        step = 8
        seeds = (
            [(x, 0) for x in range(0, w, step)]
            + [(x, h - 1) for x in range(0, w, step)]
            + [(0, y) for y in range(0, h, step)]
            + [(w - 1, y) for y in range(0, h, step)]
        )
        for seed in seeds:
            p = img.getpixel(seed)
            if p == _MAGIC_BG or not _near_white(p):
                continue
            ImageDraw.floodfill(
                img, seed, _MAGIC_BG, thresh=AppConfig.PET_WHITE_FLOOD_THRESH)

        # 2) 品红区域 → alpha 0，其余 alpha 255
        magic_img = Image.new("RGB", img.size, _MAGIC_BG)
        diff = ImageChops.difference(img, magic_img).convert("L")
        alpha = diff.point(lambda v: 255 if v > 10 else 0)
        out = img.convert("RGBA")
        out.putalpha(alpha)

        cache_dir.mkdir(parents=True, exist_ok=True)
        out.save(cache, "PNG")
        return cache
    except Exception as e:
        logger.warning("桌宠去白底失败 %s: %s", src, e)
        return src


def _cache_key(src: Path) -> str:
    """去白底缓存键：素材名 + 来源目录指纹（crc32） + 扩展名

    仅用 stem 会让内置/用户目录的同名素材、同目录下同名不同扩展名的文件
    共享同一缓存条目而互相覆盖（mtime 比对的也是另一个源文件）。
    """
    digest = zlib.crc32(str(src.resolve()).encode("utf-8"))
    return f"{src.stem}_{digest:08x}{src.suffix[1:]}"


class PetCanvas(QWidget):
    """桌宠绘制画布（自绘 pixmap，支持平移/缩放/旋转属性动画）"""

    def __init__(self, base_size: int, parent=None):
        super().__init__(parent)
        self._base = base_size
        self._pixmap: QPixmap | None = None
        self._movie: QMovie | None = None
        self._offset_y = 0.0
        self._scale = 1.0
        self._angle = 0.0
        self.setAttribute(Qt.WA_TranslucentBackground, True)

    # ── Qt 属性（动画驱动） ─────────────────────────────────

    def _get_offset_y(self) -> float:
        return self._offset_y

    def _set_offset_y(self, value: float) -> None:
        self._offset_y = value
        self.update()

    offsetY = Property(float, _get_offset_y, _set_offset_y)

    def _get_scale(self) -> float:
        return self._scale

    def _set_scale(self, value: float) -> None:
        self._scale = value
        self.update()

    scale = Property(float, _get_scale, _set_scale)

    def _get_angle(self) -> float:
        return self._angle

    def _set_angle(self, value: float) -> None:
        self._angle = value
        self.update()

    angle = Property(float, _get_angle, _set_angle)

    # ── 内容 ──────────────────────────────────────────────────

    def set_pixmap(self, pixmap: QPixmap) -> None:
        """设置静态图片（预缩放到绘制基准尺寸）"""
        self._movie = None
        self._pixmap = pixmap.scaled(
            self._base, self._base, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.update()

    def set_movie(self, movie: QMovie) -> None:
        """设置 GIF 动画（帧变化时触发重绘）"""
        self._pixmap = None
        self._movie = movie
        movie.setScaledSize(QSize(self._base, self._base))
        movie.frameChanged.connect(self.update)
        self.update()

    def clear_content(self) -> None:
        """清空内容引用（QMovie 的停止与销毁由持有方负责）

        必须在持有方 deleteLater QMovie 之前调用：否则画布仍持有
        已销毁的 C++ 对象，后续 paintEvent → current_pixmap() 会抛 RuntimeError。
        """
        self._movie = None
        self._pixmap = None
        self.update()

    def current_pixmap(self) -> QPixmap | None:
        """当前应显示的图片（静态帧或 GIF 当前帧）"""
        try:
            if self._movie is not None:
                return self._movie.currentPixmap()
        except RuntimeError:
            # 悬空 QMovie 兜底（正常流程已由 clear_content 规避）
            self._movie = None
        return self._pixmap

    def reset_transform(self) -> None:
        """复位所有变换（停止动画后调用）"""
        self._offset_y = 0.0
        self._scale = 1.0
        self._angle = 0.0
        self.update()

    def paintEvent(self, event) -> None:
        pixmap = self.current_pixmap()
        if pixmap is None or pixmap.isNull():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.translate(
            self.width() / 2, self.height() / 2 + self._offset_y)
        painter.rotate(self._angle)
        painter.scale(self._scale, self._scale)
        painter.drawPixmap(
            int(-pixmap.width() / 2), int(-pixmap.height() / 2), pixmap)
        painter.end()


class PetView(QWidget):
    """桌宠视图（替代原折叠条）"""

    signal_expand_clicked = Signal()
    signal_quick_add_clicked = Signal()
    signal_toggle_pin = Signal()  # 置顶切换（无参数，控制器管理状态）
    signal_quit_requested = Signal()  # 退出应用
    signal_animation_toggled = Signal(bool)  # 空闲动画启用状态

    def __init__(self, parent=None):
        super().__init__(parent)

        self._pinned = True
        self._pet_id: str | None = None
        self._movie: QMovie | None = None
        self._press_global = QPoint()
        self._pressed = False
        self._count = 0
        self._animations_enabled = True  # 空闲动画总开关（右键菜单控制）

        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        # ── 桌宠画布（自绘，支持变换动画） ────────────────────
        self._float_delta = AppConfig.PET_FLOAT_DELTA
        self._label_base = AppConfig.PET_WIDTH - 2 * AppConfig.PET_CANVAS_MARGIN
        self._pet_canvas = PetCanvas(self._label_base, self)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._pet_canvas)

        # ── 计数角标（右上角，不随动画移动） ────────────────
        self._badge = QLabel(self)
        self._badge.setFixedHeight(AppConfig.PET_BADGE_SIZE)
        self._badge.setAlignment(Qt.AlignCenter)
        self._badge.hide()

        # ── 空闲动画 ────────────────────────────────────────
        self._active_action: QSequentialAnimationGroup | None = None
        self._hover_anim: QSequentialAnimationGroup | None = None
        self._action_timer = QTimer(self)
        self._action_timer.setSingleShot(True)
        self._action_timer.timeout.connect(self._do_random_action)
        self._build_idle_animations()

        # ── 右键菜单 ────────────────────────────────────────
        self._context_menu = QMenu(self)
        self._context_menu.setStyleSheet(AppTheme.menu_style())
        self._act_expand = QAction("展开", self._context_menu)
        self._act_quick_add = QAction("快速添加", self._context_menu)
        self._act_pin = QAction("", self._context_menu)
        self._act_quit = QAction("退出", self._context_menu)
        self._act_animation = QAction("暂停动画", self._context_menu)
        self._act_animation.setCheckable(True)
        self._context_menu.addAction(self._act_expand)
        self._context_menu.addAction(self._act_quick_add)
        self._context_menu.addSeparator()
        self._context_menu.addAction(self._act_pin)
        self._context_menu.addSeparator()
        self._context_menu.addAction(self._act_animation)
        self._context_menu.addAction(self._act_quit)
        self._act_expand.triggered.connect(self.signal_expand_clicked.emit)
        self._act_quick_add.triggered.connect(self.signal_quick_add_clicked.emit)
        self._act_pin.triggered.connect(self.signal_toggle_pin.emit)
        self._act_quit.triggered.connect(self.signal_quit_requested.emit)
        self._act_animation.toggled.connect(self._on_animation_toggled)

        AppTheme.register(self.reapply_theme)

    # ── 空闲动画 ────────────────────────────────────────────

    def _build_idle_animations(self) -> None:
        """漂浮（offsetY 往返）+ 呼吸（scale 往返），start 衔接前段 end 避免跳变"""
        self._float_anim = QSequentialAnimationGroup(self)
        points = (0.0, float(self._float_delta), 0.0,
                  float(-self._float_delta), 0.0)
        for i in range(len(points) - 1):
            anim = QPropertyAnimation(self._pet_canvas, b"offsetY", self)
            anim.setDuration(AppConfig.PET_FLOAT_MS)
            anim.setStartValue(points[i])
            anim.setEndValue(points[i + 1])
            anim.setEasingCurve(QEasingCurve.InOutSine)
            self._float_anim.addAnimation(anim)
        self._float_anim.setLoopCount(-1)

        grow = 1.0 + AppConfig.PET_BREATH_RATIO
        self._breath_anim = QSequentialAnimationGroup(self)
        for start, end in ((1.0, grow), (grow, 1.0)):
            anim = QPropertyAnimation(self._pet_canvas, b"scale", self)
            anim.setDuration(AppConfig.PET_BREATH_MS)
            anim.setStartValue(start)
            anim.setEndValue(end)
            anim.setEasingCurve(QEasingCurve.InOutSine)
            self._breath_anim.addAnimation(anim)
        self._breath_anim.setLoopCount(-1)

    def _make_tilt_action(self) -> QSequentialAnimationGroup:
        """歪头：左右轻倾后回正"""
        group = QSequentialAnimationGroup(self)
        for start, end, dur in ((0.0, 8.0, 260), (8.0, -6.0, 320), (-6.0, 0.0, 300)):
            anim = QPropertyAnimation(self._pet_canvas, b"angle", self)
            anim.setDuration(dur)
            anim.setStartValue(start)
            anim.setEndValue(end)
            anim.setEasingCurve(QEasingCurve.InOutSine)
            group.addAnimation(anim)
        return group

    def _make_jump_action(self) -> QSequentialAnimationGroup:
        """跳一跳：快速弹起后落地"""
        group = QSequentialAnimationGroup(self)
        anim_up = QPropertyAnimation(self._pet_canvas, b"offsetY", self)
        anim_up.setDuration(220)
        anim_up.setStartValue(0.0)
        anim_up.setEndValue(float(-AppConfig.PET_JUMP_HEIGHT))
        anim_up.setEasingCurve(QEasingCurve.OutCubic)
        anim_down = QPropertyAnimation(self._pet_canvas, b"offsetY", self)
        anim_down.setDuration(260)
        anim_down.setStartValue(float(-AppConfig.PET_JUMP_HEIGHT))
        anim_down.setEndValue(0.0)
        anim_down.setEasingCurve(QEasingCurve.InCubic)
        group.addAnimation(anim_up)
        group.addAnimation(anim_down)
        return group

    def _schedule_random_action(self) -> None:
        """安排下一次随机小动作"""
        self._action_timer.start(random.randint(
            AppConfig.PET_IDLE_ACTION_MIN_MS, AppConfig.PET_IDLE_ACTION_MAX_MS))

    def _do_random_action(self) -> None:
        """随机执行歪头或跳跃（与漂浮互斥：offsetY 冲突时暂停漂浮）"""
        if self._active_action is not None:
            self._schedule_random_action()
            return
        if random.random() < 0.5:
            self._active_action = self._make_tilt_action()
        else:
            self._active_action = self._make_jump_action()
            self._float_anim.pause()  # 跳跃占用 offsetY
        self._active_action.finished.connect(self._on_action_finished)
        self._active_action.start()

    def _on_action_finished(self) -> None:
        """小动作结束：恢复漂浮，安排下一次"""
        self._float_anim.resume()
        self._active_action = None
        self._schedule_random_action()

    # ── 悬停反馈 ────────────────────────────────────────────

    def enterEvent(self, event: QEvent) -> None:
        """鼠标悬停时弹跳一下（暂停呼吸避免 scale 争抢）"""
        if self._hover_anim is None or \
                self._hover_anim.state() != QAbstractAnimation.Running:
            self._breath_anim.pause()
            group = QSequentialAnimationGroup(self)
            for start, end, dur in ((1.0, 1.12, 160), (1.12, 1.0, 200)):
                anim = QPropertyAnimation(self._pet_canvas, b"scale", self)
                anim.setDuration(dur)
                anim.setStartValue(start)
                anim.setEndValue(end)
                anim.setEasingCurve(QEasingCurve.OutCubic)
                group.addAnimation(anim)
            group.finished.connect(self._on_hover_finished)
            self._hover_anim = group
            group.start()
        super().enterEvent(event)

    def _on_hover_finished(self) -> None:
        """悬停弹跳结束：恢复呼吸"""
        self._breath_anim.resume()
        self._hover_anim = None

    # ── 动画总开关 ──────────────────────────────────────────

    def set_animation_enabled(self, enabled: bool) -> None:
        """设置空闲动画开关（由控制器恢复持久化状态 / 菜单切换时调用）"""
        self._animations_enabled = enabled
        self._act_animation.setChecked(not enabled)  # 勾选 = 暂停
        if not enabled:
            self.stop_idle()

    def _on_animation_toggled(self, paused: bool) -> None:
        """右键菜单"暂停动画"勾选变化"""
        self.set_animation_enabled(not paused)
        self.signal_animation_toggled.emit(not paused)

    def start_idle(self) -> None:
        """开始空闲动画（折叠态展示时调用；开关关闭时忽略）"""
        if not self._animations_enabled:
            return
        self._float_anim.start()
        self._breath_anim.start()
        self._schedule_random_action()

    def stop_idle(self) -> None:
        """停止空闲动画（拖拽 / 贴顶 / 展开时调用）"""
        self._float_anim.stop()
        self._breath_anim.stop()
        self._action_timer.stop()
        if self._active_action is not None:
            self._active_action.stop()
            self._active_action = None
        if self._hover_anim is not None:
            self._hover_anim.stop()
            self._hover_anim = None
        self._pet_canvas.reset_transform()

    # ── 形象加载 ────────────────────────────────────────────

    def pet_id(self) -> str:
        """当前生效的形象 id（素材缺失时回退到第一个可用素材）"""
        return self._pet_id or ""

    def load_pet(self, pet_id: str | None,
                 pets: list[dict] | None = None) -> None:
        """加载指定桌宠形象；失败或缺失时尝试第一个可用素材

        pets：可传入已扫描的素材列表（AppController 启动时已扫描一次），
        避免每次加载都重新遍历磁盘目录。
        """
        if not pet_id:
            pet_id = ""
        self._pet_id = pet_id
        self._clear_movie()

        if pets is None:
            pets = discover_pets()
        pets = {p["id"]: p for p in pets}
        if pet_id not in pets:
            # 兜底：用户选中素材已被删除 → 使用第一个可用素材
            pet_id = next(iter(pets), "") if pets else ""
        self._pet_id = pet_id
        if not pet_id:
            return

        path = Path(pets[pet_id]["path"])
        if path.suffix.lower() == ".gif":
            self._movie = QMovie(str(path), parent=self)
            if self._movie.isValid():
                self._pet_canvas.set_movie(self._movie)
                self._movie.start()
                return
            self._movie.deleteLater()
            self._movie = None

        # 静态图：白底自动去除（JPG / 无透明 PNG）
        load_path = ensure_transparent(path)
        pixmap = QPixmap(str(load_path))
        if pixmap.isNull():
            logger.warning("桌宠素材加载失败: %s", load_path)
            return
        self._pet_canvas.set_pixmap(pixmap)

    def _clear_movie(self) -> None:
        if self._movie:
            # 先让画布放下引用，再销毁 QMovie（否则画布持有悬空 C++ 对象）
            self._pet_canvas.clear_content()
            self._movie.stop()
            self._movie.deleteLater()
            self._movie = None

    # ── 更新 ──────────────────────────────────────────────────

    def update_count(self, count: int) -> None:
        """更新待办计数角标（0 隐藏，99+ 封顶）"""
        self._count = count
        if count <= 0:
            self._badge.hide()
            return
        text = "99+" if count > 99 else str(count)
        self._badge.setText(text)
        self._badge.adjustSize()
        width = max(self._badge.sizeHint().width(), AppConfig.PET_BADGE_SIZE)
        self._badge.setFixedWidth(width)
        # 右上角定位（相对右上角微偏移）
        self._badge.move(
            self.width() - width - 6,
            6,
        )
        self._badge.show()
        self._badge.raise_()

    def set_pinned(self, pinned: bool) -> None:
        """同步置顶状态（右键菜单文案，由控制器调用）"""
        self._pinned = pinned
        self._act_pin.setText("取消置顶" if pinned else "置顶")
        self._act_pin.setToolTip("点击切换置顶")

    # ── 鼠标交互 ────────────────────────────────────────────

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self._press_global = event.globalPosition().toPoint()
            self._pressed = True
            self._forward_to_window(event)
            event.accept()
        elif event.button() == Qt.RightButton:
            self._context_menu.exec(event.globalPosition().toPoint())
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._pressed and event.buttons() == Qt.LeftButton:
            # 位移超过阈值才视为拖拽并转发（避免单击时的微抖动）
            moved = (event.globalPosition().toPoint() - self._press_global).manhattanLength()
            if moved > AppConfig.PET_CLICK_THRESHOLD:
                self._forward_to_window(event)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton and self._pressed:
            self._pressed = False
            self._forward_to_window(event)
            # 位移小于阈值视为单击 → 展开
            moved = (event.globalPosition().toPoint() - self._press_global).manhattanLength()
            if moved <= AppConfig.PET_CLICK_THRESHOLD:
                self.signal_expand_clicked.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _forward_to_window(self, event: QMouseEvent) -> None:
        """把拖拽事件转发给主窗口（复用贴顶/吸附/位置保存逻辑）"""
        # 注意：PetView 挂在 QStackedWidget 内，parentWidget() 不是主窗口，
        # 必须用 window() 获取顶级窗口（MainWindow）
        window = self.window()
        if window is None or window is self:
            return
        if event.type() == QEvent.Type.MouseButtonPress:
            window.mousePressEvent(event)
        elif event.type() == QEvent.Type.MouseMove:
            window.mouseMoveEvent(event)
        elif event.type() == QEvent.Type.MouseButtonRelease:
            window.mouseReleaseEvent(event)

    # ── 主题重载 ──────────────────────────────────────────────

    def reapply_theme(self) -> None:
        """重新应用当前主题样式（角标颜色 + 右键菜单）"""
        self._badge.setStyleSheet(AppTheme.pet_badge_style())
        self._context_menu.setStyleSheet(AppTheme.menu_style())
        if self._badge.isVisible():
            self.update_count(self._count)
