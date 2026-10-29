# -*- coding: utf-8 -*-
"""抓取「藏图盒」窗口本体（即使用户没把它切到前台）。

用 PrintWindow + PW_RENDERFULLCONTENT，Tk 窗口能正常离屏渲染。
"""
from __future__ import annotations

import ctypes
import subprocess
import sys
import time
from ctypes import wintypes as wt

from PIL import Image

EXE = r"D:\_改名验证\藏图盒-v1.0.0-win64\藏图盒.exe"
TITLE = "藏图盒"

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32


def find_window(title: str, timeout: float = 20.0):
    end = time.time() + timeout
    while time.time() < end:
        hwnd = user32.FindWindowW(None, title)
        if hwnd:
            return hwnd
        time.sleep(0.3)
    return 0


def capture(hwnd, out_path: str) -> tuple:
    rect = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    w = rect.right - rect.left
    h = rect.bottom - rect.top
    if w <= 0 or h <= 0:
        raise RuntimeError("窗口尺寸异常: %dx%d" % (w, h))

    hdc = user32.GetWindowDC(hwnd)
    mdc = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(mdc, bmp)

    ok = user32.PrintWindow(hwnd, mdc, 2)  # PW_RENDERFULLCONTENT

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
            ("biPlanes", wt.WORD), ("biBitCount", wt.WORD),
            ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
            ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG),
            ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD),
        ]

    bi = BITMAPINFOHEADER()
    bi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bi.biWidth = w
    bi.biHeight = -h          # 负数 = 自上而下
    bi.biPlanes = 1
    bi.biBitCount = 32
    bi.biCompression = 0

    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bi), 0)

    im = Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1).convert("RGB")
    im.save(out_path, "PNG")

    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mdc)
    user32.ReleaseDC(hwnd, hdc)
    return im.size, ok


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "window.png"
    proc = subprocess.Popen([EXE])
    try:
        hwnd = find_window(TITLE)
        if not hwnd:
            print("找不到窗口")
            return 1
        time.sleep(1.5)
        size, ok = capture(hwnd, out)
        print("saved", out, size, "PrintWindow=", ok)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:  # noqa: BLE001
            proc.kill()
    return 0


if __name__ == "__main__":
    sys.exit(main())
