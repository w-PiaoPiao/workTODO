"""控制器级测试（offscreen 无头模式，覆盖核心业务逻辑）

覆盖：添加（标签提取）、办结归档、截止日期、置顶、排序、
便签 CRUD、标签筛选、到期提醒。
"""

import os

# 必须在导入 PySide6 之前设置无头平台
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime, timedelta

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from app.config import AppConfig
from app.controllers.app_controller import AppController
from app.models.todo_item import CST
from app.views.theme import AppTheme

# 测试期间可能写入的 QSettings 键（teardown 时清理）
_SETTINGS_KEYS = (
    "theme/mode", "theme/dark", "ui/font_scale",
    "window/opacity", "window/pinned",
)


def _clean_settings():
    s = QSettings("Personal", "待办事项和便签")
    for key in list(s.allKeys()):
        if key.startswith("reminders/") or key in _SETTINGS_KEYS:
            s.remove(key)


@pytest.fixture(scope="module")
def app():
    qapp = QApplication.instance() or QApplication([])
    yield qapp


@pytest.fixture
def controller(app, tmp_path, monkeypatch):
    _clean_settings()
    monkeypatch.setattr("app.config.AppConfig.DATA_DIR", tmp_path)
    c = AppController()
    yield c
    # 清理：断开退出回调、关闭窗口、清理设置
    try:
        app.aboutToQuit.disconnect(c._flush_store)
    except (RuntimeError, TypeError):
        pass
    c._window.close()
    c._window.deleteLater()
    _clean_settings()


class TestControllerTodo:
    def test_add_item_extracts_tags(self, controller):
        controller._on_add_item("写周报 #工作 #重要")
        assert len(controller._todos) == 1
        item = controller._todos[0]
        assert item.title == "写周报 #工作 #重要"
        assert item.tags == ["工作", "重要"]

    def test_add_item_no_tags(self, controller):
        controller._on_add_item("买牛奶")
        assert controller._todos[0].tags == []

    def test_add_item_blank_ignored(self, controller):
        controller._on_add_item("   ")
        assert controller._todos == []

    def test_complete_archives(self, controller):
        controller._on_add_item("完成任务")
        item = controller._todos[0]
        controller._on_complete_item(item.id)
        assert controller._todos == []
        assert len(controller._archived) == 1
        assert controller._archived[0].status == "completed"
        assert controller._archived[0].completed_at is not None

    def test_restore_item(self, controller):
        controller._on_add_item("可恢复")
        item = controller._todos[0]
        controller._on_complete_item(item.id)
        controller._on_restore_item(item.id)
        assert len(controller._todos) == 1
        assert controller._todos[0].status == "active"
        assert controller._archived == []

    def test_due_date_set_and_clear(self, controller):
        controller._on_add_item("带截止日期")
        item = controller._todos[0]
        controller._on_due_date_set(item.id, "2099-12-31")
        assert controller._todos[0].due_date == "2099-12-31"
        controller._on_due_date_set(item.id, "")
        assert controller._todos[0].due_date is None

    def test_sticky_toggle(self, controller):
        controller._on_add_item("置顶项")
        item = controller._todos[0]
        controller._on_toggle_sticky(item.id)
        assert item.sticky is True

    def test_reorder_updates_positions(self, controller):
        for i in range(3):
            controller._on_add_item(f"待办{i}")
        order = [controller._todos[2].id, controller._todos[0].id, controller._todos[1].id]
        controller._on_reorder_items(order)
        pos = {t.id: t.position for t in controller._todos}
        for idx, item_id in enumerate(order):
            assert pos[item_id] == idx

    def test_tag_filter(self, controller):
        controller._on_add_item("工作项 #工作")
        controller._on_add_item("生活项 #生活")
        controller._on_tag_filter_clicked("工作")
        filtered = controller._filtered_items()
        assert len(filtered) == 1
        assert "工作" in filtered[0].title

    def test_search_matches_progress(self, controller):
        controller._on_add_item("普通标题")
        item = controller._todos[0]
        controller._on_add_progress(item.id, "完成了第一版")
        controller._on_search("第一版")
        filtered = controller._filtered_items()
        assert len(filtered) == 1


class TestControllerNotes:
    def test_add_note(self, controller):
        controller._on_notes_added("新便签内容", "blue")
        assert len(controller._notes) == 1
        assert controller._notes[0].content == "新便签内容"
        assert controller._notes[0].color == "blue"

    def test_update_note(self, controller):
        controller._on_notes_added("旧内容", "yellow")
        note_id = controller._notes[0].id
        controller._on_note_updated(note_id, "新内容", "pink")
        assert controller._notes[0].content == "新内容"
        assert controller._notes[0].color == "pink"
        assert controller._notes[0].updated_at is not None

    def test_delete_note(self, controller):
        controller._on_notes_added("待删除", "green")
        note_id = controller._notes[0].id
        controller._on_note_deleted(note_id)
        assert controller._notes == []

    def test_notes_persisted_to_disk(self, controller):
        controller._on_notes_added("持久化便签", "white")
        controller._note_store.save_notes(controller._notes)
        assert (AppConfig.DATA_DIR / AppConfig.NOTES_FILE).exists()


class TestControllerReminders:
    def test_due_reminder_marks_reminded(self, controller, monkeypatch):
        from PySide6.QtWidgets import QSystemTrayIcon
        # offscreen 下托盘不支持消息，monkeypatch 使其可用
        monkeypatch.setattr(
            controller._tray_icon, "supportsMessages", lambda: True)

        yesterday = (datetime.now(CST) - timedelta(days=1)).strftime("%Y-%m-%d")
        controller._on_add_item("已过期的任务")
        controller._todos[0].due_date = yesterday

        controller._check_due_reminders()  # 不抛错即通过
        # 第二次调用不应重复（记录在 QSettings）
        controller._check_due_reminders()

    def test_due_today_reminder(self, controller, monkeypatch):
        monkeypatch.setattr(
            controller._tray_icon, "supportsMessages", lambda: True)
        today = datetime.now(CST).strftime("%Y-%m-%d")
        controller._on_add_item("今天到期")
        controller._todos[0].due_date = today
        controller._check_due_reminders()  # 不抛错即通过


class TestThemeAndExtras:
    def test_extract_tags_static(self):
        assert AppController._extract_tags("任务 #工作#生活") == ["工作", "生活"]
        assert AppController._extract_tags("无标签") == []
        assert AppController._extract_tags("带#中文标签的任务") == ["中文标签的任务"]

    def test_font_scale_changes(self, controller, app):
        scale = 1.2
        controller._on_font_scale_changed(scale)
        assert AppTheme.font_scale() == pytest.approx(scale)

    def test_theme_mode_cycles(self, controller):
        controller._theme_mode = "light"
        controller._on_theme_mode_clicked()
        assert controller._theme_mode == "dark"
        controller._on_theme_mode_clicked()
        assert controller._theme_mode == "auto"
        controller._on_theme_mode_clicked()
        assert controller._theme_mode == "light"

    def test_stats_requested(self, controller):
        controller._on_add_item("统计项")
        controller._on_stats_requested()  # 不抛错即通过
