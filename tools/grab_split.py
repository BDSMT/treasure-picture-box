# -*- coding: utf-8 -*-
"""分卷解压的界面验收 + 截图（不参与打包）。

    H:\\Python3.10.11\\python.exe tools\\grab_split.py

断言的重点不是「有没有画出来」，而是「不该出现的东西有没有出现」：
分卷不完整时，界面里不能有任何解压入口，也不能有「已停用」这类残字。
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import time
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from core import splitvol as S  # noqa: E402
from ui.app import App  # noqa: E402

OUT = ROOT / "output"
OUT.mkdir(exist_ok=True)

OK, BAD = 0, 0


def check(label, cond, extra=""):
    global OK, BAD
    extra = str(extra)
    if cond:
        OK += 1
        print("  ✅ %s%s" % (label, ("  " + extra) if extra else ""))
    else:
        BAD += 1
        print("  ❌ %s%s" % (label, ("  " + extra) if extra else ""))


def pump(app, t=0.4, until=None, limit=40.0):
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


def make_vols(work: Path, name="pack.7z", mb=3) -> None:
    """造一套 4 卷的 7z 分卷。"""
    work.mkdir(parents=True, exist_ok=True)
    (work / "readme.txt").write_bytes(b"cangtu split test\n" * 200)
    (work / "blob.bin").write_bytes(os.urandom(mb * 1024 * 1024))
    subprocess.run(
        [str(S.exe()), "a", "-t7z", "-v1m", "-mx1", name, "readme.txt", "blob.bin"],
        cwd=str(work), capture_output=True, creationflags=S.CREATE_NO_WINDOW)


def open_tab(app, path):
    inst = app.plugins.load("split")
    inst.set_file(str(path))
    pump(app, 0.4, until=lambda: inst.st["set"] is not None or inst.st["err"],
         limit=40)
    pump(app, 0.5)
    return inst


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="cangtu_split_ui_"))
    app = None
    try:
        app = App()
        app.geometry("1425x1000+20+20")
        app.attributes("-topmost", True)
        app.lift()
        pump(app, 0.9)

        print("\n[1] 侧栏里多了「分卷解压」")
        ids = [m.id for m in app.plugin_list()]
        check("split 已注册", "split" in ids, ", ".join(ids))
        check("排在最后（order 60）", ids[-1] == "split", ids[-1])
        check("依赖探测通过", all(m.ready for m in app.plugin_list()),
              ", ".join("%s=%s" % (m.id, m.why_not() or "ok")
                        for m in app.plugin_list()))

        print("\n[2] 完整分卷")
        w_ok = tmp / "ok"
        make_vols(w_ok)
        app.tab = "split"
        app.build()
        pump(app, 0.6)
        inst = open_tab(app, w_ok / "pack.7z.001")
        check("扫描完成", inst.st["set"] is not None, inst.st["err"])
        vs = inst.st["set"]
        want = len(list(w_ok.glob("pack.7z.*")))
        check("找齐全部 %d 卷" % want,
              vs is not None and len(vs.volumes) == want,
              len(vs.volumes) if vs else "-")
        texts = all_texts(app.stage)
        check("结论是「齐全」", any("齐全" in t for t in texts),
              [t for t in texts if "齐全" in t][:1])
        check("解压按钮出现", any("校验并解压" in t for t in texts))
        check("清单列出了卷名", any("pack.7z.001" in t for t in texts))
        check("没有「不能解压」字样", not any("不能解压" in t for t in texts))
        grab(app, "split_ok.png")

        print("\n[3] 缺一卷")
        w_miss = tmp / "miss"
        shutil.copytree(w_ok, w_miss)
        (w_miss / "pack.7z.003").unlink()
        app.tab = "split"
        app.build()
        pump(app, 0.5)
        inst = open_tab(app, w_miss / "pack.7z.001")
        texts = all_texts(app.stage)
        check("结论是「不能解压」", any("不能解压" in t for t in texts))
        check("**没有**解压按钮", not any("校验并解压" in t for t in texts),
              [t for t in texts if "解压" in t][:3])
        check("**没有**「只做校验」按钮", not any("只做校验" in t for t in texts))
        check("点明了缺第 3 卷", any("#3" in t for t in texts) and
              any("缺失" in t for t in texts))
        check("告诉用户要重新下载", any("重新下载" in t or "补齐" in t for t in texts))
        check("没有「已停用」这类残字",
              not any("停用" in t or "禁用" in t for t in texts))
        grab(app, "split_missing.png")

        print("\n[4] 中间卷只下了一半")
        w_short = tmp / "short"
        shutil.copytree(w_ok, w_short)
        p2 = w_short / "pack.7z.002"
        raw = p2.read_bytes()
        p2.write_bytes(raw[:len(raw) // 2])
        app.tab = "split"
        app.build()
        pump(app, 0.5)
        inst = open_tab(app, w_short / "pack.7z.001")
        texts = all_texts(app.stage)
        check("指出大小不对", any("大小不对" in t for t in texts),
              [t for t in texts if "大小不对" in t][:1])
        check("**没有**解压按钮", not any("校验并解压" in t for t in texts))
        grab(app, "split_short.png")

        print("\n[5] 拖入最后一卷也能找齐")
        app.tab = "split"
        app.build()
        pump(app, 0.5)
        inst = open_tab(app, w_ok / "pack.7z.004")
        vs = inst.st["set"]
        check("从最后一卷反推出整套",
              vs is not None and len(vs.volumes) == len(list(w_ok.glob("pack.7z.*"))),
              len(vs.volumes) if vs else "-")
        texts = all_texts(app.stage)
        check("仍然是「齐全」", any("齐全" in t for t in texts))

        print("\n[6] 完全不是压缩包")
        junk = tmp / "note.txt"
        junk.write_text("hello", encoding="utf-8")
        app.tab = "split"
        app.build()
        pump(app, 0.5)
        inst = open_tab(app, junk)
        texts = all_texts(app.stage)
        check("给出「处理不了」", any("处理不了" in t for t in texts),
              [t for t in texts if "处理不了" in t][:1])
        check("**没有**解压按钮", not any("校验并解压" in t for t in texts))
        grab(app, "split_bad.png")

        print("\n[7] 解压真的能跑通")
        app.tab = "split"
        app.build()
        pump(app, 0.5)
        inst = open_tab(app, w_ok / "pack.7z.001")
        dest = tmp / "dest"
        dest.mkdir()
        out = S.extract(inst.st["set"], dest)
        check("解出目录", out.is_dir(), out.name)
        check("两个文件都在", len(list(out.iterdir())) == 2,
              len(list(out.iterdir())))

    finally:
        if app is not None:
            app.destroy()
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n=== %d 通过，%d 失败 ===" % (OK, BAD))
    return 1 if BAD else 0


if __name__ == "__main__":
    sys.exit(main())
