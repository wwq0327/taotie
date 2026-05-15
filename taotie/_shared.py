"""共享工具函数和常量。"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterator

# ── 常量 ────────────────────────────────────────────────
RED = "\033[31m"
YELLOW = "\033[33m"
GREEN = "\033[32m"
CYAN = "\033[36m"
BOLD = "\033[1m"
RESET = "\033[0m"
DIM = "\033[2m"

_STRIP_ANSI_RE = re.compile(r"\033\[[0-9;]*m")

# ── HOME (支持测试时动态 patch) ────────────────────────
_home_getter: Callable[[], Path] = Path.home


def _set_home(path: Path) -> None:
    """设置 HOME 路径（用于测试）。"""
    global _home_getter
    _home_getter = lambda: path


def get_home() -> Path:
    """返回当前 HOME 路径。"""
    return _home_getter()


HOME = get_home()
LOG_DIR = HOME / ".local/share/taotie"
LOG_FILE = LOG_DIR / "taotie.log"


def fmt_size(size_bytes: int) -> str:
    for unit in ("B", "K", "M", "G", "T"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f}{unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f}P"


def color_size(size_bytes: int) -> str:
    s = fmt_size(size_bytes)
    if size_bytes >= 10 * 1024**3:
        return f"{RED}{s}{RESET}"
    elif size_bytes >= 1 * 1024**3:
        return f"{YELLOW}{s}{RESET}"
    return s


def run(cmd: str) -> list[str]:
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        return r.stdout.strip().split("\n") if r.stdout.strip() else []
    except Exception:
        return []


def du_sort(path, depth=1, top_n=10):
    parent = os.path.normpath(str(path))
    results = []

    # 尝试用 du（快）
    lines = run(f"du -d{depth} -k '{path}'")
    for line in lines:
        parts = line.split("\t", 1)
        if len(parts) == 2:
            results.append((parts[1], int(parts[0]) * 1024))

    # du 无结果时回退到 walk（如 /tmp 在非 TTY 下受限）
    if len(results) <= 1:
        results = []
        for p, s in _walk_items(path, depth):
            results.append((p, s))

    results.sort(key=lambda x: x[1], reverse=True)
    return [(p, s) for p, s in results if os.path.normpath(p) != parent][:top_n]


def _walk_items(path, depth, current_depth=0) -> Iterator:
    """walk 模式收集目录条目及其递归大小"""
    if current_depth > depth:
        return
    try:
        with os.scandir(path) as it:
            for entry in it:
                try:
                    if entry.is_dir(follow_symlinks=False):
                        size = du_total(entry.path)
                        yield (entry.path, size)
                    elif entry.is_file(follow_symlinks=False):
                        yield (entry.path, entry.stat().st_size)
                except OSError:
                    pass
    except PermissionError:
        pass


def du_total(path) -> int:
    """用 du 获取目录大小；/tmp 等受限目录改用 walk 累加。"""
    size = _du_total_fast(path)
    if size <= 0:
        size = _du_total_walk(path)
    return size


def _du_total_fast(path) -> int:
    lines = run(f"du -d1 -k '{path}'")
    if lines:
        try:
            return int(lines[-1].split()[0]) * 1024
        except (ValueError, IndexError):
            pass
    return -1


def _du_total_walk(path) -> int:
    """用 os.scandir 递归累加文件大小"""
    # 普通文件或失效 symlink → 直接返回大小
    if os.path.isfile(path):
        try:
            return os.lstat(path).st_size
        except OSError:
            return 0
    if os.path.islink(path) and not os.path.isdir(path):
        try:
            return os.lstat(path).st_size
        except OSError:
            return 0
    total = 0
    try:
        with os.scandir(path) as it:
            for entry in it:
                try:
                    if entry.is_dir(follow_symlinks=False):
                        total += _du_total_walk(entry.path)
                    elif entry.is_file(follow_symlinks=False):
                        total += entry.stat().st_size
                except OSError:
                    pass
    except PermissionError:
        pass
    # 加上目录自身大小
    try:
        total += os.lstat(path).st_size
    except OSError:
        pass
    return total


def print_header(text) -> None:
    print(f"\n{BOLD}{CYAN}═══ {text} ═══{RESET}")


def print_item(path, size, indent=2) -> None:
    display = path.replace(str(HOME), "~")
    print(f"{' ' * indent}{color_size(size):>10}  {display}")


def log_write(level, message, detail=""):
    """追加一条日志"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{level}] {message}"
    if detail:
        line += f"\n{detail}"
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def log_show(n=30):
    """显示最近 n 条日志"""
    if not LOG_FILE.exists():
        print("  暂无日志。")
        return
    lines = LOG_FILE.read_text().strip().split("\n")
    # 取最近 n 条（按时间戳行计数）
    entries = []
    current = None
    for line in lines:
        if line.startswith("[") and "]" in line[:22]:
            if current:
                entries.append(current)
            current = line
        elif current:
            current += "\n" + line
    if current:
        entries.append(current)
    for e in entries[-n:]:
        print(e + "\n")


def print_summary(output: dict) -> None:
    """打印汇总（C 模式：非 JSON）"""
    total = output["total_bytes"]
    print_header("汇总")
    for lv in ("safe", "medium", "manual"):
        info = output["levels"][lv]
        if info["bytes"] == 0:
            continue
        color = {"safe": GREEN, "medium": YELLOW, "manual": RED}[lv]
        print(f"  {color}{BOLD}{info['label']}{RESET}  ({fmt_size(info['bytes'])})")
    print(f"\n  {BOLD}总计: {fmt_size(total)}{RESET}")
    print(f"\n  {DIM}scan · clean · log · help{RESET}")
