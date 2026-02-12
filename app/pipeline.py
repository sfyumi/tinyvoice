"""Session orchestrator: ASR -> Agent (LLM+Tools) -> TTS with state machine and interruption."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from app.agent import AgentEvent, AgentLoop
from app.asr import SonioxASRClient
from app.llm import LLMClient
from app.memory import SoulManager
from app.skills import SkillManager
from app.tools import ToolRegistry
from app.tts import TTSClient

StateType = str
logger = logging.getLogger("tinyagent.pipeline")


class Pipeline:
    """Orchestrates per-connection real-time voice dialog with agent capabilities."""

    def __init__(
        self,
        *,
        send_json: Callable[[dict[str, Any]], Awaitable[None]],
        send_binary: Callable[[bytes], Awaitable[None]],
        soniox_api_key: str,
        soniox_ws_url: str,
        llm_base_url: str,
        llm_api_key: str,
        llm_model: str,
        dashscope_api_key: str,
        tts_voice_id: str,
        tts_model: str,
        tts_ws_url: str,
        skill_manager: SkillManager,
        tool_registry: ToolRegistry,
        soul_manager: SoulManager,
        max_tool_rounds: int = 5,
    ) -> None:
        self._send_json = send_json
        self._send_binary = send_binary
        self._asr = SonioxASRClient(
            api_key=soniox_api_key,
            ws_url=soniox_ws_url,
            language_hints=["zh", "en"],
        )
        self._llm = LLMClient(base_url=llm_base_url, api_key=llm_api_key, model=llm_model)
        self._tts = TTSClient(
            api_key=dashscope_api_key,
            model=tts_model,
            voice_id=tts_voice_id,
            ws_url=tts_ws_url,
        )
        self._skills = skill_manager
        self._tools = tool_registry
        self._soul = soul_manager
        self._agent = AgentLoop(
            llm=self._llm,
            tools=self._tools,
            skills=self._skills,
            soul=self._soul,
            max_rounds=max_tool_rounds,
        )
        self._completed_turns: int = 0
        self._audio_queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._state: StateType = "idle"
        self._running = False
        self._session_task: asyncio.Task[None] | None = None
        self._audio_forward_task: asyncio.Task[None] | None = None
        self._transcript_task: asyncio.Task[None] | None = None
        self._turn_task: asyncio.Task[None] | None = None
        self._last_endpoint_sentence: str = ""
        self._last_endpoint_at: float = 0.0
        self._current_turn_id: str | None = None
        self._listening_started_at: float = 0.0
        self._cancel_event: asyncio.Event = asyncio.Event()

    async def _set_state(self, state: StateType) -> None:
        self._state = state
        if state == "listening":
            self._listening_started_at = time.monotonic()
        logger.info("Pipeline state -> %s", state)
        await self._send_json({"type": "state", "state": state})

    async def _send_connection_status(
        self, service: str, status: str, detail: str | None = None
    ) -> None:
        payload: dict[str, Any] = {
            "type": "connection_status",
            "service": service,
            "status": status,
        }
        if detail:
            payload["detail"] = detail
        await self._send_json(payload)

    async def start_session(self) -> None:
        if self._session_task and not self._session_task.done():
            logger.info("start_session ignored: session already running")
            return
        logger.info("Starting pipeline session")
        self._running = True
        self._cancel_event.clear()
        self._session_task = asyncio.create_task(self._session_loop())

    async def stop_session(self) -> None:
        logger.info("Stopping pipeline session")
        self._running = False
        self._cancel_event.set()
        await self._tts.cancel()

        # Generate session memory summary if there were completed turns
        if self._completed_turns > 0:
            await self._save_session_memory()

        await self._send_connection_status("asr", "disconnected")
        await self._send_connection_status("tts", "idle")
        await self._send_connection_status("llm", "disconnected")
        await self._audio_queue.put(None)
        if self._turn_task and not self._turn_task.done():
            self._turn_task.cancel()
        if self._session_task and not self._session_task.done():
            self._session_task.cancel()
            try:
                await self._session_task
            except asyncio.CancelledError:
                pass

    async def _save_session_memory(self) -> None:
        """Generate a summary of this session and append to MEMORY.md."""
        try:
            # Get conversation history from LLM client
            history = self._llm._history
            if not history:
                return

            # Build a simple summary from the conversation
            user_messages = [m["content"] for m in history if m.get("role") == "user" and m.get("content")]
            assistant_messages = [m["content"] for m in history if m.get("role") == "assistant" and m.get("content")]

            if not user_messages:
                return

            # Create a concise summary
            topics = "; ".join(msg[:80] for msg in user_messages[:5])
            summary = f"对话 ({self._completed_turns} 轮): 用户问了 {topics}"
            if assistant_messages:
                last_reply = assistant_messages[-1][:100]
                summary += f"。最后的回复涉及: {last_reply}"

            self._soul.append_memory(summary)
            logger.info("Session memory saved (%d turns)", self._completed_turns)
        except Exception:
            logger.exception("Failed to save session memory")

    async def interrupt(self) -> None:
        logger.info("Interrupt requested (state=%s)", self._state)
        if self._state in ("speaking", "executing") and self._turn_task and not self._turn_task.done():
            self._cancel_event.set()
            await self._tts.cancel()
            self._turn_task.cancel()
        if self._running:
            await self._set_state("listening")

    async def feed_audio(self, chunk: bytes) -> None:
        if self._running:
            await self._audio_queue.put(chunk)

    async def activate_skill(self, name: str) -> bool:
        """Activate a skill and broadcast the update."""
        ok = self._skills.activate(name)
        if ok:
            await self._send_json({
                "type": "skill",
                "event": "activated",
                "name": name,
                "skills": self._skills.to_info_dict(),
            })
        return ok

    async def deactivate_skill(self, name: str) -> bool:
        """Deactivate a skill and broadcast the update."""
        ok = self._skills.deactivate(name)
        if ok:
            await self._send_json({
                "type": "skill",
                "event": "deactivated",
                "name": name,
                "skills": self._skills.to_info_dict(),
            })
        return ok

    async def _session_loop(self) -> None:
        logger.info("Session loop started")
        await self._set_state("listening")

        # Broadcast available skills at session start
        await self._send_json({
            "type": "skills_list",
            "skills": self._skills.to_info_dict(),
        })

        try:
            await self._asr.connect()
            logger.info("ASR connected")
            await self._send_connection_status("asr", "connected")
            await self._send_connection_status("tts", "idle")
            await self._send_connection_status("llm", "connected")
        except Exception as exc:
            logger.exception("ASR connect failed")
            await self._send_connection_status(
                "asr", "error", f"{type(exc).__name__}: {exc}"
            )
            await self._send_json(
                {
                    "type": "error",
                    "message": f"ASR connection failed: {type(exc).__name__}: {exc}",
                }
            )
            await self._set_state("idle")
            return

        async def forward_audio_to_asr() -> None:
            while self._running:
                chunk = await self._audio_queue.get()
                if chunk is None:
                    break
                self._asr.send_audio(chunk)
            self._asr.end_audio()

        async def forward_asr_text() -> None:
            while self._running:
                item = await self._asr.get_transcript()
                if item:
                    text, is_final = item
                    if is_final:
                        logger.info("ASR final transcript: %s", text[:100])
                    await self._send_json({"type": "asr", "text": text, "is_final": is_final})
                await asyncio.sleep(0.03)

        self._audio_forward_task = asyncio.create_task(forward_audio_to_asr())
        self._transcript_task = asyncio.create_task(forward_asr_text())

        try:
            while self._running:
                sentence = await self._asr.wait_sentence(timeout=1.0)
                if not sentence:
                    continue
                sentence = sentence.strip()
                if not sentence:
                    continue
                now = time.monotonic()
                if (
                    sentence == self._last_endpoint_sentence
                    and (now - self._last_endpoint_at) < 2.5
                ):
                    logger.info("Ignore duplicated endpoint sentence: %s", sentence[:160])
                    continue
                self._last_endpoint_sentence = sentence
                self._last_endpoint_at = now
                turn_id = uuid.uuid4().hex[:12]
                self._current_turn_id = turn_id
                logger.info("ASR endpoint sentence [turn_id=%s]: %s", turn_id, sentence[:160])
                await self._send_json(
                    {
                        "type": "turn",
                        "event": "user_committed",
                        "turn_id": turn_id,
                        "text": sentence,
                    }
                )
                self._cancel_event.clear()
                self._turn_task = asyncio.create_task(self._run_turn(turn_id, sentence))
                try:
                    await self._turn_task
                except asyncio.CancelledError:
                    await self._set_state("listening")
                finally:
                    self._turn_task = None
                    self._current_turn_id = None
        except asyncio.CancelledError:
            logger.info("Session loop cancelled")
            pass
        except Exception:
            logger.exception("Session loop crashed")
        finally:
            self._running = False
            await self._send_connection_status("asr", "disconnected")
            await self._send_connection_status("tts", "disconnected")
            await self._send_connection_status("llm", "disconnected")
            for task in [self._audio_forward_task, self._transcript_task]:
                if task and not task.done():
                    task.cancel()
            for task in [self._audio_forward_task, self._transcript_task]:
                if task:
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
            await self._asr.close()
            await self._set_state("idle")
            logger.info("Session loop finished")

    async def _run_turn(self, turn_id: str, user_text: str) -> None:
        logger.info("Turn start [turn_id=%s], user_text=%s", turn_id, user_text[:160])
        turn_started_at = time.monotonic()
        listening_started_at = self._listening_started_at or turn_started_at

        await self._set_state("thinking")
        llm_first_token_at: float | None = None
        llm_last_token_at: float | None = None
        tts_first_audio_at: float | None = None
        llm_token_count = 0
        tool_calls_count = 0

        # Agent event callback: forward events to WebSocket
        async def on_agent_event(event: AgentEvent) -> None:
            nonlocal tool_calls_count
            if event.type == "tool_start":
                tool_calls_count += 1
                await self._set_state("executing")
                await self._send_json({
                    "type": "tool",
                    "event": "start",
                    "turn_id": turn_id,
                    "name": event.data.get("name", ""),
                    "arguments": event.data.get("arguments", {}),
                })
            elif event.type == "tool_result":
                await self._send_json({
                    "type": "tool",
                    "event": "result",
                    "turn_id": turn_id,
                    "name": event.data.get("name", ""),
                    "content": event.data.get("content", ""),
                    "is_error": event.data.get("is_error", False),
                    "elapsed_ms": event.data.get("elapsed_ms", 0),
                })
                # Back to thinking after tool result (may loop again)
                await self._set_state("thinking")
            elif event.type == "skill_changed":
                await self._send_json({
                    "type": "skill",
                    "event": event.data.get("action", "changed"),
                    "name": event.data.get("skill_name", ""),
                    "skills": event.data.get("skills", []),
                })
            elif event.type == "thinking":
                await self._set_state("thinking")

        # Run the agent loop -- yields text tokens for TTS
        async def agent_text_stream() -> AsyncIterator[str]:
            nonlocal llm_first_token_at, llm_last_token_at, llm_token_count
            try:
                async for token in self._agent.run_turn(
                    user_text,
                    on_event=on_agent_event,
                    cancel_event=self._cancel_event,
                ):
                    llm_token_count += 1
                    now = time.monotonic()
                    if llm_first_token_at is None:
                        llm_first_token_at = now
                    llm_last_token_at = now
                    elapsed_ms = int((now - llm_first_token_at) * 1000)
                    await self._send_json(
                        {
                            "type": "llm",
                            "turn_id": turn_id,
                            "text": token,
                            "done": False,
                            "token_index": llm_token_count,
                            "elapsed_ms": elapsed_ms,
                        }
                    )
                    yield token
                logger.info(
                    "Agent stream finished [turn_id=%s], tokens=%s, tool_calls=%s",
                    turn_id, llm_token_count, tool_calls_count,
                )
                await self._send_json(
                    {
                        "type": "llm",
                        "turn_id": turn_id,
                        "text": "",
                        "done": True,
                        "token_index": llm_token_count,
                        "elapsed_ms": (
                            int((llm_last_token_at - llm_first_token_at) * 1000)
                            if llm_first_token_at and llm_last_token_at
                            else 0
                        ),
                    }
                )
            except Exception as exc:
                logger.exception("Agent stream failed [turn_id=%s]", turn_id)
                await self._send_connection_status("llm", "error", f"{type(exc).__name__}: {exc}")
                await self._send_json(
                    {
                        "type": "error",
                        "turn_id": turn_id,
                        "message": f"Agent failed: {type(exc).__name__}: {exc}",
                    }
                )
                raise

        await self._set_state("speaking")
        audio_chunks = 0
        audio_bytes = 0
        try:
            await self._send_connection_status("tts", "connected")
            async for pcm in self._tts.stream_speech(agent_text_stream()):
                audio_chunks += 1
                audio_bytes += len(pcm)
                if tts_first_audio_at is None:
                    tts_first_audio_at = time.monotonic()
                await self._send_binary(pcm)
            logger.info("TTS stream finished [turn_id=%s], audio_chunks=%s", turn_id, audio_chunks)
            await self._send_connection_status("tts", "idle")
        finally:
            turn_finished_at = time.monotonic()
            llm_elapsed_ms = 0
            if llm_first_token_at and llm_last_token_at:
                llm_elapsed_ms = int((llm_last_token_at - llm_first_token_at) * 1000)

            listening_duration_ms = int(max(0.0, turn_started_at - listening_started_at) * 1000)
            thinking_ms = (
                int(max(0.0, llm_first_token_at - turn_started_at) * 1000)
                if llm_first_token_at
                else None
            )
            llm_first_token_ms = (
                int(max(0.0, llm_first_token_at - turn_started_at) * 1000)
                if llm_first_token_at
                else None
            )
            tts_first_audio_ms = (
                int(max(0.0, tts_first_audio_at - llm_first_token_at) * 1000)
                if tts_first_audio_at and llm_first_token_at
                else None
            )
            e2e_latency_ms = (
                int(max(0.0, tts_first_audio_at - turn_started_at) * 1000)
                if tts_first_audio_at
                else None
            )
            speaking_ms = int(
                max(0.0, turn_finished_at - (llm_first_token_at or turn_started_at)) * 1000
            )
            tts_est_duration_ms = int((audio_bytes / 2 / 24000) * 1000)
            llm_tok_per_sec = (
                round(llm_token_count / max(llm_elapsed_ms / 1000, 0.001), 2)
                if llm_elapsed_ms > 0
                else 0.0
            )

            await self._send_json(
                {
                    "type": "metrics",
                    "turn_id": turn_id,
                    "listening_duration_ms": listening_duration_ms,
                    "thinking_ms": thinking_ms,
                    "speaking_ms": speaking_ms,
                    "llm_first_token_ms": llm_first_token_ms,
                    "tts_first_audio_ms": tts_first_audio_ms,
                    "e2e_latency_ms": e2e_latency_ms,
                    "llm_tokens": llm_token_count,
                    "llm_tok_per_sec": llm_tok_per_sec,
                    "tts_audio_chunks": audio_chunks,
                    "tts_est_duration_ms": tts_est_duration_ms,
                    "turn_total_ms": int(max(0.0, turn_finished_at - turn_started_at) * 1000),
                    "tool_calls": tool_calls_count,
                }
            )
            await self._send_json({"type": "turn", "event": "finished", "turn_id": turn_id})
            self._completed_turns += 1
        if self._running:
            await self._set_state("listening")
