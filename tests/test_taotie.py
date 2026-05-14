"""taotie TDD tests."""
import os
import re
import sys
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, call

sys.path.insert(0, str(Path(__file__).parent.parent))
import taotie

# 预编译正则 (修复后模块级常量)
_STRIP_ANSI_RE = re.compile(r"\033\[[0-9;]*m")


@pytest.fixture
def fake_home(tmp_path):
    """创建临时 HOME 结构."""
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
    return home


class TestClassify:
    """测试 classify 分类功能."""

    def test_uv_cache_is_safe(self, fake_home, monkeypatch):
        """~/.cache/uv 归类为 safe."""
        monkeypatch.setattr(taotie, "HOME", fake_home)
        assert taotie.classify(str(fake_home / ".cache" / "uv"), "") == "safe"

    def test_pip_cache_is_safe(self, fake_home, monkeypatch):
        """~/.cache/pip 归类为 safe."""
        monkeypatch.setattr(taotie, "HOME", fake_home)
        assert taotie.classify(str(fake_home / ".cache" / "pip"), "") == "safe"

    def test_whisper_cache_is_medium(self, fake_home, monkeypatch):
        """~/.cache/whisper 归类为 medium."""
        monkeypatch.setattr(taotie, "HOME", fake_home)
        assert taotie.classify(str(fake_home / ".cache" / "whisper"), "") == "medium"

    def test_huggingface_cache_is_medium(self, fake_home, monkeypatch):
        """~/.cache/huggingface 归类为 medium."""
        monkeypatch.setattr(taotie, "HOME", fake_home)
        assert taotie.classify(str(fake_home / ".cache" / "huggingface"), "") == "medium"

    def test_generic_cache_is_medium(self, fake_home, monkeypatch):
        """~/.cache/other 归类为 medium (非 uv/pip)."""
        monkeypatch.setattr(taotie, "HOME", fake_home)
        assert taotie.classify(str(fake_home / ".cache" / "other"), "") == "medium"


class TestAggressiveLevel:
    """测试 aggressive 级别有别于 medium 的清理目标.

    Bug: aggressive 和 medium 代码完全相同,没有额外目标.
    """

    def test_aggressive_calls_collect_for_docker_medium_does_not(self, fake_home, monkeypatch):
        """aggressive 级别应调用 collect_dir(Docker路径), medium 不应."""
        monkeypatch.setattr(taotie, "HOME", fake_home)

        # aggressive 清理 ~/Library/Containers/com.docker.docker/Data
        docker_path = str(fake_home / "Library/Containers/com.docker.docker/Data")
        Path(docker_path).mkdir(parents=True)

        original_collect_dir = taotie.collect_dir
        collect_calls = []

        def tracking_collect_dir(path):
            collect_calls.append(str(path))
            return original_collect_dir(path)

        monkeypatch.setattr(taotie, "collect_dir", tracking_collect_dir)
        monkeypatch.setattr(taotie, "collect_tmp", lambda: [])

        # medium 级别
        collect_calls.clear()
        with patch.object(sys, "stdout", MagicMock()):
            with patch("builtins.input", lambda _: "y"):
                taotie.cmd_clean("medium", dry_run=False)
        docker_called_in_medium = docker_path in collect_calls
        assert not docker_called_in_medium, \
            f"medium 不应扫描 Docker 目录, 但调用了: {[c for c in collect_calls if 'docker' in c]}"

        # aggressive 级别
        collect_calls.clear()
        with patch.object(sys, "stdout", MagicMock()):
            with patch("builtins.input", lambda _: "y"):
                taotie.cmd_clean("aggressive", dry_run=False)
        docker_called_in_aggressive = docker_path in collect_calls
        assert docker_called_in_aggressive, \
            f"aggressive 应扫描 Docker 目录, 但调用的路径为: {[c for c in collect_calls if 'docker' in c or 'Containers' in c]}"


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
