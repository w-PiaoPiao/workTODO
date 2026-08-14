"""
便签视图

彩色便利贴列表：新建、双击编辑、删除。
便签为纯文本笔记，不参与办结/归档，颜色可自选。
"""

from __future__ import annotations

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QSizePolicy,
)
from app.views.theme import AppTheme
from app.models.note import Note
from app.views.note_dialog import NoteDialog
from app.views.ui_utils import clear_layout


class NoteCard(QFrame):
    """便签卡片（双击任意位置打开编辑）"""

    def __init__(self, parent=None, on_double_click=None):
        super().__init__(parent)
        self._on_double_click = on_double_click

    def mouseDoubleClickEvent(self, event) -> None:
        if self._on_double_click:
            self._on_double_click()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class NoteView(QWidget):
    """便签面板（彩色便利贴列表）"""

    signal_notes_added = Signal(str, str)  # content, color
    signal_note_updated = Signal(str, str, str)  # note_id, content, color
    signal_note_deleted = Signal(str)  # note_id

    def __init__(self, parent=None):
        super().__init__(parent)
        self._notes: list[Note] = []
        self._build_ui()
        self.reapply_theme()

    def _build_ui(self) -> None:
        # 显式 QSS 背景（同 ExpandedView）：避免 QSS 派生调色板渲染默认/陈旧底色
        self.setStyleSheet(f"""
            NoteView {{
                background: {AppTheme.C["bg_primary"]};
            }}
        """)
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ── 顶部工具行 ────────────────────────────────────
        toolbar = QWidget()
        toolbar.setFixedHeight(38)
        toolbar.setStyleSheet("background: transparent;")
        tool_layout = QHBoxLayout()
        tool_layout.setContentsMargins(12, 4, 12, 4)
        tool_layout.setSpacing(8)

        self._count_label = QLabel("0 张便签")
        self._count_label.setStyleSheet(AppTheme.note_meta_style())

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        self._add_btn = QPushButton("＋ 新建便签")
        self._add_btn.setStyleSheet(AppTheme.accent_fill_btn("14px"))
        self._add_btn.setCursor(Qt.PointingHandCursor)
        self._add_btn.clicked.connect(self._on_add_clicked)

        tool_layout.addWidget(self._count_label)
        tool_layout.addWidget(spacer)
        tool_layout.addWidget(self._add_btn)
        toolbar.setLayout(tool_layout)
        main_layout.addWidget(toolbar)

        # ── 便签列表 ──────────────────────────────────────
        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # 框架显式透明：透出 NoteView 根的主题化背景（避免派生调色板渲染黑底）
        self._scroll_area.setStyleSheet(
            "QScrollArea { border: none; background: transparent; }")
        # 视口是列表区最终可见层：objectName + ID 选择器显式画主题背景
        # （透明 QSS 与派生调色板不可靠，会渲染成黑色）
        vp = self._scroll_area.viewport()
        vp.setObjectName("noteListViewport")
        vp.setStyleSheet(f"""
            #noteListViewport {{
                background: {AppTheme.C["bg_primary"]};
            }}
        """)

        self._list_container = QWidget()
        # 与 ExpandedView 相同：显式透明，避免 QSS 派生调色板的默认底色盖住主题背景
        self._list_container.setStyleSheet("background: transparent;")
        self._list_container.setAutoFillBackground(False)
        self._list_layout = QVBoxLayout()
        self._list_layout.setContentsMargins(12, 8, 12, 8)
        self._list_layout.setSpacing(8)
        self._list_layout.addStretch()
        self._list_container.setLayout(self._list_layout)
        self._scroll_area.setWidget(self._list_container)
        main_layout.addWidget(self._scroll_area, stretch=1)

        self.setLayout(main_layout)

    # ── 公开接口 ──────────────────────────────────────────

    def refresh(self, notes: list[Note]) -> None:
        """重建便签列表（便签数量小，全量重建即可）"""
        self._notes = list(notes)

        # 清空列表
        clear_layout(self._list_layout)

        if not notes:
            label = QLabel("还没有便签\n点击右上角 [＋ 新建便签] 记录灵感")
            label.setAlignment(Qt.AlignCenter)
            label.setStyleSheet(f"""
                font: {AppTheme.FONT["body"]};
                color: {AppTheme.C["text_disabled"]};
                padding: 40px 20px;
                background: transparent;
            """)
            self._list_layout.insertWidget(0, label)
        else:
            for note in notes:
                self._list_layout.insertWidget(
                    self._list_layout.count() - 1, self._make_card(note))

        self._count_label.setText(f"{len(notes)} 张便签")

    def focus_add(self) -> None:
        """聚焦新建便签入口"""
        self._add_btn.setFocus()

    def reapply_theme(self) -> None:
        """重新应用主题样式（主题/字号变化时重建）"""
        self.setStyleSheet(f"""
            NoteView {{
                background: {AppTheme.C["bg_primary"]};
            }}
        """)
        self._scroll_area.viewport().setStyleSheet(f"""
            #noteListViewport {{
                background: {AppTheme.C["bg_primary"]};
            }}
        """)
        self._count_label.setStyleSheet(AppTheme.note_meta_style())
        self._add_btn.setStyleSheet(AppTheme.accent_fill_btn("14px"))
        self.refresh(self._notes)

    # ── 内部 ──────────────────────────────────────────────

    def _on_add_clicked(self) -> None:
        """打开新建便签对话框"""
        dialog = NoteDialog(parent=self.window() or self)
        if dialog.exec() == NoteDialog.Accepted:
            content, color = dialog.result_data()
            if content.strip():
                self.signal_notes_added.emit(content.strip(), color)

    def _make_card(self, note: Note) -> QFrame:
        """创建一张便签卡片"""
        card = NoteCard(on_double_click=lambda n=note: self._on_edit(n))
        card.setStyleSheet(AppTheme.note_card_style(note.color))
        card.setCursor(Qt.PointingHandCursor)

        layout = QVBoxLayout()
        layout.setContentsMargins(10, 8, 10, 6)
        layout.setSpacing(4)

        # 内容预览（最多 100 字符，tooltip 显示全文）
        preview = note.content.strip()
        preview_text = preview[:100] + ("..." if len(preview) > 100 else "")
        content_label = QLabel(preview_text)
        content_label.setStyleSheet(AppTheme.note_text_style())
        content_label.setWordWrap(True)
        content_label.setMaximumHeight(60)
        content_label.setToolTip(preview)
        content_label.setTextInteractionFlags(Qt.NoTextInteraction)
        layout.addWidget(content_label)

        # 底部行：更新时间 + 操作按钮
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(4)

        time_label = QLabel(f"更新于 {_format_note_time(note.updated_at)}")
        time_label.setStyleSheet(AppTheme.note_meta_style())

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        edit_btn = QPushButton("✎")
        edit_btn.setFixedSize(22, 22)
        edit_btn.setToolTip("编辑便签")
        edit_btn.setStyleSheet(AppTheme.icon_btn("12px"))
        edit_btn.clicked.connect(lambda checked, n=note: self._on_edit(n))

        delete_btn = QPushButton("✕")
        delete_btn.setFixedSize(22, 22)
        delete_btn.setToolTip("删除便签")
        delete_btn.setStyleSheet(AppTheme.danger_btn("12px"))
        delete_btn.clicked.connect(lambda checked, n=note: self._on_delete(n))

        bottom_row.addWidget(time_label)
        bottom_row.addWidget(spacer)
        bottom_row.addWidget(edit_btn)
        bottom_row.addWidget(delete_btn)
        layout.addLayout(bottom_row)

        card.setLayout(layout)
        return card

    def _on_edit(self, note: Note) -> None:
        """打开编辑对话框"""
        dialog = NoteDialog(parent=self.window() or self, note=note)
        if dialog.exec() == NoteDialog.Accepted:
            content, color = dialog.result_data()
            if content.strip() and (content.strip() != note.content or color != note.color):
                self.signal_note_updated.emit(note.id, content.strip(), color)

    def _on_delete(self, note: Note) -> None:
        """删除便签（无确认，便签价值低，可再新建）"""
        self.signal_note_deleted.emit(note.id)


def _format_note_time(iso_str: str) -> str:
    """ISO 时间 → 简单日期显示"""
    from datetime import datetime
    try:
        dt = datetime.fromisoformat(iso_str)
        return dt.strftime("%m月%d日 %H:%M")
    except (ValueError, TypeError):
        return iso_str
