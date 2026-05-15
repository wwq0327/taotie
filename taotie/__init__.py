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

# Re-exported items from root taotie.py
_TAOTIE_NAMES = (
    'fmt_size', 'color_size', 'run', 'du_sort', 'du_total',
    'print_header',
    'RED', 'YELLOW', 'GREEN', 'CYAN', 'BOLD', 'RESET',
    '_STRIP_ANSI_RE',
    'cmd_scan', 'cmd_clean',
    'classify', 'collect_dir', 'collect_tmp', 'delete_items',
    '_reset_path_cache', '_strip_ansi', '_table',
    '_table_sep', '_pad', '_make_cache', '_get_path_cache',
    'scan_overview', '_collect_items', '_print_dir_table',
    'PY_CACHE_DIRS', '_set_home',
)
for _name in _TAOTIE_NAMES:
    globals()[_name] = getattr(_root, _name)

# cmd_log lives in taotie.log (extracted from root taotie.py)
from taotie.log import cmd_log
globals()['cmd_log'] = cmd_log

# Also expose get_home, _set_home, log_write, log_show from _shared
from taotie._shared import get_home, _set_home, log_write
globals()['get_home'] = get_home
globals()['_set_home'] = _set_home
globals()['log_write'] = log_write

__all__ = ["cmd_scan", "cmd_clean", "cmd_log"]
