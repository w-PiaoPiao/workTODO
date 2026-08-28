"""
开机自启服务

职责：Windows 注册表 Run 键的读写（含 VBS 脚本包装，避免开机弹 cmd 窗口）。
纯逻辑无视图依赖，控制器负责 UI 反馈。
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from app.config import AppConfig

logger = logging.getLogger(__name__)

REG_KEY = r"HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run"
REG_ENTRY = "待办事项和便签"

# 预先捕获，避免测试 monkeypatch QSettings 后 NativeFormat 被遮蔽
_NATIVE_FORMAT = QSettings.NativeFormat


class AutostartService:
    """开机自启：注册表 Run 键读写"""

    def is_enabled(self) -> bool:
        """读取当前开机自启状态"""
        if not AppConfig.IS_WINDOWS:
            return False
        try:
            reg = QSettings(REG_KEY, _NATIVE_FORMAT)
            return bool(reg.value(REG_ENTRY, ""))
        except Exception:
            return False

    def set_enabled(self, enabled: bool) -> None:
        """切换开机自启状态（成功返回 None，失败抛异常由调用方处理）"""
        if not AppConfig.IS_WINDOWS:
            raise RuntimeError("仅支持 Windows 系统")

        reg = QSettings(REG_KEY, _NATIVE_FORMAT)
        if enabled:
            # 获取当前可执行文件路径
            if getattr(sys, "frozen", False):
                # PyInstaller 打包模式：使用 VBS 脚本包装，避免开机弹 cmd 窗口
                exe_path = QApplication.instance().applicationFilePath()
                vbs_path = AppConfig.DATA_DIR / "startup.vbs"
                vbs_content = f'CreateObject("WScript.Shell").Run """{exe_path}""", 0, False'
                # WSH 不识别 UTF-8 BOM（报 Invalid character），必须用 utf-16（LE+BOM）
                vbs_path.write_text(vbs_content, encoding="utf-16")
                app_path = f'"{vbs_path}"'
            else:
                # 源码开发模式：使用 pythonw main.py（避免开机弹 cmd 窗口）
                script = Path(__file__).resolve().parent.parent.parent / "main.py"
                pythonw = Path(sys.executable).with_name("pythonw.exe")
                app_path = f'"{pythonw}" "{script}"'
            reg.setValue(REG_ENTRY, app_path)
            logger.info("开机自启写入注册表: %s = %s", REG_ENTRY, app_path)
        else:
            reg.remove(REG_ENTRY)
            vbs_path = AppConfig.DATA_DIR / "startup.vbs"
            if vbs_path.exists():
                vbs_path.unlink()
            logger.info("已从注册表移除开机自启条目: %s", REG_ENTRY)
        reg.sync()
