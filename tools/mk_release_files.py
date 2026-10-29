# -*- coding: utf-8 -*-
"""生成发布目录里的 config.json 与 启动.cmd（一次性脚本）。"""
import io
import json
import os
import sys

DST = os.path.join("D:" + os.sep, "藏图盒")
BS = chr(92)  # 反斜杠，避免被各种 shell 转义搞乱

cfg = {
    "theme": "dark",
    "bright": 55,
    "boost": False,
    "reveal_auto": True,
    "reveal_factor": 2.0,
    "max_side": 2600,
    "last_dir": "",
}
io.open(os.path.join(DST, "config.json"), "w", encoding="utf-8").write(
    json.dumps(cfg, ensure_ascii=False, indent=2)
)

lines = [
    "@echo off",
    "chcp 936 >nul",
    "rem \u6e90\u7801\u8fd0\u884c\u7528\uff1b\u5e73\u65f6\u76f4\u63a5\u53cc\u51fb \u85cf\u56fe\u76d2.exe",
    'cd /d "%~dp0"',
    'start "" "H:' + BS + "Python3.10.11" + BS + 'pythonw.exe" "%~dp0'
    + "\u85cf\u56fe\u76d2.py\"",
]
data = ("\r\n".join(lines) + "\r\n").encode("gbk")
with open(os.path.join(DST, "\u542f\u52a8.cmd"), "wb") as f:
    f.write(data)

print("config.json 已写入")
print("启动.cmd 已写入：%d 字节，无 BOM，CRLF，GBK" % len(data))
