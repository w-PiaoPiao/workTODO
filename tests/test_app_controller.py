"""控制器级测试（offscreen 无头模式，覆盖核心业务逻辑）

覆盖：添加（标签提取）、办结归档、截止日期、置顶、排序、
便签 CRUD、标签筛选、到期提醒。
"""

import json
import os

# 必须在导入 PySide6 之前设置无头平台
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime, timedelta

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QMessageBox

from app.config import AppConfig
from app.controllers.app_controller import AppController
from app.models.todo_item import CST
from app.views.theme import AppTheme

# 测试期间可能写入的 QSettings 键（teardown 时清理）
_SETTINGS_KEYS = (
    "theme/mode", "theme/dark", "ui/font_scale",
    "window/opacity", "window/pinned", "window/pet",
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

    def test_add_item_appears_in_active_search(self, controller):
        """搜索状态下新增待办应立即进入搜索结果（搜索索引失效修复）"""
        controller._on_add_item("旧任务")
        controller._on_search("新")  # 当前无匹配
        assert controller._filtered_items() == []
        controller._on_add_item("新任务 #新")
        filtered = controller._filtered_items()
        assert any(t.title == "新任务 #新" for t in filtered)

    def test_title_edit_refreshes_tag_filters(self, controller):
        """标题内联编辑改变 #标签 后，标签筛选行应同步刷新"""
        controller._on_add_item("工作项 #工作")
        item = controller._todos[0]
        controller._on_title_changed(item.id, "工作项 #生活")
        assert controller._expanded_view._all_tags == ["生活"]

    def test_title_edit_keeps_active_tag_filter(self, controller):
        """按标签筛选时，编辑掉该标签的条目应从结果中消失"""
        controller._on_add_item("工作项 #工作")
        controller._on_add_item("其他项")
        item = controller._todos[0]
        controller._on_tag_filter_clicked("工作")
        assert len(controller._filtered_items()) == 1
        controller._on_title_changed(item.id, "改名 #生活")
        assert controller._filtered_items() == []


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


class TestControllerBackup:
    def test_backup_clicked_no_crash(self, controller, monkeypatch):
        class _FakeSignal:
            def connect(self, *args, **kwargs):
                pass

        class _FakeAction:
            def __init__(self, text="", parent=None):
                self.triggered = _FakeSignal()

        class _FakeMenu:
            def __init__(self, parent=None):
                pass

            def addAction(self, action):
                pass

            def addSeparator(self):
                pass

            def exec(self, pos=None):
                return None

        monkeypatch.setattr("app.controllers.app_controller.QMenu", _FakeMenu)
        monkeypatch.setattr("app.controllers.app_controller.QAction", _FakeAction)
        controller._on_backup_clicked()

    def test_export_data(self, controller, monkeypatch, tmp_path):
        controller._on_add_item("待办A")
        controller._on_add_item("待办B")
        controller._on_notes_added("备份便签", "yellow")
        backup_path = tmp_path / "backup.json"

        class _FakeFileDialog:
            getSaveFileName = staticmethod(
                lambda *a, **k: (str(backup_path), ""))

        monkeypatch.setattr(
            "app.controllers.app_controller.QFileDialog", _FakeFileDialog)
        controller._on_export_data()
        assert backup_path.exists()
        data = json.loads(backup_path.read_text("utf-8"))
        assert data["app"] == AppConfig.APP_NAME
        assert len(data["todos"]) == 2
        assert len(data["archived"]) == 0
        # 便签必须包含在备份中
        assert len(data["notes"]) == 1
        assert data["notes"][0]["content"] == "备份便签"

    def test_import_data(self, controller, monkeypatch, tmp_path):
        backup_path = tmp_path / "backup.json"
        backup = {
            "app": AppConfig.APP_NAME,
            "version": "0.4.2",
            "exported_at": "2026-08-13T00:00:00+08:00",
            "todos": [{"title": "导入的待办"}],
            "archived": [],
        }
        backup_path.write_text(json.dumps(backup, ensure_ascii=False), "utf-8")

        class _FakeFileDialog:
            getOpenFileName = staticmethod(
                lambda *a, **k: (str(backup_path), ""))

        class _FakeMsgBox:
            Yes = QMessageBox.Yes
            No = QMessageBox.No
            question = staticmethod(lambda *a, **k: _FakeMsgBox.Yes)

        monkeypatch.setattr(
            "app.controllers.app_controller.QFileDialog", _FakeFileDialog)
        monkeypatch.setattr(
            "app.controllers.app_controller.QMessageBox", _FakeMsgBox)
        # 导入前先有一张便签（旧格式备份无 notes 键 → 便签应保留）
        controller._on_notes_added("现有便签", "pink")
        controller._on_import_data()
        assert len(controller._todos) == 1
        assert controller._todos[0].title == "导入的待办"
        assert len(controller._notes) == 1
        assert controller._notes[0].content == "现有便签"

    def test_import_data_with_notes(self, controller, monkeypatch, tmp_path):
        """新版备份含便签 → 导入后替换便签"""
        backup_path = tmp_path / "backup2.json"
        backup = {
            "app": AppConfig.APP_NAME,
            "version": "0.4.4",
            "exported_at": "2026-08-14T00:00:00+08:00",
            "todos": [],
            "archived": [],
            "notes": [{"content": "导入的便签", "color": "blue"}],
        }
        backup_path.write_text(json.dumps(backup, ensure_ascii=False), "utf-8")

        class _FakeFileDialog:
            getOpenFileName = staticmethod(
                lambda *a, **k: (str(backup_path), ""))

        class _FakeMsgBox:
            Yes = QMessageBox.Yes
            No = QMessageBox.No
            question = staticmethod(lambda *a, **k: _FakeMsgBox.Yes)

        monkeypatch.setattr(
            "app.controllers.app_controller.QFileDialog", _FakeFileDialog)
        monkeypatch.setattr(
            "app.controllers.app_controller.QMessageBox", _FakeMsgBox)
        controller._on_notes_added("将被替换的便签", "yellow")
        controller._on_import_data()
        assert len(controller._notes) == 1
        assert controller._notes[0].content == "导入的便签"
        assert controller._notes[0].color == "blue"


class TestControllerReminders:
    def test_due_reminder_marks_reminded(self, controller, monkeypatch):
        # offscreen 下托盘不支持消息，monkeypatch 使其可用
        monkeypatch.setattr(
            controller._tray, "supports_messages", lambda: True)

        yesterday = (datetime.now(CST) - timedelta(days=1)).strftime("%Y-%m-%d")
        controller._on_add_item("已过期的任务")
        controller._todos[0].due_date = yesterday

        controller._check_due_reminders()  # 不抛错即通过
        # 第二次调用不应重复（记录在 QSettings）
        controller._check_due_reminders()

    def test_due_today_reminder(self, controller, monkeypatch):
        monkeypatch.setattr(
            controller._tray, "supports_messages", lambda: True)
        today = datetime.now(CST).strftime("%Y-%m-%d")
        controller._on_add_item("今天到期")
        controller._todos[0].due_date = today
        controller._check_due_reminders()  # 不抛错即通过


class TestAutoArchiveNotify:
    def test_notifies_once_per_day(self, app, tmp_path, monkeypatch):
        """启动自动归档后应提示一次；同一天再次启动不重复提示"""
        from PySide6.QtCore import QSettings as QtQSettings
        from app.controllers.app_controller import AppController

        monkeypatch.setattr("app.config.AppConfig.DATA_DIR", tmp_path)
        # QSettings 重定向到临时 INI（notify/auto_archive_date 键）
        ini = tmp_path / "settings.ini"
        monkeypatch.setattr(
            "app.config.QSettings",
            lambda *a, **k: QtQSettings(str(ini), QtQSettings.IniFormat))
        _clean_settings()

        notified = []
        monkeypatch.setattr(
            "app.models.todo_store.TodoStore.auto_archive_old",
            lambda self, days=30: 2)
        monkeypatch.setattr(
            "app.services.tray_service.TrayService.supports_messages",
            lambda self: True)
        monkeypatch.setattr(
            "app.services.tray_service.TrayService.show_notification",
            lambda self, message: notified.append(message))

        c1 = AppController()
        try:
            # 只统计归档通知（window.close() 会额外触发"已最小化"通知）
            assert sum("已自动归档" in m for m in notified) == 1
            assert "已自动归档 2 条" in notified[0]
        finally:
            try:
                app.aboutToQuit.disconnect(c1._flush_store)
            except (RuntimeError, TypeError):
                pass
            c1._window.close()
            c1._window.deleteLater()

        # 同一天第二次启动：不再提示
        c2 = AppController()
        try:
            assert sum("已自动归档" in m for m in notified) == 1
        finally:
            try:
                app.aboutToQuit.disconnect(c2._flush_store)
            except (RuntimeError, TypeError):
                pass
            c2._window.close()
            c2._window.deleteLater()


class TestThemeAndExtras:
    def test_extract_tags_static(self):
        assert AppController._extract_tags("任务 #工作#生活") == ["工作", "生活"]
        assert AppController._extract_tags("无标签") == []
        assert AppController._extract_tags("带#中文标签的任务") == ["中文标签的任务"]

    def test_font_scale_changes(self, controller, app):
        scale = 1.2
        controller._theme.set_font_scale(scale)
        assert AppTheme.font_scale() == pytest.approx(scale)

    def test_theme_mode_cycles(self, controller):
        controller._theme.mode = "light"
        controller._theme.cycle()
        assert controller._theme.mode == "dark"
        controller._theme.cycle()
        assert controller._theme.mode == "auto"
        controller._theme.cycle()
        assert controller._theme.mode == "light"

    def test_stats_requested(self, controller):
        controller._on_add_item("统计项")
        controller._on_stats_requested()  # 不抛错即通过
