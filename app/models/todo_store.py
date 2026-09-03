"""
待办事项数据存储

处理 JSON 文件的原子读写、CRUD 操作、归档管理。
关键设计：
- 内存缓存：load 后驻留内存，写操作只标记脏，由 flush() 统一落盘（防抖由控制器调度）
- 原子写入：先写 .tmp 并 fsync 再 rename，防止文件损坏
- 方向化落盘：跨侧操作（归档/恢复）按最后操作方向决定双侧写盘顺序，
  中途失败的最坏结果从"数据丢失"降为"跨列表重复"（加载时按 id 去重兜底）
- 错误恢复：损坏文件隔离备份为带时间戳副本（保留多份），问题上报供 UI 告知
- 路径无关：通过 AppConfig 获取实际路径
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from app.config import AppConfig
from app.models.json_io import atomic_write_json, load_json_list
from app.models.note import Note
from app.models.todo_item import CST, StoreError, TodoItem, _now_iso

logger = logging.getLogger(__name__)


class TodoStore:
    """待办事项数据存储（带内存缓存，写操作延迟落盘）"""

    def __init__(self):
        self._todos_path = AppConfig.todos_path()
        self._archive_path = AppConfig.archive_path()
        self._todos: list[TodoItem] | None = None   # 惰性缓存
        self._archived: list[TodoItem] | None = None
        self._dirty_todos = False
        self._dirty_archived = False
        # 最后一次跨侧操作方向（"archive" | "restore"）：
        # flush 双侧都脏时按它决定写盘顺序，把中途失败的最坏结果从"丢失"降为"重复"
        self._last_cross_op = "archive"
        # 加载阶段的问题记录（kind, path, detail），由控制器读取后在 UI 告知用户
        self.problems: list[tuple[str, Path, str]] = []

    # ── 公开接口 ──────────────────────────────────────────

    def load_todos(self) -> list[TodoItem]:
        """加载活跃待办列表（首次读盘，之后返回缓存）"""
        if self._todos is None:
            self._todos = self._load_items(self._todos_path)
            self._dedupe_cross_lists()
        return self._todos

    def load_archived(self) -> list[TodoItem]:
        """加载已归档列表（首次读盘，之后返回缓存）"""
        if self._archived is None:
            self._archived = self._load_items(self._archive_path)
            self._dedupe_cross_lists()
        return self._archived

    def _dedupe_cross_lists(self) -> None:
        """同一 id 同时出现在活跃与归档时的去重兜底

        成因：归档/恢复需要双侧写盘，中途失败会留下"两侧都有"的重复
        （方向化 flush 已把最坏结果从"两侧皆无"降为此处）。
        处理：保留归档侧（更接近用户最后意图的完成态），原地剔除活跃侧
        （保持列表对象同一性，先前返回的引用同步生效），
        并标记活跃脏，下次 flush 落盘纠正。
        """
        if self._todos is None or self._archived is None:
            return
        archived_ids = {i.id for i in self._archived}
        dupes = {i.id for i in self._todos} & archived_ids
        if dupes:
            self._todos[:] = [i for i in self._todos if i.id not in dupes]
            self._dirty_todos = True
            logger.warning("检测到 %d 条跨列表重复条目，已按归档侧去重", len(dupes))

    def flush(self) -> None:
        """将有修改的列表原子写入磁盘（防抖落盘的终点）

        双侧都脏（跨侧操作：归档/恢复）时按最后操作方向决定写盘顺序——
        先写"结果侧"：中途失败的最坏结果是重复（加载时 _dedupe_cross_lists 兜底），
        而非先写"来源侧"导致的两侧皆无（数据丢失）。
        """
        if self._dirty_todos and self._dirty_archived:
            if self._last_cross_op == "restore":
                self._flush_side("todos")
                self._flush_side("archived")
            else:  # archive（默认）
                self._flush_side("archived")
                self._flush_side("todos")
        elif self._dirty_todos:
            self._flush_side("todos")
        elif self._dirty_archived:
            self._flush_side("archived")

    def _flush_side(self, side: str) -> None:
        """写入单侧并清除其脏标记（仅在该侧确有修改时由 flush 调用）"""
        if side == "todos":
            self._save_items(self._todos_path, self._todos)
            self._dirty_todos = False
        else:
            self._save_items(self._archive_path, self._archived)
            self._dirty_archived = False

    def save_todos(self, items: list[TodoItem]) -> None:
        """保存活跃待办列表（先写盘成功，再更新缓存）

        顺序不可反转：先赋缓存/清脏再写盘的话，写盘失败后内存与磁盘
        永久分叉且 flush 因不再脏而永不重试。
        """
        self._save_items(self._todos_path, items)
        self._todos = items
        self._dirty_todos = False

    def save_archived(self, items: list[TodoItem]) -> None:
        """保存归档列表（先写盘成功，再更新缓存，理由同 save_todos）"""
        self._save_items(self._archive_path, items)
        self._archived = items
        self._dirty_archived = False

    def add_item(self, item: TodoItem) -> None:
        """添加一条新待办（position 插到非置顶区最上方，标记脏）

        展示排序为 (not sticky, position, created_at)：置顶块在顶部，
        其余按 position 升序。新待办取非置顶项的最小 position（非置顶整体后移腾位），
        而非沿用旧的 max+1 追加到最下方；也不与最小值撞车——position 相同
        会靠 created_at 决胜反而落到最下方。置顶项 position 不动。
        """
        items = self.load_todos()
        min_pos = min((i.position for i in items if not i.sticky), default=0)
        for other in items:
            if not other.sticky:
                other.position += 1
        item.position = min_pos
        items.append(item)
        self._dirty_todos = True

    def reorder_items(self, ordered_ids: list[str]) -> None:
        """按 ordered_ids 顺序重新排列待办（positions 设为 0,1,2,...）"""
        items = self.load_todos()
        id_to_item = {i.id: i for i in items}
        for idx, item_id in enumerate(ordered_ids):
            if item_id in id_to_item:
                id_to_item[item_id].position = idx
        next_pos = len(ordered_ids)
        for item in items:
            if item.id not in ordered_ids:
                item.position = next_pos
                next_pos += 1
        self._dirty_todos = True

    def update_item(self, updated: TodoItem) -> None:
        """更新一条待办（按 id 匹配，标记脏）"""
        items = self.load_todos()
        for i, item in enumerate(items):
            if item.id == updated.id:
                items[i] = updated
                self._dirty_todos = True
                return
        archived = self.load_archived()
        for i, item in enumerate(archived):
            if item.id == updated.id:
                archived[i] = updated
                self._dirty_archived = True
                return
        raise StoreError(f"未找到 id={updated.id} 的待办事项")

    def delete_item(self, item_id: str) -> bool:
        """删除一条待办，返回是否找到并删除（标记脏）"""
        items = self.load_todos()
        new_items = [i for i in items if i.id != item_id]
        if len(new_items) < len(items):
            self._todos = new_items
            self._dirty_todos = True
            return True
        archived = self.load_archived()
        new_archived = [i for i in archived if i.id != item_id]
        if len(new_archived) < len(archived):
            self._archived = new_archived
            self._dirty_archived = True
            return True
        return False

    def archive_item(self, item: TodoItem) -> None:
        """办结一条待办并移入归档（标记脏）"""
        archived = self.load_archived()
        if any(i.id == item.id for i in archived):
            return  # 幂等：已在归档，避免重复归档
        item.status = "completed"
        items = self.load_todos()
        self._todos = [i for i in items if i.id != item.id]
        self._dirty_todos = True
        archived.append(item)
        self._dirty_archived = True
        self._last_cross_op = "archive"

    def restore_item(self, item_id: str) -> TodoItem | None:
        """从归档恢复到活跃列表，返回恢复的项目（标记脏）"""
        archived = self.load_archived()
        for i, item in enumerate(archived):
            if item.id == item_id:
                item.status = "active"
                item.completed_at = None
                archived.pop(i)
                self._dirty_archived = True
                items = self.load_todos()
                max_pos = max((i.position for i in items), default=0)
                item.position = max_pos + 1
                items.append(item)
                self._dirty_todos = True
                self._last_cross_op = "restore"
                return item
        return None

    def get_stats(self) -> dict:
        """获取统计信息（含今日/本周完成数）"""
        todos = self.load_todos()
        archived = self.load_archived()
        today = datetime.now(CST).date()
        week_start = today - timedelta(days=today.weekday())

        def _completed_on(items, start, end=None):
            count = 0
            for t in items:
                if not t.completed_at:
                    continue
                try:
                    d = datetime.fromisoformat(t.completed_at).date()
                except (ValueError, TypeError):
                    continue
                if d >= start and (end is None or d <= end):
                    count += 1
            return count

        return {
            "active_count": len([t for t in todos if t.is_active]),
            "completed_count": len([t for t in todos if t.is_completed]),
            "archived_count": len(archived),
            "total_count": len(todos),
            "today_completed": _completed_on(archived, today),
            "week_completed": _completed_on(archived, week_start),
            # 累计完成只统计有完成时间的归档（自动归档的未完成项不计入）
            "total_completed": sum(1 for t in archived if t.completed_at),
        }

    def auto_archive_old(self, days: int = 30) -> int:
        """自动归档超过指定天数且无近期进度更新的活跃待办，返回归档数量

        条件：创建超过 days 天，且最近一条进度也超过 days 天（若无进度则只看创建时间）
        """
        now = datetime.now(CST)
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
                        keep.append(item)
                        continue

                # 创建 > days 天 且 无近期进度 → 归档
                item.status = "archived"
                old.append(item)
            except (ValueError, TypeError):
                keep.append(item)

        if not old:
            return 0

        self._todos = keep
        self._dirty_todos = True
        archived = self.load_archived()
        archived.extend(old)
        self._dirty_archived = True
        self._last_cross_op = "archive"
        logger.info("自动归档 %d 条超过 %d 天的待办", len(old), days)
        return len(old)

    # ── 数据备份（导出/导入） ────────────────────────────

    def export_payload(self, notes: list | None = None) -> dict:
        """构建完整导出数据（活跃 + 归档 + 可选便签）

        notes 为 None 时不写入 "notes" 键（保持旧格式兼容）；
        传入便签列表时写入 {"id", "content", "created_at", "updated_at", "color"}。
        """
        data = {
            "app": AppConfig.APP_NAME,
            "version": AppConfig.APP_VERSION,
            "exported_at": _now_iso(),
            "todos": [t.to_dict() for t in self.load_todos()],
            "archived": [t.to_dict() for t in self.load_archived()],
        }
        if notes is not None:
            data["notes"] = [n.to_dict() for n in notes]
        return data

    def export_all(self, path: Path, notes: list | None = None) -> dict:
        """导出全部数据（活跃 + 归档 + 可选便签）到单个 JSON 文件，返回统计信息"""
        data = self.export_payload(notes)
        try:
            atomic_write_json(path, data)
        except StoreError as e:
            raise StoreError(f"导出失败: {e}") from e
        stats = {
            "todos": len(data["todos"]),
            "archived": len(data["archived"]),
        }
        if notes is not None:
            stats["notes"] = len(data["notes"])
        return stats

    def import_all(self, path: Path) -> tuple[int, int, list | None]:
        """从备份文件导入全部数据（替换现有待办与归档并立即落盘）

        返回 (待办数, 归档数, 便签列表或 None)：
        - 备份文件含 "notes" 键 → 解析为 Note 列表（跳过无效条目），调用方可选择恢复
        - 备份文件不含 "notes" 键（旧格式）→ 返回 None，调用方应保留现有便签
        """
        try:
            raw = path.read_text("utf-8")
            data = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError, OSError) as e:
            raise StoreError(f"导入文件无效: {e}") from e

        if not isinstance(data, dict) or not isinstance(data.get("todos"), list):
            raise StoreError("导入文件格式不正确")

        def _parse_items(entries):
            items = []
            for entry in entries:
                try:
                    items.append(TodoItem.from_dict(entry))
                except (KeyError, TypeError, ValueError, AttributeError) as e:
                    logger.warning("导入时跳过无效条目: %s", e)
            return self._sanitize_items(items)

        todos = _parse_items(data.get("todos", []))
        archived = _parse_items(data.get("archived", []))

        # 便签：旧备份无 "notes" 键 → None（不覆盖现有便签）
        notes: list | None = None
        if "notes" in data:
            notes = []
            raw_notes = data.get("notes", [])
            if not isinstance(raw_notes, list):
                logger.warning("导入文件 notes 字段格式错误，忽略便签")
                notes = None
            else:
                for entry in raw_notes:
                    try:
                        notes.append(Note.from_dict(entry))
                    except (KeyError, TypeError, ValueError, AttributeError) as e:
                        logger.warning("导入时跳过无效便签条目: %s", e)

        # 替换缓存并立即落盘
        self.save_todos(todos)
        self.save_archived(archived)
        logger.info("导入完成：%d 条待办，%d 条归档%s",
                    len(todos), len(archived),
                    f"，{len(notes)} 张便签" if notes is not None else "（旧格式，便签未变更）")
        return len(todos), len(archived), notes

    @staticmethod
    def _sanitize_items(items: list[TodoItem]) -> list[TodoItem]:
        """剔除空标题条目并归一化 position

        - 空标题卡片无意义，跳过并记日志
        - 按 position 稳定排序后重写 0..n-1，消除重复 position 的排序错乱
        """
        valid = []
        for item in items:
            if not item.title:
                logger.warning("跳过空标题条目: %s", item.id)
                continue
            valid.append(item)
        valid.sort(key=lambda t: t.position)
        for idx, item in enumerate(valid):
            item.position = idx
        return valid

    # ── 内部实现 ──────────────────────────────────────────

    def _load_items(self, path: Path) -> list[TodoItem]:
        """从 JSON 文件加载待办列表

        文件解析/损坏隔离/不可读重试由 json_io.load_json_list 统一处理
        （问题经 on_problem 记录到 self.problems，由控制器读取后 UI 告知），
        此处只负责条目校验（无效条目跳过、空标题剔除、position 归一化）。
        """
        data = load_json_list(
            path,
            on_problem=lambda kind, p, detail: self.problems.append(
                (kind, p, detail)),
        )

        items = []
        for entry in data:
            try:
                items.append(TodoItem.from_dict(entry))
            except (KeyError, TypeError, ValueError, AttributeError) as e:
                logger.warning("跳过无效条目: %s", e)
                continue
        return self._sanitize_items(items)

    def _save_items(self, path: Path, items: list[TodoItem]) -> None:
        """原子写入 JSON 文件（写入失败时原始文件不受影响）"""
        atomic_write_json(path, [item.to_dict() for item in items])
