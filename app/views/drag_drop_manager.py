"""
拖放排序管理器

处理待办卡片的拖拽排序，包含：
- 拖入/移动/离开/放下事件处理
- 插入指示线渲染
- 拖拽自动滚动
"""

from __future__ import annotations

from typing import Callable, Generator

from PySide6.QtCore import QPoint, QEvent, Signal, QObject
from PySide6.QtWidgets import QFrame, QScrollArea, QVBoxLayout
from app.views.theme import AppTheme


class DragDropManager(QObject):
    """拖放排序管理器，封装 ExpandedView 中的所有拖放逻辑"""

    signal_reorder_items = Signal(list)  # [item_id, ...]

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._list_container: QFrame | None = None
        self._list_layout: QVBoxLayout | None = None
        self._scroll_area: QScrollArea | None = None
        self._iter_cards: Callable[[], Generator] = lambda: iter([])
        self._is_searching: Callable[[], bool] = lambda: False

        self._drop_indicator: QFrame | None = None
        self._drop_local_pos: QPoint | None = None

    def install(
        self,
        list_container: QFrame,
        list_layout: QVBoxLayout,
        scroll_area: QScrollArea,
        iter_cards: Callable[[], Generator],
        is_searching: Callable[[], bool],
    ) -> None:
        """安装到 ExpandedView 的列表容器"""
        self._list_container = list_container
        self._list_layout = list_layout
        self._scroll_area = scroll_area
        self._iter_cards = iter_cards
        self._is_searching = is_searching
        list_container.setAcceptDrops(True)

    def clear(self) -> None:
        """清空状态（refresh/clear_list 时调用）"""
        if self._drop_indicator:
            self._drop_indicator.deleteLater()
            self._drop_indicator = None
        self._drop_local_pos = None

    # ── 事件分发 ──────────────────────────────────────────

    def is_valid_drag(self, event: QEvent) -> bool:
        """检查是否为有效的卡片拖放事件"""
        if self._is_searching():
            return False
        mime = event.mimeData()
        return mime.hasText() and mime.text().startswith("todo-card:")

    def _drag_local_pos(self, event: QEvent, is_viewport: bool) -> QPoint:
        """获取容器坐标系下的拖放位置"""
        if is_viewport:
            return self._list_container.mapFrom(
                self._scroll_area.viewport(), event.position().toPoint())
        return event.position().toPoint()

    def handle_drag_enter(self, event: QEvent) -> bool:
        if not self.is_valid_drag(event):
            return False
        event.acceptProposedAction()
        self._show_drop_indicator(event)
        return True

    def handle_drag_move(self, event: QEvent, is_viewport: bool) -> bool:
        if not self.is_valid_drag(event):
            return False
        self._drop_local_pos = self._drag_local_pos(event, is_viewport)
        event.acceptProposedAction()
        self._update_drop_indicator(event)
        self._scroll_during_drag(event)
        return True

    def handle_drag_leave(self) -> bool:
        self._hide_drop_indicator()
        return True

    def handle_drag_drop(self, event: QEvent, is_viewport: bool) -> bool:
        if not self.is_valid_drag(event):
            return False
        self._drop_local_pos = self._drag_local_pos(event, is_viewport)
        self._hide_drop_indicator()
        self._handle_drop(event)
        event.acceptProposedAction()
        return True

    # ── 指示器 ────────────────────────────────────────────

    def _show_drop_indicator(self, event: QEvent) -> None:
        """创建插入指示线"""
        if self._drop_indicator is None:
            self._drop_indicator = QFrame(self._list_container)
            margin = self._list_layout.contentsMargins()
            w = self._list_container.width() - margin.left() - margin.right()
            if w < 10:
                w = 200
            self._drop_indicator.setFixedSize(int(w), 3)
            self._drop_indicator.setStyleSheet(f"""
                background: {AppTheme.C["accent"]};
                border-radius: 1px;
            """)
            self._drop_indicator.hide()
        self._update_drop_indicator(event)
        self._drop_indicator.raise_()
        self._drop_indicator.show()

    def _update_drop_indicator(self, event: QEvent) -> None:
        """更新指示线位置到最近的卡片间隙"""
        if self._drop_indicator is None:
            return
        y = self._drop_position_y(event)
        margin = self._list_layout.contentsMargins()
        self._drop_indicator.move(margin.left(), y)

    def _hide_drop_indicator(self) -> None:
        """隐藏插入指示线"""
        if self._drop_indicator:
            self._drop_indicator.hide()

    # ── 定位 ──────────────────────────────────────────────

    def _drop_pos(self, event: QEvent) -> QPoint:
        """从事件中提取容器坐标系下的位置"""
        if self._drop_local_pos is not None:
            return self._drop_local_pos
        return event.position().toPoint()

    def _drop_position_y(self, event: QEvent) -> int:
        """计算指示线应放置的 Y 坐标"""
        margin = self._list_layout.contentsMargins()
        mouse_y = self._drop_pos(event).y()
        y = margin.top()

        for w in self._iter_cards():
            if not w.isVisible():
                continue
            card_rect = w.geometry()
            mid = card_rect.top() + card_rect.height() // 2
            if mouse_y <= mid:
                return card_rect.top()
            y = card_rect.bottom() + 1

        return y

    # ── 自动滚动 ──────────────────────────────────────────

    def _scroll_during_drag(self, event: QEvent) -> None:
        """拖拽时根据鼠标位置自动滚动"""
        viewport = self._scroll_area.viewport()
        pos = viewport.mapFrom(self._list_container, self._drop_pos(event))
        scrollbar = self._scroll_area.verticalScrollBar()
        scroll_step = 20
        margin = 30

        if pos.y() < margin:
            scrollbar.setValue(scrollbar.value() - scroll_step)
        elif pos.y() > viewport.height() - margin:
            scrollbar.setValue(scrollbar.value() + scroll_step)

    # ── 完成 ──────────────────────────────────────────────

    def _handle_drop(self, event: QEvent) -> None:
        """处理拖放完成——重新排序并发送信号"""
        text = event.mimeData().text()
        if not text.startswith("todo-card:"):
            return
        dragged_id = text.replace("todo-card:", "")

        mouse_pos = self._drop_pos(event)
        ordered: list[str] = []
        inserted = False

        for w in self._iter_cards():
            if not w.isVisible():
                continue
            card_id = w.property("todo_item_id")
            if card_id == dragged_id:
                continue
            card_rect = w.geometry()
            mid = card_rect.top() + card_rect.height() // 2
            if not inserted and mouse_pos.y() <= mid:
                ordered.append(dragged_id)
                inserted = True
            ordered.append(card_id)

        if not inserted:
            ordered.append(dragged_id)

        if ordered:
            self.signal_reorder_items.emit(ordered)
