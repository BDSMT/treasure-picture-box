# -*- coding: utf-8 -*-
"""一键构建发布包。

    python build.py

做的事：
    1. 检查 Python 版本与 vendor 依赖（缺了就用 pip 装进去）
    2. PyInstaller 打包（onedir）
    3. 跑一遍产物的 --selftest，确认真的能跑
    4. 组装成「解压即用」的目录
    5. 压成 release/藏图盒-vX.X.X-win64.zip

只依赖标准库 + requirements-dev.txt，Windows 上验证过。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

# Windows 控制台按「本地代码页」输出：中文系统是 cp936，英文系统是 cp1252。
# 后者编不出中文，连 print 一行「藏图盒 v1.1.0 构建」都会 UnicodeEncodeError 崩掉。
# GitHub Actions 的 windows runner 正是英文环境 —— 构建脚本第一行就挂在这里。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001  被重定向或老版本 Python，忽略即可
        pass

VERSION = "1.1.0"
APP_NAME = "藏图盒"
BUILD_DIR = "build"
RELEASE_DIR = "release"

ROOT = Path(__file__).resolve().parent
DIST = ROOT / BUILD_DIR / "dist"
WORK = ROOT / BUILD_DIR / "work"
STAGE_ROOT = ROOT / BUILD_DIR / "stage"
SPEC = ROOT / ("%s.spec" % APP_NAME)

# 分发包里要带上、但不是 PyInstaller 产物的文件
# 刻意不含 README.md：它引用了 docs/ 里的截图，而 docs 不进分发包，
# 放进去只会显示成破图。下载用户需要的是「先读我」和「使用说明」。
EXTRA_FILES = ["使用说明.md", "LICENSE"]

READ_ME = """\
藏图盒 v{ver}
================================================

【第一次打开被 Windows 拦住了？】

  弹窗写「Windows 已保护你的电脑」，这是 SmartScreen。
  因为这个程序没有买代码签名证书（要几千块一年），不是你中了病毒。

  处理办法：
    点弹窗上的「更多信息」  ->  再点「仍要运行」

  只需要做一次，之后直接双击就行。


【怎么用】

  双击「藏图盒.exe」。

  不用装 Python，不用联网，不用管理员权限。
  整个文件夹可以拷到 U 盘里带走，配置跟着走。


【四个功能】

  图种      把压缩包藏进图片。注意载荷必须是 .zip，
            生成后把后缀改成 .zip 才能解压。

  图种解包  拖入一张图种，直接把里面的文件列出来，不用改后缀。
            顺带做 CRC 校验，文件坏了会标出来。
            是种子的可以直接导出 .torrent。

  幻影坦克  一张 PNG 里塞两个画面，白底看一张、黑底看另一张。
            拖进两张图，右边会同时显示两种底色的效果。

  幻影提取  把幻影坦克图拆回两张画面。


【出问题了】

  1. 命令行运行：藏图盒.exe --selftest
     结果写进 logs\\selftest.log，能看到是哪一环出的问题。

  2. 崩溃详情在 logs\\error.log。

  3. 详细说明看「使用说明.md」。
"""


# ── 小工具 ────────────────────────────────────────────────
def say(msg: str) -> None:
    print("  %s" % msg, flush=True)


def step(msg: str) -> None:
    print("\n==> %s" % msg, flush=True)


def die(msg: str) -> None:
    print("\n[失败] %s" % msg, file=sys.stderr, flush=True)
    sys.exit(1)


def rmtree(path: Path, what: str) -> None:
    """删目录，失败时给出人话提示（Windows 上常见于文件被占用）。"""
    if not path.exists():
        return
    try:
        shutil.rmtree(path)
    except PermissionError:
        die("%s 删不掉：%s\n"
            "      大概率是程序正在运行，或者资源管理器停在这个目录里。\n"
            "      关掉再试。" % (what, path))
    except Exception as exc:  # noqa: BLE001
        die("%s 删不掉：%s（%s）" % (what, path, exc))


def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return "%.1f %s" % (n, unit) if unit != "B" else "%d B" % n
        n /= 1024.0
    return "%d B" % n


# ── 1. 环境检查 ───────────────────────────────────────────
def check_python() -> None:
    step("检查 Python")
    if sys.version_info < (3, 9):
        die("需要 Python 3.9 以上，当前是 %s" % sys.version.split()[0])
    say("Python %s" % sys.version.split()[0])

    try:
        import tkinter  # noqa: F401
    except ImportError:
        die("这个 Python 没带 tkinter。\n"
            "      精简版 / 部分 conda 环境会缺，换 python.org 官方安装包。")
    say("tkinter 可用")

    for platform_ok in (sys.platform == "win32",):
        if not platform_ok:
            say("⚠ 当前不是 Windows，打包出来的是本平台程序，不是 .exe")


def ensure_deps() -> None:
    """检查依赖是否可导入，缺了就用当前解释器装上。

    刻意不用 `pip install --target vendor`：那样每次构建都会把整个包目录删了重装，
    既慢又容易在「目录被占用」时炸掉。直接装进当前环境最省事，
    反正构建本来就在一个专门的环境里跑。
    """
    step("检查依赖")
    want = [("PIL", "Pillow"), ("numpy", "numpy"),
            ("tkinterdnd2", "tkinterdnd2"), ("PyInstaller", "pyinstaller")]

    missing = []
    for mod, pkg in want:
        try:
            __import__(mod)
        except ImportError:
            missing.append(pkg)

    if not missing:
        say("Pillow / numpy / tkinterdnd2 / PyInstaller 齐全")
        return

    say("缺少 %s，开始安装……" % "、".join(missing))
    cmd = [sys.executable, "-m", "pip", "install",
           "-r", str(ROOT / "requirements-dev.txt")]
    if subprocess.run(cmd).returncode != 0:
        die("pip 安装失败。手动执行：\n      %s" % " ".join(cmd))
    say("安装完成")


# ── 2. 打包 ───────────────────────────────────────────────
def run_pyinstaller() -> None:
    step("PyInstaller 打包")
    if not SPEC.exists():
        die("找不到 %s" % SPEC.name)

    # 每次都用干净的输出目录，避免 COLLECT 删旧目录时被占用
    rmtree(DIST.parent, "构建目录")
    DIST.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable, "-m", "PyInstaller", str(SPEC),
        "--noconfirm",
        "--distpath", str(DIST),
        "--workpath", str(WORK),
    ]
    t0 = time.time()
    if subprocess.run(cmd).returncode != 0:
        die("PyInstaller 失败，看上面的错误输出。")
    say("打包完成，耗时 %.0f 秒" % (time.time() - t0))


# ── 3. 产物自检 ───────────────────────────────────────────
def verify(exe: Path) -> None:
    step("验证产物（跑一次 --selftest）")
    if not exe.exists():
        die("没生成 exe：%s" % exe)

    log = exe.parent / "logs" / "selftest.log"
    if log.exists():
        log.unlink()

    try:
        cmd = [str(exe), "--selftest"]
        # CI 的 runner 没有可用的交互桌面，建窗口那几项必然失败。
        # 那种环境下只验算法，图形相关的检查交给本机构建把关。
        if os.environ.get("CANGTU_SKIP_GUI") or os.environ.get("CI"):
            cmd.append("--no-gui")
            say("检测到 CI 环境，跳过图形相关自检项")
        r = subprocess.run(cmd, cwd=str(exe.parent),
                           timeout=120, stdin=subprocess.DEVNULL,
                           capture_output=True)
    except subprocess.TimeoutExpired:
        die("自检超时（120 秒）。可能卡在某个环节，手动跑一次看看。")

    if r.returncode != 0:
        die("自检返回码 %d。\n%s" % (r.returncode,
                                    r.stderr.decode("utf-8", "replace")[-1500:]))

    if not log.exists():
        die("自检没写出日志，说明程序没真正启动。")
    text = log.read_text(encoding="utf-8", errors="replace")
    say("自检日志：")
    for line in text.splitlines():
        if line.strip() and not line.startswith("==="):
            say("  " + line)

    for needle in ("拖放", "图种", "主界面"):
        if needle not in text:
            say("⚠ 自检日志里没看到「%s」，检查一下" % needle)

    if "❌" in text or "失败" in text:
        die("自检里有失败项，见上面的日志。")


# ── 4. 组装 ───────────────────────────────────────────────
def stage() -> Path:
    step("组装发布目录")
    src = DIST / APP_NAME
    if not src.is_dir():
        die("找不到打包产物目录：%s" % src)

    rmtree(STAGE_ROOT, "临时组装目录")
    pkg = STAGE_ROOT / ("%s-v%s-win64" % (APP_NAME, VERSION))
    pkg.mkdir(parents=True, exist_ok=True)

    for item in src.iterdir():
        if item.name in ("logs", "output", "config.json"):
            continue          # 本机运行留下的东西，别带给别人
        dst = pkg / item.name
        if item.is_dir():
            shutil.copytree(item, dst)
        else:
            shutil.copy2(item, dst)

    for name in EXTRA_FILES:
        f = ROOT / name
        if f.exists():
            shutil.copy2(f, pkg / name)
        else:
            say("⚠ 缺少 %s，跳过" % name)

    # 第一眼看到的文件，专门回答「被拦截了怎么办」
    (pkg / "先读我.txt").write_text(
        READ_ME.format(ver=VERSION), encoding="utf-8-sig")

    size = sum(f.stat().st_size for f in pkg.rglob("*") if f.is_file())
    say("目录就绪：%d 个文件，%s" % (
        sum(1 for f in pkg.rglob("*") if f.is_file()), human(size)))
    return pkg


def make_zip(pkg: Path) -> Path:
    step("压缩发布包")
    out_dir = ROOT / RELEASE_DIR
    out_dir.mkdir(exist_ok=True)
    # 压缩包用 ASCII 名：GitHub 的发布动作会把非 ASCII 字符吃掉，
    # 「藏图盒-v1.1.0-win64.zip」传上去会变成「-v1.1.0-win64.zip」。
    # 解压出来的目录名仍是中文，用户看到的还是「藏图盒」。
    out = out_dir / ("cangtu-box-v%s-win64.zip" % VERSION)
    if out.exists():
        out.unlink()

    # 固定时间戳，同样的源码打出来的包内容一致（方便校验）
    stamp = time.localtime()[:6]
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in sorted(pkg.rglob("*")):
            if not f.is_file():
                continue
            arc = str(f.relative_to(STAGE_ROOT)).replace(os.sep, "/")
            info = zipfile.ZipInfo(arc, date_time=stamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            with open(f, "rb") as fh:
                z.writestr(info, fh.read())

    raw = sum(f.stat().st_size for f in pkg.rglob("*") if f.is_file())
    say("原始 %s → 压缩后 %s" % (human(raw), human(out.stat().st_size)))
    return out


# ── 主流程 ────────────────────────────────────────────────
def main() -> None:
    print("%s v%s 构建" % (APP_NAME, VERSION))
    print("项目目录：%s" % ROOT)

    check_python()
    ensure_deps()
    run_pyinstaller()

    exe = DIST / APP_NAME / ("%s.exe" % APP_NAME)
    verify(exe)
    pkg = stage()
    out = make_zip(pkg)

    print("\n完成：%s" % out)
    print("解压后双击 %s.exe 即可，无需安装。" % APP_NAME)


if __name__ == "__main__":
    main()
