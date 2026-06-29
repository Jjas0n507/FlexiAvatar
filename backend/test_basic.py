"""Basic feature test script"""
import asyncio
import sys
sys.path.insert(0, "D:/program/project")

from backend.config import config
from backend.session.manager import SessionManager, SessionState
from backend.tools.registry import ToolRegistry

# 1. Test config
config.load()
print("[OK] Config loaded")
print(f"  - Port: {config.get('app.port')}")
print(f"  - LLM Engine: {config.get('llm.engine')}")

# 2. Test state machine
sm = SessionManager()
print(f"[OK] State machine init: {sm.state.value}")


async def test_transitions():
    # IDLE -> LISTENING
    ok = await sm.transition("vad_speech_start", reason="test")
    assert ok
    assert sm.state == SessionState.LISTENING
    print("  [OK] IDLE -> LISTENING")

    # LISTENING -> PROCESSING
    ok = await sm.transition("vad_speech_end", reason="test")
    assert ok
    assert sm.state == SessionState.PROCESSING
    print("  [OK] LISTENING -> PROCESSING")

    # PROCESSING -> SPEAKING
    ok = await sm.transition("processing_done", reason="test")
    assert ok
    assert sm.state == SessionState.SPEAKING
    print("  [OK] PROCESSING -> SPEAKING")

    # SPEAKING -> INTERRUPTED
    ok = await sm.transition("interrupt", reason="test")
    assert ok
    assert sm.state == SessionState.INTERRUPTED
    print("  [OK] SPEAKING -> INTERRUPTED")

    # INTERRUPTED -> LISTENING
    ok = await sm.transition("interrupt_handled", reason="test")
    assert ok
    assert sm.state == SessionState.LISTENING
    print("  [OK] INTERRUPTED -> LISTENING")

    # Reset
    await sm.reset()
    assert sm.state == SessionState.IDLE
    print("  [OK] Reset to IDLE")

    print(f"  History: {len(sm.history)} records")


asyncio.run(test_transitions())

# 3. Test tool registry
registry = ToolRegistry()
count = registry.load_all()
print(f"[OK] Tool registry: {count} tools loaded")
print(f"  Available: {registry.list_tools()}")

# 4. Test schema generation
schemas = registry.get_all_schemas()
print(f"[OK] Schema generation: {len(schemas)} schemas")

print("\n=== All tests passed ===")
