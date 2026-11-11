# -*- coding: utf-8 -*-
"""藏图盒 —— 界面。

五个模块：图种（字节追加）、图种解包（把追加的东西拆出来）、
幻影坦克（双画面合成）、幻影提取（还原）、抠图（主体分离 + 三视图）。
预览全程在本地完成，不经过任何浏览器或网络。
"""
from __future__ import annotations

import os
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

from PIL import Image

from core import paths as P
from core import matting, phantom, reveal, seed, unpack
from core.seed import payload_kind
from core.imageio import LANCZOS, fit_contain, open_rgba, over_background, save_png
from core.sniff import is_image_name, sniff
from cangtu.spinner import Spinner, readable_on
from cangtu.tasks import TaskRunner
from ui.theme import FONTS, palette, s, scale, setup_scale
from ui.widgets import (Check, DropCard, PreviewTile, ScrollFrame, Slider,
                        advice_row, fmt_size)

try:
    from tkinterdnd2 import TkinterDnD

    _Base = TkinterDnD.Tk
    _DND = True
except Exception:  # noqa: BLE001
    _Base = tk.Tk
    _DND = False

IMAGE_TYPES = [
    ("图片", "*.png *.jpg *.jpeg *.gif *.webp *.bmp *.tif *.tiff *.avif"),
    ("所有文件", "*.*"),
]

PREVIEW_SIDE = 760   # 预览合成的最长边
CUT_PREVIEW_SIDE = 1400   # 抠图预览的输入边长，导出时会按原尺寸重算


def _setup_dpi():
    """让高分屏下文字不发虚。必须在创建 Tk 之前调用。"""
    if os.name != "nt":
        return
    try:
        from ctypes import windll

        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:  # noqa: BLE001
        pass


def _system_dpi() -> int:
    if os.name != "nt":
        return 96
    try:
        from ctypes import windll

        v = windll.user32.GetDpiForSystem()
        return int(v) if v else 96
    except Exception:  # noqa: BLE001
        return 96


def _stem(p: str) -> str:
    return Path(p).stem


def _ext(p: str) -> str:
    return Path(p).suffix


def _short(name: str, limit: int = 54) -> str:
    """名字太长就掐中间，保住结尾的扩展名 —— 一行放不下会被 Tk 直接切掉。"""
    if len(name) <= limit:
        return name
    keep_head = limit - 16
    return name[:keep_head] + "…" + name[-(limit - keep_head - 1):]


def _thumb(path: str, box=(64, 64)):
    try:
        im = open_rgba(path)
        im.thumbnail(box, LANCZOS)
        return im
    except Exception:  # noqa: BLE001
        return None


def _dims(path: str) -> str:
    try:
        with Image.open(path) as im:
            return "%d × %d" % im.size
    except Exception:  # noqa: BLE001
        return "—"


class App(_Base):
    def __init__(self):
        _setup_dpi()
        super().__init__()

        dpi = _system_dpi()
        setup_scale(dpi / 96.0)
        try:
            self.tk.call("tk", "scaling", dpi / 72.0)
        except Exception:  # noqa: BLE001
            pass

        self.cfg = P.load_config()
        self.theme = self.cfg.get("theme", "dark")
        self.pal = palette(self.theme)

        self.title("藏图盒")

        w, h = s(1140), s(800)
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w = min(w, sw - s(40))
        h = min(h, sh - s(80))
        self.geometry("%dx%d" % (w, h))
        self.minsize(min(s(980), w), min(s(680), h))

        # ── 状态（切主题重建界面时不会丢）──────────────────
        self.tab = "seed"
        self.st_seed = {"cover": None, "pay": None, "result": None, "extra": 0,
                        "kind": "", "end": 0, "pay_kind": ""}
        self.st_un = {"path": None, "result": None, "error": ""}
        self.st_pt = {"fg": None, "bg": None, "result": None}
        self.st_ex = {"path": None, "factor": float(self.cfg.get("reveal_factor", 2.0)),
                      "auto": bool(self.cfg.get("reveal_auto", True))}
        self.st_cu = {"path": None, "backdrop": "auto"}

        # 异步执行器：所有耗时处理都走它，期间的转圈也由它管
        self.tasks = TaskRunner(self)

        self._refs = []
        self.build()

    # ══════════════════════════════════════════════════════
    #  骨架
    # ══════════════════════════════════════════════════════
    def build(self):
        pal = palette(self.theme)
        self.pal = pal
        # 界面要整个重建：在途任务的结果必须作废，否则任务跑完回来
        # 会往新控件上写旧数据；旧 spinner 也马上会被 destroy，引用一起丢掉。
        self.tasks.invalidate()
        self.tasks.detach_spinners()
        for w in self.winfo_children():
            w.destroy()

        self.configure(bg=pal["bg"])

        head = tk.Frame(self, bg=pal["bg"])
        head.pack(fill="x", padx=s(24), pady=(s(18), s(8)))

        mark = tk.Label(head, text="藏", bg=pal["solid"], fg=pal["on_solid"],
                        font=("Microsoft YaHei UI", 14, "bold"), width=2, height=1)
        mark.pack(side="left")

        tt = tk.Frame(head, bg=pal["bg"])
        tt.pack(side="left", padx=12)
        tk.Label(tt, text="藏图盒", bg=pal["bg"], fg=pal["ink"],
                 font=FONTS["h1"], anchor="w").pack(anchor="w")
        tk.Label(tt, text="CangTu Box · 纯本地运行", bg=pal["bg"], fg=pal["ink3"],
                 font=FONTS["ui_xs"], anchor="w").pack(anchor="w")

        self.theme_btn = tk.Label(
            head, text="☀ 浅色" if self.theme == "dark" else "☾ 深色",
            bg=pal["surface"], fg=pal["ink2"], font=FONTS["ui_sm"],
            padx=s(12), pady=s(6), cursor="hand2",
            highlightbackground=pal["line"], highlightthickness=1,
        )
        self.theme_btn.pack(side="right")
        self.theme_btn.bind("<Button-1>", lambda e: self.toggle_theme())

        body = tk.Frame(self, bg=pal["bg"])
        body.pack(fill="both", expand=True, padx=s(24), pady=(s(6), s(20)))

        rail = tk.Frame(body, bg=pal["bg"], width=s(170))
        rail.pack(side="left", fill="y")
        rail.pack_propagate(False)

        for key, label, sub in (
            ("seed", "图种", "图片 + 隐藏文件"),
            ("unpack", "图种解包", "直接拆出种子"),
            ("phantom", "幻影坦克", "一张图两个画面"),
            ("reveal", "幻影提取", "把藏着的画面还原"),
            ("cut", "抠图", "主体分离 · 三视图"),
        ):
            self._rail_btn(rail, key, label, sub)

        tk.Frame(body, bg=pal["line"], width=1).pack(side="left", fill="y", padx=(0, s(18)))

        self.stage = tk.Frame(body, bg=pal["bg"])
        self.stage.pack(side="left", fill="both", expand=True)

        if self.tab == "seed":
            self.build_seed()
        elif self.tab == "unpack":
            self.build_unpack()
        elif self.tab == "phantom":
            self.build_phantom()
        elif self.tab == "reveal":
            self.build_reveal()
        else:
            self.build_cut()

    def _rail_btn(self, parent, key, label, sub):
        pal = self.pal
        active = self.tab == key
        bg = pal["surface"] if active else pal["bg"]
        box = tk.Frame(parent, bg=bg,
                       highlightbackground=pal["line"] if active else pal["bg"],
                       highlightthickness=1)
        box.pack(fill="x", pady=(0, 6))
        inner = tk.Frame(box, bg=bg)
        inner.pack(fill="x", padx=s(12), pady=s(9))
        tk.Label(inner, text=label, bg=bg, fg=pal["ink"] if active else pal["ink2"],
                 font=FONTS["ui"], anchor="w").pack(anchor="w")
        tk.Label(inner, text=sub, bg=bg, fg=pal["ink3"],
                 font=FONTS["ui_xs"], anchor="w").pack(anchor="w")

        def go(_e=None):
            if self.tab != key:
                self.tab = key
                self.build()

        for w in (box, inner, *inner.winfo_children()):
            w.bind("<Button-1>", go)
            try:
                w.configure(cursor="hand2")
            except Exception:  # noqa: BLE001
                pass

    def toggle_theme(self):
        self.theme = "light" if self.theme == "dark" else "dark"
        self.cfg["theme"] = self.theme
        P.save_config(self.cfg)
        self.build()

    # ══════════════════════════════════════════════════════
    #  通用小件
    # ══════════════════════════════════════════════════════
    def _btn(self, parent, text, cmd, primary=False):
        pal = self.pal
        bg = pal["solid"] if primary else pal["surface"]
        fg = pal["on_solid"] if primary else pal["ink2"]
        b = tk.Label(parent, text=text, bg=bg, fg=fg, font=FONTS["ui_sm"],
                     padx=s(16), pady=s(8), cursor="hand2",
                     highlightbackground=pal["line"], highlightthickness=0 if primary else 1)
        b.bind("<Button-1>", lambda e: cmd())
        b.bind("<Enter>", lambda e: b.configure(bg=pal["line2"] if not primary else pal["ink2"]))
        b.bind("<Leave>", lambda e: b.configure(bg=bg))
        return b

    def _hint(self, parent, text, pady=(0, 8)):
        return tk.Label(parent, text=text, bg=self.pal["bg"], fg=self.pal["ink3"],
                        font=FONTS["ui_xs"], anchor="w", justify="left")

    def _pick(self, cb, images_only=False, title="选择文件"):
        pal = self.pal
        initial = self.cfg.get("last_dir") or str(Path.home())
        path = filedialog.askopenfilename(
            parent=self, title=title, initialdir=initial,
            filetypes=IMAGE_TYPES if images_only else [("所有文件", "*.*")] + IMAGE_TYPES,
        )
        if path:
            self.cfg["last_dir"] = str(Path(path).parent)
            P.save_config(self.cfg)
            cb(path)

    def _ask_save(self, default_name: str, ext: str):
        initial = self.cfg.get("last_dir") or str(P.ROOT)
        types = [("PNG 图片", "*.png")] if ext == ".png" else [
            ("图片", "*" + ext), ("所有文件", "*.*")
        ]
        path = filedialog.asksaveasfilename(
            parent=self, title="保存为", initialdir=initial,
            initialfile=default_name, defaultextension=ext, filetypes=types,
        )
        if path:
            self.cfg["last_dir"] = str(Path(path).parent)
            P.save_config(self.cfg)
        return path

    def toast(self, text, err=False):
        pal = self.pal
        bg = pal["bad_line"] if err else pal["solid"]
        fg = "#FFF1F1" if err else pal["on_solid"]
        lab = tk.Label(self, text=text, bg=bg, fg=fg, font=FONTS["ui_sm"],
                       padx=16, pady=9)
        lab.place(relx=0.5, rely=1.0, y=-26, anchor="s")
        self.after(3200, lambda: (lab.destroy() if lab.winfo_exists() else None))

    def _spin(self, key, host):
        """在控件中央挂一个转圈，并交给 tasks 自动起停。

        host 可以是 PreviewTile（用它内部的 canvas，转圈正好压在图上），
        也可以是任意 Frame（用它的 body 或它自己）。

        颜色按宿主底色自己挑：预览块的底是固定的白/黑/棋盘格，不跟主题走，
        白底上画白圈等于没画。
        """
        target = getattr(host, "canvas", None) or getattr(host, "body", None) or host
        try:
            bg = str(target.cget("bg"))
        except Exception:      # noqa: BLE001
            bg = self.pal["surface"]

        # PreviewTile 里有一行「等待生成」占位文字，转圈正好压在它上面。
        # 转圈期间先把文字清空，结束再恢复 —— 有图时 _redraw 会自己再隐藏它。
        empty = getattr(host, "_empty", None)
        blank = None
        if empty is not None:
            try:
                blank = empty.cget("text")
            except Exception:      # noqa: BLE001
                empty = None

        def _show():
            if empty is not None:
                try:
                    empty.configure(text="")
                except Exception:      # noqa: BLE001
                    pass

        def _hide():
            if empty is not None:
                try:
                    empty.configure(text=blank)
                except Exception:      # noqa: BLE001
                    pass

        sp = Spinner(target, size=s(30), color=readable_on(bg), bg=bg,
                     on_show=_show, on_hide=_hide)
        self.tasks.attach_spinner(key, sp)
        return sp

    def _alive(self, key, widget: str) -> bool:
        """异步结果回来时，确认界面还停在那个模块、控件也还在。

        用户可能已经切走了，这时结果直接丢掉，不要往别的模块上写。
        """
        return self.tab == key and hasattr(self, widget)

    # ══════════════════════════════════════════════════════
    #  模块一：图种
    # ══════════════════════════════════════════════════════
    def build_seed(self):
        pal = self.pal
        wrap = ScrollFrame(self.stage, pal)
        wrap.pack(fill="both", expand=True)
        root = wrap.inner

        tk.Label(root, text="图种", bg=pal["bg"], fg=pal["ink"],
                 font=FONTS["title"], anchor="w").pack(anchor="w")
        tk.Label(
            root,
            text="图片原始字节在前，要藏的文件原封不动接在后面。"
                 "看图软件遇到图片结束标记就停下，把后缀改成 .zip 就能解压出内容。",
            bg=pal["bg"], fg=pal["ink3"], font=FONTS["ui_xs"],
            anchor="w", justify="left", wraplength=s(780),
        ).pack(anchor="w", pady=(4, 14))

        row = tk.Frame(root, bg=pal["bg"])
        row.pack(fill="x")
        row.columnconfigure(0, weight=1, uniform="c")
        row.columnconfigure(1, weight=1, uniform="c")

        self.seed_cover_card = self._seed_cover_card(row)
        self.seed_cover_card.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

        self.seed_pay_card = self._seed_pay_card(row)
        self.seed_pay_card.grid(row=0, column=1, sticky="nsew", padx=(10, 0))

        self.seed_info = tk.Frame(root, bg=pal["bg"])
        self.seed_info.pack(fill="x", pady=(12, 0))
        self._seed_render_info()

        bar = tk.Frame(root, bg=pal["bg"])
        bar.pack(fill="x", pady=(14, 0))
        self._btn(bar, "生成图种", self.seed_do_pack, primary=True).pack(side="left")
        self._btn(bar, "清空", self.seed_reset).pack(side="left", padx=8)

        self.seed_preview = PreviewTile(
            root, pal, "封面预览", "生成后图片看起来和原图一模一样", bg_rgb=(255, 255, 255),
            size=(s(560), s(190)),
        )
        self.seed_preview.pack(fill="x", pady=(16, 0))
        self._spin("seed", self.seed_preview)
        self._seed_refresh_preview()

        tk.Label(
            root,
            text="提示：图种能不能用，取决于平台会不会重新压缩图片。"
                 "原图上传、不转存，才能保住后面那段数据。",
            bg=pal["bg"], fg=pal["ink3"], font=FONTS["ui_xs"],
            anchor="w", justify="left", wraplength=s(780),
        ).pack(anchor="w", pady=(12, 6))

    def _seed_cover_card(self, parent):
        pal = self.pal
        p = self.st_seed["cover"]
        filled = None
        thumb = None
        if p:
            filled = {
                "name": Path(p).name,
                "line": "%s · %s · %s" % (self.st_seed["kind"] or "—", _dims(p),
                                          fmt_size(os.path.getsize(p))),
                "note": "图片主体结束于第 %s 字节" % format(self.st_seed["end"], ","),
            }
            thumb = _thumb(p, (72, 72))
        return DropCard(
            parent, pal, "封面图（别人看到的那张）",
            "拖入图片，或点击选择", "JPG / PNG / GIF / WEBP / BMP",
            on_pick=lambda: self._pick(self.seed_set_cover, True, "选择封面图"),
            on_path=self.seed_set_cover,
            accept=is_image_name,
            thumb=thumb, filled=filled,
        )

    def _seed_pay_card(self, parent):
        pal = self.pal
        p = self.st_seed["pay"]
        kind = self.st_seed.get("pay_kind", "")
        filled = None
        if p:
            is_zip = kind == "ZIP"
            filled = {
                "name": Path(p).name,
                "line": "%s · %s · %s" % (
                    fmt_size(os.path.getsize(p)), kind or "未知",
                    "改后缀成 .zip 就能解压" if is_zip else "只能用本工具拆"),
                "warn": not is_zip,
                "note": "" if is_zip else
                        "%s的头部必须从第 0 字节读，接在图片后面就认不出来了，"
                        "先压成 .zip 再当载荷。"
                        % (("%s 这种格式" % kind) if kind not in ("", "未知") else "这类文件"),
            }
        return DropCard(
            parent, pal, "要藏的文件",
            "拖入文件，或点击选择", "建议压成 .zip —— 只有 zip 接在图片后面还能解压",
            on_pick=lambda: self._pick(self.seed_set_pay, False, "选择要藏的文件"),
            on_path=self.seed_set_pay,
            filled=filled,
        )

    def seed_set_cover(self, path):
        try:
            raw = Path(path).read_bytes()
            info = sniff(raw)
            if not info.kind:
                self.toast("认不出这张图的格式，试试 JPG 或 PNG。", True)
                return
            if not info.end_offset:
                self.toast("这张图的结构不完整，结尾找不到。换一张试试。", True)
                return
            self.st_seed.update(cover=path, kind=info.kind, end=info.end_offset,
                                extra=max(0, len(raw) - info.end_offset), result=None)
            self.build()
        except Exception as exc:  # noqa: BLE001
            self.toast("读取这张图失败：%s" % exc, True)

    def seed_set_pay(self, path):
        try:
            if os.path.getsize(path) == 0:
                self.toast("这个文件是空的。", True)
                return
            with open(path, "rb") as f:
                head = f.read(64)
            kind = payload_kind(head)
            self.st_seed.update(pay=path, pay_kind=kind, result=None)
            self.build()
        except Exception as exc:  # noqa: BLE001
            self.toast("读取文件失败：%s" % exc, True)

    def seed_reset(self):
        self.st_seed.update(cover=None, pay=None, result=None, extra=0,
                            kind="", end=0, pay_kind="")
        self.build()

    def _seed_render_info(self):
        pal = self.pal
        for w in self.seed_info.winfo_children():
            w.destroy()

        st = self.st_seed
        if not st["cover"]:
            return

        if st["extra"] > 0:
            tail = Path(st["cover"]).read_bytes()[st["end"]:]
            from core.sniff import guess_type

            hit = guess_type(tail)
            label = hit[0] if hit else "未知"
            box = tk.Frame(self.seed_info, bg=pal["warn_bg"],
                           highlightbackground=pal["warn_line"], highlightthickness=1)
            box.pack(fill="x")
            inner = tk.Frame(box, bg=pal["warn_bg"])
            inner.pack(fill="x", padx=s(12), pady=s(9))
            tk.Label(
                inner,
                text="这张图本身就是个图种 —— 结尾之后还挂着 %s 的数据（看起来是 %s）。"
                     "直接再打包会叠在一起，建议先拆出来。" % (fmt_size(st["extra"]), label),
                bg=pal["warn_bg"], fg=pal["warn_ink"], font=FONTS["ui_xs"],
                anchor="w", justify="left", wraplength=s(680),
            ).pack(side="left")
            btn = tk.Label(inner, text="拆出来", bg=pal["warn_bg"], fg=pal["warn_ink"],
                           font=FONTS["ui_xs"], cursor="hand2",
                           highlightbackground=pal["warn_line"], highlightthickness=1,
                           padx=s(10), pady=s(4))
            btn.pack(side="right")
            btn.bind("<Button-1>", lambda e: self.seed_split())

        if st["result"]:
            r = st["result"]
            total = len(r.data)
            tk.Label(
                self.seed_info,
                text="已生成：%s（图片 %s + 载荷 %s）"
                     % (fmt_size(total), fmt_size(r.cover_len),
                        fmt_size(r.payload_len)),
                bg=pal["bg"], fg=pal["ok_ink"], font=FONTS["ui_xs"], anchor="w",
            ).pack(anchor="w", pady=(8, 0))

            if r.patched:
                tk.Label(
                    self.seed_info,
                    text="压缩包偏移已修正 —— 改成 .zip 之后，7-Zip、Bandizip、"
                         "资源管理器都能直接打开。",
                    bg=pal["bg"], fg=pal["ink3"], font=FONTS["ui_xs"],
                    anchor="w", justify="left", wraplength=s(680),
                ).pack(anchor="w", pady=(3, 0))

            if r.warning:
                box = tk.Frame(self.seed_info, bg=pal["warn_bg"],
                               highlightbackground=pal["warn_line"], highlightthickness=1)
                box.pack(fill="x", pady=(8, 0))
                tk.Label(
                    box, text=r.warning,
                    bg=pal["warn_bg"], fg=pal["warn_ink"], font=FONTS["ui_xs"],
                    anchor="w", justify="left", wraplength=s(660),
                    padx=s(12), pady=s(9),
                ).pack(fill="x")

    def _seed_refresh_preview(self):
        p = self.st_seed["cover"]
        if not p:
            self.seed_preview.set_image(None)
            return
        self.tasks.submit(
            "seed",
            fn=lambda: open_rgba(p).convert("RGB"),
            on_ok=self._seed_show,
            on_err=lambda exc: self._seed_show(None),
        )

    def _seed_show(self, im):
        if not self._alive("seed", "seed_preview"):
            return
        self.seed_preview.set_image(im)

    def seed_do_pack(self):
        st = self.st_seed
        if not (st["cover"] and st["pay"]):
            self.toast("两张都还没选全。", True)
            return
        cover, pay = st["cover"], st["pay"]
        self.tasks.submit(
            "seed",
            fn=lambda: seed.pack(cover, pay),
            on_ok=self._seed_packed,
            on_err=lambda exc: self.toast(str(exc), True),
        )

    def _seed_packed(self, res):
        st = self.st_seed
        ext = _ext(st["cover"]) or ("." + (st["kind"] or "jpg").lower())
        default = "%s_seed%s" % (_stem(st["cover"]), ext)
        out = self._ask_save(default, ext)
        if not out:
            return
        try:
            seed.write(res, out)
        except Exception as exc:  # noqa: BLE001
            self.toast("写文件失败：%s" % exc, True)
            return

        st["result"] = res
        self._seed_render_info()
        self.toast("已生成 %s，改后缀就能解压出里面的东西" % fmt_size(len(res.data)))

    def seed_split(self):
        st = self.st_seed
        if not st["cover"]:
            return
        try:
            sp = seed.split(st["cover"])
        except Exception as exc:  # noqa: BLE001
            self.toast(str(exc), True)
            return
        default = "%s_附加数据%s" % (_stem(st["cover"]), sp.tail_ext)
        out = self._ask_save(default, sp.tail_ext)
        if not out:
            return
        Path(out).write_bytes(sp.tail)
        self.toast("已拆出 %s（%s）" % (fmt_size(len(sp.tail)), sp.tail_type))

    # ══════════════════════════════════════════════════════
    #  模块二：图种解包
    # ══════════════════════════════════════════════════════
    def build_unpack(self):
        pal = self.pal
        wrap = ScrollFrame(self.stage, pal)
        wrap.pack(fill="both", expand=True)
        root = wrap.inner

        tk.Label(root, text="图种解包", bg=pal["bg"], fg=pal["ink"],
                 font=FONTS["title"], anchor="w").pack(anchor="w")
        tk.Label(
            root,
            text="拖入一张图种，直接拿到里面的文件 —— 压缩包在这里就地解开，"
                 "不用先改后缀再去解压。种子会单独列出来，并算出 infohash 供核对。",
            bg=pal["bg"], fg=pal["ink3"], font=FONTS["ui_xs"],
            anchor="w", justify="left", wraplength=s(780),
        ).pack(anchor="w", pady=(4, 14))

        st = self.st_un
        p = st["path"]
        res = st["result"]
        filled = None
        thumb = None
        if p:
            try:
                size = fmt_size(os.path.getsize(p))
            except OSError:
                size = "—"
            if res is not None and res.has_payload:
                line = "%s · 附加 %s · %s" % (
                    size, fmt_size(len(res.tail)), res.payload_type or "未知")
                note = "图片主体结束于第 %s 字节" % format(res.image_end, ",")
            elif res is not None:
                line = size
                note = "末尾没有附加数据"
            else:
                line = size
                note = ""
            filled = {"name": Path(p).name, "line": line, "note": note}
            if is_image_name(p):
                thumb = _thumb(p, (72, 72))

        self.un_card = DropCard(
            root, pal, "图种文件", "拖入图种，或点击选择",
            "改了后缀的图片也照样认；直接拖 .torrent / .zip 也行",
            on_pick=lambda: self._pick(self.un_set, False, "选择图种文件"),
            on_path=self.un_set,
            thumb=thumb, filled=filled,
        )
        self.un_card.pack(fill="x")
        self._spin("unpack", self.un_card)

        self.un_advice = tk.Frame(root, bg=pal["bg"])
        self.un_advice.pack(fill="x", pady=(12, 0))

        bar = tk.Frame(root, bg=pal["bg"])
        bar.pack(fill="x", pady=(12, 0))
        self.un_btn_tor = self._btn(bar, "导出种子", self.un_save_torrent, primary=True)
        self.un_btn_all = self._btn(bar, "全部导出", self.un_save_all)
        self.un_btn_raw = self._btn(bar, "附加数据另存", self.un_save_tail)
        self.un_bar = bar

        self.un_count = tk.Label(bar, text="", bg=pal["bg"], fg=pal["ink3"],
                                 font=FONTS["ui_xs"])
        self.un_count.pack(side="right")

        self.un_list = tk.Frame(root, bg=pal["bg"])
        self.un_list.pack(fill="x", pady=(14, 0))

        tk.Label(
            root,
            text="解包只读不写：不会改动你拖进来的那张图。"
                 "种子里的 infohash 是 info 段的 SHA-1，拿去任何站点搜一下就能对上。",
            bg=pal["bg"], fg=pal["ink3"], font=FONTS["ui_xs"],
            anchor="w", justify="left", wraplength=s(780),
        ).pack(anchor="w", pady=(14, 6))

        self._un_render()

    # -- 状态 → 界面 --------------------------------------------------
    def un_set(self, path):
        self.tasks.submit(
            "unpack",
            fn=lambda: unpack.unpack(path),
            on_ok=lambda res: self._un_done(path, res),
            on_err=lambda exc: self._un_fail(path, exc),
        )

    def _un_done(self, path, res):
        self.st_un.update(path=path, result=res, error="")
        self.build()

        if not res.has_payload:
            self.toast("这张图后面没有附加数据", True)
        elif res.entries:
            self.toast("已拆出 %d 个文件" % len(res.entries))
        elif res.warning:
            self.toast(res.warning, True)

    def _un_fail(self, path, exc):
        self.st_un.update(path=path, result=None, error=str(exc))
        self.build()
        self.toast(str(exc), True)

    def _un_sync_buttons(self, res):
        """没东西可导出的按钮就别摆着 —— 点了只会提示「没有可导出的文件」。"""
        pairs = [
            (self.un_btn_tor, res is not None and bool(res.entries)),
            (self.un_btn_all, res is not None and len(res.entries) > 1),
            (self.un_btn_raw, res is not None and bool(res.tail)),
        ]
        for w, _ in pairs:
            w.pack_forget()
        for w, show in pairs:
            if show:
                w.pack(side="left", padx=(0, 8))

    def _un_render(self):
        pal = self.pal
        for box in (self.un_advice, self.un_list):
            for w in box.winfo_children():
                w.destroy()

        st = self.st_un
        res = st["result"]
        self.un_count.config(text="")
        self._un_sync_buttons(res)

        if st["error"]:
            advice_row(self.un_advice, pal, "bad", "这个文件打不开", "",
                       st["error"]).pack(fill="x")
            return

        if res is None:
            tk.Label(
                self.un_advice, text="拖一个图种进来就会自动拆开。",
                bg=pal["bg"], fg=pal["ink3"], font=FONTS["ui_xs"], anchor="w",
            ).pack(anchor="w")
            return

        # ── 没有附加数据 ──────────────────────────────
        if not res.has_payload:
            advice_row(
                self.un_advice, pal, "warn", "这张图里没有藏东西",
                res.image_kind or "未知格式",
                "图片本体到第 %s 字节就结束了，后面一个字节都没有。"
                "图种的附加数据必须挂在这个位置之后；如果对方发来的是原图，那就是真没藏。"
                % format(res.image_end, ","),
            ).pack(fill="x")
            return

        # ── 有附加数据 ────────────────────────────────
        tq = res.torrents
        bad = res.bad_crc
        info = res.torrent

        lines = ["图片本体 %s + 附加数据 %s"
                 % (fmt_size(res.image_end), fmt_size(len(res.tail)))]
        if res.offset_fixed:
            lines.append("压缩包的偏移已还原 —— 单独拿出来也能直接双击打开")
        if res.entries:
            lines.append("CRC 全部校验通过" if bad == 0
                         else "有 %d 个文件的 CRC 对不上，图种可能在传输中被改坏了" % bad)
        if info is not None:
            lines.append("种子：%s · %d 个文件 · 共 %s"
                         % (info.name or "（无名）", info.files, fmt_size(info.size)))
            if info.tracker_host:
                lines.append("Tracker：%s" % info.tracker_host)
            if info.infohash:
                lines.append("infohash：%s" % info.infohash)
        for n in res.notes:
            lines.append(n)
        if res.warning:
            lines.append(res.warning)

        if res.warning:
            level = "warn"
        elif tq:
            level = "ok"
        elif res.entries:
            level = "ok" if bad == 0 else "warn"
        else:
            level = "warn"
        dot = "!" if level == "warn" else ""

        if tq:
            title = ("解出 %d 个文件，其中 %d 个是种子" % (len(res.entries), len(tq))
                     if len(res.entries) > 1 else "这是一个种子")
        elif res.entries:
            title = "解出 %d 个文件" % len(res.entries)
        else:
            title = res.warning or "附加数据的类型认不出来"

        advice_row(self.un_advice, pal, level, title, res.payload_type or dot,
                   "\n".join(lines)).pack(fill="x")

        if not res.entries:
            return

        # ── 文件列表 ──────────────────────────────────
        total = sum(e.size for e in res.entries)
        self.un_count.config(text="共 %d 个文件 · %s"
                                  % (len(res.entries), fmt_size(total)))

        card = tk.Frame(self.un_list, bg=pal["surface"],
                        highlightbackground=pal["line"], highlightthickness=1)
        card.pack(fill="x")

        head = tk.Frame(card, bg=pal["sunken"])
        head.pack(fill="x")
        tk.Label(head, text="拆出来的文件", bg=pal["sunken"], fg=pal["ink2"],
                 font=FONTS["ui_sm"], anchor="w").pack(side="left", padx=s(12), pady=s(6))
        tk.Label(head, text="%d 个 · %s" % (len(res.entries), fmt_size(total)),
                 bg=pal["sunken"], fg=pal["ink3"], font=FONTS["ui_xs"]).pack(
            side="right", padx=s(12))

        for i, e in enumerate(res.entries):
            self._un_row(card, i, e)

    def _un_row(self, parent, idx, entry):
        pal = self.pal
        if idx:
            tk.Frame(parent, bg=pal["line"], height=1).pack(fill="x")

        row = tk.Frame(parent, bg=pal["surface"])
        row.pack(fill="x")
        inner = tk.Frame(row, bg=pal["surface"])
        inner.pack(fill="x", padx=s(12), pady=s(7))

        tag = "TOR" if entry.is_torrent else (
            (Path(entry.name).suffix[1:4] or "file").upper())
        tk.Label(inner, text=tag, bg=pal["sunken"], fg=pal["ink2"],
                 font=FONTS["ui_xs"], width=4, pady=s(2)).pack(side="left",
                                                              padx=(0, s(10)))

        btn = tk.Label(inner, text="保存", bg=pal["surface"], fg=pal["ink2"],
                       font=FONTS["ui_xs"], cursor="hand2", padx=s(9), pady=s(3),
                       highlightbackground=pal["line"], highlightthickness=1)
        btn.pack(side="right")
        btn.bind("<Button-1>", lambda e: self.un_save_one(entry))
        btn.bind("<Enter>", lambda e: btn.configure(bg=pal["sunken"]))
        btn.bind("<Leave>", lambda e: btn.configure(bg=pal["surface"]))

        tk.Label(inner, text=fmt_size(entry.size), bg=pal["surface"], fg=pal["ink3"],
                 font=FONTS["ui_xs"]).pack(side="right", padx=s(10))

        name = _short(entry.name)
        tk.Label(
            inner, text=name, bg=pal["surface"],
            fg=pal["warn_ink"] if not entry.crc_ok else pal["ink"],
            font=FONTS["ui_sm"], anchor="w",
        ).pack(side="left", fill="x", expand=True)

    # -- 导出 ---------------------------------------------------------
    def _un_result(self):
        res = self.st_un["result"]
        if res is None or not res.entries:
            self.toast("还没有可以导出的文件。", True)
            return None
        return res

    def un_save_one(self, entry):
        if not entry.data:
            self.toast("这项读不出来，没法导出。", True)
            return
        ext = Path(entry.name).suffix or ".bin"
        out = self._ask_save(unpack.safe_leaf(entry.name), ext)
        if out:
            try:
                unpack.save_entry(entry, out)
                self.toast("已保存 %s" % fmt_size(entry.size))
            except Exception as exc:  # noqa: BLE001
                self.toast("写文件失败：%s" % exc, True)

    def un_save_torrent(self):
        res = self._un_result()
        if res is None:
            return
        tq = res.torrents or res.entries
        if len(tq) == 1:
            self.un_save_one(tq[0])
            return
        folder = filedialog.askdirectory(parent=self, title="种子导出到哪个文件夹")
        if not folder:
            return
        try:
            n = unpack.save_all(tq, folder)
            self.toast("已导出 %d 个文件" % n)
        except Exception as exc:  # noqa: BLE001
            self.toast("导出失败：%s" % exc, True)

    def un_save_all(self):
        res = self._un_result()
        if res is None:
            return
        folder = filedialog.askdirectory(parent=self, title="解出来的文件放到哪个文件夹")
        if not folder:
            return
        try:
            n = unpack.save_all(res.entries, folder)
            self.toast("已导出 %d 个文件" % n)
        except Exception as exc:  # noqa: BLE001
            self.toast("导出失败：%s" % exc, True)

    def un_save_tail(self):
        res = self.st_un["result"]
        if res is None or not res.tail:
            self.toast("没有附加数据可导出。", True)
            return
        ext = res.payload_ext or ".bin"
        out = self._ask_save("%s_附加数据%s" % (_stem(res.source), ext), ext)
        if not out:
            return
        try:
            Path(out).write_bytes(res.tail_clean)
            self.toast("已导出 %s%s" % (
                fmt_size(len(res.tail_clean)),
                "（偏移已还原，能直接打开）" if res.offset_fixed else ""))
        except Exception as exc:  # noqa: BLE001
            self.toast("写文件失败：%s" % exc, True)

    # ══════════════════════════════════════════════════════
    #  模块三：幻影坦克
    # ══════════════════════════════════════════════════════
    def build_phantom(self):
        pal = self.pal
        wrap = ScrollFrame(self.stage, pal)
        wrap.pack(fill="both", expand=True)
        root = wrap.inner

        tk.Label(root, text="幻影坦克", bg=pal["bg"], fg=pal["ink"],
                 font=FONTS["title"], anchor="w").pack(anchor="w")
        tk.Label(
            root,
            text="一张 PNG，浅色背景下看到第一张，深色背景下看到第二张。"
                 "靠 alpha 通道实现 —— 转成 JPG 就彻底失效。",
            bg=pal["bg"], fg=pal["ink3"], font=FONTS["ui_xs"],
            anchor="w", justify="left", wraplength=s(780),
        ).pack(anchor="w", pady=(4, 14))

        row = tk.Frame(root, bg=pal["bg"])
        row.pack(fill="x")
        row.columnconfigure(0, weight=1, uniform="c")
        row.columnconfigure(1, weight=1, uniform="c")

        self._pt_card(row, "fg", "正常查看的图", "浅色背景下看到的",
                      "拖入图片，或点击选择").grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        self._pt_card(row, "bg", "藏在后面的图", "深色背景下浮现，会被压暗",
                      "拖入图片，或点击选择").grid(row=0, column=1, sticky="nsew", padx=(10, 0))

        # ── 控制条 ────────────────────────────────────
        ctl = tk.Frame(root, bg=pal["bg"])
        ctl.pack(fill="x", pady=(14, 0))

        tk.Label(ctl, text="后面的图亮度", bg=pal["bg"], fg=pal["ink2"],
                 font=FONTS["ui_sm"]).pack(side="left")

        self.pt_bright = Slider(
            ctl, pal, 15, 100, int(self.cfg.get("bright", 55)), step=1,
            width=220, on_change=self._pt_slider,
        )
        self.pt_bright.pack(side="left", padx=s(10))
        self.pt_bright_lbl = tk.Label(ctl, text="%d%%" % int(self.pt_bright.get()),
                                      bg=pal["bg"], fg=pal["ink"], font=FONTS["ui_sm"],
                                      width=5, anchor="w")
        self.pt_bright_lbl.pack(side="left")

        self.pt_boost = Check(ctl, pal, "前景提亮",
                              bool(self.cfg.get("boost", False)),
                              on_change=self._pt_toggle_boost)
        self.pt_boost.pack(side="left", padx=(s(16), 0))

        bar = tk.Frame(root, bg=pal["bg"])
        bar.pack(fill="x", pady=(12, 0))
        self._btn(bar, "生成并保存 PNG", self.pt_do_save, primary=True).pack(side="left")
        self._btn(bar, "清空", self.pt_reset).pack(side="left", padx=8)

        self.pt_eq = tk.Label(bar, text="", bg=pal["bg"], fg=pal["ink3"],
                              font=FONTS["ui_xs"])
        self.pt_eq.pack(side="right")

        # ── 双底色预览（核心）──────────────────────────
        pv = tk.Frame(root, bg=pal["bg"])
        pv.pack(fill="x", pady=(14, 0))
        pv.columnconfigure(0, weight=1, uniform="p")
        pv.columnconfigure(1, weight=1, uniform="p")

        self.pt_left = PreviewTile(pv, pal, "浅色背景", "对方正常看到",
                                   bg_rgb=(255, 255, 255), size=(s(420), s(232)))
        self.pt_left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

        self.pt_right = PreviewTile(pv, pal, "深色背景", "藏着的那张",
                                    bg_rgb=(10, 10, 12), size=(s(420), s(232)))
        self.pt_right.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        self._spin("phantom", self.pt_left)

        self.pt_advice = tk.Frame(root, bg=pal["bg"])
        self.pt_advice.pack(fill="x", pady=(12, 0))

        tk.Label(
            root,
            text="输出 PNG · 尺寸跟随第一张图 · 纯本地合成，不上传",
            bg=pal["bg"], fg=pal["ink3"], font=FONTS["ui_xs"], anchor="w",
        ).pack(anchor="w", pady=(12, 6))

        self.after(60, self._pt_recompute)

    def _pt_card(self, parent, key, title, hint, sub):
        pal = self.pal
        p = self.st_pt[key]
        filled = None
        thumb = None
        if p:
            filled = {
                "name": Path(p).name,
                "line": "%s · %s" % (_dims(p), fmt_size(os.path.getsize(p))),
            }
            thumb = _thumb(p, (72, 72))
        return DropCard(
            parent, pal, title,
            hint, sub,
            on_pick=lambda: self._pick(lambda q: self.pt_set(key, q), True, "选择图片"),
            on_path=lambda q: self.pt_set(key, q),
            accept=is_image_name,
            thumb=thumb, filled=filled,
        )

    def pt_set(self, key, path):
        try:
            im = open_rgba(path)          # 先试着打开，坏图当场报错
            im.verify  # noqa: B018
            self.st_pt[key] = path
            self.st_pt["result"] = None
            self.build()
            self.after(60, self._pt_recompute)
        except Exception as exc:  # noqa: BLE001
            self.toast("这张图打不开：%s" % exc, True)

    def pt_reset(self):
        self.st_pt.update(fg=None, bg=None, result=None)
        self.build()

    def _pt_slider(self, v=None):
        self.pt_bright_lbl.config(text="%d%%" % int(self.pt_bright.get()))
        self.cfg["bright"] = int(self.pt_bright.get())
        P.save_config(self.cfg)
        self._pt_recompute()

    def _pt_toggle_boost(self, v=None):
        self.cfg["boost"] = bool(self.pt_boost.get())
        P.save_config(self.cfg)
        self._pt_recompute()

    def _pt_recompute(self):
        pal = self.pal
        if self.tab != "phantom" or not hasattr(self, "pt_left"):
            return                      # 界面已经切走，控件不在了
        st = self.st_pt
        if not (st["fg"] and st["bg"]):
            st["result"] = None
            try:
                self.pt_left.set_image(None)
                self.pt_right.set_image(None)
                self.pt_eq.config(text="两张图都拖进来后自动预览")
                for w in self.pt_advice.winfo_children():
                    w.destroy()
            except Exception:  # noqa: BLE001
                pass
            return

        self.pt_eq.config(text="正在合成…")
        fg_path, bg_path = st["fg"], st["bg"]
        bright = self.pt_bright.get() / 100.0
        boost = bool(self.pt_boost.get())

        # 拖亮度滑块会连续触发，代数机制会把上一轮作废，
        # 不会让任务排长队、也不会让旧结果盖掉新结果。
        def job():
            return phantom.compose(
                open_rgba(fg_path), open_rgba(bg_path),
                bright=bright, boost=boost, max_side=PREVIEW_SIDE,
            )

        self.tasks.submit("phantom", job, on_ok=self._pt_done,
                          on_err=self._pt_fail)

    def _pt_done(self, res):
        if not self._alive("phantom", "pt_left"):
            return
        self.st_pt["result"] = res
        self.pt_left.set_image(over_background(res.image, (255, 255, 255)))
        self.pt_right.set_image(over_background(res.image, (8, 8, 10)))
        self.pt_eq.config(text="输出 %d × %d · PNG" % (res.width, res.height))

        for w in self.pt_advice.winfo_children():
            w.destroy()
        for lv, title, quant, desc in phantom.advice(res.stat):
            advice_row(self.pt_advice, self.pal, lv, title, quant, desc).pack(
                fill="x", pady=(0, 6))

    def _pt_fail(self, exc):
        if not self._alive("phantom", "pt_left"):
            return
        self.pt_eq.config(text="合成失败")
        for w in self.pt_advice.winfo_children():
            w.destroy()
        advice_row(self.pt_advice, self.pal, "bad", "合成失败", "",
                   str(exc)).pack(fill="x")

    def pt_do_save(self):
        st = self.st_pt
        if not (st["fg"] and st["bg"]):
            self.toast("两张图还没选全。", True)
            return
        default = "%s_幻影.png" % _stem(st["fg"])
        out = self._ask_save(default, ".png")
        if not out:
            return
        fg_path, bg_path = st["fg"], st["bg"]
        bright = self.pt_bright.get() / 100.0
        boost = bool(self.pt_boost.get())
        max_side = int(self.cfg.get("max_side", 2600))

        def job():
            res = phantom.compose(
                open_rgba(fg_path), open_rgba(bg_path),
                bright=bright, boost=boost, max_side=max_side,
            )
            save_png(res.image, out)
            return out

        self.tasks.submit(
            "phantom", job,
            on_ok=lambda p: self.toast(
                "已生成 %s，换底色就能看到另一张" % fmt_size(os.path.getsize(p))),
            on_err=lambda e: self.toast("保存失败：%s" % e, True),
        )

    # ══════════════════════════════════════════════════════
    #  模块四：幻影提取
    # ══════════════════════════════════════════════════════
    def build_reveal(self):
        pal = self.pal
        wrap = ScrollFrame(self.stage, pal)
        wrap.pack(fill="both", expand=True)
        root = wrap.inner

        tk.Label(root, text="幻影提取", bg=pal["bg"], fg=pal["ink"],
                 font=FONTS["title"], anchor="w").pack(anchor="w")
        tk.Label(
            root,
            text="把幻影坦克图还原成两张：白底合成得到前景，"
                 "黑底合成再整体提亮得到藏着的那张。",
            bg=pal["bg"], fg=pal["ink3"], font=FONTS["ui_xs"],
            anchor="w", justify="left", wraplength=s(780),
        ).pack(anchor="w", pady=(4, 14))

        p = self.st_ex["path"]
        filled = None
        thumb = None
        if p:
            filled = {
                "name": Path(p).name,
                "line": "%s · %s" % (_dims(p), fmt_size(os.path.getsize(p))),
            }
            thumb = _thumb(p, (72, 72))
        DropCard(
            root, pal, "幻影坦克图", "拖入图片，或点击选择",
            "本工具生成的，或别人发来的都行",
            on_pick=lambda: self._pick(self.ex_set, True, "选择幻影坦克图"),
            on_path=self.ex_set, accept=is_image_name,
            thumb=thumb, filled=filled,
        ).pack(fill="x")

        ctl = tk.Frame(root, bg=pal["bg"])
        ctl.pack(fill="x", pady=(12, 0))

        self.ex_auto = Check(ctl, pal, "自动提亮", bool(self.st_ex["auto"]),
                             on_change=self._ex_toggle_auto)
        self.ex_auto.pack(side="left")

        self.ex_factor = Slider(
            ctl, pal, 0.8, 5.0, float(self.st_ex["factor"]), step=0.1,
            width=260, on_change=self._ex_slider,
        )
        self.ex_factor.pack(side="left", padx=s(10))
        self.ex_lbl = tk.Label(ctl, text="%.1f×" % self.ex_factor.get(), bg=pal["bg"],
                               fg=pal["ink"], font=FONTS["ui_sm"], width=6, anchor="w")
        self.ex_lbl.pack(side="left")

        pv = tk.Frame(root, bg=pal["bg"])
        pv.pack(fill="x", pady=(14, 0))
        pv.columnconfigure(0, weight=1, uniform="p")
        pv.columnconfigure(1, weight=1, uniform="p")

        self.ex_left = PreviewTile(pv, pal, "白底正常查看", "第一张",
                                   bg_rgb=(255, 255, 255), size=(s(420), s(232)))
        self.ex_left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

        self.ex_right = PreviewTile(pv, pal, "黑底提亮", "隐藏的那张",
                                    bg_rgb=(10, 10, 12), size=(s(420), s(232)))
        self.ex_right.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        self._spin("reveal", self.ex_left)

        self.ex_note = tk.Label(
            root, text="拖入一张幻影坦克图就会自动分析。", bg=pal["bg"],
            fg=pal["ink3"], font=FONTS["ui_xs"], anchor="w", justify="left",
            wraplength=s(780),
        )
        self.ex_note.pack(anchor="w", pady=(12, 6))

        bar = tk.Frame(root, bg=pal["bg"])
        bar.pack(fill="x", pady=(6, 0))
        self._btn(bar, "保存白底图", lambda: self.ex_save("fg")).pack(side="left")
        self._btn(bar, "保存隐藏图", lambda: self.ex_save("bg")).pack(side="left", padx=8)

        self.after(60, self._ex_recompute)

    def ex_set(self, path):
        self.st_ex["path"] = path
        self.build()
        self.after(60, self._ex_recompute)

    def _ex_toggle_auto(self, v=None):
        self.st_ex["auto"] = bool(self.ex_auto.get())
        self.cfg["reveal_auto"] = self.st_ex["auto"]
        P.save_config(self.cfg)
        self._ex_recompute()

    def _ex_slider(self, v=None):
        v = float(self.ex_factor.get())
        self.st_ex["factor"] = v
        self.ex_lbl.config(text="%.1f×" % v)
        self.cfg["reveal_factor"] = v
        P.save_config(self.cfg)
        self._ex_apply(recompute=False)

    def _ex_recompute(self):
        st = self.st_ex
        if self.tab != "reveal" or not hasattr(self, "ex_left"):
            return                      # 界面已经切走，控件不在了
        if not st["path"]:
            return
        path, auto, cur_factor = st["path"], st["auto"], st["factor"]

        # 一次任务做完「读图 + 分析 + 自动提亮 + 渲染」，
        # 不分两段提交，否则转圈会 stop 完又 start，闪一下。
        def job():
            im = open_rgba(path)
            an = reveal.analyze(im)
            f = reveal.auto_reveal(im) if (auto and an.phantom) else cur_factor
            views = None
            if an.phantom:
                work = im
                if max(im.size) > PREVIEW_SIDE:
                    r = PREVIEW_SIDE / max(im.size)
                    work = im.resize((max(1, round(im.size[0] * r)),
                                      max(1, round(im.size[1] * r))), LANCZOS)
                views = (reveal.build_fg(work), reveal.build_bg(work, f))
            return im, an, f, views

        self.tasks.submit("reveal", job, on_ok=self._ex_ready,
                          on_err=self._ex_fail)

    def _ex_ready(self, payload):
        if not self._alive("reveal", "ex_left"):
            return
        im, an, f, views = payload
        self._ex_stat = an
        self._ex_img = im
        st = self.st_ex

        if not an.phantom:
            self.ex_left.set_image(None)
            self.ex_right.set_image(None)
            self.ex_note.config(text=reveal.verdict(an, im, st["factor"]),
                                fg=self.pal["warn_ink"])
            return

        if st["auto"] and abs(f - st["factor"]) > 1e-6:
            st["factor"] = f
            self.ex_factor.set(f)
            self.ex_lbl.config(text="%.1f×" % f)

        fg_img, bg_img = views
        self.ex_left.set_image(fg_img)
        self.ex_right.set_image(bg_img)
        self.ex_right.set_caption("提亮 %.1f×" % f)
        self.ex_note.config(text=reveal.verdict(an, im, f), fg=self.pal["ink3"])

    def _ex_fail(self, exc):
        if not self._alive("reveal", "ex_left"):
            return
        self.ex_note.config(text="处理失败：%s" % exc, fg=self.pal["bad_ink"])

    def _ex_apply(self, recompute: bool, an=None, im=None):
        st = self.st_ex
        an = an or getattr(self, "_ex_stat", None)
        im = im or getattr(self, "_ex_img", None)
        if an is None or im is None:
            return

        big = PREVIEW_SIDE
        factor = st["factor"]

        def job():
            work = im
            if max(im.size) > big:
                work = im.resize(
                    (max(1, round(im.size[0] * big / max(im.size))),
                     max(1, round(im.size[1] * big / max(im.size)))), LANCZOS)
            return reveal.build_fg(work), reveal.build_bg(work, factor), factor

        self.tasks.submit("reveal", job, on_ok=lambda r: self._ex_paint(*r),
                          on_err=self._ex_fail)

    def _ex_paint(self, fg_img, bg_img, factor):
        if not self._alive("reveal", "ex_left"):
            return
        try:
            self.ex_left.set_image(fg_img)
            self.ex_right.set_image(bg_img)
            self.ex_right.set_caption("提亮 %.1f×" % factor)
            self.ex_note.config(
                text=reveal.verdict(self._ex_stat, self._ex_img, factor),
                fg=self.pal["ink3"])
        except Exception as exc:  # noqa: BLE001
            self.ex_note.config(text="渲染失败：%s" % exc, fg=self.pal["bad_ink"])

    def ex_save(self, which):
        st = self.st_ex
        if not st["path"] or not getattr(self, "_ex_img", None):
            self.toast("还没有可以保存的画面。", True)
            return
        im = self._ex_img
        out_im = reveal.build_fg(im) if which == "fg" else reveal.build_bg(im, st["factor"])
        suffix = "_白底" if which == "fg" else "_隐藏_%.1fx" % st["factor"]
        out = self._ask_save("%s%s.png" % (_stem(st["path"]), suffix), ".png")
        if not out:
            return
        try:
            out_im.save(out, "PNG")
            self.toast("已保存 %s" % fmt_size(os.path.getsize(out)))
        except Exception as exc:  # noqa: BLE001
            self.toast("保存失败：%s" % exc, True)


    # ══════════════════════════════════════════════════════
    #  模块五：抠图
    # ══════════════════════════════════════════════════════
    def build_cut(self):
        pal = self.pal
        wrap = ScrollFrame(self.stage, pal)
        wrap.pack(fill="both", expand=True)
        root = wrap.inner

        tk.Label(root, text="抠图", bg=pal["bg"], fg=pal["ink"],
                 font=FONTS["title"], anchor="w").pack(anchor="w")
        tk.Label(
            root,
            text="识别画面里的主体并抠出来，左中右三张：原图、抠出的元素、衬底效果。"
                 "衬白底还是黑底由主体亮度决定 —— 深色主体配白底，浅色配黑底，对比最大。",
            bg=pal["bg"], fg=pal["ink3"], font=FONTS["ui_xs"],
            anchor="w", justify="left", wraplength=s(820),
        ).pack(anchor="w", pady=(4, 14))

        p = self.st_cu["path"]
        filled = thumb = None
        if p:
            try:
                filled = {"name": Path(p).name,
                          "line": "%s · %s" % (_dims(p), fmt_size(os.path.getsize(p)))}
                thumb = _thumb(p, (72, 72))
            except OSError:
                filled = {"name": Path(p).name, "line": _dims(p)}
        DropCard(
            root, pal, "原图", "拖入图片，或点击选择",
            "带主体就行，背景复杂也能试",
            on_pick=lambda: self._pick(self.cu_set, True, "选择要抠图的原图"),
            on_path=self.cu_set, accept=is_image_name,
            thumb=thumb, filled=filled,
        ).pack(fill="x")

        # ── 当前引擎 ─────────────────────────────────────
        eng = tk.Frame(root, bg=pal["bg"])
        eng.pack(fill="x", pady=(10, 0))
        ai_ready = matting.mode() == "ai"
        tk.Label(eng, text="引擎：", bg=pal["bg"], fg=pal["ink3"],
                 font=FONTS["ui_xs"]).pack(side="left")
        tk.Label(eng,
                 text="AI 分割模型（复杂背景可用）" if ai_ready
                 else "基础算法（纯色/渐变底可用）",
                 bg=pal["bg"], fg=pal["ok_ink"] if ai_ready else pal["warn_ink"],
                 font=FONTS["ui_xs"]).pack(side="left")
        if not ai_ready:
            tk.Label(eng, text="· 把 isnet-anime.onnx 放进 models/ 可启用 AI",
                     bg=pal["bg"], fg=pal["ink3"],
                     font=FONTS["ui_xs"]).pack(side="left")

        # ── 三视图 ───────────────────────────────────────
        pv = tk.Frame(root, bg=pal["bg"])
        pv.pack(fill="x", pady=(12, 0))
        for i in range(3):
            pv.columnconfigure(i, weight=1, uniform="cu")

        # 素材多为竖幅，格子做成竖长方形比正方形省横向空间
        cell = (s(238), s(300))
        self.cu_a = PreviewTile(pv, pal, "原图", "", bg_rgb=(30, 30, 34), size=cell)
        self.cu_a.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self.cu_b = PreviewTile(pv, pal, "抠出的元素", "棋盘格＝透明", bg_rgb=(158, 158, 158),
                                size=cell)
        self.cu_b.grid(row=0, column=1, sticky="nsew", padx=8)
        self.cu_c = PreviewTile(pv, pal, "衬底效果", "", bg_rgb=(255, 255, 255), size=cell)
        self.cu_c.grid(row=0, column=2, sticky="nsew", padx=(8, 0))
        # 转圈挂在中间那格：那是结果最终要去的地方
        self._spin("cut", self.cu_b)

        # ── 结论 ─────────────────────────────────────────
        self.cu_note = tk.Label(
            root, text="拖入一张图就会自动分析。" if not p else "正在识别主体…",
            bg=pal["bg"], fg=pal["ink3"], font=FONTS["ui_xs"], anchor="w",
            justify="left", wraplength=s(820), height=3,
        )
        self.cu_note.pack(anchor="w", pady=(12, 4))

        # ── 底色与导出 ───────────────────────────────────
        bar = tk.Frame(root, bg=pal["bg"])
        bar.pack(fill="x", pady=(4, 0))

        tk.Label(bar, text="衬底", bg=pal["bg"], fg=pal["ink3"],
                 font=FONTS["ui_xs"]).pack(side="left", padx=(0, 8))
        self.cu_btns = {}
        for key, label in (("auto", "自动"), ("white", "白底"), ("black", "黑底")):
            b = tk.Label(bar, text=label, font=FONTS["ui_xs"], padx=s(12), pady=s(5),
                         cursor="hand2", highlightthickness=0)
            b.bind("<Button-1>", lambda e, k=key: self._cu_backdrop(k))
            b.pack(side="left", padx=(0, 6))
            self.cu_btns[key] = b

        self._btn(bar, "保存透明 PNG", lambda: self.cu_save("png"),
                  primary=True).pack(side="right")
        self._btn(bar, "保存三视图", lambda: self.cu_save("view")).pack(side="right", padx=8)

        self._cu_mark()
        if p:
            self.after(60, self._cu_recompute)

    # ── 抠图：状态与刷新 ─────────────────────────────────
    def cu_set(self, path):
        self.st_cu["path"] = path
        self.build()
        self.after(60, self._cu_recompute)

    def _cu_mark(self):
        """三个衬底按钮的选中态。"""
        pal = self.pal
        for key, b in getattr(self, "cu_btns", {}).items():
            on = key == self.st_cu["backdrop"]
            b.configure(bg=pal["solid"] if on else pal["surface"],
                        fg=pal["on_solid"] if on else pal["ink2"])

    def _cu_backdrop(self, key):
        self.st_cu["backdrop"] = key
        self._cu_paint()
        self._cu_mark()

    def _cu_recompute(self):
        if self.tab != "cut" or not hasattr(self, "cu_a"):
            return
        path = self.st_cu["path"]
        if not path:
            return
        self.cu_note.config(text="正在识别主体…", fg=self.pal["ink3"])
        # 抠图是全项目最重的操作（AI 模式约 2.5 秒），必须丢到后台，
        # 否则主线程卡死，转圈也转不动。
        self.tasks.submit(
            "cut",
            fn=lambda: matting.cut(path, max_side=CUT_PREVIEW_SIDE),
            on_ok=self._cu_done,
            on_err=self._cu_fail,
        )

    def _cu_done(self, res):
        if not self._alive("cut", "cu_a"):
            return
        if res is None:
            self.cu_note.config(text="这张图读不出来（格式不支持或文件损坏）。",
                                fg=self.pal["bad_ink"])
            return

        self._cu_res = res
        self._cu_paint()
        self.cu_note.config(text=self._cu_text(res),
                            fg=self.pal["warn_ink"] if res.issues else self.pal["ink3"])

    def _cu_fail(self, exc):
        if not self._alive("cut", "cu_a"):
            return
        self.cu_note.config(text="处理失败：%s" % exc, fg=self.pal["bad_ink"])

    def _cu_text(self, res) -> str:
        bits = ["模式 %s" % ("AI 分割" if res.mode == "ai" else "基础算法"),
                "主体占画面 %.0f%%" % (res.cover * 100),
                "耗时 %.1f 秒" % (res.ms / 1000.0)]
        head = " · ".join(bits)
        if res.issues:
            return head + "\n结果是可疑的：" + "；".join(res.issues) + "。可以换张图，或把模型放进 models/ 再试。"
        tail = "边缘按原图细节重新算过，发梢这类细结构能留住。"
        if res.mode == "basic":
            tail = "基础算法只认「背景颜色连不连续」，背景一复杂就会出错 —— 那种情况需要 AI 模型。"
        return head + "\n" + tail

    def _cu_paint(self):
        res = getattr(self, "_cu_res", None)
        if res is None or not hasattr(self, "cu_a"):
            return
        bd = self.st_cu["backdrop"]
        left, mid, right = matting.layers(res, bd)
        self.cu_a.set_image(matting.as_pil(left))
        self.cu_b.set_image(matting.as_pil(mid))
        self.cu_c.set_image(matting.as_pil(right))

        real = res.backdrop if bd == "auto" else bd
        self.cu_c.canvas.configure(bg="#FFFFFF" if real == "white" else "#0A0A0C")
        self.cu_c.set_caption(
            ("自动 → " + ("白底" if res.backdrop == "white" else "黑底")) if bd == "auto"
            else ("白底" if bd == "white" else "黑底"))
        self._cu_mark()

    # ── 抠图：导出（按原尺寸重算）────────────────────────
    def cu_save(self, what):
        path = self.st_cu["path"]
        if not path:
            self.toast("还没有可以保存的图。", True)
            return
        if what == "png":
            out = self._ask_save("%s_抠出.png" % _stem(path), ".png")
        else:
            out = self._ask_save("%s_三视图.png" % _stem(path), ".png")
        if not out:
            return

        self.toast("按原尺寸重算中…")
        bd = self.st_cu["backdrop"]

        def job():
            full = matting.cut(path)              # 不缩，保持原分辨率
            if full is None:
                return None
            if what == "png":
                matting.save_png(full, out)
            else:
                matting.save_compose(full, out, bd, max_side=0)
            return full

        def ok(full):
            if full is None:
                self.toast("读不出这张图。", True)
                return
            self.toast("已保存 %s（%dx%d）"
                       % (fmt_size(os.path.getsize(out)), full.size[0], full.size[1]))

        self.tasks.submit("cut", job, on_ok=ok,
                          on_err=lambda e: self.toast("保存失败：%s" % e, True))


def run():
    app = App()
    app.mainloop()


