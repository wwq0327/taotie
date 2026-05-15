#!/usr/bin/env python3
"""taotie — 吞磁盘垃圾的饕餮。诊断 + 清理 macOS 磁盘空间。"""

import argparse

from taotie.scan import cmd_scan
from taotie.clean import cmd_clean
from taotie.log import cmd_log


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
