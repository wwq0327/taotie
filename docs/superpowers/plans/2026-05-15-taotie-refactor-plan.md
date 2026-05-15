# taotie 重构实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 641 行单文件拆分为 7 个模块，增加类型注解，扩大测试覆盖率，npm cache  medium 级清理。

**Architecture:** 按设计 spec 分为 `_shared`（工具）、`_cache`（分类/展示）、`scan`/`clean`/`log`（命令）、`taotie`（路由）、`__init__`（导出）。无循环依赖。

**Tech Stack:** Python 标准库（无外部依赖）, pytest

---

## 文件结构

| 文件 | 职责 |
|------|------|
| `taotie/__init__.py` | 导出 scan/clean/log 入口 |
| `taotie/_shared.py` | 共享工具: fmt_size, run, du_sort, du_total, 颜色常量 |
| `taotie/_cache.py` | 分类/展示: classify, _strip_ansi, _table |
| `taotie/scan.py` | scan 命令 |
| `taotie/clean.py` | clean 命令 + npm cache |
| `taotie/log.py` | log 命令 |
| `taotie/taotie.py` | 入口:main(), argparse |
| `tests/test_taotie.py` | 测试文件 |

**注意**：将现有 `taotie.py` 内容正确分配到各模块，不重复代码。

---

### Task 1: 创建 `taotie/` 目录结构，抽出 `_shared.py`

**Files:**
- Create: `taotie/__init__.py`
- Create: `taotie/_shared.py` (从现有 taotie.py 抽出共享工具)
- Modify: `taotie.py` (删除已抽出函数，保留导入)
- Test: `tests/test_taotie.py`

**步骤:**

- [ ] **Step 1: 创建 `taotie/` 目录**

```bash
mkdir -p taotie
```

- [ ] **Step 2: 创建 `taotie/__init__.py`**

```python
"""taotie — 吞磁盘垃圾的饕餮。"""
from taotie.scan import cmd_scan
from taotie.clean import cmd_clean
from taotie.log import cmd_log

__all__ = ["cmd_scan", "cmd_clean", "cmd_log"]
```

- [ ] **Step 3: 创建 `taotie/_shared.py`**

```python
"""共享工具: 格式化、颜色、subprocess、du 工具。"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Iterator

# 常量
RED = "\033[31m"
YELLOW = "\033[33m"
GREEN = "\033[32m"
CYAN = "\033[36m"
BOLD = "\033[1m"
RESET = "\033[0m"

_STRIP_ANSI_RE = re.compile(r"\033\[[0-9;]*m")

HOME = Path.home()
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


def _walk_items(path: str, depth: int, current_depth: int = 0) -> Iterator[tuple[str, int]]:
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


def du_sort(path: str, depth: int = 1, top_n: int = 10) -> list[tuple[str, int]]:
    """返回 (path, size) 列表，按 size 降序。"""
    parent = os.path.normpath(path)
    results: list[tuple[str, int]] = []

    lines = run(f"du -d{depth} -k '{path}'")
    for line in lines:
        parts = line.split("\t", 1)
        if len(parts) == 2:
            results.append((parts[1], int(parts[0]) * 1024))

    if len(results) <= 1:
        results = []
        for p, s in _walk_items(path, depth):
            results.append((p, s))

    results.sort(key=lambda x: x[1], reverse=True)
    return [(p, s) for p, s in results if os.path.normpath(p) != parent][:top_n]


def _du_total_fast(path: str) -> int:
    lines = run(f"du -d1 -k '{path}'")
    if lines:
        try:
            return int(lines[-1].split()[0]) * 1024
        except (ValueError, IndexError):
            pass
    return -1


def _du_total_walk(path: str) -> int:
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
    try:
        total += os.lstat(path).st_size
    except OSError:
        pass
    return total


def du_total(path: str) -> int:
    """用 du 获取目录大小；/tmp 等受限目录改用 walk 累加。"""
    size = _du_total_fast(path)
    if size <= 0:
        size = _du_total_walk(path)
    return size


def print_header(text: str) -> None:
    print(f"\n{BOLD}{CYAN}═══ {text} ═══{RESET}")


def print_item(path: str, size: int, indent: int = 2) -> None:
    display = path.replace(str(HOME), "~")
    print(f"{' ' * indent}{color_size(size):>10}  {display}")
```

- [ ] **Step 4: 更新 `taotie.py` 顶部**

在文件顶部 import 后添加：

```python
from taotie._shared import (
    fmt_size, color_size, run, du_sort, du_total,
    print_header, print_item, HOME, LOG_DIR, LOG_FILE,
    RED, YELLOW, GREEN, CYAN, BOLD, RESET,
    _STRIP_ANSI_RE,
)
```

并删除已移走的函数定义（fmt_size, color_size, run, du_sort, _walk_items, du_total, _du_total_fast, _du_total_walk, print_header, print_item）。

- [ ] **Step 5: 更新测试 import**

测试文件 `tests/test_taotie.py` 需修改 import：
```python
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
import taotie._shared as shared
```

- [ ] **Step 6: 运行测试**

```bash
python -m pytest tests/test_taotie.py -v
```

预期: PASS (所有 10 个测试)

- [ ] **Step 7: Commit**

```bash
git add taotie/ taotie.py tests/test_taotie.py
git commit -m "refactor: extract _shared.py with fmt_size, run, du_*, print utilities"
```

---

### Task 2: 抽出 `_cache.py`

**Files:**
- Create: `taotie/_cache.py`
- Modify: `taotie.py` (删除已抽出内容)
- Test: `tests/test_taotie.py` (update classify tests import)

**步骤:**

- [ ] **Step 1: 创建 `taotie/_cache.py`**

```python
"""缓存分类和表格展示工具。"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Final

# 颜色常量 (从 _shared 导入)
RED = "\033[31m"
YELLOW = "\033[33m"
GREEN = "\033[32m"
BOLD = "\033[1m"
RESET = "\033[0m"

_STRIP_ANSI_RE = re.compile(r"\033\[[0-9;]*m")

HOME: Final[Path] = Path.home()

# 清理等级分类常量
SAFE_PATHS: Final[frozenset[str]] = frozenset({
    str(HOME / ".Trash"),
    str(HOME / "Library/Caches"),
    "/tmp",
    "/private/tmp",
})

MEDIUM_PATHS: Final[frozenset[str]] = frozenset({
    str(HOME / ".cache/whisper"),
    str(HOME / ".cache/huggingface"),
    str(HOME / ".cache/npm"),
    str(HOME / "Library/Logs"),
})

PY_CACHE_DIRS: Final[frozenset[str]] = frozenset({"uv", "pip"})


# 模块级缓存 (惰性初始化)
_cache: tuple[tuple[str, ...], tuple[str, ...], str] | None = None


def _make_cache() -> tuple[tuple[str, ...], tuple[str, ...], str]:
    return (
        tuple(os.path.normpath(sp) for sp in SAFE_PATHS),
        tuple(os.path.normpath(mp) for mp in MEDIUM_PATHS),
        os.path.normpath(str(HOME / ".cache")),
    )


def _get_path_cache() -> tuple[tuple[str, ...], tuple[str, ...], str]:
    global _cache
    if _cache is None:
        # pylint: disable=global-statement
        _cache = _make_cache()
    return _cache


def _reset_path_cache() -> None:
    """重置路径缓存 (用于测试)."""
    global _cache
    _cache = None


def classify(path: str, parent_title: str) -> str:
    """判断一个扫描条目属于哪个清理等级。返回 'safe'|'medium'|'manual'。"""
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


def _strip_ansi(s: str) -> str:
    return _STRIP_ANSI_RE.sub("", s)


def _pad(s: str, width: int) -> str:
    """按可见宽度填充字符串（忽略 ANSI 码）"""
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
    """画 Unicode 框线表格。rows 是已着色字符串的列表。"""
    lines = [_table_sep(col_widths, "top")]
    hdr = " │ ".join(f"{BOLD}{_pad(h, w)}{RESET}" for h, w in zip(headers, col_widths))
    lines.append(f"  │ {hdr} │")
    lines.append(_table_sep(col_widths, "mid"))
    for cells in rows:
        row = " │ ".join(_pad(c, w) for c, w in zip(cells, col_widths))
        lines.append(f"  │ {row} │")
    lines.append(_table_sep(col_widths, "bot"))
    return "\n".join(lines)
```

- [ ] **Step 2: 更新 `taotie.py`** - 删除 classify, _strip_ansi, _pad, _table_sep, _table, _make_cache, _get_path_cache, _reset_path_cache, SAFE_PATHS, MEDIUM_PATHS, PY_CACHE_DIRS

- [ ] **Step 3: 更新测试 import**

```python
import taotie._cache as cache_mod
# 并修改所有 taotie.classify -> cache_mod.classify
# taotie._reset_path_cache -> cache_mod._reset_path_cache
```

- [ ] **Step 4: 运行测试**

```bash
python -m pytest tests/test_taotie.py -v
```

预期: PASS

- [ ] **Step 5: Commit**

```bash
git add taotie/_cache.py taotie.py tests/test_taotie.py
git commit -m "refactor: extract _cache.py with classify, _table, path cache"
```

---

### Task 3: 抽出 `scan.py`

**Files:**
- Create: `taotie/scan.py`
- Modify: `taotie.py` (删除已抽出内容)
- Test: `tests/test_taotie.py`

**步骤:**

- [ ] **Step 1: 创建 `taotie/scan.py`**

```python
"""scan 命令。"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from taotie._shared import (
    HOME, CYAN, BOLD, RED, YELLOW, GREEN, RESET,
    fmt_size, color_size, run, du_total, du_sort, print_header,
)
from taotie._cache import classify, _table


def scan_overview() -> None:
    """打印磁盘概览和 APFS 快照。"""
    print_header("磁盘概览")
    for line in run("df -h /"):
        print(f"  {line}")
    snapshots = run("tmutil listlocalsnapshots / 2>/dev/null")
    names = [s for s in snapshots if s.startswith("com.")]
    if names:
        print(f"\n  APFS 本地快照: {len(names)} 个")
        for n in names:
            print(f"    {n}")
    else:
        print(f"\n  APFS 本地快照: 无")


def _collect_items(title: str, path: Path, depth: int, top_n: int) -> tuple[str, list[tuple], int]:
    """收集扫描数据。返回 (title, items, total)。"""
    if not os.path.exists(str(path)):
        return title, [], 0
    total = du_total(str(path))
    if total == 0:
        return title, [], 0
    raw = du_sort(str(path), depth, top_n)
    rows: list[tuple] = []
    for p, size in raw:
        if size == 0:
            continue
        level = classify(p, title)
        display = p.replace(str(HOME), "~")
        rows.append((display, size, level))
    return title, rows, total


def _print_dir_table(title: str, items: list[tuple], total: int) -> None:
    """打印一个目录的框线表格。"""
    if not items:
        if total > 0:
            print_header(f"{title}  ({fmt_size(total)})")
        return
    print_header(f"{title}  ({fmt_size(total)})")

    max_path = 40
    for display, _, _ in items:
        max_path = max(max_path, len(display))
    max_path = min(max_path, 65)
    col_w = [8, 10, max_path]

    level_color = {"safe": GREEN, "medium": YELLOW}
    table_rows = []
    for display, size, level in items:
        lc = level_color.get(level, "")
        lvl = f"{lc}{level}{RESET}" if lc else level
        table_rows.append([lvl, color_size(size), display])

    print(_table(table_rows, col_w, ["Level", "Size", "Path"]))


def cmd_scan() -> None:
    """执行磁盘扫描。"""
    scan_overview()

    scans: list[tuple[str, Path, int, int]] = [
        ("废纸篓", HOME / ".Trash", 2, 10),
        ("/tmp", Path("/tmp"), 1, 10),
        ("~/Library/Caches", HOME / "Library/Caches", 1, 5),
        ("~/Library/Logs", HOME / "Library/Logs", 1, 5),
        ("~/Library/Application Support", HOME / "Library/Application Support", 1, 5),
        ("~/Library/Containers", HOME / "Library/Containers", 1, 5),
        ("~/Library/Group Containers", HOME / "Library/Group Containers", 1, 5),
        ("~/.cache", HOME / ".cache", 1, 5),
        ("~/Movies", HOME / "Movies", 1, 5),
        ("/opt", Path("/opt"), 1, 5),
        ("/Library (系统)", Path("/Library"), 1, 5),
        ("/private/var", Path("/private/var"), 1, 5),
        ("/System/Volumes/Data/System", Path("/System/Volumes/Data/System"), 1, 5),
    ]

    total_scans = len(scans)
    results: dict[str, tuple[list, int]] = {}
    print(f"\n  {CYAN}扫描中…{RESET}")
    with ThreadPoolExecutor(max_workers=12) as ex:
        futures = {ex.submit(_collect_items, t, p, d, n): t for t, p, d, n in scans}
        for f in as_completed(futures):
            title, items, total = f.result()
            results[title] = (items, total)
            n = len(results)
            bar = "▓" * (n * 20 // total_scans) + "░" * (20 - n * 20 // total_scans)
            print(f"  {bar}  [{n}/{total_scans}]  {title}  {color_size(total)}")

    print()
    all_items: list = []
    for title, _, _, _ in scans:
        items, total = results.get(title, ([], 0))
        _print_dir_table(title, items, total)
        all_items.extend(items)

    # 汇总
    print_header("汇总")
    level_color = {"safe": GREEN, "medium": YELLOW, "manual": RED}
    level_labels: list[tuple[str, str]] = [
        ("safe", "safe 级可清理"),
        ("medium", "medium 级可清理"),
        ("manual", "需手动判断"),
    ]

    lv_groups: dict[str, list] = {}
    for lv, label in level_labels:
        items = [(d, s) for d, s, l in all_items if l == lv]
        items.sort(key=lambda x: x[1], reverse=True)
        lv_groups[lv] = items

    max_rows = min(max(len(v) for v in lv_groups.values()), 15)
    if max_rows == 0:
        print("  无数据\n")
        return

    path_w = 40
    for items in lv_groups.values():
        for d, _ in items[:max_rows]:
            path_w = max(path_w, len(d))
    path_w = min(path_w, 55)
    col_w = [10, path_w]

    grand_total = 0
    for lv, label in level_labels:
        items = lv_groups[lv]
        total = sum(s for _, s in items)
        grand_total += total
        lc = level_color[lv]

        print(f"\n  {lc}{BOLD}{label}{RESET}  ({fmt_size(total)})")
        if not items:
            print("    (无)")
            continue

        table_rows = []
        for i in range(max_rows):
            if i < len(items):
                d, s = items[i]
                table_rows.append([color_size(s), d])
            else:
                table_rows.append(["", ""])

        print(_table(table_rows, col_w, ["Size", "Path"]))

    print(f"\n  {BOLD}总计: {fmt_size(grand_total)}{RESET} "
          f"(分布: {GREEN}safe{RESET} / {YELLOW}medium{RESET} / {RED}manual{RESET})\n")

    # 记日志
    from taotie.log import log_write
    lines = [f"总计 {fmt_size(grand_total)}"]
    for lv, label in level_labels:
        items = lv_groups[lv]
        if items:
            t = sum(s for _, s in items)
            lines.append(f"  [{lv}] {fmt_size(t)}")
            for d, s in items[:10]:
                lines.append(f"    {fmt_size(s):>8}  {d}")
    log_write("SCAN", "磁盘诊断", "\n".join(lines))
```

- [ ] **Step 2: 更新 `taotie.py`** - 删除 scan_overview, _collect_items, _print_dir_table, cmd_scan, scans 常量

- [ ] **Step 3: 运行测试**

```bash
python -m pytest tests/test_taotie.py -v
```

预期: PASS

- [ ] **Step 4: Commit**

```bash
git add taotie/scan.py taotie.py
git commit -m "refactor: extract scan.py with cmd_scan and scan_overview"
```

---

### Task 4: 抽出 `log.py`

**Files:**
- Create: `taotie/log.py`
- Modify: `taotie.py` (删除已抽出内容)
- Test: 无需新测试（log_write/log_show 通过集成测试覆盖）

**步骤:**

- [ ] **Step 1: 创建 `taotie/log.py`**

```python
"""日志模块。"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from taotie._shared import LOG_DIR, LOG_FILE


def log_write(level: str, message: str, detail: str = "") -> None:
    """追加一条日志。"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{level}] {message}"
    if detail:
        line += f"\n{detail}"
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def log_show(n: int = 30) -> None:
    """显示最近 n 条日志。"""
    if not LOG_FILE.exists():
        print("  暂无日志。")
        return
    lines = LOG_FILE.read_text(encoding="utf-8").strip().split("\n")
    entries: list[str] = []
    current: str | None = None
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


def cmd_log(n: int) -> None:
    """CLI log 命令入口。"""
    log_show(n)
```

- [ ] **Step 2: 更新 `taotie.py`** - 删除 log_write, log_show, cmd_log

- [ ] **Step 3: Commit**

```bash
git add taotie/log.py taotie.py
git commit -m "refactor: extract log.py with log_write, log_show, cmd_log"
```

---

### Task 5: 抽出 `clean.py` + npm cache

**Files:**
- Create: `taotie/clean.py`
- Modify: `taotie.py` (删除已抽出内容)
- Test: `tests/test_taotie.py` (添加 npm cache 测试)

**步骤:**

- [ ] **Step 1: 创建 `taotie/clean.py`**

```python
"""clean 命令。"""
from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

from taotie._shared import (
    HOME, RED, YELLOW, GREEN, BOLD, RESET,
    fmt_size, color_size, du_total,
)
from taotie._cache import classify


def collect_dir(dir_path: str) -> list[tuple[str, int]]:
    """列出目录下所有条目及其大小。"""
    if not os.path.isdir(dir_path):
        return []
    items: list[tuple[str, int]] = []
    try:
        for entry in os.listdir(dir_path):
            epath = os.path.join(dir_path, entry)
            size = du_total(epath)
            if size > 0:
                items.append((epath, size))
    except PermissionError:
        pass
    return items


def collect_tmp() -> list[tuple[str, int]]:
    """收集 /tmp 中安全可删的文件 (>1天, 非系统)。"""
    now = time.time()
    items: list[tuple[str, int]] = []
    try:
        for entry in os.listdir("/tmp"):
            if entry.startswith("com.apple.") or entry == "powerlog":
                continue
            epath = os.path.join("/tmp", entry)
            if (now - os.path.getmtime(epath)) / 86400 < 1:
                continue
            size = du_total(epath)
            if size > 0:
                items.append((epath, size))
    except PermissionError:
        pass
    return items


def collect_npm_logs() -> list[tuple[str, int]]:
    """收集 ~/.npm/_logs/ 下修改时间 >7 天的 npm 错误日志。"""
    npm_logs = HOME / ".npm" / "_logs"
    if not npm_logs.exists():
        return []
    now = time.time()
    items: list[tuple[str, int]] = []
    try:
        for entry in os.listdir(str(npm_logs)):
            if not entry.endswith(".log"):
                continue
            epath = str(npm_logs / entry)
            if (now - os.path.getmtime(epath)) / 86400 > 7:
                size = du_total(epath)
                if size > 0:
                    items.append((epath, size))
    except PermissionError:
        pass
    return items


def delete_items(items: list[tuple[str, int]], desc: str) -> list[tuple[str, int]]:
    """删除指定条目，返回实际删除的 (path, size) 列表。"""
    print(f"\n  清理 {desc}...")
    deleted = 0
    deleted_paths: list[tuple[str, int]] = []
    for p, size in items:
        try:
            if os.path.isdir(p) and not os.path.islink(p):
                shutil.rmtree(p, ignore_errors=True)
            else:
                os.unlink(p)
            deleted += size
            deleted_paths.append((p, size))
        except Exception:
            pass
    print(f"    {GREEN}已清理 {fmt_size(deleted)}{RESET}")
    return deleted_paths


def cmd_clean(level: str, dry_run: bool) -> None:
    """执行清理。"""
    targets: list[tuple[str, list[tuple[str, int]]]] = []

    # Safe: 废纸篓 + Caches + /tmp 过期文件
    trash = collect_dir(str(HOME / ".Trash"))
    if trash:
        targets.append(("废纸篓", trash))

    caches = collect_dir(str(HOME / "Library/Caches"))
    if caches:
        targets.append(("~/Library/Caches", caches))

    tmp_items = collect_tmp()
    if tmp_items:
        targets.append(("/tmp (过期文件)", tmp_items))

    # uv/pip caches (safe)
    for cname in ["uv", "pip"]:
        cpath = str(HOME / ".cache" / cname)
        citems = collect_dir(cpath)
        if citems:
            targets.append((f"~/.cache/{cname}", citems))

    # Medium
    if level in ("medium", "aggressive"):
        for cname in ["whisper", "huggingface"]:
            cpath = str(HOME / ".cache" / cname)
            citems = collect_dir(cpath)
            if citems:
                targets.append((f"~/.cache/{cname} (模型)", citems))

        # 旧日志 (>7天)
        log_dir = HOME / "Library/Logs"
        old_logs: list[tuple[str, int]] = []
        now = time.time()
        try:
            for entry in os.listdir(str(log_dir)):
                epath = os.path.join(str(log_dir), entry)
                if (now - os.path.getmtime(epath)) / 86400 > 7:
                    size = du_total(epath)
                    if size > 0:
                        old_logs.append((epath, size))
        except PermissionError:
            pass
        if old_logs:
            targets.append(("~/Library/Logs (>=7天)", old_logs))

        # npm 错误日志 (>7天)
        npm_logs = collect_npm_logs()
        if npm_logs:
            targets.append(("~/.npm/_logs (>=7天)", npm_logs))

    # Aggressive
    if level == "aggressive":
        docker_data = HOME / "Library/Containers/com.docker.docker/Data"
        if docker_data.exists():
            docker_items = collect_dir(str(docker_data))
            if docker_items:
                targets.append(("Docker 镜像数据", docker_items))
        xcode_derived = HOME / "Library/Developer/Xcode/DerivedData"
        if xcode_derived.exists():
            xcode_items = collect_dir(str(xcode_derived))
            if xcode_items:
                targets.append(("Xcode DerivedData", xcode_items))
        sim_devices = HOME / "Library/Developer/CoreSimulator/Devices"
        if sim_devices.exists():
            sim_items = collect_dir(str(sim_devices))
            if sim_items:
                targets.append(("CoreSimulator 设备", sim_items))

    grand_total = sum(sum(s for _, s in items) for _, items in targets)

    print(f"\n{BOLD}清理等级: {YELLOW}{level}{RESET}")
    print(f"可回收空间: {RED if grand_total > 10*1024**3 else GREEN}{fmt_size(grand_total)}{RESET}\n")

    if grand_total == 0:
        print("  没有可清理的内容。")
        return

    for desc, items in targets:
        t = sum(s for _, s in items)
        print(f"  {desc}: {color_size(t)}")

    if dry_run:
        print(f"\n{GREEN}--dry-run 模式，未实际删除。{RESET}")
        return

    print()
    resp = input(f"  确认删除以上内容? [y/N] ")
    if resp.lower() != "y":
        print("  已取消。")
        return

    from taotie.log import log_write
    log_lines = [f"等级: {level}"]
    total_deleted = 0
    for desc, items in targets:
        deleted = delete_items(items, desc)
        if deleted:
            t = sum(s for _, s in deleted)
            total_deleted += t
            log_lines.append(f"  {desc}: {fmt_size(t)}")
    log_write("CLEAN", f"清理完成，回收 {fmt_size(total_deleted)}", "\n".join(log_lines))

    print(f"\n{BOLD}{GREEN}总计回收: {fmt_size(total_deleted)}{RESET}\n")
```

- [ ] **Step 2: 更新 `taotie.py`** - 删除 collect_dir, collect_tmp, delete_items, cmd_clean

- [ ] **Step 3: 运行测试**

```bash
python -m pytest tests/test_taotie.py -v
```

预期: PASS

- [ ] **Step 4: Commit**

```bash
git add taotie/clean.py taotie.py
git commit -m "refactor: extract clean.py, add npm error log cleanup (>=7 days, medium level)"
```

---

### Task 6: 重写 `taotie.py` 为纯路由

**Files:**
- Modify: `taotie/taotie.py`

**步骤:**

- [ ] **Step 1: 重写 `taotie.py`**

```python
#!/usr/bin/env python3
"""taotie CLI 入口。"""
from __future__ import annotations

import argparse

from taotie.scan import cmd_scan
from taotie.clean import cmd_clean
from taotie.log import cmd_log


def main() -> None:
    parser = argparse.ArgumentParser(description="taotie — 吞磁盘垃圾的饕餮")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("scan", help="诊断磁盘占用")

    clean_p = sub.add_parser("clean", help="清理磁盘垃圾")
    clean_p.add_argument("--level", choices=["safe", "medium", "aggressive"],
                         default="safe", help="安全等级 (默认: safe)")
    clean_p.add_argument("--dry-run", action="store_true",
                         help="只显示计划，不执行")

    log_p = sub.add_parser("log", help="查看操作记录")
    log_p.add_argument("-n", type=int, default=30, help="显示最近 n 条 (默认: 30)")

    args = parser.parse_args()

    if args.cmd == "scan":
        cmd_scan()
    elif args.cmd == "clean":
        cmd_clean(args.level, args.dry_run)
    elif args.cmd == "log":
        cmd_log(args.n)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 运行测试**

```bash
python -m pytest tests/test_taotie.py -v
python taotie.py scan --help
python taotie.py clean --help
python taotie.py log --help
```

预期: 所有测试 PASS，help 输出正常

- [ ] **Step 3: Commit**

```bash
git add taotie/taotie.py
git commit -m "refactor: reduce taotie.py to pure CLI routing, no business logic"
```

---

### Task 7: 添加新测试 (TestShared, TestClean, TestNpmCache)

**Files:**
- Modify: `tests/test_taotie.py`
- Test: `tests/test_taotie.py`

**步骤:**

- [ ] **Step 1: 添加 TestShared 测试**

```python
class TestShared:
    """测试 _shared 工具函数。"""

    def test_fmt_size_bytes(self):
        assert shared.fmt_size(500) == "500.0B"
        assert shared.fmt_size(1024) == "1.0K"
        assert shared.fmt_size(1024 * 1024) == "1.0M"
        assert shared.fmt_size(1024**3) == "1.0G"
        assert shared.fmt_size(0) == "0.0B"

    def test_color_size_no_ansi_for_small(self):
        s = shared.color_size(500 * 1024**2)  # 500M
        assert "\033" not in s  # 不带颜色

    def test_color_size_yellow_for_1gb(self):
        s = shared.color_size(1 * 1024**3)
        assert "\033[33m" in s  # YELLOW

    def test_color_size_red_for_10gb(self):
        s = shared.color_size(10 * 1024**3)
        assert "\033[31m" in s  # RED

    def test_run_returns_list(self):
        result = shared.run("echo -e 'a\nb'")
        assert isinstance(result, list)
        assert "a" in result

    def test_run_invalid_command_returns_empty(self):
        result = shared.run("nonexistent_command_xyz")
        assert result == []
```

- [ ] **Step 2: 添加 TestNpmCache 测试**

```python
class TestNpmCache:
    """测试 npm cache 分类为 medium。"""

    def test_npm_cache_is_medium(self, fake_home, monkeypatch):
        """~/.cache/npm 归类为 medium."""
        monkeypatch.setattr(taotie._cache, "HOME", fake_home)
        cache_mod._reset_path_cache()
        assert cache_mod.classify(str(fake_home / ".cache" / "npm"), "") == "medium"
```

- [ ] **Step 3: 添加 TestClean 测试**

```python
class TestClean:
    """测试 clean 模块函数。"""

    def test_collect_dir_empty_for_nonexistent(self):
        result = clean_mod.collect_dir("/nonexistent/path/xyz")
        assert result == []

    def test_delete_items_returns_deleted_paths(self, tmp_path, monkeypatch):
        f = tmp_path / "testfile"
        f.write_text("x")
        items = [(str(f), f.stat().st_size)]
        deleted = clean_mod.delete_items(items, "test")
        assert len(deleted) == 1
        assert not f.exists()  # 文件已删除
```

- [ ] **Step 4: 运行所有测试**

```bash
python -m pytest tests/test_taotie.py -v
```

预期: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_taotie.py
git commit -m "test: add TestShared, TestNpmCache, TestClean tests"
```

---

### Task 8: 最终集成验证

**步骤:**

- [ ] **Step 1: 运行完整测试套件**

```bash
python -m pytest tests/test_taotie.py -v
```

- [ ] **Step 2: 验证 CLI 正常工作**

```bash
python taotie.py scan --help
python taotie.py clean --help
python taotie.py log --help
```

- [ ] **Step 3: 验证模块导入无循环依赖**

```bash
python -c "from taotie import cmd_scan, cmd_clean, cmd_log; print('OK')"
```

- [ ] **Step 4: Commit 所有剩余改动**

```bash
git status
git add -A
git commit -m "chore: complete refactor to multi-module structure"
```

---

## 自检清单

| 检查项 | 状态 |
|--------|------|
| Task 1: _shared.py 抽出并测试通过 | ☐ |
| Task 2: _cache.py 抽出并测试通过 | ☐ |
| Task 3: scan.py 抽出并测试通过 | ☐ |
| Task 4: log.py 抽出并测试通过 | ☐ |
| Task 5: clean.py + npm cache 并测试通过 | ☐ |
| Task 6: taotie.py 纯路由并测试通过 | ☐ |
| Task 7: 新测试通过 | ☐ |
| Task 8: 集成验证通过 | ☐ |
| 所有函数有类型注解 | ☐ |
| 无循环导入 | ☐ |
| 原始 taotie.py 删除（git rm old file） | ☐ |
