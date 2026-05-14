"""taotie — 吞磁盘垃圾的饕餮。"""
import sys
from pathlib import Path
import importlib.util

# Load root taotie.py as a separate module to avoid circular imports
_root_path = Path(__file__).parent.parent / "taotie.py"
spec = importlib.util.spec_from_file_location("_taotie_root", str(_root_path))
_root = importlib.util.module_from_spec(spec)
sys.modules['_taotie_root'] = _root
spec.loader.exec_module(_root)

# Copy re-exported items into this module's namespace
for _name in (
    # shared items
    'fmt_size', 'color_size', 'run', 'du_sort', 'du_total',
    'print_header', 'print_item', 'HOME', 'LOG_DIR', 'LOG_FILE',
    'RED', 'YELLOW', 'GREEN', 'CYAN', 'BOLD', 'RESET',
    '_STRIP_ANSI_RE',
    # commands
    'cmd_scan', 'cmd_clean', 'cmd_log',
    # utilities used by tests
    'classify', 'collect_dir', 'collect_tmp', 'delete_items',
    '_reset_path_cache', '_strip_ansi', '_table',
    '_table_sep', '_pad', '_make_cache', '_get_path_cache',
    'scan_overview', '_collect_items', '_print_dir_table',
    'log_write', 'log_show',
    'SAFE_PATHS', 'MEDIUM_PATHS', 'PY_CACHE_DIRS',
):
    globals()[_name] = getattr(_root, _name)

__all__ = ["cmd_scan", "cmd_clean", "cmd_log"]
