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
    # 插件目录随包带上，落在 _internal/plugins。
    # 它是「出厂预装」的那一份：用户目录（程序目录/plugins）优先，
    # 所以删掉这里的不会丢失能力 —— 用户那边有同名 id 就会被覆盖。
    # 刻意是数据文件而不是 hiddenimports：插件要在运行期按路径 import，
    # 让 PyInstaller 静态分析它们，反而会被打进 PYZ 而丢失源码路径。
    # 里面的 manifest.json 是运行期状态，build.py 在打包前会先删掉它。
    datas=dnd_datas + [(os.path.join(ROOT, "plugins"), "plugins")],
    hiddenimports=[
        "tkinterdnd2", "tkinterdnd2.TkinterDnD",
        "core.paths", "core.sniff", "core.seed", "core.phantom",
        "core.reveal", "core.imageio", "core.unpack", "core.zipfix",
        "core.matting",
        "cangtu.api", "cangtu.loader", "cangtu.tasks", "cangtu.spinner",
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
        # onnxruntime / opencv 的可选后端会把整个 PyTorch 拖进来（371 MB），
        # 抠图只用 onnxruntime 的 CPU provider，不碰 torch。
        "torch", "torchvision", "torchaudio", "torchtext",
        "tensorflow", "jax", "transformers", "accelerate",
        "sklearn", "skimage", "sympy", "networkx",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

# cv2 的包体里有一大半是抠图用不到的东西：
#   opencv_videoio_ffmpeg  27 MB —— 视频解码，本工具只处理静态图
#   cv2/data/haarcascade*    ~8 MB —— 人脸/人脸识别级联数据
# 剔掉它们能省约 35 MB，不影响任何功能。
_DROP = ("opencv_videoio_ffmpeg", "cv2/data/haarcascade", "cv2/data/lbpcascade")

# torch 是被 onnxruntime 的 hook 用 collect_all 当作二进制/数据收集进来的，
# 光靠上面的 excludes 拦不住（excludes 只作用于模块图，不作用于收集到的二进制）。
# 抠图只用 CPU 推理，torch 及其 DLL 完全用不到，这里在收集层直接剥掉，省约 370 MB。
_DROP += ("torch",)
a.binaries = [b for b in a.binaries if not any(k in b[0] for k in _DROP)]
a.datas = [d for d in a.datas if not any(k in d[0] for k in _DROP)]
print("[spec] 已剔除 cv2 视频解码 / 人脸级联 / torch")

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
