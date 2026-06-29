"""
智能体后端入口。

FastAPI + WebSocket 服务。
负责：
- 启动时加载配置、注册工具、初始化 SessionManager
- WebSocket 连接管理
- 消息路由（根据 type 字段分发到对应处理器）
- 健康检查端点
"""

import asyncio
import json
import logging
import time
import uuid

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from backend.config import config
from backend.session.manager import SessionManager, SessionState
from backend.tools.registry import ToolRegistry
from backend.live2d.motion_controller import MotionController

# ── 日志 ─────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("agent")

# ── 应用初始化 ──────────────────────────────────

app = FastAPI(title="AI Agent Backend", version="0.1.0")

# 加载配置
config.load()

# 初始化核心组件
session_manager = SessionManager()
tool_registry = ToolRegistry()
motion_controller = MotionController()

# 加载工具
tool_count = tool_registry.load_all()
logger.info(f"已加载 {tool_count} 个工具: {tool_registry.list_tools()}")

# ── 状态机监听 ──────────────────────────────────


@session_manager.on_transition
async def log_state_transition(from_state, to_state, event, reason):
    """记录所有状态转换"""
    logger.info(f"状态转换: {from_state.value} → {to_state.value} ({event}) {reason}")


# ── WebSocket 连接管理 ──────────────────────────

connected_clients: dict[str, WebSocket] = {}


async def broadcast(message: dict) -> None:
    """向所有已连接的客户端广播消息"""
    stale = []
    for client_id, ws in connected_clients.items():
        try:
            await ws.send_json(message)
        except Exception:
            stale.append(client_id)
    for cid in stale:
        connected_clients.pop(cid, None)


async def send_to(client_id: str, message: dict) -> bool:
    """向指定客户端发送消息"""
    ws = connected_clients.get(client_id)
    if ws:
        try:
            await ws.send_json(message)
            return True
        except Exception:
            connected_clients.pop(client_id, None)
    return False


async def broadcast_state(state: SessionState, reason: str = "") -> None:
    """广播状态变更消息"""
    await broadcast({
        "type": "state.change",
        "id": str(uuid.uuid4()),
        "timestamp": int(time.time() * 1000),
        "payload": {
            "state": state.value,
            "reason": reason,
        },
    })


# ── 消息处理器 ──────────────────────────────────

async def handle_interrupt(client_id: str, payload: dict) -> None:
    """处理用户打断"""
    logger.info(f"收到打断信号 from {client_id}")
    await session_manager.interrupt(reason="user_interrupt")
    # 等待状态转换完成
    await asyncio.sleep(0.05)


async def handle_chat_text(client_id: str, payload: dict) -> None:
    """处理文本聊天消息（调试/文字输入模式）"""
    text = payload.get("text", "")
    if not text:
        return

    logger.info(f"收到文字消息: {text[:50]}...")

    # 模拟状态流转
    await session_manager.transition("vad_speech_start", reason="text_input")
    await session_manager.transition("vad_speech_end", reason="text_input")

    # 回显（阶段 1 用 echo，阶段 3 替换为 LLM）
    response_text = f"[Echo] 收到: {text}"

    await session_manager.transition("processing_done", reason="echo")

    # 发送回复
    await send_to(client_id, {
        "type": "llm.stream",
        "id": str(uuid.uuid4()),
        "timestamp": int(time.time() * 1000),
        "payload": {
            "text": response_text,
            "isFirstChunk": True,
            "isLastChunk": True,
        },
    })

    await session_manager.transition("speaking_done", reason="echo_complete")


async def handle_ping(client_id: str, payload: dict) -> None:
    """处理 ping"""
    await send_to(client_id, {
        "type": "pong",
        "id": str(uuid.uuid4()),
        "timestamp": int(time.time() * 1000),
        "payload": {},
    })


# 消息处理器映射
MESSAGE_HANDLERS = {
    "user.interrupt": handle_interrupt,
    "chat.text": handle_chat_text,
    "ping": handle_ping,
}


# ── REST 端点 ───────────────────────────────────

@app.get("/health")
async def health_check():
    """健康检查端点"""
    return {
        "status": "ok",
        "state": session_manager.state.value,
        "tools": tool_registry.list_tools(),
        "clients": len(connected_clients),
    }


@app.get("/api/state")
async def get_state():
    """获取当前状态"""
    return {
        "state": session_manager.state.value,
        "history": session_manager.history[-10:],  # 最近 10 条转换
    }


@app.get("/api/tools")
async def get_tools():
    """获取所有已注册工具的信息"""
    tools_info = {}
    for name, tool in tool_registry.get_all().items():
        tools_info[name] = {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters_model().model_json_schema(),
        }
    return {"tools": tools_info}


@app.get("/api/config")
async def get_config():
    """获取当前配置（脱敏）"""
    data = config.to_dict()
    # 移除敏感字段
    for key in ("api_key", "secret"):
        _remove_sensitive(data, key)
    return data


def _remove_sensitive(obj, key_pattern):
    """递归移除敏感字段"""
    if isinstance(obj, dict):
        for k in list(obj.keys()):
            if key_pattern in k.lower():
                obj[k] = "***"
            elif isinstance(obj[k], (dict, list)):
                _remove_sensitive(obj[k], key_pattern)
    elif isinstance(obj, list):
        for item in obj:
            _remove_sensitive(item, key_pattern)


# ── WebSocket 端点 ──────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket 连接端点"""
    await websocket.accept()
    client_id = str(uuid.uuid4())[:8]
    connected_clients[client_id] = websocket
    logger.info(f"客户端连接: {client_id} (总计 {len(connected_clients)})")

    # 发送欢迎消息（含当前状态）
    await websocket.send_json({
        "type": "state.change",
        "id": str(uuid.uuid4()),
        "timestamp": int(time.time() * 1000),
        "payload": {
            "state": session_manager.state.value,
            "tools": tool_registry.list_tools(),
            "reason": "connected",
        },
    })

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({
                    "type": "error",
                    "id": str(uuid.uuid4()),
                    "timestamp": int(time.time() * 1000),
                    "payload": {"code": "INVALID_JSON", "message": "无效的 JSON 格式", "recoverable": True},
                })
                continue

            msg_type = msg.get("type", "")
            payload = msg.get("payload", {})

            if msg_type == "ping":
                await handle_ping(client_id, payload)
                continue

            handler = MESSAGE_HANDLERS.get(msg_type)
            if handler:
                try:
                    await handler(client_id, payload)
                except Exception as e:
                    logger.error(f"处理消息 {msg_type} 失败: {e}", exc_info=True)
                    await websocket.send_json({
                        "type": "error",
                        "id": str(uuid.uuid4()),
                        "timestamp": int(time.time() * 1000),
                        "payload": {"code": "HANDLER_ERROR", "message": str(e), "recoverable": True},
                    })
            else:
                logger.debug(f"未知消息类型: {msg_type}")
                await websocket.send_json({
                    "type": "error",
                    "id": str(uuid.uuid4()),
                    "timestamp": int(time.time() * 1000),
                    "payload": {
                        "code": "UNKNOWN_TYPE",
                        "message": f"未知的消息类型: {msg_type}",
                        "recoverable": True,
                    },
                })

    except WebSocketDisconnect:
        logger.info(f"客户端断开: {client_id}")
    except Exception as e:
        logger.error(f"WebSocket 异常: {e}", exc_info=True)
    finally:
        connected_clients.pop(client_id, None)
        logger.info(f"客户端已清理: {client_id} (剩余 {len(connected_clients)})")


# ── 启动事件 ────────────────────────────────────

@app.on_event("startup")
async def startup():
    logger.info("=" * 50)
    logger.info(f"AI Agent Backend v{config.get('app.version', '0.1.0')}")
    logger.info(f"配置引擎: {config.get('app.name', 'unknown')}")
    logger.info(f"已加载 {tool_count} 个工具")
    logger.info(f"WebSocket 端点: ws://{config.get('app.host', '127.0.0.1')}:{config.get('app.port', 8765)}/ws")
    logger.info("=" * 50)


@app.on_event("shutdown")
async def shutdown():
    logger.info("正在关闭...")
    await session_manager.reset()
    connected_clients.clear()
    logger.info("已关闭")


# ── 直接运行 ────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    host = config.get("app.host", "127.0.0.1")
    port = config.get("app.port", 8765)
    uvicorn.run("backend.main:app", host=host, port=port, reload=False, log_level="info")
