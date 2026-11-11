# -*- coding: utf-8 -*-
"""图种解包 —— 第一个真正搬出本体的插件。

选它当第一个，是因为它依赖最轻（纯字节处理，没有 numpy / OpenCV），
出问题最容易回退；同时它有状态、有异步、有导出，足够验证整套机制：
    发现 → 按需 import → build → 任务跑在 worker 线程 → 结果回来重建界面。

## 插件怎么写

只需要两样东西：
    1. 同目录一个 plugin.json（宿主读它来渲染侧栏，**不 import 本文件**）
    2. 一个 PLUGIN 变量，指向长得像 cangtu.api.Plugin 的对象

界面全部建在 ctx.stage 下面。宿主每次切 tab 都会把它 destroy 掉重建，
所以控件引用不能跨次缓存 —— 要留的东西放 self 上（比如 self.st）。
"""
from __future__ import annotations

import os
import tkinter as tk
from pathlib import Path

from cangtu.api import short_name, stem_of, thumb
from core import unpack as logic
from core.sniff import is_image_name


class UnpackPlugin:
    # ── 元数据（plugin.json 里也有一份，以 json 为准；这里留着方便单测）──
    id = "unpack"
    name = "图种解包"
    subtitle = "直接拆出种子"
    order = 20
    api_version = "1.0"
    requires = ()

    def __init__(self):
        self.ctx = None
        # 界面状态。切 tab、切主题都会重建控件，但实例是复用的，所以这里不丢。
        self.st = {"path": None, "result": None, "error": ""}

    # ── 生命周期 ──────────────────────────────────────────
    def check(self):
        """解包只用标准库，正常情况下没有不可用的理由。

        这里只验「逻辑模块是不是完整」—— 打包时漏收模块、安装包被截断，
        在这里就能暴露，而不是等用户拖进文件才炸。
        """
        if not hasattr(logic, "unpack"):
            return False, "解包模块缺少 unpack()，安装包可能不完整"
        return True, ""

    def build(self, ctx):
        self.ctx = ctx
        W, F, s = ctx.widgets, ctx.fonts, ctx.s
        pal = ctx.pal

        wrap = W.ScrollFrame(ctx.stage, pal)
        wrap.pack(fill="both", expand=True)
        root = wrap.inner

        tk.Label(root, text="图种解包", bg=pal["bg"], fg=pal["ink"],
                 font=F["title"], anchor="w").pack(anchor="w")
        tk.Label(
            root,
            text="拖入一张图种，直接拿到里面的文件 —— 压缩包在这里就地解开，"
                 "不用先改后缀再去解压。种子会单独列出来，并算出 infohash 供核对。",
            bg=pal["bg"], fg=pal["ink3"], font=F["ui_xs"],
            anchor="w", justify="left", wraplength=s(780),
        ).pack(anchor="w", pady=(4, 14))

        st = self.st
        p = st["path"]
        res = st["result"]
        filled = None
        pic = None
        if p:
            try:
                size = W.fmt_size(os.path.getsize(p))
            except OSError:
                size = "—"
            if res is not None and res.has_payload:
                line = "%s · 附加 %s · %s" % (
                    size, W.fmt_size(len(res.tail)), res.payload_type or "未知")
                note = "图片主体结束于第 %s 字节" % format(res.image_end, ",")
            elif res is not None:
                line = size
                note = "末尾没有附加数据"
            else:
                line = size
                note = ""
            filled = {"name": Path(p).name, "line": line, "note": note}
            if is_image_name(p):
                pic = thumb(p, (72, 72))

        self.card = W.DropCard(
            root, pal, "图种文件", "拖入图种，或点击选择",
            "改了后缀的图片也照样认；直接拖 .torrent / .zip 也行",
            on_pick=lambda: ctx.pick_file(self.set_file, False, "选择图种文件"),
            on_path=self.set_file,
            thumb=pic, filled=filled,
        )
        self.card.pack(fill="x")
        ctx.spin(self.id, self.card)

        self.advice = tk.Frame(root, bg=pal["bg"])
        self.advice.pack(fill="x", pady=(12, 0))

        bar = tk.Frame(root, bg=pal["bg"])
        bar.pack(fill="x", pady=(12, 0))
        self.btn_tor = ctx.btn(bar, "导出种子", self.save_torrent, primary=True)
        self.btn_all = ctx.btn(bar, "全部导出", self.save_all)
        self.btn_raw = ctx.btn(bar, "附加数据另存", self.save_tail)

        self.count = tk.Label(bar, text="", bg=pal["bg"], fg=pal["ink3"],
                              font=F["ui_xs"])
        self.count.pack(side="right")

        self.list_box = tk.Frame(root, bg=pal["bg"])
        self.list_box.pack(fill="x", pady=(14, 0))

        tk.Label(
            root,
            text="解包只读不写：不会改动你拖进来的那张图。"
                 "种子里的 infohash 是 info 段的 SHA-1，拿去任何站点搜一下就能对上。",
            bg=pal["bg"], fg=pal["ink3"], font=F["ui_xs"],
            anchor="w", justify="left", wraplength=s(780),
        ).pack(anchor="w", pady=(14, 6))

        self._render()
        return wrap

    # ── 状态 → 界面 ───────────────────────────────────────
    def set_file(self, path):
        ctx = self.ctx
        ctx.tasks.submit(
            self.id,
            fn=lambda: logic.unpack(path),
            on_ok=lambda res: self._done(path, res),
            on_err=lambda exc: self._fail(path, exc),
        )

    def _done(self, path, res):
        self.st.update(path=path, result=res, error="")
        self.ctx.rebuild()

        if not res.has_payload:
            self.ctx.toast("这张图后面没有附加数据", True)
        elif res.entries:
            self.ctx.toast("已拆出 %d 个文件" % len(res.entries))
        elif res.warning:
            self.ctx.toast(res.warning, True)

    def _fail(self, path, exc):
        self.st.update(path=path, result=None, error=str(exc))
        self.ctx.rebuild()
        self.ctx.toast(str(exc), True)

    def _sync_buttons(self, res):
        """没东西可导出的按钮就别摆着 —— 点了只会提示「没有可导出的文件」。"""
        pairs = [
            (self.btn_tor, res is not None and bool(res.entries)),
            (self.btn_all, res is not None and len(res.entries) > 1),
            (self.btn_raw, res is not None and bool(res.tail)),
        ]
        for w, _ in pairs:
            w.pack_forget()
        for w, show in pairs:
            if show:
                w.pack(side="left", padx=(0, 8))

    def _render(self):
        W, F, s = self.ctx.widgets, self.ctx.fonts, self.ctx.s
        pal = self.ctx.pal
        for box in (self.advice, self.list_box):
            for w in box.winfo_children():
                w.destroy()

        st = self.st
        res = st["result"]
        self.count.config(text="")
        self._sync_buttons(res)

        if st["error"]:
            W.advice_row(self.advice, pal, "bad", "这个文件打不开", "",
                         st["error"]).pack(fill="x")
            return

        if res is None:
            tk.Label(
                self.advice, text="拖一个图种进来就会自动拆开。",
                bg=pal["bg"], fg=pal["ink3"], font=F["ui_xs"], anchor="w",
            ).pack(anchor="w")
            return

        # ── 没有附加数据 ──────────────────────────────
        if not res.has_payload:
            W.advice_row(
                self.advice, pal, "warn", "这张图里没有藏东西",
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
                 % (W.fmt_size(res.image_end), W.fmt_size(len(res.tail)))]
        if res.offset_fixed:
            lines.append("压缩包的偏移已还原 —— 单独拿出来也能直接双击打开")
        if res.entries:
            lines.append("CRC 全部校验通过" if bad == 0
                         else "有 %d 个文件的 CRC 对不上，图种可能在传输中被改坏了" % bad)
        if info is not None:
            lines.append("种子：%s · %d 个文件 · 共 %s"
                         % (info.name or "（无名）", info.files, W.fmt_size(info.size)))
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

        W.advice_row(self.advice, pal, level, title, res.payload_type or dot,
                     "\n".join(lines)).pack(fill="x")

        if not res.entries:
            return

        # ── 文件列表 ──────────────────────────────────
        total = sum(e.size for e in res.entries)
        self.count.config(text="共 %d 个文件 · %s"
                               % (len(res.entries), W.fmt_size(total)))

        card = tk.Frame(self.list_box, bg=pal["surface"],
                        highlightbackground=pal["line"], highlightthickness=1)
        card.pack(fill="x")

        head = tk.Frame(card, bg=pal["sunken"])
        head.pack(fill="x")
        tk.Label(head, text="拆出来的文件", bg=pal["sunken"], fg=pal["ink2"],
                 font=F["ui_sm"], anchor="w").pack(side="left", padx=s(12), pady=s(6))
        tk.Label(head, text="%d 个 · %s" % (len(res.entries), W.fmt_size(total)),
                 bg=pal["sunken"], fg=pal["ink3"], font=F["ui_xs"]).pack(
            side="right", padx=s(12))

        for i, e in enumerate(res.entries):
            self._row(card, i, e)

    def _row(self, parent, idx, entry):
        F, s = self.ctx.fonts, self.ctx.s
        pal = self.ctx.pal
        if idx:
            tk.Frame(parent, bg=pal["line"], height=1).pack(fill="x")

        row = tk.Frame(parent, bg=pal["surface"])
        row.pack(fill="x")
        inner = tk.Frame(row, bg=pal["surface"])
        inner.pack(fill="x", padx=s(12), pady=s(7))

        tag = "TOR" if entry.is_torrent else (
            (Path(entry.name).suffix[1:4] or "file").upper())
        tk.Label(inner, text=tag, bg=pal["sunken"], fg=pal["ink2"],
                 font=F["ui_xs"], width=4, pady=s(2)).pack(side="left",
                                                           padx=(0, s(10)))

        btn = tk.Label(inner, text="保存", bg=pal["surface"], fg=pal["ink2"],
                       font=F["ui_xs"], cursor="hand2", padx=s(9), pady=s(3),
                       highlightbackground=pal["line"], highlightthickness=1)
        btn.pack(side="right")
        btn.bind("<Button-1>", lambda e: self.save_one(entry))
        btn.bind("<Enter>", lambda e: btn.configure(bg=pal["sunken"]))
        btn.bind("<Leave>", lambda e: btn.configure(bg=pal["surface"]))

        tk.Label(inner, text=self.ctx.widgets.fmt_size(entry.size),
                 bg=pal["surface"], fg=pal["ink3"],
                 font=F["ui_xs"]).pack(side="right", padx=s(10))

        tk.Label(
            inner, text=short_name(entry.name), bg=pal["surface"],
            fg=pal["warn_ink"] if not entry.crc_ok else pal["ink"],
            font=F["ui_sm"], anchor="w",
        ).pack(side="left", fill="x", expand=True)

    # ── 导出 ──────────────────────────────────────────────
    def _result(self):
        res = self.st["result"]
        if res is None or not res.entries:
            self.ctx.toast("还没有可以导出的文件。", True)
            return None
        return res

    def save_one(self, entry):
        ctx = self.ctx
        if not entry.data:
            ctx.toast("这项读不出来，没法导出。", True)
            return
        ext = Path(entry.name).suffix or ".bin"
        out = ctx.ask_save(logic.safe_leaf(entry.name), ext)
        if out:
            try:
                logic.save_entry(entry, out)
                ctx.toast("已保存 %s" % ctx.widgets.fmt_size(entry.size))
            except Exception as exc:  # noqa: BLE001
                ctx.toast("写文件失败：%s" % exc, True)

    def save_torrent(self):
        ctx = self.ctx
        res = self._result()
        if res is None:
            return
        tq = res.torrents or res.entries
        if len(tq) == 1:
            self.save_one(tq[0])
            return
        folder = ctx.ask_dir("种子导出到哪个文件夹")
        if not folder:
            return
        try:
            n = logic.save_all(tq, folder)
            ctx.toast("已导出 %d 个文件" % n)
        except Exception as exc:  # noqa: BLE001
            ctx.toast("导出失败：%s" % exc, True)

    def save_all(self):
        ctx = self.ctx
        res = self._result()
        if res is None:
            return
        folder = ctx.ask_dir("解出来的文件放到哪个文件夹")
        if not folder:
            return
        try:
            n = logic.save_all(res.entries, folder)
            ctx.toast("已导出 %d 个文件" % n)
        except Exception as exc:  # noqa: BLE001
            ctx.toast("导出失败：%s" % exc, True)

    def save_tail(self):
        ctx = self.ctx
        res = self.st["result"]
        if res is None or not res.tail:
            ctx.toast("没有附加数据可导出。", True)
            return
        ext = res.payload_ext or ".bin"
        out = ctx.ask_save("%s_附加数据%s" % (stem_of(res.source), ext), ext)
        if not out:
            return
        try:
            Path(out).write_bytes(res.tail_clean)
            ctx.toast("已导出 %s%s" % (
                ctx.widgets.fmt_size(len(res.tail_clean)),
                "（偏移已还原，能直接打开）" if res.offset_fixed else ""))
        except Exception as exc:  # noqa: BLE001
            ctx.toast("写文件失败：%s" % exc, True)


PLUGIN = UnpackPlugin()
