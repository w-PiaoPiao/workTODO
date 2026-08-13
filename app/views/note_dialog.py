"""
便签编辑对话框

新建/编辑彩色便签：多行文本 + 颜色选择。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QPoint
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QWidget, QSizePolicy,
)
from app.config import AppConfig
from app.views.theme import AppTheme
from app.views.ui_utils import DragMixin
from app.models.note import Note


class NoteDialog(DragMixin, QDialog):
    """便签编辑对话框"""

    def __init__(self, parent=None, note: Note | None = None):
        super().__init__(parent)
        self._note = note
        self._selected_color = note.color if note else "yellow"
        self._drag_pos = QPoint()

        self.setWindowTitle("编辑便签" if note else "新建便签")
        self.setFixedSize(340, 280)
        self.setWindowFlags(
            Qt.Dialog | Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint
        )
        self.setStyleSheet(AppTheme.dialog_frame_style())

        self._build_ui()
        if note:
            self._text_edit.setPlainText(note.content)

    # ── UI ────────────────────────────────────────────────

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

        title_label = QLabel("📝 " + ("编辑便签" if self._note else "新建便签"))
        title_label.setStyleSheet(f"font: {AppTheme.FONT['title']}; background: transparent;")

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(28, 28)
        close_btn.setStyleSheet(AppTheme.close_btn())
        close_btn.clicked.connect(self.reject)

        title_layout.addWidget(title_label)
        title_layout.addWidget(spacer)
        title_layout.addWidget(close_btn)
        title_bar.setLayout(title_layout)
        layout.addWidget(title_bar)

        # ── 内容区 ────────────────────────────────────────
        content = QWidget()
        content.setStyleSheet("background: transparent;")
        content_layout = QVBoxLayout()
        content_layout.setContentsMargins(12, 8, 12, 8)
        content_layout.setSpacing(8)

        self._text_edit = QTextEdit()
        self._text_edit.setPlaceholderText("在这里记录便签内容...")
        self._text_edit.setFixedHeight(150)
        self._text_edit.setStyleSheet("""
            QTextEdit {
                border: 1px solid %s;
                border-radius: 4px;
                padding: 6px;
                background: %s;
                color: %s;
            }
            QTextEdit:focus { border-color: %s; }
        """ % (
            AppTheme.C["border"], AppTheme.C["bg_card"],
            AppTheme.C["text_primary"], AppTheme.C["accent"],
        ))
        content_layout.addWidget(self._text_edit)

        # ── 颜色选择行 ────────────────────────────────────
        color_label = QLabel("颜色")
        color_label.setStyleSheet(AppTheme.panel_label_style())
        color_row = QHBoxLayout()
        color_row.setSpacing(6)
        color_row.addWidget(color_label)
        for key in AppConfig.NOTE_COLORS:
            btn = QPushButton()
            btn.setFixedSize(20, 20)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setProperty("note_color_key", key)
            btn.setStyleSheet(AppTheme.note_color_btn(key, key == self._selected_color))
            btn.clicked.connect(lambda checked, k=key: self._select_color(k))
            color_row.addWidget(btn)
        color_row.addStretch(1)
        content_layout.addLayout(color_row)

        # ── 按钮行 ────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        cancel_btn = QPushButton("取消")
        cancel_btn.setFixedHeight(28)
        cancel_btn.setStyleSheet(AppTheme.outline_btn())
        cancel_btn.clicked.connect(self.reject)

        save_btn = QPushButton("保存")
        save_btn.setFixedHeight(28)
        save_btn.setStyleSheet(AppTheme.accent_fill_btn("14px"))
        save_btn.clicked.connect(self.accept)

        btn_row.addStretch(1)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        content_layout.addLayout(btn_row)

        content.setLayout(content_layout)
        layout.addWidget(content, stretch=1)
        self.setLayout(layout)

    # ── 内部 ──────────────────────────────────────────────

    def _select_color(self, color_key: str) -> None:
        """切换选中颜色并刷新按钮样式"""
        self._selected_color = color_key
        content_layout = self.layout().itemAt(1).layout()
        color_row = content_layout.itemAt(1).layout()  # 0=text_edit, 1=color_row
        for i in range(color_row.count()):
            btn = color_row.itemAt(i).widget()
            if isinstance(btn, QPushButton) and btn.property("note_color_key"):
                key = btn.property("note_color_key")
                btn.setStyleSheet(AppTheme.note_color_btn(key, key == self._selected_color))

    def result_data(self) -> tuple[str, str]:
        """返回 (内容, 颜色)"""
        return self._text_edit.toPlainText(), self._selected_color
