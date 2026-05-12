# taotie

[饕餮](https://baike.baidu.com/item/%E9%A5%95%E9%A4%AE) — 吞磁盘垃圾的神兽。macOS 磁盘诊断 + 清理工具。

## 安装

```bash
git clone https://github.com/wwq0327/taotie.git
```

Python 标准库，零依赖。

## 用法

### 诊断

```bash
python taotie.py scan
```

扫描用户目录和系统目录的磁盘占用，红色标记 >10G 的大户，黄色标记 >1G 的项目。

### 清理

```bash
python taotie.py clean --dry-run          # 预览 safe 级
python taotie.py clean                     # 执行 safe 清理
python taotie.py clean --level medium --dry-run
```

三个安全等级：

| 等级 | 范围 |
|------|------|
| `safe` | 废纸篓、`~/Library/Caches`、`/tmp` 过期文件（>1天）、`~/.cache/uv`、`~/.cache/pip` |
| `medium` | safe + Whisper/HuggingFace 模型缓存 + 旧日志（>7天） |
| `aggressive` | 同 medium（更大范围需手动词） |

清理前需输入 `y` 确认。`--dry-run` 只预览不执行。
