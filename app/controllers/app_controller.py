"""
应用控制器

连接数据模型、系统服务与 UI 视图的核心协调器。
处理待办/便签的业务逻辑、信号连接、异常处理。
系统级功能（托盘/主题/自启/提醒）已拆至 app/services/。
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, QSettings
from PySide6.QtWidgets import (
    QApplication, QMessageBox, QInputDialog,
    QFileDialog,
)
from PySide6.QtGui import QShortcut, QKeySequence, QCursor

from app.config import AppConfig
from app.models.todo_item import TodoItem, ProgressEntry, StoreError, CST
from app.models.todo_store import TodoStore
from app.models.note import Note, NoteStore
from app.views.theme import AppTheme
from app.views.main_window import MainWindow
from app.views.pet_view import PetView, discover_pets
from app.views.expanded_view import ExpandedView
from app.views.archive_dialog import ArchiveDialog
from app.services.theme_service import ThemeService
from app.services.tray_service import TrayService
from app.services.reminder_service import ReminderService
from app.services.autostart_service import AutostartService

logger = logging.getLogger(__name__)


class AppController(QObject):
    """应用控制器"""

    def __init__(self):
        super().__init__()

        # ── 系统服务（主题服务先创建，在视图构建前设定主题色） ──
        self._theme = ThemeService()

        app = QApplication.instance()
        app.setStyleSheet(AppTheme.global_qss())
        AppTheme.apply_palette(app)

        # ── 数据层 ────────────────────────────────────────
        self._store = TodoStore()
        self._note_store = NoteStore()

        # ── UI 层 ─────────────────────────────────────────
        self._window = MainWindow()
        self._pet_view = PetView()
        self._expanded_view = ExpandedView()

        # 注入视图到主窗口
        self._window.set_views(self._pet_view, self._expanded_view)

        # ── 系统服务（托盘 / 自启 / 提醒） ─────────────────
        self._tray = TrayService(self._window)
        self._autostart = AutostartService()
        self._reminder = ReminderService(self)
        self._reminder.configure(lambda: self._todos, self._show_notification)

        # ── 桌宠形象 ──────────────────────────────────────
        self._pets = discover_pets()
        settings = QSettings("Personal", "待办事项和便签")
        pet_id = settings.value("window/pet", "")
        self._pet_view.load_pet(pet_id)
        self._expanded_view.set_pets(self._pets, self._pet_view.pet_id())

        # ── 桌宠空闲动画开关（右键菜单，持久化） ─────────
        pet_animation = settings.value(
            "window/pet_animation", True, type=bool)
        self._pet_view.set_animation_enabled(pet_animation)
        self._tray.signal_show_requested.connect(self._on_tray_show)
        self._tray.signal_quit_requested.connect(self._on_quit)
        self._theme.signal_theme_applied.connect(self._on_theme_applied)

        # ── 搜索 / 标签状态 ───────────────────────────────
        self._search_query = ""
        self._active_tag = ""
        self._search_index: dict[str, str] | None = None   # item_id → 小写搜索文本
        self._search_index_list_id: int | None = None      # 索引对应的 _todos 列表身份

        # ── 数据落盘防抖 ──────────────────────────────────
        self._save_timer = QTimer()
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(AppConfig.SAVE_DEBOUNCE_MS)
        self._save_timer.timeout.connect(self._flush_store)
        app.aboutToQuit.connect(self._flush_store)

        # ── 加载数据 ──────────────────────────────────────
        self._load_data()

        # ── 连接信号 ──────────────────────────────────────
        self._connect_signals()

        # ── 同步视图初始状态 ──────────────────────────────
        self._theme.apply()
        self._expanded_view.set_font_scale_value(AppTheme.font_scale())
        self._expanded_view.set_autostart(self._autostart.is_enabled())

        # ── 显示窗口 ──────────────────────────────────
        self._window.show()
        self._window.start_collapsed_idle()

        # ── 恢复窗口状态（置顶、位置等）───────────────
        self._restore_window_state()

        # ── 启动时检查截止日期提醒 ─────────────────────
        self._check_due_reminders()

    # ── 公共访问 ──────────────────────────────────────────

    def window(self):
        """返回主窗口实例"""
        return self._window

    # ── 数据加载 ──────────────────────────────────────────

    def _load_data(self) -> None:
        """加载数据并刷新视图"""
        try:
            # 自动归档超过 30 天的旧项目（随后立即落盘）
            self._store.auto_archive_old(AppConfig.AUTO_ARCHIVE_DAYS)
            self._store.flush()

            self._todos = self._store.load_todos()
            self._archived = self._store.load_archived()
            self._notes = self._note_store.load_notes()
        except StoreError as e:
            logger.error("加载数据失败: %s", e)
            self._todos = []
            self._archived = []
            self._notes = []
            self._show_error(f"数据加载失败: {e}")

        self._refresh_views()

    def _filtered_items(self) -> list[TodoItem]:
        """按搜索词 + 标签过滤活跃待办（视图展示的列表）"""
        result = [i for i in self._todos if i.is_active]
        q = self._search_query.lower()
        if q:
            index = self._search_index_text()
            result = [i for i in result if q in index.get(i.id, "")]
        if self._active_tag:
            result = [i for i in result if self._active_tag in i.tags]
        return result

    def _search_index_text(self) -> dict[str, str]:
        """构建/复用标题+进度的小写搜索索引（列表替换或内容修改时重建）"""
        if self._search_index_list_id != id(self._todos):
            self._search_index = None
            self._search_index_list_id = id(self._todos)
        if self._search_index is None:
            self._search_index = {
                t.id: (t.title + "\n" + "\n".join(p.text for p in t.progress)).lower()
                for t in self._todos
            }
        return self._search_index

    def _invalidate_search_index(self) -> None:
        """内容被原地修改（标题/进度）时使搜索索引失效"""
        self._search_index = None

    def _collect_tags(self) -> list[str]:
        """收集所有活跃待办的标签（保持出现顺序去重）"""
        tags: list[str] = []
        for t in self._todos:
            if not t.is_active:
                continue
            for tag in t.tags:
                if tag not in tags:
                    tags.append(tag)
        return tags

    @staticmethod
    def _extract_tags(title: str) -> list[str]:
        """从标题中提取 #标签（#中文、#英文、#数字）"""
        tags: list[str] = []
        for m in re.finditer(r"#([\u4e00-\u9fa5A-Za-z0-9_\-]+)", title):
            tag = m.group(1)
            if tag and tag not in tags:
                tags.append(tag)
        return tags

    def _refresh_views(self) -> None:
        """刷新所有视图（保持搜索/标签过滤状态）"""
        filtered = self._filtered_items()
        self._expanded_view.refresh(filtered, self._search_query)
        self._expanded_view.update_tag_filters(self._collect_tags(), self._active_tag)

        # 更新计数
        active_count = len([t for t in self._todos if t.is_active])
        archived_count = len(self._archived)
        self._pet_view.update_count(active_count)
        self._expanded_view.update_stats(active_count, archived_count)

    def _refresh_notes(self) -> None:
        """刷新便签视图"""
        self._expanded_view.set_notes(self._notes)

    # ── 数据落盘（防抖） ──────────────────────────────────

    def _schedule_save(self) -> None:
        """安排延迟落盘（高频操作合并为一次写入）"""
        self._save_timer.start()

    def _flush_store(self) -> None:
        """立即落盘（防抖到期 / 退出时调用）"""
        try:
            self._store.flush()
        except StoreError as e:
            logger.error("保存数据失败: %s", e)

    # ── 信号连接 ──────────────────────────────────────────

    def _connect_signals(self) -> None:
        """连接所有视图信号到控制器槽函数"""

        # 折叠视图（桌宠）
        self._pet_view.signal_expand_clicked.connect(self._window.expand)
        self._pet_view.signal_quick_add_clicked.connect(
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
        self._expanded_view.signal_sticky_toggled.connect(self._on_toggle_sticky)
        self._expanded_view.signal_reorder_items.connect(self._on_reorder_items)
        self._expanded_view.signal_title_changed.connect(self._on_title_changed)
        self._expanded_view.signal_progress_edited.connect(self._on_edit_progress)
        self._expanded_view.signal_progress_deleted.connect(self._on_delete_progress)
        self._expanded_view.signal_theme_mode_clicked.connect(self._theme.cycle)
        self._expanded_view.signal_autostart_toggled.connect(self._on_toggle_autostart)
        self._expanded_view.signal_opacity_changed.connect(self._on_opacity_changed)
        self._expanded_view.signal_opacity_committed.connect(
            self._on_opacity_committed
        )
        self._expanded_view.signal_font_scale_changed.connect(
            self._theme.set_font_scale
        )
        self._expanded_view.signal_due_date_set.connect(self._on_due_date_set)
        self._expanded_view.signal_tag_filter_clicked.connect(
            self._on_tag_filter_clicked
        )
        self._expanded_view.signal_stats_requested.connect(self._on_stats_requested)
        self._expanded_view.signal_backup_clicked.connect(self._on_backup_clicked)
        self._expanded_view.signal_notes_added.connect(self._on_notes_added)
        self._expanded_view.signal_note_updated.connect(self._on_note_updated)
        self._expanded_view.signal_note_deleted.connect(self._on_note_deleted)
        self._expanded_view.signal_pet_selected.connect(self._on_pet_selected)

        # 主窗口
        self._window.signal_close_requested.connect(self._on_close_requested)

        # 置顶切换（两个视图同步）
        self._pet_view.signal_toggle_pin.connect(self._on_toggle_pin)
        self._expanded_view.signal_toggle_pin.connect(self._on_toggle_pin)
        self._pet_view.signal_quit_requested.connect(self._on_quit)
        self._pet_view.signal_animation_toggled.connect(
            self._on_pet_animation_toggled)

        # ── 键盘快捷键 ──────────────────────────────────
        self._setup_shortcuts()

    def _setup_shortcuts(self) -> None:
        """注册全局键盘快捷键"""
        QShortcut(QKeySequence("Ctrl+N"), self._window, self._on_shortcut_new)
        QShortcut(QKeySequence("Ctrl+F"), self._window, self._on_shortcut_search)

    # ── 核心业务逻辑 ──────────────────────────────────────

    def _on_add_item(self, title: str) -> None:
        """添加新待办（自动提取 #标签）"""
        title = title.strip()
        if not title:
            return

        item = TodoItem(title=title)
        item.tags = self._extract_tags(title)
        try:
            self._store.add_item(item)  # add_item 会修改 item.position（原地）
            self._todos = self._store.load_todos()
            self._schedule_save()
            self._refresh_views()
            self._show_notification(f"已添加：{title[:20]}")
        except StoreError as e:
            self._show_error(f"添加失败: {e}")

    def _on_complete_item(self, item_id: str) -> None:
        """办结待办并归档"""
        item = next((t for t in self._todos if t.id == item_id), None)
        if not item:
            return

        original_completed_at = item.completed_at
        item.completed_at = datetime.now(CST).isoformat(timespec="seconds")

        try:
            self._store.archive_item(item)
            self._todos = self._store.load_todos()
            self._archived = self._store.load_archived()
            self._schedule_save()
            self._refresh_views()
            self._show_notification("已办结 ✓")
        except StoreError as e:
            item.completed_at = original_completed_at  # 回滚内存状态
            self._show_error(f"办结失败: {e}")

    def _on_delete_item(self, item_id: str) -> None:
        """删除待办（带确认）"""
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
            self._archived = self._store.load_archived()
            self._schedule_save()
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
            self._schedule_save()
            self._invalidate_search_index()
            self._refresh_views()
        except StoreError as e:
            item.progress.pop()  # 回滚内存状态
            self._show_error(f"添加进度失败: {e}")

    def _on_edit_progress(self, item_id: str, entry_id: str, new_text: str) -> None:
        """编辑一条进度记录"""
        new_text = new_text.strip()
        if not new_text:
            return

        item = next((t for t in self._todos if t.id == item_id), None)
        if not item:
            return

        entry = next((p for p in item.progress if p.id == entry_id), None)
        if not entry:
            return

        old_text = entry.text
        entry.text = new_text

        try:
            self._store.update_item(item)
            self._schedule_save()
            self._invalidate_search_index()
            self._refresh_views()  # 刷新搜索过滤等视图状态
            self._show_notification("进度已更新")
        except StoreError as e:
            entry.text = old_text  # 回滚内存状态
            self._refresh_views()
            self._show_error(f"编辑进度失败: {e}")

    def _on_delete_progress(self, item_id: str, entry_id: str) -> None:
        """删除一条进度记录"""
        item = next((t for t in self._todos if t.id == item_id), None)
        if not item:
            return

        idx = next((i for i, p in enumerate(item.progress) if p.id == entry_id), None)
        if idx is None:
            return

        removed = item.progress.pop(idx)

        try:
            self._store.update_item(item)
            self._schedule_save()
            self._invalidate_search_index()
            self._refresh_views()
            self._show_notification("进度已删除")
        except StoreError as e:
            item.progress.insert(idx, removed)  # 回滚内存状态
            self._refresh_views()
            self._show_error(f"删除进度失败: {e}")

    def _on_title_changed(self, item_id: str, new_title: str) -> None:
        """待办标题内联编辑后持久化（重新提取标签）"""
        item = next((t for t in self._todos if t.id == item_id), None)
        if not item:
            return
        old_title = item.title
        old_tags = list(item.tags)
        item.title = new_title
        item.tags = self._extract_tags(new_title)
        try:
            self._store.update_item(item)
            self._schedule_save()
            self._invalidate_search_index()
            # 无需刷新视图，卡片已就地更新
            self._show_notification("已更新标题")
        except StoreError as e:
            item.title = old_title  # 回滚内存状态
            item.tags = old_tags
            self._refresh_views()  # 刷新视图以恢复旧标题显示
            self._show_error(f"更新标题失败: {e}")

    def _on_due_date_set(self, item_id: str, due_date: str) -> None:
        """设置/清除截止日期"""
        item = next((t for t in self._todos if t.id == item_id), None)
        if not item:
            return
        old_due = item.due_date
        item.due_date = due_date or None
        try:
            self._store.update_item(item)
            self._schedule_save()
            self._refresh_views()
            self._show_notification("已设置截止日期" if item.due_date else "已清除截止日期")
        except StoreError as e:
            item.due_date = old_due  # 回滚内存状态
            self._refresh_views()
            self._show_error(f"设置截止日期失败: {e}")

    def _on_search(self, query: str) -> None:
        """搜索待办（在控制器中过滤，视图只负责展示）"""
        self._search_query = query
        self._expanded_view.refresh(self._filtered_items(), query)

    def _on_tag_filter_clicked(self, tag: str) -> None:
        """标签筛选切换"""
        self._active_tag = tag
        self._refresh_views()

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
                self._schedule_save()
                self._refresh_views()
                self._show_notification(f"已恢复：{restored.title[:20]}")
        except StoreError as e:
            self._show_error(f"恢复失败: {e}")

    def _on_toggle_sticky(self, item_id: str) -> None:
        """切换待办置顶状态（带动画）"""
        item = next((t for t in self._todos if t.id == item_id), None)
        if not item:
            return
        original_sticky = item.sticky
        item.sticky = not item.sticky
        try:
            self._store.update_item(item)
            self._schedule_save()
            if self._window.mode == "expanded":
                self._expanded_view.animate_sticky(item_id, self._todos)
            else:
                self._refresh_views()
        except StoreError as e:
            item.sticky = original_sticky  # 回滚内存状态
            self._show_error(f"置顶切换失败: {e}")

    def _on_reorder_items(self, ordered_ids: list[str]) -> None:
        """接收拖放排序后的新顺序并持久化"""
        try:
            self._store.reorder_items(ordered_ids)
            self._todos = self._store.load_todos()
            self._schedule_save()
            self._refresh_views()
        except StoreError as e:
            self._show_error(f"排序失败: {e}")

    def _on_quick_add_collapsed(self) -> None:
        """在折叠模式下快速添加"""
        title, ok = QInputDialog.getText(
            self._window,
            "快速添加",
            "待办内容：",
        )
        if ok and title.strip():
            self._on_add_item(title.strip())

    # ── 统计 ──────────────────────────────────────────────

    def _on_stats_requested(self) -> None:
        """请求并显示统计面板"""
        try:
            stats = self._store.get_stats()
            self._expanded_view.show_stats(stats)
        except StoreError as e:
            self._show_error(f"获取统计失败: {e}")

    # ── 数据备份（导出 / 导入） ──────────────────────────

    def _on_backup_clicked(self) -> None:
        """弹出备份菜单（导出 / 导入）"""
        menu = QMenu(self._window)
        export_action = QAction("导出数据备份...", menu)
        export_action.triggered.connect(self._on_export_data)
        import_action = QAction("导入数据备份...", menu)
        import_action.triggered.connect(self._on_import_data)
        menu.addAction(export_action)
        menu.addSeparator()
        menu.addAction(import_action)
        menu.exec(QCursor.pos())

    def _on_export_data(self) -> None:
        """导出全部数据到 JSON 文件"""
        path, _ = QFileDialog.getSaveFileName(
            self._window,
            "导出数据备份",
            str(Path.home() / "待办备份.json"),
            "JSON 文件 (*.json)",
        )
        if not path:
            return
        try:
            stats = self._store.export_all(Path(path))
            self._show_notification(
                f"已导出 {stats['todos']} 条待办、{stats['archived']} 条归档")
        except StoreError as e:
            self._show_error(f"导出失败: {e}")

    def _on_import_data(self) -> None:
        """从备份文件导入数据（替换现有待办与归档，便签不受影响）"""
        path, _ = QFileDialog.getOpenFileName(
            self._window,
            "导入数据备份",
            str(Path.home()),
            "JSON 文件 (*.json)",
        )
        if not path:
            return
        reply = QMessageBox.question(
            self._window,
            "确认导入",
            "导入将替换当前所有待办和归档数据，此操作不可撤销。\n是否继续？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        try:
            n_todos, n_archived = self._store.import_all(Path(path))
            # 重新加载内存引用并刷新
            self._todos = self._store.load_todos()
            self._archived = self._store.load_archived()
            self._search_query = ""
            self._active_tag = ""
            self._refresh_views()
            self._show_notification(
                f"导入完成：{n_todos} 条待办、{n_archived} 条归档")
        except StoreError as e:
            self._show_error(f"导入失败: {e}")

    # ── 便签 ──────────────────────────────────────────────

    def _on_notes_added(self, content: str, color: str) -> None:
        """新建便签"""
        note = Note(content=content, color=color)
        try:
            self._note_store.add_note(note)
            self._notes = self._note_store.load_notes()
            self._refresh_notes()
        except StoreError as e:
            self._show_error(f"新建便签失败: {e}")

    def _on_note_updated(self, note_id: str, content: str, color: str) -> None:
        """更新便签内容/颜色"""
        note = next((n for n in self._notes if n.id == note_id), None)
        if not note:
            return
        old_content, old_color = note.content, note.color
        note.content = content
        note.color = color
        note.updated_at = datetime.now(CST).isoformat(timespec="seconds")
        try:
            self._note_store.update_note(note)
            self._refresh_notes()
        except StoreError as e:
            note.content, note.color = old_content, old_color  # 回滚内存状态
            self._refresh_notes()
            self._show_error(f"保存便签失败: {e}")

    def _on_note_deleted(self, note_id: str) -> None:
        """删除便签"""
        try:
            if self._note_store.delete_note(note_id):
                self._notes = self._note_store.load_notes()
                self._refresh_notes()
        except StoreError as e:
            self._show_error(f"删除便签失败: {e}")

    # ── 截止日期提醒 ──────────────────────────────────────

    def _check_due_reminders(self) -> None:
        """检查到期/过期待办并发送托盘提醒（每天每项只提醒一次）"""
        if not self._tray.supports_messages():
            return
        self._reminder.check()

    # ── 系统托盘回调 ──────────────────────────────────────

    def _on_tray_show(self) -> None:
        self._window.ensure_visible()
        self._window.show()
        self._window.raise_()
        self._window.activateWindow()

    def _on_close_requested(self) -> None:
        """关闭按钮行为：最小化到托盘"""
        if self._window.mode == "expanded":
            self._window.collapse()
        self._window.hide()
        self._show_notification("已最小化到系统托盘")

    def _on_quit(self) -> None:
        """退出应用（先强制落盘）"""
        self._flush_store()
        self._tray.hide()
        QApplication.quit()

    # ── 窗口状态管理 ──────────────────────────────────────

    def _restore_window_state(self) -> None:
        """恢复窗口置顶状态、透明度并同步按钮"""
        settings = QSettings("Personal", "待办事项和便签")
        self._pinned = settings.value("window/pinned", True, type=bool)
        self._sync_pin_state()
        opacity = settings.value(
            "window/opacity", AppConfig.WINDOW_OPACITY_DEFAULT, type=float)
        self._window.set_opacity(opacity)
        self._expanded_view.set_opacity_value(opacity)

    def _on_toggle_pin(self) -> None:
        """切换窗口置顶并同步所有视图"""
        self._pinned = not self._pinned
        self._window.set_always_on_top(self._pinned)
        self._sync_pin_state()
        settings = QSettings("Personal", "待办事项和便签")
        settings.setValue("window/pinned", self._pinned)

    def _sync_pin_state(self) -> None:
        """同步置顶按钮样式"""
        self._pet_view.set_pinned(self._pinned)
        self._expanded_view.set_pinned(self._pinned)

    # ── 桌宠形象 ──────────────────────────────────────────

    def _on_pet_selected(self, pet_id: str) -> None:
        """切换桌宠形象并持久化"""
        self._pet_view.load_pet(pet_id)
        settings = QSettings("Personal", "待办事项和便签")
        settings.setValue("window/pet", self._pet_view.pet_id())
        self._expanded_view.set_selected_pet(self._pet_view.pet_id())
        self._show_notification("已切换桌宠形象")

    def _on_pet_animation_toggled(self, enabled: bool) -> None:
        """桌宠空闲动画开关切换：持久化，恢复时若处于折叠态立即重启"""
        settings = QSettings("Personal", "待办事项和便签")
        settings.setValue("window/pet_animation", enabled)
        if enabled:
            self._window.start_collapsed_idle()
        self._show_notification(
            "已开启桌宠动画" if enabled else "已暂停桌宠动画")

    # ── 主题（浅色 / 深色 / 跟随系统） ────────────────────

    def _on_theme_applied(self, mode: str) -> None:
        """主题应用后同步展开视图的主题按钮状态"""
        self._expanded_view.set_theme_mode(mode)

    # ── 开机自启 ──────────────────────────────────────

    def _on_toggle_autostart(self, enabled: bool) -> None:
        """切换开机自启状态"""
        if not AppConfig.IS_WINDOWS:
            return
        try:
            self._autostart.set_enabled(enabled)
            self._expanded_view.set_autostart(enabled)
            self._show_notification("已开启开机自启" if enabled else "已关闭开机自启")
        except Exception as e:
            logger.error("设置开机自启失败: %s", e)
            self._show_error(f"设置开机自启失败: {e}")

    # ── 窗口透明度 / 字号 ─────────────────────────────────

    def _on_opacity_changed(self, value: float) -> None:
        """透明度实时变化：仅更新窗口（不写注册表）"""
        self._window.set_opacity(value)

    def _on_opacity_committed(self, value: float) -> None:
        """透明度松手后持久化"""
        self._window.set_opacity(value)
        settings = QSettings("Personal", "待办事项和便签")
        settings.setValue("window/opacity", value)

    # ── 键盘快捷键 ──────────────────────────────────────

    def _on_shortcut_new(self) -> None:
        """Ctrl+N：新建（待办页新建待办，便签页新建便签）"""
        if self._window.mode != "expanded":
            self._window.expand()
        if self._expanded_view.current_tab() == "notes":
            self._expanded_view.focus_note_add()
        else:
            self._expanded_view.focus_add_input()

    def _on_shortcut_search(self) -> None:
        """Ctrl+F：搜索（切回待办页）"""
        if self._window.mode == "expanded":
            if self._expanded_view.current_tab() == "notes":
                self._expanded_view.switch_tab("todo")
            self._expanded_view.focus_search()
        else:
            self._window.expand()
            self._expanded_view.focus_search()

    # ── 通知 ──────────────────────────────────────────────

    def _show_notification(self, message: str) -> None:
        """显示短暂的通知消息（托盘气泡，不支持时静默）"""
        self._tray.show_notification(message)

    def _show_error(self, message: str) -> None:
        """显示错误对话框"""
        QMessageBox.warning(self._window, "错误", message)
