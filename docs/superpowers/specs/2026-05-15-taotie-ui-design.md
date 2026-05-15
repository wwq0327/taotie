# taotie UI 改进设计文档

> **方案组合**: C + E + I + G
> - **C**: Terminal UI — 进度条 + 底部命令条 + q 退出
> - **E**: JSON 输出模式 — `taotie scan --json`
> - **I**: tqdm 进度条 — 替换手写原地刷新
> - **G**: 清理前后对比 — clean 执行后报告回收量 + 节省百分比

**目标**: 零破坏性改动，向后兼容，不影响现有输出行为。

---

## 架构

### 文件变更

| 文件 | 变更 |
|------|------|
| `taotie/scan.py` | C+E+I: 新增 `--json` flag，tqdm 进度条 |
| `taotie/clean.py` | G: 清理前后对比；H: `--quiet` + macOS 通知 |
| `taotie/taotie.py` | 透传 `--json`（scan）、`--quiet`（clean）参数 |
| `pyproject.toml` | 新增 `tqdm` 依赖 |

### 依赖变更

```toml
# pyproject.toml
dependencies = [
    "tqdm",
]
```

---

## C: Terminal UI + I: tqdm 进度条

### 改动点

**`scan.py`** 的 `cmd_scan()` 函数：

1. **tqdm 进度条**（替代手写 `▓░` 多行堆叠）：
   ```python
   from tqdm import tqdm
   # ...
   with ThreadPoolExecutor(max_workers=12) as ex:
       futures = {ex.submit(_collect_items, t, p, d, n): t for t, p, d, n in scans}
       pbar = tqdm(total=len(scans), desc="扫描中", unit="项",
                   bar_format="{l_bar}{bar}| {n}/{total} [{elapsed}]")
       for f in as_completed(futures):
           title, items, total = f.result()
           results[title] = (items, total)
           pbar.update(1)
           pbar.set_postfix_str(f"{title} {fmt_size(total)}")
       pbar.close()
   ```

2. **底部命令条**（scan 结束后打印）：
   ```
   ───────────────────────────────────────────────
     scan · clean · log · help   q 退出
   ```

3. **扫描状态指示**（tqdm postfix）：
   - `✓` 前缀表示已完成
   - `◐` 表示扫描中

### 向后兼容

- 不加 `--json` 时：行为与现在完全一致（只是进度条更好看）
- tqdm 自动检测 TTY，非 TTY（重定向/管道）时不输出进度条

---

## E: JSON 输出模式

### 改动点

**`taotie/taotie.py`** — `scan` 子命令新增 `--json` flag：

```python
sub.add_parser("scan", help="诊断磁盘占用")
# 原来这样就够了，现在要加参数支持
```

实际通过在 `cmd_scan` 里加 `args` 参数实现：

```python
# taotie/taotie.py 的 scan 分支改为：
if args.cmd == "scan":
    from taotie.scan import cmd_scan
    cmd_scan(json=args.json if hasattr(args, 'json') else False)
```

**`scan.py`** — `cmd_scan(json=False)`：

```python
def cmd_scan(json=False):
    # ... 收集逻辑不变 ...
    # 汇总部分：
    output = {
        "total": fmt_size(grand_total),
        "total_bytes": grand_total,
        "levels": {
            "safe":    {"bytes": ..., "label": "safe 级可清理"},
            "medium":  {"bytes": ..., "label": "medium 级可清理"},
            "manual":  {"bytes": ..., "label": "需手动判断"},
        },
        "items_by_level": {
            "safe":    [{"path": d, "bytes": s} for d, s, l in all_items if l == "safe"],
            "medium":  [...],
            "manual":  [...],
        },
    }
    if json:
        import json as _json
        print(_json.dumps(output, ensure_ascii=False, indent=2))
    else:
        # 现有打印逻辑
        _print_summary(output)
```

### JSON 格式

```json
{
  "total": "46.1G",
  "total_bytes": 49521000000,
  "levels": {
    "safe":   {"bytes": 2254000000, "label": "safe 级可清理"},
    "medium": {"bytes": 6220000000, "label": "medium 级可清理"},
    "manual": {"bytes": 41090000000, "label": "需手动判断"}
  },
  "items_by_level": {
    "safe": [{"path": "~/.cache/uv", "bytes": 800000000}, ...]
  }
}
```

---

## G: 清理前后对比

### 改动点

**`clean.py`** 的 `cmd_clean(level, dry_run, quiet=False)`：

```python
def cmd_clean(level, dry_run, quiet=False):
    # ── 清理前：记录磁盘总量 ──
    disk_before = du_total(get_home())

    # ... 现有逻辑不变 ...

    # ── 清理后：报告对比 ──
    if not dry_run:
        disk_after = du_total(get_home())
        recovered = disk_before - disk_after
        pct = (recovered / disk_before * 100) if disk_before > 0 else 0

        if quiet:
            _send_notification(f"taotie 清理完成", f"回收 {fmt_size(recovered)}（节省 {pct:.1f}%）")
        else:
            print(f"""
{BOLD}{GREEN}━━━ 清理完成 ━━━{RESET}
  回收空间: {GREEN}{fmt_size(recovered)}{RESET}
  节省比例: {GREEN}{pct:.1f}%{RESET}
  清理前:  {color_size(disk_before)}
  清理后:  {color_size(disk_after)}
""")
```

### macOS 通知（H 的 `--quiet` 模式）

```python
import subprocess

def _send_notification(title, body):
    script = f'display notification "{body}" with title "{title}"'
    subprocess.run(["osascript", "-e", script], capture_output=True)
```

### `--quiet` flag

**`taotie/taotie.py`**：
```python
clean_p.add_argument("--quiet", action="store_true",
                     help="静默模式，完成后发系统通知")
```

透传给 `cmd_clean(args.level, args.dry_run, args.quiet)`。

---

## 汇总函数抽离

`_print_summary()` 新增到 `_shared.py`（C 和 E 共用）：

```python
def print_summary(output: dict):
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
    # 底部命令条
    print(f"\n  {DIM}scan · clean · log · help   q 退出{RESET}")
```

---

## 测试

| 测试 | 内容 |
|------|------|
| `test_scan_json_output` | `cmd_scan(json=True)` 输出有效 JSON |
| `test_clean_quiet_flag` | `--quiet` 不打印到 stdout |
| `test_clean_before_after` | `du_total` 前后差值正确 |

---

## 实现顺序

1. **I** — 先加 tqdm 依赖，改 `scan.py` 的进度条（无感改动）
2. **E** — 加 `--json` flag 和 `cmd_scan(json=)` 参数
3. **C** — 加底部命令条、汇总函数抽离
4. **G+H** — `clean.py` 加清理前后对比 + `--quiet` + 通知
5. **测试** — 3 个新测试
