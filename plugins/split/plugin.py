# -*- coding: utf-8 -*-
"""分卷解压 —— 界面。

这个插件的重点不在「解压」，在「拦住不该解压的东西」。

整个交互围绕一个判断：
    卷齐了吗？大小对吗？内容真的没坏吗？
只有三关都过，解压按钮才会出现。

按产品上的老规矩：**不能用的东西不摆出来**。分卷不齐的时候，
这里不会有一个灰掉的「解压」按钮等着用户去点 —— 只会有一句话告诉他
缺哪一卷、去哪儿补。按钮在条件满足前根本不存在。
"""
from __future__ import annotations

import tkinter as tk
from pathlib import Path

from cangtu.api import short_name
from core import splitvol as S


class SplitPlugin:
    id = "split"
    name = "分卷解压"
    subtitle = "缺卷检测 · 完整校验"
    order = 60
    api_version = "1.0"
    requires = ()

    def __init__(self):
        self.ctx = None
        # 界面会被反复重建，状态放这里才不会丢
        self.st = {"path": None, "set": None, "probe": None, "err": ""}

    # ── 生命周期 ──────────────────────────────────────────
    def check(self):
        """后端不在就如实说。

        7z.exe 是随包带的，缺了只有一种可能：文件被删了或者在杀软隔离区里。
        那属于「损坏」不是「没装」，所以要显示出来，而不是让模块悄悄消失。
        """
        return S.backend()

    def build(self, ctx):
        self.ctx = ctx
        W, F, s, pal = ctx.widgets, ctx.fonts, ctx.s, ctx.pal

        wrap = W.ScrollFrame(ctx.stage, pal)
        wrap.pack(fill="both", expand=True)
        root = wrap.inner

        tk.Label(root, text="分卷解压", bg=pal["bg"], fg=pal["ink"],
                 font=F["title"], anchor="w").pack(anchor="w")
        tk.Label(
            root,
            text="拖进任意一卷就行（第 2 卷、最后一卷都可以），程序会按文件名"
                 "找回同目录的其他卷，先确认齐全、再逐个校验内容，全部通过才解压。",
            bg=pal["bg"], fg=pal["ink3"], font=F["ui_xs"],
            anchor="w", justify="left", wraplength=s(780),
        ).pack(anchor="w", pady=(4, 14))

        st = self.st
        p = st["path"]
        vs = st["set"]
        filled = None
        if p:
            try:
                size = W.fmt_size(Path(p).stat().st_size)
            except OSError:
                size = "—"
            note = ""
            if vs is not None:
                # 不完整时不能只报「共 3 卷」—— 那会让人以为整个包就 3 卷。
                # 要写成 3 / 4，缺的那一卷才看得出来。
                if vs.complete:
                    note = "%s 型 · 共 %d 卷 · %s" % (
                        vs.kind.upper(), len(vs.volumes), W.fmt_size(vs.total))
                else:
                    note = "%s 型 · 已有 %d / %d 卷 · 已下载 %s" % (
                        vs.kind.upper(), len(vs.volumes), vs.count,
                        W.fmt_size(vs.total))
            filled = {"name": Path(p).name, "line": size, "note": note}

        self.card = W.DropCard(
            root, pal, "分卷文件", "拖入任意一卷，或点击选择",
            "支持 .7z.001 / .zip.001 / .part1.rar / .z01 / .001",
            on_pick=lambda: ctx.pick_file(self.set_file, False,
                                          "选择分卷文件（任意一卷）"),
            on_path=self.set_file,
            filled=filled,
        )
        self.card.pack(fill="x")
        ctx.spin(self.id, self.card)

        self.advice = tk.Frame(root, bg=pal["bg"])
        self.advice.pack(fill="x", pady=(12, 0))

        self.list_box = tk.Frame(root, bg=pal["bg"])
        self.list_box.pack(fill="x", pady=(10, 0))

        self.bar = tk.Frame(root, bg=pal["bg"])
        self.bar.pack(fill="x", pady=(12, 0))

        self._render()

        tk.Label(
            root,
            text="为什么不能「差不多就解」：分卷缺一段或者坏一个字节，解出来的文件"
                 "看起来是完整的，但里面已经有坏数据了 —— 图片打不开、视频卡在某一帧、"
                 "安装包中途报错。这类问题事后极难定位，所以在解压前就挡住。",
            bg=pal["bg"], fg=pal["ink3"], font=F["ui_xs"],
            anchor="w", justify="left", wraplength=s(780),
        ).pack(anchor="w", pady=(14, 6))

        return wrap

    # ── 选文件 ────────────────────────────────────────────
    def set_file(self, path):
        """扫描卷组 + 结构校验，都放后台。

        结构校验要调 7z（读头尾），对放在机械盘上的大分卷可能要一两秒，
        不能卡在界面线程里。
        """
        st = self.st
        st.update(path=path, set=None, probe=None, err="")

        def work():
            vs = S.scan(path)
            return vs, S.structure(vs)

        self.ctx.tasks.submit(
            self.id,
            fn=work,
            on_ok=lambda r: self._scanned(*r),
            on_err=self._failed,
        )

    def _scanned(self, vs, probe):
        self.st.update(set=vs, probe=probe)
        # 命名层面的问题（缺卷、大小不对）比 7z 的判断更具体，
        # 有它就优先用它；7z 的话留作后备。
        named = S.describe_problem(vs)
        if named:
            self.st["probe"] = (False, named)
        self.ctx.rebuild()

    def _failed(self, exc):
        self.st.update(set=None, probe=None, err=str(exc))
        self.ctx.rebuild()
        self.ctx.toast("这个文件处理不了", True)

    # ── 渲染 ──────────────────────────────────────────────
    def _render(self):
        W, F, s = self.ctx.widgets, self.ctx.fonts, self.ctx.s
        pal = self.ctx.pal
        for box in (self.advice, self.list_box, self.bar):
            for w in box.winfo_children():
                w.destroy()

        st = self.st
        if st["err"]:
            W.advice_row(self.advice, pal, "bad", "这个文件处理不了", "",
                         st["err"]).pack(fill="x")
            return

        vs = st["set"]
        if vs is None:
            tk.Label(self.advice, text="拖一卷进来，会先检查齐不齐。",
                     bg=pal["bg"], fg=pal["ink3"], font=F["ui_xs"],
                     anchor="w").pack(anchor="w")
            return

        probe_ok, probe_msg = st["probe"] or (True, "")
        complete = vs.complete and probe_ok

        # ── 结论 ──────────────────────────────────────
        if complete:
            W.advice_row(
                self.advice, pal, "ok",
                "%d 卷齐全，结构正确" % len(vs.volumes),
                "%s · %s" % (vs.kind.upper(), W.fmt_size(vs.total)),
                "卷号连续、每卷大小一致，归档头尾也定位到了。"
                "点下面的按钮再跑一次完整校验，然后才开始解压。",
            ).pack(fill="x")
        else:
            # 右上角那个数字要跟着问题走：缺卷就报 3/4，大小不对就点名第几卷。
            # 一律写「4 / 4 卷」会让人以为卷齐了就没事。
            if vs.missing:
                quant = "%d / %d 卷" % (len(vs.volumes), vs.count)
            elif vs.odd:
                quant = "第 %d 卷异常" % vs.odd[0].index
            else:
                quant = "%s · %s" % (vs.kind.upper(), W.fmt_size(vs.total))
            W.advice_row(
                self.advice, pal, "bad",
                "这个分卷包不完整，不能解压",
                quant,
                probe_msg or "分卷不完整。",
            ).pack(fill="x")

        self._draw_volumes(vs)
        self._draw_actions(vs, complete)

    def _draw_volumes(self, vs):
        """卷清单。缺的那一卷要占它本该在的位置，不能直接跳过 ——
        跳过的话用户看到的是「1、2、4」，还得自己数一下才知道少了 3。"""
        W, F, s = self.ctx.widgets, self.ctx.fonts, self.ctx.s
        pal = self.ctx.pal

        by_idx = {v.index: v for v in vs.volumes}
        hi = max(by_idx) if by_idx else 0
        if hi == 0:
            return

        card = tk.Frame(self.list_box, bg=pal["surface"],
                        highlightbackground=pal["line"], highlightthickness=1)
        card.pack(fill="x")

        head = tk.Frame(card, bg=pal["sunken"])
        head.pack(fill="x")
        tk.Label(head, text="分卷清单", bg=pal["sunken"], fg=pal["ink2"],
                 font=F["ui_sm"], anchor="w").pack(side="left", padx=s(12), pady=s(6))
        tk.Label(head, text="%d 卷 · %s" % (len(by_idx), W.fmt_size(vs.total)),
                 bg=pal["sunken"], fg=pal["ink3"], font=F["ui_xs"]).pack(
            side="right", padx=s(12))

        body = tk.Frame(card, bg=pal["surface"])
        body.pack(fill="x", padx=s(12), pady=(s(6), s(10)))

        # 卷特别多时只列前 40 行，免得一个 300 卷的包把界面撑成长条
        shown = 0
        for i in range(1, hi + 1):
            v = by_idx.get(i)
            if v is None:
                self._row(body, i, "（缺失）", "—", "需要重新下载", bad=True)
                shown += 1
                continue
            if shown >= 40:
                rest = hi - i + 1
                if rest > 0:
                    tk.Label(body, text="… 还有 %d 卷未列出" % rest,
                             bg=pal["surface"], fg=pal["ink3"], font=F["ui_xs"],
                             anchor="w").pack(anchor="w", pady=(s(2), 0))
                break
            if v in vs.odd:
                why = "大小不对（应为 %s）" % W.fmt_size(vs.mode)
                self._row(body, i, v.name, W.fmt_size(v.size), why, bad=True)
            elif v.size == 0:
                self._row(body, i, v.name, "0 B", "空文件", bad=True)
            else:
                self._row(body, i, v.name, W.fmt_size(v.size), "")
            shown += 1

    def _row(self, parent, index, name, size, note, bad=False):
        F, s = self.ctx.fonts, self.ctx.s
        pal = self.ctx.pal
        line = tk.Frame(parent, bg=pal["surface"])
        line.pack(fill="x", pady=s(1))

        tk.Label(line, text="#%d" % index, bg=pal["surface"],
                 fg=pal["bad_ink"] if bad else pal["ink3"],
                 font=F["ui_xs"], width=5, anchor="w").pack(side="left")

        tk.Label(line, text=short_name(name, 40), bg=pal["surface"],
                 fg=pal["bad_ink"] if bad else pal["ink2"],
                 font=F["ui_xs"], anchor="w").pack(side="left")

        if note:
            tk.Label(line, text=note, bg=pal["surface"], fg=pal["bad_ink"],
                     font=F["ui_xs"], anchor="e").pack(side="right")
        tk.Label(line, text=size, bg=pal["surface"], fg=pal["ink3"],
                 font=F["ui_xs"], width=10, anchor="e").pack(side="right",
                                                             padx=s(10))

    def _draw_actions(self, vs, complete):
        """按钮区。

        不完整的时候这里**不放按钮** —— 只放一句话。按这个项目一贯的规矩，
        点了必然失败的入口不该出现在界面上。
        """
        W, F, s = self.ctx.widgets, self.ctx.fonts, self.ctx.s
        pal = self.ctx.pal

        if not complete:
            tk.Label(self.bar,
                     text="把缺的卷补齐、或者重新下载有问题的那一卷，"
                          "放回同一个文件夹后再点一次。",
                     bg=pal["bg"], fg=pal["ink3"], font=F["ui_xs"],
                     anchor="w", justify="left",
                     wraplength=s(700)).pack(anchor="w")
            return

        self.ctx.btn(self.bar, "校验并解压", self.do_extract, primary=True).pack(
            side="left")

        self.ctx.btn(self.bar, "只做校验", self.do_check).pack(side="left",
                                                              padx=(8, 0))

        if vs.style == "single":
            tk.Label(self.bar, text="单个归档", bg=pal["bg"], fg=pal["ink3"],
                     font=F["ui_xs"]).pack(side="right")

    # ── 动作 ──────────────────────────────────────────────
    def do_extract(self):
        vs = self.st["set"]
        if vs is None or not vs.complete:
            return
        dest = self.ctx.ask_dir("解压到哪个文件夹")
        if not dest:
            return
        self._run(lambda: S.extract(vs, dest, verify_first=True),
                  "正在校验并解压，大分卷要几分钟…")

    def do_check(self):
        vs = self.st["set"]
        if vs is None:
            return
        self._run(lambda: S.verify(vs), "正在逐文件校验…")

    def _run(self, fn, busy_text):
        """把耗时动作丢到后台，转圈由 tasks 统一管。

        进度提示用 toast 说一句就够了：解压一个大分卷要几分钟，
        真正需要传达的只有「在干活，别以为卡死了」。
        """
        self.ctx.toast(busy_text)
        self.ctx.tasks.submit(
            self.id,
            fn=fn,
            on_ok=self._done,
            on_err=self._task_failed,
        )

    def _done(self, result):
        if isinstance(result, tuple):     # verify() 的返回
            ok, why = result
            if ok:
                self.ctx.toast("校验通过，所有文件都完好")
            else:
                self.ctx.toast("校验没通过", True)
                self.st["probe"] = (False, why)
                self.ctx.rebuild()
            return

        # extract() 返回的是输出目录
        self.ctx.toast("解压完成：%s" % Path(result).name)

    def _task_failed(self, exc):
        self.ctx.toast(str(exc).splitlines()[0], True)
        self.ctx.rebuild()
        # 详细原因单独弹一次 —— 缺哪一卷、哪个文件 CRC 坏了，
        # 这些信息必须让人看清楚，不能只留一句一闪而过的 toast
        self.ctx.alert("没有解压", str(exc))


PLUGIN = SplitPlugin()
