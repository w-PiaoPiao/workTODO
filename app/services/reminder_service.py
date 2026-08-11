"""
截止日期提醒服务

职责：检查到期/过期待办并触发通知，每天每项只提醒一次。
与视图/托盘解耦：通过 configure() 注入数据源与通知回调，
定时器由本服务内部驱动（每小时一次，见 AppConfig.DUE_REMIND_CHECK_MS）。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Callable, Optional

from PySide6.QtCore import QObject, QSettings, QTimer

from app.config import AppConfig
from app.models.todo_item import CST, TodoItem, _parse_due_date

logger = logging.getLogger(__name__)


class ReminderService(QObject):
    """截止日期提醒：每小时检查，每天每项只提醒一次"""

    def __init__(self, parent=None):
        super().__init__(parent)

        self._todos_provider: Optional[Callable[[], list[TodoItem]]] = None
        self._notify: Optional[Callable[[str], None]] = None

        self._timer = QTimer(self)
        self._timer.setInterval(AppConfig.DUE_REMIND_CHECK_MS)
        self._timer.timeout.connect(self.check)
        self._timer.start()

    def configure(self, todos_provider: Callable[[], list[TodoItem]],
                  notify: Callable[[str], None]) -> None:
        """注入数据源与通知回调（由控制器在启动时调用）"""
        self._todos_provider = todos_provider
        self._notify = notify

    def check(self) -> None:
        """检查到期/过期待办并发送提醒（每天每项只提醒一次）"""
        if not self._todos_provider or not self._notify:
            return
        today = datetime.now(CST).date()
        today_key = today.isoformat()
        settings = QSettings("Personal", "待办事项和便签")
        reminded = set((settings.value(f"reminders/{today_key}", "") or "").split(","))

        overdue: list[str] = []
        due_today: list[str] = []
        touched_ids: list[str] = []
        for t in self._todos_provider():
            if not t.is_active or not t.due_date:
                continue
            touched_ids.append(t.id)
            if t.id in reminded:
                continue
            try:
                due = _parse_due_date(t.due_date)
            except ValueError:
                continue
            if due < today:
                overdue.append(t.title)
            elif due == today:
                due_today.append(t.title)

        if overdue or due_today:
            parts = []
            if overdue:
                parts.append(f"已过期：{'、'.join(overdue[:3])}")
            if due_today:
                parts.append(f"今日到期：{'、'.join(due_today[:3])}")
            self._notify("；".join(parts))

        # 标记本次已检查的 id，避免重复提醒
        if touched_ids:
            settings.setValue(f"reminders/{today_key}", ",".join(touched_ids))
