"""桌宠视图测试（offscreen 无头模式）

覆盖：素材发现（内置 + 用户目录优先级）、形象加载、白底去除、
计数角标、拖拽/单击、动画启停与开关、展开锚点（屏幕边缘）。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest
from PySide6.QtCore import QAbstractAnimation, QPoint, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from app.config import AppConfig
from app.views.pet_view import PetView, discover_pets

BUILTIN_PET = "deepseek娘"


@pytest.fixture(scope="module")
def app():
    qapp = QApplication.instance() or QApplication([])
    yield qapp


@pytest.fixture
def user_pets_dir(tmp_path, monkeypatch):
    """把用户素材目录指向 tmp_path，并放入一个自定义素材"""
    monkeypatch.setattr("app.config.AppConfig.DATA_DIR", tmp_path)
    d = tmp_path / "pets"
    d.mkdir(parents=True, exist_ok=True)
    (d / "custom.png").write_bytes(b"not-a-real-image")
    return d


def _all_pet_ids() -> set[str]:
    return {p["id"] for p in discover_pets()}


# ── 素材发现 ────────────────────────────────────────────────


def test_discover_includes_builtin_pet():
    ids = _all_pet_ids()
    assert BUILTIN_PET in ids


def test_discover_includes_user_pets(user_pets_dir):
    ids = _all_pet_ids()
    assert "custom" in ids


def test_builtin_pet_comes_from_resources():
    """deepseek娘 应来自内置 resources 目录"""
    pet = next(p for p in discover_pets() if p["id"] == BUILTIN_PET)
    assert Path(pet["path"]).is_relative_to(
        AppConfig.resource_path("app/resources/pets"))


# ── 形象加载 ────────────────────────────────────────────────


def test_load_pet_pixmap(app, tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.AppConfig.DATA_DIR", tmp_path)
    view = PetView()
    view.load_pet(BUILTIN_PET)
    pixmap = view._pet_canvas.current_pixmap()
    assert pixmap is not None and not pixmap.isNull()


def test_load_missing_pet_falls_back(app, tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.AppConfig.DATA_DIR", tmp_path)
    view = PetView()
    view.load_pet("no_such_pet")
    # 回退到第一个可用素材（内置 deepseek娘）
    assert view.pet_id() == BUILTIN_PET


def test_load_pet_no_pets_available(app, tmp_path, monkeypatch):
    """素材全空时加载不崩溃，pet_id 为空"""
    monkeypatch.setattr("app.config.AppConfig.DATA_DIR", tmp_path)
    monkeypatch.setattr(
        AppConfig, "resource_path",
        classmethod(lambda cls, name: tmp_path / "empty"))
    view = PetView()
    view.load_pet("whatever")
    assert view.pet_id() == ""


# ── 计数角标 / 菜单 ─────────────────────────────────────────


def test_update_count_badge(app, tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.AppConfig.DATA_DIR", tmp_path)
    view = PetView()
    view.resize(AppConfig.PET_WIDTH, AppConfig.PET_HEIGHT)

    view.update_count(0)
    view.show()
    assert not view._badge.isVisible()

    view.update_count(5)
    assert view._badge.isVisible()
    assert view._badge.text() == "5"

    view.update_count(120)
    assert view._badge.text() == "99+"


def test_set_pinned_updates_menu_text(app, tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.AppConfig.DATA_DIR", tmp_path)
    view = PetView()
    view.set_pinned(True)
    assert view._act_pin.text() == "取消置顶"
    view.set_pinned(False)
    assert view._act_pin.text() == "置顶"


# ── 拖拽 / 单击 ─────────────────────────────────────────────


def _mouse_event(type_, local, global_, button=Qt.LeftButton, buttons=Qt.LeftButton):
    return QMouseEvent(
        type_, local, global_, button, buttons, Qt.NoModifier)


def test_drag_moves_window(app, tmp_path, monkeypatch):
    """拖拽事件必须转发到顶级窗口（回归：parentWidget 是 QStackedWidget 的 bug）"""
    monkeypatch.setattr("app.config.AppConfig.DATA_DIR", tmp_path)
    from app.views.main_window import MainWindow

    window = MainWindow()
    pet = PetView()
    window.set_views(pet, pet)  # expanded_view 占位
    window.show()
    app.processEvents()

    start = window.pos()
    pet.mousePressEvent(_mouse_event(
        QMouseEvent.Type.MouseButtonPress, pet.rect().center(), start))
    app.processEvents()
    assert window._is_dragging

    # 移动超过阈值（8px）→ 窗口跟随
    target = start + QPoint(60, 40)
    pet.mouseMoveEvent(_mouse_event(
        QMouseEvent.Type.MouseMove, pet.rect().center() + QPoint(60, 40),
        target))
    app.processEvents()
    assert window.pos() == target

    pet.mouseReleaseEvent(_mouse_event(
        QMouseEvent.Type.MouseButtonRelease, pet.rect().center() + QPoint(60, 40),
        target))
    app.processEvents()
    assert not window._is_dragging
    window.close()
    window.deleteLater()


def test_click_within_threshold_expands_without_moving(app, tmp_path, monkeypatch):
    """单击（位移 ≤8px）触发展开信号且不移动窗口"""
    monkeypatch.setattr("app.config.AppConfig.DATA_DIR", tmp_path)
    from app.views.main_window import MainWindow

    window = MainWindow()
    pet = PetView()
    window.set_views(pet, pet)
    window.show()
    app.processEvents()

    start = window.pos()
    expanded = []
    pet.signal_expand_clicked.connect(lambda: expanded.append(True))

    pet.mousePressEvent(_mouse_event(
        QMouseEvent.Type.MouseButtonPress, pet.rect().center(), start))
    pet.mouseMoveEvent(_mouse_event(
        QMouseEvent.Type.MouseMove, pet.rect().center() + QPoint(3, 2),
        start + QPoint(3, 2)))
    pet.mouseReleaseEvent(_mouse_event(
        QMouseEvent.Type.MouseButtonRelease, pet.rect().center() + QPoint(3, 2),
        start + QPoint(3, 2)))
    app.processEvents()

    assert expanded == [True]
    assert window.pos() == start
    window.close()
    window.deleteLater()


# ── 白底去除 ────────────────────────────────────────────────


def _make_white_bg_jpg(path: Path) -> None:
    """生成测试图：白底 + 蓝色方块（角色）+ 方块内不连通白色小块"""
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (200, 200), (255, 255, 255))
    d = ImageDraw.Draw(img)
    d.rectangle((60, 60, 140, 140), fill=(30, 80, 200))   # 角色主体
    d.rectangle((90, 90, 110, 110), fill=(255, 255, 255))  # 内部白色（不连通边缘）
    img.save(path, "JPEG", quality=95)


def test_ensure_transparent_removes_white_bg(app, tmp_path, monkeypatch):
    """白底自动去除：边缘连通白色 → 透明，内部白色保留"""
    monkeypatch.setattr("app.config.AppConfig.DATA_DIR", tmp_path)
    from PIL import Image

    from app.views.pet_view import ensure_transparent

    src = tmp_path / "pet.jpg"
    _make_white_bg_jpg(src)
    out = ensure_transparent(src)

    assert out != src and out.exists()
    result = Image.open(out).convert("RGBA")
    assert result.getpixel((2, 2))[3] == 0        # 角点背景 → 透明
    assert result.getpixel((100, 75))[3] == 255   # 角色主体 → 不透明
    assert result.getpixel((100, 100))[3] == 255  # 内部白色 → 保留


def test_ensure_transparent_uses_cache(app, tmp_path, monkeypatch):
    """二次调用命中缓存（路径相同且不再重新生成）"""
    monkeypatch.setattr("app.config.AppConfig.DATA_DIR", tmp_path)
    from app.views.pet_view import ensure_transparent

    src = tmp_path / "pet.jpg"
    _make_white_bg_jpg(src)
    first = ensure_transparent(src)
    mtime = first.stat().st_mtime
    second = ensure_transparent(src)
    assert second == first
    assert second.stat().st_mtime == mtime


def test_ensure_transparent_skips_already_transparent(app, tmp_path, monkeypatch):
    """已有透明像素的 PNG 直接返回原路径"""
    monkeypatch.setattr("app.config.AppConfig.DATA_DIR", tmp_path)
    from PIL import Image

    from app.views.pet_view import ensure_transparent

    src = tmp_path / "pet.png"
    img = Image.new("RGBA", (100, 100), (255, 255, 255, 255))
    img.putpixel((0, 0), (0, 0, 0, 0))
    img.save(src)
    assert ensure_transparent(src) == src


def test_load_jpg_pet_gets_transparency(app, tmp_path, monkeypatch):
    """加载 JPG 形象后，画布 pixmap 带透明通道"""
    monkeypatch.setattr("app.config.AppConfig.DATA_DIR", tmp_path)
    pets_dir = AppConfig.pets_dir()
    _make_white_bg_jpg(pets_dir / "whitepet.jpg")

    view = PetView()
    view.load_pet("whitepet")
    assert view.pet_id() == "whitepet"
    pixmap = view._pet_canvas.current_pixmap()
    assert pixmap is not None and pixmap.hasAlphaChannel()


# ── 动画 ────────────────────────────────────────────────────


def test_idle_animations_start_and_stop(app, tmp_path, monkeypatch):
    """空闲动画启停：start 运行、stop 停止且变换复位"""
    monkeypatch.setattr("app.config.AppConfig.DATA_DIR", tmp_path)

    view = PetView()
    view.load_pet(BUILTIN_PET)
    view.start_idle()
    assert view._float_anim.state() == QAbstractAnimation.Running
    assert view._breath_anim.state() == QAbstractAnimation.Running
    assert view._action_timer.isActive()

    view.stop_idle()
    assert view._float_anim.state() == QAbstractAnimation.Stopped
    assert view._breath_anim.state() == QAbstractAnimation.Stopped
    assert not view._action_timer.isActive()
    canvas = view._pet_canvas
    assert canvas._offset_y == 0.0
    assert canvas._scale == 1.0
    assert canvas._angle == 0.0


def test_random_action_runs_without_error(app, tmp_path, monkeypatch):
    """随机小动作可执行且不崩溃（强制触发一次）"""
    monkeypatch.setattr("app.config.AppConfig.DATA_DIR", tmp_path)

    view = PetView()
    view.load_pet(BUILTIN_PET)
    view.start_idle()
    view._do_random_action()
    app.processEvents()
    assert view._active_action is not None
    view.stop_idle()


def test_animation_enabled_toggle(app, tmp_path, monkeypatch):
    """右键菜单暂停动画：开关关闭后 start_idle 被忽略，信号正确发射"""
    monkeypatch.setattr("app.config.AppConfig.DATA_DIR", tmp_path)

    view = PetView()
    view.load_pet(BUILTIN_PET)
    view.start_idle()
    toggles = []
    view.signal_animation_toggled.connect(lambda enabled: toggles.append(enabled))

    # 勾选"暂停动画" → 停掉动画
    view._act_animation.setChecked(True)
    assert not view._animations_enabled
    assert view._float_anim.state() == QAbstractAnimation.Stopped
    # 关闭时调用 start_idle 被忽略
    view.start_idle()
    assert view._float_anim.state() == QAbstractAnimation.Stopped

    # 取消勾选 → 恢复
    view._act_animation.setChecked(False)
    assert view._animations_enabled
    assert toggles == [False, True]
    view.start_idle()
    assert view._float_anim.state() == QAbstractAnimation.Running
    view.stop_idle()


# ── 展开锚点（桌宠贴屏幕边缘，不瞬移） ─────────────────────


def _wait_animation(app, window=None, ms=2000):
    """轮询事件循环直到窗口动画完成（超时上限 ms）"""
    import time
    deadline = time.time() + ms / 1000
    while time.time() < deadline:
        app.processEvents()
        if window is None or not window._animation_running:
            return
        time.sleep(0.01)
    app.processEvents()


def _make_window(app, tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.AppConfig.DATA_DIR", tmp_path)
    from app.views.main_window import MainWindow
    window = MainWindow()
    pet = PetView()
    window.set_views(pet, pet)
    window.show()
    app.processEvents()
    return window


def _screen_geo(app, window):
    from PySide6.QtWidgets import QApplication
    screen = QApplication.screenAt(window.pos()) or QApplication.primaryScreen()
    return screen.availableGeometry()


def test_expand_at_right_edge_anchors_right(app, tmp_path, monkeypatch):
    """回归：桌宠贴右边缘展开 → 右上锚点，向左下展开，右边缘保持原位"""
    window = _make_window(app, tmp_path, monkeypatch)
    geo = _screen_geo(app, window)
    window.move(geo.right() - window.width(), geo.top() + 40)
    app.processEvents()

    before_right = window.geometry().right()
    window.expand()
    _wait_animation(app, window)

    assert window.mode == "expanded"
    assert window.geometry().right() == before_right  # 右边缘不动，无瞬移
    assert window.x() + window.width() <= geo.right()
    assert window.y() + window.height() <= geo.bottom()
    window.close()
    window.deleteLater()


def test_expand_at_bottom_edge_anchors_bottom(app, tmp_path, monkeypatch):
    """回归：桌宠贴底边缘展开 → 左下锚点，向右上展开，下边缘保持原位"""
    window = _make_window(app, tmp_path, monkeypatch)
    geo = _screen_geo(app, window)
    window.move(geo.left() + 40, geo.bottom() - window.height())
    app.processEvents()

    before_bottom = window.geometry().bottom()
    window.expand()
    _wait_animation(app, window)

    assert window.mode == "expanded"
    assert window.geometry().bottom() == before_bottom  # 下边缘不动，无瞬移
    assert window.y() + window.height() <= geo.bottom()
    assert window.x() + window.width() <= geo.right()
    window.close()
    window.deleteLater()


def test_expand_at_corner_anchors_corner(app, tmp_path, monkeypatch):
    """回归：桌宠贴右下角展开 → 右下锚点，向左上展开，两边缘均保持"""
    window = _make_window(app, tmp_path, monkeypatch)
    geo = _screen_geo(app, window)
    window.move(geo.right() - window.width(),
                geo.bottom() - window.height())
    app.processEvents()

    before = window.geometry()
    window.expand()
    _wait_animation(app, window)

    assert window.mode == "expanded"
    after = window.geometry()
    assert after.right() == before.right()
    assert after.bottom() == before.bottom()
    assert after.left() >= geo.left() and after.top() >= geo.top()
    window.close()
    window.deleteLater()


def test_expand_center_not_moved(app, tmp_path, monkeypatch):
    """回归：桌宠在屏幕中央（展开后不越界）时展开不移动位置"""
    window = _make_window(app, tmp_path, monkeypatch)
    geo = _screen_geo(app, window)
    window.move(
        (geo.width() - AppConfig.EXPANDED_WIDTH) // 2,
        (geo.height() - AppConfig.EXPANDED_HEIGHT) // 2)
    app.processEvents()

    before = window.pos()
    window.expand()
    _wait_animation(app, window)

    assert window.mode == "expanded"
    assert window.pos() == before
    window.close()
    window.deleteLater()


def test_collapse_returns_to_original_position(app, tmp_path, monkeypatch):
    """回归：右边缘展开后折叠，用同一锚点收缩回桌宠原位"""
    window = _make_window(app, tmp_path, monkeypatch)
    geo = _screen_geo(app, window)
    original = geo.right() - window.width(), geo.top() + 40
    window.move(*original)
    app.processEvents()

    window.expand()
    _wait_animation(app, window)
    window.collapse()
    _wait_animation(app, window)

    assert window.mode == "collapsed"
    assert window.pos() == QPoint(*original)
    window.close()
    window.deleteLater()
