"""展开尺寸记忆测试（offscreen 无头模式）

覆盖：QSettings 记忆尺寸的恢复/钳制、展开使用记忆尺寸、
用户 resize 采集与持久化、折叠再展开保持、中间态/动画帧不被误采集。

注意：沙箱内 pytest tmp_path 不可用，QSettings 用内存 fake 隔离
（monkeypatch AppConfig.settings），不读写真实注册表。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSize
from PySide6.QtWidgets import QApplication

from app.config import AppConfig
from app.views.pet_view import PetView


class _FakeSettings:
    """dict-backed QSettings 替身（覆盖 MainWindow 用到的接口）"""

    def __init__(self):
        self._data = {}

    def setValue(self, key, value):
        self._data[key] = value

    def value(self, key, default=None, type=None):
        if key not in self._data:
            return default
        v = self._data[key]
        if type is bool:
            return bool(v)
        if type is float:
            return float(v)
        return v


@pytest.fixture(scope="module")
def app():
    qapp = QApplication.instance() or QApplication([])
    yield qapp


@pytest.fixture
def fake_settings(monkeypatch):
    fake = _FakeSettings()
    monkeypatch.setattr(AppConfig, "settings", lambda *a, **k: fake)
    return fake


def _make_window(app, monkeypatch):
    monkeypatch.setattr("app.config.AppConfig.DATA_DIR",
                        __import__("pathlib").Path("."))
    from app.views.main_window import MainWindow

    window = MainWindow()
    pet = PetView()
    window.set_views(pet, pet)
    window.show()
    app.processEvents()
    return window


def _wait_animation(app, window, ms=2000):
    import time

    deadline = time.time() + ms / 1000
    while time.time() < deadline:
        app.processEvents()
        if window is None or not window._animation_running:
            return
        time.sleep(0.01)
    app.processEvents()


def _center_window(window, app):
    """把窗口移到屏幕中央（锚点 top_left，便于精确断言尺寸）"""
    from PySide6.QtWidgets import QApplication

    screen = QApplication.primaryScreen().availableGeometry()
    window.move((screen.width() - window.width()) // 2,
                (screen.height() - window.height()) // 2)
    app.processEvents()


# ── 读取与钳制 ───────────────────────────────────────────

class TestLoadExpandedSize:
    def test_default_without_saved_value(self, app, monkeypatch, fake_settings):
        w = _make_window(app, monkeypatch)
        assert w._expanded_size == QSize(
            AppConfig.EXPANDED_WIDTH, AppConfig.EXPANDED_HEIGHT)

    def test_saved_size_restored(self, app, monkeypatch, fake_settings):
        fake_settings.setValue("window/expanded_size", QSize(600, 700))
        w = _make_window(app, monkeypatch)
        assert w._expanded_size == QSize(600, 700)

    def test_oversize_clamped_to_max(self, app, monkeypatch, fake_settings):
        fake_settings.setValue("window/expanded_size", QSize(5000, 5000))
        w = _make_window(app, monkeypatch)
        assert w._expanded_size == QSize(
            AppConfig.EXPANDED_MAX_WIDTH, AppConfig.EXPANDED_MAX_HEIGHT)

    def test_undersize_clamped_to_min(self, app, monkeypatch, fake_settings):
        fake_settings.setValue("window/expanded_size", QSize(50, 50))
        w = _make_window(app, monkeypatch)
        assert w._expanded_size == QSize(
            AppConfig.EXPANDED_MIN_WIDTH, AppConfig.EXPANDED_MIN_HEIGHT)

    def test_invalid_type_falls_back_to_default(self, app, monkeypatch,
                                                fake_settings):
        fake_settings.setValue("window/expanded_size", "600x700")
        w = _make_window(app, monkeypatch)
        assert w._expanded_size == QSize(
            AppConfig.EXPANDED_WIDTH, AppConfig.EXPANDED_HEIGHT)


# ── 展开恢复 ─────────────────────────────────────────────

class TestExpandWithMemory:
    def test_expand_uses_saved_size(self, app, monkeypatch, fake_settings):
        fake_settings.setValue("window/expanded_size", QSize(600, 700))
        w = _make_window(app, monkeypatch)
        _center_window(w, app)
        w.expand()
        _wait_animation(app, w)
        assert w.mode == "expanded"
        assert w.size() == QSize(600, 700)
        w.close()
        w.deleteLater()

    def test_expand_clamps_to_screen(self, app, monkeypatch, fake_settings):
        # 屏幕钳制在 expand 时生效；offscreen 屏幕小于 MAX 时必然被压小
        fake_settings.setValue(
            "window/expanded_size",
            QSize(AppConfig.EXPANDED_MAX_WIDTH, AppConfig.EXPANDED_MAX_HEIGHT))
        w = _make_window(app, monkeypatch)
        _center_window(w, app)
        geo = QApplication.primaryScreen().availableGeometry()
        w.expand()
        _wait_animation(app, w)
        margin = AppConfig.SCREEN_MARGIN
        assert w.width() <= geo.width() - margin
        assert w.height() <= geo.height() - margin
        w.close()
        w.deleteLater()


# ── 用户调整采集与持久化 ─────────────────────────────────

class TestUserResizeCapture:
    def test_resize_updates_and_persists(self, app, monkeypatch, fake_settings):
        w = _make_window(app, monkeypatch)
        _center_window(w, app)
        w.expand()
        _wait_animation(app, w)
        w.resize(560, 640)  # 模拟缩放手柄拖拽产生的窗口 resize
        app.processEvents()
        assert w._expanded_size == QSize(560, 640)
        assert fake_settings._data["window/expanded_size"] == QSize(560, 640)
        w.close()
        w.deleteLater()

    def test_collapse_reexpand_keeps_user_size(self, app, monkeypatch,
                                               fake_settings):
        w = _make_window(app, monkeypatch)
        _center_window(w, app)
        w.expand()
        _wait_animation(app, w)
        w.resize(560, 640)
        app.processEvents()
        w.collapse()
        _wait_animation(app, w)
        assert w._collapsed_size == QSize(AppConfig.PET_WIDTH, AppConfig.PET_HEIGHT)
        w.expand()
        _wait_animation(app, w)
        assert w.size() == QSize(560, 640)
        w.close()
        w.deleteLater()

    def test_plain_expand_does_not_persist(self, app, monkeypatch,
                                           fake_settings):
        """纯展开（无用户 resize）不写入尺寸键：中间态/动画帧被守卫挡住"""
        w = _make_window(app, monkeypatch)
        _center_window(w, app)
        w.expand()
        _wait_animation(app, w)
        app.processEvents()
        assert "window/expanded_size" not in fake_settings._data
        w.close()
        w.deleteLater()

    def test_resize_ignored_during_animation(self, app, monkeypatch,
                                             fake_settings):
        """动画运行期间（_animation_running/_expanding）不采集尺寸"""
        w = _make_window(app, monkeypatch)
        _center_window(w, app)
        w.expand()
        # 动画进行中直接调用 resizeEvent 逻辑路径
        assert w._animation_running
        w.resize(999, 999)
        assert w._expanded_size != QSize(999, 999)
        _wait_animation(app, w)
        w.close()
        w.deleteLater()
