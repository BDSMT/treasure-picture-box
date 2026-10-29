# -*- coding: utf-8 -*-
"""配色 —— 与网页版 seed-toolbox.html 的 CSS 变量一一对应。"""

DARK = {
    "bg": "#171614",
    "surface": "#201E1C",
    "sunken": "#141312",
    "line": "#332F2B",
    "line2": "#48423C",
    "ink": "#F2EFEC",
    "ink2": "#BCB5AE",
    "ink3": "#8D867E",
    "solid": "#F2EFEC",
    "on_solid": "#171614",
    "ok_bg": "#12261B",
    "ok_line": "#2B5340",
    "ok_ink": "#7FD6A8",
    "warn_bg": "#2A2214",
    "warn_line": "#5C4820",
    "warn_ink": "#E8C46A",
    "bad_bg": "#2B1515",
    "bad_line": "#5E2A2A",
    "bad_ink": "#E99090",
}

LIGHT = {
    "bg": "#FAF9F7",
    "surface": "#FFFFFF",
    "sunken": "#F4F2EF",
    "line": "#E8E4DF",
    "line2": "#D6D0C9",
    "ink": "#1B1917",
    "ink2": "#57524C",
    "ink3": "#8D867E",
    "solid": "#1B1917",
    "on_solid": "#FAF9F7",
    "ok_bg": "#F1FAF4",
    "ok_line": "#C2E4CE",
    "ok_ink": "#15603C",
    "warn_bg": "#FDF6E7",
    "warn_line": "#EDD9AC",
    "warn_ink": "#7A4A05",
    "bad_bg": "#FCEFEF",
    "bad_line": "#E7C3C3",
    "bad_ink": "#8C2020",
}

FONTS = {
    "ui": ("Microsoft YaHei UI", 10),
    "ui_sm": ("Microsoft YaHei UI", 9),
    "ui_xs": ("Microsoft YaHei UI", 8),
    "title": ("Microsoft YaHei UI", 13, "bold"),
    "h1": ("Microsoft YaHei UI", 15, "bold"),
    "num": ("Consolas", 9),
}


def palette(theme: str) -> dict:
    return DARK if theme == "dark" else LIGHT


# ── 高 DPI 缩放 ────────────────────────────────────────
# 开了 DPI 感知之后，Tk 的点值字号会按 dpi/72 放大；像素常量必须同步放大，
# 否则字变大、留白不变，版面会挤在一起。
_SCALE = [1.0]


def setup_scale(v: float) -> None:
    _SCALE[0] = max(1.0, min(3.0, float(v)))


def scale() -> float:
    return _SCALE[0]


def s(px: float) -> int:
    """把设计稿上的像素值换算成当前屏幕的像素值。"""
    return int(round(px * _SCALE[0]))
