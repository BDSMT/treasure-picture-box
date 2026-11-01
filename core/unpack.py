# -*- coding: utf-8 -*-
"""图种解包 —— 把图片末尾挂着的载荷拆出来，压缩包就地解开。

打包是「图片字节 + 载荷字节」的一次顺序拼接，解包就是反过来：

    1. 按图片格式走到真正的结尾（sniff）
    2. 结尾之后的那一段，就是被藏起来的东西
    3. 认出这段是什么（先试 bencode 种子，再匹配魔数）
    4. 是 ZIP 就在内存里解开，把里面的文件摆出来

这样就不用「改后缀 → 解压 → 翻文件夹找种子」了。

── ZIP 有两种状态，都要认 ─────────────────────────
本工具生成的图种在写入时做过「偏移修正」（见 zipfix.py）：载荷里记的偏移是
相对**整个图片文件**的绝对位置，这样 7-Zip / 资源管理器也能直接解压。
别的工具生成的图种则是相对 ZIP 自身起点。unfix_prefix 负责把前者还原成
干净的 ZIP —— 拆出来单独放着也能双击打开。
"""
from __future__ import annotations

import hashlib
import io
import zipfile
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from . import zipfix
from .sniff import guess_type, sniff

# 解包上限：单个成员 512 MB，合计 2 GB
# 图种本来就是小文件传种子的用法，超过这个量级说明场景不对
MAX_ENTRY = 512 * 1024 * 1024
MAX_TOTAL = 2048 * 1024 * 1024


class UnpackError(Exception):
    """无法解包，消息直接给界面显示。"""


@dataclass
class Entry:
    """压缩包里的一项，或者识别出的整个载荷。"""
    name: str                   # 包内路径（可能含子目录）
    data: bytes
    crc_ok: bool = True
    note: str = ""

    @property
    def size(self) -> int:
        return len(self.data)

    @property
    def leaf(self) -> str:
        return Path(self.name).name

    @property
    def is_torrent(self) -> bool:
        return self.leaf.lower().endswith(".torrent")


@dataclass
class TorrentInfo:
    """种子的关键信息，顺带算出 infohash 给人核对。"""
    name: str = ""
    announce: str = ""
    files: int = 0
    size: int = 0
    piece_length: int = 0
    infohash: str = ""

    @property
    def tracker_host(self) -> str:
        a = self.announce
        if not a:
            return ""
        try:
            rest = a.split("://", 1)[-1]
            return rest.split("/", 1)[0].split(":", 1)[0]
        except Exception:  # noqa: BLE001
            return a


@dataclass
class UnpackResult:
    source: str = ""
    image_kind: str = ""        # PNG / JPEG / …；不是图片时为空
    image_end: int = 0          # 图片主体结束的位置
    tail: bytes = b""           # 原文附加数据
    tail_clean: bytes = b""     # 还原过偏移的附加数据（导出用）
    offset_fixed: bool = False  # 附加数据是否被还原过偏移
    payload_type: str = ""      # ZIP / TORRENT / RAR / 未知…
    payload_ext: str = ""
    entries: List[Entry] = field(default_factory=list)
    torrent: Optional[TorrentInfo] = None
    warning: str = ""           # 需要提醒用户的事
    notes: List[str] = field(default_factory=list)

    @property
    def torrents(self) -> List[Entry]:
        return [e for e in self.entries if e.is_torrent]

    @property
    def has_payload(self) -> bool:
        return bool(self.tail)

    @property
    def bad_crc(self) -> int:
        return sum(1 for e in self.entries if not e.crc_ok)


# ══════════════════════════════════════════════════════════
#  bencode —— 种子的文件格式
# ══════════════════════════════════════════════════════════
class _Node:
    __slots__ = ("t", "v", "s", "e")

    def __init__(self, t: str, v, s: int, e: int):
        self.t, self.v, self.s, self.e = t, v, s, e


def _benc_one(b: bytes, i: int, end: int, depth: int = 0):
    """解析一个 bencode 元素，返回 (节点, 下一个位置)。"""
    if depth > 40:
        raise ValueError("嵌套过深")
    if i >= end:
        raise ValueError("意外结束")

    c = b[i]

    if c == 0x69:                                   # i<整数>e
        j = b.find(b"e", i + 1, end)
        if j < 0:
            raise ValueError("整数没闭合")
        return _Node("int", int(b[i + 1:j]), i, j + 1), j + 1

    if 0x30 <= c <= 0x39:                           # <长度>:<字节串>
        k = b.find(b":", i, end)
        if k < 0 or k - i > 9:
            raise ValueError("字符串头损坏")
        ln = int(b[i:k])
        s0, s1 = k + 1, k + 1 + ln
        if s1 > end:
            raise ValueError("字符串越界")
        return _Node("str", b[s0:s1], i, s1), s1

    if c == 0x6C:                                   # l … e
        arr = []
        j = i + 1
        while j < end and b[j] != 0x65:
            node, j = _benc_one(b, j, end, depth + 1)
            arr.append(node)
        if j >= end:
            raise ValueError("列表没闭合")
        return _Node("list", arr, i, j + 1), j + 1

    if c == 0x64:                                   # d … e
        mp = {}
        j = i + 1
        while j < end and b[j] != 0x65:
            key, j = _benc_one(b, j, end, depth + 1)
            if key.t != "str":
                raise ValueError("键不是字符串")
            val, j = _benc_one(b, j, end, depth + 1)
            mp[key.v] = val
        if j >= end:
            raise ValueError("字典没闭合")
        return _Node("dict", mp, i, j + 1), j + 1

    raise ValueError("不是 bencode")


def torrent_info(b: bytes) -> Optional[TorrentInfo]:
    """解析种子；不是有效种子返回 None。"""
    try:
        root, _ = _benc_one(b, 0, len(b), 0)
    except Exception:  # noqa: BLE001
        return None
    if root.t != "dict":
        return None
    info = root.v.get(b"info")
    if info is None or info.t != "dict":
        return None

    enc = root.v.get(b"encoding")
    gbk = bool(enc is not None and enc.t == "str" and b"gb" in enc.v.lower())

    def txt(node, default: str = "") -> str:
        if node is None or node.t != "str":
            return default
        try:
            return node.v.decode("gbk" if gbk else "utf-8")
        except Exception:  # noqa: BLE001
            return node.v.decode("utf-8", "replace")

    t = TorrentInfo()
    t.name = txt(info.v.get(b"name"))
    t.announce = txt(root.v.get(b"announce"))

    if not t.announce:                              # 没有 announce 就翻 announce-list
        al = root.v.get(b"announce-list")
        if (al is not None and al.t == "list" and al.v
                and al.v[0].t == "list" and al.v[0].v):
            t.announce = txt(al.v[0].v[0])

    pl = info.v.get(b"piece length")
    if pl is not None and pl.t == "int":
        t.piece_length = pl.v

    files = info.v.get(b"files")
    if files is not None and files.t == "list":
        t.files = len(files.v)
        for f in files.v:
            if f.t == "dict" and f.v.get(b"length") is not None and f.v[b"length"].t == "int":
                t.size += f.v[b"length"].v
    else:
        t.files = 1
        ln = info.v.get(b"length")
        if ln is not None and ln.t == "int":
            t.size = ln.v

    # infohash = info 字典那一段字节的 SHA-1，这是种子的唯一身份
    t.infohash = hashlib.sha1(b[info.s:info.e]).hexdigest()
    return t


def looks_like_torrent(b: bytes) -> bool:
    head = b[:700]
    return b[:1] == b"d" and (b"8:announce" in head or b"4:info" in head)


# ══════════════════════════════════════════════════════════
#  ZIP
# ══════════════════════════════════════════════════════════
def _member_name(zi: zipfile.ZipInfo) -> str:
    """压缩包里的中文名。

    zipfile 遇到没有 UTF-8 标志位（bit 11）的名字会按 cp437 解码，
    而中文压缩包实际存的是 GBK —— 直接显示就是乱码。
    """
    if zi.flag_bits & 0x800:
        return zi.filename
    try:
        return zi.filename.encode("cp437").decode("gbk")
    except Exception:  # noqa: BLE001
        return zi.filename


def _raw_member(blob: bytes, zi: zipfile.ZipInfo) -> bytes:
    """CRC 坏掉时手动解一次 —— zipfile 会校验失败，但数据往往还在。"""
    try:
        off = zi.header_offset
        if blob[off:off + 4] != b"PK\x03\x04":
            return b""
        nl = int.from_bytes(blob[off + 26:off + 28], "little")
        el = int.from_bytes(blob[off + 28:off + 30], "little")
        start = off + 30 + nl + el
        raw = blob[start:start + zi.compress_size]
        if zi.compress_type == zipfile.ZIP_DEFLATED:
            return zlib.decompressobj(-15).decompress(raw)
        if zi.compress_type == zipfile.ZIP_STORED:
            return raw
    except Exception:  # noqa: BLE001
        pass
    return b""


def zip_entries(tail: bytes):
    """把载荷当 ZIP 读，返回 (entries, 是否还原过偏移, 备注列表)。"""
    clean, fixed = zipfix.unfix_prefix(tail)

    try:
        zf = zipfile.ZipFile(io.BytesIO(clean))
    except zipfile.BadZipFile as exc:
        raise UnpackError("压缩包读不开：%s" % exc) from exc

    entries: List[Entry] = []
    notes: List[str] = []
    total = 0

    with zf:
        infos = [zi for zi in zf.infolist() if not zi.is_dir()]
        if not infos:
            raise UnpackError("这个压缩包是空的。")

        for zi in infos:
            name = _member_name(zi)
            if zi.file_size > MAX_ENTRY:
                notes.append("「%s」有 %s，超过单文件上限，没有展开。" % (Path(name).name, _human(zi.file_size)))
                continue
            if total + zi.file_size > MAX_TOTAL:
                notes.append("解开后超过 2 GB，剩下的没有展开。")
                break

            note = ""
            try:
                if zi.flag_bits & 0x1:
                    raise UnpackError("有密码")
                data = zf.read(zi)
                ok = True
            except Exception:  # noqa: BLE001
                data = _raw_member(clean, zi)
                ok = False
                note = "CRC 对不上，内容可能已经损坏" if data else "这项读不出来"

            total += len(data)
            entries.append(Entry(name=name, data=data, crc_ok=ok, note=note))

    return entries, fixed, notes


# ══════════════════════════════════════════════════════════
#  主流程
# ══════════════════════════════════════════════════════════
def detect(tail: bytes):
    """认出附加数据的类型，返回 (type, ext)。"""
    if not tail:
        return "空", ""
    if looks_like_torrent(tail):
        return "TORRENT", ".torrent"
    hit = guess_type(tail)
    if hit:
        return hit[0], hit[1]
    return "未知", ".bin"


def unpack(path: str | Path) -> UnpackResult:
    """拆开一个图种（也接受直接拖进来的 .zip / .torrent）。"""
    path = Path(path)
    raw = path.read_bytes()
    res = UnpackResult(source=str(path))

    info = sniff(raw)
    if info.kind:
        if not info.end_offset:
            raise UnpackError("这张图的结构不完整，找不到结尾。换一张试试。")
        res.image_kind = info.kind
        res.image_end = min(info.end_offset, len(raw))
    else:
        # 不是图片：整段当载荷，支持直接拖 .torrent / .zip 进来
        res.image_kind = ""
        res.image_end = 0

    res.tail = raw[res.image_end:]
    res.tail_clean = res.tail
    if not res.tail:
        return res

    res.payload_type, res.payload_ext = detect(res.tail)

    try:
        if res.payload_type == "ZIP":
            entries, fixed, notes = zip_entries(res.tail)
            res.entries = entries
            res.notes.extend(notes)
            if fixed:
                res.offset_fixed = True
                res.tail_clean, _ = zipfix.unfix_prefix(res.tail)

        elif res.payload_type == "TORRENT":
            name = path.stem + ".torrent"
            res.entries = [Entry(name=name, data=res.tail)]
            res.torrent = torrent_info(res.tail)
            if res.torrent is None:
                res.warning = "看起来是个种子，但结构解析不出来。"

        else:
            name = path.stem + "_附加数据" + res.payload_ext
            res.entries = [Entry(name=name, data=res.tail)]

    except UnpackError as exc:
        res.entries = []
        res.warning = str(exc)
    except Exception as exc:  # noqa: BLE001
        res.entries = []
        res.warning = "解包时出错：%s" % exc

    # 缩略图目录里若含种子，顺手把种子信息也读出来
    if res.torrent is None:
        for e in res.entries:
            if e.is_torrent and e.data:
                res.torrent = torrent_info(e.data)
                if res.torrent is not None:
                    break

    return res


def _human(n: float) -> str:
    units = ["B", "KB", "MB", "GB"]
    v = float(n)
    i = 0
    while v >= 1024 and i < len(units) - 1:
        v /= 1024.0
        i += 1
    return ("%d %s" if i == 0 or v >= 100 else "%.1f %s") % (v, units[i])


def safe_leaf(name: str) -> str:
    """取出一个能直接当文件名的名字。"""
    leaf = Path(name).name or "file"
    for ch in '\\/:*?"<>|':
        leaf = leaf.replace(ch, "_")
    return leaf[:120] or "file"


def save_entry(entry: Entry, out_path: str | Path) -> None:
    Path(out_path).write_bytes(entry.data)


def save_all(entries: List[Entry], folder: str | Path) -> int:
    """把解出来的文件都写到 folder 里，保留包内子目录。返回写了几个。"""
    root = Path(folder)
    written = 0
    for e in entries:
        parts = [p for p in Path(e.name).parts if p not in ("..", ".", "/", "\\")]
        if not parts:
            parts = [safe_leaf(e.name)]
        dst = root.joinpath(*parts)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(e.data)
        written += 1
    return written
