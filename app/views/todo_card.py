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

from PySide6.QtCore import Signal, Qt, QMimeData, QPoint, QRect, QEvent
from PySide6.QtGui import QDrag, QMouseEvent
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QPushButton,
    QLineEdit, QWidget, QApplication, QGraphicsOpacityEffect,
)
from app.config import AppConfig
from app.views.theme import AppTheme
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

    def __init__(self, item: TodoItem, parent=None):
        super().__init__(parent)
        self._item = item
        self._editing = False
        self._drag_start_pos = None  # 拖拽起始位置
        self._all_collapsed = False  # 全部卡片折叠模式

        self._build_ui()
        self._populate(item)

    def _build_ui(self) -> None:
        """构建卡片 UI"""

        self.setStyleSheet(AppTheme.card_style(completed=False))

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

        self._sticky_btn = QPushButton("↑")
        self._sticky_btn.setFixedSize(24, 24)
        self._sticky_btn.setToolTip("置顶")
        self._sticky_btn.setStyleSheet(self._sticky_btn_style(False))
        self._sticky_btn.clicked.connect(self._on_toggle_sticky)

        self._complete_btn = QPushButton("办结")
        self._complete_btn.setFixedSize(40, 24)
        self._complete_btn.setToolTip("标记为已完成")
        self._complete_btn.setStyleSheet(self._action_btn_style())
        self._complete_btn.clicked.connect(self._on_complete)

        self._delete_btn = QPushButton("✕")
        self._delete_btn.setFixedSize(24, 24)
        self._delete_btn.setToolTip("删除")
        self._delete_btn.setStyleSheet(self._delete_btn_style())
        self._delete_btn.clicked.connect(self._on_delete)

        top_row.addWidget(self._title_label, stretch=1)
        top_row.addWidget(self._sticky_btn)
        top_row.addWidget(self._complete_btn)
        top_row.addWidget(self._delete_btn)

        main_layout.addLayout(top_row)

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
        self._progress_input.setStyleSheet(f"""
            QLineEdit {{
                border: none;
                font: {AppTheme.FONT["small"]};
                color: {AppTheme.C["text_secondary"]};
                padding: 2px 4px;
                background: transparent;
            }}
            QLineEdit:focus {{
                color: {AppTheme.C["text_primary"]};
            }}
        """)
        self._progress_input.returnPressed.connect(self._on_progress_submit)

        self._progress_btn = QPushButton("＋")
        self._progress_btn.setFixedSize(20, 20)
        self._progress_btn.setToolTip("添加进度")
        self._progress_btn.setStyleSheet(f"""
            QPushButton {{
                font-size: 12px;
                color: {AppTheme.C["text_disabled"]};
                border: none;
                padding: 0;
                background: transparent;
            }}
            QPushButton:hover {{
                color: {AppTheme.C["accent"]};
            }}
        """)
        self._progress_btn.clicked.connect(self._on_progress_submit)

        progress_row.addWidget(self._progress_input, stretch=1)
        progress_row.addWidget(self._progress_btn)
        main_layout.addLayout(progress_row)

        self.setLayout(main_layout)

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

        self._title_label.setFullText(item.title)
        # 卡片级别 tooltip：ElidedLabel 的 tooltip 因 WA_TransparentForMouseEvents 不可用，
        # 需在 TodoCard 级别设置，当鼠标悬浮在标题区域时显示完整文本
        self.setToolTip(item.title)

        # 置顶状态
        self._sticky_btn.setStyleSheet(self._sticky_btn_style(item.sticky))

        # 填充进度
        self._progress_widget.set_entries(item.progress)

    # ── 交互事件 ──────────────────────────────────────────

    def _on_complete(self) -> None:
        self.signal_completed.emit(self._item.id)

    def _on_delete(self) -> None:
        self.signal_deleted.emit(self._item.id)

    def _on_toggle_sticky(self) -> None:
        # 只发射信号，由控制器处理翻转和刷新
        self.signal_sticky_toggled.emit(self._item.id)

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
        self._edit_input.setStyleSheet(f"""
            border: 1px solid {AppTheme.C["accent"]};
            border-radius: 3px;
            padding: 2px 6px;
            font: {AppTheme.FONT["body"]};
        """)
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

        new_title = self._edit_input.text().strip()
        if new_title and new_title != self._item.title:
            self._title_label.setFullText(new_title)
            self.setToolTip(new_title)  # 同步卡片 tooltip（因 ElidedLabel 鼠标透传导致原生 tooltip 不可用）
            self.signal_title_changed.emit(self._item.id, new_title)

        # 保护：如果信号导致的 StoreError 已触发 _refresh_views 销毁了卡片，
        # 后续的 widget 操作不再安全（会抛出 RuntimeError）
        try:
            self._title_label.show()
            if self._edit_input:
                self._edit_input.deleteLater()
                self._edit_input = None
            QApplication.instance().removeEventFilter(self)
        except RuntimeError:
            # widget 已被 deleteLater 实际删除
            self._edit_input = None

    def eventFilter(self, obj, event) -> bool:
        """全局事件过滤器：点击编辑框外部时自动保存并退出编辑"""
        if self._editing and event.type() == QEvent.MouseButtonPress:
            edit_rect = QRect(
                self._edit_input.mapToGlobal(QPoint(0, 0)),
                self._edit_input.size(),
            )
            if not edit_rect.contains(event.globalPosition().toPoint()):
                self._finish_edit()
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

    def update_item(self, item: TodoItem) -> None:
        """更新卡片显示（无重建）"""
        self._populate(item)

    def collapse_progress(self) -> None:
        """收起进度展开（封装对 ProgressWidget 的内部访问）"""
        self._progress_widget.collapse()

    def set_all_collapsed(self, collapsed: bool) -> None:
        """全部卡片折叠模式：隐藏进度区域和添加进度行，仅保留标题行"""
        self._all_collapsed = collapsed
        if collapsed:
            self._progress_widget.setVisible(False)
            self._progress_input.setVisible(False)
            self._progress_btn.setVisible(False)
        else:
            self._progress_widget.setVisible(True)
            visible = not self._item.is_completed
            self._progress_input.setVisible(visible)
            self._progress_btn.setVisible(visible)

    def reapply_theme(self) -> None:
        """重新应用当前主题样式（主题切换时调用，无需重建卡片）"""
        C = AppTheme.C
        item = self._item

        # 卡片背景
        self.setStyleSheet(AppTheme.card_style(completed=item.is_completed))

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
        self._sticky_btn.setStyleSheet(self._sticky_btn_style(item.sticky))
        self._complete_btn.setStyleSheet(self._action_btn_style())
        self._delete_btn.setStyleSheet(self._delete_btn_style())

        # 进度输入区域
        self._progress_input.setStyleSheet(f"""
            QLineEdit {{
                border: none;
                font: {AppTheme.FONT["small"]};
                color: {C["text_secondary"]};
                padding: 2px 4px;
                background: transparent;
            }}
            QLineEdit:focus {{
                color: {C["text_primary"]};
            }}
        """)
        self._progress_btn.setStyleSheet(f"""
            QPushButton {{
                font-size: 12px;
                color: {C["text_disabled"]};
                border: none;
                padding: 0;
                background: transparent;
            }}
            QPushButton:hover {{
                color: {C["accent"]};
            }}
        """)

        # 进度子组件（轻量重建）
        self._progress_widget.reapply_theme()

    @property
    def progress_toggled_signal(self):
        """进度展开/收起信号"""
        return self._progress_widget.signal_show_all_changed

    # ── 样式 ──────────────────────────────────────────────

    @staticmethod
    def _sticky_btn_style(sticky: bool) -> str:
        C = AppTheme.C
        color = C["accent"] if sticky else C["text_disabled"]
        return f"""
            QPushButton {{
                font-size: 14px;
                color: {color};
                border: none;
                padding: 0;
                background: transparent;
            }}
            QPushButton:hover {{
                color: {C["accent"]};
            }}
        """

    @staticmethod
    def _action_btn_style() -> str:
        C = AppTheme.C
        return f"""
            QPushButton {{
                font: {AppTheme.FONT["small"]};
                color: {C["accent"]};
                border: 1px solid {C["accent"]};
                border-radius: 3px;
                padding: 2px 6px;
                background: transparent;
            }}
            QPushButton:hover {{
                background: {C["accent"]};
                color: white;
            }}
        """

    @staticmethod
    def _delete_btn_style() -> str:
        C = AppTheme.C
        return f"""
            QPushButton {{
                font-size: 12px;
                color: {C["text_disabled"]};
                border: none;
                padding: 0;
                background: transparent;
            }}
            QPushButton:hover {{
                color: {C["danger"]};
            }}
        """
