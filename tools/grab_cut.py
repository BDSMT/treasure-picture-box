# -*- coding: utf-8 -*-
"""临时工具：给「抠图」模块截图验收（不参与打包）。"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import ImageGrab  # noqa: E402

from ui.app import App  # noqa: E402

OUT = ROOT / "output"
OUT.mkdir(exist_ok=True)

SAMPLES = [
    r"E:\zancun\bili\1761730944350.jpeg",   # 复杂背景（和服）
    r"E:\zancun\bili\1736062005880.jpg",    # 海景背景（泳装）
    r"E:\zancun\bili\1761528493439.png",    # 纯色底（白衣）
]


def pump(app, t=0.6, until=None, limit=40.0):
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


def grab(app, name):
    """直接向窗口要画好的内容（PrintWindow），不依赖屏幕可见。"""
    app.update_idletasks()
    pump(app, 0.5)

    import ctypes
    from ctypes import wintypes as wt

    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32

    hwnd = int(app.wm_frame(), 16)
    rect = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    w, h = rect.right - rect.left, rect.bottom - rect.top

    hdc = user32.GetWindowDC(hwnd)
    mdc = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(mdc, bmp)
    user32.PrintWindow(hwnd, mdc, 2)          # PW_RENDERFULLCONTENT

    class BMI(ctypes.Structure):
        _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
                    ("biPlanes", wt.WORD), ("biBitCount", wt.WORD),
                    ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
                    ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG),
                    ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD)]

    bi = BMI()
    bi.biSize = ctypes.sizeof(BMI)
    bi.biWidth = w
    bi.biHeight = -h                          # 负高度 = 自上而下
    bi.biPlanes = 1
    bi.biBitCount = 32
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bi), 0)

    from PIL import Image
    im = Image.frombuffer("RGB", (w, h), buf, "raw", "BGRX", 0, 1)
    im.save(OUT / name, "PNG")

    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mdc)
    user32.ReleaseDC(hwnd, hdc)
    print("saved", name, im.size)


def main():
    app = App()
    app.geometry("1425x1000+30+20")
    app.attributes("-topmost", True)
    app.lift()
    pump(app, 0.8)

    app.tab = "cut"
    app.build()
    pump(app, 0.8)

    grab(app, "cut_empty.png")

    for i, src in enumerate(SAMPLES):
        app.cu_set(src)
        pump(app, 0.4, until=lambda: getattr(app, "_cu_res", None) is not None, limit=60)
        pump(app, 1.2)
        grab(app, "cut_%d.png" % i)
        print("  样本 %d: %s" % (i, Path(src).name))

    # 切到浅色主题再拍一张
    if app.theme == "dark":
        app.toggle_theme()
    app.tab = "cut"
    app.build()
    pump(app, 0.8)
    if app.st_cu["path"]:
        pump(app, 0.4, until=lambda: getattr(app, "_cu_res", None) is not None, limit=60)
        pump(app, 1.0)
    grab(app, "cut_light.png")

    app.destroy()
    print("done")


if __name__ == "__main__":
    main()
