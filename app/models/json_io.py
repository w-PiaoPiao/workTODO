"""
JSON 文件读写公共工具

被 TodoStore / NoteStore 共用：
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
