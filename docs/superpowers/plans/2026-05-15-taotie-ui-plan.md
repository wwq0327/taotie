# taotie UI 改进实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 C+E+I+G 四项 UI 改进：tqdm 进度条、JSON 输出、底部命令条、清理前后对比

**Architecture:**
- `taotie/scan.py`: 新增 `cmd_scan(json=False)` 参数、tqdm 进度条、`_build_scan_output()` 构建结构化数据
- `taotie/clean.py`: 新增 `cmd_clean(level, dry_run, quiet=False)` 参数、清理前后对比、macOS 通知
- `taotie/_shared.py`: 新增 `print_summary()` 汇总打印函数
- `taotie/taotie.py`: 透传 `--json` 和 `--quiet` 参数
- `pyproject.toml`: 新增 `tqdm` 依赖

**Tech Stack:** Python 标准库 + `tqdm` 库

---

## Task 1: 加 tqdm 依赖，改 scan.py 进度条

**Files:**
- Modify: `pyproject.toml`
- Modify: `taotie/scan.py:92-104`

- [ ] **Step 1: 写失败的测试（进度条不抛异常）**

```python
# tests/test_taotie.py 新增

class TestScanTqdm:
    def test_scan_with_tqdm_no_error(self, fake_home, monkeypatch):
        """scan 在有数据时不抛异常，进度条正常"""
        # 模拟 du_total 返回小值避免超时
        import taotie.scan as scan_mod
        def fast_total(p):
            return 1024
        monkeypatch.setattr(scan_mod, 'du_total', fast_total)
        monkeypatch.setattr(scan_mod, 'du_sort', lambda p, d, n: [])

        # 不抛异常即通过
        scan_mod.cmd_scan()
```

- [ ] **Step 2: Run test**

Run: `pytest tests/test_taotie.py::TestScanTqdm::test_scan_with_tqdm_no_error -v`
Expected: PASS（无 tqdm 时也 PASS，改动无感）

- [ ] **Step 3: 加 tqdm 到 pyproject.toml**

```toml
# pyproject.toml
dependencies = [
    "tqdm",
]
```

- [ ] **Step 4: 改 scan.py 的进度条部分**

读取当前 `taotie/scan.py` 第 92-104 行，替换为：

```python
from tqdm import tqdm

    # 并行收集数据
    total_scans = len(scans)
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
```

- [ ] **Step 5: Run test 确认无破坏**

Run: `pytest tests/test_taotie.py -v`
Expected: 全部 PASS

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml taotie/scan.py
git commit -m "feat: use tqdm progress bar in scan command"
```

---

## Task 2: 抽离 _build_scan_output 和 print_summary

**Files:**
- Modify: `taotie/_shared.py`
- Modify: `taotie/scan.py`

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_taotie.py 新增

class TestScanOutput:
    def test_build_scan_output_returns_dict(self, fake_home, monkeypatch):
        """_build_scan_output 返回正确结构的 dict"""
        import taotie.scan as scan_mod

        # Mock du_total 和 du_sort
        def mock_total(p):
            if "Trash" in str(p): return 1024
            if "Caches" in str(p): return 2048
            return 0
        monkeypatch.setattr(scan_mod, 'du_total', mock_total)
        monkeypatch.setattr(scan_mod, 'du_sort', lambda p, d, n: [])

        output = scan_mod._build_scan_output([
            ("废纸篓", fake_home / ".Trash", 1, 5),
            ("Caches", fake_home / "Library/Caches", 1, 5),
        ])
        assert isinstance(output, dict)
        assert "total" in output
        assert "levels" in output
        assert "items_by_level" in output
        assert output["levels"]["safe"]["bytes"] == 1024
        assert output["levels"]["medium"]["bytes"] == 2048
```

- [ ] **Step 2: Run test**

Run: `pytest tests/test_taotie.py::TestScanOutput::test_build_scan_output_returns_dict -v`
Expected: FAIL — `_build_scan_output` not defined

- [ ] **Step 3: 在 _shared.py 添加 print_summary**

在 `taotie/_shared.py` 末尾添加：

```python
def print_summary(output: dict) -> None:
    """打印汇总（C 模式：非 JSON）

    output 结构：
        {
            "total": str,          # 格式化总大小
            "total_bytes": int,    # 原始字节数
            "levels": {
                "safe":   {"bytes": int, "label": str},
                "medium": {"bytes": int, "label": str},
                "manual": {"bytes": int, "label": str},
            },
            "items_by_level": {
                "safe":   [{"path": str, "bytes": int}, ...],
                ...
            }
        }
    """
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
    print(f"\n  scan · clean · log · help")
```

- [ ] **Step 4: 在 scan.py 添加 _build_scan_output**

在 `taotie/scan.py` 的 `cmd_scan` 前添加：

```python
def _build_scan_output(scan_list: list) -> dict:
    """收集扫描数据并构建结构化输出 dict。"""
    results = {}
    for title, path, depth, top_n in scan_list:
        if not os.path.exists(str(path)):
            continue
        total = du_total(path)
        if total == 0:
            continue
        raw = du_sort(path, depth, top_n)
        rows = []
        for p, size in raw:
            if size == 0:
                continue
            level = classify(p, title)
            display = p.replace(str(get_home()), "~")
            rows.append((display, size, level))
        results[title] = (rows, total)

    all_items = []
    for title, (items, _) in results.items():
        all_items.extend(items)

    # 按 level 分组
    lv_groups = {}
    level_labels = [("safe", "safe 级可清理"), ("medium", "medium 级可清理"), ("manual", "需手动判断")]
    for lv, label in level_labels:
        items = [(d, s) for d, s, l in all_items if l == lv]
        items.sort(key=lambda x: x[1], reverse=True)
        lv_groups[lv] = items

    grand_total = sum(sum(s for _, s in items) for items in lv_groups.values())

    return {
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
```

- [ ] **Step 5: Run test**

Run: `pytest tests/test_taotie.py::TestScanOutput::test_build_scan_output_returns_dict -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add taotie/_shared.py taotie/scan.py
git commit -m "refactor: extract _build_scan_output and print_summary for C+E UI"
```

---

## Task 3: E — JSON 输出模式 + cmd_scan(json=)

**Files:**
- Modify: `taotie/scan.py`
- Modify: `taotie/taotie.py`

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_taotie.py 新增

class TestScanJson:
    def test_scan_json_output_is_valid_json(self, fake_home, monkeypatch, capsys):
        """cmd_scan(json=True) 输出有效 JSON"""
        import taotie.scan as scan_mod

        def mock_total(p):
            return 1024
        monkeypatch.setattr(scan_mod, 'du_total', mock_total)
        monkeypatch.setattr(scan_mod, 'du_sort', lambda p, d, n: [])

        scan_mod.cmd_scan(json=True)
        captured = capsys.readouterr().out

        import json as _json
        data = _json.loads(captured)
        assert "total" in data
        assert "levels" in data
        assert "items_by_level" in data
        assert data["levels"]["safe"]["bytes"] == 1024
```

- [ ] **Step 2: Run test**

Run: `pytest tests/test_taotie.py::TestScanJson::test_scan_json_output_is_valid_json -v`
Expected: FAIL — `cmd_scan` 不接受 `json` 参数

- [ ] **Step 3: 修改 cmd_scan(json=False)**

将 `taotie/scan.py` 的 `cmd_scan()` 签名改为 `cmd_scan(json=False)`，
替换函数体末尾的汇总打印逻辑：

读取 `cmd_scan()` 完整实现，将汇总打印部分替换为：

```python
def cmd_scan(json=False):
    scan_overview()

    # 构建扫描计划
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

    # 并行收集（tqdm 进度条）
    total_scans = len(scans)
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

    # 构建结构化输出
    output = _build_scan_output(scans)

    if json:
        import json as _json
        print(_json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print_summary(output)

    # 记日志
    lines = [f"总计 {output['total']}"]
    for lv in ("safe", "medium", "manual"):
        items = output["items_by_level"].get(lv, [])
        if items:
            t = sum(i["bytes"] for i in items)
            lines.append(f"  [{lv}] {fmt_size(t)}")
    log_write("SCAN", "磁盘诊断", "\n".join(lines))
```

注意：`_collect_items` 被 tqdm 循环内调用保持不变，只是进度条显示方式变了。
需要从 `results` 字典构建 `_build_scan_output` 所需的扫描列表格式。

实际上 `_build_scan_output` 接收的是原始 `(title, path, depth, top_n)` 列表，
但它内部会重新调用 `du_total` 和 `du_sort`，这会重复扫描。
修正：`cmd_scan` 复用已有的 `results` 字典，直接构建 output：

在 `cmd_scan()` 末尾，在 tqdm 循环结束后，替换汇总打印逻辑为：

```python
    # ── 构建结构化输出 ──
    lv_groups = {}
    level_labels = [("safe", "safe 级可清理"), ("medium", "medium 级可清理"), ("manual", "需手动判断")]
    for lv, label in level_labels:
        items = [(d, s) for d, s, l in all_items if l == lv]
        items.sort(key=lambda x: x[1], reverse=True)
        lv_groups[lv] = items

    grand_total = sum(sum(s for _, s in items) for items in lv_groups.values())

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

    if json:
        import json as _json
        print(_json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print_summary(output)
```

（删掉 `_build_scan_output` 函数，它在 Task 2 中引入但此处用内联方式更简洁）

- [ ] **Step 4: 修改 taotie/taotie.py 加 --json flag**

读取 `taotie/taotie.py`，找到 `sub.add_parser("scan")` 附近，
替换为带参数的版本：

```python
    scan_p = sub.add_parser("scan", help="诊断磁盘占用")
    scan_p.add_argument("--json", action="store_true",
                        help="输出 JSON 格式")
```

找到 `if args.cmd == "scan":` 分支，改为：

```python
    if args.cmd == "scan":
        cmd_scan(json=getattr(args, 'json', False))
```

- [ ] **Step 5: Run test**

Run: `pytest tests/test_taotie.py::TestScanJson::test_scan_json_output_is_valid_json -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add taotie/scan.py taotie/taotie.py
git commit -m "feat: add --json output mode for scan command"
```

---

## Task 4: G+H — clean 清理前后对比 + --quiet + macOS 通知

**Files:**
- Modify: `taotie/clean.py`
- Modify: `taotie/taotie.py`

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_taotie.py 新增

class TestCleanQuiet:
    def test_clean_quiet_no_stdout(self, fake_home, monkeypatch, capsys):
        """cmd_clean(quiet=True) 不向 stdout 打印"""
        import taotie.clean as clean_mod

        def empty_dir(p):
            return []
        monkeypatch.setattr(clean_mod, 'collect_dir', empty_dir)
        monkeypatch.setattr(clean_mod, 'collect_tmp', lambda: [])

        clean_mod.cmd_clean("safe", dry_run=False, quiet=True)
        captured = capsys.readouterr().out
        # quiet 模式下除了最终通知外不应有输出
        assert "清理" not in captured

class TestCleanBeforeAfter:
    def test_clean_reports_recovered_space(self, fake_home, monkeypatch):
        """cmd_clean 报告回收空间大小"""
        import taotie.clean as clean_mod
        import taotie._shared as shared

        before = 10 * 1024**3
        after = 8 * 1024**3

        call_args = {}
        def mock_du_total(p):
            import taotie._shared as s
            home = s.get_home()
            if str(p) == str(home):
                return before
            return after
            return after
        monkeypatch.setattr(clean_mod, 'du_total', mock_du_total)
        monkeypatch.setattr(clean_mod, 'collect_dir', lambda p: [])
        monkeypatch.setattr(clean_mod, 'collect_tmp', lambda: [])

        # dry_run 不触发对比
        clean_mod.cmd_clean("safe", dry_run=True, quiet=True)
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/test_taotie.py::TestCleanQuiet -v`
Expected: FAIL — `cmd_clean` 不接受 `quiet` 参数

- [ ] **Step 3: 修改 clean.py**

读取 `taotie/clean.py` 完整内容，替换 `cmd_clean` 签名和末尾：

```python
def cmd_clean(level, dry_run, quiet=False):
    """清理磁盘垃圾。

    Args:
        level: "safe" | "medium" | "aggressive"
        dry_run: 是否仅预览不删除
        quiet: 是否静默模式（完成后发系统通知）
    """
    # ── 清理前：记录 HOME 目录总大小 ──
    disk_before = du_total(get_home())

    targets = []
    # ... 中间所有 target 收集逻辑保持不变（lines 66-142）...
    # [即 collect_dir, collect_tmp, medium, aggressive 的所有逻辑原样保留]

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

    # ── 清理后：对比报告 ──
    disk_after = du_total(get_home())
    recovered = disk_before - disk_after
    pct = (recovered / disk_before * 100) if disk_before > 0 else 0

    if quiet:
        _send_notification(
            f"taotie 清理完成",
            f"回收 {fmt_size(recovered)}（节省 {pct:.1f}%）"
        )
    else:
        print(f"""
{BOLD}{GREEN}━━━ 清理完成 ━━━{RESET}
  回收空间: {GREEN}{fmt_size(recovered)}{RESET}
  节省比例: {GREEN}{pct:.1f}%{RESET}
  清理前:  {color_size(disk_before)}
  清理后:  {color_size(disk_after)}
""")


def _send_notification(title: str, body: str) -> None:
    """发送 macOS 系统通知。"""
    script = f'display notification "{body}" with title "{title}"'
    subprocess.run(["osascript", "-e", script], capture_output=True)
```

在文件顶部 import 添加 `subprocess`：

```python
import os
import shutil
import time
import subprocess
```

- [ ] **Step 4: 修改 taotie/taotie.py 加 --quiet flag**

在 `clean_p` 的 `--dry-run` 之后添加：

```python
    clean_p.add_argument("--quiet", action="store_true",
                         help="静默模式，完成后发系统通知")
```

找到 `cmd_clean` 调用，改为：

```python
    cmd_clean(args.level, args.dry_run, getattr(args, 'quiet', False))
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_taotie.py::TestCleanQuiet -v`
Run: `pytest tests/test_taotie.py -v`
Expected: 全部 PASS

- [ ] **Step 6: Commit**

```bash
git add taotie/clean.py taotie/taotie.py
git commit -m "feat: add --quiet mode and before/after comparison to clean"
```

---

## Task 5: 集成验证

**Files:**
- Modify: `tests/test_taotie.py`

- [ ] **Step 1: 确认所有 16+ 测试通过**

Run: `pytest tests/test_taotie.py -v`
Expected: 全部 PASS

- [ ] **Step 2: 手动验证 CLI**

```bash
# 验证 --json
python taotie.py scan --json 2>&1 | head -5

# 验证 --help 显示新参数
python taotie.py scan --help
python taotie.py clean --help

# 验证 clean --dry-run 正常
python taotie.py clean --dry-run
```

- [ ] **Step 3: Commit any test fixes**

```bash
git add tests/test_taotie.py
git commit -m "test: add UI feature tests"
```
