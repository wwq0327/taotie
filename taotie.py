#!/usr/bin/env python3
"""taotie — 吞磁盘垃圾的饕餮。诊断 + 清理 macOS 磁盘空间。"""

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HOME = Path.home()

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
    # 如果是文件，直接返回大小
    if os.path.isfile(path) or os.path.islink(path):
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


def scan_dir(title, path, depth=1, top_n=5):
    if not os.path.exists(str(path)):
        return
    total = du_total(path)
    if total == 0:
        return
    print_header(f"{title}  ({fmt_size(total)})")
    items = du_sort(path, depth, top_n)
    for p, size in items:
        if size > 0:
            print_item(p, size)


def cmd_scan():
    scan_overview()

    scan_dir("废纸篓", HOME / ".Trash", depth=2)
    scan_dir("/tmp", "/tmp", depth=1, top_n=10)
    scan_dir("~/Library/Caches", HOME / "Library/Caches")
    scan_dir("~/Library/Logs", HOME / "Library/Logs")
    scan_dir("~/Library/Application Support", HOME / "Library/Application Support", depth=1)
    scan_dir("~/Library/Containers", HOME / "Library/Containers", depth=1)
    scan_dir("~/Library/Group Containers", HOME / "Library/Group Containers", depth=1)
    scan_dir("~/.cache", HOME / ".cache")
    scan_dir("~/Movies", HOME / "Movies")

    scan_dir("/opt", "/opt")
    scan_dir("/Library (系统)", "/Library", depth=1)
    scan_dir("/private/var", "/private/var", depth=1)
    scan_dir("/System/Volumes/Data/System", "/System/Volumes/Data/System", depth=1)

    print()


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
    for p, size in items:
        try:
            if os.path.isdir(p) and not os.path.islink(p):
                shutil.rmtree(p, ignore_errors=True)
            else:
                os.unlink(p)
            deleted += size
        except Exception:
            pass
    print(f"    {GREEN}已清理 {fmt_size(deleted)}{RESET}")


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

    for desc, items in targets:
        delete_items(items, desc)

    print(f"\n{BOLD}{GREEN}总计回收: {fmt_size(grand_total)}{RESET}\n")


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

    args = parser.parse_args()

    if args.cmd == "scan":
        cmd_scan()
    elif args.cmd == "clean":
        cmd_clean(args.level, args.dry_run)


if __name__ == "__main__":
    main()
