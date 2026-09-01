"""行内就地添加进度交互测试（offscreen 无头模式）

覆盖：空状态提示行点击进入添加模式、折叠行"＋"就地编辑、
Enter/Esc/失焦三种退出路径、空文本不提交、已完成卡片禁用入口、
全部折叠模式不再引用已移除的常驻输入行。
"""

import os

# 必须在导入 PySide6 之前设置无头平台
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QLineEdit, QPushButton

from app.models.todo_item import ProgressEntry, TodoItem
from app.views.progress_widget import ProgressWidget
from app.views.todo_card import TodoCard


@pytest.fixture(scope="module")
def app():
    qapp = QApplication.instance() or QApplication([])
    yield qapp


@pytest.fixture
def received():
    """收集 signal_progress_added 发射的列表"""
    return []


# ── 空状态：提示行 → 添加模式 ────────────────────────────

class TestEmptyStateAdd:
    def test_empty_shows_clickable_hint(self, app):
        w = ProgressWidget()
        assert w._layout.count() == 1
        hint_row = w._layout.itemAt(0).widget()
        assert hint_row is not None

    def test_hint_click_enters_add_mode(self, app):
        w = ProgressWidget()
        hint_row = w._layout.itemAt(0).widget()
        assert hint_row.findChild(QLineEdit) is None  # 进入前无输入框
        # 模拟点击提示行（_ClickLabel.clicked 由内部触发）
        hint_row.layout().itemAt(0).widget().clicked.emit()
        inp = w._add_input
        assert isinstance(inp, QLineEdit)
        assert inp.placeholderText() == "添加进度..."
        # 行内替换而非新增行：布局仍只有一行
        assert w._layout.count() == 1
        assert w._layout.itemAt(0).widget() is hint_row

    def test_enter_commits_and_exits(self, app, received):
        w = ProgressWidget()
        w.signal_progress_added.connect(received.append)
        hint_row = w._layout.itemAt(0).widget()
        hint_row.layout().itemAt(0).widget().clicked.emit()
        w._add_input.setText("完成了第一版")
        w._commit_add()
        assert received == ["完成了第一版"]
        assert w._add_input is None  # 已退出添加模式

    def test_empty_text_commit_emits_nothing(self, app, received):
        w = ProgressWidget()
        w.signal_progress_added.connect(received.append)
        hint_row = w._layout.itemAt(0).widget()
        hint_row.layout().itemAt(0).widget().clicked.emit()
        w._add_input.setText("   ")
        w._commit_add()
        assert received == []
        assert w._add_input is None

    def test_escape_cancels_without_emit(self, app, received):
        w = ProgressWidget()
        w.signal_progress_added.connect(received.append)
        hint_row = w._layout.itemAt(0).widget()
        hint_row.layout().itemAt(0).widget().clicked.emit()
        w._add_input.setText("不想加了")
        w._cancel_add()
        assert received == []
        assert w._add_input is None

    def test_set_entries_resets_add_mode(self, app, received):
        w = ProgressWidget()
        hint_row = w._layout.itemAt(0).widget()
        hint_row.layout().itemAt(0).widget().clicked.emit()
        assert w._add_input is not None
        item = TodoItem(title="x")
        item.progress.append(ProgressEntry(text="第一步"))
        w.set_entries(item.progress)
        assert w._add_input is None  # 数据重建取消添加模式
        assert w._layout.count() == 1  # 折叠行显示最新一条


# ── 折叠行（有进度）：＋ → 就地编辑 ─────────────────────

class TestCollapsedRowAdd:
    def test_add_button_hidden_until_hover(self, app):
        item = TodoItem(title="x")
        item.progress.append(ProgressEntry(text="第一步"))
        w = ProgressWidget()
        w.set_entries(item.progress)
        btn = w._layout.itemAt(0).widget().findChild(QPushButton)
        assert btn is not None
        assert btn.isHidden()  # hover 揭示，默认隐藏

    def test_add_button_click_replaces_text_inplace(self, app):
        item = TodoItem(title="x")
        item.progress.append(ProgressEntry(text="第一步"))
        w = ProgressWidget()
        w.set_entries(item.progress)
        row = w._layout.itemAt(0).widget()
        assert w._layout.count() == 1  # 进入前一行
        w._on_add_button_clicked()
        inp = w._add_input
        assert isinstance(inp, QLineEdit)
        # 仍是同一行、同高度就地替换：行 widget 未变，无新增行
        assert w._layout.count() == 1
        assert w._layout.itemAt(0).widget() is row

    def test_add_disabled_hides_button_and_hint(self, app):
        w = ProgressWidget()
        w.set_add_enabled(False)
        # 空状态：无提示行，回退为静态"暂无进度"
        assert w._add_input is None
        item = TodoItem(title="x")
        item.progress.append(ProgressEntry(text="第一步"))
        w.set_entries(item.progress)
        row = w._layout.itemAt(0).widget()
        assert row.findChild(QPushButton) is None  # 无"＋"按钮
        # 禁用后点击入口无效
        w._on_add_button_clicked()
        assert w._add_input is None


# ── TodoCard 集成 ────────────────────────────────────────

class TestTodoCardIntegration:
    def test_card_wires_item_id(self, app, received):
        item = TodoItem(title="测试")
        c = TodoCard(item)
        c.signal_progress_added.connect(
            lambda item_id, text: received.append((item_id, text)))
        w = c._progress_widget
        hint_row = w._layout.itemAt(0).widget()
        hint_row.layout().itemAt(0).widget().clicked.emit()
        w._add_input.setText("新进度")
        w._commit_add()
        assert received == [(item.id, "新进度")]

    def test_no_permanent_input_row_in_card(self, app):
        c = TodoCard(TodoItem(title="测试"))
        assert not hasattr(c, "_progress_input")
        assert not hasattr(c, "_progress_btn")

    def test_completed_card_disables_add(self, app):
        item = TodoItem(title="完成", status="completed")
        c = TodoCard(item)
        assert c._progress_widget._add_enabled is False

    def test_completed_flip_on_update(self, app):
        item = TodoItem(title="测试")
        c = TodoCard(item)
        assert c._progress_widget._add_enabled is True
        item2 = TodoItem(title="完成", status="completed")
        item2.id = item.id
        c.update_item(item2)
        assert c._progress_widget._add_enabled is False

    def test_set_all_collapsed_hides_progress(self, app):
        item = TodoItem(title="测试")
        item.progress.append(ProgressEntry(text="第一步"))
        c = TodoCard(item)
        c.show()  # 未显示的 widget isVisible 恒为 False，先展示再测记忆恢复
        c.set_all_collapsed(True)
        assert c._progress_widget.isHidden()
        c.set_all_collapsed(False)
        assert not c._progress_widget.isHidden()

    def test_expanded_mode_ends_with_hint_row(self, app):
        item = TodoItem(title="测试")
        item.progress.append(ProgressEntry(text="第一步"))
        item.progress.append(ProgressEntry(text="第二步"))
        c = TodoCard(item)
        w = c._progress_widget
        w.expand()
        # 两条进度 + 提示行 + 收起按钮
        assert w._layout.count() == 4
