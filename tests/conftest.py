"""pytest 共享 fixtures"""

import pytest

from app.models.todo_item import ProgressEntry, TodoItem


@pytest.fixture
def sample_item():
    return TodoItem(title="测试待办")


@pytest.fixture
def item_with_progress():
    item = TodoItem(title="带进度的待办")
    item.progress.append(ProgressEntry(text="第一步"))
    item.progress.append(ProgressEntry(text="第二步"))
    return item


@pytest.fixture
def completed_item():
    item = TodoItem(title="已完成待办", status="completed")
    from datetime import datetime, timedelta, timezone
    cst = timezone(timedelta(hours=8), "CST")
    item.completed_at = datetime.now(cst).isoformat(timespec="seconds")
    return item
