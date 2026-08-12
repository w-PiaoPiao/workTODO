"""
生成桌宠默认形象 PNG（emoji 渲染，透明背景）

用法：
    python tools/make_pet_placeholders.py

产物：app/resources/pets/{cat,dog,rabbit,panda}.png
用户后续可把自定义 PNG/JPG/GIF 放入该目录（或 data/pets/）替换/增补。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QGuiApplication, QPainter, QPixmap

PETS = {
    "cat": "🐱",
    "dog": "🐶",
    "rabbit": "🐰",
    "panda": "🐼",
}
SIZE = 512
OUT_DIR = Path(__file__).resolve().parent.parent / "app" / "resources" / "pets"


def render_emoji(emoji: str, size: int, out: Path) -> None:
    """用系统 emoji 字体渲染到透明 PNG（Windows 11: Segoe UI Emoji）"""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    font = QFont("Segoe UI Emoji")
    font.setPixelSize(int(size * 0.82))
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignCenter, emoji)
    painter.end()
    pixmap.save(str(out), "PNG")


def main() -> None:
    app = QGuiApplication([])
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, emoji in PETS.items():
        out = OUT_DIR / f"{name}.png"
        render_emoji(emoji, SIZE, out)
        print(f"已生成 {out}")


if __name__ == "__main__":
    main()
