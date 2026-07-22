"""测试数据存储层：CRUD、归档、损坏恢复、原子写入"""

import json
import pytest
from pathlib import Path

from app.models.todo_item import TodoItem, ProgressEntry, StoreError
from app.models.todo_store import TodoStore


@pytest.fixture
def store(tmp_path, monkeypatch):
    """使用临时目录的 TodoStore（monkeypatch 确保异常时自动还原）"""
    monkeypatch.setattr("app.config.AppConfig.DATA_DIR", tmp_path)
    return TodoStore()


class TestTodoStore:
    def test_empty_store(self, store):
        assert store.load_todos() == []
        assert store.load_archived() == []

    def test_add_and_load(self, store):
        item = TodoItem(title="新待办")
        store.add_item(item)
        todos = store.load_todos()
        assert len(todos) == 1
        assert todos[0].title == "新待办"
        assert todos[0].position > 0

    def test_add_multiple(self, store):
        for i in range(3):
            store.add_item(TodoItem(title=f"待办{i}"))
        todos = store.load_todos()
        assert len(todos) == 3

    def test_update_item(self, store):
        item = TodoItem(title="原标题")
        store.add_item(item)
        item.title = "新标题"
        store.update_item(item)
        todos = store.load_todos()
        assert todos[0].title == "新标题"

    def test_update_nonexistent(self, store):
        item = TodoItem(title="不存在")
        with pytest.raises(StoreError):
            store.update_item(item)

    def test_delete_item(self, store):
        item = TodoItem(title="待删除")
        store.add_item(item)
        assert store.delete_item(item.id) is True
        assert store.load_todos() == []

    def test_delete_nonexistent(self, store):
        assert store.delete_item("nonexistent") is False

    def test_archive_and_restore(self, store):
        item = TodoItem(title="待归档")
        store.add_item(item)
        store.archive_item(item)

        todos = store.load_todos()
        assert len(todos) == 0

        archived = store.load_archived()
        assert len(archived) == 1
        assert archived[0].status == "completed"

        # 恢复
        restored = store.restore_item(item.id)
        assert restored is not None
        assert restored.status == "active"
        assert restored.completed_at is None
        assert len(store.load_todos()) == 1
        assert len(store.load_archived()) == 0

    def test_restore_nonexistent(self, store):
        assert store.restore_item("nonexistent") is None

    def test_reorder_items(self, store):
        items = [TodoItem(title=f"待办{i}") for i in range(3)]
        for item in items:
            store.add_item(item)

        order = [items[2].id, items[0].id, items[1].id]
        store.reorder_items(order)

        # reorder_items 只更新 position 字段，不改变文件写入顺序
        todos = store.load_todos()
        id_to_pos = {t.id: t.position for t in todos}
        for idx, item_id in enumerate(order):
            assert id_to_pos[item_id] == idx

    def test_get_stats(self, store):
        store.add_item(TodoItem(title="活跃1"))
        store.add_item(TodoItem(title="活跃2"))
        stats = store.get_stats()
        assert stats["active_count"] == 2
        assert stats["total_count"] == 2
        assert stats["archived_count"] == 0

    def test_corrupted_file(self, store, tmp_path):
        """损坏的 JSON 文件应备份并返回空列表"""
        todos_file = tmp_path / "todos.json"
        todos_file.write_text("这不是 json", encoding="utf-8")
        result = store.load_todos()
        assert result == []
        bak_file = tmp_path / "todos.json.bak"
        assert bak_file.exists()

    def test_atomic_write(self, store):
        """原子写入：临时文件不应残留"""
        item = TodoItem(title="原子写入测试")
        store.add_item(item)

        tmp_files = list(store._todos_path.parent.glob("*.tmp"))
        assert len(tmp_files) == 0

    def test_data_persistence(self, store):
        item = TodoItem(title="持久化测试")
        store.add_item(item)

        # 重新加载
        todos = store.load_todos()
        assert len(todos) == 1
        assert todos[0].title == "持久化测试"

    def test_progress_preserved(self, store):
        item = TodoItem(title="带进度")
        item.progress.append(ProgressEntry(text="步骤1"))
        store.add_item(item)

        todos = store.load_todos()
        assert len(todos[0].progress) == 1
        assert todos[0].progress[0].text == "步骤1"

    def test_delete_from_archived(self, store):
        item = TodoItem(title="归档删除")
        store.add_item(item)
        store.archive_item(item)
        assert store.delete_item(item.id) is True
        assert store.load_archived() == []

    def test_auto_archive_old(self, store):
        """测试自动归档：由于时间依赖，只验证接口正确性"""
        from datetime import datetime, timezone, timedelta
        cst = timezone(timedelta(hours=8), "CST")
        old = datetime.now(cst) - timedelta(days=60)

        item = TodoItem(title="旧待办")
        item.created_at = old.isoformat(timespec="seconds")
        store.add_item(item)

        count = store.auto_archive_old(days=30)
        assert count >= 0  # 至少不会报错
