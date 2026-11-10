# -*- coding: utf-8 -*-
"""抠图：把主体从背景里分离出来，输出透明 PNG 与三视图。

两种模式，共用同一套边缘处理：

  ai     检测到 models/ 下有分割模型时使用。语义分割能理解「哪个是人」，
         复杂背景（花纹、光效、渐变）也能抠，这是纯算法做不到的。

  basic  没有模型时退化为区域生长：从画面四边向内扩散，
         一路比较相邻像素色差。渐变背景能跟着走过去，主体描线是色差突变，走不过去。
         对纯色底、浅渐变底效果好；背景一复杂就失效，此时会明确报「不可靠」。

关键认识：无论哪种模式，分割结果都只是「大致范围」。
真正决定发梢质量的，是最后那步在边缘带内重新计算 alpha —— 见 _refine_alpha。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from . import paths as P

MODEL_DIR = P.ROOT / "models"
MODEL_NAMES = ("isnet-anime.onnx", "anime.onnx", "u2net.onnx", "isnet.onnx")

# 模型推理边长。anime-seg 训练时就是 1024
AI_SIZE = 1024


@dataclass
class Cutout:
    src: np.ndarray                      # 原图 BGR
    alpha: np.ndarray                    # 0..1 float，原图尺寸
    backdrop: str = "auto"               # white / black
    lumen: float = 0.0                   # 主体 alpha 加权亮度
    mode: str = "basic"                  # ai / basic
    issues: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    ms: int = 0

    @property
    def ok(self) -> bool:
        return not self.issues

    @property
    def size(self):
        h, w = self.alpha.shape[:2]
        return w, h

    @property
    def cover(self) -> float:
        return float((self.alpha > 0.5).mean())


# ── 模型发现 ──────────────────────────────────────────────
_session = None
_model_path = None


def find_model() -> Path | None:
    for name in MODEL_NAMES:
        p = MODEL_DIR / name
        if p.is_file() and p.stat().st_size > 1_000_000:
            return p
    if MODEL_DIR.is_dir():
        for p in sorted(MODEL_DIR.glob("*.onnx")):
            if p.stat().st_size > 1_000_000:
                return p
    return None


def _session_get(path: Path):
    global _session, _model_path
    if _session is not None and _model_path == path:
        return _session
    import onnxruntime as ort

    so = ort.SessionOptions()
    so.log_severity_level = 3
    so.intra_op_num_threads = 4          # CPU 推理，四线程足够，再多收益递减
    sess = ort.InferenceSession(str(path), sess_options=so,
                                providers=["CPUExecutionProvider"])
    _session, _model_path = sess, path
    return sess


def mode() -> str:
    return "ai" if find_model() else "basic"


# ── AI 分割 ───────────────────────────────────────────────
def _ai_mask(img: np.ndarray) -> np.ndarray:
    """返回 0..1 的前景概率，已放大回原图尺寸。"""
    path = find_model()
    if path is None:
        raise RuntimeError("没有可用的分割模型")
    sess = _session_get(path)

    h, w = img.shape[:2]
    name = sess.get_inputs()[0].name
    side = AI_SIZE                       # isnet-anime 训练分辨率就是 1024

    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    small = cv2.resize(rgb, (side, side), interpolation=cv2.INTER_AREA)
    x = small.astype(np.float32) / 255.0
    x = (x - np.array([0.485, 0.456, 0.406], np.float32)) / np.array(
        [0.229, 0.224, 0.225], np.float32)
    x = np.ascontiguousarray(x.transpose(2, 0, 1)[None])

    outs = sess.run(None, {name: x})
    m = np.asarray(outs[0], np.float32)
    while m.ndim > 2:
        m = m[0]
    if m.max() > 1.5 or m.min() < -0.5:          # 有些模型输出 logits
        m = 1.0 / (1.0 + np.exp(-m))
    m = np.clip(m, 0.0, 1.0)

    if m.shape != (h, w):
        m = cv2.resize(m, (w, h), interpolation=cv2.INTER_LINEAR)
    return m


# ── 纯算法：区域生长 ──────────────────────────────────────
def _auto_tolerance(img: np.ndarray, frac: float = 0.02) -> float:
    h, w = img.shape[:2]
    t = max(2, int(min(h, w) * frac))
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.int16)
    dx = np.abs(np.diff(g, axis=1))
    dy = np.abs(np.diff(g, axis=0))
    band = np.zeros((h, w), bool)
    band[:t, :] = band[-t:, :] = True
    band[:, :t] = band[:, -t:] = True
    vals = np.concatenate([dx[band[:, :-1]], dy[band[:-1, :]]]) if (dx.size and dy.size) else np.array([5])
    return float(np.clip(np.percentile(vals, 88) * 1.5 + 6.0, 8.0, 46.0))


def _grow_bg(img: np.ndarray, tol: float) -> np.ndarray:
    h, w = img.shape[:2]
    step = max(4, int(min(h, w) * 0.012))
    mask = np.zeros((h + 2, w + 2), np.uint8)
    work = img.copy()
    flags = 4 | cv2.FLOODFILL_MASK_ONLY | (255 << 8)
    lo = up = int(round(tol))

    seeds = [(x, 0) for x in range(0, w, step)] + [(x, h - 1) for x in range(0, w, step)]
    seeds += [(0, y) for y in range(0, h, step)] + [(w - 1, y) for y in range(0, h, step)]
    for sx, sy in seeds:
        if mask[sy + 1, sx + 1] != 0:
            continue
        cv2.floodFill(work, mask, (sx, sy), 0, (lo,) * 3, (up,) * 3, flags)
    return mask[1:-1, 1:-1].copy()


def _basic_mask(img: np.ndarray) -> tuple[np.ndarray, float]:
    tol = _auto_tolerance(img)
    bg = _grow_bg(img, tol)

    # 去掉与边界无关的碎斑（水印毛边、压缩噪点）
    n, lab, stats, _ = cv2.connectedComponentsWithStats((bg > 0).astype(np.uint8), 8)
    if n > 1:
        keep = np.zeros_like(bg)
        for i in range(1, n):
            if stats[i, cv2.CC_STAT_AREA] >= max(16, int(bg.size * 0.0004)):
                keep[lab == i] = 255
        bg = keep

    sub = cv2.bitwise_not(bg)
    sub = cv2.morphologyEx(sub, cv2.MORPH_OPEN,
                           cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
    sub = _fill_holes(sub)
    return sub.astype(np.float32) / 255.0, tol


def _fill_holes(mask: np.ndarray) -> np.ndarray:
    """把被主体包住的背景孔洞补回主体。

    判据是「有没有碰到图像边界」而不是「从某点能否走到」：
    背景常被主体切成几块互不连通，单点泛洪只能覆盖其中一块，
    其余会被整片误判成孔洞 —— 实测能把主体从 52% 撑到 99%。
    """
    h, w = mask.shape
    inv = (mask == 0).astype(np.uint8)
    n, lab = cv2.connectedComponents(inv, connectivity=8)
    if n <= 1:
        return mask
    edge = set(lab[0, :].ravel().tolist())
    edge.update(lab[-1, :].ravel().tolist())
    edge.update(lab[:, 0].ravel().tolist())
    edge.update(lab[:, -1].ravel().tolist())
    edge.discard(0)
    hole = (inv > 0) & (~np.isin(lab, list(edge)))
    out = mask.copy()
    out[hole] = 255
    return out


# ── 边缘精修（两模式共用）──────────────────────────────────
def _box(x: np.ndarray, r: int) -> np.ndarray:
    k = 2 * r + 1
    return cv2.boxFilter(x, -1, (k, k), normalize=True, borderType=cv2.BORDER_REFLECT)


def _guided(guide: np.ndarray, src: np.ndarray, r: int, eps: float) -> np.ndarray:
    """引导滤波：让 src 的边缘跟着 guide 走。

    AI 输出的 mask 是 1024 边长、双线性放大后边缘会糊成 3 像素宽的斜坡；
    纯算法得到的 mask 边缘是硬的。用原图灰度做引导，两者都能重新贴合
    真实边缘 —— 发梢那种 1~2 像素的细结构主要靠这一步保住。
    """
    mi = _box(guide, r)
    mp = _box(src, r)
    cov_ip = _box(guide * src, r) - mi * mp
    var_i = _box(guide * guide, r) - mi * mi
    a = cov_ip / (var_i + eps)
    b = mp - a * mi
    return _box(a, r) * guide + _box(b, r)


def _refine_alpha(img: np.ndarray, mask: np.ndarray) -> np.ndarray:
    h, w = img.shape[:2]
    m = np.clip(mask.astype(np.float32), 0.0, 1.0)

    # 极端值先固定，只让过渡区参与后续计算
    solid = m > 0.985
    empty = m < 0.015

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
    r = max(2, int(round(min(h, w) * 0.0016)))
    r = min(r, 5)
    g = _guided(gray, m, r, 1e-4)
    g = np.clip(g, 0.0, 1.0)

    # 只在过渡带替换，避免把主体内部被引导滤波拉花的区域算进来
    band = cv2.subtract(cv2.dilate((m > 0.5).astype(np.uint8),
                                  np.ones((2 * r + 3, 2 * r + 3), np.uint8)),
                        cv2.erode((m > 0.5).astype(np.uint8),
                                  np.ones((2 * r + 1, 2 * r + 1), np.uint8))) > 0
    out = m.copy()
    out[band] = g[band]
    out[solid] = 1.0
    out[empty] = 0.0
    return np.clip(out, 0.0, 1.0)


# ── 底色选择 ──────────────────────────────────────────────
def _luma(img: np.ndarray, alpha: np.ndarray) -> float:
    """主体自身的亮度（alpha 加权），用于决定衬白底还是黑底。"""
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
    w = np.clip(alpha, 0.0, 1.0)
    s = float(w.sum())
    if s < 1e-3:
        return float(g.mean())
    return float((g * w).sum() / s)


def pick_backdrop(lumen: float) -> str:
    """深色主体衬白底，浅色主体衬黑底 —— 让边缘对比最大。"""
    return "white" if lumen < 140 else "black"


def _drop_orphan_fringe(img: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    """清掉远离主体的半透明碎片。

    AI 分割对「像前景的模糊背景」会给出中间概率 —— 光斑、花瓣、烟雾
    常被打成 0.2~0.5 的半透明块，散在主体周围。它们不是发梢
    （发梢一定与主体轮廓相连），所以判据是「离主体主块多远」：
    主块向外扩一小圈，圈外的半透明一律清掉。
    """
    h, w = alpha.shape[:2]
    core = (alpha > 0.5).astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(core, 8)
    if n <= 1:
        return alpha

    main = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    r = max(2, int(min(h, w) * 0.006))
    near = cv2.dilate((lab == main).astype(np.uint8),
                      cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1,) * 2)) > 0

    out = alpha.copy()
    out[(~near) & (out < 0.55)] = 0.0
    return out


# ── 主流程 ────────────────────────────────────────────────
def cut(path: str, use_ai: bool = True, max_side: int = 0) -> Cutout | None:
    t0 = time.time()
    raw = np.fromfile(path, dtype=np.uint8)
    img = cv2.imdecode(raw, cv2.IMREAD_COLOR)
    if img is None:
        return None
    h, w = img.shape[:2]

    # 预览走缩略图：AI 推理本来就在 1024 上做，缩了不影响效果，
    # 只是让引导滤波和界面刷新快很多。保存时才按原尺寸重算。
    if max_side and max(h, w) > max_side:
        s = max_side / max(h, w)
        img = cv2.resize(img, (max(1, int(w * s)), max(1, int(h * s))),
                         interpolation=cv2.INTER_AREA)

    notes: list[str] = []
    used = "basic"
    if use_ai and find_model() is not None:
        try:
            mask = _ai_mask(img)
            used = "ai"
        except Exception as exc:                      # noqa: BLE001
            notes.append("模型推理失败，已退回纯算法：%s" % exc)
            mask, tol = _basic_mask(img)
            notes.append("区域生长容差 %.1f" % tol)
    else:
        mask, tol = _basic_mask(img)
        notes.append("区域生长容差 %.1f" % tol)

    alpha = _refine_alpha(img, mask)
    alpha = _drop_orphan_fringe(img, alpha)
    cover = float((alpha > 0.5).mean())

    # 分割模型只认「人/角色」这类主体。遇到抽象图、纯色块、文字图、产品特写，
    # 它会整张给 0 —— 这不是算法坏了，是训练数据里没有这类样本。
    # 与其给一张空图，不如退回纯算法再试一次。
    if used == "ai" and cover < 0.01:
        notes.append("AI 模型没识别出主体，已自动退回基础算法")
        mask, tol = _basic_mask(img)
        notes.append("区域生长容差 %.1f" % tol)
        alpha = _refine_alpha(img, mask)
        alpha = _drop_orphan_fringe(img, alpha)
        cover = float((alpha > 0.5).mean())
        used = "basic"

    lum = _luma(img, alpha)

    issues: list[str] = []
    if cover < 0.02:
        issues.append("几乎没抠出东西")
    elif cover > 0.985:
        issues.append("背景没被识别，整张图都算进了主体")
    edge_touch = float(((alpha[0, :] > 0.5).mean() + (alpha[-1, :] > 0.5).mean()
                        + (alpha[:, 0] > 0.5).mean() + (alpha[:, -1] > 0.5).mean()) / 4)
    # 特写构图本来就会撑满画面，主体占比大时贴边是正常的，不算问题
    if edge_touch > 0.35 and cover < 0.55:
        issues.append("主体贴着画面边缘，可能连带把背景留下了")

    if used == "basic" and not issues and cover > 0.02:
        # 纯算法在复杂背景上常给出「看着正常但其实是碎块」的结果，补一道检查
        n, lab, stats, _ = cv2.connectedComponentsWithStats(
            (alpha > 0.5).astype(np.uint8), 8)
        big = [s for s in stats[1:, cv2.CC_STAT_AREA] if s > alpha.size * 0.004]
        if len(big) == 0:
            issues.append("没找到明显的主体块")
        elif len(big) > 8:
            issues.append("结果碎成 %d 块，背景可能太复杂" % len(big))

    return Cutout(src=img, alpha=alpha, backdrop=pick_backdrop(lum), lumen=lum,
                  mode=used, issues=issues, notes=notes,
                  ms=int((time.time() - t0) * 1000))


# ── 出图 ──────────────────────────────────────────────────
def checker(h: int, w: int, cell: int | None = None) -> np.ndarray:
    cell = cell or max(8, min(h, w) // 36)
    yy, xx = np.mgrid[0:h, 0:w]
    v = np.where(((yy // cell) + (xx // cell)) % 2 > 0, 208, 158).astype(np.uint8)
    return np.dstack([v] * 3)


def layers(result: Cutout, backdrop: str = "auto") -> tuple:
    """拆成三张：原图 / 抠出（棋盘格）/ 纯色底。界面要分开摆，所以要单独拿。"""
    img = result.src
    a = result.alpha
    h, w = a.shape[:2]
    if backdrop == "auto":
        backdrop = result.backdrop

    a3 = np.dstack([a] * 3).astype(np.float32)
    f = img.astype(np.float32)
    mid = (f * a3 + checker(h, w).astype(np.float32) * (1 - a3)).astype(np.uint8)

    plate = np.full_like(img, 255 if backdrop == "white" else 0)
    right = (f * a3 + plate.astype(np.float32) * (1 - a3)).astype(np.uint8)
    return img, mid, right


def compose(result: Cutout, backdrop: str = "auto", gap: int = 0) -> np.ndarray:
    """左：原图 / 中：抠出的元素 / 右：纯色底。"""
    if backdrop == "auto":
        backdrop = result.backdrop
    left, mid, right = layers(result, backdrop)
    if gap > 0:
        sep = np.full((left.shape[0], gap, 3), 40, np.uint8)
        return np.hstack([left, sep, mid, sep, right])
    return np.hstack([left, mid, right])


def as_pil(bgr: np.ndarray):
    """BGR ndarray → PIL，界面控件吃 PIL。"""
    from PIL import Image

    return Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))


def to_rgba(result: Cutout) -> np.ndarray:
    a = (np.clip(result.alpha, 0, 1) * 255).astype(np.uint8)
    return cv2.cvtColor(np.dstack([result.src, a]), cv2.COLOR_BGRA2RGBA)


def save_png(result: Cutout, out_path: str) -> str:
    rgba = to_rgba(result)
    ok, buf = cv2.imencode(".png", rgba)
    if not ok:
        raise RuntimeError("PNG 编码失败")
    buf.tofile(out_path)
    return out_path


def save_compose(result: Cutout, out_path: str, backdrop: str = "auto",
                 max_side: int = 0) -> str:
    comp = compose(result, backdrop)
    if max_side and max(comp.shape[:2]) > max_side:
        s = max_side / max(comp.shape[:2])
        comp = cv2.resize(comp, (int(comp.shape[1] * s), int(comp.shape[0] * s)),
                          interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".png", comp)
    if not ok:
        raise RuntimeError("PNG 编码失败")
    buf.tofile(out_path)
    return out_path


def shrink(result: Cutout, max_side: int = 1400) -> Cutout:
    """给界面显示用的缩略版本，避免几千万像素的图拖慢 Tk。"""
    h, w = result.alpha.shape[:2]
    s = max_side / max(h, w)
    if s >= 1:
        return result
    nw, nh = max(1, int(w * s)), max(1, int(h * s))
    return Cutout(src=cv2.resize(result.src, (nw, nh), interpolation=cv2.INTER_AREA),
                  alpha=cv2.resize(result.alpha, (nw, nh), interpolation=cv2.INTER_AREA),
                  backdrop=result.backdrop, lumen=result.lumen, mode=result.mode,
                  issues=list(result.issues), notes=list(result.notes), ms=result.ms)
