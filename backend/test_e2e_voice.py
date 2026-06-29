"""
端到端语音流水线测试。

逐帧发送 512-sample 音频帧 → VAD 检测 → ASR → TTS → 验证。
"""

import asyncio
import json
import sys
import base64
import numpy as np
sys.path.insert(0, "D:/program/project")

import websockets
from backend.vad.silero_adapter import SileroVAD


async def main():
    print("=" * 50)
    print("E2E Voice Pipeline Test")
    print("=" * 50)

    test_wav = "D:/program/project/resources/test_audio/test_zh_hello.wav"
    print(f"Test audio: {test_wav}")

    audio = SileroVAD.load_wav(test_wav)
    audio_int16 = (audio * 32767).clip(-32768, 32767).astype(np.int16)
    print(f"Total audio: {len(audio_int16)} samples ({len(audio_int16)/16000:.2f}s)")

    async with websockets.connect("ws://127.0.0.1:8765/ws") as ws:
        welcome = json.loads(await ws.recv())
        print(f"[OK] Connected: state={welcome['payload']['state']}")

        received = []

        async def recv_loop():
            try:
                while True:
                    msg = json.loads(await ws.recv())
                    received.append(msg)
                    t = msg["type"]
                    p = msg.get("payload", {})
                    if t == "state.change":
                        print(f"  <- STATE: {p.get('state')}")
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

        # Send audio frame by frame (512 samples each)
        frame_size = 512
        n_frames = 0
        print(f"\nSending {len(audio_int16)//frame_size} frames...")

        for i in range(0, len(audio_int16) - frame_size + 1, frame_size):
            frame = audio_int16[i:i + frame_size]
            audio_b64 = base64.b64encode(frame.tobytes()).decode("ascii")

            await ws.send(json.dumps({
                "type": "audio.chunk",
                "id": f"f{n_frames}",
                "timestamp": 0,
                "payload": {"data": audio_b64, "format": "pcm", "sampleRate": 16000},
            }))
            n_frames += 1
            # 模拟实时 — 32ms per frame
            await asyncio.sleep(0.032)

        print(f"Sent {n_frames} frames ({n_frames * frame_size / 16000:.1f}s)")

        # Wait for processing
        print("Waiting for results...")
        for _ in range(30):
            await asyncio.sleep(1)
            tts_count = sum(1 for m in received if m["type"] == "tts.audio")
            if tts_count > 0:
                print("  Got response!")
                break
        else:
            print("  Timed out waiting for response")

        await asyncio.sleep(2)
        recv_task.cancel()
        try:
            await recv_task
        except asyncio.CancelledError:
            pass

        # Results
        print(f"\n{'='*50}")
        print("Results")
        print("=" * 50)

        types_seen = set(m["type"] for m in received)
        print(f"Message types: {types_seen}")

        states = [m["payload"].get("state") for m in received if m["type"] == "state.change"]
        print(f"States: {' -> '.join(states) if states else '(none)'}")

        asr_final = [m for m in received if m["type"] == "asr.result" and m["payload"].get("isFinal")]
        asr_ok = len(asr_final) > 0 and len(asr_final[-1]["payload"]["text"]) > 2
        if asr_final:
            print(f"ASR final: '{asr_final[-1]['payload']['text'][:60]}'")
        print(f"ASR: {'PASS' if asr_ok else 'FAIL'}")

        tts_msgs = [m for m in received if m["type"] == "tts.audio"]
        tts_ok = len(tts_msgs) > 0
        if tts_msgs:
            tts_p = tts_msgs[0]["payload"]
            print(f"TTS: {tts_p.get('durationMs', 0):.0f}ms")
            ph = tts_p.get('phonemes', [])
            print(f"TTS phonemes: {[(p['phoneme'], p['startMs']) for p in ph[:6]]}")
        print(f"TTS: {'PASS' if tts_ok else 'FAIL'}")

        live2d_msgs = [m for m in received if m["type"] == "live2d.control"]
        print(f"Live2D: {len(live2d_msgs)} msgs")

        print(f"\nOverall: {'ALL PASSED' if (asr_ok and tts_ok) else 'SOME FAILED'}")
        print("=" * 50)


asyncio.run(main())
