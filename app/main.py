"""FastAPI app: serves static web UI and WebSocket voice pipeline."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.pipeline import Pipeline

ROOT_DIR = Path(__file__).resolve().parents[1]
STATIC_DIR = ROOT_DIR / "static"

app = FastAPI(title="TinyVoice")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("tinyvoice.main")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.websocket("/ws")
async def voice_ws(websocket: WebSocket) -> None:
    await websocket.accept()
    logger.info("WebSocket accepted from client")
    settings = get_settings()

    async def send_json(payload: dict[str, Any]) -> None:
        await websocket.send_json(payload)

    async def send_binary(payload: bytes) -> None:
        await websocket.send_bytes(payload)

    pipeline = Pipeline(
        send_json=send_json,
        send_binary=send_binary,
        soniox_api_key=settings.soniox_api_key,
        soniox_ws_url=settings.soniox_ws_url,
        llm_base_url=settings.llm_base_url,
        llm_api_key=settings.llm_api_key,
        llm_model=settings.llm_model,
        dashscope_api_key=settings.dashscope_api_key,
        tts_voice_id=settings.tts_voice_id,
        tts_model=settings.tts_model,
        tts_ws_url=settings.tts_ws_url,
    )

    await send_json(
        {
            "type": "session_info",
            "llm_model": settings.llm_model,
            "tts_model": settings.tts_model,
            "tts_voice": settings.tts_voice_id,
            "asr_configured": settings.asr_configured(),
            "llm_configured": settings.llm_configured(),
            "tts_configured": settings.tts_configured(),
            "soniox_ws_url": settings.soniox_ws_url,
            "tts_ws_url": settings.tts_ws_url,
            "llm_base_url": settings.llm_base_url,
        }
    )

    if not settings.asr_configured():
        logger.warning("ASR not configured: SONIOX_API_KEY missing")
        await send_json({"type": "error", "message": "Missing SONIOX_API_KEY"})
    if not settings.llm_configured():
        logger.warning("LLM not configured: one or more LLM_* vars missing")
        await send_json(
            {"type": "error", "message": "Missing LLM_BASE_URL / LLM_API_KEY / LLM_MODEL"}
        )
    if not settings.tts_configured():
        logger.warning("TTS not configured: DASHSCOPE_API_KEY or TTS_VOICE_ID missing")
        await send_json(
            {"type": "error", "message": "Missing DASHSCOPE_API_KEY or TTS_VOICE_ID"}
        )

    try:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                logger.info("WebSocket disconnect message received")
                break
            if message.get("bytes") is not None:
                await pipeline.feed_audio(message["bytes"])
                continue

            text_data = message.get("text")
            if not text_data:
                continue

            try:
                payload = json.loads(text_data)
            except json.JSONDecodeError:
                await send_json({"type": "error", "message": "Invalid JSON message"})
                continue

            msg_type = payload.get("type")
            if msg_type == "start_session":
                logger.info("Received control message: start_session")
                await pipeline.start_session()
            elif msg_type == "stop_session":
                logger.info("Received control message: stop_session")
                await pipeline.stop_session()
            elif msg_type == "interrupt":
                logger.info("Received control message: interrupt")
                await pipeline.interrupt()
            else:
                logger.warning("Received unknown control message type: %s", msg_type)
                await send_json({"type": "error", "message": f"Unknown message type: {msg_type}"})
    except WebSocketDisconnect:
        logger.info("WebSocketDisconnect exception")
        await pipeline.stop_session()
    except RuntimeError as exc:
        # Starlette may raise this after disconnect if receive() is called again.
        logger.info("WebSocket closed runtime: %s", exc)
        await pipeline.stop_session()
    except Exception:
        logger.exception("Unhandled exception in WebSocket handler")
        await pipeline.stop_session()
    finally:
        logger.info("WebSocket handler finished")
