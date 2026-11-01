# -*- coding: utf-8 -*-
"""藏图盒 —— 界面。

四个模块：图种（字节追加）、图种解包（把追加的东西拆出来）、
幻影坦克（双画面合成）、幻影提取（还原）。
预览全程在本地完成，不经过任何浏览器或网络。
"""
from __future__ import annotations

import os
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

from PIL import Image

from core import paths as P
from core import phantom, reveal, seed, unpack
from core.seed import payload_kind
from core.imageio import LANCZOS, fit_contain, open_rgba, over_background, save_png
from core.sniff import is_image_name, sniff
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

        self._refs = []
        self.build()

    # ══════════════════════════════════════════════════════
    #  骨架
    # ══════════════════════════════════════════════════════
    def build(self):
        pal = palette(self.theme)
        self.pal = pal
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
        else:
            self.build_reveal()

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
        try:
            self.seed_preview.set_image(open_rgba(p).convert("RGB"))
        except Exception:  # noqa: BLE001
            self.seed_preview.set_image(None)

    def seed_do_pack(self):
        st = self.st_seed
        if not (st["cover"] and st["pay"]):
            self.toast("两张都还没选全。", True)
            return
        try:
            res = seed.pack(st["cover"], st["pay"])
        except Exception as exc:  # noqa: BLE001
            self.toast(str(exc), True)
            return

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

        DropCard(
            root, pal, "图种文件", "拖入图种，或点击选择",
            "改了后缀的图片也照样认；直接拖 .torrent / .zip 也行",
            on_pick=lambda: self._pick(self.un_set, False, "选择图种文件"),
            on_path=self.un_set,
            thumb=thumb, filled=filled,
        ).pack(fill="x")

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
        try:
            res = unpack.unpack(path)
        except Exception as exc:  # noqa: BLE001
            self.st_un.update(path=path, result=None, error=str(exc))
            self.build()
            self.toast(str(exc), True)
            return

        self.st_un.update(path=path, result=res, error="")
        self.build()

        if not res.has_payload:
            self.toast("这张图后面没有附加数据", True)
        elif res.entries:
            self.toast("已拆出 %d 个文件" % len(res.entries))
        elif res.warning:
            self.toast(res.warning, True)

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

        try:
            self.pt_eq.config(text="正在合成…")
            self.update_idletasks()

            fg = open_rgba(st["fg"])
            bg = open_rgba(st["bg"])
            res = phantom.compose(
                fg, bg,
                bright=self.pt_bright.get() / 100.0,
                boost=bool(self.pt_boost.get()),
                max_side=PREVIEW_SIDE,
            )
            st["result"] = res

            self.pt_left.set_image(over_background(res.image, (255, 255, 255)))
            self.pt_right.set_image(over_background(res.image, (8, 8, 10)))
            self.pt_eq.config(text="输出 %d × %d · PNG" % (res.width, res.height))

            for w in self.pt_advice.winfo_children():
                w.destroy()
            for lv, title, quant, desc in phantom.advice(res.stat):
                advice_row(self.pt_advice, pal, lv, title, quant, desc).pack(
                    fill="x", pady=(0, 6))
        except Exception as exc:  # noqa: BLE001
            self.pt_eq.config(text="合成失败")
            for w in self.pt_advice.winfo_children():
                w.destroy()
            advice_row(self.pt_advice, pal, "bad", "合成失败", "",
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
        try:
            fg = open_rgba(st["fg"])
            bg = open_rgba(st["bg"])
            res = phantom.compose(
                fg, bg,
                bright=self.pt_bright.get() / 100.0,
                boost=bool(self.pt_boost.get()),
                max_side=int(self.cfg.get("max_side", 2600)),
            )
            save_png(res.image, out)
            self.toast("已生成 %s，换底色就能看到另一张"
                       % fmt_size(os.path.getsize(out)))
        except Exception as exc:  # noqa: BLE001
            self.toast("保存失败：%s" % exc, True)

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
        try:
            im = open_rgba(st["path"])
            an = reveal.analyze(im)
            self._ex_stat = an
            self._ex_img = im

            if not an.phantom:
                self.ex_left.set_image(None)
                self.ex_right.set_image(None)
                self.ex_note.config(text=reveal.verdict(an, im, st["factor"]),
                                    fg=self.pal["warn_ink"])
                return

            if st["auto"]:
                f = reveal.auto_reveal(im)
                st["factor"] = f
                self.ex_factor.set(f)
                self.ex_lbl.config(text="%.1f×" % f)

            self._ex_apply(recompute=True, an=an, im=im)
        except Exception as exc:  # noqa: BLE001
            self.ex_note.config(text="读取失败：%s" % exc, fg=self.pal["bad_ink"])

    def _ex_apply(self, recompute: bool, an=None, im=None):
        st = self.st_ex
        an = an or getattr(self, "_ex_stat", None)
        im = im or getattr(self, "_ex_img", None)
        if an is None or im is None:
            return

        big = PREVIEW_SIDE
        work = im
        if max(im.size) > big:
            work = im.resize(
                (max(1, round(im.size[0] * big / max(im.size))),
                 max(1, round(im.size[1] * big / max(im.size)))), LANCZOS)

        try:
            self.ex_left.set_image(reveal.build_fg(work))
            self.ex_right.set_image(reveal.build_bg(work, st["factor"]))
            self.ex_right.set_caption("提亮 %.1f×" % st["factor"])
            self.ex_note.config(text=reveal.verdict(an, im, st["factor"]),
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


def run():
    app = App()
    app.mainloop()
