# -*- coding: utf-8 -*-
"""图片读写 —— Pillow 只做 I/O 和缩放，合成算法在 phantom / reveal 里用 numpy 做。"""
from __future__ import annotations

from pathlib import Path

from PIL import Image

# 打开时最多读多少像素，避免超大图直接把内存吃满（约 8 千万像素）
Image.MAX_IMAGE_PIXELS = 80_000_000

try:                      # Pillow 9.1+ 的写法
    LANCZOS = Image.Resampling.LANCZOS
except AttributeError:    # 老版本兜底
    LANCZOS = Image.LANCZOS


def open_rgba(path: str | Path) -> Image.Image:
    """打开任意常见格式，统一成 RGBA。多帧图（GIF/WEBP）取第一帧。"""
    im = Image.open(str(path))
    try:
        im.seek(0)
    except Exception:
        pass
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
    else:
        im = im.convert("RGBA")
    return im


def fit_contain(im: Image.Image, max_w: int, max_h: int) -> Image.Image:
    """等比缩放到能塞进 max_w×max_h 的框里（只缩不放）。"""
    w, h = im.size
    if w <= max_w and h <= max_h:
        return im
    sc = min(max_w / w, max_h / h)
    size = (max(1, round(w * sc)), max(1, round(h * sc)))
    return im.resize(size, LANCZOS)


def cover_to(im: Image.Image, w: int, h: int) -> Image.Image:
    """按「铺满」方式缩放到 w×h 并居中裁切（对应 canvas drawImage 的 cover 行为）。"""
    bw, bh = im.size
    s = max(w / bw, h / bh)
    dw, dh = round(bw * s), round(bh * s)
    if (dw, dh) != (bw, bh):
        im = im.resize((max(1, dw), max(1, dh)), LANCZOS)
    dw, dh = im.size
    left = (dw - w) // 2
    top = (dh - h) // 2
    return im.crop((left, top, left + w, top + h))


def over_background(im_rgba: Image.Image, rgb: tuple) -> Image.Image:
    """把 RGBA 图铺在纯色底上，返回 RGB。"""
    bg = Image.new("RGBA", im_rgba.size, (rgb[0], rgb[1], rgb[2], 255))
    return Image.alpha_composite(bg, im_rgba).convert("RGB")


def save_png(im: Image.Image, path: str | Path) -> None:
    im.save(str(path), "PNG", optimize=False)
