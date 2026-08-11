"""系统服务单元测试：提醒、自启、主题

QSettings 全部重定向到临时 INI 文件，不污染真实注册表。
"""

import os

# 必须在导入 PySide6 之前设置无头平台
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import importlib
from datetime import datetime, timedelta

import pytest
from PySide6.QtCore import QSettings as QtQSettings
from PySide6.QtWidgets import QApplication

from app.config import AppConfig
from app.models.todo_item import CST, TodoItem
from app.services.reminder_service import ReminderService
from app.services.autostart_service import AutostartService
from app.services.theme_service import ThemeService
from app.views.theme import AppTheme


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def ini_settings(monkeypatch, tmp_path):
    """把指定模块内的 QSettings 重定向到临时 INI 文件"""
    path = tmp_path / "settings.ini"

    def factory(*args, **kwargs):
        return QtQSettings(str(path), QtQSettings.IniFormat)

    def apply_for(module_name):
        module = importlib.import_module(module_name)
        monkeypatch.setattr(module, "QSettings", factory)

    return apply_for


class TestReminderService:
    def _make_notify(self, s, todos):
        notified = []
        s.configure(lambda: todos, notified.append)
        return notified

    def test_no_due_no_notify(self, qapp, ini_settings):
        ini_settings("app.services.reminder_service")
        s = ReminderService()
        todos = [TodoItem(title="无日期")]
        notified = self._make_notify(s, todos)
        s.check()
        assert notified == []

    def test_overdue_notifies_once_per_day(self, qapp, ini_settings):
        ini_settings("app.services.reminder_service")
        s = ReminderService()
        yesterday = (datetime.now(CST) - timedelta(days=1)).strftime("%Y-%m-%d")
        todos = [TodoItem(title="过期任务", due_date=yesterday)]
        notified = self._make_notify(s, todos)
        s.check()
        assert len(notified) == 1
        assert "已过期" in notified[0]
        # 同一天第二次检查不再通知
        s.check()
        assert len(notified) == 1

    def test_due_today_notifies(self, qapp, ini_settings):
        ini_settings("app.services.reminder_service")
        s = ReminderService()
        today = datetime.now(CST).strftime("%Y-%m-%d")
        todos = [TodoItem(title="今日任务", due_date=today)]
        notified = self._make_notify(s, todos)
        s.check()
        assert len(notified) == 1
        assert "今日到期" in notified[0]

    def test_mixed_overdue_and_today(self, qapp, ini_settings):
        ini_settings("app.services.reminder_service")
        s = ReminderService()
        today = datetime.now(CST).strftime("%Y-%m-%d")
        yesterday = (datetime.now(CST) - timedelta(days=1)).strftime("%Y-%m-%d")
        todos = [
            TodoItem(title="过期A", due_date=yesterday),
            TodoItem(title="今天B", due_date=today),
            TodoItem(title="未来C", due_date="2099-01-01"),
            TodoItem(title="无日期D"),
        ]
        notified = self._make_notify(s, todos)
        s.check()
        assert len(notified) == 1
        assert "已过期：过期A" in notified[0]
        assert "今日到期：今天B" in notified[0]

    def test_invalid_due_date_skipped(self, qapp, ini_settings):
        ini_settings("app.services.reminder_service")
        s = ReminderService()
        todos = [TodoItem(title="坏日期", due_date="not-a-date")]
        notified = self._make_notify(s, todos)
        s.check()
        assert notified == []

    def test_unconfigured_safe(self, qapp, ini_settings):
        ini_settings("app.services.reminder_service")
        s = ReminderService()
        s.check()  # 未 configure 不应崩溃


class TestAutostartService:
    def test_set_and_unset(self, ini_settings):
        ini_settings("app.services.autostart_service")
        svc = AutostartService()
        assert svc.is_enabled() is False
        svc.set_enabled(True)
        assert svc.is_enabled() is True
        svc.set_enabled(False)
        assert svc.is_enabled() is False

    def test_non_windows_raises(self, ini_settings, monkeypatch):
        ini_settings("app.services.autostart_service")
        monkeypatch.setattr("app.config.AppConfig.IS_WINDOWS", False)
        svc = AutostartService()
        with pytest.raises(RuntimeError):
            svc.set_enabled(True)
        assert svc.is_enabled() is False


class TestThemeService:
    def test_cycle_order(self, qapp, ini_settings):
        ini_settings("app.services.theme_service")
        svc = ThemeService()
        svc.mode = "light"
        svc.cycle()
        assert svc.mode == "dark"
        svc.cycle()
        assert svc.mode == "auto"
        svc.cycle()
        assert svc.mode == "light"

    def test_apply_idempotent(self, qapp, ini_settings):
        ini_settings("app.services.theme_service")
        svc = ThemeService()
        svc.apply()  # 不抛错即通过
        svc.apply()

    def test_mode_persisted(self, qapp, ini_settings):
        ini_settings("app.services.theme_service")
        svc = ThemeService()
        svc.mode = "light"
        svc.cycle()  # → dark 并持久化
        svc2 = ThemeService()  # 重新读取
        assert svc2.mode == "dark"

    def test_font_scale_applies(self, qapp, ini_settings):
        ini_settings("app.services.theme_service")
        svc = ThemeService()
        svc.set_font_scale(1.15)
        assert AppTheme.font_scale() == pytest.approx(1.15)
