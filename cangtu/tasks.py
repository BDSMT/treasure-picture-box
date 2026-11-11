# -*- coding: utf-8 -*-
"""异步执行器与加载状态。

## 为什么需要它

现在所有图像处理都在 Tk 主线程同步跑：抠图 2.5 秒、幻影合成几百毫秒。
这期间窗口完全不响应，连"正在识别"那行字都刷不出来 —— 更别说转圈了。

把重活丢到 worker 线程，结果用 `after(0, ...)` 回主线程再碰控件。

## 为什么用队列 + 主线程轮询，而不是 worker 里直接 after()

Tkinter 不是线程安全的：从子线程调 `root.after()` 会静默失败
（不报错，回调永远不执行）。最初写成 worker 里 after() 的结果就是
「任务跑完了但界面永远停在加载中」。

正确做法：worker 线程只往 `queue.Queue` 里放结果，
主线程用 `after(30ms)` 轮询取出——30ms 对界面完全无感，
却是唯一可靠的跨线程交接方式。

## 为什么用「代数」而不是 cancel

Python 线程无法强制中断。用户快速连换三张图时，前两个任务还会跑完。
这里给每个 key 记一个代数（generation），任务提交时自增，
结果回来时代数对不上就静默丢弃。

这比试图 kill 线程简单得多，也避开了 Tkinter 跨线程操作崩溃的问题
（Tk 控件只能在主线程碰）。

## 状态语义

status:
  idle     没有任务在跑，也没有结果
  loading  正在跑
  done     最近一次跑完了
  error    最近一次失败了，error 里有原因
"""
from __future__ import annotations

import queue
import threading
from dataclasses import dataclass, field


@dataclass
class TaskState:
    status: str = "idle"
    error: str = ""
    gen: int = field(default=0)


class TaskRunner:
    """一个 App 实例共用一份。key 建议直接用模块名（"cut" / "phantom"…）。"""

    PUMP_MS = 30        # 主线程取结果的间隔
    PUMP_MAX = 60       # 一次轮询最多处理几个，避免积压时卡住界面

    def __init__(self, root):
        self.root = root
        self._q: queue.Queue = queue.Queue()
        self._states: dict = {}
        self._spinners: dict = {}
        self._pump_id = None
        self._start_pump()

    # ── 主线程轮询 ────────────────────────────────────────
    def _start_pump(self) -> None:
        if self._pump_id is not None:
            return
        try:
            self._pump_id = self.root.after(self.PUMP_MS, self._pump)
        except Exception:          # noqa: BLE001
            self._pump_id = None

    def _pump(self) -> None:
        self._pump_id = None
        for _ in range(self.PUMP_MAX):
            try:
                item = self._q.get_nowait()
            except queue.Empty:
                break
            try:
                self._finish(*item)
            except Exception:      # noqa: BLE001  单个结果出错不能拖垮轮询
                pass
        try:
            self._pump_id = self.root.after(self.PUMP_MS, self._pump)
        except Exception:          # noqa: BLE001  窗口已销毁
            self._pump_id = None

    # ── 状态查询 ──────────────────────────────────────────
    def state(self, key: str) -> TaskState:
        return self._states.setdefault(key, TaskState())

    def is_busy(self, key: str) -> bool:
        return self.state(key).status == "loading"

    # ── 转圈管理 ──────────────────────────────────────────
    def attach_spinner(self, key: str, spinner) -> None:
        """把一个 Spinner 绑到 key 上，任务开始时自动 start、结束自动 stop。"""
        self._spinners[key] = spinner

    def detach_spinners(self) -> None:
        """切 tab 重建界面时调用。

        旧控件已经被 destroy，这里只丢引用 —— 不能调 stop()，
        因为 stop 会去碰已经不存在的控件（虽然 Spinner 内部有保护，
        但没必要走那条路径）。
        """
        self._spinners.clear()

    def recolor_spinners(self, color: str, bg: str) -> None:
        """主题切换后统一改配色。"""
        for sp in self._spinners.values():
            try:
                sp.recolor(color, bg)
            except Exception:      # noqa: BLE001
                pass

    # ── 作废在途任务 ──────────────────────────────────────
    def invalidate(self, key: str | None = None) -> None:
        """让在途任务的结果失效。

        切 tab、换文件、点"重置"时调用：正在跑的那个任务还会跑完，
        但结果回来时代数不匹配，会被丢弃，不会覆盖新界面的状态。
        """
        targets = list(self._states.values()) if key is None else [self.state(key)]
        for st in targets:
            st.gen += 1
            if st.status == "loading":
                st.status = "idle"

    # ── 提交任务 ──────────────────────────────────────────
    def submit(self, key: str, fn, on_ok=None, on_err=None, quiet: bool = False) -> None:
        """后台执行 fn，结果回主线程交给 on_ok / on_err。

        quiet=True 时不显示转圈，用于很短的操作（如读文件头）。
        """
        st = self.state(key)
        st.gen += 1
        gen = st.gen
        st.status, st.error = "loading", ""

        spinner = None
        if not quiet:
            spinner = self._spinners.get(key)
            if spinner is not None:
                try:
                    spinner.start()
                except Exception:      # noqa: BLE001
                    # 启动失败也要保留引用：结束时必须尝试 stop()，
                    # 否则万一 place 成功了而后续失败，转圈会永久留在界面上。
                    pass

        def worker():
            # 线程里只做计算 + 入队，绝不碰任何 Tk 对象
            try:
                res = fn()
            except Exception as exc:       # noqa: BLE001
                self._q.put((key, gen, spinner, None, exc, on_ok, on_err))
            else:
                self._q.put((key, gen, spinner, res, None, on_ok, on_err))

        threading.Thread(target=worker, daemon=True,
                         name="cangtu-task-%s" % key).start()

    def _finish(self, key, gen, spinner, res, exc, on_ok, on_err) -> None:
        st = self.state(key)
        if st.gen != gen:
            return                      # 被更新的任务取代了，静默丢弃

        if spinner is not None:
            try:
                spinner.stop()
            except Exception:           # noqa: BLE001
                pass

        if exc is not None:
            st.status, st.error = "error", str(exc)
            if on_err is not None:
                try:
                    on_err(exc)
                except Exception:       # noqa: BLE001
                    pass
        else:
            st.status = "done"
            if on_ok is not None:
                try:
                    on_ok(res)
                except Exception:       # noqa: BLE001
                    pass
