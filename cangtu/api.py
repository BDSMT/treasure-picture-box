# -*- coding: utf-8 -*-
"""宿主 ↔ 插件 的唯一契约。

这个文件是插件**唯一**允许依赖的本体模块。插件不该碰 ``ui.app`` 的实现细节，
需要什么能力就从 :class:`HostContext` 拿 —— 这样插件可以脱离窗口单独测试
（塞一个假的 ctx 就行），本体内部改名换姓也不会把插件一起带崩。

## 版本策略

``API_VERSION`` 的**主版本号**变了就是破坏性变更：老插件会被 loader 判为
不兼容而拒绝加载，并在侧栏说明原因，而不是加载到一半抛一堆莫名其妙的
AttributeError。次版本号只增不减，表示「新增了能力，老插件照旧能用」。

## 为什么用 Protocol 而不是抽象基类

插件是第三方可以写的东西，不该被迫 ``from cangtu.api import PluginBase``
再继承。鸭子类型 + Protocol 只在类型检查时起作用，运行时零耦合：
插件只要长着 id / name / check() / build() 这几个东西就是插件。
"""
from __future__ import annotations

import importlib.util
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, Sequence

API_VERSION = "1.0"


def api_compatible(version: str) -> bool:
    """只比主版本号。插件写 1.3、宿主是 1.0 也算兼容（次版本只增不减）。"""
    try:
        return str(version).split(".")[0] == API_VERSION.split(".")[0]
    except Exception:  # noqa: BLE001
        return False


# ══════════════════════════════════════════════════════════
#  元数据
# ══════════════════════════════════════════════════════════
@dataclass
class PluginMeta:
    """插件自述。**只靠 plugin.json 就能构造，不 import 任何插件代码。**

    这是「按需加载」能成立的前提：侧栏要显示五个模块的名字，如果为了拿名字
    就把它们 import 一遍，抠图那 100 MB 的 cv2 / onnxruntime 在程序启动时
    就得全部加载完 —— 按需加载就名存实亡了。
    """

    id: str
    name: str
    subtitle: str = ""
    order: int = 100
    api_version: str = API_VERSION
    requires: Sequence[str] = field(default_factory=list)
    probe: Sequence[str] = field(default_factory=list)
    """只需「找得到」的模块名，用 find_spec 探测（不 import、不加载 DLL）。

    抠图靠它判断 cv2/onnxruntime 在不在，代价是微秒级；
    真去 import 一次要 1 秒以上，还会把 100 MB 的二进制读进内存。
    """

    builtin: str = ""
    """非空 = 本体内置实现，值是 App 上的构建方法名（如 ``build_seed``）。

    双轨期的过渡形态：1.2.x 里五个模块都还是 App 的方法，
    只有 unpack 真搬进了 plugins/。等 1.3.0 全部搬完，这个字段就没人用了。
    """

    entry: str = "plugin.py"
    description: str = ""
    dir: str = ""
    origin: str = ""          # user / bundled

    # ── 派生判断 ──────────────────────────────────────────
    @property
    def compatible(self) -> bool:
        return api_compatible(self.api_version)

    def missing(self) -> list:
        """探测缺失的第三方模块。空列表 = 齐了。

        刻意不用 ``import``：``find_spec`` 只查路径，不执行模块代码。
        """
        lack = []
        for m in self.probe:
            try:
                if importlib.util.find_spec(m) is None:
                    lack.append(m)
            except (ImportError, ValueError, AttributeError):
                lack.append(m)
        return lack

    @property
    def ready(self) -> bool:
        """能不能进：启用状态要另外查 manager，这里只看「自身条件」。"""
        return self.compatible and not self.missing()

    def why_not(self) -> str:
        """给人看的一句话原因。"""
        if not self.compatible:
            return "需要 API %s，本体是 %s" % (self.api_version, API_VERSION)
        lack = self.missing()
        if lack:
            return "缺少 %s" % "、".join(lack)
        return ""


# ══════════════════════════════════════════════════════════
#  插件契约
# ══════════════════════════════════════════════════════════
class Plugin(Protocol):
    """插件长什么样。

    元数据既可以写成类属性，也可以从 plugin.json 读 —— loader 以 json 为准
    （侧栏渲染不加载代码），实例上的值只在插件代码内部用到。
    """

    id: str
    name: str
    subtitle: str
    order: int
    api_version: str
    requires: Sequence[str]

    def check(self) -> tuple:
        """可用性自检，返回 (可用, 不可用原因)。

        在**首次加载时**调用一次（不是启动时，否则又会把重依赖提前拉起来）。
        返回 False 时侧栏入口点进去会看到原因页，而不是一堆异常。
        """

    def build(self, ctx: "HostContext") -> Any:
        """在 ``ctx.stage`` 里画出自己的界面。

        宿主每次切 tab / 切主题都会 destroy 掉上一次的控件再来一次，
        所以这里**不能**缓存控件引用 —— 要留的东西放 self 上。
        """


# ══════════════════════════════════════════════════════════
#  宿主上下文
# ══════════════════════════════════════════════════════════
class HostContext:
    """插件能碰到的全部本体能力。刻意收得很窄。

    每个成员都是「转发」而不是「实现」：本体的 App 有自己的状态机
    （主题、DPI、任务代数），插件不该知道这些细节，也不该绕过它们。
    """

    def __init__(self, app):
        self._app = app

    # ── 外观 ──────────────────────────────────────────────
    @property
    def pal(self) -> dict:
        """当前主题的调色板。切主题后插件会被重建，所以这里总是新的。"""
        return self._app.pal

    @property
    def theme(self) -> str:
        return self._app.theme

    @property
    def stage(self):
        """插件界面的根容器。所有控件都建在它下面。"""
        return self._app.stage

    def s(self, n: int) -> int:
        """DPI 缩放。所有像素尺寸都要过这一道，否则高分屏上会小一圈。"""
        try:
            from ui.theme import s as scale

            return scale(n)
        except Exception:  # noqa: BLE001
            return n

    # ── 通用能力 ──────────────────────────────────────────
    def toast(self, text: str, err: bool = False) -> None:
        self._app.toast(text, err)

    def pick_file(self, cb, images_only: bool = False, title: str = "选择文件") -> None:
        self._app._pick(cb, images_only, title)

    def ask_save(self, default_name: str, ext: str):
        return self._app._ask_save(default_name, ext)

    def ask_dir(self, title: str = "选择文件夹"):
        return self._app._ask_dir(title)

    def confirm(self, title: str, message: str, danger: bool = False) -> bool:
        return self._app._confirm(title, message, danger)

    def alert(self, title: str, message: str) -> None:
        """纯告知，不带「是/否」。校验失败、缺卷这类信息要用它。"""
        self._app._alert(title, message)

    # ── 状态与并发 ────────────────────────────────────────
    @property
    def tasks(self):
        """统一的异步执行器。key 建议用插件 id。"""
        return self._app.tasks

    def spin(self, key: str, host) -> Any:
        """在控件中央挂一个转圈，任务开始时自动转、结束自动停。"""
        return self._app._spin(key, host)

    def alive(self, pid: str, widget: str) -> bool:
        """异步结果回来时问一句：界面还停在我这个模块、那个控件还在吗？

        不在就把结果丢掉 —— 否则会往别的模块的控件上写数据。
        """
        return self._app._alive(pid, widget)

    def is_current(self, pid: str) -> bool:
        return self._app.tab == pid

    def rebuild(self) -> None:
        """请求宿主重建整个界面（换文件、改状态之后调）。

        重建时插件实例是复用的（loader 有缓存），self 上的状态不会丢。
        """
        self._app.build()

    # ── 控件 ──────────────────────────────────────────────
    def btn(self, parent, text: str, cmd, primary: bool = False):
        return self._app._btn(parent, text, cmd, primary)

    def hint(self, parent, text: str, pady=(0, 8)):
        return self._app._hint(parent, text, pady)

    @property
    def widgets(self):
        """本体控件库。插件用它们，视觉才和本体一致。"""
        return self._app.W

    @property
    def fonts(self) -> dict:
        return self._app.F

    @property
    def config(self) -> dict:
        """可读写的配置字典。改动后要 ``ctx.save_config()``。"""
        return self._app.cfg

    def save_config(self) -> None:
        self._app.save_config()

    @property
    def app(self):
        """逃生舱。只给「框架还没提供对应能力」的临时场景用，
        用了就欠一笔技术债 —— 1.3.0 前应该补进 HostContext。"""
        return self._app

    @property
    def log(self):
        return self._app.log


# ══════════════════════════════════════════════════════════
#  小工具（插件也常用，放这里免得各写一份）
# ══════════════════════════════════════════════════════════
def stem_of(p) -> str:
    return Path(p).stem


def ext_of(p) -> str:
    return Path(p).suffix


def short_name(name: str, limit: int = 54) -> str:
    """名字太长就掐中间，保住结尾的扩展名 —— 一行放不下会被 Tk 直接切掉。"""
    if len(name) <= limit:
        return name
    keep_head = limit - 16
    return name[:keep_head] + "…" + name[-(limit - keep_head - 1):]


def thumb(path, box=(64, 64)):
    """缩略图。失败返回 None —— 封面图坏掉不该让整个界面炸。"""
    try:
        from PIL import Image

        from core.imageio import open_rgba

        im = open_rgba(path)
        im.thumbnail(box, Image.LANCZOS)
        return im
    except Exception:  # noqa: BLE001
        return None


def dims(path) -> str:
    try:
        from PIL import Image

        with Image.open(path) as im:
            return "%d × %d" % im.size
    except Exception:  # noqa: BLE001
        return "—"
