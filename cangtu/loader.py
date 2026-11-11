# -*- coding: utf-8 -*-
"""插件的发现、按需加载、卸载与清单维护。

## 三条设计约束

**1. 发现阶段绝不 import 插件代码。**
侧栏要显示五个模块的名字。如果为了拿名字就把它们 import 一遍，
抠图的 cv2 + onnxruntime（约 100 MB）在程序启动时就得读进内存 ——
「按需加载」就成了空话。所以名字、排序、依赖探测全部来自 plugin.json，
用 importlib.util.find_spec 判断模块在不在（只查路径，不执行）。

**2. 插件目录有两个来源，用户目录优先。**
    <程序目录>/plugins/     用户装的（可写，卸载就是删这里）
    <_internal>/plugins/    随包发行的（只读，相当于「出厂预装」）
同一个 id 出现两次时，用户的覆盖出厂的 —— 这样用户想换掉某个插件，
往 plugins/ 里放一份同 id 的就行，不用先删内置的。

**3. 加载失败必须变成一句人话，而不是 traceback。**
插件是第三方代码，语法错、缺依赖、版本不对都会发生。
任何异常都在这里收成 PluginError（带原文），由界面渲染成原因页。
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import traceback
import zipfile
from pathlib import Path

from cangtu.api import API_VERSION, PluginMeta, api_compatible

MANIFEST_NAME = "manifest.json"
META_NAME = "plugin.json"


class PluginError(Exception):
    """插件层面能预料到的失败。str(exc) 直接给人看。"""

    def __init__(self, message: str, detail: str = ""):
        super().__init__(message)
        self.detail = detail


# ══════════════════════════════════════════════════════════
#  内置插件适配器
# ══════════════════════════════════════════════════════════
class BuiltinPlugin:
    """把「App 上的一个 build_xxx 方法」包装成插件。

    双轨期的过渡物：机制先立起来，五个模块的代码暂时还留在本体。
    好处是侧栏、懒加载、不可用降级、错误隔离这些**框架行为**从第一天就是真的，
    不用等到 1.3.0 拆完才验证。1.3.0 之后这个类就可以删了。
    """

    def __init__(self, meta: PluginMeta, holder=None):
        self._meta = meta
        self._holder = holder

    # 元数据照抄清单
    @property
    def id(self) -> str:
        return self._meta.id

    @property
    def name(self) -> str:
        return self._meta.name

    @property
    def subtitle(self) -> str:
        return self._meta.subtitle

    @property
    def order(self) -> int:
        return self._meta.order

    @property
    def api_version(self) -> str:
        return self._meta.api_version

    @property
    def requires(self):
        return list(self._meta.requires)

    def check(self):
        # 本体可以按插件 id 提供更细的自检（如抠图查模型、查 cv2 版本）
        fn = getattr(self._holder, "plugin_check", None) if self._holder else None
        if fn is None:
            return True, ""
        return fn(self._meta.id)

    def build(self, ctx):
        app = ctx.app
        fn = getattr(app, self._meta.builtin, None)
        if fn is None:
            raise PluginError("本体缺少方法 %s" % self._meta.builtin)
        return fn()


# ══════════════════════════════════════════════════════════
#  管理器
# ══════════════════════════════════════════════════════════
class PluginManager:
    def __init__(self, user_root, bundled=(), holder=None):
        self.user_root = Path(user_root)
        self.bundled = [Path(p) for p in bundled if Path(p) != self.user_root]
        self.holder = holder            # 内置插件要回调本体做自检

        self._metas: dict = {}          # id -> PluginMeta
        self._inst: dict = {}           # id -> 插件实例
        self._err: dict = {}            # id -> 最近一次加载错误
        self._disabled: set = set()     # 被停用的 id
        self._vendor: dict = {}         # id -> 插进 sys.path 的 vendor 目录
        self._checked: dict = {}        # id -> (可用, 原因)，卸载时清

    # ── 目录 ──────────────────────────────────────────────
    @property
    def manifest_path(self) -> Path:
        return self.user_root / MANIFEST_NAME

    def roots(self) -> list:
        return [self.user_root] + self.bundled

    # ── 发现 ──────────────────────────────────────────────
    def discover(self) -> list:
        """扫两个根目录，构造元数据。不 import 任何插件代码。"""
        self._load_manifest()
        found: dict = {}
        for root in self.roots():
            if not root.is_dir():
                continue
            origin = "user" if root == self.user_root else "bundled"
            for pj in sorted(root.glob("*/" + META_NAME)):
                # 以 . 或 _ 开头的目录一律不认：那是「备份 / 临时关掉」的常见起名方式。
                # pathlib 的 * 会匹配点开头的目录（和 shell 不一样），
                # 不排掉的话，把 unpack 改名成 .unpack_off 它照样会被加载回来。
                if pj.parent.name[:1] in (".", "_"):
                    continue
                try:
                    raw = json.loads(pj.read_text(encoding="utf-8-sig"))
                    meta = self._meta_from(raw)
                except Exception:  # noqa: BLE001  清单坏了不该让其他插件一起消失
                    continue
                if meta.id in found:
                    continue          # 先扫到的优先（用户目录在前）
                meta.dir = str(pj.parent)
                meta.origin = origin
                found[meta.id] = meta
        self._metas = found
        self._checked.clear()       # 清单变了，自检结论作废
        return self.metas()

    @staticmethod
    def _meta_from(raw: dict) -> PluginMeta:
        if not isinstance(raw, dict):
            raise ValueError("plugin.json 顶层必须是对象")
        pid = str(raw.get("id") or "").strip()
        if not pid:
            raise ValueError("plugin.json 缺少 id")
        return PluginMeta(
            id=pid,
            name=str(raw.get("name") or pid),
            subtitle=str(raw.get("subtitle") or ""),
            order=int(raw.get("order") or 100),
            api_version=str(raw.get("api_version") or API_VERSION),
            requires=list(raw.get("requires") or []),
            probe=list(raw.get("probe") or []),
            builtin=str(raw.get("builtin") or ""),
            entry=str(raw.get("entry") or "plugin.py"),
            description=str(raw.get("description") or ""),
        )

    def metas(self) -> list:
        """按 order 排序（同 order 按 id，保证顺序稳定）。"""
        return sorted(self._metas.values(), key=lambda m: (m.order, m.id))

    def meta(self, pid: str):
        return self._metas.get(pid)

    def ids(self) -> list:
        return [m.id for m in self.metas()]

    def find(self, pid: str) -> str:
        """模糊找 id：用户可能只记得名字。"""
        if pid in self._metas:
            return pid
        for m in self._metas.values():
            if pid in (m.name, m.subtitle):
                return m.id
        return ""

    # ── 启用状态 ──────────────────────────────────────────
    def _load_manifest(self) -> None:
        self._disabled = set()
        try:
            raw = json.loads(self.manifest_path.read_text(encoding="utf-8-sig"))
        except Exception:  # noqa: BLE001
            return
        items = raw.get("plugins") if isinstance(raw, dict) else raw
        if isinstance(items, dict):
            for pid, val in items.items():
                on = val.get("enabled", True) if isinstance(val, dict) else bool(val)
                if not on:
                    self._disabled.add(pid)
        elif isinstance(items, list):
            for val in items:
                if not isinstance(val, dict):
                    continue
                if val.get("enabled", True) is False and val.get("id"):
                    self._disabled.add(str(val["id"]))

    def save_manifest(self) -> bool:
        """写 user_root/manifest.json。只存「覆盖」，没提到的就是启用。"""
        data = {
            "api_version": API_VERSION,
            "plugins": {m.id: {"enabled": self.enabled(m.id)} for m in self.metas()},
        }
        try:
            self.user_root.mkdir(parents=True, exist_ok=True)
            self.manifest_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            return True
        except OSError:
            return False

    def enabled(self, pid: str) -> bool:
        return pid not in self._disabled

    def set_enabled(self, pid: str, on: bool) -> None:
        if on:
            self._disabled.discard(pid)
        else:
            self._disabled.add(pid)
            self.unload(pid)

    # ── 加载 ──────────────────────────────────────────────
    def load(self, pid: str):
        """取插件实例。第一次调用才真正 import 插件代码。"""
        if pid in self._inst:
            return self._inst[pid]

        meta = self._metas.get(pid)
        if meta is None:
            raise PluginError("找不到插件「%s」" % pid)
        if not meta.compatible:
            raise PluginError("%s 需要 API %s，本体是 %s"
                              % (meta.name, meta.api_version, API_VERSION))

        inst = BuiltinPlugin(meta, self.holder) if meta.builtin else self._import(meta)
        self._inst[pid] = inst
        self._err.pop(pid, None)
        return inst

    def _import(self, meta: PluginMeta):
        dirp = Path(meta.dir)
        entry = dirp / meta.entry
        if not entry.is_file():
            raise PluginError("%s 缺少入口文件 %s" % (meta.name, meta.entry))

        # 插件私有依赖优先于本体：同名包（比如插件自带的 cv2）不会串味
        vendor = dirp / "vendor"
        added = False
        if vendor.is_dir() and str(vendor) not in sys.path:
            sys.path.insert(0, str(vendor))
            self._vendor[meta.id] = str(vendor)
            added = True

        modname = "_cangtu_plugin_" + meta.id
        try:
            mod = sys.modules.get(modname)
            if mod is None:
                # submodule_search_locations 让 plugin.py 变成一个「包」，
                # 插件内部就能写 `from . import logic`，多文件插件不用改写法。
                spec = importlib.util.spec_from_file_location(
                    modname, str(entry),
                    submodule_search_locations=[str(dirp)],
                )
                if spec is None or spec.loader is None:
                    raise PluginError("%s 的入口无法解析" % meta.name)
                mod = importlib.util.module_from_spec(spec)
                sys.modules[modname] = mod
                try:
                    spec.loader.exec_module(mod)
                except BaseException:
                    sys.modules.pop(modname, None)     # 别留下半成品
                    raise
            plugin = getattr(mod, "PLUGIN", None)
            if plugin is None:
                raise PluginError("%s 的 %s 里没有 PLUGIN 变量"
                                  % (meta.name, meta.entry))
        except PluginError:
            raise
        except BaseException as exc:  # noqa: BLE001
            detail = traceback.format_exc()
            self._err[meta.id] = detail
            if added:
                try:
                    sys.path.remove(str(vendor))
                except ValueError:
                    pass
                self._vendor.pop(meta.id, None)
            raise PluginError("加载失败：%s: %s" % (type(exc).__name__, exc), detail)

        return plugin

    # ── 自检 ──────────────────────────────────────────────
    def check(self, pid: str) -> tuple:
        """(可用, 原因)。任何异常都收成不可用，绝不让它冒到界面上。

        结果会缓存到卸载为止：界面每次重建（切 tab、切主题）都会问一遍，
        而 check() 里可能要去开模型、试连设备 —— 那些不该每次都做一遍。
        """
        cached = self._checked.get(pid)
        if cached is not None:
            return cached

        try:
            plugin = self.load(pid)
        except PluginError as exc:
            res = (False, str(exc))
            self._checked[pid] = res
            return res
        except Exception as exc:  # noqa: BLE001
            res = (False, "%s: %s" % (type(exc).__name__, exc))
            self._checked[pid] = res
            return res

        fn = getattr(plugin, "check", None)
        if fn is None:
            res = (True, "")
        else:
            try:
                ok, why = fn()
                res = (bool(ok), str(why or ""))
            except Exception as exc:  # noqa: BLE001
                res = (False, "自检出错：%s: %s" % (type(exc).__name__, exc))
        self._checked[pid] = res
        return res

    # ── 卸载 ──────────────────────────────────────────────
    def unload(self, pid: str) -> bool:
        """从内存里卸掉（不删文件）。下次用到会重新 import。

        Python 不会回收已 import 的第三方模块（cv2 之类），
        所以这里只保证「插件自己的代码」被清掉，那点内存留着无妨 ——
        反正卸载之后不会再走它的逻辑。
        """
        had = self._inst.pop(pid, None) is not None
        self._checked.pop(pid, None)     # 重新加载要重新自检
        modname = "_cangtu_plugin_" + pid
        for name in [n for n in sys.modules
                     if n == modname or n.startswith(modname + ".")]:
            sys.modules.pop(name, None)
        v = self._vendor.pop(pid, None)
        if v:
            try:
                sys.path.remove(v)
            except ValueError:
                pass
        return had

    @property
    def loaded(self) -> list:
        return sorted(self._inst)

    def loaded_ids(self) -> list:
        return sorted(self._inst)

    # ── 安装 / 卸载（磁盘）────────────────────────────────
    def install(self, zip_path, pid: str = "") -> str:
        """装一个插件包（zip）。返回装好的 id。

        包的形态可以是这两种之一，都能认：
            cut-plugin-v1.zip → cut/plugin.json, cut/plugin.py, ...
            cut-plugin-v1.zip → plugin.json, plugin.py, ...（单插件裸包）
        """
        zp = Path(zip_path)
        if not zp.is_file():
            raise PluginError("找不到 %s" % zp)
        try:
            zf = zipfile.ZipFile(zp)
        except zipfile.BadZipFile:
            raise PluginError("%s 不是有效的 zip" % zp.name)

        with zf:
            names = [n for n in zf.namelist() if not n.endswith("/")]
            metas = [n for n in names if n.split("/")[-1] == META_NAME]
            if not metas:
                raise PluginError("这个包里没有 %s，不像插件包" % META_NAME)

            # 选层级最浅的那份清单
            metas.sort(key=lambda n: n.count("/"))
            src_meta = metas[0]
            top = src_meta.rsplit("/", 1)[0] + "/" if "/" in src_meta else ""

            try:
                raw = json.loads(zf.read(src_meta).decode("utf-8-sig"))
                meta = self._meta_from(raw)
            except Exception as exc:  # noqa: BLE001
                raise PluginError("清单读不出来：%s" % exc)
            if not meta.compatible:
                raise PluginError("%s 需要 API %s，本体是 %s"
                                  % (meta.name, meta.api_version, API_VERSION))

            target = self.user_root / meta.id
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
            target.mkdir(parents=True, exist_ok=True)

            for n in names:
                if not n.startswith(top):
                    continue
                rel = n[len(top):]
                if not rel or rel.startswith("/") or ".." in rel.split("/"):
                    continue          # 防目录穿越
                dst = target / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(n) as src, open(dst, "wb") as out:
                    shutil.copyfileobj(src, out)

        self.discover()
        self.set_enabled(meta.id, True)
        self.save_manifest()
        return meta.id

    def uninstall(self, pid: str) -> None:
        """删掉用户装的插件。出厂的（bundled）只能停用，不能删。"""
        meta = self._metas.get(pid)
        if meta is None:
            raise PluginError("没有这个插件：%s" % pid)
        if meta.origin != "user":
            raise PluginError("「%s」是随程序发行的，不能删除；可以停用它"
                              % meta.name)
        self.unload(pid)
        shutil.rmtree(Path(meta.dir), ignore_errors=True)
        self._metas.pop(pid, None)
        self.save_manifest()

    # ── 诊断 ──────────────────────────────────────────────
    def last_error(self, pid: str) -> str:
        return self._err.get(pid, "")

    def report(self) -> list:
        """给 --plugins 用的一行行说明。"""
        out = []
        for m in self.metas():
            why = m.why_not()
            if not self.enabled(m.id):
                why = "已停用"
            state = "已加载" if m.id in self._inst else "未加载"
            out.append("%s %s order=%-3d %s %s %s" % (
                _pad(m.id, 9), _pad(m.name, 12), m.order,
                _pad("内置" if m.builtin else "插件", 6),
                _pad(state, 8), why or "就绪"))
        return out


def _pad(text: str, width: int) -> str:
    """按**显示宽度**补空格 —— 中文一个字占两格，用 %-9s 会排歪。"""
    import unicodedata

    w = sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in text)
    return text + " " * max(0, width - w)
