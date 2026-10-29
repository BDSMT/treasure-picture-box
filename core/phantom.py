# -*- coding: utf-8 -*-
"""幻影坦克 —— 一张 PNG，换个底色就换个画面。

原理（每个像素独立算）：

    输出 RGB = (P - d) / a        输出 alpha = a
    其中 a = 1 - d/255，d = 前景亮度 - 背景亮度×k（被夹到 [0, min(R,G,B)]）

铺在浅色底上：RGB×a + 255×(1-a) = (P-d) + d = P      → 精确还原前景
铺在深色底上：RGB×a             = P - d               → 看到被压暗的背景

所以「后面的图一定更暗」不是取舍，是公式决定的。
d 能不能取到想要的值，取决于前景在最暗通道上还剩多少余量 ——
余量不够，多出来的差额就变成黑底上的一层前景残影。
支撑度（support）就是量化这件事的。

算法与网页版 seed-toolbox.html 的 ptCompose() 逐项对齐，结果应当像素级一致。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
from PIL import Image

from .imageio import cover_to

_LUMA = np.array([0.299, 0.587, 0.114], dtype=np.float64)
BOOST_G = 0.45


@dataclass
class Stat:
    total: int = 0
    support: float = 1.0        # 支撑度 0..1
    clamp_ratio: float = 0.0    # 余量吃满的像素比例
    over_ratio: float = 0.0     # 背景比前景还亮的像素比例
    avg_ideal: float = 0.0      # 背景平均想要多少亮度
    avg_ghost: float = 0.0      # 黑底上实际平均亮度
    keep_area: float = 1.0      # 背景未被裁掉的比例
    keep_w: float = 1.0
    keep_h: float = 1.0
    boost: bool = False
    proj_support: Optional[float] = None   # 勾上前景提亮能达到的支撑度

    @property
    def level(self) -> str:
        s = self.support
        return "ok" if s >= 0.88 else ("warn" if s >= 0.62 else "bad")

    @property
    def percent(self) -> int:
        return 100 if self.support > 0.999 else min(99, int(round(self.support * 100)))


@dataclass
class ComposeResult:
    image: Image.Image
    stat: Stat
    width: int = 0
    height: int = 0


def _luma(rgb: np.ndarray) -> np.ndarray:
    return rgb @ _LUMA


def _core(c: np.ndarray, bl: np.ndarray):
    """给定（可能已提亮的）前景 RGB 与背景亮度，算出输出与统计量。"""
    pl = _luma(c)
    raw = pl - bl

    neg = np.maximum(-raw, 0.0)              # 背景比前景亮的损失
    d = np.maximum(raw, 0.0)

    mn = c.min(axis=2)                        # 每个像素最暗的通道
    over = d > mn
    clamp_loss = np.where(over, d - mn, 0.0)
    d = np.minimum(d, mn)

    ideal = float(bl.sum())
    loss = float(neg.sum() + clamp_loss.sum())
    ghost = float((pl - d).sum())
    clamp_n = int(over.sum())
    over_n = int((raw < 0).sum())
    total = max(1, int(raw.size))

    support = 1.0 - (loss / ideal) if ideal > 0 else 1.0
    support = min(1.0, max(0.0, support))

    alpha = 255.0 - d                         # a*255
    safe = np.maximum(alpha, 1e-9)
    out = np.where(alpha[..., None] > 0, (c - d[..., None]) * 255.0 / safe[..., None], 0.0)

    rgba = np.empty(c.shape[:2] + (4,), dtype=np.uint8)
    rgba[..., :3] = np.clip(np.round(out), 0, 255).astype(np.uint8)
    rgba[..., 3] = np.clip(np.round(alpha), 0, 255).astype(np.uint8)

    stats = dict(
        total=total,
        support=support,
        clamp_ratio=clamp_n / total,
        over_ratio=over_n / total,
        avg_ideal=ideal / total,
        avg_ghost=ghost / total,
    )
    return rgba, stats


def compose(
    fg: Image.Image,
    bg: Image.Image,
    bright: float = 0.55,
    boost: bool = False,
    max_side: int = 2600,
) -> ComposeResult:
    """合成幻影坦克图。fg/bg 都是 RGBA。输出尺寸跟随前景图。"""
    fw, fh = fg.size
    sc = min(1.0, max_side / max(fw, fh))
    w = max(1, int(round(fw * sc)))
    h = max(1, int(round(fh * sc)))

    fg_im = fg if (w, h) == (fw, fh) else fg.resize((w, h), Image.LANCZOS)

    # 背景按 cover 铺满；比例不同时两侧/上下会被裁掉 —— 这也是一种「放不下」
    bw, bh = bg.size
    s = max(w / bw, h / bh)
    keep_w = min(1.0, w / (bw * s))
    keep_h = min(1.0, h / (bh * s))

    bg_im = cover_to(bg, w, h)

    F = np.asarray(fg_im, dtype=np.float64)
    B = np.asarray(bg_im, dtype=np.float64)

    c = F[..., :3]
    if boost:
        c = c + (255.0 - c) * BOOST_G
    bl = _luma(B[..., :3]) * float(bright)

    rgba, st = _core(c, bl)

    proj = None
    if not boost:
        # 空跑一遍「如果开了提亮会怎样」，用来提示「勾上能提到多少」
        c2 = F[..., :3] + (255.0 - F[..., :3]) * BOOST_G
        _, st2 = _core(c2, bl)
        proj = st2["support"]

    stat = Stat(
        total=st["total"],
        support=st["support"],
        clamp_ratio=st["clamp_ratio"],
        over_ratio=st["over_ratio"],
        avg_ideal=st["avg_ideal"],
        avg_ghost=st["avg_ghost"],
        keep_area=keep_w * keep_h,
        keep_w=keep_w,
        keep_h=keep_h,
        boost=boost,
        proj_support=proj,
    )
    return ComposeResult(
        image=Image.fromarray(rgba, "RGBA"), stat=stat, width=w, height=h
    )


def advice(stat: Stat) -> list:
    """把统计量翻成人能看懂的话，对应 HTML 的 ptCheckRender()。

    每条：(level, title, quant, desc)  level ∈ ok/warn/bad
    """
    out = []

    if stat.avg_ideal < 5:
        out.append((
            "warn",
            "后面那张几乎全黑，黑底下看不出内容",
            "平均亮度 %d/255" % round(stat.avg_ideal),
            "深色背景下本来就没什么可显的，藏进去也等于白藏。"
            "换一张亮度正常的图当背景，才看得到效果。",
        ))
    else:
        lv = stat.level
        sp = stat.percent
        cp = int(round(stat.clamp_ratio * 100))
        res = max(0, int(round(stat.avg_ghost - stat.avg_ideal)))

        if lv == "ok":
            tail = (
                "；%d%% 的像素余量吃满，通常是画面最亮的地方，可能透出一点前景" % cp
                if cp >= 8 else ""
            )
            desc = "黑底下 %d%% 的背景亮度都到位了，残影极淡%s。可以直接生成。" % (sp, tail)
            title = "撑得住 —— 前景有余量，后面那张透得出来"
        elif lv == "warn":
            desc = ("有 %d%% 的像素灰度余量不够，背景想要的亮度没给足，"
                    "黑底上平均多出 %d 级亮度。还能看，但后面那张会发灰。" % (cp, res))
            title = "有点勉强 —— 黑底上会带一层前景残影"
        else:
            desc = ("有 %d%% 的像素没给够差值。黑底上你看到的绝大部分是"
                    "前景残影，不是后面那张图。换一张更亮、更浅、"
                    "饱和度更低的前景才是根本办法。" % cp)
            title = "撑不住 —— 前景太暗，后面那张显不出来"

        if not stat.boost and stat.proj_support is not None and stat.proj_support > stat.support + 0.03:
            desc += "勾上「前景提亮」可以提到 %d%%，代价是第一张整体变淡。" % round(
                stat.proj_support * 100
            )
        elif stat.boost and lv != "ok":
            desc += "前景提亮已经开了，还是不够 —— 只能换前景图。"

        out.append((lv, title, "支撑度 %d%%" % sp, desc))

    if stat.keep_area < 0.8:
        lost = int(round((1 - stat.keep_area) * 100))
        if stat.keep_w < stat.keep_h:
            side = "左右各裁掉 %d%%" % round((1 - stat.keep_w) * 50)
        else:
            side = "上下各裁掉 %d%%" % round((1 - stat.keep_h) * 50)
        out.append((
            "warn",
            "两张图比例不一样，背景被裁掉了 %d%%" % lost,
            "保留 %d%% 画面" % round(stat.keep_area * 100),
            "背景按「铺满」方式缩放，结果%s。先把两张裁成同一比例，能少丢一块画面。" % side,
        ))

    return out
