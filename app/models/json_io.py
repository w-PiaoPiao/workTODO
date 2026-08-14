"""
JSON 文件读写公共工具

被 TodoStore / NoteStore 共用：
- load_json_list：读取列表数据（损坏自动备份为 .bak 并返回空列表）
- atomic_write_json：原子写入（先写 .tmp 再 replace，失败清理临时文件）
- backup_corrupted：损坏文件备份为 .bak
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

from app.models.todo_item import StoreError

logger = logging.getLogger(__name__)


def load_json_list(path: Path) -> list:
    """从 JSON 文件加载列表数据

    边界情况：
    - 文件不存在 → 返回空列表
    - JSON 解析错误 → 备份损坏文件，返回空列表
    - 顶层不是列表 → 备份文件，返回空列表
    """
    if not path.exists():
        return []

    try:
        raw = path.read_text("utf-8")
        data = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        logger.warning("JSON 解析失败 (%s)，备份文件: %s", e, path)
        backup_corrupted(path)
        return []

    if not isinstance(data, list):
        logger.warning("数据格式错误，期望列表，实际 %s", type(data).__name__)
        backup_corrupted(path)
        return []

    return data


def atomic_write_json(path: Path, data, *, indent: int = 2, ensure_ascii: bool = False) -> None:
    """原子写入 JSON 文件

    策略：写入 .tmp 临时文件 → 重命名为目标文件
    如果写入中途失败，原始文件不受影响。
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    tmp_path = path.with_suffix(".tmp")
    try:
        content = json.dumps(data, ensure_ascii=ensure_ascii, indent=indent)
        tmp_path.write_text(content, encoding="utf-8")
        # Windows 上 replace 是原子操作（同分区）
        tmp_path.replace(path)
    except (IOError, OSError, PermissionError) as e:
        # 清理临时文件
        if tmp_path.exists():
            tmp_path.unlink()
        raise StoreError(f"保存失败 ({path.name}): {e}")


def backup_corrupted(path: Path) -> None:
    """备份损坏的文件"""
    bak_path = path.with_suffix(".json.bak")
    try:
        shutil.copy2(path, bak_path)
        logger.info("已备份损坏文件到 %s", bak_path)
    except (IOError, OSError) as e:
        logger.error("备份损坏文件失败: %s", e)
