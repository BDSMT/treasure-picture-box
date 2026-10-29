# -*- coding: utf-8 -*-
"""藏图盒 —— 启动入口

双击「启动.cmd」或用 pythonw 运行本文件。
用 Python 3.10（H:\\Python3.10.11）启动，因为该版本自带 tkinter；
WorkBuddy 托管的 3.13 精简版不含 tkinter。
"""
from __future__ import annotations

import ctypes
import os
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# 源码运行时把 vendor（Pillow / tkinterdnd2）挂进搜索路径；
# 打包后这些已经被收进程序内部，不需要也不应该再找目录。
if not getattr(sys, "frozen", False):
    for sub in ("vendor", ""):
        p = ROOT / sub if sub else ROOT
        if p.is_dir() and str(p) not in sys.path:
            sys.path.insert(0, str(p))

if getattr(sys, "frozen", False):
    ROOT = Path(sys.executable).resolve().parent
    try:
        os.chdir(ROOT)
    except OSError:
        pass


def _fatal(title: str, body: str):
    try:
        import tkinter as tk
        from tkinter import messagebox

        r = tk.Tk()
        r.withdraw()
        messagebox.showerror(title, body)
        r.destroy()
    except Exception:  # noqa: BLE001
        sys.stderr.write("%s\n%s\n" % (title, body))


def _selftest() -> int:
    """`藏图盒.exe --selftest`

    打包后没有控制台，出问题看不到内部状态。这里把关键能力逐项验证，
    并且真的做一次「合成 → 提取 → 比对」和「打包 → 拆分」往返。
    """
    import tempfile

    lines = []

    def log(m):
        lines.append(str(m))

    def flush():
        try:
            from core.paths import write_log

            write_log("selftest.log", "\n".join(lines))
        except Exception:  # noqa: BLE001
            pass

    try:
        log("=== 藏图盒 自检 ===")
        log("程序目录: %s" % ROOT)
        log("打包运行: %s" % bool(getattr(sys, "frozen", False)))
        log("Python: %s" % sys.version.split()[0])

        try:
            import PIL

            log("Pillow: %s" % PIL.__version__)
        except Exception as exc:  # noqa: BLE001
            log("Pillow: ❌ %s" % exc)

        try:
            import numpy

            log("numpy: %s" % numpy.__version__)
        except Exception as exc:  # noqa: BLE001
            log("numpy: ❌ %s" % exc)

        try:
            import tkinterdnd2

            log("tkinterdnd2: 已内置 %s" % tkinterdnd2.__file__)
            d = Path(tkinterdnd2.__file__).parent / "tkdnd"
            log("  tkdnd 目录: %s (存在=%s)" % (d, d.is_dir()))
        except Exception as exc:  # noqa: BLE001
            log("tkinterdnd2: ❌ %s" % exc)

        try:
            from tkinterdnd2 import DND_FILES, TkinterDnD

            r = TkinterDnD.Tk()
            r.withdraw()
            r.drop_target_register(DND_FILES)
            r.update()
            r.destroy()
            log("拖放: ✅ 可用")
        except Exception as exc:  # noqa: BLE001
            log("拖放: ❌ %s" % exc)

        tmp = Path(tempfile.mkdtemp(prefix="seedbox_"))
        try:
            from PIL import Image

            from core import phantom, reveal, seed

            # 造两张 240×180 的测试图：前景偏亮（留余量），背景是渐变
            fg = Image.new("RGB", (240, 180), (232, 228, 220))
            px = fg.load()
            for y in range(180):
                for x in range(240):
                    px[x, y] = (200 + x % 40, 205 + y % 30, 215)
            fg_p, bg_p = tmp / "fg.png", tmp / "bg.png"
            fg.save(fg_p, "PNG")

            bg = Image.new("RGB", (240, 180))
            bp = bg.load()
            for y in range(180):
                for x in range(240):
                    v = int(120 * (x / 240) + 40 * (y / 180))
                    bp[x, y] = (v, v, v)
            bg.save(bg_p, "PNG")

            # ── 幻影坦克：合成 ────────────────────────
            res = phantom.compose(Image.open(fg_p).convert("RGBA"),
                                  Image.open(bg_p).convert("RGBA"),
                                  bright=0.55, boost=False, max_side=240)
            log("合成: %d×%d 支撑度=%.3f 余量吃满=%.1f%% 裁掉=%.1f%%"
                % (res.width, res.height, res.stat.support,
                   res.stat.clamp_ratio * 100, (1 - res.stat.keep_area) * 100))
            out_p = tmp / "phantom.png"
            res.image.save(out_p, "PNG")
            log("产物: %s (%d 字节)" % (out_p.name, out_p.stat().st_size))

            # ── 白底合成应当精确还原前景 ──────────────
            back = reveal.build_fg(Image.open(out_p).convert("RGBA"))
            import numpy as np

            a = np.asarray(back.convert("RGB"), dtype=np.int16)
            b = np.asarray(Image.open(fg_p).convert("RGB"), dtype=np.int16)
            diff = np.abs(a - b)
            log("前景还原: 最大误差=%d 平均误差=%.3f (应≈0)"
                % (int(diff.max()), float(diff.mean())))

            # ── 提取：自动提亮 + 黑底 ─────────────────
            an = reveal.analyze(Image.open(out_p).convert("RGBA"))
            k = reveal.auto_reveal(Image.open(out_p).convert("RGBA"))
            log("提取识别: 半透明像素=%.1f%% phantom=%s 自动提亮=%.2f×"
                % (an.mid * 100, an.phantom, k))
            hid = reveal.build_bg(Image.open(out_p).convert("RGBA"), k)
            log("隐藏图: %d×%d 已生成" % hid.size)

            # ── 图种：打包 + 拆分往返 ─────────────────
            import io as _io
            import zipfile as _zf

            buf = _io.BytesIO()
            with _zf.ZipFile(buf, "w", _zf.ZIP_DEFLATED) as zf:
                zf.writestr("自检.txt", "自检用的真实压缩包\n" * 60)
                zf.writestr("子目录/深层.txt", b"deep" * 200)
            pay_bytes = buf.getvalue()

            pay_p = tmp / "payload.zip"
            pay_p.write_bytes(pay_bytes)
            r2 = seed.pack(fg_p, pay_p)
            seed_p = tmp / "out_seed.png"
            seed.write(r2, seed_p)
            log("图种: 图片 %d + 载荷 %d = %d 字节（载荷类型=%s）"
                % (r2.cover_len, r2.payload_len, len(r2.data),
                   r2.payload_type or "未知"))

            # 偏移必须已修正，否则严格的解压器（7-Zip 等）会拒绝
            from core import zipfix as _zf2

            lay = _zf2.describe(r2.data)
            log("图种偏移: 偏差=%+d（应为 0）修正=%s"
                % (lay.get("dev", 999), r2.patched))
            with _zf.ZipFile(_io.BytesIO(r2.data)) as zz:
                names = zz.namelist()
                bad = zz.testzip()
            log("图种可解压: %d 项 坏文件=%s" % (len(names), bad))

            sp = seed.split(seed_p)
            log("拆分: 尾部 %d 字节 类型=%s 还原一致=%s"
                % (len(sp.tail), sp.tail_type, sp.tail == pay_bytes))
            with _zf.ZipFile(_io.BytesIO(sp.tail)) as zz2:
                log("拆分后可解压: %d 项" % len(zz2.namelist()))
        finally:
            try:
                import shutil

                shutil.rmtree(tmp, ignore_errors=True)
            except Exception:  # noqa: BLE001
                pass

        # ── 主界面能否创建 ────────────────────────────
        try:
            from ui.app import App, _system_dpi

            app = App()               # 构造时才开启 DPI 感知，所以要在这之后读尺寸
            app.withdraw()
            app.update()

            dpi = _system_dpi()
            log("屏幕: dpi=%d 缩放=%.2f 分辨率=%dx%d"
                % (dpi, dpi / 96.0,
                   ctypes.windll.user32.GetSystemMetrics(0),
                   ctypes.windll.user32.GetSystemMetrics(1)))
            log("主窗口: %dx%d（含标题栏）"
                % (app.winfo_width(), app.winfo_height()))
            tabs = []
            for key in ("seed", "phantom", "reveal"):
                app.tab = key
                app.build()
                app.update()
                tabs.append(key)
            app.destroy()
            log("主界面: ✅ 三个模块均可创建（%s）" % ", ".join(tabs))
        except Exception:  # noqa: BLE001
            log("主界面: ❌\n" + traceback.format_exc())

        log("=== 自检结束 ===")
    except Exception:  # noqa: BLE001
        log("异常:\n" + traceback.format_exc())

    flush()
    return 0


def main() -> int:
    if "--selftest" in sys.argv:
        return _selftest()

    try:
        import tkinter  # noqa: F401
    except ImportError:
        _fatal("缺少图形库",
               "当前 Python 没有 tkinter，无法显示界面。\n\n"
               "请改用自带 tkinter 的 Python 运行，例如：\n"
               "  H:\\Python3.10.11\\pythonw.exe 藏图盒.py")
        return 2

    if not getattr(sys, "frozen", False):
        if not (ROOT / "core" / "phantom.py").exists():
            _fatal("文件不完整",
                   "找不到 core 目录，请确认整个「藏图盒程序」文件夹是完整的。")
            return 3

    try:
        from ui.app import run

        run()
        return 0
    except Exception:  # noqa: BLE001
        detail = traceback.format_exc()
        try:
            from core.paths import write_log

            write_log("error.log", detail)
        except Exception:  # noqa: BLE001
            pass
        _fatal("程序启动失败",
               "启动时发生错误，详情已写入 logs\\error.log\n\n"
               + detail.strip().splitlines()[-1][:300])
        return 1


if __name__ == "__main__":
    sys.exit(main())
