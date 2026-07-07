"""
待办事项数据存储

处理 JSON 文件的原子读写、CRUD 操作、归档管理。
关键设计：
- 原子写入：先写 .tmp 再 rename，防止文件损坏
- 错误恢复：损坏文件自动备份为 .bak，返回空列表
- 路径无关：通过 AppConfig 获取实际路径
"""

from __future__ import annotations

import json
import shutil
import logging
from pathlib import Path
from typing import Optional

from app.config import AppConfig
from app.models.todo_item import TodoItem, StoreError

logger = logging.getLogger(__name__)


class TodoStore:
    """待办事项数据存储"""

    def __init__(self):
        self._todos_path = AppConfig.todos_path()
        self._archive_path = AppConfig.archive_path()

    # ── 公开接口 ──────────────────────────────────────────

    def load_todos(self) -> list[TodoItem]:
        """加载活跃待办列表"""
        return self._load_items(self._todos_path)

    def load_archived(self) -> list[TodoItem]:
        """加载已归档列表"""
        return self._load_items(self._archive_path)

    def save_todos(self, items: list[TodoItem]) -> None:
        """保存活跃待办列表"""
        self._save_items(self._todos_path, items)

    def save_archived(self, items: list[TodoItem]) -> None:
        """保存归档列表"""
        self._save_items(self._archive_path, items)

    def add_item(self, item: TodoItem) -> None:
        """添加一条新待办（自动分配 position）"""
        items = self.load_todos()
        # 新项排最后
        max_pos = max((i.position for i in items), default=0)
        item.position = max_pos + 1
        items.append(item)
        self.save_todos(items)

    def reorder_items(self, ordered_ids: list[str]) -> None:
        """按 ordered_ids 顺序重新排列待办（positions 设为 0,1,2,...）"""
        items = self.load_todos()
        id_to_item = {i.id: i for i in items}
        # 分配新位置
        for idx, item_id in enumerate(ordered_ids):
            if item_id in id_to_item:
                id_to_item[item_id].position = idx
        # 处理不在 ordered_ids 中的项
        next_pos = len(ordered_ids)
        for item in items:
            if item.id not in ordered_ids:
                item.position = next_pos
                next_pos += 1
        self.save_todos(items)

    def update_item(self, updated: TodoItem) -> None:
        """更新一条待办（按 id 匹配）"""
        items = self.load_todos()
        for i, item in enumerate(items):
            if item.id == updated.id:
                items[i] = updated
                self.save_todos(items)
                return
        # 也检查归档
        archived = self.load_archived()
        for i, item in enumerate(archived):
            if item.id == updated.id:
                archived[i] = updated
                self.save_archived(archived)
                return
        raise StoreError(f"未找到 id={updated.id} 的待办事项")

    def delete_item(self, item_id: str) -> bool:
        """删除一条待办，返回是否找到并删除"""
        items = self.load_todos()
        new_items = [i for i in items if i.id != item_id]
        if len(new_items) < len(items):
            self.save_todos(new_items)
            return True
        # 检查归档
        archived = self.load_archived()
        new_archived = [i for i in archived if i.id != item_id]
        if len(new_archived) < len(archived):
            self.save_archived(new_archived)
            return True
        return False

    def archive_item(self, item: TodoItem) -> None:
        """办结一条待办并移入归档"""
        item.status = "completed"
        # 从活跃列表移除
        items = self.load_todos()
        items = [i for i in items if i.id != item.id]
        self.save_todos(items)
        # 追加到归档
        archived = self.load_archived()
        archived.append(item)
        self.save_archived(archived)

    def restore_item(self, item_id: str) -> Optional[TodoItem]:
        """从归档恢复到活跃列表，返回恢复的项目"""
        archived = self.load_archived()
        for i, item in enumerate(archived):
            if item.id == item_id:
                item.status = "active"
                item.completed_at = None
                archived.pop(i)
                self.save_archived(archived)
                # 加入活跃列表
                items = self.load_todos()
                items.append(item)
                self.save_todos(items)
                return item
        return None

    def get_stats(self) -> dict:
        """获取统计信息"""
        todos = self.load_todos()
        archived = self.load_archived()
        return {
            "active_count": len([t for t in todos if t.is_active]),
            "completed_count": len([t for t in todos if t.is_completed]),
            "archived_count": len(archived),
            "total_count": len(todos),
        }

    def auto_archive_old(self, days: int = 30) -> int:
        """自动归档超过指定天数且无近期进度更新的活跃待办，返回归档数量

        条件：创建超过 days 天，且最近一条进度也超过 days 天（若无进度则只看创建时间）
        """
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone(timedelta(hours=8), "CST"))
        cutoff = now - timedelta(days=days)

        todos = self.load_todos()
        old: list[TodoItem] = []
        keep: list[TodoItem] = []
        for item in todos:
            try:
                created = datetime.fromisoformat(item.created_at)
                if not item.is_active or created >= cutoff:
                    keep.append(item)
                    continue

                # 检查最近一条进度的时间
                if item.progress:
                    last_progress = datetime.fromisoformat(item.progress[-1].timestamp)
                    if last_progress >= cutoff:
                        # 近期有进度更新，保留
                        keep.append(item)
                        continue

                # 创建 > days 天 且 无近期进度 → 归档
                item.status = "archived"
                old.append(item)
            except (ValueError, TypeError):
                keep.append(item)

        if not old:
            return 0

        self.save_todos(keep)
        archived = self.load_archived()
        archived.extend(old)
        self.save_archived(archived)
        logger.info("自动归档 %d 条超过 %d 天的待办", len(old), days)
        return len(old)

    # ── 内部实现 ──────────────────────────────────────────

    def _load_items(self, path: Path) -> list[TodoItem]:
        """从 JSON 文件加载待办列表

        边界情况：
        - 文件不存在 → 返回空列表
        - JSON 解析错误 → 备份损坏文件，返回空列表
        - 数据格式不对 → 跳过无效条目
        """
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

        items = []
        for entry in data:
            try:
                items.append(TodoItem.from_dict(entry))
            except (KeyError, TypeError, ValueError) as e:
                logger.warning("跳过无效条目: %s", e)
                continue
        return items

    def _save_items(self, path: Path, items: list[TodoItem]) -> None:
        """原子写入 JSON 文件

        策略：写入 .tmp 临时文件 → 重命名为目标文件
        如果写入中途失败，原始文件不受影响。
        """
        # 确保父目录存在
        path.parent.mkdir(parents=True, exist_ok=True)

        tmp_path = path.with_suffix(".tmp")
        try:
            data = [item.to_dict() for item in items]
            content = json.dumps(
                data,
                ensure_ascii=False,
                indent=2,
            )
            tmp_path.write_text(content, encoding="utf-8")
            # Windows 上 replace 是原子操作（同分区）
            tmp_path.replace(path)
        except (IOError, OSError, PermissionError) as e:
            # 清理临时文件
            if tmp_path.exists():
                tmp_path.unlink()
            raise StoreError(f"保存失败 ({path.name}): {e}")

    @staticmethod
    def _backup_corrupted(path: Path) -> None:
        """备份损坏的文件"""
        bak_path = path.with_suffix(".json.bak")
        try:
            shutil.copy2(path, bak_path)
            logger.info("已备份损坏文件到 %s", bak_path)
        except (IOError, OSError) as e:
            logger.error("备份损坏文件失败: %s", e)
