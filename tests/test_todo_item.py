"""测试数据模型：ProgressEntry、TodoItem 序列化/反序列化"""

from app.models.todo_item import TodoItem, ProgressEntry, _now_iso


class TestProgressEntry:
    def test_create(self):
        e = ProgressEntry(text="测试进度")
        assert e.text == "测试进度"
        assert e.id is not None
        assert e.timestamp is not None

    def test_to_dict(self):
        e = ProgressEntry(text="测试", id="abc123")
        d = e.to_dict()
        assert d["text"] == "测试"
        assert d["id"] == "abc123"
        assert "timestamp" in d

    def test_from_dict(self):
        d = {"text": "恢复的进度", "id": "xyz789", "timestamp": _now_iso()}
        e = ProgressEntry.from_dict(d)
        assert e.text == "恢复的进度"
        assert e.id == "xyz789"

    def test_from_dict_missing_fields(self):
        e = ProgressEntry.from_dict({"text": "只有文本"})
        assert e.text == "只有文本"
        assert e.id is not None
        assert e.timestamp is not None

    def test_time_display(self):
        e = ProgressEntry(text="刚刚的", timestamp=_now_iso())
        assert "刚刚" in e.time_display or "分钟" in e.time_display


class TestTodoItem:
    def test_create(self):
        item = TodoItem(title="买牛奶")
        assert item.title == "买牛奶"
        assert item.status == "active"
        assert item.is_active
        assert not item.is_completed
        assert not item.is_archived

    def test_defaults(self):
        item = TodoItem(title="默认值")
        assert item.id is not None
        assert item.created_at is not None
        assert item.completed_at is None
        assert item.progress == []
        assert item.sticky is False
        assert item.position == 0

    def test_status_properties(self):
        active = TodoItem(title="活跃")
        assert active.is_active and not active.is_completed and not active.is_archived

        done = TodoItem(title="完成", status="completed")
        assert done.is_completed and not done.is_active and not done.is_archived

        archived = TodoItem(title="归档", status="archived")
        assert archived.is_archived and not archived.is_active and not archived.is_completed

    def test_latest_progress(self, item_with_progress):
        assert item_with_progress.latest_progress == "第二步"

    def test_latest_progress_empty(self, sample_item):
        assert sample_item.latest_progress is None

    def test_to_dict(self, sample_item):
        d = sample_item.to_dict()
        assert d["title"] == "测试待办"
        assert d["status"] == "active"
        assert d["id"] == sample_item.id
        assert d["progress"] == []
        assert d["sticky"] is False

    def test_from_dict(self):
        d = {
            "id": "test-id",
            "title": "从字典恢复",
            "status": "completed",
            "created_at": _now_iso(),
            "completed_at": _now_iso(),
            "progress": [{"text": "进度1", "id": "p1"}],
            "sticky": True,
            "position": 5,
        }
        item = TodoItem.from_dict(d)
        assert item.id == "test-id"
        assert item.title == "从字典恢复"
        assert item.status == "completed"
        assert item.sticky is True
        assert item.position == 5
        assert len(item.progress) == 1

    def test_round_trip(self, sample_item):
        d = sample_item.to_dict()
        restored = TodoItem.from_dict(d)
        assert restored.id == sample_item.id
        assert restored.title == sample_item.title
        assert restored.status == sample_item.status

    def test_round_trip_with_progress(self, item_with_progress):
        d = item_with_progress.to_dict()
        restored = TodoItem.from_dict(d)
        assert len(restored.progress) == 2
        assert restored.progress[0].text == "第一步"
        assert restored.progress[1].text == "第二步"

    def test_completed_display(self, completed_item):
        display = completed_item.completed_display
        assert display != ""
        assert "前" in display or "刚刚" in display

    def test_completed_display_none(self, sample_item):
        assert sample_item.completed_display == ""
