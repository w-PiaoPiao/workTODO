"""
设置弹出面板

独立组件：透明度滑块 + 字号缩放滑块 + 桌宠形象切换。
通过信号向外部（ExpandedView / Controller）上报：
- signal_opacity_changed       透明度实时变化
- signal_opacity_committed     滑块松手（持久化）
- signal_font_scale_committed  字号缩放（松手应用并持久化）
- signal_pet_selected          桌宠形象切换
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
)

from app.config import AppConfig
from app.views.theme import AppTheme


class SettingsPanel(QFrame):
    """设置面板：透明度 / 字号 / 桌宠形象"""

    signal_opacity_changed = Signal(float)  # 0.0 ~ 1.0（实时窗口）
    signal_opacity_committed = Signal(float)  # 0.0 ~ 1.0（松手持久化）
    signal_font_scale_committed = Signal(float)  # 字号缩放（松手应用+持久化）
    signal_pet_selected = Signal(str)  # 桌宠形象 id

    def __init__(self, parent=None):
        super().__init__(parent)

        self._opacity = AppConfig.WINDOW_OPACITY_DEFAULT
        self._pets: list[dict] = []  # 桌宠形象 [{id, name, path}]
        self._selected_pet_id = ""  # 当前选中桌宠形象 id
        self._pet_buttons: dict[str, QPushButton] = {}  # pet_id → 缩略图按钮
        self._pet_thumb_icons: dict[str, QIcon] = {}  # pet_id → 缩略图图标缓存

        self.setFixedWidth(220)
        self._build_ui()
        self.hide()

    # ── UI 构建 ──────────────────────────────────────────

    def _build_ui(self) -> None:
        """构建面板布局（透明度 + 字号 + 桌宠）"""
        self.setStyleSheet(AppTheme.popup_panel_style())
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(4)

        # ── 透明度行 ────────────────────────────────────
        opacity_row = QHBoxLayout()
        opacity_row.setSpacing(8)
        opacity_label = QLabel("透明度")
        opacity_label.setStyleSheet(AppTheme.panel_label_style())
        opacity_label.setFixedWidth(44)

        self._opacity_label = QLabel("100%")
        self._opacity_label.setStyleSheet(AppTheme.panel_label_style())
        self._opacity_label.setMinimumWidth(36)

        self._opacity_slider = QSlider(Qt.Horizontal)
        self._opacity_slider.setRange(
            int(AppConfig.WINDOW_OPACITY_MIN * 100),
            int(AppConfig.WINDOW_OPACITY_MAX * 100),
        )
        self._opacity_slider.setValue(int(self._opacity * 100))
        self._opacity_slider.valueChanged.connect(self._on_opacity_slider_changed)
        self._opacity_slider.sliderReleased.connect(self._on_opacity_committed)

        opacity_row.addWidget(opacity_label)
        opacity_row.addWidget(self._opacity_slider, stretch=1)
        opacity_row.addWidget(self._opacity_label)

        # ── 字号行 ──────────────────────────────────────
        font_row = QHBoxLayout()
        font_row.setSpacing(8)
        font_label = QLabel("字号")
        font_label.setStyleSheet(AppTheme.panel_label_style())
        font_label.setFixedWidth(44)

        self._font_label = QLabel("100%")
        self._font_label.setStyleSheet(AppTheme.panel_label_style())
        self._font_label.setMinimumWidth(36)

        self._font_slider = QSlider(Qt.Horizontal)
        self._font_slider.setRange(
            int(AppConfig.FONT_SCALE_MIN * 100),
            int(AppConfig.FONT_SCALE_MAX * 100),
        )
        self._font_slider.setValue(int(AppTheme.font_scale() * 100))
        self._font_slider.valueChanged.connect(self._on_font_slider_changed)
        self._font_slider.sliderReleased.connect(self._on_font_committed)

        font_row.addWidget(font_label)
        font_row.addWidget(self._font_slider, stretch=1)
        font_row.addWidget(self._font_label)

        # ── 桌宠行 ──────────────────────────────────────
        pet_row = QHBoxLayout()
        pet_row.setSpacing(6)
        pet_label = QLabel("宠物")
        pet_label.setStyleSheet(AppTheme.panel_label_style())
        pet_label.setFixedWidth(44)
        self._pet_thumbs_row = QHBoxLayout()
        self._pet_thumbs_row.setSpacing(4)
        pet_row.addWidget(pet_label)
        pet_row.addLayout(self._pet_thumbs_row, stretch=1)

        layout.addLayout(opacity_row)
        layout.addLayout(font_row)
        layout.addLayout(pet_row)
        self.adjustSize()

    # ── 公开接口 ──────────────────────────────────────────

    def set_opacity_value(self, value: float) -> None:
        """设置透明度值并同步滑块（由控制器调用，恢复持久化值）"""
        self._opacity = value
        self._opacity_slider.setValue(int(value * 100))

    def set_font_scale_value(self, scale: float) -> None:
        """设置字号缩放并同步滑块（由控制器调用，恢复持久化值）"""
        self._font_slider.setValue(int(scale * 100))
        self._font_label.setText(f"{int(scale * 100)}%")

    def set_pets(self, pets: list[dict], selected_id: str) -> None:
        """设置桌宠形象列表并构建缩略图按钮（由控制器调用）"""
        self._pets = list(pets)
        self._selected_pet_id = selected_id

        while self._pet_thumbs_row.count():
            item = self._pet_thumbs_row.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._pet_buttons.clear()
        self._pet_thumb_icons.clear()

        for pet in pets:
            pixmap = QPixmap(str(pet["path"]))
            icon = QIcon(pixmap.scaled(
                26, 26, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self._pet_thumb_icons[pet["id"]] = icon

            btn = QPushButton()
            btn.setFixedSize(30, 30)
            btn.setIconSize(QSize(26, 26))
            btn.setIcon(icon)
            btn.setToolTip(pet["name"])
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(AppTheme.pet_thumb_btn(pet["id"] == selected_id))
            btn.clicked.connect(
                lambda checked=False, pid=pet["id"]: self._on_pet_thumb_clicked(pid))
            self._pet_thumbs_row.addWidget(btn)
            self._pet_buttons[pet["id"]] = btn

    def set_selected_pet(self, pet_id: str) -> None:
        """高亮当前选中的桌宠形象（由控制器调用）"""
        self._selected_pet_id = pet_id
        for pid, btn in self._pet_buttons.items():
            btn.setStyleSheet(AppTheme.pet_thumb_btn(pid == pet_id))

    def reapply_theme(self) -> None:
        """重新应用当前主题样式（主题切换时调用）"""
        self.setStyleSheet(AppTheme.popup_panel_style())
        self._opacity_label.setStyleSheet(AppTheme.panel_label_style())
        self._font_label.setStyleSheet(AppTheme.panel_label_style())
        # 桌宠缩略图按钮也随主题刷新（保持选中态高亮）
        for pid, btn in self._pet_buttons.items():
            btn.setStyleSheet(AppTheme.pet_thumb_btn(pid == self._selected_pet_id))

    # ── 内部交互 ──────────────────────────────────────────

    def _on_pet_thumb_clicked(self, pet_id: str) -> None:
        """桌宠形象缩略图点击"""
        self.set_selected_pet(pet_id)
        self.signal_pet_selected.emit(pet_id)

    def _on_opacity_slider_changed(self, value: int) -> None:
        """滑块值变化时实时更新窗口透明度"""
        opacity = value / 100.0
        self._opacity = opacity
        self._opacity_label.setText(f"{value}%")
        self.signal_opacity_changed.emit(opacity)

    def _on_opacity_committed(self) -> None:
        """松手后持久化透明度（避免拖动时高频写注册表）"""
        self.signal_opacity_committed.emit(self._opacity)

    def _on_font_slider_changed(self, value: int) -> None:
        """字号滑块变化：仅更新显示，松手才应用"""
        self._font_label.setText(f"{value}%")

    def _on_font_committed(self) -> None:
        """字号滑块松手：应用缩放并持久化"""
        scale = self._font_slider.value() / 100.0
        self.signal_font_scale_committed.emit(scale)
