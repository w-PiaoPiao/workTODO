"""
截止日期提醒服务

职责：检查到期/过期待办并触发通知，每天每项只提醒一次。
与视图/托盘解耦：通过 configure() 注入数据源与通知回调，
定时器由本服务内部驱动（每小时一次，见 AppConfig.DUE_REMIND_CHECK_MS）。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime

from PySide6.QtCore import QObject, QTimer

from app.config import AppConfig
from app.models.todo_item import CST, TodoItem, _parse_due_date

logger = logging.getLogger(__name__)


class ReminderService(QObject):
    """截止日期提醒：每小时检查，每天每项只提醒一次"""

    def __init__(self, parent=None):
        super().__init__(parent)

        self._todos_provider: Callable[[], list[TodoItem]] | None = None
        self._notify: Callable[[str], None] | None = None
        self._supports_messages: Callable[[], bool] | None = None

        self._timer = QTimer(self)
        self._timer.setInterval(AppConfig.DUE_REMIND_CHECK_MS)
        self._timer.timeout.connect(self.check)
        self._timer.start()

    def configure(self, todos_provider: Callable[[], list[TodoItem]],
                  notify: Callable[[str], None],
                  supports_messages: Callable[[], bool] | None = None) -> None:
        """注入数据源、通知回调与托盘支持探测（由控制器在启动时调用）"""
        self._todos_provider = todos_provider
        self._notify = notify
        self._supports_messages = supports_messages

    def check(self) -> None:
        """检查到期/过期待办并发送提醒（每天每项只提醒一次）"""
        if not self._todos_provider or not self._notify:
            return
        # 托盘不支持气泡通知时跳过（内部定时器每小时触发，不能只靠
        # 控制器启动时的一次性判断，否则会做无意义的检查与注册表写入）
        if self._supports_messages is not None and not self._supports_messages():
            return
        today = datetime.now(CST).date()
        today_key = today.isoformat()
        settings = AppConfig.settings()
        # filter(None, ...)：空存储值 split 出的 "" 占位不写回（避免脏数据累积）
        reminded = set(filter(None, (settings.value(f"reminders/{today_key}", "") or "").split(",")))

        overdue: list[str] = []
        due_today: list[str] = []
        newly_reminded: list[str] = []
        for t in self._todos_provider():
            if not t.is_active or not t.due_date:
                continue
            if t.id in reminded:
                continue
            try:
                due = _parse_due_date(t.due_date)
            except ValueError:
                continue
            if due < today:
                overdue.append(t.title)
                newly_reminded.append(t.id)
            elif due == today:
                due_today.append(t.title)
                newly_reminded.append(t.id)

        if overdue or due_today:
            parts = []
            if overdue:
                parts.append(f"已过期：{'、'.join(overdue[:3])}")
            if due_today:
                parts.append(f"今日到期：{'、'.join(due_today[:3])}")
            self._notify("；".join(parts))

        # 只记录“实际已提醒”的 id，避免未来到期项提前占位、
        # 导致用户当天改期到今天时漏提醒（今天已提醒的仍累计保留）
        if newly_reminded:
            reminded.update(newly_reminded)
            settings.setValue(f"reminders/{today_key}", ",".join(sorted(reminded)))

        # 清理历史日期的提醒键，防止 QSettings 键无限累积
        for key in settings.allKeys():
            if key.startswith("reminders/") and key != f"reminders/{today_key}":
                settings.remove(key)
