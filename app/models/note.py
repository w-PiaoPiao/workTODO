"""
便签数据模型与存储

Note：一条独立于待办的纯文本便利贴（支持颜色）。
NoteStore：notes.json 的原子读写与 CRUD。
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from app.config import AppConfig
from app.models.json_io import atomic_write_json, load_json_list
from app.models.todo_item import StoreError, _get_id, _get_str, _now_iso

logger = logging.getLogger(__name__)


@dataclass
class Note:
    """一张便签"""
    content: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)
    color: str = "yellow"  # 便利贴颜色 key（见 AppConfig.NOTE_COLORS）

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "content": self.content,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "color": self.color,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Note:
        color = _get_str(data, "color", "yellow")
        if color not in AppConfig.NOTE_COLORS:
            color = "yellow"
        return cls(
            id=_get_id(data),
            content=_get_str(data, "content", ""),
            created_at=_get_str(data, "created_at", _now_iso()),
            updated_at=_get_str(data, "updated_at", _now_iso()),
            color=color,
        )

    @property
    def title(self) -> str:
        """标题：内容首行（用于列表预览）"""
        first_line = self.content.strip().splitlines()
        if not first_line:
            return ""
        return first_line[0][:30]


class NoteStore:
    """便签数据存储（JSON 原子读写）"""

    def __init__(self):
        self._notes_path = AppConfig.notes_path()
        self._notes: list[Note] | None = None  # 惰性缓存
        # 加载阶段的问题记录（kind, path, detail），由控制器读取后在 UI 告知用户
        self.problems: list[tuple[str, Path, str]] = []

    def load_notes(self) -> list[Note]:
        """加载便签列表（带缓存）"""
        if self._notes is None:
            self._notes = self._load_items()
        return self._notes

    def add_note(self, note: Note) -> None:
        """添加一张便签"""
        notes = self.load_notes()
        notes.append(note)
        self.save_notes(notes)

    def update_note(self, note: Note) -> None:
        """更新一张便签（按 id 匹配，不存在则报错）"""
        notes = self.load_notes()
        for i, n in enumerate(notes):
            if n.id == note.id:
                notes[i] = note
                self.save_notes(notes)
                return
        raise StoreError(f"未找到 id={note.id} 的便签")

    def delete_note(self, note_id: str) -> bool:
        """删除一张便签，返回是否找到并删除"""
        notes = self.load_notes()
        new_notes = [n for n in notes if n.id != note_id]
        if len(new_notes) < len(notes):
            self.save_notes(new_notes)
            return True
        return False

    def save_notes(self, notes: list[Note]) -> None:
        """立即写入磁盘（便签数量小、编辑频率低，无需防抖）

        先写盘成功再更新缓存：写盘失败时内存与磁盘保持一致（旧数据），
        避免清了缓存后失败导致状态分叉。
        """
        self._save_items(notes)
        self._notes = notes

    # ── 内部实现 ──────────────────────────────────────────

    def _load_items(self) -> list[Note]:
        """从 JSON 文件加载便签（解析/损坏备份由 json_io 统一处理）"""
        data = load_json_list(
            self._notes_path,
            on_problem=lambda kind, path, detail: self.problems.append(
                (kind, path, detail)),
        )

        notes = []
        for entry in data:
            try:
                notes.append(Note.from_dict(entry))
            except (KeyError, TypeError, ValueError) as e:
                logger.warning("跳过无效便签条目: %s", e)
                continue
        return notes

    def _save_items(self, notes: list[Note]) -> None:
        """原子写入 JSON 文件"""
        atomic_write_json(self._notes_path, [n.to_dict() for n in notes])
