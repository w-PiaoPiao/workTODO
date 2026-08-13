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
    APP_VERSION = "0.4.3"

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
    NOTES_FILE = "notes.json"

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

    @classmethod
    def notes_path(cls) -> Path:
        """便签文件路径（确保目录存在）"""
        cls.DATA_DIR.mkdir(parents=True, exist_ok=True)
        return cls.DATA_DIR / cls.NOTES_FILE

    # ── 窗口尺寸与位置 ────────────────────────────────────────
    COLLAPSED_WIDTH = 320
    COLLAPSED_HEIGHT = 48
    EXPANDED_WIDTH = 400
    EXPANDED_HEIGHT = 520
    EXPANDED_MIN_WIDTH = 300
    EXPANDED_MIN_HEIGHT = 200
    EXPANDED_MAX_WIDTH = 1200
    EXPANDED_MAX_HEIGHT = 1080
    ANIMATION_MS = 200          # 折叠/展开动画时长
    SCREEN_MARGIN = 20          # 屏幕边缘留白

    # ── 行为选项 ──────────────────────────────────────────────
    AUTO_ARCHIVE_DAYS = 30      # 自动归档天数阈值
    MAX_PROGRESS_COLLAPSED = 3  # 进度条折叠阈值
    SEARCH_DEBOUNCE_MS = 300    # 搜索防抖毫秒
    NOTIFICATION_DURATION_MS = 2000  # 通知显示时长
    SAVE_DEBOUNCE_MS = 500      # 数据落盘防抖毫秒

    # ── 截止日期提醒 ──────────────────────────────────────────
    DUE_REMIND_HOUR = 9         # 每天检查截止日期提醒的时间（时）
    DUE_REMIND_CHECK_MS = 3600_000  # 运行期间提醒检查间隔（1 小时）

    # ── 窗口透明度 ──────────────────────────────────────────────
    WINDOW_OPACITY_DEFAULT = 1.0     # 默认完全不透明
    WINDOW_OPACITY_MIN = 0.3         # 最小透明度
    WINDOW_OPACITY_MAX = 1.0         # 最大透明度

    # ── 字号缩放 ──────────────────────────────────────────────
    FONT_SCALE_DEFAULT = 1.0     # 默认字号比例
    FONT_SCALE_MIN = 0.85        # 最小字号比例
    FONT_SCALE_MAX = 1.3         # 最大字号比例

    # ── 便签颜色（key → (浅色背景, 深色背景, 名称)） ──────────
    NOTE_COLORS = {
        "yellow": ("#FFF3B8", "#4A4218", "黄色"),
        "blue":   ("#C7E8FF", "#17374F", "蓝色"),
        "green":  ("#D4F5D0", "#1B3D1C", "绿色"),
        "pink":   ("#FFD6E0", "#4A1A28", "粉色"),
        "white":  ("#FFFFFF", "#2D2D2D", "白色"),
    }

    # ── 贴顶隐藏 ──────────────────────────────────────────────
    STICK_TO_TOP_PEEK_HEIGHT = 6    # 隐藏后露出的像素高度
    STICK_TO_TOP_THRESHOLD = 10     # 判定"贴顶部"的阈值（像素）
    STICK_RESTORE_Y_MARGIN = 6      # 恢复时距屏幕顶部的像素（标题栏完整可见）
    STICK_HOVER_DELAY_MS = 150      # 鼠标悬停后弹出的延迟（毫秒）
    STICK_HIDE_DELAY_MS = 500       # 鼠标离开后隐藏的延迟（毫秒）

    # ── 颜色（浅色） ──────────────────────────────────────────
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

    # ── 颜色（深色 / Windows 11 dark 风格） ─────────────────
    DARK_COLORS = {
        "bg_primary": "#1E1E1E",
        "bg_card": "#2D2D2D",
        "bg_hover": "#3D3D3D",
        "bg_completed": "#262626",
        "text_primary": "#E0E0E0",
        "text_secondary": "#A0A0A0",
        "text_disabled": "#666666",
        "accent": "#60CDFF",
        "accent_hover": "#4EC2F0",
        "success": "#6CCB5F",
        "danger": "#FF5F52",
        "warning": "#FFB800",
        "border": "#404040",
    }

    # ── 桌宠（折叠模式） ──────────────────────────────────────
    PET_WIDTH = 140             # 桌宠窗口宽度
    PET_HEIGHT = 140            # 桌宠窗口高度
    PET_BADGE_SIZE = 22         # 计数角标尺寸
    PET_CLICK_THRESHOLD = 8     # 单击判定最大位移（像素，超过视为拖拽）
    PET_CANVAS_MARGIN = 12      # 绘制边距（容纳漂浮/跳跃超程，避免裁剪）
    PET_FLOAT_MS = 1600         # 漂浮动画单程时长（毫秒）
    PET_FLOAT_DELTA = 5         # 漂浮幅度（像素）
    PET_BREATH_MS = 1800        # 呼吸动画单程时长（毫秒）
    PET_BREATH_RATIO = 0.05     # 呼吸缩放比例（5%）
    PET_JUMP_HEIGHT = 12        # 跳跃动作高度（像素，≤ CANVAS_MARGIN）
    PET_IDLE_ACTION_MIN_MS = 6000    # 随机小动作最小间隔
    PET_IDLE_ACTION_MAX_MS = 14000   # 随机小动作最大间隔
    PET_WHITE_SEED_THRESHOLD = 245   # 白底种子点判定阈值（RGB ≥）
    PET_WHITE_FLOOD_THRESH = 25      # floodfill 容差（吃掉 JPG 压缩噪点）
    PET_PROCESSED_SIZE = 512         # 去白底处理前缩放尺寸
    PET_SUBDIR = "pets"         # 素材目录名（resources 与 data 下同名）

    # ── 平台检测 ──────────────────────────────────────────────
    IS_WINDOWS = sys.platform == "win32"

    @classmethod
    def pets_dir(cls) -> Path:
        """用户桌宠素材目录（数据目录下，打包后可自行增补）"""
        path = cls.DATA_DIR / cls.PET_SUBDIR
        path.mkdir(parents=True, exist_ok=True)
        return path

    @classmethod
    def resource_path(cls, name: str) -> Path:
        """定位内置资源文件（兼容 PyInstaller 打包后的临时解压目录）"""
        if getattr(sys, "_MEIPASS", None):
            return Path(sys._MEIPASS) / name
        return Path(__file__).resolve().parent.parent / name
