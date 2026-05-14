# taotie 重构设计

## 目标

将 641 行单文件拆分为多模块结构，增加类型注解，扩大测试覆盖率。

## 模块划分

```
taotie/
├── __init__.py       # 导出主要 API（scan, clean, log）
├── _shared.py        # 共享工具: fmt_size, color_size, run, HOME, 颜色常量, _STRIP_ANSI_RE
├── _cache.py        # 缓存相关: classify, _strip_ansi, _pad, _table_sep, _table, _path_cache
├── scan.py          # scan 命令: scan_overview, cmd_scan, _collect_items, _print_dir_table
├── clean.py         # clean 命令: SAFE/MEDIUM/AGGRESSIVE_PATHS, collect_dir, collect_tmp,
│                     cmd_clean, delete_items, npm error log 收集
├── log.py           # log 命令: log_write, log_show, cmd_log
└── taotie.py        # 入口: main(), argparse, CLI 路由
```

**设计原则**：
- `_shared.py`：无状态工具函数和常量
- `_cache.py`：分类和展示逻辑
- `scan.py` / `clean.py` / `log.py`：各自命令的业务逻辑
- `taotie.py`：只做路由和 argparse，不含业务逻辑

## 数据结构（TypedDict / dataclass）

```python
# scan 结果条目
@dataclass
class ScanItem:
    path: str
    size: int
    level: Literal["safe", "medium", "manual"]

# clean 目标
@dataclass
class CleanTarget:
    desc: str
    items: list[tuple[str, int]]  # (path, size)

# _collect_items 返回值
@dataclass
class ScanResult:
    title: str
    items: list[ScanItem]
    total: int
```

## 类型注解

所有函数添加完整类型注解。`HOME`、`LOG_DIR` 等常量加 `Final` 标注。

## 测试扩展

覆盖以下模块：

| 测试类 | 覆盖范围 |
|--------|----------|
| `TestClassify` | classify() 5 个场景（已存在） |
| `TestStripAnsiPerformance` | _strip_ansi 性能（已存在） |
| `TestTablePerformance` | _table sep 性能（已存在） |
| `TestClassifyPerformance` | classify 缓存（已存在） |
| `TestAggressiveLevel` | aggressive 区别于 medium（已存在） |
| `TestShared` | fmt_size, color_size, run |
| `TestClean` | collect_dir, collect_tmp, delete_items, npm error log |
| `TestNpmCache` | npm cache 分类为 medium |

## npm Cache（medium 级）

**路径**：`~/.npm/_logs/` 中的错误日志文件（文件名格式 `npm-*.log`）

**规则**：
- `~/.npm` 本身归 medium（包含缓存和日志混合）
- `~/.npm/_logs/npm-*.log` 文件单独清理（>7 天）

**实现**：在 `clean.py` 中，`collect_npm_logs()` 函数收集 `~/.npm/_logs/` 下修改时间 >7 天的 `.log` 文件。

## 实施顺序

1. 创建 `__init__.py`、`_shared.py`（抽出共享代码）
2. 创建 `_cache.py`（抽出 classify 相关）
3. 创建 `scan.py`（抽出 scan 命令）
4. 创建 `log.py`（抽出 log 命令）
5. 创建 `clean.py`（抽出 clean 命令，加入 npm cache）
6. 重写 `taotie.py` 为纯路由
7. 添加新测试
8. 逐模块运行测试，全部通过后 commit
