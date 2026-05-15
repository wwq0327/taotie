"""Scan command — disk diagnostics."""

from concurrent.futures import ThreadPoolExecutor, as_completed
import os

from tqdm import tqdm

import json

from taotie._shared import (
    fmt_size, color_size, run, du_sort, du_total,
    print_header, get_home, print_summary,
    RED, YELLOW, GREEN, CYAN, BOLD, RESET,
)
from taotie._cache import classify, _table
from taotie._shared import log_write


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
        display = p.replace(str(get_home()), "~")
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


def cmd_scan(json_output=False):
    scan_overview()

    scans = [
        ("废纸篓", get_home() / ".Trash", 2, 10),
        ("/tmp", "/tmp", 1, 10),
        ("~/Library/Caches", get_home() / "Library/Caches", 1, 5),
        ("~/Library/Logs", get_home() / "Library/Logs", 1, 5),
        ("~/Library/Application Support", get_home() / "Library/Application Support", 1, 5),
        ("~/Library/Containers", get_home() / "Library/Containers", 1, 5),
        ("~/Library/Group Containers", get_home() / "Library/Group Containers", 1, 5),
        ("~/.cache", get_home() / ".cache", 1, 5),
        ("~/Movies", get_home() / "Movies", 1, 5),
        ("/opt", "/opt", 1, 5),
        ("/Library (系统)", "/Library", 1, 5),
        ("/private/var", "/private/var", 1, 5),
        ("/System/Volumes/Data/System", "/System/Volumes/Data/System", 1, 5),
    ]

    # 并行收集数据
    results = {}
    with ThreadPoolExecutor(max_workers=12) as ex:
        futures = {ex.submit(_collect_items, t, p, d, n): t for t, p, d, n in scans}
        pbar = tqdm(total=len(scans), desc="扫描中", unit="项",
                    bar_format="{l_bar}{bar}| {n}/{total}")
        for f in as_completed(futures):
            title, items, total = f.result()
            results[title] = (items, total)
            pbar.update(1)
            pbar.set_postfix_str(f"{title} {fmt_size(total)}")
        pbar.close()

    # 按原始顺序打印详细表格
    print()
    all_items = []
    for title, _, _, _ in scans:
        items, total = results.get(title, ([], 0))
        _print_dir_table(title, items, total)
        all_items.extend(items)

    # ── 汇总 ──
    level_labels = [("safe", "safe 级可清理"), ("medium", "medium 级可清理"), ("manual", "需手动判断")]

    # 收集每个等级的项目（按大小降序）
    lv_groups = {}
    for lv, label in level_labels:
        items = [(d, s) for d, s, l in all_items if l == lv]
        items.sort(key=lambda x: x[1], reverse=True)
        lv_groups[lv] = items

    grand_total = sum(sum(s for _, s in items) for items in lv_groups.values())

    if grand_total == 0:
        if not json_output:
            print_header("汇总")
            print("  无数据\n")
        log_write("SCAN", "磁盘诊断", f"总计 {fmt_size(grand_total)}")
        return

    # 构建输出结构
    output = {
        "total": fmt_size(grand_total),
        "total_bytes": grand_total,
        "levels": {
            lv: {"bytes": sum(s for _, s in lv_groups[lv]), "label": label}
            for lv, label in level_labels
        },
        "items_by_level": {
            lv: [{"path": d, "bytes": s} for d, s in items]
            for lv, items in lv_groups.items()
        },
    }

    if json_output:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print_summary(output)

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


__all__ = ['cmd_scan', 'scan_overview', '_collect_items', '_print_dir_table']