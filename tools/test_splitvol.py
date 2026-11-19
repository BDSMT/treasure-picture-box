# -*- coding: utf-8 -*-
"""分卷解压的自动化验收。

造样本 → 故意弄坏 → 断言检测结果。跑法：

    python tools/test_splitvol.py

每个用例都自己造数据，跑完删干净，不依赖任何外部文件。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import splitvol as S  # noqa: E402

PASS = 0
FAIL = 0


def check(name, cond, detail="") -> bool:
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ✅ %s%s" % (name, ("  ← " + str(detail)) if detail else ""))
        return True
    FAIL += 1
    print("  ❌ %s%s" % (name, ("  ← " + str(detail)) if detail else ""))
    return False


def seven(args, cwd) -> int:
    exe = S.exe()
    out = subprocess.run([str(exe)] + args, cwd=str(cwd),
                         capture_output=True, creationflags=S.CREATE_NO_WINDOW)
    return out.returncode


def make_archive(work: Path, kind: str, name: str, vol: str = "1m") -> None:
    """造一个分卷归档：一个文本 + 一个 3MB 随机块，压成 1MB 一卷。"""
    (work / "readme.txt").write_bytes(b"split volume test payload\n" * 300)
    (work / "blob.bin").write_bytes(os.urandom(3 * 1024 * 1024))
    args = ["a", "-t" + kind, "-v" + vol, "-mx1", name, "readme.txt", "blob.bin"]
    code = seven(args, work)
    if code != 0:
        raise SystemExit("造样本失败：%s" % kind)


def vols(work: Path, pattern: str) -> list:
    return sorted(p for p in work.glob(pattern) if p.is_file())


def main() -> int:
    print("=" * 62)
    print(" 分卷解压验收")
    print("=" * 62)

    ok, why = S.backend()
    print("\n[0] 后端")
    check("7z 可用", ok, why[:52])
    if not ok:
        return 1

    base = Path(tempfile.mkdtemp(prefix="svtest_"))
    try:
        run_cases(base)
    finally:
        shutil.rmtree(base, ignore_errors=True)

    print("\n" + "=" * 62)
    print(" 通过 %d 项，失败 %d 项" % (PASS, FAIL))
    print("=" * 62)
    return 0 if FAIL == 0 else 1


def run_cases(base: Path) -> None:
    # ══ 1. 完整的 7z 分卷 ═══════════════════════════════
    print("\n[1] 完整 7z 分卷")
    w1 = base / "ok7z"
    w1.mkdir()
    make_archive(w1, "7z", "pack.7z")
    vs = S.scan(w1 / "pack.7z.001")
    check("识别为 7z", vs.kind == "7z", vs.kind)
    check("找到 4 卷", len(vs.volumes) == 4, len(vs.volumes))
    check("判定完整", vs.complete, S.describe_problem(vs))
    check("结构层通过", S.structure(vs)[0])
    check("内容层通过", S.verify(vs)[0])
    check("标准卷大小 = 1 MB", vs.mode == 1048576, vs.mode)

    # 拖入的是中间那卷，也要能找齐
    vs_mid = S.scan(w1 / "pack.7z.003")
    check("拖入第 3 卷也能反推整套", len(vs_mid.volumes) == 4, len(vs_mid.volumes))
    check("反推的入口是第 1 卷",
          vs_mid.entry is not None and vs_mid.entry.name == "pack.7z.001",
          getattr(vs_mid.entry, "name", None))

    # ══ 2. 解压 ═════════════════════════════════════════
    print("\n[2] 解压")
    out = base / "out_ok"
    dest = S.extract(vs, out, verify_first=True)
    check("解压出目录", dest.is_dir(), dest.name)
    check("目录名去掉分卷痕迹", dest.name == "pack", dest.name)
    check("文件数正确", len(list(dest.iterdir())) == 2, len(list(dest.iterdir())))
    blob = dest / "blob.bin"
    check("内容大小正确", blob.is_file() and blob.stat().st_size == 3 * 1024 * 1024,
          blob.stat().st_size if blob.is_file() else "缺失")
    check("没有留下临时目录",
          not any(p.name.startswith(".cangtu_") for p in out.iterdir()))

    # ══ 3. 缺卷 ═════════════════════════════════════════
    print("\n[3] 缺一卷")
    w3 = base / "missing"
    shutil.copytree(w1, w3)
    (w3 / "pack.7z.003").unlink()
    vs3 = S.scan(w3 / "pack.7z.001")
    check("检出缺第 3 卷", vs3.missing == [3], vs3.missing)
    check("判定不完整", not vs3.complete)
    prob = S.describe_problem(vs3)
    check("提示里写明缺哪一卷", "第 3 卷" in prob, prob.splitlines()[0])
    check("提示里要求重新下载", "下载" in prob)
    check("结构层能拦住", not S.structure(vs3)[0])

    out3 = base / "out_missing"
    try:
        S.extract(vs3, out3)
        check("缺卷时拒绝解压", False, "居然解压成功了")
    except S.SplitError as exc:
        check("缺卷时拒绝解压", True, str(exc).splitlines()[0])
    check("失败后目标目录没有残留",
          not out3.exists() or not any(out3.iterdir()),
          list(out3.iterdir()) if out3.exists() else "目录未创建")

    # 缺第 1 卷（最容易被忽略：用户从 .002 开始下）
    w3b = base / "nohead"
    shutil.copytree(w1, w3b)
    (w3b / "pack.7z.001").unlink()
    vs3b = S.scan(w3b / "pack.7z.002")
    check("检出缺第 1 卷", vs3b.missing == [1], vs3b.missing)

    # ══ 4. 卷被截断 ═════════════════════════════════════
    print("\n[4] 中间卷只下了一半")
    w4 = base / "short"
    shutil.copytree(w1, w4)
    half = w4 / "pack.7z.002"
    data = half.read_bytes()
    half.write_bytes(data[:len(data) // 2])
    vs4 = S.scan(w4 / "pack.7z.001")
    check("卷号是齐的", not vs4.missing)
    check("检出大小异常", [v.index for v in vs4.odd] == [2],
          [v.index for v in vs4.odd])
    check("判定不完整", not vs4.complete)
    prob4 = S.describe_problem(vs4)
    check("提示给出应有大小和实际大小",
          "应该是" in prob4 and "实际" in prob4, prob4.splitlines()[0])
    check("结构层也能拦住", not S.structure(vs4)[0])

    # ══ 5. 长度正常但内容坏了 ═══════════════════════════
    print("\n[5] 大小全对、中间错了一个字节")
    w5 = base / "corrupt"
    shutil.copytree(w1, w5)
    tgt = w5 / "pack.7z.002"
    raw = bytearray(tgt.read_bytes())
    raw[300000] ^= 0xFF
    tgt.write_bytes(bytes(raw))
    vs5 = S.scan(w5 / "pack.7z.001")
    check("卷号齐、大小全对", vs5.missing == [] and vs5.odd == [])
    check("结构层看不出问题（这是设计上的盲区）", S.structure(vs5)[0])
    ok5, why5 = S.verify(vs5)
    check("内容层抓住了", not ok5)
    check("指出坏的是哪个文件", "blob.bin" in why5, why5.splitlines()[0])

    out5 = base / "out_corrupt"
    try:
        S.extract(vs5, out5)
        check("损坏时报错而不是产出坏文件", False, "居然解压成功了")
    except S.SplitError as exc:
        check("损坏时报错而不是产出坏文件", True, str(exc).splitlines()[0])
    check("失败后没有留下任何文件",
          not out5.exists() or not any(out5.iterdir()),
          list(out5.iterdir()) if out5.exists() else "目录未创建")

    # ══ 6. ZIP 分卷 ═════════════════════════════════════
    print("\n[6] ZIP 分卷（.zip.001）")
    w6 = base / "zip"
    w6.mkdir()
    make_archive(w6, "zip", "album.zip")
    vs6 = S.scan(w6 / "album.zip.001")
    check("识别为 zip", vs6.kind == "zip", vs6.kind)
    check("找到 4 卷", len(vs6.volumes) == 4, len(vs6.volumes))
    check("判定完整", vs6.complete)
    check("内容层通过", S.verify(vs6)[0])
    dest6 = S.extract(vs6, base / "out_zip", verify_first=False)
    check("解出 2 个文件", len(list(dest6.iterdir())) == 2, len(list(dest6.iterdir())))

    # ══ 7. 裸 .001（没有内层扩展名）═════════════════════
    print("\n[7] 裸分卷 .001，格式靠魔数嗅探")
    w7 = base / "bare"
    w7.mkdir()
    for i, src in enumerate(vols(w1, "pack.7z.*"), start=1):
        shutil.copy(src, w7 / ("movie.%03d" % i))
    vs7 = S.scan(w7 / "movie.001")
    check("从魔数认出是 7z", vs7.kind == "7z", vs7.kind)
    check("找到 4 卷", len(vs7.volumes) == 4, len(vs7.volumes))
    check("判定完整", vs7.complete)
    check("内容层通过", S.verify(vs7)[0])

    # ══ 8. 命名误判防护 ═════════════════════════════════
    print("\n[8] 不要把普通文件当成第 N 卷")
    w8 = base / "naming"
    w8.mkdir()
    (w8 / "photo.2024").write_bytes(b"not a volume")
    check("photo.2024 不被当成分卷", S.parse_name(w8 / "photo.2024") is None,
          S.parse_name(w8 / "photo.2024"))
    (w8 / "photo.001").write_bytes(b"x")
    nm = S.parse_name(w8 / "photo.2024")
    check("同目录有 .001 时才认它", nm is not None and nm.index == 2024,
          nm)

    # ══ 9. 各种命名风格的解析 ═══════════════════════════
    print("\n[9] 命名解析")
    cases = [
        ("a.7z.001", ("a.7z", 1, "num")),
        ("a.zip.012", ("a.zip", 12, "num")),
        ("b.001", ("b", 1, "num")),
        ("c.part1.rar", ("c", 1, "part")),
        ("c.part07.rar", ("c", 7, "part")),
        ("d.z01", ("d", 1, "z")),
        ("e.r00", ("e", 2, "oldrar")),
        ("e.r03", ("e", 5, "oldrar")),
    ]
    for name, (stem, idx, style) in cases:
        got = S.parse_name(Path(name))
        good = got is not None and got.index == idx and got.style == style
        check("%-14s → 第 %d 卷 / %s" % (name, idx, style), good,
              got and (got.stem, got.index, got.style))

    # ══ 10. 单文件（不是分卷）════════════════════════════
    print("\n[10] 单文件归档")
    w10 = base / "single"
    w10.mkdir()
    (w10 / "hello.txt").write_bytes(b"hi\n" * 100)
    seven(["a", "-t7z", "-mx1", "solo.7z", "hello.txt"], w10)
    vs10 = S.scan(w10 / "solo.7z")
    check("识别为单文件", vs10.style == "single", vs10.style)
    check("类型是 7z", vs10.kind == "7z", vs10.kind)
    check("判定可用", vs10.complete)
    dest10 = S.extract(vs10, base / "out_single")
    check("解压成功", (dest10 / "hello.txt").is_file(), dest10.name)

    # ══ 11. 完全不是压缩包 ═══════════════════════════════
    print("\n[11] 不认识的文件")
    w11 = base / "junk"
    w11.mkdir()
    (w11 / "note.txt").write_text("hello", encoding="utf-8")
    try:
        S.scan(w11 / "note.txt")
        check("拒绝未知格式", False, "居然接受了")
    except S.SplitError as exc:
        check("拒绝未知格式", True, str(exc).splitlines()[0])

    # ══ 12. 输出目录重名 ═════════════════════════════════
    print("\n[12] 目标目录已存在")
    out12 = base / "out_again"
    S.extract(vs, out12)
    try:
        S.extract(vs, out12)
        check("重名时拒绝覆盖", False, "居然覆盖了")
    except S.SplitError as exc:
        check("重名时拒绝覆盖", True, str(exc).splitlines()[0])
    check("原有内容没被动过", (out12 / "pack" / "blob.bin").is_file())


if __name__ == "__main__":
    sys.exit(main())
