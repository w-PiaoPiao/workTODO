"""贴顶隐藏位置提示条（DockIndicator）测试（offscreen 无头模式）

覆盖：贴顶隐藏时显示/唤出/取消时隐藏、定位对齐、单击展开、退出信号、
计数角标转发、透明度同步、主题重绘、首次提示一次性。

注意：offscreen 下光标默认在 (0,0)，贴顶后露出 6px 恰好在光标下会触发
enterEvent → 临时唤出，干扰断言。所有贴顶用例先把光标移到屏幕中央。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QCursor, QMouseEvent
from PySide6.QtWidgets import QApplication

from app.config import AppConfig
from app.views.pet_view import PetView
from app.views.theme import AppTheme


@pytest.fixture(scope="module")
def app():
    qapp = QApplication.instance() or QApplication([])
    yield qapp


@pytest.fixture
def ini_settings(monkeypatch, tmp_path):
    """把 QSettings 重定向到临时 INI 文件，不污染真实注册表"""
    from PySide6.QtCore import QSettings as QtQSettings

    path = tmp_path / "settings.ini"

    def factory(*args, **kwargs):
        return QtQSettings(str(path), QtQSettings.IniFormat)

    monkeypatch.setattr("app.config.QSettings", factory)
    return path


def _make_window(app, tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.AppConfig.DATA_DIR", tmp_path)
    from app.views.main_window import MainWindow

    window = MainWindow()
    pet = PetView()
    window.set_views(pet, pet)
    window.show()
    app.processEvents()
    return window


def _screen_geo(app, window=None):
    if window is not None:
        screen = (QApplication.screenAt(window.pos())
                  or QApplication.primaryScreen())
    else:
        screen = QApplication.primaryScreen()
    return screen.availableGeometry()


def _move_cursor_away(app):
    """把光标移到屏幕中央，避开顶部热区（否则 6px 露出会触发临时唤出）"""
    geo = _screen_geo(app)
    QCursor.setPos(geo.center().x(), geo.center().y())
    app.processEvents()


def _stick_to_top(window, app) -> None:
    """把窗口放到顶部热区并贴顶隐藏（调用前需先移开光标）"""
    geo = _screen_geo(app, window)
    window.move(geo.left() + 40, geo.top() + 2)
    app.processEvents()
    assert window._check_and_stick_to_top()
    app.processEvents()


def _wait_animation(app, window, ms=2000):
    import time

    deadline = time.time() + ms / 1000
    while time.time() < deadline:
        app.processEvents()
        if window is None or not window._animation_running:
            return
        time.sleep(0.01)
    app.processEvents()


# ── 显示 / 隐藏状态机 ───────────────────────────────────────


def test_indicator_shown_when_stuck_hidden(app, tmp_path, monkeypatch, ini_settings):
    window = _make_window(app, tmp_path, monkeypatch)
    _move_cursor_away(app)
    _stick_to_top(window, app)

    assert window._stuck_to_top
    assert window._dock_indicator.isVisible()
    window.close()
    window.deleteLater()


def test_indicator_hidden_when_temporarily_shown(app, tmp_path, monkeypatch, ini_settings):
    window = _make_window(app, tmp_path, monkeypatch)
    _move_cursor_away(app)
    _stick_to_top(window, app)
    assert window._dock_indicator.isVisible()

    window._temporarily_show()
    app.processEvents()
    assert window._temporarily_visible
    assert not window._dock_indicator.isVisible()
    window.close()
    window.deleteLater()


def test_indicator_hidden_after_unstick(app, tmp_path, monkeypatch, ini_settings):
    window = _make_window(app, tmp_path, monkeypatch)
    _move_cursor_away(app)
    _stick_to_top(window, app)

    window._full_unstick()
    app.processEvents()
    assert not window._stuck_to_top
    assert not window._dock_indicator.isVisible()
    window.close()
    window.deleteLater()


def test_indicator_hidden_when_window_hidden(app, tmp_path, monkeypatch, ini_settings):
    """最小化到托盘（window.hide）时提示条也隐藏，不残留孤儿窗口"""
    window = _make_window(app, tmp_path, monkeypatch)
    _move_cursor_away(app)
    _stick_to_top(window, app)
    assert window._dock_indicator.isVisible()

    window.hide()
    app.processEvents()
    assert not window._dock_indicator.isVisible()
    window.close()
    window.deleteLater()


# ── 定位 ─────────────────────────────────────────────────────


def test_indicator_aligned_to_window_center(app, tmp_path, monkeypatch, ini_settings):
    window = _make_window(app, tmp_path, monkeypatch)
    _move_cursor_away(app)
    _stick_to_top(window, app)

    ind = window._dock_indicator
    geo = _screen_geo(app, window)
    win_center = window.x() + window.width() // 2
    ind_center = ind.x() + ind.width() // 2
    assert abs(ind_center - win_center) <= 1
    assert ind.y() == geo.top()          # 紧贴屏幕顶边
    assert ind.geometry().right() <= geo.right()   # 不出屏
    assert ind.x() >= geo.left()
    window.close()
    window.deleteLater()


def test_indicator_clamped_inside_screen(app, tmp_path, monkeypatch, ini_settings):
    """窗口贴近右边缘时，提示条仍完整落在屏幕内"""
    window = _make_window(app, tmp_path, monkeypatch)
    _move_cursor_away(app)
    geo = _screen_geo(app, window)
    window.move(geo.right() - window.width(), geo.top() + 2)
    app.processEvents()
    assert window._check_and_stick_to_top()
    app.processEvents()

    ind = window._dock_indicator
    assert ind.geometry().right() <= geo.right()
    assert ind.x() >= geo.left()
    window.close()
    window.deleteLater()


# ── 交互 ─────────────────────────────────────────────────────


def _mouse_event(type_, local, global_, button=Qt.LeftButton, buttons=Qt.LeftButton):
    return QMouseEvent(type_, local, global_, button, buttons, Qt.NoModifier)


def test_indicator_left_click_expands(app, tmp_path, monkeypatch, ini_settings):
    window = _make_window(app, tmp_path, monkeypatch)
    _move_cursor_away(app)
    _stick_to_top(window, app)
    assert window._dock_indicator.isVisible()

    ind = window._dock_indicator
    ind.mousePressEvent(_mouse_event(
        QMouseEvent.Type.MouseButtonPress, ind.rect().center(), ind.pos()))
    ind.mouseReleaseEvent(_mouse_event(
        QMouseEvent.Type.MouseButtonRelease, ind.rect().center(), ind.pos()))
    _wait_animation(app, window)

    assert window.mode == "expanded"
    assert not window._dock_indicator.isVisible()
    window.close()
    window.deleteLater()


def test_indicator_quit_signal_emitted(app, tmp_path, monkeypatch):
    window = _make_window(app, tmp_path, monkeypatch)
    quits = []
    window.signal_dock_quit_requested.connect(lambda: quits.append(True))

    window._dock_indicator.signal_quit_requested.emit()
    assert quits == [True]
    window.close()
    window.deleteLater()


# ── 计数 / 透明度 / 主题 ─────────────────────────────────────


def test_update_dock_count(app, tmp_path, monkeypatch):
    window = _make_window(app, tmp_path, monkeypatch)
    window.update_dock_count(0)
    assert window._dock_indicator._count == 0

    window.update_dock_count(5)
    assert window._dock_indicator._count == 5

    window.update_dock_count(120)
    assert window._dock_indicator._count == 120
    # 计数>0 时绘制角标不崩溃
    window._dock_indicator.show()
    window._dock_indicator.update()
    app.processEvents()
    window.close()
    window.deleteLater()


def test_opacity_synced_to_window(app, tmp_path, monkeypatch):
    window = _make_window(app, tmp_path, monkeypatch)
    window.set_opacity(0.6)
    app.processEvents()
    assert window._dock_indicator.windowOpacity() == pytest.approx(0.6)
    window.close()
    window.deleteLater()


def test_theme_switch_repaints_without_crash(app, tmp_path, monkeypatch):
    window = _make_window(app, tmp_path, monkeypatch)
    AppTheme.switch_theme(True)
    AppTheme.switch_theme(False)
    app.processEvents()  # reapply_theme 回调执行，不抛错即通过
    window.close()
    window.deleteLater()


# ── 首次提示一次性 ───────────────────────────────────────────


def test_first_stick_tip_shown_once(app, tmp_path, monkeypatch, ini_settings):
    window = _make_window(app, tmp_path, monkeypatch)
    _move_cursor_away(app)
    _stick_to_top(window, app)

    assert AppConfig.settings().value(
        "notify/stick_tip_shown", False, type=bool) is True
    window._maybe_show_stick_tip()
    app.processEvents()
    # 第二次不再追加提示（值保持为 True）
    assert AppConfig.settings().value(
        "notify/stick_tip_shown", False, type=bool) is True
    window.close()
    window.deleteLater()
