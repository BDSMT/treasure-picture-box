# -*- coding: utf-8 -*-
"""插件框架的回归测试（无需图形界面）。

    H:\\Python3.10.11\\python.exe tools\\test_plugins.py

验的是框架自己的行为，不是界面上好不好看：
    1. 发现阶段不 import 插件代码（抠图那 100 MB 不能被拖起来）
    2. 按需加载：第一次 load 才 import，第二次命中缓存
    3. 加载失败收成 PluginError，不是 traceback 炸到界面上
    4. 版本不兼容的插件被识别出来，但不会拖累其他插件
    5. 卸载能清掉模块缓存，之后还能重新加载
    6. 装包 / 卸载包（zip ↔ 目录）
    7. 用户目录覆盖出厂目录（同 id 时用户优先）
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cangtu.loader import PluginError, PluginManager  # noqa: E402

OK, BAD = 0, 0


def check(label: str, cond, extra: str = "") -> None:
    global OK, BAD
    if cond:
        OK += 1
        print("  ✅ %s%s" % (label, ("  " + extra) if extra else ""))
    else:
        BAD += 1
        print("  ❌ %s%s" % (label, ("  " + extra) if extra else ""))


HELLO_JSON = {
    "id": "hello", "name": "打招呼", "subtitle": "测试用", "order": 5,
    "api_version": "1.0", "entry": "plugin.py",
}
HELLO_PY = """\
class Hello:
    id, name, subtitle, order, api_version = "hello", "打招呼", "测试用", 5, "1.0"
    requires = ()
    def check(self):
        return True, ""
    def build(self, ctx):
        return "built:%d" % ctx.s(4)
PLUGIN = Hello()
"""


def make_plugin(root: Path, pid: str, code: str, **meta) -> Path:
    d = root / pid
    d.mkdir(parents=True, exist_ok=True)
    m = dict(HELLO_JSON)
    m["id"] = pid
    m.update(meta)
    (d / "plugin.json").write_text(json.dumps(m, ensure_ascii=False),
                                   encoding="utf-8")
    (d / "plugin.py").write_text(code, encoding="utf-8")
    return d


class FakeCtx:
    def s(self, n):
        return n


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="cangtu_plugin_test_"))
    try:
        user = tmp / "plugins"

        # ── 1. 发现：只读 json ────────────────────────────
        print("\n[1] 发现")
        make_plugin(user, "hello", HELLO_PY, order=5)
        make_plugin(user, "broken", "raise RuntimeError('故意炸的')\n", order=6)
        make_plugin(user, "future", HELLO_PY, api_version="9.0", order=7)
        pm = PluginManager(user, bundled=[ROOT / "plugins"])
        metas = pm.discover()
        ids = [m.id for m in metas]
        check("扫到 3 个测试插件 + 出厂 5 个", len(metas) >= 8, "共 %d 个: %s"
              % (len(metas), ", ".join(ids)))
        check("发现阶段没有 import 任何插件模块",
              not any(k.startswith("_cangtu_plugin_") for k in sys.modules))
        check("order 排序生效",
              ids[:3] == ["hello", "broken", "future"] and ids[3] == "seed",
              "前四个: %s" % ids[:4])
        check("版本不兼容被识别",
              pm.meta("future") is not None and not pm.meta("future").compatible,
              pm.meta("future").why_not())

        # ── 2. 按需加载 ───────────────────────────────────
        print("\n[2] 按需加载")
        inst = pm.load("hello")
        check("load 返回插件实例", inst is not None, type(inst).__name__)
        check("build 能拿到 ctx", inst.build(FakeCtx()) == "built:4")
        check("第二次 load 命中缓存", pm.load("hello") is inst)
        check("loaded 里只有一个", pm.loaded_ids() == ["hello"], str(pm.loaded_ids()))

        # ── 3. 加载失败 ───────────────────────────────────
        print("\n[3] 加载失败")
        try:
            pm.load("broken")
            check("损坏插件抛 PluginError", False)
        except PluginError as exc:
            check("损坏插件抛 PluginError", True, str(exc)[:60])
        ok, why = pm.check("broken")
        check("check() 收成不可用而不是抛异常", (not ok) and bool(why), why[:50])
        check("失败不污染 sys.modules",
              "_cangtu_plugin_broken" not in sys.modules)
        check("其他插件不受影响", pm.load("hello") is inst)

        # ── 4. 卸载 / 重载 ────────────────────────────────
        print("\n[4] 卸载与重载")
        check("unload 返回 True", pm.unload("hello") is True)
        check("模块缓存已清", "_cangtu_plugin_hello" not in sys.modules)
        inst2 = pm.load("hello")
        check("卸载后能重新加载", inst2 is not None and inst2 is not inst)
        pm.unload("hello")
        pm.unload("hello")
        check("重复卸载不炸", True)

        # ── 5. 用户目录覆盖出厂 ───────────────────────────
        print("\n[5] 目录优先级")
        # 备份/隐藏目录不算插件：否则把 unpack 改名成 .unpack_off 想关掉它，
        # 反而会被 pathlib 的 * 扫回来（* 匹配点开头的目录，和 shell 不同）。
        make_plugin(user, ".unpack_off", HELLO_PY, id="unpack", name="改名后的备份")
        pm_hidden = PluginManager(user, bundled=[ROOT / "plugins"])
        pm_hidden.discover()
        up_meta = pm_hidden.meta("unpack")
        check("点开头的备份目录不被当成插件",
              up_meta.origin == "bundled", up_meta.origin + " " + up_meta.dir)

        make_plugin(user, "cut", HELLO_PY.replace('"hello"', '"cut"')
                    .replace("打招呼", "抠图·用户版"), name="抠图·用户版")
        pm2 = PluginManager(user, bundled=[ROOT / "plugins"])
        pm2.discover()
        cut = pm2.meta("cut")
        check("同 id 时用户目录覆盖出厂", cut.origin == "user", cut.dir)
        check("覆盖后读到用户的名字", cut.name == "抠图·用户版", cut.name)
        shutil.rmtree(user / "cut")

        # ── 6. 装包 / 卸载包 ──────────────────────────────
        print("\n[6] 装包与卸载")
        src = tmp / "pkg_src"
        make_plugin(src, "zipped", HELLO_PY.replace('"hello"', '"zipped"'))
        zp = tmp / "zipped-plugin.zip"
        with zipfile.ZipFile(zp, "w") as z:
            for f in (src / "zipped").iterdir():
                z.write(f, "zipped/" + f.name)
        pm3 = PluginManager(user / "install", bundled=[ROOT / "plugins"])
        pm3.discover()
        pid = pm3.install(zp)
        check("装包返回 id", pid == "zipped", pid)
        check("装完立刻可见", pm3.meta("zipped") is not None)
        check("装完默认启用", pm3.enabled("zipped"))
        check("文件真的落盘", (user / "install" / "zipped" / "plugin.py").exists())
        check("manifest 写出来了",
              (user / "install" / "manifest.json").exists())
        pm3.uninstall("zipped")
        check("卸载后目录消失", not (user / "install" / "zipped").exists())

        # 出厂的不能删，只能停用
        try:
            pm3.uninstall("seed")
            check("出厂插件拒绝删除", False)
        except PluginError:
            check("出厂插件拒绝删除", True)
        pm3.set_enabled("seed", False)
        pm3.save_manifest()
        pm4 = PluginManager(user / "install", bundled=[ROOT / "plugins"])
        pm4.discover()
        check("停用状态能持久化", not pm4.enabled("seed"))

        # ── 7. 真实项目：五个模块 + 懒加载证明 ────────────
        print("\n[7] 真项目")
        real = PluginManager(ROOT / "plugins")
        got = real.discover()
        check("项目里发现 5 个模块", len(got) == 5,
              ", ".join(m.id for m in got))
        check("顺序是 seed→unpack→phantom→reveal→cut",
              [m.id for m in got] == ["seed", "unpack", "phantom", "reveal", "cut"])
        check("unpack 是外置插件，其余四个暂为内置",
              real.meta("unpack").builtin == ""
              and all(real.meta(x).builtin for x in
                      ("seed", "phantom", "reveal", "cut")))
        check("发现完仍然没 import cv2（关键）", "cv2" not in sys.modules)
        up = real.load("unpack")
        check("unpack 加载成功", up is not None, type(up).__name__)
        ok, why = real.check("unpack")
        check("unpack 自检通过", ok, why or "OK")
        check("加载 unpack 也没有惊动 cv2", "cv2" not in sys.modules)
        real.unload("unpack")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n=== %d 通过，%d 失败 ===" % (OK, BAD))
    return 1 if BAD else 0


if __name__ == "__main__":
    sys.exit(main())
