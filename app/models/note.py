"""
便签数据模型与存储

Note：一条独立于待办的纯文本便利贴（支持颜色）。
NoteStore：notes.json 的原子读写与 CRUD。
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.config import AppConfig
from app.models.todo_item import CST, StoreError

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    """返回当前时间的 ISO-8601 字符串（北京时间）"""
    return datetime.now(CST).isoformat(timespec="seconds")


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
    def from_dict(cls, data: dict) -> "Note":
        return cls(
            id=data.get("id", uuid.uuid4().hex),
            content=data.get("content", ""),
            created_at=data.get("created_at", _now_iso()),
            updated_at=data.get("updated_at", _now_iso()),
            color=data.get("color", "yellow"),
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
        self._notes_path = AppConfig.DATA_DIR / AppConfig.NOTES_FILE
        self._notes: Optional[list[Note]] = None  # 惰性缓存

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
        """立即写入磁盘（便签数量小、编辑频率低，无需防抖）"""
        self._notes = notes
        self._save_items(notes)

    # ── 内部实现 ──────────────────────────────────────────

    def _load_items(self) -> list[Note]:
        """从 JSON 文件加载便签（损坏时备份并返回空列表）"""
        path = self._notes_path
        if not path.exists():
            return []

        try:
            raw = path.read_text("utf-8")
            data = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.warning("JSON 解析失败 (%s)，备份文件: %s", e, path)
            self._backup_corrupted(path)
            return []

        if not isinstance(data, list):
            logger.warning("数据格式错误，期望列表，实际 %s", type(data).__name__)
            self._backup_corrupted(path)
            return []

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
        path = self._notes_path
        path.parent.mkdir(parents=True, exist_ok=True)

        tmp_path = path.with_suffix(".tmp")
        try:
            data = [n.to_dict() for n in notes]
            content = json.dumps(data, ensure_ascii=False, indent=2)
            tmp_path.write_text(content, encoding="utf-8")
            tmp_path.replace(path)
        except (IOError, OSError, PermissionError) as e:
            if tmp_path.exists():
                tmp_path.unlink()
            raise StoreError(f"保存失败 ({path.name}): {e}")

    @staticmethod
    def _backup_corrupted(path: Path) -> None:
        """备份损坏的文件"""
        import shutil
        bak_path = path.with_suffix(".json.bak")
        try:
            shutil.copy2(path, bak_path)
            logger.info("已备份损坏文件到 %s", bak_path)
        except (IOError, OSError) as e:
            logger.error("备份损坏文件失败: %s", e)
