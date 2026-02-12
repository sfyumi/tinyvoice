"""FastAPI app: serves static web UI and WebSocket voice pipeline with agent capabilities."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.memory import SoulManager
from app.pipeline import Pipeline
from app.skills import SkillManager
from app.tools import create_default_registry

ROOT_DIR = Path(__file__).resolve().parents[1]
STATIC_DIR = ROOT_DIR / "static"

app = FastAPI(title="TinyAgent")
app.mount("/static", StaticFiles(directory=STATIC_DIR, html=False), name="static")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("tinyagent.main")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.websocket("/ws")
async def voice_ws(websocket: WebSocket) -> None:
    await websocket.accept()
    logger.info("WebSocket accepted from client")
    settings = get_settings()

    # Each connection gets its own SkillManager (copy state from global)
    skill_dirs = [ROOT_DIR / d for d in settings.get_skills_dirs()]
    conn_skills = SkillManager(skill_dirs=skill_dirs)
    conn_skills.discover()

    # Soul manager for this connection
    soul_mgr = SoulManager(soul_dir=ROOT_DIR / "soul")
    soul_mgr.load()

    # Create tool registry for this connection
    tool_registry = create_default_registry(
        skill_manager=conn_skills,
        soul_manager=soul_mgr,
        enabled_tools=settings.get_enabled_tools(),
        allow_shell=settings.tools_allow_shell,
        python_exec_enabled=settings.python_exec_enabled,
        browser_enabled=settings.browser_enabled,
        google_project=settings.google_project,
        google_location=settings.google_location,
        google_credentials_path=settings.google_credentials_path,
        web_search_gemini_model=settings.web_search_gemini_model,
        web_search_synthesis_temperature=settings.web_search_synthesis_temperature,
        web_search_synthesis_max_tokens=settings.web_search_synthesis_max_tokens,
    )

    pipeline = Pipeline(
        send_json=websocket.send_json,
        send_binary=websocket.send_bytes,
        soniox_api_key=settings.soniox_api_key,
        soniox_ws_url=settings.soniox_ws_url,
        llm_base_url=settings.llm_base_url,
        llm_api_key=settings.llm_api_key,
        llm_model=settings.llm_model,
        dashscope_api_key=settings.dashscope_api_key,
        tts_voice_id=settings.tts_voice_id,
        tts_model=settings.tts_model,
        tts_ws_url=settings.tts_ws_url,
        skill_manager=conn_skills,
        tool_registry=tool_registry,
        soul_manager=soul_mgr,
        max_tool_rounds=settings.agent_max_tool_rounds,
        ui_tool_result_max_chars=settings.ui_tool_result_max_chars,
    )

    await websocket.send_json(
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
            "tools": tool_registry.tool_names,
            "skills": conn_skills.to_info_dict(),
            "soul": soul_mgr.to_info_dict(),
        }
    )

    if not settings.asr_configured():
        logger.warning("ASR not configured: SONIOX_API_KEY missing")
        await websocket.send_json({"type": "error", "message": "Missing SONIOX_API_KEY"})
    if not settings.llm_configured():
        logger.warning("LLM not configured: one or more LLM_* vars missing")
        await websocket.send_json(
            {"type": "error", "message": "Missing LLM_BASE_URL / LLM_API_KEY / LLM_MODEL"}
        )
    if not settings.tts_configured():
        logger.warning("TTS not configured: DASHSCOPE_API_KEY or TTS_VOICE_ID missing")
        await websocket.send_json(
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
                await websocket.send_json({"type": "error", "message": "Invalid JSON message"})
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
            elif msg_type in {"activate_skill", "deactivate_skill"}:
                skill_name = payload.get("name", "")
                logger.info("Received control message: %s %s", msg_type, skill_name)
                if msg_type == "activate_skill":
                    await pipeline.activate_skill(skill_name)
                else:
                    await pipeline.deactivate_skill(skill_name)
            else:
                logger.warning("Received unknown control message type: %s", msg_type)
                await websocket.send_json({"type": "error", "message": f"Unknown message type: {msg_type}"})
    except WebSocketDisconnect:
        logger.info("WebSocketDisconnect exception")
        await pipeline.stop_session()
    except RuntimeError as exc:
        logger.info("WebSocket closed runtime: %s", exc)
        await pipeline.stop_session()
    except Exception:
        logger.exception("Unhandled exception in WebSocket handler")
        await pipeline.stop_session()
    finally:
        logger.info("WebSocket handler finished")
