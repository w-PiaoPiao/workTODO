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
    from PySide6.QtCore import Qt, QSharedMemory

    app = QApplication(sys.argv)
    app.setApplicationName("待办事项和便签")
    app.setOrganizationName("Personal")
    app.setQuitOnLastWindowClosed(False)

    # ── 单实例锁：防止同时打开多个窗口 ────────────────────
    _lock = QSharedMemory("待办事项和便签-SingleInstanceLock")
    if not _lock.create(1):
        # 已有实例在运行，直接退出
        sys.exit(0)

    # 高 DPI 支持
    app.setStyle("Fusion")

    # ── 全局样式表（必须在 QApplication 级别，QToolTip 是顶层窗口，
    #    不会继承 MainWindow 上的 setStyleSheet）─────────────────
    from app.views.theme import AppTheme
    app.setStyleSheet(AppTheme.global_qss())

    # ── Windows 下 QSS background 无法控制 tooltip 实际渲染
    #    （Windows 用 GDI 画 tooltip 窗口），必须通过 QPalette 角色设置 ──
    AppTheme.apply_palette(app)

    # ── 终极方案：自定义 tooltip ─────────────────────────
    # 若 QApplication QSS + QPalette 仍无法覆盖 Windows 原生 tooltip 黑底，
    # 则拦截所有 QEvent.ToolTip，用白底 QFrame 自己显示。
    from app.views.custom_tooltip import install_custom_tooltip
    install_custom_tooltip(app)

    # ── 启动控制器 ────────────────────────────────────────
    from app.controllers.app_controller import AppController

    controller = AppController()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
