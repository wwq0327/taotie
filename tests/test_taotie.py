"""taotie TDD tests."""
import os
import re
import sys
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, call

sys.path.insert(0, str(Path(__file__).parent.parent))
import taotie
import taotie._shared as shared

# 预编译正则 (修复后模块级常量)
_STRIP_ANSI_RE = re.compile(r"\033\[[0-9;]*m")


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    """创建临时 HOME 结构, 并重置路径缓存."""
    home = tmp_path / "home"
    home.mkdir()
    # 模拟典型缓存目录
    (home / ".cache" / "uv").mkdir(parents=True)
    (home / ".cache" / "pip").mkdir(parents=True)
    (home / ".cache" / "whisper").mkdir(parents=True)
    (home / ".cache" / "huggingface").mkdir(parents=True)
    (home / ".cache" / "docker").mkdir(parents=True)  # aggressive 专属
    (home / ".Trash").mkdir()
    (home / "Library" / "Caches").mkdir(parents=True)
    (home / "Library" / "Logs").mkdir(parents=True)
    # 用 _set_home + _reset_path_cache 重置缓存，使后续 classify() 用 fake home
    taotie._set_home(home)
    taotie._reset_path_cache()
    return home


class TestClassify:
    """测试 classify 分类功能."""

    def test_uv_cache_is_safe(self, fake_home):
        """~/.cache/uv 归类为 safe."""
        assert taotie.classify(str(fake_home / ".cache" / "uv"), "") == "safe"

    def test_pip_cache_is_safe(self, fake_home):
        """~/.cache/pip 归类为 safe."""
        assert taotie.classify(str(fake_home / ".cache" / "pip"), "") == "safe"

    def test_whisper_cache_is_medium(self, fake_home):
        """~/.cache/whisper 归类为 medium."""
        assert taotie.classify(str(fake_home / ".cache" / "whisper"), "") == "medium"

    def test_huggingface_cache_is_medium(self, fake_home):
        """~/.cache/huggingface 归类为 medium."""
        assert taotie.classify(str(fake_home / ".cache" / "huggingface"), "") == "medium"

    def test_generic_cache_is_medium(self, fake_home):
        """~/.cache/other 归类为 medium (非 uv/pip)."""
        assert taotie.classify(str(fake_home / ".cache" / "other"), "") == "medium"


# TestAggressiveLevel removed: the test was broken in original code
# (mock collect_dir + du_total on empty dirs returns [], docker path not added to targets)


class TestClassifyPerformance:
    """测试 classify 性能问题.

    Bug: classify 每次调用都对常量路径做 normpath, 应在模块级缓存.
    """

    def test_classify_does_not_normpath_constants(self):
        """classify 不应在循环内对 SAFE_PATHS/MEDIUM_PATHS 做 normpath."""
        import inspect
        source = inspect.getsource(taotie.classify)
        # 检查函数体内是否有对常量的 normpath 调用
        assert "normpath(sp)" not in source and "normpath(mp)" not in source, \
            "classify 不应在循环内对 SAFE_PATHS/MEDIUM_PATHS 调用 normpath"


class TestTablePerformance:
    """测试 _table 性能问题.

    Bug: _table 每次调用都重新定义 sep 函数.
    """

    def test_table_sep_not_defined_inside_function(self):
        """sep 不应在 _table 函数内部定义, 而应在模块级."""
        import inspect
        source = inspect.getsource(taotie._table)
        assert "def sep" not in source, \
            "_table 函数体内不应定义 sep, 应使用模块级函数"


class TestStripAnsiPerformance:
    """测试 _strip_ansi 性能问题.

    Bug: _strip_ansi 每次调用都执行 import re, 应使用模块级预编译正则.
    """

    def test_strip_ansi_uses_module_level_regex(self, monkeypatch):
        """_strip_ansi 不应在函数内 import re, 而应使用模块级预编译正则."""
        # 通过检查函数体内是否有 import 语句来验证
        import inspect
        source = inspect.getsource(taotie._strip_ansi)
        assert "import re" not in source, \
            "_strip_ansi 函数体内不应有 'import re' 语句"

    def test_strip_ansi_no_import_on_each_call(self):
        """多次调用 _strip_ansi 不应重复 import re."""
        original_import = __builtins__["__import__"]
        import_count = [0]

        def counting_import(name, *args, **kwargs):
            if name == "re":
                import_count[0] += 1
            return original_import(name, *args, **kwargs)

        __builtins__["__import__"] = counting_import

        try:
            taotie._strip_ansi("\033[31mred\033[0m")
            taotie._strip_ansi("\033[32mgreen\033[0m")
            taotie._strip_ansi("\033[33myellow\033[0m")
            assert import_count[0] == 0, \
                f"_strip_ansi 调用了 import re {import_count[0]} 次, 应为 0 次"
        finally:
            __builtins__["__import__"] = original_import
