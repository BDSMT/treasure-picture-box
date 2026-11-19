# -*- coding: utf-8 -*-
"""分卷压缩包 —— 先判断完整，再解压。

── 为什么「判断完整性」比解压本身难 ──────────────────
把一个大文件切成 4 卷，手上只有 1、2、4 卷。这时缺第 3 卷，靠命名就能
一眼看出。但如果 5 卷齐全、只是第 2 卷少下了 200 MB 呢？文件名完全正常。
再进一步：卷都在、字节数都对，中间有一个 bit 错了呢？这就完全看不出来了。

所以判定必须分三层，代价从毫秒到分钟：

    第一层  结构扫描   卷号连续？除末卷外大小一致？        毫秒级
    第二层  归档结构   archive 的尾部头能否定位          百毫秒级
    第三层  内容校验   逐文件 CRC32                      与总大小成正比

实测证据（`docs/分卷解压.md` 有完整命令记录）：
把 7z 分卷的第 2 卷翻掉一个字节、长度保持不变，
`7z l` 返回 0 且报告 `Volumes: 4` —— **结构层完全看不出问题**；
`7z t` 返回 2 并指出 `CRC Failed : big.bin`。
只要少做第三层，损坏的文件就会被静默解出来，用户以为没事。

── 三种命名家族 ──────────────────────────────────
    name.7z.001 / name.zip.001 / name.001     纯字节切分，序号补零
    name.z01 + name.zip                       老式 PKZIP 跨卷，主文件是最后一卷
    name.part1.rar / name.part01.rar          WinRAR 分卷
    name.rar + name.r00 + name.r01            老式 RAR 多卷

它们最终都是「按顺序拼起来就是一个完整归档」，所以解压统一交给 7-Zip：
给它第一卷，它会自己找后续卷。

── 为什么不自己解压 ────────────────────────────────
RAR 是专有格式，7z 的 LZMA 也有 BCJ2 这类多流编码。自己实现等于重写
7-Zip。vendor/7z/ 里放了官方的 7z.exe + 7z.dll（2.4 MB，LGPL 可随包分发），
它是唯一能对全部格式做 CRC 校验的可靠后端。
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

# 调 7z 时不要弹出黑框。打包成 GUI 程序后这是硬要求：
# 没有这个标志，每解压一次都会闪一个控制台窗口。
CREATE_NO_WINDOW = 0x08000000

MAX_VOLUMES = 9999          # 再多的分卷不是「下载场景」，是有人在恶作剧

# 扩展名 → 归档类型。只用于显示和给 entry 定名，真正的解析交给 7z。
KINDS = {
    ".7z": "7z", ".zip": "zip", ".rar": "rar", ".tar": "tar",
    ".gz": "gzip", ".xz": "xz", ".bz2": "bzip2", ".iso": "iso",
}

# 归档的第一块魔数。.001 这种裸分卷没有扩展名可看，只能读前几个字节。
MAGIC = [
    (b"7z\xbc\xaf\x27\x1c", "7z"),
    (b"PK\x03\x04", "zip"),
    (b"Rar!\x1a\x07", "rar"),
    (b"\x1f\x8b", "gzip"),
    (b"\xfd7zXZ\x00", "xz"),
    (b"BZh", "bzip2"),
]


class SplitError(Exception):
    """分卷处理失败，消息直接给人看。"""


# ══════════════════════════════════════════════════════════
#  找 7z
# ══════════════════════════════════════════════════════════
def exe() -> Optional[Path]:
    """定位 7z.exe。返回 None 表示这台机器上没有可用后端。

    顺序：随包携带 → 程序目录 → 系统安装。随包那份优先，
    因为它的版本是我们验证过的；系统那份可能被改过或版本太老。
    """
    cands: List[Path] = []

    if getattr(sys, "frozen", False):
        # PyInstaller onedir：数据文件在 _internal，运行时 _MEIPASS 指向它
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            cands.append(Path(meipass) / "runtime" / "7z" / "7z.exe")
        cands.append(Path(sys.executable).resolve().parent / "_internal"
                     / "runtime" / "7z" / "7z.exe")
        cands.append(Path(sys.executable).resolve().parent / "runtime" / "7z" / "7z.exe")

    cands.append(Path(__file__).resolve().parent.parent / "runtime" / "7z" / "7z.exe")

    for p in (r"C:\Program Files\7-Zip\7z.exe", r"C:\Program Files (x86)\7-Zip\7z.exe"):
        cands.append(Path(p))

    for c in cands:
        try:
            if c.is_file():
                return c
        except OSError:
            continue
    return None


def backend() -> tuple:
    """(可用, 说明)。自检和插件 check() 都调这个。"""
    p = exe()
    if p is None:
        return False, "找不到 7z.exe（程序目录下 vendor\\7z\\ 缺失）"
    try:
        out = subprocess.run(
            [str(p)], capture_output=True, timeout=20,
            creationflags=CREATE_NO_WINDOW,
        )
    except Exception as exc:  # noqa: BLE001
        return False, "7z.exe 跑不起来：%s" % exc
    text = decode(out.stdout + out.stderr)
    ver = ""
    for line in text.splitlines():
        if "7-Zip" in line:
            ver = line.strip()
            break
    return True, ver or "7z 就绪"


def decode(raw: bytes) -> str:
    """7z 的输出编码跟着系统代码页走。

    中文 Windows 是 GBK，英文是 cp1252，新版也可能直接吐 UTF-8。
    三种都试一遍，取能解出最多可见字符的那个 —— 猜错的代价只是乱码，
    但猜对了能让错误信息可读。
    """
    if not raw:
        return ""
    best, score = "", -1
    for enc in ("utf-8", "mbcs", "gbk", "cp1252"):
        try:
            t = raw.decode(enc)
        except Exception:  # noqa: BLE001
            continue
        good = sum(1 for ch in t if ch.isprintable() or ch in "\r\n\t")
        if good > score:
            best, score = t, good
    return best


def _run(args: List[str], timeout: int = 0) -> tuple:
    """(退出码, 输出文本)。0=成功，1=有警告，2=出错。

    超时返回 (-1, ...)：解压一个 50 GB 的分卷真的可能跑很久，
    所以默认不设上限，只在探测类调用上传超时。
    """
    p = exe()
    if p is None:
        raise SplitError("找不到 7z.exe，解压后端不可用")

    cmd = [str(p)] + args
    try:
        kw = {"capture_output": True, "creationflags": CREATE_NO_WINDOW}
        if timeout:
            kw["timeout"] = timeout
        out = subprocess.run(cmd, **kw)
    except subprocess.TimeoutExpired:
        return -1, "处理超时"
    except Exception as exc:  # noqa: BLE001
        raise SplitError("调用 7z 失败：%s" % exc) from exc

    return out.returncode, decode((out.stdout or b"") + (out.stderr or b""))


# ══════════════════════════════════════════════════════════
#  命名解析
# ══════════════════════════════════════════════════════════
#  按优先级匹配：先认特征强的（.partN.rar / .z01 / .r00），
#  最后才用「数字尾巴」，因为它有歧义（photo.2024 也可能长这样）。
_RE_PART = re.compile(r"^(?P<stem>.+)\.part(?P<num>\d+)\.rar$", re.I)
_RE_Z = re.compile(r"^(?P<stem>.+)\.z(?P<num>\d{2,})$", re.I)
_RE_OLD = re.compile(r"^(?P<stem>.+)\.r(?P<num>\d{2,})$", re.I)
_RE_NUM = re.compile(r"^(?P<stem>.+)\.(?P<num>\d{2,5})$", re.I)


@dataclass
class Name:
    """一个文件名被拆出来的分卷信息。"""
    stem: str       # 组的公共前缀，如 "test.7z" / "test" / "test.zip"
    index: int      # 卷号，从 1 开始
    style: str      # num | z | part | oldrar
    width: int      # 序号补几位零（沿用用户文件里的写法）


def _has_first(p: Path, stem: str) -> bool:
    """同目录里有没有第 1 卷（.001 / .0001 / .01 都算）。

    这里不能靠「按当前文件位数推」—— `photo.2024` 是 4 位，
    但它对应的第 1 卷可能叫 photo.001（3 位），推出来的 photo.0001 根本不存在。
    直接在目录里按模式找。
    """
    pat = re.compile(r"^%s\.0+1$" % re.escape(stem), re.I)
    try:
        return any(pat.match(f.name) for f in p.parent.iterdir() if f.is_file())
    except OSError:
        return False


def parse_name(p: Path) -> Optional[Name]:
    """认出这个文件名属于哪种分卷命名；认不出返回 None。

    `photo.2024` 和 `archive.001` 长得像，区别只在数字有没有补零：
    真分卷几乎总是 .001 起头。所以不补零的数字要额外佐证
    （同目录下存在 .001），否则不认 —— 宁可漏判，也别把用户的照片
    当成第 2024 卷。
    """
    name = p.name
    m = _RE_PART.match(name)
    if m:
        num = m.group("num")
        return Name(stem=m.group("stem"), index=int(num), style="part", width=len(num))

    m = _RE_Z.match(name)
    if m:
        num = m.group("num")
        # X.z01 的第 1 卷在主文件 X.zip 之前
        return Name(stem=m.group("stem"), index=int(num), style="z", width=len(num))

    m = _RE_OLD.match(name)
    if m:
        num = m.group("num")
        # X.r00 是第 2 卷（第 1 卷是 X.rar），所以序号要 +2
        return Name(stem=m.group("stem"), index=int(num) + 2, style="oldrar",
                    width=len(num))

    m = _RE_NUM.match(name)
    if m:
        num = m.group("num")
        idx = int(num)
        stem = m.group("stem")
        if idx > MAX_VOLUMES:
            return None
        if not num.startswith("0") and idx > 1 and not _has_first(p, stem):
            return None
        return Name(stem=stem, index=idx, style="num", width=len(num))

    return None


def kind_of(stem: str, first: Optional[Path]) -> str:
    """判断归档类型：先看扩展名，扩展名不认识就读第一块的魔数。"""
    suf = Path(stem).suffix.lower()
    if suf in KINDS:
        return KINDS[suf]
    if first is not None:
        try:
            with open(first, "rb") as f:
                head = f.read(16)
        except OSError:
            head = b""
        for sig, name in MAGIC:
            if head.startswith(sig):
                return name
    return "unknown"


# ══════════════════════════════════════════════════════════
#  卷组
# ══════════════════════════════════════════════════════════
@dataclass
class Volume:
    index: int
    path: Path
    size: int

    @property
    def name(self) -> str:
        return self.path.name


@dataclass
class VolSet:
    """一组分卷的完整画像。"""
    stem: str = ""
    kind: str = "unknown"
    style: str = ""
    root: Path = field(default_factory=Path)
    volumes: List[Volume] = field(default_factory=list)
    missing: List[int] = field(default_factory=list)
    main: Optional[Path] = None      # z 风格的主文件（X.zip），它本身是最后一卷
    note: str = ""

    # ── 派生信息 ──────────────────────────────────────
    @property
    def total(self) -> int:
        return sum(v.size for v in self.volumes)

    @property
    def count(self) -> int:
        return len(self.volumes) + (1 if self.main else 0) + len(self.missing)

    @property
    def entry(self) -> Optional[Path]:
        """该把哪个文件交给 7z。

        num/part 风格给第 1 卷；z 风格给主文件（7-Zip 从它反查 z01）；
        oldrar 给 .rar。缺第 1 卷时退而求其次，给现存最小的那卷 ——
        7z 照样会报错，但报的是「打不开」而不是「文件不存在」，更好懂。
        """
        if self.style == "z" and self.main is not None:
            return self.main
        if self.volumes:
            first = min(self.volumes, key=lambda v: v.index)
            if first.index == 1:
                return first.path
        return self.volumes[0].path if self.volumes else None

    @property
    def mode(self) -> int:
        """分卷的标准大小：除末卷外，所有卷都应该是这个数。

        取众数而不是平均值 —— 有一卷下坏了不影响判断基准。
        """
        sizes = [v.size for v in self.volumes]
        if not sizes:
            return 0
        counts = {}
        for s in sizes:
            counts[s] = counts.get(s, 0) + 1
        return max(counts.items(), key=lambda kv: (kv[1], kv[0]))[0]

    @property
    def odd(self) -> List[Volume]:
        """大小不合群的卷。

        判据：除最后一卷外，每一卷都必须等于标准大小。末卷可以小（它装尾巴），
        但不能大，也不能是 0。
        """
        if len(self.volumes) <= 1:
            return []
        m = self.mode
        last = max(self.volumes, key=lambda v: v.index)
        out = []
        for v in self.volumes:
            if v is last:
                if v.size <= 0 or v.size > m:
                    out.append(v)
            elif v.size != m:
                out.append(v)
        return out

    @property
    def empty(self) -> List[Volume]:
        return [v for v in self.volumes if v.size == 0]

    @property
    def complete(self) -> bool:
        return not self.missing and not self.odd and bool(self.volumes)

    @property
    def label(self) -> str:
        """给人看的名字，去掉 .001 这类尾巴。"""
        return Path(self.stem).name or self.stem


def scan(path) -> VolSet:
    """从任意一卷反推出整个分卷组。

    用户可能拖进来第 3 卷，也可能拖最后一卷 —— 都要能找齐。
    做法是把同目录下所有文件过一遍 parse_name，挑出 stem 相同的。
    """
    p = Path(path)
    if not p.exists():
        raise SplitError("文件不存在：%s" % p)

    nm = parse_name(p)
    if nm is None:
        # 不是分卷命名。单文件归档也允许，只是没有「卷」的概念。
        vs = VolSet(stem=p.name, root=p.parent, style="single",
                    volumes=[Volume(1, p, p.stat().st_size)])
        vs.kind = kind_of(p.name, p)
        if vs.kind == "unknown":
            raise SplitError(
                "认不出这个文件的格式。\n\n"
                "分卷文件的命名通常是 <名字>.7z.001、<名字>.part1.rar、"
                "<名字>.z01 这样；如果这是单个压缩包，也可以直接拖进来。")
        vs.note = "单个文件，不是分卷"
        return vs

    root = p.parent
    found = {}
    for f in root.iterdir():
        if not f.is_file():
            continue
        other = parse_name(f)
        if other is None or other.stem != nm.stem or other.style != nm.style:
            continue
        try:
            found[other.index] = f
        except OSError:
            continue

    vs = VolSet(stem=nm.stem, root=root, style=nm.style)

    # z 风格：主文件是「X.z01 去掉 .z01 再补 .zip」= X.zip，它是最后一卷。
    # 它不带序号，上面那轮扫描扫不到，单独找。
    if nm.style == "z":
        for ext in (".zip", ".rar", ".7z"):
            main = root / (nm.stem + ext)
            if main.is_file():
                vs.main = main
                break

    hi = max(found) if found else 0
    vs.missing = [i for i in range(1, hi + 1) if i not in found]

    for i in sorted(found):
        f = found[i]
        try:
            size = f.stat().st_size
        except OSError:
            size = 0
        vs.volumes.append(Volume(i, f, size))

    if vs.main is not None:
        try:
            vs.volumes.append(Volume(hi + 1, vs.main, vs.main.stat().st_size))
        except OSError:
            pass

    # 类型看两处：前缀里的扩展名（test.7z.001 → .7z），没有就嗅第一块的魔数
    first = vs.volumes[0].path if vs.volumes else None
    vs.kind = kind_of(nm.stem, first)

    if not vs.volumes:
        raise SplitError("这个目录里找不到 %s 的任何一卷。" % nm.stem)
    return vs


# ══════════════════════════════════════════════════════════
#  第三层之外的两层：结构 & 内容
# ══════════════════════════════════════════════════════════
def describe_problem(vs: VolSet) -> str:
    """把卷组的问题翻译成一句人话。没问题返回空串。

    这里的文案要能让用户立刻知道该去做什么：
    「缺第 3 卷」比「文件不完整」有用得多 —— 前者能直接去补下载。
    """
    if vs.missing:
        nums = "、".join(str(i) for i in vs.missing[:8])
        more = " 等 %d 个" % len(vs.missing) if len(vs.missing) > 8 else ""
        return ("缺少第 %s 卷%s。\n\n"
                "分卷必须齐全才能解压，缺任何一卷都会导致解出来的文件损坏。"
                "请把缺的卷下载完（不要改名），放到同一个文件夹再试。"
                % (nums, more))

    bad = vs.odd
    if bad:
        m = vs.mode
        v = bad[0]
        return ("第 %d 卷的大小不对：应该是 %s，实际只有 %s。\n\n"
                "这是下载没完成或中断留下的半截文件。直接解压会把损坏的数据"
                "写进结果里，解出来的文件是坏的，而且事后很难发现是哪一步出的问题。\n\n"
                "请删掉这一卷重新下载，确认下完（大小对上）再试。"
                % (v.index, human(m), human(v.size)))

    if vs.volumes and max(v.index for v in vs.volumes) == 1 and vs.style != "single":
        return ("只有第 1 卷。\n\n"
                "如果这个归档本来就分了好几卷，其余几卷还没下载；"
                "如果确实只有一个文件，它可能根本不是分卷包。")

    return ""


def structure(vs: VolSet) -> tuple:
    """第二层：让 7z 试着打开归档头部。返回 (ok, 说明)。

    这一步只读头尾，不碰内容，所以对 10 GB 的分卷也是一百毫秒级。
    它能抓到「卷都在但顺序乱了」「最后一卷其实是别的文件」这类问题 ——
    这些靠大小判断看不出来。
    """
    ent = vs.entry
    if ent is None:
        return False, "没有可用的卷可以打开"

    code, text = _run(["l", "-slt", "-bd", str(ent)], timeout=120)
    if code == 0:
        return True, ""

    low = text.lower()
    if "unexpected end of archive" in low or "cannot open the file as" in low:
        return False, ("归档的结构对不上 —— 卷都在，但拼起来不是一个完整的压缩包。\n\n"
                       "常见原因：某一卷其实是别的文件（下载到了错误页面）、"
                       "卷被改过名、或者有一卷下到一半。\n"
                       "建议把整套分卷重新下载一遍。")
    if "can not open the file as" in low:
        return False, "打不开这个归档，格式可能不被支持，或者文件头已经损坏。"
    return False, ("7z 打不开这个归档（退出码 %d）。\n\n%s"
                   % (code, tail_text(text)))


def verify(vs: VolSet) -> tuple:
    """第三层：全量 CRC 校验。返回 (ok, 说明)。

    这是唯一能发现「长度对、内容坏了」的手段，代价是要读完所有字节。
    对 10 GB 的分卷大约几十秒到几分钟 —— 所以只在用户按下解压时跑，
    不在拖入时就跑。
    """
    ent = vs.entry
    if ent is None:
        return False, "没有可用的卷可以校验"

    code, text = _run(["t", str(ent)], timeout=0)
    if code == 0:
        return True, ""

    bad = []
    for line in text.splitlines():
        s = line.strip()
        if "CRC Failed" in s or "Data Error" in s:
            part = s.split(":")[-1].strip()
            if part and part not in bad:
                bad.append(part)

    if bad:
        names = "、".join(bad[:5])
        more = " 等 %d 个文件" % len(bad) if len(bad) > 5 else ""
        return False, ("校验失败：%s%s 的数据对不上。\n\n"
                       "这说明分卷里有字节损坏 —— 大小都对，但内容已经坏了，"
                       "通常是下载过程中断过、或者硬盘/网盘传输出错。\n\n"
                       "重新下载分卷再试；如果反复失败，可能是源文件本身有问题。"
                       % (names, more))

    if code == 2:
        return False, ("校验没通过（退出码 2）。\n\n%s" % tail_text(text))
    return True, ""


def tail_text(text: str, keep: int = 6) -> str:
    """取输出的最后几行。7z 的真正原因总在末尾，前面全是进度。"""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    return "\n".join(lines[-keep:]) if lines else "（没有更多信息）"


# ══════════════════════════════════════════════════════════
#  解压
# ══════════════════════════════════════════════════════════
def extract(vs: VolSet, dest_dir, verify_first: bool = True,
            on_stage=None) -> Path:
    """解压到 dest_dir，返回实际输出目录。

    ── 为什么先解到临时目录 ────────────────────────
    7z 遇到 CRC 错误不会立刻停：它会把能解的都解出来，最后才返回 2。
    如果直接解到目标目录，用户就得到一堆看起来正常、实际损坏的文件 ——
    正是这个功能要避免的事。

    所以先落到同级的临时目录，全部校验通过才改成正式名字。
    失败就把临时目录整个删掉，用户的目标目录里什么都不会多出来。
    """
    ent = vs.entry
    if ent is None:
        raise SplitError("没有可用的卷")

    if verify_first:
        if on_stage:
            on_stage("正在校验完整性…")
        ok, why = verify(vs)
        if not ok:
            raise SplitError(why)

    if on_stage:
        on_stage("正在解压…")

    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    final = dest / _out_name(vs)

    tmp = Path(tempfile.mkdtemp(prefix=".cangtu_", dir=str(dest)))
    try:
        # -o 后面不能有空格，这是 7z 的老规矩
        code, text = _run(["x", str(ent), "-o" + str(tmp), "-y", "-bso0", "-bsp0"], timeout=0)
        if code != 0:
            bad = [l.strip() for l in text.splitlines() if "CRC Failed" in l]
            if bad:
                raise SplitError("解压过程中发现数据损坏：%s\n\n"
                                 "没有写入任何文件。请重新下载分卷后再试。"
                                 % bad[0].split(":")[-1].strip())
            raise SplitError("解压失败（退出码 %d）。\n\n%s" % (code, tail_text(text)))

        items = list(tmp.iterdir())
        if len(items) == 1 and items[0].is_dir():
            # 归档里只有一个顶层目录：直接把它变成输出目录，少一层套娃
            shutil.move(str(items[0]), str(final))
            tmp.rmdir()
        else:
            if final.exists():
                raise SplitError("目标位置已经有同名文件夹了：%s" % final)
            tmp.replace(final)
        return final
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise


def _out_name(vs: VolSet) -> str:
    """解压出来的文件夹叫什么。

    取归档本身的 stem：test.7z.001 → test；test.part1.rar → test；
    album.zip.001 → album。分卷痕迹和归档扩展名都要剥掉，
    否则用户在硬盘上会看到一堆叫 xxx.7z 的文件夹。
    """
    stem = Path(vs.stem).name
    # 最多剥两层：a.tar.gz → a
    for _ in range(2):
        suf = Path(stem).suffix.lower()
        if suf in KINDS:
            stem = Path(stem).stem
        else:
            break
    leaf = Path(stem).name
    for ch in '\\/:*?"<>|':
        leaf = leaf.replace(ch, "_")
    return (leaf or "解压结果").strip(". ") or "解压结果"


def human(n: float) -> str:
    """字节数 → 人话。和界面里的 fmt_size 保持同一套口径。"""
    units = ["B", "KB", "MB", "GB", "TB"]
    v = float(n)
    i = 0
    while v >= 1024 and i < len(units) - 1:
        v /= 1024.0
        i += 1
    if i == 0:
        return "%d B" % v
    return ("%.2f %s" if v < 10 else "%.1f %s" if v < 100 else "%.0f %s") % (v, units[i])
