"""
统计弹出面板

独立组件：展示 待办 / 今日完成 / 本周完成 / 累计完成 / 归档 统计。
本身不负责定位与显隐（由 ExpandedView 负责锚定与事件过滤器），
只负责根据统计数据渲染文本并按主题刷新样式。
"""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout

from app.views.theme import AppTheme


class StatsPanel(QFrame):
    """统计面板"""

    def __init__(self, parent=None):
        super().__init__(parent)

        self._labels: list[QLabel] = []

        self.setFixedSize(180, 110)
        self.setStyleSheet(AppTheme.popup_panel_style())
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(3)

        for _ in range(5):
            label = QLabel("")
            label.setStyleSheet(AppTheme.panel_label_style())
            layout.addWidget(label)
            self._labels.append(label)

        self.hide()

    def show_stats(self, stats: dict) -> None:
        """按统计数据填充文本（仅渲染，不负责显示/定位）"""
        lines = [
            f"待办 {stats['active_count']} 项",
            f"今日完成 {stats['today_completed']} 项",
            f"本周完成 {stats['week_completed']} 项",
            f"累计完成 {stats['total_completed']} 项",
            f"归档 {stats['archived_count']} 条",
        ]
        for label, text in zip(self._labels, lines, strict=False):
            label.setText(text)

    def reapply_theme(self) -> None:
        """重新应用当前主题样式（主题切换时调用）"""
        self.setStyleSheet(AppTheme.popup_panel_style())
        for label in self._labels:
            label.setStyleSheet(AppTheme.panel_label_style())
