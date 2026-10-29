# -*- coding: utf-8 -*-
"""路径、配置、日志 —— 程序运行的基本设施。

打包成 exe 后（PyInstaller onedir），__file__ 指向临时目录，不能当程序目录用。
判断依据是 sys.frozen，此时程序目录 = exe 自己所在的目录。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


ROOT = app_root()
CONFIG_PATH = ROOT / "config.json"
LOG_DIR = ROOT / "logs"
OUT_DIR = ROOT / "output"

DEFAULTS = {
    "theme": "dark",
    "bright": 55,          # 幻影坦克：后面的图亮度 %
    "boost": False,        # 幻影坦克：前景提亮
    "reveal_auto": True,   # 幻影提取：自动提亮
    "reveal_factor": 2.0,
    "max_side": 2600,      # 生成的幻影图最长边
    "last_dir": "",
}


def _ensure_dirs() -> None:
    for d in (LOG_DIR, OUT_DIR):
        try:
            d.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            for k, v in raw.items():
                if k in DEFAULTS:
                    cfg[k] = v
    except Exception:
        pass
    return cfg


def save_config(cfg: dict) -> None:
    try:
        _ensure_dirs()
        CONFIG_PATH.write_text(
            json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        pass


def write_log(name: str, text: str) -> None:
    try:
        _ensure_dirs()
        (LOG_DIR / name).write_text(text, encoding="utf-8")
    except Exception:
        pass


_ensure_dirs()
