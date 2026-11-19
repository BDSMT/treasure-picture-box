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


def _say(title: str, body: str):
    """给窗口版程序用的「打印」。

    打包成 console=False 之后 sys.stdout 是 None，直接 print 会抛 AttributeError ——
    开发时看不出来，打包后一跑 --plugins 就静默崩掉。所以这里必须防一手。
    """
    try:
        if sys.stdout is not None:
            print(body)
    except Exception:  # noqa: BLE001
        pass
    if not getattr(sys, "frozen", False) or "--quiet" in sys.argv:
        return
    try:
        import tkinter as tk
        from tkinter import messagebox

        r = tk.Tk()
        r.withdraw()
        messagebox.showinfo(title, body)
        r.destroy()
    except Exception:  # noqa: BLE001
        pass


def plugin_roots() -> tuple:
    """(用户插件目录, [随包插件目录])。

    打包后随包的插件在 _internal/plugins，用户装的在程序目录/plugins。
    两者的优先级由 loader 决定：用户的覆盖随包的。
    """
    user = ROOT / "plugins"
    bundled = []
    base = getattr(sys, "_MEIPASS", None)
    if base:
        p = Path(base) / "plugins"
        try:
            if p.resolve() != user.resolve():
                bundled.append(p)
        except OSError:
            bundled.append(p)
    return user, bundled


def _plugins_cli() -> int:
    """`藏图盒.exe --plugins` —— 不启动界面，只看插件状态。

    打包后是窗口程序，没有控制台，print 出去就没了。
    所以报告同时写 logs/plugins.log，并用弹窗显示一份 —— 用户点了能看到。
    """
    from cangtu.loader import PluginManager

    user, bundled = plugin_roots()
    pm = PluginManager(user, bundled)
    pm.discover()

    lines = ["插件目录：%s" % user]
    if bundled:
        lines.append("随包目录：%s" % bundled[0])
    lines.append("")
    if not pm.metas():
        lines.append("一个插件都没找到 —— 程序目录下的 plugins\\ 可能被删了。")
    else:
        lines.extend("  " + s for s in pm.report())
        lines.append("")
        lines.append("共 %d 个模块。停用某个插件：改 plugins\\manifest.json 里对应的 enabled。"
                     % len(pm.metas()))
    body = "\n".join(lines)
    try:
        from core.paths import write_log

        write_log("plugins.log", body)
    except Exception:  # noqa: BLE001
        pass
    _say("藏图盒 · 插件状态", body)
    return 0


def _install_cli(path: str, remove: bool = False) -> int:
    from cangtu.loader import PluginError, PluginManager

    user, bundled = plugin_roots()
    pm = PluginManager(user, bundled)
    pm.discover()
    try:
        if remove:
            pm.uninstall(pm.find(path) or path)
            _say("藏图盒 · 卸载插件", "已卸载「%s」。" % path)
        else:
            pid = pm.install(path)
            _say("藏图盒 · 安装插件",
                 "已安装「%s」，重启藏图盒就能在侧栏看到。" % pid)
    except PluginError as exc:
        _say("藏图盒", "操作失败：%s" % exc)
        return 1
    except Exception as exc:  # noqa: BLE001
        _say("藏图盒", "操作失败：%s: %s" % (type(exc).__name__, exc))
        return 1
    return 0


def _selftest() -> int:
    """`藏图盒.exe --selftest`

    打包后没有控制台，出问题看不到内部状态。这里把关键能力逐项验证，
    并且真的做一次「合成 → 提取 → 比对」和「打包 → 拆分」往返。
    """
    import tempfile

    # CI / 远程构建的机器上没有可用的交互桌面，建窗口必然抛异常。
    # 这类环境只验算法，图形相关的项明确标成「跳过」而不是「失败」。
    no_gui = ("--no-gui" in sys.argv
              or os.environ.get("CANGTU_SKIP_GUI") == "1")

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

        if no_gui:
            log("拖放: ⏭ 跳过（无图形环境）")
        else:
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

        # ── 插件框架 ──────────────────────────────────
        # 放在算法测试之前：这块要证明的是「启动阶段不为重依赖付费」，
        # 等抠图自检把 cv2 import 进来之后再看就没意义了。
        try:
            import time as _t

            from cangtu.loader import PluginManager

            _user, _bundled = plugin_roots()
            _pm = PluginManager(_user, _bundled)
            _metas = _pm.discover()
            log("插件: 发现 %d 个（%s）"
                % (len(_metas), ", ".join(m.id for m in _metas)))
            for line in _pm.report():
                log("  " + line)
            if "unpack" in [m.id for m in _metas]:
                _t0 = _t.time()
                _p = _pm.load("unpack")
                log("按需加载: unpack -> %s（%.2f 秒）"
                    % (type(_p).__name__, _t.time() - _t0))
                # 这条是关键证据：翻遍所有清单、把 unpack 加载起来之后，
                # 抠图那 100 MB 的 cv2 依然没被 import。
                log("懒加载: 此时 cv2 已导入=%s（应为 False）" % ("cv2" in sys.modules))
                _ok, _why = _pm.check("unpack")
                log("unpack 自检: %s%s" % ("✅" if _ok else "❌", "" if _ok else _why))
                _pm.unload("unpack")
                log("卸载: 模块缓存已清=%s"
                    % ("_cangtu_plugin_unpack" not in sys.modules))
        except Exception:  # noqa: BLE001
            log("插件: ❌\n" + traceback.format_exc())

        # ── 分卷解压后端 ──────────────────────────────
        # 7z.exe 是随包带的，找不到就说明打包漏了文件或者被杀软隔离了 ——
        # 这两种情况用户自己很难判断，必须在自检里点名。
        try:
            from core import splitvol as _sv

            _ok, _why = _sv.backend()
            log("分卷后端: %s %s" % ("✅" if _ok else "❌", _why))
            log("  7z 路径: %s" % (_sv.exe() or "（未找到）"))
        except Exception:  # noqa: BLE001
            log("分卷后端: ❌\n" + traceback.format_exc())


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

            # ── 解包：把刚做出来的图种原样拆回来 ───────
            from core import unpack as _un

            ur = _un.unpack(seed_p)
            with _zf.ZipFile(_io.BytesIO(pay_bytes)) as z0:
                origin = {zi.filename: z0.read(zi) for zi in z0.infolist()}
            got = {e.name: e.data for e in ur.entries}
            log("解包识别: 图片=%s 载荷=%s 文件=%d 偏移还原=%s"
                % (ur.image_kind, ur.payload_type, len(ur.entries),
                   ur.offset_fixed))
            log("解包内容: CRC 全通过=%s 与原始载荷一致=%s"
                % (all(e.crc_ok for e in ur.entries), got == origin))

            # 附带验证种子解析与 infohash
            import hashlib as _hl

            _tinfo = (b"d6:lengthi1024e4:name4:demo12:piece lengthi16384e6:"
                      b"pieces20:" + b"A" * 20 + b"e")
            _url = b"http://tracker.test/ann"
            _tor = (b"d8:announce" + str(len(_url)).encode() + b":" + _url
                    + b"4:info" + _tinfo + b"e")
            _ti = _un.torrent_info(_tor)
            log("种子解析: 名称=%s 文件数=%d 大小=%d infohash 正确=%s"
                % (_ti.name, _ti.files, _ti.size,
                   _ti.infohash == _hl.sha1(_tinfo).hexdigest()))

            # ── 抠图：造一张「纯色底 + 主体 + 细发丝」的图验收 ──
            from core import matting as _mat

            try:
                import cv2 as _cv
                import numpy as _np

                # AI 模型是外置的（发布包不带，用户自己放 models/），
                # 这里只报告「有没有、能不能加载」，不作为硬性失败项。
                _mp = _mat.find_model()
                if _mp:
                    try:
                        _sess = _mat._session_get(_mp)
                        log("抠图模型: %s 加载=%s（AI 模式可用）"
                            % (_mp.name, _sess is not None))
                    except Exception as _me:  # noqa: BLE001
                        log("抠图模型: %s 加载失败=%s" % (_mp.name, _me))
                else:
                    log("抠图模型: 未找到（纯算法模式，复杂背景能力受限）")

                # 白底、深灰主体、五条两像素宽的细线（模拟发梢）
                _W = _H = 400
                _canvas = _np.full((_H, _W, 3), 255, _np.uint8)
                _cv.circle(_canvas, (200, 230), 85, (70, 70, 78), -1)
                for _i in range(5):
                    _x = 150 + _i * 25
                    _cv.line(_canvas, (_x, 150), (_x, 60), (70, 70, 78), 2)
                _cp = tmp / "cut_probe.png"
                _ok, _buf = _cv.imencode(".png", _canvas)
                _buf.tofile(str(_cp))

                _r = _mat.cut(str(_cp))
                if _r is None:
                    log("抠图: ❌ 读不出测试图")
                else:
                    _a = _r.alpha
                    _corner = float(_a[0:12, 0:12].mean())
                    _core = float(_a[215:245, 185:215].mean())
                    _strand = float(max(_a[70:110, 148:154].mean(),
                                        _a[70:110, 248:254].mean()))
                    _okcorner = _corner < 0.15
                    _okcore = _core > 0.85
                    _okstrand = _strand > 0.30
                    log("抠图[%s]: 背景残留=%.2f 主体不透明=%.2f 细线保留=%.2f → %s"
                        % (_r.mode, _corner, _core, _strand,
                           "✅" if (_okcorner and _okcore and _okstrand) else "❌"))
                    log("抠图底色: 深色主体→%s（应为 white）判定=%s 占比=%.0f%%"
                        % (_r.backdrop, "✅" if _r.backdrop == "white" else "❌",
                           _r.cover * 100))

                    # 浅色主体应该反过来衬黑底
                    _light = _np.full((240, 240, 3), 255, _np.uint8)
                    _cv.circle(_light, (120, 120), 60, (232, 232, 238), -1)
                    _cv.circle(_light, (120, 120), 60, (150, 150, 158), 2)
                    _lp = tmp / "cut_light.png"
                    _ok, _buf = _cv.imencode(".png", _light)
                    _buf.tofile(str(_lp))
                    _rl = _mat.cut(str(_lp))
                    if _rl is not None:
                        log("抠图底色: 浅色主体→%s（应为 black）判定=%s"
                            % (_rl.backdrop, "✅" if _rl.backdrop == "black" else "❌"))

                    # 三视图形状：横排三张，宽=3×W
                    _views = _mat.compose(_r)
                    log("抠图三视图: %dx%d 宽度倍数=%.1f %s"
                        % (_views.shape[0], _views.shape[1],
                           _views.shape[1] / max(1, _r.size[0]),
                           "✅" if _views.shape[1] >= _r.size[0] * 3 else "❌"))
            except ImportError:
                log("抠图: ⏭ 跳过（未安装 opencv）")
            except Exception:  # noqa: BLE001
                log("抠图: ❌\n" + traceback.format_exc())
        finally:
            try:
                import shutil

                shutil.rmtree(tmp, ignore_errors=True)
            except Exception:  # noqa: BLE001
                pass

        # ── 主界面能否创建 ────────────────────────────
        if no_gui:
            log("主界面: ⏭ 跳过（无图形环境）")
        else:
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
                # 只遍历「侧栏真的会显示」的模块 —— 停用/未安装的不该出现在侧栏，
                # 也就不该在这里出现。
                shown = [m.id for m in app.plugin_list()]
                tabs = []
                for key in shown:
                    app.tab = key
                    app.build()
                    app.update()
                    tabs.append(key)
                app.destroy()
                log("主界面: ✅ %d 个模块均可创建（%s）"
                    % (len(tabs), ", ".join(tabs)))
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

    if "--plugins" in sys.argv:
        return _plugins_cli()

    for flag, remove in (("--install-plugin", False), ("--uninstall-plugin", True)):
        if flag in sys.argv:
            i = sys.argv.index(flag)
            if i + 1 >= len(sys.argv):
                _say("藏图盒", "用法：%s <插件包路径或插件 id>" % flag)
                return 2
            return _install_cli(sys.argv[i + 1], remove)

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
