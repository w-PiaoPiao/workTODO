"""测试数据模型：ProgressEntry、TodoItem 序列化/反序列化"""

from app.models.todo_item import ProgressEntry, TodoItem, _now_iso


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

    def test_due_date_default(self, sample_item):
        assert sample_item.due_date is None
        assert sample_item.tags == []

    def test_due_date_round_trip(self):
        item = TodoItem(title="带日期", due_date="2099-01-01", tags=["工作", "重要"])
        d = item.to_dict()
        assert d["due_date"] == "2099-01-01"
        assert d["tags"] == ["工作", "重要"]
        restored = TodoItem.from_dict(d)
        assert restored.due_date == "2099-01-01"
        assert restored.tags == ["工作", "重要"]

    def test_from_dict_legacy_without_new_fields(self):
        """旧版本数据无 due_date/tags 字段，应正常解析"""
        item = TodoItem.from_dict({"title": "旧数据"})
        assert item.due_date is None
        assert item.tags == []

    def test_from_dict_tags_ignores_non_string(self):
        item = TodoItem.from_dict({"title": "脏标签", "tags": ["好", 123, None]})
        assert item.tags == ["好"]

    def test_is_overdue(self):
        item = TodoItem(title="已过期", due_date="2000-01-01")
        assert item.is_overdue

    def test_is_overdue_future(self):
        item = TodoItem(title="未到期", due_date="2099-01-01")
        assert not item.is_overdue

    def test_is_overdue_invalid(self):
        item = TodoItem(title="格式错误", due_date="not-a-date")
        assert not item.is_overdue
        assert item.due_display == "not-a-date"

    def test_due_display_today(self):
        from datetime import datetime

        from app.models.todo_item import CST
        today = datetime.now(CST).strftime("%Y-%m-%d")
        item = TodoItem(title="今天到期", due_date=today)
        assert "今天" in item.due_display

    def test_due_display_tomorrow(self):
        from datetime import datetime, timedelta

        from app.models.todo_item import CST
        tomorrow = (datetime.now(CST) + timedelta(days=1)).strftime("%Y-%m-%d")
        item = TodoItem(title="明天到期", due_date=tomorrow)
        assert "明天" in item.due_display

    def test_due_display_overdue(self):
        item = TodoItem(title="过期", due_date="2000-01-01")
        assert "已过期" in item.due_display

    # ── from_dict 脏数据校验 ─────────────────────────────

    def test_from_dict_invalid_status_defaults_to_active(self):
        for bad in ("ARCHIVED", "done", "123", 42):
            item = TodoItem.from_dict({"title": "脏状态", "status": bad})
            assert item.status == "active"

    def test_from_dict_invalid_due_date_becomes_none(self):
        for bad in ("not-a-date", "2026-13-99", "2026/01/01", 123):
            item = TodoItem.from_dict({"title": "脏日期", "due_date": bad})
            assert item.due_date is None

    def test_from_dict_valid_due_date_kept(self):
        item = TodoItem.from_dict({"title": "好日期", "due_date": "2026-12-31"})
        assert item.due_date == "2026-12-31"

    def test_from_dict_invalid_position_clamped(self):
        for bad in (-5, "abc", None):
            item = TodoItem.from_dict({"title": "脏位置", "position": bad})
            assert item.position == 0
        item = TodoItem.from_dict({"title": "位置", "position": "7"})
        assert item.position == 7

    def test_from_dict_title_stripped(self):
        item = TodoItem.from_dict({"title": "  两边有空格  "})
        assert item.title == "两边有空格"

    def test_from_dict_non_dict_progress_skipped(self):
        item = TodoItem.from_dict({"title": "脏进度", "progress": [123, "x", None]})
        assert item.progress == []
