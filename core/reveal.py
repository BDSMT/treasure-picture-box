# -*- coding: utf-8 -*-
"""幻影提取 —— 把幻影坦克图还原成两张画面。

每个像素满足  RGB = (P - d)/a，alpha = a，于是两种底色的合成结果不同：

    浅色底（白）  RGB×a + 255×(1-a)   → 前景原图（精确）
    深色底（黑）  RGB×a               → 背景原图（被压暗过）

提取就是把这两步各做一遍。深色底那张的亮度在生成时就已经被 alpha 压掉了，
只能按倍数拉回来，不可能完全还原 —— 所以提亮做成可调的，
不给「完美还原」这种假承诺。

自动提亮的锚点：原图最亮部分不会超过 255，用接近最亮的 p99 去凑 248，
反推出生成时乘的那个系数。比按平均亮度猜稳得多，暗调背景不会被整体拉爆。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image

_LUMA = np.array([0.299, 0.587, 0.114], dtype=np.float64)


@dataclass
class Analysis:
    total: int = 0
    opaque: float = 0.0
    mid: float = 0.0
    zero: float = 0.0
    phantom: bool = False


def analyze(im_rgba: Image.Image) -> Analysis:
    a = np.asarray(im_rgba, dtype=np.uint8)[..., 3]
    total = max(1, a.size)
    opaque = float((a == 255).sum()) / total
    zero = float((a < 10).sum()) / total
    mid = 1.0 - opaque - zero
    return Analysis(
        total=total, opaque=opaque, mid=mid, zero=zero, phantom=mid > 0.02
    )


def auto_reveal(im_rgba: Image.Image) -> float:
    """按 p99 反推压暗倍数，夹到 0.8..5。"""
    arr = np.asarray(im_rgba, dtype=np.float64)
    alpha = arr[..., 3]
    mask = alpha >= 12
    if not mask.any():
        return 1.0

    lum = (arr[..., :3] @ _LUMA) * (alpha / 255.0)
    vals = np.clip(lum[mask], 0, 255).astype(np.int32)

    hist = np.bincount(vals, minlength=256).astype(np.float64)
    n = float(hist.sum())
    if n <= 0:
        return 1.0

    target = n * 0.99
    acc = 0.0
    p99 = 255
    for v in range(256):
        acc += hist[v]
        if acc >= target:
            p99 = v
            break

    k = 248.0 / p99 if p99 > 2 else 4.0
    return max(0.8, min(5.0, k))


def build_fg(im_rgba: Image.Image) -> Image.Image:
    """白底合成 —— 正常查看时看到的那张。"""
    arr = np.asarray(im_rgba, dtype=np.float64)
    a = arr[..., 3:4] / 255.0
    base = 255.0 * (1.0 - a)
    out = np.clip(np.round(arr[..., :3] * a + base), 0, 255).astype(np.uint8)
    return Image.fromarray(out, "RGB")


def build_bg(im_rgba: Image.Image, factor: float) -> Image.Image:
    """黑底合成 + 整体提亮 —— 藏着的那张。"""
    arr = np.asarray(im_rgba, dtype=np.float64)
    a = (arr[..., 3:4] / 255.0) * float(factor)
    out = np.clip(np.round(arr[..., :3] * a), 0, 255).astype(np.uint8)
    return Image.fromarray(out, "RGB")


def verdict(an: Analysis, im_rgba: Image.Image, factor: float) -> str:
    """一句人话结论。"""
    if not an.phantom:
        if an.opaque > 0.98:
            return ("看不出幻影结构 —— 这张图几乎完全不透明，"
                    "应该是普通图片。如果它确实是幻影坦克，试试原始的 PNG 版本。")
        if an.zero > 0.5:
            return ("大部分像素是全透明的，更像一张带透明通道的普通图，"
                    "不太像幻影坦克。")
        return "没检测到明显的半透明结构，可能不是本工具生成的那种幻影坦克图。"

    lines = []
    lines.append("半透明像素占 %d%%，这张图里确实藏了第二个画面。"
                 % round(an.mid * 100))
    lines.append("下面左边是白底正常查看的效果，右边是按 %.1f× 提亮后的隐藏画面。"
                 % factor)
    if factor >= 4.5:
        lines.append("提亮倍数已经接近上限，说明原图压得很暗，"
                     "右边的噪点会明显一些，这是原理决定的。")
    return "".join(lines)
