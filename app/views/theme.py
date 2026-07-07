"""
主题样式系统

集中管理全局 QSS 样式表、颜色变量和字体配置。
所有视图组件通过导入 AppTheme 获取样式常量。
支持浅色/深色模式动态切换。
"""

from app.config import AppConfig


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

    # ── 主题开关 ──────────────────────────────────────────

    @classmethod
    def switch_theme(cls, dark: bool) -> None:
        """切换浅色/深色模式。dark=True → 深色"""
        cls._current_theme = "dark" if dark else "light"
        cls.C = AppConfig.DARK_COLORS if dark else AppConfig.COLORS

    @classmethod
    def is_dark(cls) -> bool:
        """当前是否深色模式"""
        return cls._current_theme == "dark"

    @classmethod
    def apply_palette(cls, app) -> None:
        """将当前主题色应用到 QApplication palette（用于 tooltip 等）"""
        from PySide6.QtGui import QPalette, QColor
        palette = app.palette()
        palette.setColor(QPalette.ToolTipBase, QColor(cls.C["bg_card"]))
        palette.setColor(QPalette.ToolTipText, QColor(cls.C["text_primary"]))
        app.setPalette(palette)

    # ── 全局样式表 ────────────────────────────────────────

    @classmethod
    def global_qss(cls) -> str:
        """全局应用样式表"""
        C = cls.C
        return f"""
            /* 全局 */
            QWidget {{
                font-family: '{cls.FONT_FAMILY}';
                font-size: 12pt;
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
        """待办卡片样式"""
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
