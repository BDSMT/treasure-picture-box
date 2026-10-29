# -*- coding: utf-8 -*-
"""ZIP 前缀偏移修正。

── 为什么需要这一步 ──────────────────────────────
ZIP 的末尾有 EOCD（End Of Central Directory），里面记着「中央目录在文件
开头往后第几个字节」。每个中央目录条目里又记着「这个文件的本地头在
开头往后第几个字节」。

这些偏移量都是**相对 ZIP 数据自身起点**的。把 ZIP 接在图片后面之后，
JPEG 的 216389 字节把一切都往后推了，记录里的数字就全错位了。

· Python 的 zipfile、Info-ZIP、libarchive 会做「偏移补偿」：
  发现记录的位置和实际位置不符，就把差值套用到所有条目上，所以能读。
· 7-Zip、Bandizip、Windows 资源管理器不做这个补偿，
  读到错位的位置发现不是 PK 签名，直接报「不是压缩文件」。

所以要让图种在任何解压软件里都能开，必须在写入前把偏移量改成
**加了前缀之后的绝对位置**。这正是 Info-ZIP 的 `zip -A` 干的事。

── 反向也要做 ────────────────────────────────
拆分时把载荷还原成独立文件，也必须把偏移量减回去，
否则拆出来的 zip 自己单独打不开。
"""
from __future__ import annotations

import struct
from typing import Optional

EOCD_SIG = b"PK\x05\x06"          # 22 字节 + 注释
CD_SIG = b"PK\x01\x02"            # 46 字节 + 名称/扩展/注释
Z64_LOC_SIG = b"PK\x06\x07"       # 20 字节
Z64_EOCD_SIG = b"PK\x06\x06"      # 56 字节 + 扩展数据

EOCD_MIN = 22
MAX_COMMENT = 65535
U32 = 0xFFFFFFFF


class ZipError(Exception):
    pass


def is_zip(b: bytes) -> bool:
    return len(b) >= 4 and b[:4] in (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")


def find_eocd(b: bytes) -> int:
    """从尾部向前找 EOCD 签名，返回偏移；找不到返回 -1。"""
    if len(b) < EOCD_MIN:
        return -1
    hi = len(b) - EOCD_MIN
    lo = max(0, len(b) - EOCD_MIN - MAX_COMMENT)
    for i in range(hi, lo - 1, -1):
        if b[i:i + 4] == EOCD_SIG:
            # 注释长度要自洽，否则可能是数据里碰巧出现的字节
            (cmlen,) = struct.unpack("<H", b[i + 20:i + 22])
            if i + EOCD_MIN + cmlen == len(b):
                return i
    # 严格匹配失败时退一步，只认签名
    for i in range(hi, lo - 1, -1):
        if b[i:i + 4] == EOCD_SIG:
            return i
    return -1


def _layout(b: bytes) -> Optional[dict]:
    """解析出中央目录的位置信息。"""
    e = find_eocd(b)
    if e < 0:
        return None
    (cd_size,) = struct.unpack("<I", b[e + 12:e + 16])
    (cd_off,) = struct.unpack("<I", b[e + 16:e + 20])
    cd_start = e - cd_size          # 中央目录真实位置（紧贴 EOCD 之前）
    return {
        "eocd": e,
        "cd_size": cd_size,
        "cd_off": cd_off,
        "cd_start": cd_start,
        "dev": cd_start - cd_off,   # 偏差：>0 说明前面挂过东西
        "zip64": cd_off == U32 or cd_size == U32,
    }


def _shift_entries(b: bytearray, delta: int) -> int:
    """把所有中央目录条目里的「本地头偏移」加上 delta，返回处理条数。"""
    lay = _layout(bytes(b))
    if not lay:
        return 0
    p, cnt = lay["cd_start"], 0
    n = len(b)
    while p + 46 <= n and b[p:p + 4] == CD_SIG:
        name_len, extra_len, cmt_len = struct.unpack("<HHH", b[p + 28:p + 34])
        (lho,) = struct.unpack("<I", b[p + 42:p + 46])
        new = lho + delta
        if new < 0 or new > U32:
            raise ZipError("偏移量超出 32 位范围（图种总大小超过 4 GB）")
        struct.pack_into("<I", b, p + 42, new)
        cnt += 1
        p += 46 + name_len + extra_len + cmt_len
    return cnt


def fix_prefix(data: bytes, prefix_len: int) -> tuple:
    """让「前缀 + zip」变成任何解压器都认的合法 zip。

    data 必须是**已经拼好的完整数据**，且 zip 内部的偏移仍是
    「相对 zip 自身起点」的状态。返回 (修补后的 bytes, 是否改动)。
    """
    lay = _layout(data)
    if not lay or prefix_len <= 0:
        return data, False
    if lay["zip64"]:
        raise ZipError("这个压缩包是 ZIP64 格式（超 4 GB 或文件数超 6 万），"
                       "做不了前缀修正，请换普通 zip。")

    b = bytearray(data)
    _shift_entries(b, prefix_len)
    # 中央目录的真实位置就在 EOCD 前面，直接写这个值最稳（也天然幂等）
    struct.pack_into("<I", b, lay["eocd"] + 16, lay["cd_start"])
    return bytes(b), True


def normalize(data: bytes) -> tuple:
    """把「偏移指向绝对位置」的 zip 还原成相对自身，用于清理带前缀的载荷。"""
    lay = _layout(data)
    if not lay or lay["zip64"]:
        return data, False
    dev = lay["dev"]
    if dev <= 0:
        return data, False
    b = bytearray(data)
    _shift_entries(b, -dev)
    struct.pack_into("<I", b, lay["eocd"] + 16, lay["cd_start"] - dev)
    return bytes(b), True


def unfix_prefix(tail: bytes) -> tuple:
    """拆分时调用：把偏移量减回「相对自身」的状态。

    返回 (还原后的 bytes, 是否改动)。本来就干净的（老图种）原样返回。

    在 tail 里，dev = 真实中央目录位置 − 记录的位置。
    修补过的 tail 会得到 dev = −前缀长度，所以要加的是 dev（负数）。
    """
    lay = _layout(tail)
    if not lay or lay["zip64"]:
        return tail, False
    dev = lay["dev"]
    if dev >= 0:
        return tail, False        # 0 = 干净；>0 不是我们造成的，不碰
    b = bytearray(tail)
    _shift_entries(b, dev)
    struct.pack_into("<I", b, lay["eocd"] + 16, lay["cd_start"])
    return bytes(b), True


def describe(data: bytes) -> dict:
    """给界面用的诊断信息。"""
    lay = _layout(data)
    if not lay:
        return {}
    return {
        "entries": struct.unpack("<H", data[lay["eocd"] + 10:lay["eocd"] + 12])[0],
        "dev": lay["dev"],
        "cd_start": lay["cd_start"],
        "cd_off": lay["cd_off"],
        "ok": lay["dev"] == 0,
        "zip64": lay["zip64"],
    }
