"""
应用配置常量

所有配置集中在单处，方便管理和修改。
"""

import os
import sys
from pathlib import Path


class AppConfig:
    """应用全局配置"""

    # 应用信息
    APP_NAME = "待办事项和便签"
    APP_VERSION = "1.0.0"

    # ── 数据路径 ──────────────────────────────────────────────
    # 数据存储目录：优先使用环境变量覆盖，默认在用户数据目录下
    _env_override = os.environ.get("FLOATING_TODO_DATA_DIR")
    if _env_override:
        DATA_DIR = Path(_env_override)
    else:
        # 使用 appdirs 定位标准数据目录
        try:
            import appdirs
            DATA_DIR = Path(appdirs.user_data_dir(APP_NAME, False))
        except ImportError:
            # fallback：本地 data 文件夹
            DATA_DIR = Path(__file__).resolve().parent.parent / "data"

    # 数据文件
    TODOS_FILE = "todos.json"
    ARCHIVE_FILE = "archive.json"

    @classmethod
    def todos_path(cls) -> Path:
        """活跃待办文件路径（确保目录存在）"""
        cls.DATA_DIR.mkdir(parents=True, exist_ok=True)
        return cls.DATA_DIR / cls.TODOS_FILE

    @classmethod
    def archive_path(cls) -> Path:
        """归档文件路径（确保目录存在）"""
        cls.DATA_DIR.mkdir(parents=True, exist_ok=True)
        return cls.DATA_DIR / cls.ARCHIVE_FILE

    # ── 窗口尺寸与位置 ────────────────────────────────────────
    COLLAPSED_WIDTH = 320
    COLLAPSED_HEIGHT = 48
    EXPANDED_WIDTH = 400
    EXPANDED_HEIGHT = 520
    ANIMATION_MS = 200          # 折叠/展开动画时长
    SCREEN_MARGIN = 20          # 屏幕边缘留白

    # ── 行为选项 ──────────────────────────────────────────────
    AUTO_ARCHIVE_DAYS = 30      # 自动归档天数阈值
    MAX_PROGRESS_COLLAPSED = 3  # 进度条折叠阈值
    SEARCH_DEBOUNCE_MS = 300    # 搜索防抖毫秒
    NOTIFICATION_DURATION_MS = 2000  # 通知显示时长

    # ── 颜色 ──────────────────────────────────────────────────
    COLORS = {
        "bg_primary": "#F3F3F3",
        "bg_card": "#FFFFFF",
        "bg_hover": "#E5F3FF",
        "bg_completed": "#F0F0F0",
        "text_primary": "#1A1A1A",
        "text_secondary": "#666666",
        "text_disabled": "#AAAAAA",
        "accent": "#0078D4",
        "accent_hover": "#106EBE",
        "success": "#107C10",
        "danger": "#D13438",
        "warning": "#FF8C00",
        "border": "#E0E0E0",
    }

    # ── 平台检测 ──────────────────────────────────────────────
    IS_WINDOWS = sys.platform == "win32"
