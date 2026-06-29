"""Test configuration — 必须在其他导入之前设置 sys.path"""
import sys
from pathlib import Path

# 项目根目录 (tests/ 的父目录)
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 测试资源路径
TEST_AUDIO_DIR = PROJECT_ROOT / "resources" / "test_audio"
