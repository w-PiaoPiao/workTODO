"""
待办卡片组件

单个待办项的展示，包含：
- 完成复选框（☐/☑）
- 标题（双击编辑）
- 进度历史列表
- 添加进度输入
- 办结/删除按钮
"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Signal, Qt, QMimeData, QPoint, QRect, QEvent, QSize
from PySide6.QtGui import QDrag, QMouseEvent
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QPushButton,
    QLineEdit, QWidget, QApplication, QGraphicsOpacityEffect,
    QInputDialog, QMessageBox, QLabel,
)
from app.config import AppConfig
from app.views.theme import AppTheme
from app.views.icons import AppIcons
from app.views.elided_label import ElidedLabel
from app.models.todo_item import TodoItem, ProgressEntry
from app.views.progress_widget import ProgressWidget


class TodoCard(QFrame):
    """单个待办卡片"""

    signal_completed = Signal(str)  # item_id
    signal_deleted = Signal(str)  # item_id
    signal_progress_added = Signal(str, str)  # item_id, text
    signal_sticky_toggled = Signal(str)  # item_id
    signal_title_changed = Signal(str, str)  # item_id, new_title
    signal_progress_edited = Signal(str, str, str)  # item_id, entry_id, new_text
    signal_progress_deleted = Signal(str, str)  # item_id, entry_id
    signal_due_date_set = Signal(str, str)  # item_id, due_date（空字符串=清除）

    def __init__(self, item: TodoItem, parent=None):
        super().__init__(parent)
        self._item = item
        self._editing = False
        self._drag_start_pos = None  # 拖拽起始位置
        self._progress_visible_before_collapse = True  # 收起前进度区可见性，用于恢复

        self._build_ui()
        self._populate(item)

    def _build_ui(self) -> None:
        """构建卡片 UI"""

        self.setStyleSheet(AppTheme.card_style(completed=False))

        # ── 外层布局：置顶竖条 + 内容区 ────────────────────
        outer = QHBoxLayout()
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # 置顶竖条（独立布局元素，与内容物理隔离，不随 hover 变化）
        self._sticky_bar = QFrame()
        self._sticky_bar.setFixedWidth(3)
        self._sticky_bar.setStyleSheet(AppTheme.sticky_bar_style())
        self._sticky_bar.setVisible(self._item.sticky)
        outer.addWidget(self._sticky_bar)

        content = QWidget()
        content.setStyleSheet("background: transparent;")
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(10, 8, 10, 8)
        main_layout.setSpacing(4)

        # ── 顶行：标题 + 操作按钮 ────────────────────────────
        top_row = QHBoxLayout()
        top_row.setSpacing(8)
        self._title_row = top_row  # 保存引用，供 _start_edit 使用

        self._title_label = ElidedLabel()
        self._title_label.setStyleSheet(f"""
            font: {AppTheme.FONT["body"]};
            color: {AppTheme.C["text_primary"]};
            background: transparent;
            padding: 2px 0;
        """)
        # ElidedLabel 已设置 Expanding + minimumWidth(0)

        self._date_btn = QPushButton()
        self._date_btn.setFixedSize(24, 24)
        self._date_btn.setIconSize(QSize(16, 16))
        self._date_btn.setIcon(AppIcons.get("calendar", 16))
        self._date_btn.setToolTip("设置截止日期")
        self._date_btn.setStyleSheet(AppTheme.icon_btn())
        self._date_btn.clicked.connect(self._on_set_due_date)

        self._sticky_btn = QPushButton()
        self._sticky_btn.setFixedSize(24, 24)
        self._sticky_btn.setIconSize(QSize(16, 16))
        self._sticky_btn.setToolTip("置顶")
        self._sticky_btn.setStyleSheet(AppTheme.icon_btn())
        self._sticky_btn.clicked.connect(self._on_toggle_sticky)

        self._complete_btn = QPushButton("办结")
        self._complete_btn.setFixedSize(40, 24)
        self._complete_btn.setToolTip("标记为已完成")
        self._complete_btn.setStyleSheet(AppTheme.outline_btn())
        self._complete_btn.clicked.connect(self._on_complete)

        self._delete_btn = QPushButton()
        self._delete_btn.setFixedSize(24, 24)
        self._delete_btn.setIconSize(QSize(16, 16))
        self._delete_btn.setToolTip("删除")
        self._delete_btn.setStyleSheet(AppTheme.danger_btn())
        self._delete_btn.clicked.connect(self._on_delete)

        top_row.addWidget(self._title_label, stretch=1)
        top_row.addWidget(self._date_btn)
        top_row.addWidget(self._sticky_btn)
        top_row.addWidget(self._complete_btn)
        top_row.addWidget(self._delete_btn)

        main_layout.addLayout(top_row)

        # ── 元信息行：标签 chips + 截止日期徽标 ─────────────
        self._meta_row = QHBoxLayout()
        self._meta_row.setSpacing(6)
        self._tags_container = QWidget()
        self._tags_layout = QHBoxLayout()
        self._tags_layout.setContentsMargins(0, 0, 0, 0)
        self._tags_layout.setSpacing(4)
        self._tags_container.setLayout(self._tags_layout)
        self._due_label = QLabel()
        self._due_label.hide()

        self._meta_row.addWidget(self._tags_container)
        self._meta_row.addStretch(1)
        self._meta_row.addWidget(self._due_label)
        main_layout.addLayout(self._meta_row)

        # ── 进度区域 ──────────────────────────────────────
        self._progress_widget = ProgressWidget()
        self._progress_widget.signal_progress_edited.connect(
            lambda entry_id, new_text: self.signal_progress_edited.emit(
                self._item.id, entry_id, new_text))
        self._progress_widget.signal_progress_deleted.connect(
            lambda entry_id: self.signal_progress_deleted.emit(
                self._item.id, entry_id))
        main_layout.addWidget(self._progress_widget)

        # ── 添加进度行 ────────────────────────────────────
        progress_row = QHBoxLayout()
        progress_row.setSpacing(4)
        progress_row.setContentsMargins(0, 0, 0, 0)  # 无复选框，取消缩进

        self._progress_input = QLineEdit()
        self._progress_input.setPlaceholderText("添加进度...")
        self._progress_input.setStyleSheet(AppTheme.progress_input_style())
        self._progress_input.returnPressed.connect(self._on_progress_submit)

        self._progress_btn = QPushButton("＋")
        self._progress_btn.setFixedSize(20, 20)
        self._progress_btn.setToolTip("添加进度")
        self._progress_btn.setStyleSheet(AppTheme.icon_btn("12px"))
        self._progress_btn.clicked.connect(self._on_progress_submit)

        progress_row.addWidget(self._progress_input, stretch=1)
        progress_row.addWidget(self._progress_btn)
        main_layout.addLayout(progress_row)

        content.setLayout(main_layout)
        outer.addWidget(content, stretch=1)

        self.setLayout(outer)

    def _populate(self, item: TodoItem) -> None:
        """用数据填充卡片"""
        self._item = item

        if item.is_completed:
            self._title_label.setStyleSheet(f"""
                font: {AppTheme.FONT["body"]};
                color: {AppTheme.C["text_disabled"]};
                background: transparent;
                text-decoration: line-through;
                padding: 2px 0;
            """)
            self._complete_btn.setVisible(False)
            self._progress_input.setVisible(False)
            self._progress_btn.setVisible(False)
            self._sticky_btn.setVisible(False)
            self._date_btn.setVisible(False)

        self._title_label.setFullText(item.title)
        # 卡片级别 tooltip：ElidedLabel 的 tooltip 因 WA_TransparentForMouseEvents 不可用，
        # 需在 TodoCard 级别设置，当鼠标悬浮在标题区域时显示完整文本
        self.setToolTip(item.title)

        # 置顶状态
        self._apply_sticky_icon()
        self._sticky_bar.setVisible(item.sticky)

        # 操作按钮默认隐藏（办结按钮常驻），鼠标悬停卡片时显示
        self._date_btn.setVisible(False)
        self._sticky_btn.setVisible(False)
        self._delete_btn.setVisible(False)

        # 截止日期徽标
        if item.due_date:
            self._due_label.setText(item.due_display)
            self._due_label.setStyleSheet(AppTheme.date_badge_style(item.is_overdue))
            self._due_label.show()
            self._date_btn.setToolTip(f"截止 {item.due_date}，点击修改/清除")
        else:
            self._due_label.hide()
            self._date_btn.setToolTip("设置截止日期")

        # 标签 chips
        self._rebuild_tags(item.tags)

        # 填充进度
        self._progress_widget.set_entries(item.progress)

    def _rebuild_tags(self, tags: list[str]) -> None:
        """重建标签 chips 行"""
        # 清空旧 chips（保留布局对象）
        while self._tags_layout.count():
            item = self._tags_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        if not tags:
            self._tags_container.hide()
            return
        for tag in tags:
            chip = QLabel(f"#{tag}")
            chip.setStyleSheet(AppTheme.tag_chip_style())
            self._tags_layout.addWidget(chip)
        self._tags_container.show()

    # ── 交互事件 ──────────────────────────────────────────

    def _on_complete(self) -> None:
        self.signal_completed.emit(self._item.id)

    def _on_delete(self) -> None:
        self.signal_deleted.emit(self._item.id)

    def _on_toggle_sticky(self) -> None:
        # 只发射信号，由控制器处理翻转和刷新
        self.signal_sticky_toggled.emit(self._item.id)

    def _on_set_due_date(self) -> None:
        """弹出截止日期输入框（留空清除）"""
        current = self._item.due_date or ""
        text, ok = QInputDialog.getText(
            self.window() or self,
            "设置截止日期",
            "截止日期（格式 YYYY-MM-DD，留空清除）：",
            QLineEdit.Normal,
            current,
        )
        if not ok:
            return
        text = text.strip()
        if not text:
            self.signal_due_date_set.emit(self._item.id, "")
            return
        try:
            datetime.strptime(text, "%Y-%m-%d")
        except ValueError:
            QMessageBox.warning(
                self.window() or self,
                "日期格式错误",
                "请使用 YYYY-MM-DD 格式，例如 2026-08-05",
            )
            return
        self.signal_due_date_set.emit(self._item.id, text)

    # ── 拖拽支持 ──────────────────────────────────────────

    def _is_title_click(self, event: QMouseEvent) -> bool:
        """判断鼠标事件是否点击在标题区域"""
        return (event.button() == Qt.LeftButton
                and self._title_label.isVisible()
                and self._title_label.rect().contains(
                    self._title_label.mapFrom(self, event.position().toPoint())))

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """处理单击——记录拖拽起始位置"""
        if self._is_title_click(event):
            self._drag_start_pos = event.position().toPoint()
            event.accept()
            return

        # 标题区域之外的点击 → 清理拖拽状态
        self._drag_start_pos = None
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        """处理双击——进入内联编辑"""
        if self._is_title_click(event):
            if not self._item.is_completed and not self._editing:
                self._start_edit()
                event.accept()
                return
        super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if (self._drag_start_pos is not None
                and event.buttons() == Qt.LeftButton
                and (event.position().toPoint() - self._drag_start_pos).manhattanLength()
                >= QApplication.startDragDistance()):
            self._start_drag(event)
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_start_pos = None
        super().mouseReleaseEvent(event)

    def enterEvent(self, event) -> None:
        """鼠标进入卡片：显示操作按钮"""
        if not self._item.is_completed:
            self._date_btn.setVisible(True)
            self._sticky_btn.setVisible(True)
        self._delete_btn.setVisible(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        """鼠标离开卡片：隐藏操作按钮"""
        self._date_btn.setVisible(False)
        self._sticky_btn.setVisible(False)
        self._delete_btn.setVisible(False)
        super().leaveEvent(event)

    def _start_drag(self, event) -> None:
        """启动拖拽"""
        drag = QDrag(self)
        mime = QMimeData()
        mime.setText(f"todo-card:{self._item.id}")
        drag.setMimeData(mime)

        # 拖拽时半透明
        opacity = QGraphicsOpacityEffect()
        opacity.setOpacity(0.4)
        self.setGraphicsEffect(opacity)

        # 拖拽小图（略微缩小）
        pixmap = self.grab()
        pixmap = pixmap.scaled(
            int(self.width() * 0.95), int(self.height() * 0.95),
            Qt.KeepAspectRatio, Qt.SmoothTransformation,
        )
        drag.setPixmap(pixmap)
        drag.setHotSpot(event.position().toPoint())

        self._drag_start_pos = None

        # exec() 运行本地事件循环，拖放完成后才返回
        drag.exec(Qt.MoveAction)

        # 恢复外观（拖放处理可能已销毁此 widget，需防御）
        try:
            self.setGraphicsEffect(None)
        except RuntimeError:
            pass  # widget 已被 deleteLater

    # ── 文字溢出省略（由 ElidedLabel 内部 paintEvent 处理）──

    def _on_progress_submit(self) -> None:
        text = self._progress_input.text().strip()
        if text:
            self.signal_progress_added.emit(self._item.id, text)
            self._progress_input.clear()

    def _start_edit(self) -> None:
        """双击标题进入内联编辑"""
        if self._editing or self._item.is_completed:
            return
        self._editing = True

        self._edit_input = QLineEdit(self._item.title)
        self._edit_input.setStyleSheet(AppTheme.edit_input_style())
        self._edit_input.selectAll()

        # 替换标题标签为输入框（使用保存的 _title_row 引用）
        layout = self._title_row
        idx = layout.indexOf(self._title_label)
        layout.insertWidget(idx, self._edit_input)
        self._title_label.hide()

        self._edit_input.setFocus()
        self._edit_input.returnPressed.connect(self._finish_edit)
        self._edit_input.editingFinished.connect(self._finish_edit)

        # 安装全局事件过滤器：点击编辑框外部时自动保存并退出编辑
        QApplication.instance().installEventFilter(self)

    def _finish_edit(self) -> None:
        """完成内联编辑"""
        if not self._editing:
            return
        self._editing = False

        app = QApplication.instance()
        new_title = self._edit_input.text().strip()
        try:
            if new_title and new_title != self._item.title:
                self._title_label.setFullText(new_title)
                self.setToolTip(new_title)  # 同步卡片 tooltip（因 ElidedLabel 鼠标透传导致原生 tooltip 不可用）
                self.signal_title_changed.emit(self._item.id, new_title)

            self._title_label.show()
            if self._edit_input:
                self._edit_input.deleteLater()
        except RuntimeError:
            # widget 已被 deleteLater 实际删除，后续对象操作不再安全
            pass
        finally:
            self._edit_input = None
            # 无论成功/异常/卡片销毁，都必须移除全局事件过滤器，防止泄漏
            try:
                app.removeEventFilter(self)
            except RuntimeError:
                pass

    def eventFilter(self, obj, event) -> bool:
        """全局事件过滤器：点击编辑框外部时自动保存并退出编辑"""
        try:
            if self._editing and event.type() == QEvent.MouseButtonPress:
                edit_rect = QRect(
                    self._edit_input.mapToGlobal(QPoint(0, 0)),
                    self._edit_input.size(),
                )
                if not edit_rect.contains(event.globalPosition().toPoint()):
                    self._finish_edit()
        except RuntimeError:
            # 卡片已被销毁：清理过滤器并放行事件
            try:
                QApplication.instance().removeEventFilter(self)
            except RuntimeError:
                pass
            return False
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event) -> None:
        """键盘事件：编辑状态下 Escape 取消编辑"""
        if self._editing and event.key() == Qt.Key_Escape:
            self._cancel_edit()
            event.accept()
            return
        super().keyPressEvent(event)

    def _cancel_edit(self) -> None:
        """取消编辑，恢复原标题"""
        self._editing = False
        self._title_label.show()
        if self._edit_input:
            self._edit_input.deleteLater()
            self._edit_input = None
        QApplication.instance().removeEventFilter(self)

    # ── 更新 ──────────────────────────────────────────────

    def _apply_sticky_icon(self) -> None:
        """按置顶状态刷新置顶按钮图标颜色"""
        color = AppTheme.C["accent"] if self._item.sticky else AppTheme.C["text_disabled"]
        self._sticky_btn.setIcon(AppIcons.get("pin", 16, color=color))

    def _apply_action_icons(self) -> None:
        """统一刷新操作按钮图标（主题/字号变化时调用）"""
        C = AppTheme.C
        self._date_btn.setIcon(AppIcons.get("calendar", 16))
        self._delete_btn.setIcon(
            AppIcons.get("delete", 16, color=C["text_disabled"], active_color=C["danger"]))
        self._apply_sticky_icon()

    def update_item(self, item: TodoItem) -> None:
        """更新卡片显示（无重建）"""
        self._populate(item)

    def collapse_progress(self) -> None:
        """收起进度展开（封装对 ProgressWidget 的内部访问）"""
        self._progress_widget.collapse()

    def set_all_collapsed(self, collapsed: bool) -> None:
        """全部卡片折叠模式：隐藏进度区域和添加进度行，仅保留标题行

        收起前记忆进度区原可见性，恢复时按原状态还原，
        避免破坏用户对单张卡片进度的个体折叠状态。
        """
        if collapsed:
            self._progress_visible_before_collapse = self._progress_widget.isVisible()
            self._progress_widget.setVisible(False)
            self._progress_input.setVisible(False)
            self._progress_btn.setVisible(False)
        else:
            self._progress_widget.setVisible(self._progress_visible_before_collapse)
            input_visible = not self._item.is_completed
            self._progress_input.setVisible(input_visible)
            self._progress_btn.setVisible(input_visible)

    def reapply_theme(self) -> None:
        """重新应用当前主题样式（主题切换时调用，无需重建卡片）"""
        C = AppTheme.C
        item = self._item

        # 卡片背景
        self.setStyleSheet(AppTheme.card_style(completed=item.is_completed))

        # 置顶竖条
        self._sticky_bar.setStyleSheet(AppTheme.sticky_bar_style())
        self._sticky_bar.setVisible(item.sticky)

        # 标题
        if item.is_completed:
            self._title_label.setStyleSheet(f"""
                font: {AppTheme.FONT["body"]};
                color: {C["text_disabled"]};
                background: transparent;
                text-decoration: line-through;
                padding: 2px 0;
            """)
        else:
            self._title_label.setStyleSheet(f"""
                font: {AppTheme.FONT["body"]};
                color: {C["text_primary"]};
                background: transparent;
                padding: 2px 0;
            """)

        # 按钮样式
        self._complete_btn.setStyleSheet(AppTheme.outline_btn())
        self._delete_btn.setStyleSheet(AppTheme.danger_btn())
        self._date_btn.setStyleSheet(AppTheme.icon_btn())
        self._sticky_btn.setStyleSheet(AppTheme.icon_btn())
        self._apply_action_icons()

        # 进度输入区域
        self._progress_input.setStyleSheet(AppTheme.progress_input_style())
        self._progress_btn.setStyleSheet(AppTheme.icon_btn("12px"))

        # 截止日期徽标 / 标签 chips
        if item.due_date:
            self._due_label.setStyleSheet(AppTheme.date_badge_style(item.is_overdue))
        for i in range(self._tags_layout.count()):
            w = self._tags_layout.itemAt(i).widget()
            if isinstance(w, QLabel):
                w.setStyleSheet(AppTheme.tag_chip_style())

        # 进度子组件（轻量重建）
        self._progress_widget.reapply_theme()

    @property
    def progress_toggled_signal(self):
        """进度展开/收起信号"""
        return self._progress_widget.signal_show_all_changed


