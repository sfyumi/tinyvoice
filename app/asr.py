"""Soniox real-time ASR WebSocket client. Accumulates final tokens and yields complete sentences on endpoint."""
import asyncio
import json
import logging
from collections.abc import AsyncIterator, Callable
from typing import Any

import websockets
from websockets.exceptions import ConnectionClosed

logger = logging.getLogger("tinyvoice.asr")


def _build_config(api_key: str, language_hints: list[str] | None = None) -> dict:
    if language_hints is None:
        language_hints = ["zh", "en"]
    return {
        "api_key": api_key,
        "model": "stt-rt-v4",
        "language_hints": language_hints,
        "enable_language_identification": False,
        "enable_speaker_diarization": False,
        "enable_endpoint_detection": True,
        "audio_format": "pcm_s16le",
        "sample_rate": 16000,
        "num_channels": 1,
    }


async def run_asr_session(
    api_key: str,
    audio_chunks: AsyncIterator[bytes],
    *,
    on_transcript: Callable[[str, bool], Any] | None = None,
    on_sentence: Callable[[str], Any] | None = None,
    language_hints: list[str] | None = None,
) -> str | None:
    """
    Run a Soniox ASR session: send config, stream audio from audio_chunks, parse responses.

    - on_transcript(text, is_final) is called for real-time display.
    - on_sentence(full_text) is called when the user stops speaking (endpoint or finished).
    Returns the final complete sentence text, or None if session ended without one.
    """
    config = _build_config(api_key, language_hints=language_hints)
    final_tokens: list[dict] = []
    last_sentence: str | None = None

    async def collect_final_text() -> str:
        return "".join(t.get("text", "") for t in final_tokens)

    async with websockets.connect("wss://stt-rt.soniox.com/transcribe-websocket") as ws:
        await ws.send(json.dumps(config))

        async def send_audio() -> None:
            try:
                async for chunk in audio_chunks:
                    if chunk:
                        await ws.send(chunk)
            except Exception:
                pass
            await ws.send("")

        send_task = asyncio.create_task(send_audio())

        try:
            while True:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=300.0)
                except asyncio.TimeoutError:
                    break
                if isinstance(msg, bytes):
                    continue
                res = json.loads(msg)
                if res.get("error_code") is not None:
                    raise RuntimeError(
                        f"ASR error: {res.get('error_code')} - {res.get('error_message', '')}"
                    )
                non_final_text_parts: list[str] = []
                for token in res.get("tokens", []):
                    text = token.get("text") or ""
                    if not text:
                        continue
                    if token.get("is_final"):
                        final_tokens.append(token)
                    else:
                        non_final_text_parts.append(text)
                full_final = "".join(t.get("text", "") for t in final_tokens)
                provisional = "".join(non_final_text_parts)
                if on_transcript:
                    if full_final or provisional:
                        on_transcript(full_final + provisional, not non_final_text_parts)
                if res.get("finished"):
                    last_sentence = await collect_final_text()
                    if last_sentence.strip() and on_sentence:
                        on_sentence(last_sentence.strip())
                    break
        finally:
            send_task.cancel()
            try:
                await send_task
            except asyncio.CancelledError:
                pass

    return last_sentence if (last_sentence and last_sentence.strip()) else None


class SonioxASRClient:
    """
    Wrapper that runs ASR in a background task and exposes:
    - send_audio(bytes) for the pipeline to push PCM chunks
    - async iteration over (transcript_text, is_final) and sentence completion.
    """

    def __init__(
        self,
        api_key: str,
        ws_url: str = "wss://stt-rt.soniox.com/transcribe-websocket",
        language_hints: list[str] | None = None,
    ) -> None:
        self._api_key = api_key
        self._ws_url = ws_url
        self._language_hints = language_hints or ["zh", "en"]
        self._audio_queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._transcript_queue: asyncio.Queue[tuple[str, bool]] = asyncio.Queue()
        self._sentence_queue: asyncio.Queue[str] = asyncio.Queue()
        self._ws: websockets.WebSocketClientProtocol | None = None
        self._recv_task: asyncio.Task | None = None
        self._send_task: asyncio.Task | None = None

    async def _audio_iterator(self) -> AsyncIterator[bytes]:
        while True:
            chunk = await self._audio_queue.get()
            if chunk is None:
                return
            yield chunk

    def send_audio(self, chunk: bytes) -> None:
        self._audio_queue.put_nowait(chunk)

    def end_audio(self) -> None:
        self._audio_queue.put_nowait(None)

    def _on_transcript(self, text: str, is_final: bool) -> None:
        self._transcript_queue.put_nowait((text, is_final))

    def _on_sentence(self, text: str) -> None:
        self._sentence_queue.put_nowait(text)

    async def get_transcript(self) -> tuple[str, bool] | None:
        """Non-blocking get next (text, is_final). Returns None if closed."""
        try:
            return self._transcript_queue.get_nowait()
        except asyncio.QueueEmpty:
            return None

    async def wait_sentence(self, timeout: float | None = None) -> str | None:
        """Wait for next complete sentence (endpoint)."""
        try:
            return await asyncio.wait_for(self._sentence_queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    async def connect(self) -> None:
        config = _build_config(self._api_key, language_hints=self._language_hints)
        logger.info("Connecting Soniox ASR websocket: %s", self._ws_url)
        connect_kwargs = dict(
            open_timeout=10,
            close_timeout=5,
            ping_interval=20,
            ping_timeout=20,
        )
        try:
            self._ws = await asyncio.wait_for(
                websockets.connect(self._ws_url, **connect_kwargs),
                timeout=12,
            )
        except ImportError as exc:
            # Happens when system proxy is SOCKS but python-socks isn't installed.
            logger.warning(
                "ASR connect through proxy failed (%s). Retrying direct connection without proxy.",
                exc,
            )
            self._ws = await asyncio.wait_for(
                websockets.connect(self._ws_url, proxy=None, **connect_kwargs),
                timeout=12,
            )
        logger.info("Soniox ASR websocket connected")
        await self._ws.send(json.dumps(config))
        logger.info("Soniox ASR config sent")

        async def send_audio_task() -> None:
            try:
                while True:
                    chunk = await self._audio_queue.get()
                    if chunk is None:
                        await self._ws.send("")
                        return
                    await self._ws.send(chunk)
            except Exception:
                pass

        self._send_task = asyncio.create_task(send_audio_task())

        async def recv_task() -> None:
            # Tokens for the *current* utterance; cleared after each <end>.
            current_tokens: list[str] = []

            try:
                while self._ws:
                    msg = await self._ws.recv()
                    if isinstance(msg, bytes):
                        continue
                    res = json.loads(msg)

                    if res.get("error_code") is not None:
                        logger.error(
                            "Soniox ASR error: %s - %s",
                            res.get("error_code"),
                            res.get("error_message"),
                        )
                        break

                    got_endpoint = False
                    non_final_parts: list[str] = []

                    for token in res.get("tokens", []):
                        text = token.get("text") or ""
                        if not text:
                            continue
                        if text == "<end>":
                            got_endpoint = True
                            continue
                        if token.get("is_final"):
                            current_tokens.append(text)
                        else:
                            non_final_parts.append(text)

                    # Build display text (final so far + provisional).
                    display = "".join(current_tokens) + "".join(non_final_parts)
                    if display:
                        is_stable = len(non_final_parts) == 0
                        self._on_transcript(display, is_stable)

                    # <end> = Soniox semantic endpoint: user finished an utterance.
                    if got_endpoint:
                        sentence = "".join(current_tokens).strip()
                        if sentence:
                            logger.info("ASR endpoint sentence (%d chars): %s", len(sentence), sentence[:120])
                            self._on_sentence(sentence)
                        # Reset buffer for next utterance.
                        current_tokens.clear()

                    if res.get("finished"):
                        # Session ending; flush any remaining tokens.
                        sentence = "".join(current_tokens).strip()
                        if sentence:
                            logger.info("ASR finished sentence (%d chars): %s", len(sentence), sentence[:120])
                            self._on_sentence(sentence)
                        break

            except ConnectionClosed:
                logger.info("ASR websocket closed")
            except asyncio.CancelledError:
                logger.info("ASR recv task cancelled")
            except Exception:
                logger.exception("ASR recv task crashed")

        self._recv_task = asyncio.create_task(recv_task())

    async def close(self) -> None:
        self.end_audio()
        if self._send_task:
            self._send_task.cancel()
            try:
                await self._send_task
            except asyncio.CancelledError:
                pass
        if self._recv_task:
            self._recv_task.cancel()
            try:
                await self._recv_task
            except asyncio.CancelledError:
                pass
        if self._ws:
            await self._ws.close()
            self._ws = None
