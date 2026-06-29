"""WebSocket integration test"""
import asyncio
import json
import sys
sys.path.insert(0, "D:/program/project")

import websockets

WS_URL = "ws://127.0.0.1:8765/ws"


async def test():
    print("=== WebSocket Integration Test ===\n")

    async with websockets.connect(WS_URL) as ws:
        # 1. Receive welcome message
        welcome = json.loads(await ws.recv())
        print(f"[OK] Welcome message: type={welcome['type']}")
        print(f"     State: {welcome['payload']['state']}")

        # 2. Send ping
        ping_msg = {"type": "ping", "id": "test-1", "timestamp": 0, "payload": {}}
        await ws.send(json.dumps(ping_msg))
        pong = json.loads(await ws.recv())
        assert pong["type"] == "pong"
        print("[OK] Ping/pong works")

        # 3. Send text chat
        text_msg = {
            "type": "chat.text",
            "id": "test-2",
            "timestamp": 0,
            "payload": {"text": "Hello, test!"},
        }
        await ws.send(json.dumps(text_msg))
        response = json.loads(await ws.recv())
        assert response["type"] == "llm.stream"
        print(f"[OK] Chat response: {response['payload']['text']}")

        # 4. Test interrupt
        interrupt_msg = {"type": "user.interrupt", "id": "test-3", "timestamp": 0, "payload": {}}
        await ws.send(json.dumps(interrupt_msg))
        print("[OK] Interrupt sent (no response expected)")

        # 5. Check health via REST
        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.get("http://127.0.0.1:8765/health")
            data = resp.json()
            assert data["status"] == "ok"
            print(f"[OK] Health check: state={data['state']}")

            resp2 = await client.get("http://127.0.0.1:8765/api/state")
            data2 = resp2.json()
            print(f"[OK] State endpoint: {data2['state']}")

            resp3 = await client.get("http://127.0.0.1:8765/api/tools")
            data3 = resp3.json()
            print(f"[OK] Tools endpoint: {len(data3['tools'])} tools")

    print("\n=== All integration tests passed ===")


asyncio.run(test())
