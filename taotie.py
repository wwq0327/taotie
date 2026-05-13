#!/usr/bin/env python3
"""taotie — 吞磁盘垃圾的饕餮。诊断 + 清理 macOS 磁盘空间。"""

import argparse
import os
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

HOME = Path.home()
LOG_DIR = HOME / ".local/share/taotie"
LOG_FILE = LOG_DIR / "taotie.log"

RED = "\033[31m"
YELLOW = "\033[33m"
GREEN = "\033[32m"
CYAN = "\033[36m"
BOLD = "\033[1m"
RESET = "\033[0m"


def fmt_size(size_bytes):
    for unit in ("B", "K", "M", "G", "T"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f}{unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f}P"


def color_size(size_bytes):
    s = fmt_size(size_bytes)
    if size_bytes >= 10 * 1024**3:
        return f"{RED}{s}{RESET}"
    elif size_bytes >= 1 * 1024**3:
        return f"{YELLOW}{s}{RESET}"
    return s


def run(cmd):
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


def _walk_items(path, depth, current_depth=0):
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


def du_total(path):
    """用 du 获取目录大小；/tmp 等受限目录改用 walk 累加。"""
    size = _du_total_fast(path)
    if size <= 0:
        size = _du_total_walk(path)
    return size


def _du_total_fast(path):
    lines = run(f"du -d1 -k '{path}'")
    if lines:
        try:
            return int(lines[-1].split()[0]) * 1024
        except (ValueError, IndexError):
            pass
    return -1


def _du_total_walk(path):
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


def print_header(text):
    print(f"\n{BOLD}{CYAN}═══ {text} ═══{RESET}")


def print_item(path, size, indent=2):
    display = path.replace(str(HOME), "~")
    print(f"{' ' * indent}{color_size(size):>10}  {display}")


# ── log ───────────────────────────────────────────────


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


# ── scan ──────────────────────────────────────────────


def scan_overview():
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


# 清理等级分类
SAFE_PATHS = {
    str(HOME / ".Trash"),
    str(HOME / "Library/Caches"),
    "/tmp",
    "/private/tmp",
}
MEDIUM_PATHS = {
    str(HOME / ".cache/whisper"),
    str(HOME / ".cache/huggingface"),
    str(HOME / "Library/Logs"),
}
PY_CACHE_DIRS = {"uv", "pip"}  # safe 级里的 ~/.cache/xxx 子目录


def classify(path, parent_title):
    """判断一个扫描条目属于哪个清理等级"""
    p = os.path.normpath(str(path))
    for sp in SAFE_PATHS:
        if p.startswith(os.path.normpath(sp)):
            return "safe"
    for mp in MEDIUM_PATHS:
        if p.startswith(os.path.normpath(mp)):
            return "medium"
    # ~/.cache 下的 uv/pip 归 safe
    cache_dir = str(HOME / ".cache")
    if p.startswith(cache_dir):
        sub = os.path.relpath(p, cache_dir).split("/")[0]
        if sub in PY_CACHE_DIRS:
            return "safe"
        return "medium"
    return "manual"


def _strip_ansi(s):
    import re
    return re.sub(r"\033\[[0-9;]*m", "", s)


def _pad(s, width):
    """按可见宽度填充字符串（忽略 ANSI 码）"""
    visible = _strip_ansi(s)
    return s + " " * (width - len(visible))


def _table(rows, col_widths, headers):
    """画 Unicode 框线表格。rows 是已着色字符串的列表。"""
    def sep(pos):
        if pos == "top":
            return f"  ┌─{'─┬─'.join('─' * w for w in col_widths)}─┐"
        elif pos == "mid":
            return f"  ├─{'─┼─'.join('─' * w for w in col_widths)}─┤"
        else:
            return f"  └─{'─┴─'.join('─' * w for w in col_widths)}─┘"

    lines = [sep("top")]
    hdr = " │ ".join(f"{BOLD}{_pad(h, w)}{RESET}" for h, w in zip(headers, col_widths))
    lines.append(f"  │ {hdr} │")
    lines.append(sep("mid"))
    for cells in rows:
        row = " │ ".join(_pad(c, w) for c, w in zip(cells, col_widths))
        lines.append(f"  │ {row} │")
    lines.append(sep("bot"))
    return "\n".join(lines)


def _collect_items(title, path, depth, top_n):
    """收集扫描数据（只做 du，不打印）。返回 (title, items, total)"""
    if not os.path.exists(str(path)):
        return title, [], 0
    total = du_total(path)
    if total == 0:
        return title, [], 0
    raw = du_sort(path, depth, top_n)
    rows = []
    for p, size in raw:
        if size == 0:
            continue
        level = classify(p, title)
        display = p.replace(str(HOME), "~")
        rows.append((display, size, level))
    return title, rows, total


def _print_dir_table(title, items, total):
    """打印一个目录的框线表格"""
    if not items:
        # 有总大小但无子项列表（如空废纸篓），只打表头
        if total > 0:
            print_header(f"{title}  ({fmt_size(total)})")
        return
    print_header(f"{title}  ({fmt_size(total)})")

    # 计算列宽
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


def cmd_scan():
    scan_overview()

    scans = [
        ("废纸篓", HOME / ".Trash", 2, 10),
        ("/tmp", "/tmp", 1, 10),
        ("~/Library/Caches", HOME / "Library/Caches", 1, 5),
        ("~/Library/Logs", HOME / "Library/Logs", 1, 5),
        ("~/Library/Application Support", HOME / "Library/Application Support", 1, 5),
        ("~/Library/Containers", HOME / "Library/Containers", 1, 5),
        ("~/Library/Group Containers", HOME / "Library/Group Containers", 1, 5),
        ("~/.cache", HOME / ".cache", 1, 5),
        ("~/Movies", HOME / "Movies", 1, 5),
        ("/opt", "/opt", 1, 5),
        ("/Library (系统)", "/Library", 1, 5),
        ("/private/var", "/private/var", 1, 5),
        ("/System/Volumes/Data/System", "/System/Volumes/Data/System", 1, 5),
    ]

    # 并行收集数据
    results = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(_collect_items, t, p, d, n): t for t, p, d, n in scans}
        for f in as_completed(futures):
            title, items, total = f.result()
            results[title] = (items, total)

    # 按原始顺序打印
    all_items = []
    for title, _, _, _ in scans:
        items, total = results.get(title, ([], 0))
        _print_dir_table(title, items, total)
        all_items.extend(items)

    # ── 汇总 ──
    print_header("汇总")
    level_color = {"safe": GREEN, "medium": YELLOW, "manual": RED}
    level_labels = [("safe", "safe 级可清理"), ("medium", "medium 级可清理"), ("manual", "需手动判断")]

    # 收集每个等级的项目（按大小降序）
    lv_groups = {}
    for lv, label in level_labels:
        items = [(d, s) for d, s, l in all_items if l == lv]
        items.sort(key=lambda x: x[1], reverse=True)
        lv_groups[lv] = items

    # 对齐行数
    max_rows = min(max(len(v) for v in lv_groups.values()), 15)
    if max_rows == 0:
        print("  无数据\n")
        return

    # 计算列宽（Path 列统一宽度）
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

        # 表头
        print(f"\n  {lc}{BOLD}{label}{RESET}  ({fmt_size(total)})")
        if not items:
            print("    (无)")
            continue

        # 数据行（按大小降序，补齐到 max_rows）
        table_rows = []
        for i in range(max_rows):
            if i < len(items):
                d, s = items[i]
                table_rows.append([color_size(s), d])
            else:
                table_rows.append(["", ""])

        print(_table(table_rows, col_w, ["Size", "Path"]))

    print(f"\n  {BOLD}总计: {fmt_size(grand_total)}{RESET} (分布: {GREEN}safe{RESET} / {YELLOW}medium{RESET} / {RED}manual{RESET})\n")

    # 记日志
    lines = [f"总计 {fmt_size(grand_total)}"]
    for lv, label in level_labels:
        items = lv_groups[lv]
        if items:
            t = sum(s for _, s in items)
            lines.append(f"  [{lv}] {fmt_size(t)}")
            for d, s in items[:10]:
                lines.append(f"    {fmt_size(s):>8}  {d}")
    log_write("SCAN", "磁盘诊断", "\n".join(lines))


# ── clean ──────────────────────────────────────────────


def collect_dir(dir_path):
    """列出目录下所有条目及其大小"""
    if not os.path.isdir(dir_path):
        return []
    items = []
    try:
        for entry in os.listdir(dir_path):
            epath = os.path.join(dir_path, entry)
            size = du_total(epath)
            if size > 0:
                items.append((epath, size))
    except PermissionError:
        pass
    return items


def collect_tmp():
    """收集 /tmp 中安全可删的文件 (>1天, 非系统)"""
    now = time.time()
    items = []
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


def delete_items(items, desc):
    print(f"\n  清理 {desc}...")
    deleted = 0
    deleted_paths = []
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


def cmd_clean(level, dry_run):
    targets = []

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

    # uv/pip caches
    for cname in ["uv", "pip"]:
        cpath = HOME / ".cache" / cname
        citems = collect_dir(str(cpath))
        if citems:
            targets.append((f"~/.cache/{cname}", citems))

    # Medium
    if level in ("medium", "aggressive"):
        for cname in ["whisper", "huggingface"]:
            cpath = HOME / ".cache" / cname
            citems = collect_dir(str(cpath))
            if citems:
                targets.append((f"~/.cache/{cname} (模型)", citems))

        # 旧日志 (>7天)
        log_dir = HOME / "Library/Logs"
        old_logs = []
        now = time.time()
        for entry in os.listdir(str(log_dir)):
            epath = os.path.join(str(log_dir), entry)
            if (now - os.path.getmtime(epath)) / 86400 > 7:
                size = du_total(epath)
                if size > 0:
                    old_logs.append((epath, size))
        if old_logs:
            targets.append(("~/Library/Logs (>=7天)", old_logs))

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


# ── log ───────────────────────────────────────────────


def cmd_log(n):
    log_show(n)


# ── main ──────────────────────────────────────────────


def main():
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
