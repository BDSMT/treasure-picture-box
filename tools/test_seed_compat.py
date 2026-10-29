# -*- coding: utf-8 -*-
"""图种兼容性诊断：生成后模拟「改后缀 → 用解压软件打开」的真实路径。"""
from __future__ import annotations

import io
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

from core import seed, sniff  # noqa: E402

SEVENZ = Path(r"D:/livehime/7.54.0.10521/7z.exe")
OUT = ROOT / "output" / "compat"
OUT.mkdir(parents=True, exist_ok=True)

DESK = Path.home() / "Desktop"
JPG = DESK / "331223d53564912f362ac7e947797a8a.jpg"
PNG = DESK / "1761844906126_幻影.png"


def make_zip(path: Path, n: int = 3) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for i in range(n):
            z.writestr("说明%d.txt" % i, ("这是第 %d 个测试文件。\n" % i).encode("utf-8") * 40)
        z.writestr("子目录/深层.txt", b"deep file" * 30)
    return path


def show(path: Path, label: str):
    raw = path.read_bytes()
    info = sniff.sniff(raw)
    print("\n【%s】%s" % (label, path.name))
    print("   文件大小      : %d 字节" % len(raw))
    print("   识别格式      : %s" % info.kind)
    print("   图片结束偏移  : %s" % info.end_offset)
    print("   尾部剩余      : %d 字节" % (len(raw) - (info.end_offset or 0)))
    if info.end_offset:
        h = raw[info.end_offset:info.end_offset + 8]
        print("   尾部前 8 字节 : %s" % h.hex(" "))

    # 1) Python zipfile（多数脚本/后端的行为）
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            bad = z.testzip()
            print("   [zipfile]     ✅ 能打开 %d 项，坏文件=%s" % (len(names), bad))
    except Exception as e:  # noqa: BLE001
        print("   [zipfile]     ❌ %s: %s" % (type(e).__name__, e))

    # 2) 7-Zip 测试压缩包完整性
    if SEVENZ.exists():
        r = subprocess.run([str(SEVENZ), "t", str(path)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        tail = [l for l in (r.stdout or "").splitlines() if l.strip()][-3:]
        print("   [7z t]        %s %s" % ("✅" if r.returncode == 0 else "❌ rc=%d" % r.returncode,
                                         " | ".join(tail)))
        r2 = subprocess.run([str(SEVENZ), "l", "-ba", str(path)],
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
        n_items = len([l for l in (r2.stdout or "").splitlines() if l.strip()])
        print("   [7z l]        %s 列出 %d 行" % ("✅" if r2.returncode == 0 else "❌", n_items))


def main():
    if not JPG.exists():
        print("缺少 JPEG 样本:", JPG)
        return

    # 造载荷
    base_zip = make_zip(OUT / "payload.zip")
    print("载荷 zip: %d 字节" % base_zip.stat().st_size)

    covers = [("JPEG 封面", JPG)]
    if PNG.exists():
        covers.insert(0, ("PNG 封面", PNG))

    for label, cover in covers:
        res = seed.pack(cover, base_zip)
        outname = (OUT / ("%s_改后缀.zip" % label.replace(" ", "_"))).resolve()
        seed.write(res, outname)
        print("\n" + "=" * 66)
        print("生成: %s  封面 %d + 载荷 %d = %d" %
              (outname.name, res.cover_len, res.payload_len, len(res.data)))
        # 关键：确认拼接处正是载荷开头
        off = res.cover_len
        print("拼接处字节: %s  (期望 50 4b 03 04)" % res.data[off:off + 8].hex(" "))
        show(outname, label)

        # 3) 拆回来验证（工具自己的反向逻辑）
        sp = seed.split(outname)
        print("   [工具拆分]    %s 字节 / 尾部 %d 字节 (%s) 与载荷一致=%s"
              % (sp.kind, len(sp.tail), sp.tail_ext,
                 sp.tail == base_zip.read_bytes()))


if __name__ == "__main__":
    main()
