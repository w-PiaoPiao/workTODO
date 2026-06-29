"""
应用控制器

连接数据模型与 UI 视图的核心调度器。
处理所有用户操作的业务逻辑、信号连接、异常处理。
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Qt, QTimer, QSettings
from PySide6.QtWidgets import (
    QApplication, QSystemTrayIcon, QMenu, QMessageBox, QInputDialog,
)
from PySide6.QtGui import QIcon, QAction, QPixmap, QPainter, QColor, QFont, QShortcut, QKeySequence

from app.config import AppConfig
from app.models.todo_item import TodoItem, ProgressEntry, StoreError
from app.models.todo_store import TodoStore
from app.views.main_window import MainWindow
from app.views.collapsed_view import CollapsedView
from app.views.expanded_view import ExpandedView
from app.views.archive_dialog import ArchiveDialog

logger = logging.getLogger(__name__)


class AppController(QObject):
    """应用控制器"""

    def __init__(self):
        super().__init__()

        # ── 数据层 ────────────────────────────────────────
        self._store = TodoStore()

        # ── UI 层 ─────────────────────────────────────────
        self._window = MainWindow()
        self._collapsed_view = CollapsedView()
        self._expanded_view = ExpandedView()

        # 注入视图到主窗口
        self._window.set_views(self._collapsed_view, self._expanded_view)

        # ── 系统托盘 ──────────────────────────────────────
        self._tray_icon = None
        self._setup_tray()

        # ── 加载数据 ──────────────────────────────────────
        self._load_data()

        # ── 连接信号 ──────────────────────────────────────
        self._connect_signals()

        # ── 显示窗口 ──────────────────────────────────
        self._window.show()

        # ── 恢复窗口状态（置顶、位置等）───────────────
        self._restore_window_state()

    # ── 公共访问 ──────────────────────────────────────────

    def window(self):
        """返回主窗口实例"""
        return self._window

    # ── 数据加载 ──────────────────────────────────────────

    def _load_data(self) -> None:
        """加载数据并刷新视图"""
        try:
            self._todos = self._store.load_todos()
            self._archived = self._store.load_archived()
        except StoreError as e:
            logger.error("加载数据失败: %s", e)
            self._todos = []
            self._archived = []
            self._show_error(f"数据加载失败: {e}")

        self._refresh_views()

    def _refresh_views(self) -> None:
        """刷新所有视图"""
        # 更新展开视图
        self._expanded_view.refresh(self._todos)

        # 更新计数
        active_count = len([t for t in self._todos if t.is_active])
        archived_count = len(self._archived)
        self._collapsed_view.update_count(active_count)
        self._expanded_view.update_stats(active_count, archived_count)

    # ── 信号连接 ──────────────────────────────────────────

    def _connect_signals(self) -> None:
        """连接所有视图信号到控制器槽函数"""

        # 折叠视图
        self._collapsed_view.signal_expand_clicked.connect(self._window.expand)
        self._collapsed_view.signal_quick_add_clicked.connect(
            self._on_quick_add_collapsed
        )

        # 展开视图
        self._expanded_view.signal_collapse_clicked.connect(self._window.collapse)
        self._expanded_view.signal_item_added.connect(self._on_add_item)
        self._expanded_view.signal_item_completed.connect(self._on_complete_item)
        self._expanded_view.signal_item_deleted.connect(self._on_delete_item)
        self._expanded_view.signal_progress_added.connect(self._on_add_progress)
        self._expanded_view.signal_search_changed.connect(self._on_search)
        self._expanded_view.signal_archive_view_requested.connect(
            self._on_show_archive
        )
        self._expanded_view.signal_quit_requested.connect(self._on_quit)

        # 主窗口
        self._window.signal_close_requested.connect(self._on_close_requested)

        # 置顶切换（两个视图同步）
        self._collapsed_view.signal_toggle_pin.connect(self._on_toggle_pin)
        self._expanded_view.signal_toggle_pin.connect(self._on_toggle_pin)

        # ── 键盘快捷键 ──────────────────────────────────
        self._setup_shortcuts()

    def _setup_shortcuts(self) -> None:
        """注册全局键盘快捷键"""
        QShortcut(QKeySequence("Ctrl+N"), self._window, self._on_shortcut_new)
        QShortcut(QKeySequence("Ctrl+F"), self._window, self._on_shortcut_search)

    # ── 核心业务逻辑 ──────────────────────────────────────

    def _on_add_item(self, title: str) -> None:
        """添加新待办"""
        title = title.strip()
        if not title:
            return

        item = TodoItem(title=title)
        try:
            self._store.add_item(item)
            self._todos = self._store.load_todos()
            self._refresh_views()
            # 展开模式下滚动到底部
            self._show_notification(f"已添加：{title[:20]}")
        except StoreError as e:
            self._show_error(f"添加失败: {e}")

    def _on_complete_item(self, item_id: str) -> None:
        """办结待办并归档"""
        # 找到项目
        item = next((t for t in self._todos if t.id == item_id), None)
        if not item:
            return

        from datetime import datetime, timezone, timedelta
        cst = timezone(timedelta(hours=8), "CST")
        item.completed_at = datetime.now(cst).isoformat(timespec="seconds")

        try:
            self._store.archive_item(item)
            self._todos = self._store.load_todos()
            self._archived = self._store.load_archived()
            self._refresh_views()
            self._show_notification("已办结 ✓")
        except StoreError as e:
            self._show_error(f"办结失败: {e}")

    def _on_delete_item(self, item_id: str) -> None:
        """删除待办（带确认）"""
        # 获取标题用于确认框
        item = next((t for t in self._todos if t.id == item_id), None)
        title = item.title if item else "此待办事项"

        reply = QMessageBox.question(
            self._window,
            "确认删除",
            f"确定要删除「{title[:30]}」吗？\n此操作不可恢复。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        try:
            self._store.delete_item(item_id)
            self._todos = self._store.load_todos()
            self._refresh_views()
            self._show_notification("已删除")
        except StoreError as e:
            self._show_error(f"删除失败: {e}")

    def _on_add_progress(self, item_id: str, text: str) -> None:
        """为待办添加进度记录"""
        text = text.strip()
        if not text:
            return

        item = next((t for t in self._todos if t.id == item_id), None)
        if not item:
            return

        entry = ProgressEntry(text=text)
        item.progress.append(entry)

        try:
            self._store.update_item(item)
            self._todos = self._store.load_todos()
            self._refresh_views()
        except StoreError as e:
            self._show_error(f"添加进度失败: {e}")

    def _on_search(self, query: str) -> None:
        """搜索待办（已内嵌在 expanded_view 中）"""
        # 通知 expanded_view 重新渲染
        self._expanded_view.refresh(self._todos)

    def _on_show_archive(self) -> None:
        """显示归档对话框"""
        dialog = ArchiveDialog(self._archived, self._window)
        dialog.signal_restore_item.connect(self._on_restore_item)
        dialog.exec()

    def _on_restore_item(self, item_id: str) -> None:
        """从归档恢复到待办列表"""
        try:
            restored = self._store.restore_item(item_id)
            if restored:
                self._todos = self._store.load_todos()
                self._archived = self._store.load_archived()
                self._refresh_views()
                self._show_notification(f"已恢复：{restored.title[:20]}")
        except StoreError as e:
            self._show_error(f"恢复失败: {e}")

    def _on_quick_add_collapsed(self) -> None:
        """在折叠模式下快速添加"""
        title, ok = QInputDialog.getText(
            self._window,
            "快速添加",
            "待办内容：",
        )
        if ok and title.strip():
            self._on_add_item(title.strip())

    # ── 系统托盘 ──────────────────────────────────────────

    def _setup_tray(self) -> None:
        """初始化系统托盘"""
        self._tray_icon = QSystemTrayIcon(self._window)

        # 手绘一个 📋 图标（Windows 没有主题图标）
        pixmap = QPixmap(32, 32)
        pixmap.fill(QColor(0, 0, 0, 0))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        # 蓝色圆形背景
        painter.setBrush(QColor("#0078D4"))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(1, 1, 30, 30, 6, 6)
        painter.end()
        self._tray_icon.setIcon(QIcon(pixmap))
        self._tray_icon.setToolTip("待办事项和便签")

        # 右键菜单
        menu = QMenu()
        show_action = QAction("显示/隐藏", menu)
        show_action.triggered.connect(self._on_tray_show)
        menu.addAction(show_action)

        menu.addSeparator()

        quit_action = QAction("退出", menu)
        quit_action.triggered.connect(self._on_quit)
        menu.addAction(quit_action)

        self._tray_icon.setContextMenu(menu)

        # 双击托盘恢复
        self._tray_icon.activated.connect(self._on_tray_activated)

        self._tray_icon.show()

    def _on_tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.DoubleClick:
            self._on_tray_show()

    def _on_tray_show(self) -> None:
        self._window.show()
        self._window.raise_()
        self._window.activateWindow()

    def _on_close_requested(self) -> None:
        """关闭按钮行为：最小化到托盘"""
        # 展开时先折叠
        if self._window.mode == "expanded":
            self._window.collapse()
        self._window.hide()
        self._show_notification("已最小化到系统托盘")

    def _on_quit(self) -> None:
        """退出应用"""
        self._tray_icon.hide()
        QApplication.quit()

    # ── 窗口状态管理 ──────────────────────────────────────

    def _restore_window_state(self) -> None:
        """恢复窗口置顶状态并同步按钮"""
        self._pinned = True  # 默认置顶
        settings = QSettings("Personal", "待办事项和便签")
        self._pinned = settings.value("window/pinned", True, type=bool)
        self._sync_pin_state()

    def _on_toggle_pin(self) -> None:
        """切换窗口置顶并同步所有视图"""
        self._pinned = not self._pinned
        self._window.set_always_on_top(self._pinned)
        self._sync_pin_state()
        # 持久化
        settings = QSettings("Personal", "待办事项和便签")
        settings.setValue("window/pinned", self._pinned)

    def _sync_pin_state(self) -> None:
        """同步置顶按钮样式"""
        self._collapsed_view.set_pinned(self._pinned)
        self._expanded_view.set_pinned(self._pinned)

    # ── 键盘快捷键 ──────────────────────────────────────

    def _on_shortcut_new(self) -> None:
        """Ctrl+N：新建待办"""
        if self._window.mode == "expanded":
            self._expanded_view.focus_add_input()
        else:
            self._on_quick_add_collapsed()

    def _on_shortcut_search(self) -> None:
        """Ctrl+F：搜索"""
        if self._window.mode == "expanded":
            self._expanded_view.focus_search()
        else:
            self._window.expand()
            self._expanded_view.focus_search()

    # ── 通知 ──────────────────────────────────────────────

    def _show_notification(self, message: str) -> None:
        """显示短暂的通知消息（托盘气泡）"""
        if self._tray_icon and self._tray_icon.supportsMessages():
            self._tray_icon.showMessage(
                "待办事项和便签",
                message,
                QSystemTrayIcon.Information,
                AppConfig.NOTIFICATION_DURATION_MS,
            )

    def _show_error(self, message: str) -> None:
        """显示错误对话框"""
        QMessageBox.warning(self._window, "错误", message)
