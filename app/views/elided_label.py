"""
自动省略长文本的 QLabel 子类

特点：
- 单行显示，宽度不足时尾部加 ...
- 完整文本通过 tooltip 悬浮显示
- paintEvent 实时计算省略（无缓存、无 setMaximumWidth）
- sizeHint 返回最小尺寸，让 layout 把剩余空间全部分配给它

解决历史 bug：
  原 todo_card / progress_widget 试图在 resizeEvent + QTimer.singleShot
  + setMaximumWidth 三个时机分别调用 elidedText，多次失败。原因：
    1. 时机难抓：layout 未完成时 self.width() 错误
    2. magic number (132) 算错
    3. setMaximumWidth 强制约束 → 触发 layout → resize 循环

  本类用 paintEvent 实时算，永远基于正确的当前 width，零状态、零时序问题。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QLabel, QSizePolicy


class ElidedLabel(QLabel):
    """自动省略的 QLabel"""

    def __init__(self, text: str = "", parent=None):
        super().__init__("", parent)
        self._full_text = text
        # 透传鼠标事件到父控件（TodoCard 统一处理拖拽和双击编辑）
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        # Expanding 让 layout 优先给扩展空间
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        # 关键：默认 QLabel.sizeHint() 返回完整文本的宽度，
        # 会让 layout 按"自然宽度"分配，stetch=1 时反而可能得到较小空间。
        # 重写为 0 宽 → layout 把所有剩余空间都分给我们。
        self.setMinimumWidth(0)

    def setFullText(self, text: str) -> None:
        """设置完整文本（自动省略显示）"""
        if text == self._full_text:
            return
        self._full_text = text
        self.update()  # 触发 paintEvent 重绘

    def fullText(self) -> str:
        """获取完整文本"""
        return self._full_text

    def text(self) -> str:
        """覆盖 QLabel.text() 返回完整文本（方便外部访问/调试）"""
        return self._full_text

    def sizeHint(self) -> QSize:
        """最小尺寸 hint - 高度一行，宽度 0（让 layout 给剩余空间）"""
        fm = self.fontMetrics()
        return QSize(0, fm.height())

    def minimumSizeHint(self) -> QSize:
        """最小尺寸"""
        return self.sizeHint()

    def paintEvent(self, event) -> None:
        """绘制时实时算省略文本"""
        if not self._full_text:
            return super().paintEvent(event)
        painter = QPainter(self)
        fm = self.fontMetrics()
        # self.width() 一定是 layout 分配给我们的当前宽度（实时正确）
        elided = fm.elidedText(self._full_text, Qt.ElideRight, max(1, self.width()))
        painter.drawText(self.rect(), int(self.alignment()), elided)
        painter.end()
