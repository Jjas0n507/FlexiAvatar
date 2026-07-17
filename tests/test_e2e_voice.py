"""
端到端语音流水线测试。

逐帧发送 WAV → WebSocket → VAD → ASR → Echo → TTS → Live2D → 验证。
需要先启动后端: python -m uvicorn backend.main:app --host 127.0.0.1 --port 8765
"""
import asyncio
import json
import base64
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import websockets
TEST_AUDIO_DIR = Path(__file__).parent.parent / "resources" / "test_audio"

from backend.vad.silero_adapter import SileroVAD


async def main():
    print("=" * 50)
    print("E2E Voice Pipeline Test")
    print("=" * 50)

    test_wav = TEST_AUDIO_DIR / "test_zh_hello.wav"
    print(f"Test audio: {test_wav}")

    audio = SileroVAD.load_wav(str(test_wav))
    audio_int16 = (audio * 32767).clip(-32768, 32767).astype(np.int16)
    print(f"Audio: {len(audio_int16)} samples ({len(audio_int16)/16000:.2f}s)")

    async with websockets.connect("ws://127.0.0.1:8765/ws") as ws:
        welcome = json.loads(await ws.recv())
        assert welcome["type"] == "state.change"
        print(f"[OK] Connected: state={welcome['payload']['state']}")

        received = []
        stop_sending = asyncio.Event()   # VAD 定稿进入 processing 后停止送帧，避免尾音触发 barge-in

        async def recv_loop():
            try:
                while True:
                    msg = json.loads(await ws.recv())
                    received.append(msg)
                    t, p = msg["type"], msg.get("payload", {})
                    if t == "state.change":
                        print(f"  <- STATE: {p.get('state')}")
                        if p.get("state") in ("processing", "speaking"):
                            stop_sending.set()
                    elif t == "asr.result":
                        print(f"  <- ASR: '{p.get('text', '')[:50]}' (final={p.get('isFinal')})")
                    elif t == "llm.stream":
                        print(f"  <- LLM: '{p.get('text', '')[:50]}'")
                    elif t == "tts.audio":
                        print(f"  <- TTS: {p.get('durationMs', 0):.0f}ms, {len(p.get('phonemes', []))} phonemes")
                    elif t == "live2d.control":
                        print(f"  <- LIVE2D: {p.get('command')}")
            except websockets.ConnectionClosed:
                pass

        recv_task = asyncio.create_task(recv_loop())

        # 逐帧发送
        frame_size, n_frames = 512, 0
        print(f"\nSending {len(audio_int16)//frame_size} frames...")
        for i in range(0, len(audio_int16) - frame_size + 1, frame_size):
            if stop_sending.is_set():
                print(f"  (VAD 已定稿，提前停止送帧 @ frame {n_frames})")
                break
            frame = audio_int16[i:i + frame_size]
            audio_b64 = base64.b64encode(frame.tobytes()).decode("ascii")
            await ws.send(json.dumps({
                "type": "audio.chunk", "id": f"f{n_frames}", "timestamp": 0,
                "payload": {"data": audio_b64, "format": "pcm", "sampleRate": 16000},
            }))
            n_frames += 1
            await asyncio.sleep(0.032)

        print(f"Sent {n_frames} frames ({n_frames * frame_size / 16000:.1f}s)")

        # 等待结果
        print("Waiting for results...")
        for _ in range(30):
            await asyncio.sleep(1)
            if any(m["type"] == "tts.audio" for m in received):
                print("  Got response!")
                break

        await asyncio.sleep(2)
        recv_task.cancel()
        try:
            await recv_task
        except asyncio.CancelledError:
            pass

        # 验证
        print(f"\n{'='*50}")
        print("Results")
        print("=" * 50)

        types_seen = set(m["type"] for m in received)
        expected_types = {"asr.result", "llm.stream", "tts.audio", "live2d.control"}
        missing = expected_types - types_seen
        if missing:
            print(f"WARNING: Missing message types: {missing}")

        asr_final = [m for m in received if m["type"] == "asr.result" and m["payload"].get("isFinal")]
        tts_msgs = [m for m in received if m["type"] == "tts.audio"]
        live2d = [m for m in received if m["type"] == "live2d.control"]

        asr_ok = len(asr_final) > 0 and len(asr_final[-1]["payload"]["text"]) > 2
        tts_ok = len(tts_msgs) > 0

        print(f"ASR: {'PASS' if asr_ok else 'FAIL'} ({len(asr_final)} final)")
        if asr_final:
            print(f"  Text: '{asr_final[-1]['payload']['text'][:60]}'")
        print(f"TTS: {'PASS' if tts_ok else 'FAIL'} ({len(tts_msgs)} msgs)")
        print(f"Live2D: {len(live2d)} msgs")

        assert asr_ok, "ASR failed"
        assert tts_ok, "TTS failed"
        print("\n=== E2E test PASSED ===")


if __name__ == "__main__":
    asyncio.run(main())
