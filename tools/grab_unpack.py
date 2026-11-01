# -*- coding: utf-8 -*-
"""临时工具：给「图种解包」模块截图验收（不参与打包）。"""
from __future__ import annotations

import io
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageGrab  # noqa: E402

from core import seed  # noqa: E402
from ui.app import App  # noqa: E402

OUT = ROOT / "output"
OUT.mkdir(exist_ok=True)


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
    im = ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True)
    im.save(OUT / name, "PNG")
    print("saved", name, im.size)


def make_seed():
    """造一张带种子的图种。"""
    cover = OUT / "解包封面.png"
    im = Image.new("RGB", (960, 540))
    px = im.load()
    for y in range(540):
        for x in range(960):
            px[x, y] = (24 + x * 60 // 960, 30 + y * 90 // 540, 60 + (x + y) * 80 // 1500)
    im.save(cover, "PNG")

    def bs(s: str) -> bytes:
        raw = s.encode("utf-8")
        return str(len(raw)).encode() + b":" + raw

    info = (b"d6:lengthi8589934592e4:name" + bs("荒野猎人 4K 双语字幕")
            + b"12:piece lengthi524288e6:pieces20:" + b"A" * 20 + b"e")
    url = b"http://tr.bangumi.tv/announce"
    tor = b"d8:announce" + str(len(url)).encode() + b":" + url + b"4:info" + info + b"e"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("荒野猎人 4K 双语字幕.torrent", tor)
        z.writestr("声明.txt", "仅供学习交流，请于 24 小时内删除。".encode("utf-8"))
    pay = OUT / "解包载荷.zip"
    pay.write_bytes(buf.getvalue())

    res = seed.pack(cover, pay)
    out = OUT / "样例_图种.png"
    seed.write(res, out)
    print("图种:", out, len(res.data), "字节")
    return out, cover


def main():
    seed_p, cover = make_seed()
    plain = OUT / "解包_普通图.png"
    Image.open(cover).save(plain, "PNG")

    app = App()
    app.geometry("1425x1000+30+20")
    app.attributes("-topmost", True)
    app.lift()
    pump(app, 0.8)

    app.tab = "unpack"
    app.build()
    pump(app, 0.6)
    grab(app, "live_un_empty.png")

    app.un_set(str(seed_p))
    pump(app, 0.9)
    grab(app, "live_un_seed.png")

    app.un_set(str(plain))
    pump(app, 0.7)
    grab(app, "live_un_plain.png")

    # 深色 / 浅色各来一张
    if app.theme == "dark":
        app.toggle_theme()
        app.tab = "unpack"
        app.un_set(str(seed_p))
        pump(app, 0.9)
        grab(app, "live_un_seed_light.png")
        app.toggle_theme()
    else:
        app.toggle_theme()
        app.tab = "unpack"
        app.un_set(str(seed_p))
        pump(app, 0.9)
        grab(app, "live_un_seed_dark.png")
        app.toggle_theme()

    app.destroy()


if __name__ == "__main__":
    main()
