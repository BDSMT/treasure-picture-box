# -*- coding: utf-8 -*-
"""临时工具：给图种模块的两种载荷状态各截一张图。"""
from __future__ import annotations

import io
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

from PIL import ImageGrab  # noqa: E402

from core import seed  # noqa: E402
from ui.app import App  # noqa: E402

OUT = ROOT / "output"
OUT.mkdir(exist_ok=True)
COVER = Path.home() / "Desktop" / "331223d53564912f362ac7e947797a8a.jpg"


def pump(app, t=0.6):
    end = time.time() + t
    while time.time() < end:
        app.update()
        time.sleep(0.03)


def grab(app, name):
    app.update_idletasks()
    pump(app, 0.45)
    x, y = app.winfo_rootx(), app.winfo_rooty()
    w, h = app.winfo_width(), app.winfo_height()
    sc = app.winfo_fpixels("1i") / 96.0
    box = (int(x * sc), int(y * sc), int((x + w) * sc), int((y + h) * sc))
    im = ImageGrab.grab(bbox=box, all_screens=True)
    im.save(OUT / name, "PNG")
    print("saved", name, im.size)


def main():
    good = OUT / "载荷_好.zip"
    with zipfile.ZipFile(good, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("资料/说明.txt", "内容" * 3000)
        z.writestr("设计稿.png", b"x" * 40000)
        z.writestr("存档/进度.bin", b"y" * 120000)

    bad = OUT / "载荷_坏.pcap"
    bad.write_bytes(b"\xd4\xc3\xb2\xa1" + b"\x00" * 90000)

    app = App()
    pump(app, 0.5)
    app.tab = "seed"
    app.st_seed.update(cover=None, pay=None, result=None, extra=0,
                       kind="", end=0, pay_kind="")
    app.build()
    pump(app, 0.3)

    app.seed_set_cover(str(COVER))
    pump(app, 0.4)

    # 场景 1：zip 载荷（正常）
    app.seed_set_pay(str(good))
    pump(app, 0.5)
    app.st_seed["result"] = seed.pack(app.st_seed["cover"], str(good))
    app._seed_render_info()
    pump(app, 0.5)
    grab(app, "seed_zip.png")

    # 场景 2：非 zip 载荷（应当给出警告）
    app.seed_set_pay(str(bad))
    pump(app, 0.5)
    app.st_seed["result"] = seed.pack(app.st_seed["cover"], str(bad))
    app._seed_render_info()
    pump(app, 0.5)
    grab(app, "seed_bad.png")

    app.destroy()


if __name__ == "__main__":
    main()
