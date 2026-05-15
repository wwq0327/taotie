"""Log command — view operation history."""

from taotie._shared import log_show, LOG_FILE

def cmd_log(n: int = 30) -> None:
    """显示最近 n 条日志"""
    log_show(n)

__all__ = ['cmd_log']
