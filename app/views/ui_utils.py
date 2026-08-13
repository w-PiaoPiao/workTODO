"""
UI 公共工具

- DragMixin：无边框窗口鼠标拖拽混入（QDialog 等复用）
- clear_layout：清空布局中的 widget（保留末尾 stretch）
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QMouseEvent


class DragMixin:
    """无边框窗口拖拽混入：按下记录偏移，移动跟随，松开复位

    依赖宿主类（QWidget/QDialog）自带 frameGeometry() / move()，
    宿主需在 __init__ 中初始化 self._drag_pos = QPoint()。
    """

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_pos = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if event.buttons() == Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_pos = QPoint()
            event.accept()


def clear_layout(layout, keep: int = 1) -> None:
    """清空布局中的 widget，保留末尾 keep 个 item（默认保留 stretch）"""
    while layout.count() > keep:
        item = layout.takeAt(0)
        w = item.widget()
        if w:
            w.deleteLater()
