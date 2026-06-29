"""
WebSocket 集成测试。

测试: 连接 → ping/pong → 文字聊天 → REST API。
需要先启动后端: python -m uvicorn backend.main:app --host 127.0.0.1 --port 8765
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncio
import json
import httpx
import websockets


async def main():
    print("=" * 50)
    print("Integration Test")
    print("=" * 50)

    async with websockets.connect("ws://127.0.0.1:8765/ws") as ws:
        # Welcome message
        welcome = json.loads(await ws.recv())
        assert welcome["type"] == "state.change"
        print(f"[OK] Welcome: state={welcome['payload']['state']}")

        # Ping/pong
        await ws.send(json.dumps({"type": "ping", "id": "t1", "timestamp": 0, "payload": {}}))
        pong = json.loads(await ws.recv())
        assert pong["type"] == "pong"
        print("[OK] Ping/pong")

        # Text chat
        await ws.send(json.dumps({
            "type": "chat.text", "id": "t2", "timestamp": 0,
            "payload": {"text": "Hello test"}
        }))
        resp = json.loads(await ws.recv())
        assert resp["type"] == "llm.stream"
        print(f"[OK] Chat response: '{resp['payload']['text'][:40]}'")

        # Interrupt
        await ws.send(json.dumps({"type": "user.interrupt", "id": "t3", "timestamp": 0, "payload": {}}))
        print("[OK] Interrupt sent")

    # REST API
    async with httpx.AsyncClient() as client:
        health = (await client.get("http://127.0.0.1:8765/health")).json()
        assert health["status"] == "ok"
        print(f"[OK] Health: state={health['state']}")

        tools = (await client.get("http://127.0.0.1:8765/api/tools")).json()
        print(f"[OK] Tools: {len(tools['tools'])} tools")

        state = (await client.get("http://127.0.0.1:8765/api/state")).json()
        print(f"[OK] State: {state['state']}")

    print("\n=== All integration tests passed ===")


if __name__ == "__main__":
    asyncio.run(main())
