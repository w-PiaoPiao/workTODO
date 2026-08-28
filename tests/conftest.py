"""pytest 共享 fixtures"""

import os

# 必须在导入任何 Qt 模块之前强制无头平台（用赋值而非 setdefault，
# 防止外部环境变量穿透）：避免带显示器的环境下测试真实移动鼠标
# （QCursor.setPos）或依赖真实屏幕几何
os.environ["QT_QPA_PLATFORM"] = "offscreen"

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
