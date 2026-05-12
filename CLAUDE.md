# taotie

## 目标
诊断 + 清理 macOS 磁盘空间。扫描大户、按安全等级清理临时文件和缓存。

## 技术栈
- Python（标准库，零外部依赖）

## 启动方式
```bash
python taotie.py scan              # 诊断磁盘占用
python taotie.py clean --dry-run   # 预览可清理项
python taotie.py clean             # 安全清理（需确认）
python taotie.py clean --level medium --dry-run
```
