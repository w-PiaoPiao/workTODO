"""
悬浮待办事项和便签 — 启动入口

用法：
    python main.py          # 正常启动
    python main.py --debug  # 调试模式（输出详细日志）
"""

import sys
import logging


def main():
    # ── 解析参数 ──────────────────────────────────────────
    debug = "--debug" in sys.argv

    # ── 日志配置 ──────────────────────────────────────────
    level = logging.DEBUG if debug else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # ── 启动 Qt 应用 ──────────────────────────────────────
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt

    app = QApplication(sys.argv)
    app.setApplicationName("待办事项和便签")
    app.setOrganizationName("Personal")
    app.setQuitOnLastWindowClosed(False)

    # 高 DPI 支持
    app.setStyle("Fusion")

    # ── 启动控制器 ────────────────────────────────────────
    from app.controllers.app_controller import AppController

    controller = AppController()

    # ── 窗口阴影（必须在窗口 show() 之后应用，避开 PySide6 模块内 bug）─
    from PySide6.QtWidgets import QGraphicsDropShadowEffect
    from PySide6.QtGui import QColor
    shadow = QGraphicsDropShadowEffect()
    shadow.setBlurRadius(15)
    shadow.setOffset(0, 4)
    shadow.setColor(QColor(0, 0, 0, 80))
    controller.window().setGraphicsEffect(shadow)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
