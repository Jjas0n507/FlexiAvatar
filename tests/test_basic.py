"""基础功能测试 — 配置、状态机、工具注册中心"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncio

from backend.config import config
from backend.session.manager import SessionManager, SessionState
from backend.tools.registry import ToolRegistry


def test_config():
    """测试配置加载"""
    config.load()
    assert config.get("app.port") == 8765
    assert config.get("app.host") == "127.0.0.1"
    print("[OK] Config loaded")
    print(f"     Port: {config.get('app.port')}")
    print(f"     LLM engine: {config.get('llm.engine')}")


def test_state_machine():
    """测试状态机转换"""

    async def _run():
        sm = SessionManager()
        assert sm.state == SessionState.IDLE
        print(f"[OK] State machine init: {sm.state.value}")

        # IDLE → LISTENING
        ok = await sm.transition("vad_speech_start", reason="test")
        assert ok and sm.state == SessionState.LISTENING
        print("  [OK] IDLE → LISTENING")

        # LISTENING → PROCESSING
        ok = await sm.transition("vad_speech_end", reason="test")
        assert ok and sm.state == SessionState.PROCESSING
        print("  [OK] LISTENING → PROCESSING")

        # PROCESSING → SPEAKING
        ok = await sm.transition("processing_done", reason="test")
        assert ok and sm.state == SessionState.SPEAKING
        print("  [OK] PROCESSING → SPEAKING")

        # SPEAKING → INTERRUPTED
        ok = await sm.transition("interrupt", reason="test")
        assert ok and sm.state == SessionState.INTERRUPTED
        print("  [OK] SPEAKING → INTERRUPTED")

        # INTERRUPTED → LISTENING
        ok = await sm.transition("interrupt_handled", reason="test")
        assert ok and sm.state == SessionState.LISTENING
        print("  [OK] INTERRUPTED → LISTENING")

        # 重置
        await sm.reset()
        assert sm.state == SessionState.IDLE
        print("  [OK] Reset to IDLE")

    asyncio.run(_run())


def test_tool_registry():
    """测试工具注册中心"""
    registry = ToolRegistry()
    count = registry.load_all()
    schemas = registry.get_all_schemas()
    print(f"[OK] Tool registry: {count} tools, {len(schemas)} schemas")


if __name__ == "__main__":
    test_config()
    test_state_machine()
    test_tool_registry()
    print("\n=== All basic tests passed ===")
