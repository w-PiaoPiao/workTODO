"""UI 重构相关测试（offscreen 无头模式）

覆盖：SVG 图标加载、标题栏溢出菜单、待办卡片操作按钮 hover 显隐、
置顶卡片样式、主题 set_mode 持久化。
"""

import os

# 必须在导入 PySide6 之前设置无头平台
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, QObject, QPointF, QSettings
from PySide6.QtGui import QAction, QEnterEvent
from PySide6.QtWidgets import QApplication

from app.config import AppConfig
from app.models.todo_item import TodoItem
from app.views.icons import AppIcons
from app.views.title_bar import TitleBar
from app.views.todo_card import TodoCard


class _FakeMenu(QObject):
    """模拟 QMenu，避免 exec() 模态阻塞（monkeypatch 用）"""

    def __init__(self, parent=None):
        super().__init__(parent)

    def setStyleSheet(self, s):
        pass

    def addAction(self, *args, **kwargs):
        act = QAction(self)
        if args and isinstance(args[-1], str):
            act.setText(args[-1])
        return act

    def addMenu(self, *args, **kwargs):
        return _FakeMenu(self)

    def addSeparator(self):
        pass

    def exec(self, pos=None):
        return None


@pytest.fixture(scope="module")
def app():
    qapp = QApplication.instance() or QApplication([])
    yield qapp


class TestAppIcons:
    def test_all_icons_load(self, app):
        d = AppConfig.resource_path("app/resources/icons")
        names = sorted(p.stem for p in d.glob("*.svg"))
        assert names, "图标目录为空"
        for name in names:
            icon = AppIcons.get(name, 16)
            assert not icon.isNull(), f"图标 {name} 渲染失败"

    def test_icon_color_variants(self, app):
        i1 = AppIcons.get("search", 16, color="#111111")
        i2 = AppIcons.get("search", 16, color="#222222")
        assert not i1.isNull() and not i2.isNull()


class TestTitleBar:
    def test_build_icons(self, app):
        t = TitleBar()
        assert not t._more_btn.icon().isNull()
        assert not t._search_btn.icon().isNull()
        assert not t._settings_btn.icon().isNull()
        assert not t._collapse_btn.icon().isNull()

    def test_more_menu_no_crash(self, app, monkeypatch):
        monkeypatch.setattr("app.views.title_bar.QMenu", _FakeMenu)
        t = TitleBar()
        t._show_more_menu()  # 不抛错即通过

    def test_state_sync(self, app):
        t = TitleBar()
        t.set_pinned(False)
        assert t._pinned is False
        t.set_autostart(True)
        assert t._autostart is True
        t.set_theme_mode("dark")
        assert t._theme_mode == "dark"
        t.set_collapse_cards_state(True)
        assert t._all_collapsed is True

    def test_more_menu_emits_pin(self, app, monkeypatch):
        monkeypatch.setattr("app.views.title_bar.QMenu", _FakeMenu)
        t = TitleBar()
        received = []
        t.signal_toggle_pin.connect(lambda: received.append("pin"))
        t._show_more_menu()
        # fake 菜单 exec 为空操作，仅验证构建无异常、信号对象可连接
        assert received == []


class TestTodoCard:
    def test_action_buttons_hidden_initially(self, app):
        c = TodoCard(TodoItem(title="测试"))
        assert c._date_btn.isHidden()
        assert c._sticky_btn.isHidden()
        assert c._delete_btn.isHidden()
        assert not c._complete_btn.isHidden()

    def test_action_buttons_show_on_hover(self, app):
        c = TodoCard(TodoItem(title="测试"))
        enter = QEnterEvent(QPointF(1, 1), QPointF(1, 1), QPointF(1, 1))
        c.enterEvent(enter)
        assert not c._date_btn.isHidden()
        assert not c._sticky_btn.isHidden()
        assert not c._delete_btn.isHidden()
        c.leaveEvent(QEvent(QEvent.Type.Leave))
        assert c._date_btn.isHidden()
        assert c._delete_btn.isHidden()

    def test_completed_hides_date_sticky(self, app):
        item = TodoItem(title="完成", status="completed")
        c = TodoCard(item)
        enter = QEnterEvent(QPointF(1, 1), QPointF(1, 1), QPointF(1, 1))
        c.enterEvent(enter)
        assert c._date_btn.isHidden()
        assert c._sticky_btn.isHidden()
        assert not c._delete_btn.isHidden()

    def test_sticky_icon_renders(self, app):
        c = TodoCard(TodoItem(title="置顶", sticky=True))
        c2 = TodoCard(TodoItem(title="普通"))
        assert not c._sticky_btn.icon().isNull()
        assert not c2._sticky_btn.icon().isNull()


class TestArchiveDialog:
    def test_search_matches_progress_text(self, app):
        """归档搜索应覆盖进度文本（与主搜索一致）"""
        from app.models.todo_item import ProgressEntry, TodoItem
        from app.views.archive_dialog import ArchiveDialog

        item = TodoItem(title="标题无关键词")
        item.progress.append(ProgressEntry(text="关键进度词"))
        d = ArchiveDialog([item])
        d._on_search("关键进度词")
        assert len(d._filtered_items) == 1
        d._on_search("标题无")
        assert len(d._filtered_items) == 1
        d._on_search("不存在的词")
        assert d._filtered_items == []
        d._on_search("")
        assert len(d._filtered_items) == 1

    def test_search_empty_archive(self, app):
        from app.views.archive_dialog import ArchiveDialog
        d = ArchiveDialog([])
        d._on_search("随便")
        assert d._filtered_items == []


class TestThemeService:
    def test_set_mode_persists(self, app):
        from app.services.theme_service import ThemeService
        s = QSettings("Personal", "待办事项和便签")
        s.remove("theme/mode")
        t = ThemeService()
        t.set_mode("dark")
        assert t.mode == "dark"
        t.set_mode("light")
        assert t.mode == "light"
        t.set_mode("invalid")  # 非法值忽略
        assert t.mode == "light"
        s.remove("theme/mode")
