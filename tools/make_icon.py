"""
生成应用图标 icon.ico（多尺寸，与托盘图标同风格）

用法：
    python tools/make_icon.py

产物：app/resources/icon.ico
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "app" / "resources" / "icon.ico"
SIZES = (256, 128, 64, 48, 32, 16)
BG = "#0078D4"
CHECK = "#0078D4"
WHITE = "#FFFFFF"


def draw_icon(size: int) -> Image.Image:
    """绘制单个尺寸的图标"""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    s = size
    m = max(1, s // 16)
    inner = s - 2 * m
    radius = inner // 4

    # 背景：蓝色圆角方块
    d.rounded_rectangle(
        (m, m, s - m, s - m), radius=radius, fill=BG)

    # 顶部高光
    d.rounded_rectangle(
        (m, m, s - m, m + inner // 3), radius=radius, fill=(255, 255, 255, 40))
    d.rectangle((m, m + inner // 6, s - m, m + inner // 6 + 2), fill=(255, 255, 255, 40))

    # 白色剪切板
    pm = max(2, s // 5)
    pw = s - 2 * pm
    ph = int(pw * 1.15)
    px, py = pm, pm + 1
    paper_r = max(2, s // 14)
    d.rounded_rectangle(
        (px, py, px + pw, py + ph), radius=paper_r, fill=(255, 255, 255, 235))

    # 回形针
    cw = max(3, s // 9)
    ch = max(3, s // 7)
    cx = (s - cw) // 2
    cy = py - 1
    d.rounded_rectangle((cx, cy, cx + cw, cy + ch), radius=2, fill=BG)

    # 勾号
    lw = max(2, s // 12)
    left_x = px + pw * 0.20
    mid_x = px + pw * 0.46
    mid_y = py + ph * 0.60
    right_x = px + pw * 0.80
    top_y = py + ph * 0.30
    d.line([(left_x, mid_y), (mid_x, py + ph * 0.74), (right_x, top_y)],
           fill=CHECK, width=lw, joint="curve")

    return img


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    images = [draw_icon(size) for size in SIZES]
    # ICO 保存多尺寸：最大的在前，Windows 按需取用
    images[0].save(
        OUT, format="ICO",
        sizes=[(size, size) for size in SIZES],
        append_images=images[1:],
    )
    print(f"已生成 {OUT}（{len(SIZES)} 个尺寸）")


if __name__ == "__main__":
    main()
