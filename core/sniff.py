# -*- coding: utf-8 -*-
"""图片格式识别 —— 找出图片「真正的结尾」在哪个字节。

图种的原理就是把文件接在这个字节之后。所以结尾位置必须精确：
宁可多解析几个块，也不能把图片自身的尾部数据当成附加内容。

移植自网页版 seed-toolbox.html 的 sniff() / guessType()，规则完全一致。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

IMAGE_EXTS = {
    ".jpg", ".jpeg", ".jpe", ".png", ".gif", ".webp", ".bmp",
    ".tif", ".tiff", ".avif", ".ico",
}


@dataclass
class ImageInfo:
    kind: Optional[str] = None      # PNG / JPEG / GIF / BMP / WEBP
    end_offset: Optional[int] = None  # 图片主体结束的字节位置
    note: str = ""


def is_image_name(name: str) -> bool:
    i = name.rfind(".")
    return i > 0 and name[i:].lower() in IMAGE_EXTS


def sniff(b: bytes) -> ImageInfo:
    info = ImageInfo()
    n = len(b)

    # PNG：逐块走到 IEND
    if n > 24 and b[0] == 0x89 and b[1] == 0x50 and b[2] == 0x4E and b[3] == 0x47:
        info.kind = "PNG"
        p = 8
        while p + 8 <= n:
            length = (b[p] << 24) | (b[p + 1] << 16) | (b[p + 2] << 8) | b[p + 3]
            ctype = b[p + 4:p + 8].decode("latin-1")
            nxt = p + 8 + length + 4
            if nxt <= p or nxt > n:
                break
            if ctype == "IEND":
                info.end_offset = nxt
                break
            p = nxt
        return info

    # JPEG：逐段走，遇到 EOI(FFD9)
    if n > 4 and b[0] == 0xFF and b[1] == 0xD8:
        info.kind = "JPEG"
        p, guard = 2, 0
        while p + 1 < n and guard < 800000:
            guard += 1
            if b[p] != 0xFF:
                p += 1
                continue
            m = b[p + 1]
            if m == 0xD9:
                info.end_offset = p + 2
                break
            if m == 0x01 or 0xD0 <= m <= 0xD7:
                p += 2
                continue
            if m == 0xDA:
                # 扫描段：跳过熵编码数据，注意 FF00 是字节填充，不是标记
                p += 2
                while p + 1 < n:
                    if b[p] == 0xFF and b[p + 1] != 0x00 and not (0xD0 <= b[p + 1] <= 0xD7):
                        break
                    p += 1
                continue
            if m == 0x00 or m == 0xFF:
                p += 1
                continue
            if p + 4 > n:
                break
            seg = (b[p + 2] << 8) | b[p + 3]
            if seg < 2:
                break
            p += 2 + seg
        return info

    # GIF：最后一个 0x3B
    if n > 12 and b[0] == 0x47 and b[1] == 0x49 and b[2] == 0x46:
        info.kind = "GIF"
        for i in range(n - 1, 12, -1):
            if b[i] == 0x3B:
                info.end_offset = i + 1
                break
        return info

    # BMP：文件头的尺寸字段
    if n > 14 and b[0] == 0x42 and b[1] == 0x4D:
        info.kind = "BMP"
        v = b[2] | (b[3] << 8) | (b[4] << 16) | (b[5] << 24)
        if 14 < v <= n:
            info.end_offset = v
        return info

    # WEBP：RIFF 块长度
    if (n > 12 and b[0] == 0x52 and b[1] == 0x49 and b[2] == 0x46 and b[3] == 0x46):
        info.kind = "WEBP"
        v = b[4] | (b[5] << 8) | (b[6] << 16) | (b[7] << 24)
        if 0 < v and v + 8 <= n:
            info.end_offset = v + 8
        return info

    return info


# 附加数据的类型猜测（只用于起个像样的文件名，不参与拆分逻辑）
_SIGS = [
    ("ZIP", bytes([0x50, 0x4B, 0x03, 0x04]), ".zip", 0),
    ("ZIP", bytes([0x50, 0x4B, 0x05, 0x06]), ".zip", 0),
    ("RAR", bytes([0x52, 0x61, 0x72, 0x21, 0x1A, 0x07]), ".rar", 0),
    ("7Z", bytes([0x37, 0x7A, 0xBC, 0xAF, 0x27, 0x1C]), ".7z", 0),
    ("GZIP", bytes([0x1F, 0x8B, 0x08]), ".gz", 0),
    ("MP4", bytes([0x66, 0x74, 0x79, 0x70]), ".mp4", 4),
    ("PDF", bytes([0x25, 0x50, 0x44, 0x46]), ".pdf", 0),
]


def guess_type(tail: bytes) -> Optional[tuple]:
    """返回 (type, ext) 或 None。"""
    for name, sig, ext, at in _SIGS:
        if len(tail) < at + len(sig):
            continue
        if tail[at:at + len(sig)] == sig:
            return name, ext
    return None
