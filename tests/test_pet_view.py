"""桌宠视图测试（offscreen 无头模式）

覆盖：素材发现（内置 + 用户目录优先级）、形象加载、计数角标。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from app.config import AppConfig
from app.views.pet_view import PetView, discover_pets


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


def _builtin_pet_ids() -> set[str]:
    return {p["id"] for p in discover_pets()}


def test_discover_includes_builtin_placeholders():
    ids = _builtin_pet_ids()
    assert {"cat", "dog", "rabbit", "panda"} <= ids


def test_discover_includes_user_pets(user_pets_dir):
    ids = _builtin_pet_ids()
    assert "custom" in ids


def test_user_dir_overrides_builtin_same_name(app, user_pets_dir, tmp_path):
    """用户目录同名素材应覆盖内置（优先级更高）"""
    builtin_cat = next(p for p in discover_pets() if p["id"] == "cat")
    assert not Path(builtin_cat["path"]).is_relative_to(AppConfig.pets_dir())


def test_load_pet_pixmap(app, tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.AppConfig.DATA_DIR", tmp_path)
    view = PetView()
    view.load_pet("cat")
    pixmap = view._pet_canvas.current_pixmap()
    assert pixmap is not None and not pixmap.isNull()


def test_load_missing_pet_falls_back(app, tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.AppConfig.DATA_DIR", tmp_path)
    view = PetView()
    view.load_pet("no_such_pet")
    # 回退到第一个可用素材（内置 cat）
    assert view.pet_id() == "cat"


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
    from app.views.pet_view import ensure_transparent
    from PIL import Image

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
    from app.views.pet_view import ensure_transparent
    from PIL import Image

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
    from PySide6.QtCore import QAbstractAnimation

    view = PetView()
    view.load_pet("cat")
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
    view.load_pet("cat")
    view.start_idle()
    view._do_random_action()
    app.processEvents()
    assert view._active_action is not None
    view.stop_idle()
