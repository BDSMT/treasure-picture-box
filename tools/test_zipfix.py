# -*- coding: utf-8 -*-
"""验证 zipfix：修补后 7-Zip 能开、拆分还原后也能开、重复修补不叠加。"""
from __future__ import annotations

import io
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

from core import zipfix  # noqa: E402

SEVENZ = Path(r"D:/livehime/7.54.0.10521/7z.exe")
OUT = ROOT / "output" / "compat"
OUT.mkdir(parents=True, exist_ok=True)


def make_zip(n=3) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for i in range(n):
            z.writestr("文件%d.txt" % i, ("内容 %d\n" % i).encode() * 200)
        z.writestr("子目录/深层.txt", b"deep" * 100)
        z.writestr("无压缩.txt", b"stored" * 10, zipfile.ZIP_STORED)
    return buf.getvalue()


def check(name: str, data: bytes) -> bool:
    f = OUT / ("z_%s.zip" % name)
    f.write_bytes(data)
    lay = zipfix.describe(data)
    r = subprocess.run([str(SEVENZ), "l", "-ba", str(f)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    items = [l for l in (r.stdout or "").splitlines() if l.strip()]
    ok7 = r.returncode == 0 and len(items) > 0
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            okpy = z.testzip() is None and len(z.namelist()) > 0
            n = len(z.namelist())
    except Exception:  # noqa: BLE001
        okpy, n = False, 0
    print("  %-24s 7z=%-4s py=%-4s 条目=%-2d 偏差=%+d"
          % (name, "✅" if ok7 else "❌", "✅" if okpy else "❌",
             n, lay.get("dev", 0)))
    return ok7 and okpy


def main():
    z = make_zip()
    prefix = b"\xff\xd8\xff\xe0" + b"JPEGDATA" * 3000      # 模拟 27KB 图片
    full = prefix + z

    print("\n[1] 修补前（旧做法）")
    check("1_原始未修补", full)

    print("\n[2] 修补后")
    fixed, changed = zipfix.fix_prefix(full, len(prefix))
    print("     是否改动:", changed)
    ok2 = check("2_修补后", fixed)

    print("\n[3] 幂等：对已修补的再修一次")
    again, ch2 = zipfix.fix_prefix(fixed, 0)
    print("     是否改动:", ch2, "（应为 False）")
    same = again == fixed
    print("     字节一致:", same)

    print("\n[4] 拆分还原（模拟工具的反向逻辑）")
    tail = fixed[len(prefix):]
    back, ch3 = zipfix.unfix_prefix(tail)
    print("     是否改动:", ch3, "（应为 True）")
    ok4 = check("4_拆分还原", back)
    print("     与原始载荷字节一致:", back == z)

    print("\n[5] 未修补的老图种拆分（不应被二次改动）")
    old_back, ch4 = zipfix.unfix_prefix(z)
    print("     是否改动:", ch4, "（应为 False）", " 字节一致:", old_back == z)

    print("\n结果:", "全部通过" if (ok2 and ok4 and same and back == z) else "有问题")


if __name__ == "__main__":
    main()
