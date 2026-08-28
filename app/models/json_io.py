"""
JSON 文件读写公共工具

被 TodoStore / NoteStore 共用：
- load_json_list：读取列表数据（损坏自动隔离备份并返回空列表，问题经 on_problem 上报）
- atomic_write_json：原子写入（先写 .tmp 并 fsync 落盘，再 replace，失败清理临时文件）
- backup_corrupted：损坏文件备份为带时间戳的隔离副本（保留最近 N 份）
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from app.models.todo_item import StoreError

logger = logging.getLogger(__name__)

# 损坏隔离备份的保留份数（超出自动清理最旧的）
CORRUPT_BACKUP_KEEP = 5


def load_json_list(
    path: Path,
    on_problem: Callable[[str, Path, str], None] | None = None,
) -> list:
    """从 JSON 文件加载列表数据

    边界情况：
    - 文件不存在 → 返回空列表
    - JSON 解析错误/顶层不是列表 → 隔离备份损坏文件，返回空列表
    - 文件暂时不可读（被杀毒/同步盘独占锁定等）→ 短暂重试后仍失败则返回空列表
      （避免一次临时文件锁导致启动即崩）

    异常经 on_problem(kind, path, detail) 上报（kind: "corrupted" | "unreadable"），
    供调用方在 UI 明确告知用户，避免静默清零。
    """
    if not path.exists():
        return []

    raw: str | None = None
    read_error: Exception | None = None
    for attempt in range(3):
        try:
            raw = path.read_text("utf-8")
            break
        except OSError as e:
            read_error = e
            time.sleep(0.1 * (attempt + 1))

    if raw is None:
        logger.error("数据文件读取失败，以空数据启动: %s (%s)", path, read_error)
        if on_problem:
            on_problem("unreadable", path, str(read_error))
        return []

    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        logger.warning("JSON 解析失败 (%s)，隔离备份文件: %s", e, path)
        backup_corrupted(path)
        if on_problem:
            on_problem("corrupted", path, str(e))
        return []

    if not isinstance(data, list):
        logger.warning("数据格式错误，期望列表，实际 %s", type(data).__name__)
        backup_corrupted(path)
        if on_problem:
            on_problem("corrupted", path, f"顶层不是列表: {type(data).__name__}")
        return []

    return data


def atomic_write_json(path: Path, data, *, indent: int = 2, ensure_ascii: bool = False) -> None:
    """原子写入 JSON 文件

    策略：写入 .tmp 临时文件 → flush + fsync 确保内容落盘 → 重命名为目标文件。
    必须先 fsync 再 replace：os.replace 只保证"名字切换"原子，掉电/蓝屏时
    未经 fsync 的内容可能未持久化，产生空文件或半截文件（恰好落入损坏清零路径）。
    如果写入中途失败，原始文件不受影响。
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    tmp_path = path.with_suffix(".tmp")
    try:
        content = json.dumps(data, ensure_ascii=ensure_ascii, indent=indent)
        with tmp_path.open("w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        # Windows 上 replace 是原子操作（同分区）
        tmp_path.replace(path)
    except OSError as e:  # 含 PermissionError（OSError 子类）
        # 清理临时文件；清理自身失败不掩盖原始异常
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            logger.warning("清理临时文件失败: %s", tmp_path)
        raise StoreError(f"保存失败 ({path.name}): {e}") from e


def backup_corrupted(path: Path) -> Path | None:
    """备份损坏的文件为带时间戳的隔离副本（保留最近 CORRUPT_BACKUP_KEEP 份）

    时间戳命名避免后一次损坏覆盖前一次备份；返回备份路径，失败返回 None。
    """
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    bak_path = path.with_name(f"{path.name}.corrupt.{stamp}.bak")
    try:
        shutil.copy2(path, bak_path)
    except OSError as e:
        logger.error("备份损坏文件失败: %s", e)
        return None
    _prune_corrupt_backups(path)
    logger.info("已备份损坏文件到 %s", bak_path)
    return bak_path


def _prune_corrupt_backups(path: Path) -> None:
    """清理超出保留份数的最旧损坏备份（时间戳文件名，按名排序即按时间排序）"""
    try:
        backups = sorted(path.parent.glob(f"{path.name}.corrupt.*.bak"))
        for old in backups[:-CORRUPT_BACKUP_KEEP]:
            old.unlink(missing_ok=True)
    except OSError as e:
        logger.warning("清理历史损坏备份失败: %s", e)
