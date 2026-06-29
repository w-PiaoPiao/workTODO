"""
主题样式系统

集中管理全局 QSS 样式表、颜色变量和字体配置。
所有视图组件通过导入 AppTheme 获取样式常量。
"""

from app.config import AppConfig


class AppTheme:
    """应用主题定义"""

    # ── 颜色（从配置读取，保持单源） ──────────────────────
    C = AppConfig.COLORS

    # ── 字体 ──────────────────────────────────────────────
    FONT_FAMILY = "Microsoft YaHei UI"
    FONT = {
        "title": f"14pt '{FONT_FAMILY}'",
        "body": f"12pt '{FONT_FAMILY}'",
        "small": f"10pt '{FONT_FAMILY}'",
        "body_bold": f"12pt '{FONT_FAMILY}'",
    }

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
