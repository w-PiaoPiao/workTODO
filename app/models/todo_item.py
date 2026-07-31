"""
待办事项数据模型

核心数据类：ProgressEntry（进度条目）、TodoItem（待办事项）
处理序列化/反序列化、校验逻辑。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from typing import Optional


# ── 时区：东八区（北京时间） ─────────────────────────────────
CST = timezone(timedelta(hours=8), "CST")


def _now_iso() -> str:
    """返回当前时间的 ISO-8601 字符串（北京时间）"""
    return datetime.now(CST).isoformat(timespec="seconds")


def _format_relative(iso_str: str) -> str:
    """将 ISO 时间转为友好中文描述"""
    try:
        dt = datetime.fromisoformat(iso_str)
        now = datetime.now(CST)
        delta = now - dt

        if delta < timedelta(minutes=1):
            return "刚刚"
        if delta < timedelta(hours=1):
            return f"{int(delta.total_seconds() // 60)} 分钟前"
        if delta < timedelta(days=1):
            return f"{int(delta.total_seconds() // 3600)} 小时前"
        if delta < timedelta(days=2):
            return "昨天"
        if delta < timedelta(days=7):
            return f"{delta.days} 天前"
        return dt.strftime("%m月%d日")
    except (ValueError, TypeError):
        return iso_str


# ── 异常类 ──────────────────────────────────────────────────


class StoreError(Exception):
    """数据存储操作异常"""
    pass


# ── 数据类 ──────────────────────────────────────────────────


@dataclass
class ProgressEntry:
    """一条进度记录"""
    text: str
    timestamp: str = field(default_factory=_now_iso)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def to_dict(self) -> dict:
        return {"text": self.text, "timestamp": self.timestamp, "id": self.id}

    @classmethod
    def from_dict(cls, data: dict) -> "ProgressEntry":
        return cls(
            text=data.get("text", ""),
            timestamp=data.get("timestamp", _now_iso()),
            id=data.get("id", uuid.uuid4().hex),  # 兼容旧数据
        )

    @property
    def time_display(self) -> str:
        """友好的时间显示"""
        return _format_relative(self.timestamp)


@dataclass
class TodoItem:
    """一个待办事项"""
    title: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    status: str = "active"  # active | completed | archived
    created_at: str = field(default_factory=_now_iso)
    completed_at: Optional[str] = None
    progress: list[ProgressEntry] = field(default_factory=list)
    sticky: bool = False  # 是否置顶
    position: int = 0     # 手动排序位置（0=最前）
    due_date: Optional[str] = None  # 截止日期 "YYYY-MM-DD"
    tags: list[str] = field(default_factory=list)  # 分类标签（#标签）

    # ── 属性 ──────────────────────────────────────────────

    @property
    def is_active(self) -> bool:
        return self.status == "active"

    @property
    def is_completed(self) -> bool:
        return self.status == "completed"

    @property
    def is_archived(self) -> bool:
        return self.status == "archived"

    @property
    def is_overdue(self) -> bool:
        """是否已超过截止日期（仅对有效截止日期判断）"""
        if not self.due_date:
            return False
        try:
            due = datetime.strptime(self.due_date, "%Y-%m-%d").date()
        except ValueError:
            return False
        return due < datetime.now(CST).date()

    @property
    def due_display(self) -> str:
        """截止日期友好显示（含年月日）"""
        if not self.due_date:
            return ""
        try:
            due = datetime.strptime(self.due_date, "%Y-%m-%d").date()
        except ValueError:
            return self.due_date
        if self.is_overdue:
            return f"已过期 {self.due_date}"
        today = datetime.now(CST).date()
        if due == today:
            return f"今天到期"
        if (due - today).days == 1:
            return f"明天到期"
        return self.due_date

    @property
    def age_display(self) -> str:
        """创建时间友好显示"""
        return _format_relative(self.created_at)

    @property
    def completed_display(self) -> str:
        """完成时间友好显示"""
        if self.completed_at:
            return _format_relative(self.completed_at)
        return ""

    @property
    def latest_progress(self) -> Optional[str]:
        """最近一条进度文本"""
        if self.progress:
            return self.progress[-1].text
        return None

    # ── 序列化 ──────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "status": self.status,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "progress": [p.to_dict() for p in self.progress],
            "sticky": self.sticky,
            "position": self.position,
            "due_date": self.due_date,
            "tags": list(self.tags),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TodoItem":
        return cls(
            id=data.get("id", uuid.uuid4().hex),
            title=data.get("title", ""),
            status=data.get("status", "active"),
            created_at=data.get("created_at", _now_iso()),
            completed_at=data.get("completed_at"),
            progress=[
                ProgressEntry.from_dict(p)
                for p in data.get("progress", [])
            ],
            sticky=data.get("sticky", False),
            position=data.get("position", 0),
            due_date=data.get("due_date"),
            tags=[t for t in data.get("tags", []) if isinstance(t, str)],
        )
