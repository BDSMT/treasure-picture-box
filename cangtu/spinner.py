# -*- coding: utf-8 -*-
"""转圈图标。

Tkinter 没有原生 spinner，用 Canvas 画 8 段弧，每 90ms 转一格。

为什么不用更快的刷新（16ms）：这个 Canvas 每帧要重建 8 个 arc 对象，
90ms 在视觉上已经够顺，而 CPU 占用几乎为零 —— 后台推理时不该抢主线程。

为什么所有 Tk 调用都包 try/except TclError：控件可能已经被 destroy
（切 tab 会重建整个界面），对一个已销毁的控件调 place 会抛异常，
而那里恰好是「停止转圈」的收尾路径，不能因为控件没了就崩。
"""
from __future__ import annotations

import tkinter as tk


def _hex_to_rgb(h: str) -> tuple:
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def blend(fg: str, bg: str, t: float) -> str:
    """把 fg 按比例 t 混到 bg 上。t=1 是 fg 原色，t=0 是 bg。"""
    fr, fgg, fb = _hex_to_rgb(fg)
    br, bgg, bb = _hex_to_rgb(bg)
    t = max(0.0, min(1.0, t))
    return "#%02X%02X%02X" % (
        int(br + (fr - br) * t),
        int(bgg + (fgg - bgg) * t),
        int(bb + (fb - bb) * t),
    )


def readable_on(bg: str) -> str:
    """给指定背景挑一个看得清的转圈颜色。

    预览块的画布底色是固定的（白底/黑底/棋盘格），不跟主题走，
    所以转圈颜色必须自己判断明暗，否则白底上画白圈等于没画。
    """
    r, g, b = _hex_to_rgb(bg)
    luma = 0.299 * r + 0.587 * g + 0.114 * b
    return "#5F5E5A" if luma > 140 else "#D3D1C7"


class Spinner(tk.Canvas):
    """转圈。

    用法：
        sp = Spinner(parent, size=22, color=pal["ink3"], bg=pal["surface"])
        sp.start()      # 显示在父控件中央并开始转
        sp.stop()       # 停止并从界面上移除

    start / stop 都是幂等的，重复调用不会叠加动画。
    """

    SEGMENTS = 8
    INTERVAL = 90          # ms

    def __init__(self, master, size: int = 22, color: str = "#8D867E",
                 bg: str = "#FFFFFF", on_show=None, on_hide=None, **kw):
        super().__init__(master, width=size, height=size, bg=bg,
                         highlightthickness=0, bd=0, **kw)
        self._size = int(size)
        self._color = color
        self._bg = bg
        self._ang = 0.0
        self._job = None
        self._items = []
        # 可选钩子：用来暂时清掉底下的「等待生成」占位文字，
        # 否则转圈会和那四个字叠在一起。
        self._on_show = on_show
        self._on_hide = on_hide
        self._paint()

    # ── 内部 ──
    def _paint(self) -> None:
        try:
            for it in self._items:
                self.delete(it)
        except tk.TclError:
            return
        self._items.clear()

        n, size = self.SEGMENTS, self._size
        pad = max(2, size // 8)
        box = (pad, pad, size - pad, size - pad)
        step = 360.0 / n
        width = max(2, size // 11)

        for i in range(n):
            # 头部最实、尾部最淡，形成拖尾
            shade = 0.12 + 0.88 * (1.0 - i / n)
            try:
                self._items.append(self.create_arc(
                    *box,
                    start=self._ang + i * step,
                    extent=step - 8,
                    style="arc",
                    outline=blend(self._color, self._bg, shade),
                    width=width,
                ))
            except tk.TclError:
                return

    def _tick(self) -> None:
        self._ang = (self._ang + 360.0 / self.SEGMENTS) % 360.0
        self._paint()
        try:
            self._job = self.after(self.INTERVAL, self._tick)
        except tk.TclError:
            self._job = None

    # ── 对外 ──
    def start(self, relx: float = 0.5, rely: float = 0.5) -> None:
        if self._job is not None:
            return
        try:
            self.place(relx=relx, rely=rely, anchor="center")
        except tk.TclError:
            return
        # 这里刻意不调 lift()：Canvas 的 lift 会被 Tk 解释成「提升画布内的
        # 图形元素」（raise tagOrId），参数对不上直接抛 TclError，把后面的
        # _tick() 一起断掉 —— 表现就是转圈显示出来但永远不转、也不消失。
        # place 出来的控件本来就叠在最后创建的位置，不需要再提升。
        if self._on_show is not None:
            try:
                self._on_show()
            except Exception:      # noqa: BLE001
                pass
        self._tick()

    def stop(self) -> None:
        """停止并移除。这就是需求里的「处理结束后自动移除」。"""
        if self._job is not None:
            try:
                self.after_cancel(self._job)
            except tk.TclError:
                pass
            self._job = None
        try:
            self.place_forget()
        except tk.TclError:
            pass
        if self._on_hide is not None:
            try:
                self._on_hide()
            except Exception:      # noqa: BLE001
                pass

    def running(self) -> bool:
        return self._job is not None

    def recolor(self, color: str, bg: str) -> None:
        """主题切换时更新配色。"""
        self._color = color
        self._bg = bg
        try:
            self.configure(bg=bg)
            self._paint()
        except tk.TclError:
            pass
