# -*- coding: utf-8 -*-
"""临时工具：把界面截下来，供人工检查排版（不参与打包）。"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

from PIL import ImageGrab  # noqa: E402

from ui.app import App  # noqa: E402

OUT = ROOT / "output"
OUT.mkdir(exist_ok=True)


def grab(app, name):
    app.update_idletasks()
    app.update()
    time.sleep(0.12)
    app.update()
    x, y = app.winfo_rootx(), app.winfo_rooty()
    w, h = app.winfo_width(), app.winfo_height()

    # 程序里已经开了 DPI 感知，winfo 坐标就是物理像素，直接裁即可
    box = (x, y, x + w, y + h)

    im = ImageGrab.grab(bbox=box, all_screens=True)
    im.save(OUT / name, "PNG")
    print("saved", name, im.size)


def main():
    app = App()
    app.update()
    time.sleep(0.3)

    for tab, name in (("seed", "shot_seed.png"), ("phantom", "shot_pt.png"),
                      ("reveal", "shot_ex.png")):
        app.tab = tab
        app.build()
        app.update()
        time.sleep(0.35)
        grab(app, name)

    app.destroy()


if __name__ == "__main__":
    main()
