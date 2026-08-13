"""
SVG 图标渲染模块

从 app/resources/icons/*.svg 加载单色 SVG，按主题色着色后渲染为 QIcon。

设计要点：
- SVG 文件统一使用 #000000 作为占位色，渲染前字符串替换为目标色
- 缓存按 (名称, 尺寸, 颜色) 键控，主题/字号变化时颜色改变自然生成新版
- 主题切换时 AppTheme 调用 clear() 释放旧缓存
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QByteArray, QRectF
from PySide6.QtGui import QIcon, QPixmap, QPainter
from PySide6.QtSvg import QSvgRenderer

from app.config import AppConfig

_ICON_DIR = AppConfig.resource_path("app/resources/icons")
_PLACEHOLDER = "#000000"


class AppIcons:
    """SVG 图标工厂（单色、可随主题变色）"""

    _cache: dict[tuple[str, int, str], QIcon] = {}

    @classmethod
    def get(
        cls,
        name: str,
        size: int = 16,
        color: str | None = None,
        active_color: str | None = None,
    ) -> QIcon:
        """获取指定图标。color 缺省取次要文字色，active_color 缺省取强调色。

        返回的 QIcon 含 Normal（color）与 Active（active_color）两态，
        按钮 hover 时自动切换到 Active 图标。
        """
        from app.views.theme import AppTheme
        if color is None:
            color = AppTheme.C["text_secondary"]
        if active_color is None:
            active_color = AppTheme.C["accent"]

        key = (name, size, color, active_color)
        cached = cls._cache.get(key)
        if cached is not None:
            return cached

        icon = QIcon()
        icon.addPixmap(cls._render_pixmap(name, size, color), QIcon.Mode.Normal)
        icon.addPixmap(cls._render_pixmap(name, size, active_color), QIcon.Mode.Active)
        cls._cache[key] = icon
        return icon

    @classmethod
    def _render_pixmap(cls, name: str, size: int, color: str) -> QPixmap:
        """读取 SVG → 替换占位色 → QSvgRenderer 渲染为 QPixmap"""
        path = _ICON_DIR / f"{name}.svg"
        if not path.exists():
            return QPixmap()

        data = path.read_text(encoding="utf-8").replace(_PLACEHOLDER, color)
        renderer = QSvgRenderer(QByteArray(data.encode("utf-8")))
        if not renderer.isValid():
            return QPixmap()

        # 2x 渲染 + devicePixelRatio，保证高分屏清晰
        # 必须显式指定目标矩形，否则 QSvgRenderer 在 DPR=2 的 pixmap 上渲染错位/裁剪
        pixmap = QPixmap(size * 2, size * 2)
        pixmap.setDevicePixelRatio(2.0)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter, QRectF(0, 0, size, size))
        painter.end()
        return pixmap

    @classmethod
    def clear(cls) -> None:
        """清空缓存（主题切换时由 AppTheme 调用）"""
        cls._cache.clear()
