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

from PySide6.QtCore import Signal, Qt, QEvent
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QSizePolicy, QWidget,
)
from PySide6.QtGui import QFontMetrics
from app.config import AppConfig
from app.views.theme import AppTheme
from app.models.todo_item import TodoItem, ProgressEntry
from app.views.progress_widget import ProgressWidget


class TodoCard(QFrame):
    """单个待办卡片"""

    signal_completed = Signal(str)  # item_id
    signal_deleted = Signal(str)  # item_id
    signal_progress_added = Signal(str, str)  # item_id, text
    signal_sticky_toggled = Signal(str)  # item_id

    def __init__(self, item: TodoItem, parent=None):
        super().__init__(parent)
        self._item = item
        self._editing = False

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

        self._title_label = QLabel()
        self._title_label.setStyleSheet(f"""
            font: {AppTheme.FONT["body"]};
            color: {AppTheme.C["text_primary"]};
            background: transparent;
            padding: 2px 0;
        """)
        self._title_label.setMinimumWidth(0)
        self._title_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._title_label.installEventFilter(self)

        # 双击标题进入编辑模式
        self._title_label.mouseDoubleClickEvent = self._start_edit

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

        self._title_label.setText(item.title)
        self._title_label.setToolTip(item.title)

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
        self._item.sticky = not self._item.sticky
        self._sticky_btn.setStyleSheet(self._sticky_btn_style(self._item.sticky))
        self.signal_sticky_toggled.emit(self._item.id)

    # ── 文字溢出省略 ──────────────────────────────────────

    def eventFilter(self, obj, event):
        if obj == self._title_label and event.type() == QEvent.Resize:
            fm = self._title_label.fontMetrics()
            elided = fm.elidedText(
                self._item.title, Qt.ElideRight, self._title_label.width()
            )
            if elided != self._title_label.text():
                self._title_label.setText(elided)
        return super().eventFilter(obj, event)

    def _on_progress_submit(self) -> None:
        text = self._progress_input.text().strip()
        if text:
            self.signal_progress_added.emit(self._item.id, text)
            self._progress_input.clear()

    def _start_edit(self, event) -> None:
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

        # 替换标题标签为输入框
        label_parent = self._title_label.parent()
        if label_parent:
            layout = self._title_label.parent().layout()
            if isinstance(layout, QHBoxLayout):
                idx = layout.indexOf(self._title_label)
                layout.insertWidget(idx, self._edit_input)
                self._title_label.hide()

        self._edit_input.setFocus()
        self._edit_input.returnPressed.connect(self._finish_edit)
        self._edit_input.editingFinished.connect(self._finish_edit)

    def _finish_edit(self) -> None:
        """完成内联编辑"""
        if not self._editing:
            return
        self._editing = False

        new_title = self._edit_input.text().strip()
        if new_title and new_title != self._item.title:
            self._item.title = new_title
            self._title_label.setText(new_title)

        # 恢复标签显示
        self._title_label.show()
        if self._edit_input:
            self._edit_input.deleteLater()
            self._edit_input = None

    # ── 更新 ──────────────────────────────────────────────

    def update_item(self, item: TodoItem) -> None:
        """更新卡片显示（无重建）"""
        self._populate(item)

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
