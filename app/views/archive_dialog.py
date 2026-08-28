"""
归档查看对话框

以只读方式展示已归档的待办事项，支持搜索和恢复。
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.config import AppConfig
from app.models.todo_item import TodoItem
from app.views.elided_label import ElidedLabel
from app.views.theme import AppTheme
from app.views.ui_utils import DragMixin, clear_layout


class ArchiveDialog(DragMixin, QDialog):
    """归档查看对话框"""

    signal_restore_item = Signal(str)  # item_id

    def remove_item(self, item_id: str) -> None:
        """恢复成功后由控制器回调：同步移除该条目并刷新

        否则对话框停留在打开时的快照上，被恢复条目仍显示，
        再次点击"恢复"静默无效（restore_item 返回 None），按钮像坏了。
        """
        self._all_items = [i for i in self._all_items if i.id != item_id]
        self._filtered_items = [
            i for i in self._filtered_items if i.id != item_id]
        self._refresh()

    def __init__(self, items: list[TodoItem], parent=None):
        super().__init__(parent)
        self._all_items = items
        self._filtered_items = items[:]
        self._drag_pos = QPoint()  # 拖拽用

        # 搜索防抖（与主搜索一致），避免每次按键都全量重建列表
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self._flush_search)

        self.setWindowTitle("归档记录")
        self.setFixedSize(420, 480)
        self.setWindowFlags(
            Qt.Dialog | Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint
        )
        self.setStyleSheet(AppTheme.dialog_frame_style("ArchiveDialog"))

        self._build_ui()
        self._refresh()

    # ── UI 构建 ────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── 标题栏 ────────────────────────────────────────
        title_bar = QWidget()
        title_bar.setFixedHeight(40)
        title_bar.setStyleSheet(AppTheme.dialog_title_bar_style())
        title_layout = QHBoxLayout()
        title_layout.setContentsMargins(12, 0, 8, 0)

        title_label = QLabel("📦 归档记录")
        title_label.setStyleSheet(f"font: {AppTheme.FONT['title']}; background: transparent;")

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        spacer.setStyleSheet("background: transparent;")

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(28, 28)
        close_btn.setStyleSheet(AppTheme.close_btn())
        close_btn.clicked.connect(self.close)

        title_layout.addWidget(title_label)
        title_layout.addWidget(spacer)
        title_layout.addWidget(close_btn)
        title_bar.setLayout(title_layout)
        layout.addWidget(title_bar)

        # ── 搜索栏 ────────────────────────────────────────
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("搜索归档记录...")
        self._search_input.setStyleSheet(AppTheme.dialog_input_style())
        self._search_input.textChanged.connect(self._on_search_debounced)
        layout.addWidget(self._search_input)

        # ── 列表区域 ──────────────────────────────────────
        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # 框架显式透明：透出对话框根的主题化背景（避免派生调色板渲染黑底）
        self._scroll_area.setStyleSheet(
            "QScrollArea { border: none; background: transparent; }")
        # 视口是列表区最终可见层：objectName + ID 选择器显式画对话框底色
        # （透明 QSS 与派生调色板不可靠，会渲染成黑色）
        vp = self._scroll_area.viewport()
        vp.setObjectName("archiveListViewport")
        vp.setStyleSheet(f"""
            #archiveListViewport {{
                background: {AppTheme.C["bg_card"]};
            }}
        """)

        self._list_widget = QWidget()
        # 与 ExpandedView 相同：显式透明，避免 QSS 派生调色板的默认底色盖住主题背景
        self._list_widget.setStyleSheet("background: transparent;")
        self._list_widget.setAutoFillBackground(False)
        self._list_layout = QVBoxLayout()
        self._list_layout.setContentsMargins(12, 8, 12, 8)
        self._list_layout.setSpacing(6)
        self._list_layout.addStretch()
        self._list_widget.setLayout(self._list_layout)
        self._scroll_area.setWidget(self._list_widget)

        layout.addWidget(self._scroll_area, stretch=1)

        # ── 底部统计 ──────────────────────────────────────
        self._footer_label = QLabel()
        self._footer_label.setFixedHeight(32)
        self._footer_label.setAlignment(Qt.AlignCenter)
        self._footer_label.setStyleSheet(AppTheme.dialog_footer_style())
        layout.addWidget(self._footer_label)

        self.setLayout(layout)

    def _on_search_debounced(self, text: str) -> None:
        """搜索输入防抖：重启单次 timer，松手/停顿后才真正过滤"""
        self._search_timer.start(AppConfig.SEARCH_DEBOUNCE_MS)

    def _flush_search(self) -> None:
        """防抖到期后执行过滤刷新"""
        self._on_search(self._search_input.text())

    def _on_search(self, text: str) -> None:
        q = text.lower().strip()
        if not q:
            self._filtered_items = self._all_items[:]
        else:
            # 与主搜索一致：标题 + 进度文本
            self._filtered_items = [
                i for i in self._all_items
                if q in i.title.lower()
                or any(q in p.text.lower() for p in i.progress)
            ]
        self._refresh()

    def _refresh(self) -> None:
        # 清空列表
        clear_layout(self._list_layout)

        if not self._filtered_items:
            label = QLabel("暂无归档记录" if not self._search_input.text()
                           else "没有匹配的记录")
            label.setAlignment(Qt.AlignCenter)
            label.setStyleSheet(f"""
                color: {AppTheme.C["text_disabled"]};
                padding: 40px 20px;
                background: transparent;
            """)
            self._list_layout.insertWidget(0, label)
        else:
            for item in self._filtered_items:
                card = self._make_archive_card(item)
                self._list_layout.insertWidget(self._list_layout.count() - 1, card)

        self._footer_label.setText(
            f"共 {len(self._filtered_items)} 条归档记录"
            if not self._search_input.text()
            else f"找到 {len(self._filtered_items)} 条"
        )

    def _make_archive_card(self, item: TodoItem) -> QWidget:
        """创建归档卡片（只读）"""
        card = QFrame()
        card.setStyleSheet(AppTheme.archive_card_style())
        layout = QVBoxLayout()
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)

        # 标题行
        title_row = QHBoxLayout()
        title_row.setSpacing(8)

        title_label = QLabel("☑ " + item.title)
        title_label.setStyleSheet(f"""
            font: {AppTheme.FONT["body_bold"]};
            color: {AppTheme.C["text_disabled"]};
            background: transparent;
            text-decoration: line-through;
        """)
        title_label.setWordWrap(True)
        title_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        # 完成时间
        if item.completed_at:
            time_label = QLabel(item.completed_display)
            time_label.setStyleSheet(f"""
                font: {AppTheme.FONT["small"]};
                color: {AppTheme.C["text_disabled"]};
                background: transparent;
            """)
            title_row.addWidget(title_label, stretch=1)
            title_row.addWidget(time_label)
        else:
            title_row.addWidget(title_label, stretch=1)

        layout.addLayout(title_row)

        # 进度摘要
        if item.progress:
            for p in item.progress[-2:]:  # 最多显示 2 条
                p_label = ElidedLabel(f"  ·  {p.text}")
                p_label.setStyleSheet(f"""
                    font: {AppTheme.FONT["small"]};
                    color: {AppTheme.C["text_secondary"]};
                    background: transparent;
                """)
                layout.addWidget(p_label)

        # 恢复按钮
        restore_btn = QPushButton("↩ 恢复到待办")
        restore_btn.setStyleSheet(AppTheme.outline_btn("120px"))
        restore_btn.clicked.connect(
            lambda checked, i=item: self.signal_restore_item.emit(i.id)
        )
        layout.addWidget(restore_btn, alignment=Qt.AlignRight)

        card.setLayout(layout)
        return card
