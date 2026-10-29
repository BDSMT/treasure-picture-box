# -*- coding: utf-8 -*-
"""可复用控件：拖放卡片、预览图块、提示条。"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional

from PIL import Image, ImageTk

from core.imageio import LANCZOS
from .theme import FONTS, s

try:
    from tkinterdnd2 import DND_FILES  # type: ignore

    _HAS_DND = True
except Exception:  # noqa: BLE001
    DND_FILES = None  # type: ignore
    _HAS_DND = False


def has_dnd() -> bool:
    return _HAS_DND


def fmt_size(n: float) -> str:
    if n is None or n < 0:
        return "—"
    if n < 1024:
        return "%d B" % n
    units = ["KB", "MB", "GB", "TB"]
    v = float(n)
    i = -1
    while v >= 1024 and i < len(units) - 1:
        v /= 1024.0
        i += 1
    return ("%.0f %s" if v >= 100 else "%.1f %s") % (v, units[i])


class DropCard(tk.Frame):
    """一块可以点击选文件、也能直接把文件拖进来的区域。"""

    def __init__(
        self,
        master,
        pal: dict,
        title: str,
        hint: str,
        sub: str,
        on_pick: Callable[[], None],
        on_path: Callable[[str], None],
        accept: Optional[Callable[[str], bool]] = None,
        thumb: Optional[Image.Image] = None,
        filled: Optional[dict] = None,
        height: int = None,
    ):
        super().__init__(
            master,
            bg=pal["surface"],
            highlightbackground=pal["line"],
            highlightthickness=1,
            height=s(132) if height is None else height,
        )
        self.pack_propagate(False)
        self.pal = pal
        self.on_pick = on_pick
        self.on_path = on_path
        self.accept = accept
        self._thumb_ref = None

        head = tk.Frame(self, bg=pal["surface"])
        head.pack(fill="x", padx=14, pady=(10, 0))
        tk.Label(
            head, text=title, bg=pal["surface"], fg=pal["ink2"],
            font=FONTS["ui_sm"], anchor="w",
        ).pack(side="left")

        body = tk.Frame(self, bg=pal["surface"])
        body.pack(fill="both", expand=True, padx=14, pady=(6, 12))
        self.body = body

        if filled:
            self._build_filled(body, filled, thumb)
        else:
            self._build_empty(body, hint, sub)

        self._bind_click(self)
        if _HAS_DND:
            try:
                self.drop_target_register(DND_FILES)  # type: ignore[attr-defined]
                self.dnd_bind("<<Drop>>", self._on_drop)  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001
                pass

    # -- 内部 ---------------------------------------------------------
    def _bind_click(self, w):
        w.bind("<Button-1>", lambda e: self.on_pick())
        for c in w.winfo_children():
            self._bind_click(c)

    def _on_drop(self, event):
        try:
            paths = self.tk.splitlist(event.data)
        except Exception:  # noqa: BLE001
            paths = [event.data]
        for p in paths:
            p = str(p).strip("{}")
            if self.accept and not self.accept(p):
                continue
            self.on_path(p)
            return

    def _build_empty(self, body, hint, sub):
        pal = self.pal
        box = tk.Frame(body, bg=pal["surface"])
        box.place(relx=0.5, rely=0.5, anchor="center")
        tk.Label(
            box, text="＋", bg=pal["surface"], fg=pal["ink3"],
            font=("Microsoft YaHei UI", 18),
        ).pack()
        tk.Label(
            box, text=hint, bg=pal["surface"], fg=pal["ink2"], font=FONTS["ui"],
        ).pack(pady=(2, 0))
        tk.Label(
            box, text=sub, bg=pal["surface"], fg=pal["ink3"], font=FONTS["ui_xs"],
        ).pack()

    def _build_filled(self, body, info, thumb):
        pal = self.pal
        row = tk.Frame(body, bg=pal["surface"])
        row.pack(fill="both", expand=True)

        if thumb is not None:
            tkimg = ImageTk.PhotoImage(thumb)
            self._thumb_ref = tkimg
            pic = tk.Label(row, image=tkimg, bg=pal["sunken"], bd=0)
            pic.pack(side="left", padx=(0, 12))

        meta = tk.Frame(row, bg=pal["surface"])
        meta.pack(side="left", fill="both", expand=True)
        tk.Label(
            meta, text=info.get("name", ""), bg=pal["surface"], fg=pal["ink"],
            font=FONTS["ui"], anchor="w", justify="left",
        ).pack(fill="x")
        tk.Label(
            meta, text=info.get("line", ""), bg=pal["surface"],
            fg=pal["warn_ink"] if info.get("warn") else pal["ink2"],
            font=FONTS["ui_sm"], anchor="w", justify="left",
        ).pack(fill="x", pady=(4, 0))
        if info.get("note"):
            tk.Label(
                meta, text=info["note"], bg=pal["surface"], fg=pal["ink3"],
                font=FONTS["ui_xs"], anchor="w", justify="left", wraplength=s(260),
            ).pack(fill="x", pady=(4, 0))
        tk.Label(
            meta, text="点这里可以换一个" if not info.get("readonly") else "",
            bg=pal["surface"], fg=pal["ink3"], font=FONTS["ui_xs"], anchor="w",
        ).pack(side="bottom", anchor="w")


class PreviewTile(tk.Frame):
    """带标题栏的预览图块。底图颜色固定（白底/黑底），不跟随主题。"""

    def __init__(self, master, pal: dict, cap_left: str, cap_right: str,
                 bg_rgb=(255, 255, 255), size=None):
        super().__init__(master, bg=pal["surface"], highlightbackground=pal["line"],
                         highlightthickness=1)
        self.pal = pal
        self._ref = None
        self._src = None

        bar = tk.Frame(self, bg=pal["surface"])
        bar.pack(fill="x", padx=12, pady=(8, 6))
        tk.Label(bar, text=cap_left, bg=pal["surface"], fg=pal["ink2"],
                 font=FONTS["ui_sm"]).pack(side="left")
        self.cap_right = tk.Label(bar, text=cap_right, bg=pal["surface"],
                                  fg=pal["ink3"], font=FONTS["ui_xs"])
        self.cap_right.pack(side="right")

        w, h = size or (s(400), s(240))
        self._dw, self._dh = w, h
        hexbg = "#%02X%02X%02X" % bg_rgb
        self.canvas = tk.Canvas(self, width=w, height=h, bg=hexbg,
                                highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        # 画布尺寸要等布局完成才知道，所以尺寸一变就按新尺寸重画
        self.canvas.bind("<Configure>", lambda e: self._redraw())

        self._empty = tk.Label(
            self.canvas, text="等待生成", bg=hexbg,
            fg="#8D867E", font=FONTS["ui_sm"],
        )
        self._empty.place(relx=0.5, rely=0.5, anchor="center")

    def set_image(self, im: Optional[Image.Image]):
        self._src = im.copy() if im is not None else None
        self._redraw()

    def _redraw(self):
        try:
            if not self.canvas.winfo_exists():
                return
        except Exception:  # noqa: BLE001
            return

        w = max(self.canvas.winfo_width(), self._dw)
        h = max(self.canvas.winfo_height(), self._dh)

        if self._src is None:
            self.canvas.delete("all")
            self._ref = None
            self._empty.place(relx=0.5, rely=0.5, anchor="center")
            return

        im = self._src.copy()
        im.thumbnail((max(40, w - 4), max(40, h - 4)), LANCZOS)
        self._ref = ImageTk.PhotoImage(im)
        self.canvas.delete("all")
        self.canvas.create_image(w // 2, h // 2, image=self._ref, anchor="center")
        self._empty.place_forget()

    def set_caption(self, right: str):
        self.cap_right.config(text=right)


def advice_row(master, pal: dict, level: str, title: str, quant: str, desc: str):
    """一条诊断结论。level ∈ ok / warn / bad"""
    fill = pal.get(level + "_bg", pal["sunken"])
    line = pal.get(level + "_line", pal["line"])
    ink = pal.get(level + "_ink", pal["ink"])

    box = tk.Frame(master, bg=fill, highlightbackground=line, highlightthickness=1)
    inner = tk.Frame(box, bg=fill)
    inner.pack(fill="x", padx=12, pady=9)

    dot = "✓" if level == "ok" else "!"
    tk.Label(inner, text=dot, bg=fill, fg=ink,
             font=("Microsoft YaHei UI", 11, "bold")).pack(side="left", padx=(0, 9))

    right = tk.Frame(inner, bg=fill)
    right.pack(side="left", fill="x", expand=True)

    head = tk.Frame(right, bg=fill)
    head.pack(fill="x")
    tk.Label(head, text=title, bg=fill, fg=ink, font=FONTS["ui_sm"],
             anchor="w").pack(side="left")
    if quant:
        tk.Label(head, text=quant, bg=fill, fg=ink, font=FONTS["ui_xs"],
                 anchor="e").pack(side="right")

    tk.Label(right, text=desc, bg=fill, fg=ink, font=FONTS["ui_xs"],
             anchor="w", justify="left", wraplength=s(700)).pack(fill="x", pady=(3, 0))
    return box


class ScrollFrame(tk.Frame):
    """竖向滚动容器（内容超高时才出现滚动条）。"""

    def __init__(self, master, pal: dict):
        super().__init__(master, bg=pal["bg"])
        self.pal = pal
        self.canvas = tk.Canvas(self, bg=pal["bg"], highlightthickness=0, bd=0)
        self.vs = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vs.set)
        self.canvas.pack(side="left", fill="both", expand=True)

        self.inner = tk.Frame(self.canvas, bg=pal["bg"])
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")

        self.inner.bind("<Configure>", self._on_inner)
        self.canvas.bind("<Configure>", self._on_canvas)
        self.canvas.bind_all("<MouseWheel>", self._on_wheel, add="+")

    def _on_inner(self, _e=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self._sync_bar()

    def _on_canvas(self, e):
        self.canvas.itemconfigure(self._win, width=e.width)
        self._sync_bar()

    def _sync_bar(self):
        """内容放得下就把滚动条收起来，别留一条没有用的竖线。"""
        try:
            need = self.inner.winfo_reqheight() > self.canvas.winfo_height() + 2
            shown = bool(self.vs.winfo_ismapped())
            if need and not shown:
                self.vs.pack(side="right", fill="y")
            elif not need and shown:
                self.vs.pack_forget()
        except Exception:  # noqa: BLE001
            pass

    def _on_wheel(self, e):
        try:
            if not self.winfo_ismapped():
                return
        except Exception:  # noqa: BLE001
            return
        self.canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")


class Slider(tk.Canvas):
    """自己画的滑块。

    不用 tk.Scale / ttk.Scale：深色主题下它们的手柄会用与背景同色的画刷，
    结果只剩一条线，用户根本看不出能拖。
    """

    def __init__(self, master, pal: dict, lo: float, hi: float, value: float,
                 step: float = 1.0, width: int = 200, height: int = 22,
                 on_change=None, fmt=None):
        super().__init__(master, width=s(width), height=s(height),
                         bg=pal["bg"], highlightthickness=0, bd=0, cursor="hand2")
        self.pal = pal
        self.lo, self.hi, self.step = lo, hi, step
        self.value = value
        self.on_change = on_change
        self.fmt = fmt
        # 注意：_w 是 Tkinter 内部存窗口路径名的属性，不能用，改名 _dw/_dh
        self._dw, self._dh = s(width), s(height)
        self.bind("<Button-1>", self._on_click)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<Configure>", lambda e: self.redraw())
        self.redraw()

    # -- 数值 ---------------------------------------------------------
    def get(self) -> float:
        return self.value

    def set(self, v: float, notify: bool = False):
        v = max(self.lo, min(self.hi, float(v)))
        if self.step > 0:
            v = round(round(v / self.step) * self.step, 4)
        self.value = v
        self.redraw()
        if notify and self.on_change:
            self.on_change(v)

    def _ratio(self) -> float:
        span = (self.hi - self.lo) or 1.0
        return (self.value - self.lo) / span

    # -- 交互 ---------------------------------------------------------
    def _from_x(self, x):
        pad = s(9)
        w = max(1, self.winfo_width() - 2 * pad)
        r = (x - pad) / w
        r = max(0.0, min(1.0, r))
        return self.lo + r * (self.hi - self.lo)

    def _on_click(self, e):
        self.set(self._from_x(e.x), notify=True)

    def _on_drag(self, e):
        self.set(self._from_x(e.x), notify=True)

    # -- 绘制 ---------------------------------------------------------
    def redraw(self):
        try:
            if not self.winfo_exists():
                return
        except Exception:  # noqa: BLE001
            return
        pal = self.pal
        self.delete("all")
        w = max(self.winfo_width(), self._dw)
        h = max(self.winfo_height(), self._dh)
        pad = s(9)
        cy = h // 2

        x0, x1 = pad, w - pad
        self.create_line(x0, cy, x1, cy, fill=pal["line2"], width=s(3),
                         capstyle="round")
        kx = x0 + (x1 - x0) * self._ratio()
        self.create_line(x0, cy, kx, cy, fill=pal["ink2"], width=s(3),
                         capstyle="round")
        r = s(6)
        self.create_oval(kx - r, cy - r, kx + r, cy + r,
                         fill=pal["ink"], outline=pal["bg"], width=s(2))


class Check(tk.Frame):
    """自己画的复选框，跟着主题走。"""

    def __init__(self, master, pal: dict, text: str, value: bool = False,
                 on_change=None):
        super().__init__(master, bg=pal["bg"], cursor="hand2")
        self.pal = pal
        self.value = bool(value)
        self.on_change = on_change

        self.box = tk.Canvas(self, width=s(15), height=s(15), bg=pal["bg"],
                             highlightthickness=0, bd=0, cursor="hand2")
        self.box.pack(side="left", pady=(s(2), 0))
        self.lab = tk.Label(self, text=text, bg=pal["bg"], fg=pal["ink2"],
                            font=FONTS["ui_sm"], cursor="hand2")
        self.lab.pack(side="left", padx=(s(7), 0))

        for w in (self, self.box, self.lab):
            w.bind("<Button-1>", self._toggle)
        self.redraw()

    def get(self) -> bool:
        return self.value

    def set(self, v: bool, notify: bool = False):
        self.value = bool(v)
        self.redraw()
        if notify and self.on_change:
            self.on_change(self.value)

    def _toggle(self, _e=None):
        self.set(not self.value, notify=True)

    def redraw(self):
        try:
            if not self.winfo_exists() or not self.box.winfo_exists():
                return
        except Exception:  # noqa: BLE001
            return
        pal = self.pal
        c = self.box
        c.delete("all")
        n = s(15)
        if self.value:
            c.create_rectangle(0, 0, n, n, fill=pal["ink"], outline=pal["ink"])
            c.create_line(s(3.5), s(8), s(6.5), s(11), s(11.5), s(4.5),
                          fill=pal["bg"], width=s(2), capstyle="round",
                          joinstyle="round")
        else:
            c.create_rectangle(0, 0, n, n, fill=pal["bg"], outline=pal["line2"])
        self.lab.config(fg=pal["ink"] if self.value else pal["ink2"])
