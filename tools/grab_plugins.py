# -*- coding: utf-8 -*-
"""临时工具：插件化改造后的界面验收 + 截图（不参与打包）。

    H:\\Python3.10.11\\python.exe tools\\grab_plugins.py

除了拍照，还要断言几件事：
  · 侧栏条目来自 plugin.json（不是硬编码）
  · unpack 是真插件：实例类型是 UnpackPlugin，状态在插件自己身上
  · 切走再切回来，插件实例复用、状态不丢
  · 停用插件后点进去看到的是原因页，不是白屏
"""
from __future__ import annotations

import io
import json
import shutil
import sys
import tempfile
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from core import seed  # noqa: E402
from ui.app import App  # noqa: E402

OUT = ROOT / "output"
OUT.mkdir(exist_ok=True)

OK, BAD = 0, 0


def check(label, cond, extra=""):
    global OK, BAD
    if cond:
        OK += 1
        print("  ✅ %s%s" % (label, ("  " + extra) if extra else ""))
    else:
        BAD += 1
        print("  ❌ %s%s" % (label, ("  " + extra) if extra else ""))


def pump(app, t=0.4, until=None, limit=30.0):
    end = time.time() + t
    while time.time() < end:
        app.update()
        time.sleep(0.03)
    if until is None:
        return
    stop = time.time() + limit
    while time.time() < stop:
        app.update()
        if until():
            return
        time.sleep(0.05)


def all_texts(w) -> list:
    """递归收集窗口里所有 Label 的文字 —— 用来断言「没有残字」。"""
    out = []
    for c in w.winfo_children():
        try:
            t = c.cget("text")
            if t:
                out.append(str(t))
        except Exception:  # noqa: BLE001
            pass
        out.extend(all_texts(c))
    return out


def rail_count(app) -> int:
    return len(app.rail.winfo_children()) if app.rail is not None else 0


def rail_is_tight(app) -> bool:
    """侧栏条目应当首尾相接、高度正常 —— 隐藏一项不能留下空位。"""
    if app.rail is None:
        return True
    app.update_idletasks()
    kids = app.rail.winfo_children()
    if not kids:
        return True
    prev_bottom = None
    for k in kids:
        if k.winfo_height() <= 1:
            return False
        if prev_bottom is not None:
            gap = k.winfo_y() - prev_bottom
            if gap < 0 or gap > 8:      # pack(pady=(0,6)) 的间距
                return False
        prev_bottom = k.winfo_y() + k.winfo_height()
    return True


def grab(app, name):
    app.update_idletasks()
    pump(app, 0.45)

    import ctypes
    from ctypes import wintypes as wt

    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    hwnd = int(app.wm_frame(), 16)
    rect = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    w, h = rect.right - rect.left, rect.bottom - rect.top

    hdc = user32.GetWindowDC(hwnd)
    mdc = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(mdc, bmp)
    user32.PrintWindow(hwnd, mdc, 2)

    class BMI(ctypes.Structure):
        _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
                    ("biPlanes", wt.WORD), ("biBitCount", wt.WORD),
                    ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
                    ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG),
                    ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD)]

    bi = BMI()
    bi.biSize = ctypes.sizeof(BMI)
    bi.biWidth, bi.biHeight = w, -h
    bi.biPlanes, bi.biBitCount = 1, 32
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bi), 0)
    Image.frombuffer("RGB", (w, h), buf, "raw", "BGRX", 0, 1).save(OUT / name, "PNG")

    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mdc)
    user32.ReleaseDC(hwnd, hdc)
    print("  📷 %s" % name)


def make_seed(tmp: Path) -> Path:
    """造一个真图种：PNG + 一个 zip 载荷。"""
    im = Image.new("RGB", (420, 300), (60, 70, 90))
    px = im.load()
    for y in range(300):
        for x in range(420):
            px[x, y] = (40 + x % 120, 60 + y % 100, 110)
    cover = tmp / "cover.png"
    im.save(cover)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("说明.txt", "这是插件回归测试用的载荷\n" * 40)
        z.writestr("子目录/示例.bin", bytes(range(256)) * 8)
    pay = tmp / "payload.zip"
    pay.write_bytes(buf.getvalue())

    out = tmp / "图种.png"
    seed.write(seed.pack(cover, pay), out)
    return out


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="cangtu_ui_"))
    app = None
    try:
        seed_p = make_seed(tmp)
        app = App()
        app.geometry("1425x1000+20+20")
        app.attributes("-topmost", True)
        app.lift()
        pump(app, 0.9)

        print("\n[1] 侧栏来自清单")
        metas = app.plugin_list()
        check("五个模块", len(metas) == 5, ", ".join(m.id for m in metas))
        check("顺序 seed→unpack→phantom→reveal→cut",
              [m.id for m in metas] == ["seed", "unpack", "phantom", "reveal", "cut"])
        check("全部通过依赖探测", all(m.ready for m in metas),
              ", ".join("%s=%s" % (m.id, m.why_not() or "ok") for m in metas))
        grab(app, "plugin_seed.png")

        print("\n[2] unpack 是真插件")
        app.tab = "unpack"
        app.build()
        pump(app, 0.6)
        inst = app.plugins.load("unpack")
        check("实例类型是插件类", type(inst).__name__ == "UnpackPlugin",
              type(inst).__name__)
        check("状态在插件自己身上", isinstance(inst.st, dict) and not hasattr(app, "st_un"))
        check("界面已挂上", hasattr(inst, "card") and inst.card.winfo_exists())

        inst.set_file(str(seed_p))
        pump(app, 0.3, until=lambda: inst.st["result"] is not None, limit=30)
        pump(app, 0.6)
        res = inst.st["result"]
        check("异步拆包完成", res is not None and res.has_payload)
        check("拆出 2 个文件", res is not None and len(res.entries) == 2,
              str(len(res.entries)) if res else "-")
        check("界面已按结果重建", inst.list_box.winfo_children() != [] and
              inst.card.winfo_exists())
        grab(app, "plugin_unpack.png")

        print("\n[3] 切走再切回，状态不丢")
        app.tab = "phantom"
        app.build()
        pump(app, 0.5)
        grab(app, "plugin_phantom.png")
        app.tab = "unpack"
        app.build()
        pump(app, 0.5)
        again = app.plugins.load("unpack")
        check("插件实例复用", again is inst)
        check("结果还在", inst.st["result"] is not None)
        check("重建后控件是新的一批", inst.card.winfo_exists())

        print("\n[4] 切主题")
        app.toggle_theme()
        pump(app, 0.6)
        check("浅色下 unpack 仍然在", app.plugins.load("unpack") is inst)
        app.tab = "unpack"
        app.build()
        pump(app, 0.4)
        grab(app, "plugin_unpack_light.png")
        app.toggle_theme()
        pump(app, 0.4)

        print("\n[5] 停用 → 入口整体消失")
        app.plugins.set_enabled("unpack", False)
        app.tab = "unpack"
        app.build()
        pump(app, 0.6)
        ids = [m.id for m in app.plugin_list()]
        check("侧栏里没有 unpack 了", "unpack" not in ids, str(ids))
        check("当前模块自动落到第一个可用的", app.tab == ids[0], app.tab)
        check("侧栏条目数 = 可用模块数", rail_count(app) == len(ids),
              "%d vs %d" % (rail_count(app), len(ids)))
        check("侧栏无空隙、无零高条目", rail_is_tight(app))
        texts = all_texts(app)
        check("界面上没有「停用」字样", not any("停用" in t for t in texts),
              " | ".join(t for t in texts if "停用" in t)[:60])
        check("界面上没有「不可用 / 用不了 / 暂不」字样",
              not any(("不可用" in t or "用不了" in t or "暂不" in t) for t in texts))
        check("界面上没有 unpack 的任何残字",
              not any(("解包" in t) for t in texts))
        grab(app, "plugin_hidden_disabled.png")
        app.plugins.set_enabled("unpack", True)
        app.plugins.save_manifest()

        print("\n[5b] 未安装 → 入口整体消失")
        pj = Path(app.plugins.meta("unpack").dir) / "plugin.json"
        bak = pj.read_bytes()
        try:
            pj.unlink()                      # 拿掉清单 = 等效于没装
            app.plugins.discover()
            app.tab = "unpack"
            app.build()
            pump(app, 0.6)
            ids = [m.id for m in app.plugin_list()]
            check("unpack 从侧栏消失", "unpack" not in ids, str(ids))
            check("当前模块落到可用的那个", app.tab in ids, app.tab)
            check("侧栏条目数 = 可用模块数", rail_count(app) == len(ids),
                  "%d vs %d" % (rail_count(app), len(ids)))
            check("侧栏无空隙", rail_is_tight(app))
            texts = all_texts(app)
            check("没有留下任何提示文案",
                  not any(("解包" in t or "未安装" in t or "缺少" in t) for t in texts),
                  " | ".join(t for t in texts)[:60])
            grab(app, "plugin_hidden_missing.png")
        finally:
            pj.write_bytes(bak)
            app.plugins.discover()
            app.tab = "unpack"
            app.build()
            pump(app, 0.5)
        check("装回来之后立刻可用", "unpack" in [m.id for m in app.plugin_list()])
        check("装回来之后界面正常", hasattr(app.plugins.load("unpack"), "card"))

        print("\n[5c] 缺依赖 → 入口整体消失")
        cj = Path(app.plugins.meta("cut").dir) / "plugin.json"
        cbak = cj.read_bytes()
        try:
            meta = json.loads(cbak.decode("utf-8"))
            meta["probe"] = ["definitely_missing_module_xyz"]
            cj.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
            app.plugins.discover()
            app.tab = "cut"
            app.build()
            pump(app, 0.6)
            ids = [m.id for m in app.plugin_list()]
            check("cut 从侧栏消失", "cut" not in ids, str(ids))
            check("当前模块落到可用的那个", app.tab in ids, app.tab)
            check("侧栏条目数 = 可用模块数", rail_count(app) == len(ids))
            texts = all_texts(app)
            check("没有「缺少 / 不可用」文案",
                  not any(("缺少" in t or "不可用" in t or "抠图" in t) for t in texts))
            grab(app, "plugin_hidden_dep.png")
        finally:
            cj.write_bytes(cbak)
            app.plugins.discover()
            app.tab = "cut"
            app.build()
            pump(app, 0.5)
        check("依赖恢复后 cut 回来了", "cut" in [m.id for m in app.plugin_list()])

        print("\n[5d] 全部停用 → 空态页，且不留下空侧栏")
        for m in app.plugins.metas():
            app.plugins.set_enabled(m.id, False)
        app.build()
        pump(app, 0.6)
        check("侧栏整条不画", app.rail is None)
        texts = all_texts(app)
        check("显示空态说明", any("没有可用的模块" in t for t in texts),
              " | ".join(texts)[:60])
        check("空态里没有「停用 / 不可用」字样",
              not any(("停用" in t or "不可用" in t) for t in texts))
        grab(app, "plugin_empty.png")
        for m in app.plugins.metas():
            app.plugins.set_enabled(m.id, True)
        app.plugins.save_manifest()
        app.tab = "seed"
        app.build()
        pump(app, 0.5)
        check("恢复后侧栏回来", rail_count(app) == len(app.plugin_list()))

        print("\n[6] 加载失败 → 重试页")
        # 把 unpack 的入口临时改坏，验证「加载失败」这条路
        entry = Path(app.plugins.meta("unpack").dir) / "plugin.py"
        bak = entry.read_bytes()
        try:
            entry.write_text("raise ImportError('模拟缺少依赖')\n", encoding="utf-8")
            app.plugins.unload("unpack")
            app.tab = "unpack"
            app.build()
            pump(app, 0.6)
            page = app.stage.winfo_children()[0]
            labels = []
            for w in page.winfo_children():
                try:
                    labels.append(str(w.cget("text")))
                except Exception:  # noqa: BLE001
                    pass
            check("显示加载失败页", any("加载失败" in t for t in labels),
                  " | ".join(labels)[:70])
            check("错误写进了 plugin.log",
                  (ROOT / "logs" / "plugin.log").exists())
            grab(app, "plugin_error.png")
        finally:
            entry.write_bytes(bak)
            app.plugins.unload("unpack")
            app.tab = "seed"
            app.build()
            pump(app, 0.5)

        print("\n[7] 所有可见模块都能挂载")
        ids = [m.id for m in app.plugin_list()]
        check("五个模块都可见", ids == ["seed", "unpack", "phantom", "reveal", "cut"],
              str(ids))
        for pid in ids:
            app.tab = pid
            app.build()
            pump(app, 0.7, until=lambda: not app.tasks.is_busy(pid), limit=20)
            alive = bool(app.stage.winfo_children())
            check("%s 挂载成功" % pid, alive)
        grab(app, "plugin_cut.png")
    finally:
        if app is not None:
            app.destroy()
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n=== %d 通过，%d 失败 ===" % (OK, BAD))
    return 1 if BAD else 0


if __name__ == "__main__":
    sys.exit(main())
