# -*- coding: utf-8 -*-
"""图种 —— 字节拼接。

原理简单到不需要算法：图片原始字节在前，载荷原封不动接在后面。
看图软件遇到图片的结束标记就停止解析，后面的数据被忽略；
把后缀改成 .zip 之类的，解压软件就能读到这段载荷。

关键只有一条：拼接的位置必须是图片「真正的结尾」，不能简单地整个文件接上去。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import zipfix
from .sniff import guess_type, sniff


@dataclass
class SeedResult:
    data: bytes
    kind: str
    cover_len: int
    payload_len: int
    payload_type: str = ""          # 载荷的实际格式：ZIP / RAR / 7Z / 未知…
    patched: bool = False           # 是否做了 zip 偏移修正
    warning: str = ""               # 给界面看的提醒


def packed_size(cover: bytes, payload: bytes) -> int:
    info = sniff(cover)
    base = info.end_offset or len(cover)
    return base + len(payload)


def payload_kind(payload: bytes) -> str:
    hit = guess_type(payload)
    if hit:
        return hit[0]
    if zipfix.is_zip(payload):
        return "ZIP"
    return "未知"


def pack(cover_path: str | Path, payload_path: str | Path) -> SeedResult:
    """生成图种字节。

    封面图如果本身就带着附加数据（本身是个图种），只取到它的真实结尾，
    避免把上一次藏的东西也一起吞进新图里 —— 叠在一起谁也拆不干净。

    ZIP 载荷会额外做一次偏移修正，否则只有 python / Info-ZIP 这类
    会做偏移补偿的解压器认得，7-Zip、Bandizip、资源管理器会报「不是压缩文件」。
    """
    cover = Path(cover_path).read_bytes()
    payload = Path(payload_path).read_bytes()

    info = sniff(cover)
    if not info.kind:
        raise ValueError("认不出这张图的格式，试试 JPG 或 PNG。")
    if not info.end_offset:
        raise ValueError("这张图的结构不完整，结尾找不到。换一张试试。")

    base = cover[: info.end_offset]
    data = base + payload
    kind = payload_kind(payload)

    patched = False
    warning = ""
    if zipfix.is_zip(payload):
        try:
            data, patched = zipfix.fix_prefix(data, len(base))
        except zipfix.ZipError as exc:
            warning = str(exc)
    else:
        what = ("%s 这种格式" % kind) if kind not in ("", "未知") else "这类文件"
        warning = ("载荷不是 ZIP 压缩包。%s的头部必须从第 0 字节开始读，"
                   "接在图片后面就认不出来了 —— 改后缀解压不了，"
                   "只能用本工具拆出来。" % what)

    return SeedResult(
        data=data,
        kind=info.kind,
        cover_len=len(base),
        payload_len=len(payload),
        payload_type=kind,
        patched=patched,
        warning=warning,
    )


def write(result: SeedResult, out_path: str | Path) -> None:
    Path(out_path).write_bytes(result.data)


# ── 反向：把一个图种拆开 ────────────────────────────────

@dataclass
class SplitResult:
    image: bytes
    tail: bytes
    kind: str
    tail_type: str
    tail_ext: str
    unfixed: bool = False           # 是否把 zip 偏移还原成了可独立解压的状态


def split(seed_path: str | Path) -> SplitResult:
    raw = Path(seed_path).read_bytes()
    info = sniff(raw)
    if not info.kind or not info.end_offset:
        raise ValueError("这不是能识别的图片，或者结构不完整。")

    tail = raw[info.end_offset:]
    hit = guess_type(tail)

    # 新版图种写进去的是「偏移已修正」的 zip，拆出来必须减回去，
    # 否则这个 zip 单独放着也解压不了。
    unfixed = False
    if zipfix.is_zip(tail):
        tail, unfixed = zipfix.unfix_prefix(tail)

    return SplitResult(
        image=raw[: info.end_offset],
        tail=tail,
        kind=info.kind,
        tail_type=hit[0] if hit else "未知",
        tail_ext=hit[1] if hit else ".bin",
        unfixed=unfixed,
    )
