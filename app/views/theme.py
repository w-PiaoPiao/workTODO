"""
主题样式系统

集中管理全局 QSS 样式表、颜色变量和字体配置。
所有视图组件通过导入 AppTheme 获取样式常量。
支持浅色/深色模式动态切换。

通用按钮样式工厂方法集中在此，各视图组件直接引用，
避免跨文件散落重复的 QSS 字符串。
"""

from __future__ import annotations

import logging
from typing import Callable

from app.config import AppConfig

logger = logging.getLogger(__name__)


class AppTheme:
    """应用主题定义"""

    # ── 当前主题模式 ──────────────────────────────────────
    # "light" | "dark"
    _current_theme = "light"

    # ── 颜色（从配置读取，初始指向浅色方案） ──────────────
    C = AppConfig.COLORS

    # ── 字体 ──────────────────────────────────────────────
    FONT_FAMILY = "Microsoft YaHei UI"
    FONT = {
        "title": f"14pt '{FONT_FAMILY}'",
        "body": f"12pt '{FONT_FAMILY}'",
        "small": f"10pt '{FONT_FAMILY}'",
        "body_bold": f"12pt '{FONT_FAMILY}'",
    }
    _font_scale = 1.0  # 字号缩放比例（0.85 ~ 1.3）
    _qss_cache: str | None = None  # global_qss() 结果缓存（主题/字号变化时失效）

    # ── 主题观察者 ────────────────────────────────────────
    _listeners: list[Callable[[], None]] = []

    @classmethod
    def register(cls, listener: Callable[[], None]) -> None:
        """注册主题切换监听器（视图 reapply_theme 等）"""
        if listener not in cls._listeners:
            cls._listeners.append(listener)

    @classmethod
    def _notify_listeners(cls) -> None:
        """通知所有监听器刷新样式"""
        for listener in cls._listeners:
            try:
                listener()
            except Exception as e:
                logger.warning("主题监听器异常: %s", e)

    # ── 字号缩放 ──────────────────────────────────────────

    @classmethod
    def set_font_scale(cls, scale: float) -> None:
        """设置全局字号缩放比例并通知所有视图刷新"""
        cls._font_scale = max(
            AppConfig.FONT_SCALE_MIN, min(AppConfig.FONT_SCALE_MAX, float(scale)))
        cls.FONT = {
            "title": f"{round(14 * cls._font_scale, 1)}pt '{cls.FONT_FAMILY}'",
            "body": f"{round(12 * cls._font_scale, 1)}pt '{cls.FONT_FAMILY}'",
            "small": f"{round(10 * cls._font_scale, 1)}pt '{cls.FONT_FAMILY}'",
            "body_bold": f"{round(12 * cls._font_scale, 1)}pt '{cls.FONT_FAMILY}'",
        }
        cls._invalidate_qss()
        cls._notify_listeners()

    @classmethod
    def font_scale(cls) -> float:
        """当前字号缩放比例"""
        return cls._font_scale

    # ── 主题开关 ──────────────────────────────────────────

    @classmethod
    def switch_theme(cls, dark: bool) -> None:
        """切换浅色/深色模式。dark=True → 深色"""
        cls._current_theme = "dark" if dark else "light"
        cls.C = AppConfig.DARK_COLORS if dark else AppConfig.COLORS
        cls._invalidate_qss()
        cls._clear_icon_cache()
        cls._notify_listeners()

    @classmethod
    def _clear_icon_cache(cls) -> None:
        """主题颜色变化时清空 SVG 图标缓存（延迟导入避免循环依赖）"""
        try:
            from app.views.icons import AppIcons
            AppIcons.clear()
        except ImportError:
            pass

    @classmethod
    def is_dark(cls) -> bool:
        """当前是否深色模式"""
        return cls._current_theme == "dark"

    @classmethod
    def apply_palette(cls, app) -> None:
        """将当前主题色应用到 QApplication palette。

        覆盖 Window/Base/Text 等核心角色，保证依赖 QPalette 的控件
        （QScrollArea 视口、QMenu、QLineEdit 等）与主题一致，
        避免系统为深色模式而 app 主题为浅色时出现黑底/文字不清。
        """
        from PySide6.QtGui import QPalette, QColor
        C = cls.C
        palette = app.palette()
        palette.setColor(QPalette.Window, QColor(C["bg_primary"]))
        palette.setColor(QPalette.WindowText, QColor(C["text_primary"]))
        palette.setColor(QPalette.Base, QColor(C["bg_card"]))
        palette.setColor(QPalette.Text, QColor(C["text_primary"]))
        palette.setColor(QPalette.PlaceholderText, QColor(C["text_disabled"]))
        palette.setColor(QPalette.Button, QColor(C["bg_card"]))
        palette.setColor(QPalette.ButtonText, QColor(C["text_primary"]))
        palette.setColor(QPalette.Highlight, QColor(C["accent"]))
        palette.setColor(QPalette.HighlightedText, QColor("white"))
        palette.setColor(QPalette.ToolTipBase, QColor(C["bg_card"]))
        palette.setColor(QPalette.ToolTipText, QColor(C["text_primary"]))
        app.setPalette(palette)

    # ── 全局样式表 ────────────────────────────────────────

    @classmethod
    def _invalidate_qss(cls) -> None:
        """使缓存的全局样式表失效（主题/字号变化时调用）"""
        cls._qss_cache = None

    @classmethod
    def global_qss(cls) -> str:
        """全局应用样式表（结果缓存，主题/字号变化时自动失效）"""
        if cls._qss_cache is not None:
            return cls._qss_cache
        cls._qss_cache = cls._build_global_qss()
        return cls._qss_cache

    @classmethod
    def _build_global_qss(cls) -> str:
        """拼接全局样式表（较慢，仅主题/字号变化时执行一次）"""
        C = cls.C
        return f"""
            /* 全局 */
            QWidget {{
                font-family: '{cls.FONT_FAMILY}';
                font-size: {round(12 * cls._font_scale, 1)}pt;
                color: {C["text_primary"]};
            }}

            /* 滚动条 */
            QScrollBar:vertical {{
                width: 6px;
                background: transparent;
                margin: 0;
            }}
            QScrollBar::handle:vertical {{
                background: {C["border"]};
                border-radius: 3px;
                min-height: 30px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {C["text_disabled"]};
            }}
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {{
                height: 0;
            }}

            /* 输入框 */
            QLineEdit {{
                border: 1px solid {C["border"]};
                border-radius: 4px;
                padding: 6px 10px;
                background: {C["bg_card"]};
                color: {C["text_primary"]};
                selection-background-color: {C["accent"]};
            }}
            QLineEdit:focus {{
                border-color: {C["accent"]};
            }}
            QLineEdit::placeholder {{
                color: {C["text_disabled"]};
            }}

            /* 按钮 */
            QPushButton {{
                border: none;
                border-radius: 4px;
                padding: 4px 12px;
                color: {C["text_primary"]};
                background: transparent;
            }}
            QPushButton:hover {{
                background: {C["bg_hover"]};
            }}
            QPushButton:pressed {{
                background: {C["border"]};
            }}

            /* 标签 */
            QLabel {{
                color: {C["text_primary"]};
            }}

            /* 滚动区域 */
            QScrollArea {{
                border: none;
                background: transparent;
            }}

            /* 工具提示（亮底暗字，高可读性） */
            QToolTip {{
                background: {C["bg_card"]};
                color: {C["text_primary"]};
                border: 1px solid {C["border"]};
                border-radius: 4px;
                padding: 6px 10px;
                font-size: 10pt;
                max-width: 400px;
            }}

            /* 对话框 */
            QMessageBox {{
                background: {C["bg_card"]};
            }}
            QMessageBox QLabel {{
                color: {C["text_primary"]};
                background: transparent;
            }}
            QMessageBox QPushButton {{
                min-width: 80px;
                padding: 6px 16px;
                border: 1px solid {C["border"]};
                border-radius: 4px;
                background: {C["bg_card"]};
                color: {C["text_primary"]};
            }}
            QMessageBox QPushButton:hover {{
                background: {C["bg_hover"]};
            }}
        """

    @classmethod
    def card_style(cls, completed: bool = False) -> str:
        """待办卡片样式（置顶指示由内部竖条 widget 提供，见 sticky_bar_style）"""
        C = cls.C
        bg = C["bg_completed"] if completed else C["bg_card"]
        return f"""
            QFrame {{
                background: {bg};
                border-radius: 6px;
                border: 1px solid {C["border"]};
            }}
            QFrame:hover {{
                border-color: {C["accent"]};
                background: {C["bg_hover"] if not completed else bg};
            }}
        """

    @classmethod
    def sticky_bar_style(cls) -> str:
        """置顶竖条样式（卡片内部左侧 3px accent 竖条，与卡片圆角匹配）"""
        C = cls.C
        return f"""
            QFrame {{
                background: {C["accent"]};
                border: none;
                border-top-left-radius: 6px;
                border-bottom-left-radius: 6px;
            }}
        """

    @classmethod
    def progress_style(cls) -> str:
        """进度条目样式"""
        C = cls.C
        return f"""
            QFrame {{
                background: {C["bg_primary"]};
                border-radius: 3px;
                padding: 4px;
            }}
        """

    @classmethod
    def archive_title_style(cls) -> str:
        """归档标题按钮样式"""
        C = cls.C
        return f"""
            QPushButton {{
                color: {C["accent"]};
                font-size: 11pt;
                padding: 4px 8px;
            }}
            QPushButton:hover {{
                color: {C["accent_hover"]};
                text-decoration: underline;
            }}
        """

    @classmethod
    def pin_btn_style(cls, pinned: bool = True) -> str:
        """置顶按钮样式（共用，避免跨视图重复）"""
        C = cls.C
        color = C["danger"] if pinned else C["text_disabled"]
        hov_color = C["danger"] if pinned else C["text_secondary"]
        return f"""
            QPushButton {{
                font-size: 13px;
                color: {color};
                border-radius: 4px;
                padding: 2px;
                background: transparent;
            }}
            QPushButton:hover {{
                background: {C["bg_hover"]};
                color: {hov_color};
            }}
        """

    # ── 通用按钮样式工厂 ──────────────────────────────────

    @classmethod
    def icon_btn(cls, font_size: str = "14px") -> str:
        """小图标按钮（text_secondary，hover → accent + bg_hover）"""
        C = cls.C
        return f"""
            QPushButton {{
                font-size: {font_size};
                color: {C["text_secondary"]};
                border-radius: 4px;
                padding: 2px;
                background: transparent;
            }}
            QPushButton:hover {{
                background: {C["bg_hover"]};
                color: {C["accent"]};
            }}
        """

    @classmethod
    def toggle_btn(cls, active: bool) -> str:
        """开关按钮（active → accent，inactive → text_disabled，hover → accent）"""
        C = cls.C
        color = C["accent"] if active else C["text_disabled"]
        return f"""
            QPushButton {{
                font-size: 14px;
                color: {color};
                border-radius: 4px;
                padding: 2px;
                background: transparent;
            }}
            QPushButton:hover {{
                background: {C["bg_hover"]};
                color: {C["accent"]};
            }}
        """

    @classmethod
    def outline_btn(cls, max_width: str = "") -> str:
        """线框按钮（accent 色边框，hover 反白）"""
        C = cls.C
        mw = f"max-width: {max_width};" if max_width else ""
        return f"""
            QPushButton {{
                font: {cls.FONT["small"]};
                color: {C["accent"]};
                border: 1px solid {C["accent"]};
                border-radius: 3px;
                padding: 2px 6px;
                background: transparent;
                {mw}
            }}
            QPushButton:hover {{
                background: {C["accent"]};
                color: white;
            }}
        """

    @classmethod
    def danger_btn(cls, font_size: str = "12px") -> str:
        """危险按钮（透明，hover → danger 色）"""
        C = cls.C
        return f"""
            QPushButton {{
                font-size: {font_size};
                color: {C["text_disabled"]};
                border: none;
                padding: 0;
                background: transparent;
            }}
            QPushButton:hover {{
                color: {C["danger"]};
            }}
        """

    @classmethod
    def danger_fill_btn(cls) -> str:
        """危险填充按钮（hover 变红底白字）"""
        C = cls.C
        return f"""
            QPushButton {{
                font: {cls.FONT["small"]};
                color: {C["text_disabled"]};
                border-radius: 4px;
                padding: 2px 8px;
                background: transparent;
            }}
            QPushButton:hover {{
                background: {C["danger"]};
                color: white;
            }}
        """

    @classmethod
    def accent_fill_btn(cls, font_size: str = "18px") -> str:
        """强调填充按钮（bg_hover 底 + accent 色，hover 反白）"""
        C = cls.C
        return f"""
            QPushButton {{
                font-size: {font_size};
                color: {C["accent"]};
                border-radius: 4px;
                padding: 2px;
                background: {C["bg_hover"]};
            }}
            QPushButton:hover {{
                background: {C["accent"]};
                color: white;
            }}
        """

    @classmethod
    def text_link_btn(cls) -> str:
        """文字链接按钮（accent 色，hover bg_hover）"""
        C = cls.C
        return f"""
            QPushButton {{
                font: {cls.FONT["small"]};
                color: {C["accent"]};
                padding: 4px 8px;
                border-radius: 4px;
                background: transparent;
            }}
            QPushButton:hover {{
                background: {C["bg_hover"]};
            }}
        """

    @classmethod
    def close_btn(cls) -> str:
        """关闭按钮（hover 变红）"""
        C = cls.C
        return f"""
            QPushButton {{
                font-size: 14px;
                color: {C["text_secondary"]};
                border-radius: 4px;
                background: transparent;
            }}
            QPushButton:hover {{
                background: {C["bg_hover"]};
                color: {C["danger"]};
            }}
        """

    @classmethod
    def search_bar_style(cls) -> str:
        """搜索输入框（accent 色聚焦边框）"""
        C = cls.C
        return f"""
            QLineEdit {{
                border: 1px solid {C["accent"]};
                border-radius: 4px;
                padding: 6px 10px;
                background: {C["bg_card"]};
            }}
        """

    @classmethod
    def progress_input_style(cls) -> str:
        """进度输入框（无边框，聚焦变 primary）"""
        C = cls.C
        return f"""
            QLineEdit {{
                border: none;
                font: {cls.FONT["small"]};
                color: {C["text_secondary"]};
                padding: 2px 4px;
                background: transparent;
            }}
            QLineEdit:focus {{
                color: {C["text_primary"]};
            }}
        """

    @classmethod
    def edit_input_style(cls) -> str:
        """内联编辑输入框"""
        C = cls.C
        return f"""
            QLineEdit {{
                border: 1px solid {C["accent"]};
                border-radius: 3px;
                padding: 2px 6px;
                font: {cls.FONT["body"]};
            }}
        """

    # ── 对话框通用样式（归档对话框等） ────────────────────

    @classmethod
    def pet_badge_style(cls) -> str:
        """桌宠计数角标（accent 底白字，白色描边保证两种主题都醒目）"""
        C = cls.C
        radius = AppConfig.PET_BADGE_SIZE // 2
        return f"""
            QLabel {{
                font: {cls.FONT["small"]};
                font-weight: bold;
                color: white;
                background: {C["accent"]};
                border-radius: {radius}px;
                border: 2px solid white;
                padding: 0px 4px;
            }}
        """

    @classmethod
    def pet_thumb_btn(cls, selected: bool) -> str:
        """桌宠形象缩略图按钮（选中 → accent 描边）"""
        C = cls.C
        border = f"2px solid {C['accent']}" if selected else f"1px solid {C['border']}"
        return f"""
            QPushButton {{
                background: transparent;
                border: {border};
                border-radius: 6px;
                padding: 1px;
            }}
            QPushButton:hover {{
                border-color: {C["accent"]};
            }}
        """

    @classmethod
    def dialog_frame_style(cls, selector: str = "QDialog") -> str:
        """对话框整体框架"""
        C = cls.C
        return f"""
            {selector} {{
                background: {C["bg_card"]};
                border: 1px solid {C["border"]};
                border-radius: 8px;
            }}
        """

    @classmethod
    def dialog_title_bar_style(cls, selector: str = "QWidget") -> str:
        """对话框标题栏"""
        C = cls.C
        return f"""
            {selector} {{
                background: {C["bg_primary"]};
                border-bottom: 1px solid {C["border"]};
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
            }}
        """

    @classmethod
    def dialog_input_style(cls) -> str:
        """对话框搜索/输入框"""
        C = cls.C
        return f"""
            QLineEdit {{
                border: 1px solid {C["border"]};
                border-radius: 4px;
                padding: 6px 10px;
                margin: 8px 12px;
                background: {C["bg_card"]};
            }}
            QLineEdit:focus {{ border-color: {C["accent"]}; }}
        """

    @classmethod
    def dialog_footer_style(cls) -> str:
        """对话框底部统计栏"""
        C = cls.C
        return f"""
            font: {cls.FONT["small"]};
            color: {C["text_secondary"]};
            background: {C["bg_primary"]};
            border-top: 1px solid {C["border"]};
            border-bottom-left-radius: 8px;
            border-bottom-right-radius: 8px;
        """

    @classmethod
    def archive_card_style(cls) -> str:
        """归档条目卡片"""
        C = cls.C
        return f"""
            QFrame {{
                background: {C["bg_completed"]};
                border-radius: 6px;
                border: 1px solid {C["border"]};
            }}
        """

    # ── 截止日期 / 标签 ──────────────────────────────────

    @classmethod
    def date_badge_style(cls, overdue: bool) -> str:
        """截止日期徽标（过期红色，未过期蓝色）"""
        C = cls.C
        color = C["danger"] if overdue else C["accent"]
        bg = C["danger"] if overdue else C["bg_hover"]
        return f"""
            QLabel {{
                font: {cls.FONT["small"]};
                color: {color};
                background: {bg};
                border-radius: 8px;
                padding: 1px 6px;
            }}
        """

    @classmethod
    def tag_chip_style(cls) -> str:
        """标签小圆片"""
        C = cls.C
        return f"""
            QLabel {{
                font: {cls.FONT["small"]};
                color: {C["accent"]};
                background: {C["bg_hover"]};
                border-radius: 7px;
                padding: 0px 6px;
            }}
        """

    @classmethod
    def tag_filter_btn(cls, active: bool) -> str:
        """标签筛选按钮"""
        C = cls.C
        if active:
            return f"""
                QPushButton {{
                    font: {cls.FONT["small"]};
                    color: white;
                    background: {C["accent"]};
                    border-radius: 9px;
                    padding: 2px 10px;
                }}
            """
        return f"""
            QPushButton {{
                font: {cls.FONT["small"]};
                color: {C["text_secondary"]};
                background: {C["bg_card"]};
                border: 1px solid {C["border"]};
                border-radius: 9px;
                padding: 2px 10px;
            }}
            QPushButton:hover {{
                color: {C["accent"]};
                border-color: {C["accent"]};
            }}
        """

    # ── 便签 ──────────────────────────────────────────────

    @classmethod
    def note_card_style(cls, color_key: str) -> str:
        """彩色便签卡片（color_key 见 AppConfig.NOTE_COLORS）"""
        colors = AppConfig.NOTE_COLORS.get(color_key)
        bg = colors[0] if not cls.is_dark() else colors[1]
        border = cls.C["border"] if not cls.is_dark() else "#555555"
        return f"""
            QFrame {{
                background: {bg};
                border-radius: 6px;
                border: 1px solid {border};
            }}
            QFrame:hover {{
                border-color: {cls.C["accent"]};
            }}
        """

    @classmethod
    def note_text_style(cls) -> str:
        """便签内容文本"""
        return f"""
            font: {cls.FONT["body"]};
            color: {cls.C["text_primary"]};
            background: transparent;
        """

    @classmethod
    def note_meta_style(cls) -> str:
        """便签时间元信息"""
        return f"""
            font: {cls.FONT["small"]};
            color: {cls.C["text_disabled"]};
            background: transparent;
        """

    @classmethod
    def note_color_btn(cls, color_key: str, selected: bool) -> str:
        """便签颜色选择圆点按钮"""
        colors = AppConfig.NOTE_COLORS.get(color_key, ("#FFFFFF", "#2D2D2D"))
        bg = colors[0] if not cls.is_dark() else colors[1]
        border = "2px solid " + cls.C["accent"] if selected else f"1px solid {cls.C['border']}"
        return f"""
            QPushButton {{
                background: {bg};
                border: {border};
                border-radius: 10px;
                min-width: 20px;
                max-width: 20px;
                min-height: 20px;
                max-height: 20px;
                padding: 0;
            }}
        """

    # ── 标签页 / 面板 ─────────────────────────────────────

    @classmethod
    def tab_bar_style(cls) -> str:
        """待办/便签切换标签栏"""
        C = cls.C
        return f"""
            QTabBar::tab {{
                font: {cls.FONT["small"]};
                color: {C["text_secondary"]};
                background: transparent;
                padding: 4px 16px;
                border-bottom: 2px solid transparent;
            }}
            QTabBar::tab:selected {{
                color: {C["accent"]};
                border-bottom: 2px solid {C["accent"]};
            }}
            QTabBar::tab:hover {{
                color: {C["text_primary"]};
            }}
        """

    @classmethod
    def menu_style(cls) -> str:
        """弹出菜单样式（标题栏 ⋯ 溢出菜单）"""
        C = cls.C
        return f"""
            QMenu {{
                background: {C["bg_card"]};
                border: 1px solid {C["border"]};
                border-radius: 6px;
                padding: 4px;
            }}
            QMenu::item {{
                padding: 6px 24px 6px 10px;
                border-radius: 4px;
                color: {C["text_primary"]};
                background: transparent;
            }}
            QMenu::item:selected {{
                background: {C["bg_hover"]};
            }}
            QMenu::separator {{
                height: 1px;
                background: {C["border"]};
                margin: 4px 8px;
            }}
        """

    @classmethod
    def popup_panel_style(cls) -> str:
        """弹出面板（设置/统计等）"""
        C = cls.C
        return f"""
            QFrame {{
                background: {C["bg_card"]};
                border: 1px solid {C["border"]};
                border-radius: 6px;
            }}
            QLabel {{
                background: transparent;
            }}
        """

    @classmethod
    def panel_label_style(cls) -> str:
        """面板内文字标签"""
        C = cls.C
        return f"""
            font: {cls.FONT["small"]};
            color: {C["text_primary"]};
            background: transparent;
        """
