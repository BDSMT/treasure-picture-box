# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 打包配置

产物：dist\藏图盒\  （onedir 模式）
  · 启动快（不用每次解压几十 MB）
  · 和「视频转格式」用同一套打包方式，方便一起维护

关键点：
  tkinterdnd2 的拖放依赖 tkdnd 的原生二进制 + tcl 脚本，
  它们不是 .py，PyInstaller 不会自动收集，必须手动放进 datas，
  并且路径要落在 `tkinterdnd2/tkdnd` 下（包内部按这个相对路径找）。

  numpy 和 Pillow 是合成算法的必需品，不能像视频工具那样排除掉 ——
  纯 Python 逐像素处理 2600×2600 的图会慢到不可接受。
"""
import os
import sys

ROOT = os.path.abspath(SPECPATH)
VENDOR = os.path.join(ROOT, "vendor")

# vendor/ 是可选的：存在就用它里面的依赖（便携构建），
# 不存在就用当前 Python 环境装的（pip install -r requirements-dev.txt）。
pathex = [ROOT]
if os.path.isdir(VENDOR):
    sys.path.insert(0, VENDOR)
    pathex.insert(0, VENDOR)
    print("[spec] 依赖来源: vendor/")
else:
    print("[spec] 依赖来源: 当前 Python 环境")

# ---- 收集 tkinterdnd2 的 tkdnd 数据 ----
dnd_datas = []
try:
    import tkinterdnd2

    tkdnd_src = os.path.join(os.path.dirname(tkinterdnd2.__file__), "tkdnd")
    if os.path.isdir(tkdnd_src):
        dnd_datas.append((tkdnd_src, os.path.join("tkinterdnd2", "tkdnd")))
        print("[spec] tkdnd 已收集:", tkdnd_src)
    else:
        print("[spec] ⚠ 找不到 tkdnd 目录:", tkdnd_src)
except Exception as exc:  # noqa: BLE001
    print("[spec] ⚠ 导入 tkinterdnd2 失败，拖放将不可用:", exc)

a = Analysis(
    [os.path.join(ROOT, "藏图盒.py")],
    pathex=pathex,
    binaries=[],
    datas=dnd_datas,
    hiddenimports=[
        "tkinterdnd2", "tkinterdnd2.TkinterDnD",
        "core.paths", "core.sniff", "core.seed", "core.phantom",
        "core.reveal", "core.imageio", "core.unpack", "core.zipfix",
        "ui.app", "ui.theme", "ui.widgets",
        "PIL._tkinter_finder",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "matplotlib", "scipy", "pandas", "notebook", "IPython",
        "PyQt5", "PyQt6", "PySide2", "PySide6", "wx",
        "pytest", "setuptools", "pip", "unittest",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="藏图盒",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,                    # GUI 程序，不弹黑窗
    disable_windowed_traceback=False, # 崩溃时弹 traceback，便于排查
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="藏图盒",
)
