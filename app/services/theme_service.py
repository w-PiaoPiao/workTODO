"""
主题服务

职责：浅色/深色/跟随系统 三态管理、系统主题注册表读取、30 秒轮询跟随。
与视图解耦：应用主题后通过 signal_theme_applied(mode) 通知控制器同步视图按钮。

初始化时序约定：控制器在创建任何视图前先构造 ThemeService
（内部会立即按持久化偏好设定 AppTheme 颜色），视图构建完成后调用 apply()
完成全局样式应用，避免启动闪烁。
"""

from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import QObject, QSettings, QTimer, Signal

from app.config import AppConfig
from app.views.custom_tooltip import CustomTooltip
from app.views.theme import AppTheme

logger = logging.getLogger(__name__)

# 系统主题注册表
THEME_REG_KEY = (
    r"HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
)
THEME_REG_VALUE = "AppsUseLightTheme"

# QSettings 键
SETTINGS_MODE_KEY = "theme/mode"
SETTINGS_OLD_DARK_KEY = "theme/dark"
SETTINGS_FONT_SCALE_KEY = "ui/font_scale"

# 预先捕获，避免测试 monkeypatch QSettings 后 NativeFormat 被遮蔽
_NATIVE_FORMAT = QSettings.NativeFormat


class ThemeService(QObject):
    """主题模式管理：浅色 / 深色 / 自动（跟随系统）"""

    signal_theme_applied = Signal(str)  # mode: "light" | "dark" | "auto"

    # 主题模式轮换顺序
    THEME_CYCLE = ["light", "dark", "auto"]

    def __init__(self, parent=None):
        super().__init__(parent)

        self._theme_mode = self._load_mode()

        # 在视图创建前先设定主题颜色（无监听器，仅更新颜色常量）
        dark = (self._system_theme_is_dark()
                if self._theme_mode == "auto"
                else self._theme_mode == "dark")
        AppTheme.switch_theme(dark)

        # 字号缩放偏好
        settings = QSettings("Personal", "待办事项和便签")
        font_scale = settings.value(
            SETTINGS_FONT_SCALE_KEY, AppConfig.FONT_SCALE_DEFAULT, type=float)
        if font_scale != AppConfig.FONT_SCALE_DEFAULT:
            AppTheme.set_font_scale(font_scale)

        # 30 秒轮询系统主题（自动模式）
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(30_000)
        self._poll_timer.timeout.connect(self._poll_system_theme)
        self._poll_timer.start()

    # ── 对外接口 ──────────────────────────────────────────

    @property
    def mode(self) -> str:
        """当前主题模式（"light" | "dark" | "auto"）"""
        return self._theme_mode

    @mode.setter
    def mode(self, value: str) -> None:
        """设置主题模式（不持久化，测试/初始化用）"""
        if value in self.THEME_CYCLE:
            self._theme_mode = value

    def apply(self) -> None:
        """按当前模式应用主题（幂等：主题未变时跳过监听器通知）"""
        dark = (self._system_theme_is_dark()
                if self._theme_mode == "auto"
                else self._theme_mode == "dark")
        if dark != AppTheme.is_dark():
            AppTheme.switch_theme(dark)  # 通知各视图监听器刷新自身样式
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        app.setStyleSheet(AppTheme.global_qss())
        AppTheme.apply_palette(app)
        CustomTooltip.apply_theme_style()
        self.signal_theme_applied.emit(self._theme_mode)

    def cycle(self) -> None:
        """主题模式三态轮换：浅色 → 深色 → 自动，并持久化"""
        order = {"light": "dark", "dark": "auto", "auto": "light"}
        self.set_mode(order.get(self._theme_mode, "light"))

    def set_mode(self, mode: str) -> None:
        """直接设置主题模式（浅色/深色/跟随系统）并持久化"""
        if mode not in self.THEME_CYCLE or mode == self._theme_mode:
            return
        self._theme_mode = mode
        settings = QSettings("Personal", "待办事项和便签")
        settings.setValue(SETTINGS_MODE_KEY, self._theme_mode)
        settings.remove(SETTINGS_OLD_DARK_KEY)  # 清理旧版本键
        self.apply()

    def set_font_scale(self, scale: float) -> None:
        """字号缩放应用并持久化"""
        AppTheme.set_font_scale(scale)  # 通知各视图监听器刷新自身样式
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        app.setStyleSheet(AppTheme.global_qss())
        CustomTooltip.apply_theme_style()
        QSettings("Personal", "待办事项和便签").setValue(
            SETTINGS_FONT_SCALE_KEY, scale)

    # ── 内部实现 ──────────────────────────────────────────

    def _load_mode(self) -> str:
        """从持久化存储加载主题模式（兼容旧版本布尔值）"""
        settings = QSettings("Personal", "待办事项和便签")
        mode = settings.value(SETTINGS_MODE_KEY, "")
        if not mode:
            old_dark = settings.value(SETTINGS_OLD_DARK_KEY, False, type=bool)
            mode = "dark" if old_dark else "auto"
        return mode

    def _poll_system_theme(self) -> None:
        """自动模式下轮询系统主题变化并即时切换"""
        if self._theme_mode != "auto":
            return
        if self._system_theme_is_dark() != AppTheme.is_dark():
            self.apply()

    @staticmethod
    def _system_theme_is_dark() -> bool:
        """读取 Windows 系统主题（深色返回 True）"""
        if not AppConfig.IS_WINDOWS:
            return False
        try:
            reg = QSettings(THEME_REG_KEY, _NATIVE_FORMAT)
            light = reg.value(THEME_REG_VALUE, 1, type=int)
            return light == 0
        except Exception:
            return False
