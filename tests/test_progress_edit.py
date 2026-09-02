"""双击行内就地编辑进度交互测试（offscreen 无头模式）

覆盖：折叠模式最新一条双击进入编辑、展开模式任意条目双击编辑、
Enter/Esc/失焦三种退出路径、空文本/未变更不提交、
编辑与添加模式互斥、已完成卡片、数据刷新重建行后退出编辑。
"""

import os

# 必须在导入 PySide6 之前设置无头平台
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QLineEdit

from app.models.todo_item import ProgressEntry, TodoItem
from app.views.progress_widget import ClickableElidedLabel, ProgressWidget
from app.views.todo_card import TodoCard


def _dbl():
    """构造左键双击事件（走真实 mouseDoubleClickEvent 路径）"""
    return QMouseEvent(QEvent.Type.MouseButtonDblClick, QPointF(2, 2),
                       QPointF(2, 2), Qt.LeftButton, Qt.LeftButton,
                       Qt.NoModifier)


@pytest.fixture(scope="module")
def app():
    qapp = QApplication.instance() or QApplication([])
    yield qapp


@pytest.fixture
def edited():
    """收集 signal_progress_edited 发射的 (entry_id, text) 列表"""
    return []


def _make_entries(*texts: str) -> list[ProgressEntry]:
    return [ProgressEntry(text=t) for t in texts]


def _collapsed_text_label(w: ProgressWidget):
    """折叠模式行里的文本 label（按类型查找，位置随展开按钮数量变化）"""
    row = w._layout.itemAt(0).widget()
    return row.findChild(ClickableElidedLabel)


def _row_text_label(row):
    """展开模式进度行里的文本 label（按类型查找）"""
    return row.findChild(ClickableElidedLabel)


# ── 折叠模式：双击最新一条 ───────────────────────────────

class TestCollapsedEdit:
    def test_double_click_enters_edit_mode(self, app):
        entries = _make_entries("第一步", "第二步")
        w = ProgressWidget()
        w.set_entries(entries)
        assert w._layout.count() == 1
        label = _collapsed_text_label(w)
        label._on_double_click(_dbl())  # 模拟双击
        inp = w._edit_input
        assert isinstance(inp, QLineEdit)
        assert inp.text() == "第二步"  # 预填最新一条原文
        # 行内替换而非新增行
        assert w._layout.count() == 1
        assert w._layout.itemAt(0).widget() is label.parentWidget()

    def test_enter_commits(self, app, edited):
        entries = _make_entries("旧文本")
        w = ProgressWidget()
        w.set_entries(entries)
        w.signal_progress_edited.connect(
            lambda entry_id, text: edited.append((entry_id, text)))
        _collapsed_text_label(w)._on_double_click(_dbl())
        w._edit_input.setText("新文本")
        w._commit_edit()
        assert edited == [(entries[-1].id, "新文本")]
        assert w._edit_input is None

    def test_escape_cancels_without_emit(self, app, edited):
        entries = _make_entries("旧文本")
        w = ProgressWidget()
        w.set_entries(entries)
        w.signal_progress_edited.connect(
            lambda entry_id, text: edited.append((entry_id, text)))
        _collapsed_text_label(w)._on_double_click(_dbl())
        w._edit_input.setText("改了又不想改了")
        w._cancel_edit()
        assert edited == []
        assert w._edit_input is None

    def test_empty_text_commit_no_emit(self, app, edited):
        entries = _make_entries("旧文本")
        w = ProgressWidget()
        w.set_entries(entries)
        w.signal_progress_edited.connect(
            lambda entry_id, text: edited.append((entry_id, text)))
        _collapsed_text_label(w)._on_double_click(_dbl())
        w._edit_input.setText("   ")
        w._commit_edit()
        assert edited == []
        assert w._edit_input is None

    def test_unchanged_text_commit_no_emit(self, app, edited):
        entries = _make_entries("原样")
        w = ProgressWidget()
        w.set_entries(entries)
        w.signal_progress_edited.connect(
            lambda entry_id, text: edited.append((entry_id, text)))
        _collapsed_text_label(w)._on_double_click(_dbl())
        w._edit_input.setText(" 原样 ")  # strip 后与原文相同
        w._commit_edit()
        assert edited == []

    def test_set_entries_rebuild_cancels_edit(self, app, edited):
        entries = _make_entries("旧文本")
        w = ProgressWidget()
        w.set_entries(entries)
        w.signal_progress_edited.connect(
            lambda entry_id, text: edited.append((entry_id, text)))
        _collapsed_text_label(w)._on_double_click(_dbl())
        assert w._edit_input is not None
        w._edit_input.setText("未提交就被刷新")
        item = TodoItem(title="x")
        item.progress.extend(_make_entries("刷新后的进度"))
        w.set_entries(item.progress)
        assert w._edit_input is None  # 行重建取消编辑模式
        assert edited == []  # 未发射提交


# ── 展开模式：双击任意条目 ───────────────────────────────

class TestExpandedEdit:
    def test_double_click_first_row_edits_that_entry(self, app, edited):
        entries = _make_entries("第一条", "第二条", "第三条")
        w = ProgressWidget()
        w.set_entries(entries)
        w.expand()
        # 行 0/1 = 前两条进度，行 2 = 提示行，行 3 = 收起按钮
        row0 = w._layout.itemAt(0).widget()
        label0 = _row_text_label(row0)
        label0._on_double_click(_dbl())
        assert w._edit_input.text() == "第一条"
        w._edit_input.setText("改第一条")
        w.signal_progress_edited.connect(
            lambda entry_id, text: edited.append((entry_id, text)))
        w._commit_edit()
        assert edited == [(entries[0].id, "改第一条")]

    def test_double_click_middle_row(self, app, edited):
        entries = _make_entries("第一条", "第二条")
        w = ProgressWidget()
        w.set_entries(entries)
        w.expand()
        row1 = w._layout.itemAt(1).widget()
        label1 = _row_text_label(row1)
        label1._on_double_click(_dbl())
        assert w._edit_input.text() == "第二条"
        w._edit_input.setText("改第二条")
        w.signal_progress_edited.connect(
            lambda entry_id, text: edited.append((entry_id, text)))
        w._commit_edit()
        assert edited == [(entries[1].id, "改第二条")]

    def test_edit_and_add_mutually_exclusive(self, app):
        entries = _make_entries("第一条")
        w = ProgressWidget()
        w.set_entries(entries)
        # 编辑中 → 无法进入添加模式
        _collapsed_text_label(w)._on_double_click(_dbl())
        w._on_add_button_clicked()
        assert w._add_input is None
        assert w._edit_input is not None
        w._cancel_edit()
        # 添加中 → 双击无法进入编辑模式
        w._on_add_button_clicked()
        assert w._add_input is not None
        _collapsed_text_label(w)._on_double_click(_dbl())
        assert w._edit_input is None


# ── TodoCard 集成 ────────────────────────────────────────

class TestTodoCardEditIntegration:
    def test_card_wires_edit_signal(self, app, edited):
        item = TodoItem(title="测试")
        item.progress.append(ProgressEntry(text="旧进度"))
        c = TodoCard(item)
        c.signal_progress_edited.connect(
            lambda item_id, entry_id, text: edited.append((item_id, entry_id, text)))
        w = c._progress_widget
        row = w._layout.itemAt(0).widget()
        label = row.findChild(ClickableElidedLabel)
        label._on_double_click(_dbl())
        w._edit_input.setText("新进度")
        w._commit_edit()
        assert edited == [(item.id, item.progress[-1].id, "新进度")]

    def test_completed_card_still_editable(self, app, edited):
        """已完成卡片：不能添加进度，但已有进度仍可双击修正"""
        item = TodoItem(title="完成", status="completed")
        item.progress.append(ProgressEntry(text="历史进度"))
        c = TodoCard(item)
        c.signal_progress_edited.connect(
            lambda item_id, entry_id, text: edited.append((item_id, entry_id, text)))
        w = c._progress_widget
        assert w._add_enabled is False
        row = w._layout.itemAt(0).widget()
        label = row.findChild(ClickableElidedLabel)
        label._on_double_click(_dbl())
        assert w._edit_input is not None
        w._edit_input.setText("修正历史进度")
        w._commit_edit()
        assert edited == [(item.id, item.progress[-1].id, "修正历史进度")]

    def test_hover_reveal_blocked_during_edit(self, app):
        item = TodoItem(title="测试")
        item.progress.append(ProgressEntry(text="第一步"))
        c = TodoCard(item)
        w = c._progress_widget
        label_row = w._layout.itemAt(0).widget()
        label = label_row.findChild(ClickableElidedLabel)
        label._on_double_click(_dbl())
        # 编辑模式下 hover 行不再揭示"＋"按钮
        assert not label_row._can_reveal()
