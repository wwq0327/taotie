"""缓存分类和表格展示工具。"""
from __future__ import annotations

import os
import re
from pathlib import Path

from taotie._shared import (
    RED, YELLOW, GREEN, BOLD, RESET,
    _STRIP_ANSI_RE, get_home,
)

PY_CACHE_DIRS = {"uv", "pip"}  # safe 级里的 ~/.cache/xxx 子目录

# ── 路径缓存 ─────────────────────────────────────────

def _make_cache():
    home = get_home()
    safe_paths = {
        str(home / ".Trash"),
        str(home / "Library/Caches"),
        "/tmp",
        "/private/tmp",
    }
    medium_paths = {
        str(home / ".cache/whisper"),
        str(home / ".cache/huggingface"),
        str(home / "Library/Logs"),
    }
    return (
        tuple(os.path.normpath(sp) for sp in safe_paths),
        tuple(os.path.normpath(mp) for mp in medium_paths),
        os.path.normpath(str(home / ".cache")),
    )

_cache = None

def _get_path_cache():
    global _cache
    if _cache is None:
        _cache = _make_cache()
    return _cache

def _reset_path_cache():
    global _cache
    _cache = None

def classify(path: str, parent_title: str) -> str:
    safe_norm, medium_norm, cache_dir_norm = _get_path_cache()
    p = os.path.normpath(path)
    for sp in safe_norm:
        if p.startswith(sp):
            return "safe"
    for mp in medium_norm:
        if p.startswith(mp):
            return "medium"
    if p.startswith(cache_dir_norm):
        sub = os.path.relpath(p, cache_dir_norm).split("/")[0]
        if sub in PY_CACHE_DIRS:
            return "safe"
        return "medium"
    return "manual"

# ── 表格工具 ─────────────────────────────────────────

def _strip_ansi(s: str) -> str:
    return _STRIP_ANSI_RE.sub("", s)

def _pad(s: str, width: int) -> str:
    visible = _strip_ansi(s)
    return s + " " * (width - len(visible))

def _table_sep(col_widths: list[int], pos: str) -> str:
    if pos == "top":
        return f"  ┌─{'─┬─'.join('─' * w for w in col_widths)}─┐"
    elif pos == "mid":
        return f"  ├─{'─┼─'.join('─' * w for w in col_widths)}─┤"
    else:
        return f"  └─{'─┴─'.join('─' * w for w in col_widths)}─┘"

def _table(rows: list[list[str]], col_widths: list[int], headers: list[str]) -> str:
    lines = [_table_sep(col_widths, "top")]
    hdr = " │ ".join(f"{BOLD}{_pad(h, w)}{RESET}" for h, w in zip(headers, col_widths))
    lines.append(f"  │ {hdr} │")
    lines.append(_table_sep(col_widths, "mid"))
    for cells in rows:
        row = " │ ".join(_pad(c, w) for c, w in zip(cells, col_widths))
        lines.append(f"  │ {row} │")
    lines.append(_table_sep(col_widths, "bot"))
    return "\n".join(lines)
