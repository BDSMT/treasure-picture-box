# -*- coding: utf-8 -*-
"""临时工具：用真实图片走完整流程并截图（不参与打包）。"""
from __future__ import annotations

import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

from PIL import ImageGrab  # noqa: E402

from core import phantom  # noqa: E402
from core.imageio import open_rgba, save_png  # noqa: E402
from ui.app import App  # noqa: E402

OUT = ROOT / "output"
OUT.mkdir(exist_ok=True)

# 演示素材本地目录（不进 git，示例输入自行准备）。
# 自己截图时把「前」放前景、「后」放背景即可：
DEMO = Path("E:/zancun/bili/演示")
FG = DEMO / "前" / "1765797758933.png"
BG = DEMO / "后" / "1765414702368.png"


def pump(app, t=0.5):
    end = time.time() + t
    while time.time() < end:
        app.update()
        time.sleep(0.03)


def grab(app, name):
    app.update_idletasks()
    pump(app, 0.45)
    x, y = app.winfo_rootx(), app.winfo_rooty()
    w, h = app.winfo_width(), app.winfo_height()
    # DPI 感知进程里 winfo_* 已经是物理像素，不能再乘缩放比
    im = ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True)
    im.save(OUT / name, "PNG")
    print("saved", name, im.size)


def main():
    print("前景:", FG.exists(), FG)
    print("背景:", BG.exists(), BG)

    app = App()
    app.geometry("1425x1120+40+20")
    app.attributes("-topmost", True)
    app.lift()
    pump(app, 0.8)

    # 1) 图种
    app.tab = "seed"
    app.geometry("1425x800")
    app.st_seed.update(cover=None, pay=None)
    app.build()
    # 用一张干净的封面（不带尾部数据），避免宣传图里出现警告条
    cover = OUT / "样例_幻影.png"
    if not cover.exists():
        cover = FG
    app.seed_set_cover(str(cover))
    pay = OUT / "样例载荷.zip"
    with zipfile.ZipFile(pay, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("资料/说明.txt", "图种可以藏任何文件\n" * 200)
        z.writestr("存档/进度.bin", b"x" * 60000)
    app.seed_set_pay(str(pay))
    pump(app, 0.8)
    grab(app, "live_seed.png")

    # 2) 幻影坦克
    app.tab = "phantom"
    app.geometry("1425x1120")
    app.build()
    app.st_pt.update(fg=str(FG), bg=str(BG), result=None)
    app.build()
    app._pt_recompute()
    pump(app, 1.2)
    grab(app, "live_pt.png")

    # 3) 真的合成一张，再拿去提取
    res = phantom.compose(open_rgba(str(FG)), open_rgba(str(BG)),
                          bright=0.55, boost=False, max_side=1400)
    png = OUT / "样例_幻影.png"
    save_png(res.image, png)
    print("样例幻影图:", png, png.stat().st_size, "字节  支撑度=%.3f" % res.stat.support)

    app.tab = "reveal"
    app.geometry("1425x910")
    app.build()
    app.st_ex["path"] = str(png)
    app.build()
    app._ex_recompute()
    pump(app, 1.2)
    grab(app, "live_ex.png")

    app.destroy()


if __name__ == "__main__":
    main()
