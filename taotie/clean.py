"""Clean command — safe/medium/aggressive disk cleanup."""
import os
import shutil
import time

from taotie._shared import (
    fmt_size, color_size, du_total, get_home, log_write,
    GREEN, YELLOW, RED, BOLD, RESET,
)


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
    trash = collect_dir(str(get_home() / ".Trash"))
    if trash:
        targets.append(("废纸篓", trash))

    caches = collect_dir(str(get_home() / "Library/Caches"))
    if caches:
        targets.append(("~/Library/Caches", caches))

    tmp_items = collect_tmp()
    if tmp_items:
        targets.append(("/tmp (过期文件)", tmp_items))

    # uv/pip caches
    for cname in ["uv", "pip"]:
        cpath = get_home() / ".cache" / cname
        citems = collect_dir(str(cpath))
        if citems:
            targets.append((f"~/.cache/{cname}", citems))

    # Medium
    if level in ("medium", "aggressive"):
        for cname in ["whisper", "huggingface"]:
            cpath = get_home() / ".cache" / cname
            citems = collect_dir(str(cpath))
            if citems:
                targets.append((f"~/.cache/{cname} (模型)", citems))

        # 旧日志 (>7天)
        log_dir = get_home() / "Library/Logs"
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

        # npm error logs (>7天)
        npm_logs = get_home() / ".npm" / "_logs"
        if npm_logs.exists():
            old_npm_logs = []
            now = time.time()
            for entry in os.listdir(str(npm_logs)):
                epath = os.path.join(str(npm_logs), entry)
                if (now - os.path.getmtime(epath)) / 86400 > 7:
                    size = du_total(epath)
                    if size > 0:
                        old_npm_logs.append((epath, size))
            if old_npm_logs:
                targets.append(("~/.npm/_logs (>=7天)", old_npm_logs))

    # Aggressive
    if level == "aggressive":
        # Docker 镜像和缓存
        docker_data = get_home() / "Library/Containers/com.docker.docker/Data"
        if docker_data.exists():
            docker_items = collect_dir(str(docker_data))
            if docker_items:
                targets.append(("Docker 镜像数据", docker_items))
        # Xcode DerivedData (包含编译缓存)
        xcode_derived = get_home() / "Library/Developer/Xcode/DerivedData"
        if xcode_derived.exists():
            xcode_items = collect_dir(str(xcode_derived))
            if xcode_items:
                targets.append(("Xcode DerivedData", xcode_items))
        # CoreSimulator 设备缓存
        sim_devices = get_home() / "Library/Developer/CoreSimulator/Devices"
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