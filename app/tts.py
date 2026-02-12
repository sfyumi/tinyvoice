"""Qwen TTS Realtime wrapper: stream text in, yield PCM audio chunks. Runs sync DashScope API in a thread."""
import asyncio
import base64
import logging
import threading
from collections.abc import AsyncIterator
from queue import Empty, Queue
from typing import Any

import dashscope
from dashscope.audio.qwen_tts_realtime import (
    AudioFormat,
    QwenTtsRealtime,
    QwenTtsRealtimeCallback,
)

logger = logging.getLogger("tinyvoice.tts")


class _TTSCallback(QwenTtsRealtimeCallback):
    """Puts PCM chunks into a queue; signals when session is finished."""

    def __init__(self, audio_queue: Queue, cancel_event: threading.Event) -> None:
        self._audio_queue: Queue = audio_queue
        self._cancel_event = cancel_event
        self._finished = threading.Event()

    def on_open(self) -> None:
        pass

    def on_close(self, close_status_code: int, close_msg: str) -> None:
        self._audio_queue.put(None)
        self._finished.set()

    def on_event(self, response: dict) -> None:
        try:
            if self._cancel_event.is_set():
                return
            event_type = response.get("type", "")
            if event_type == "response.audio.delta":
                audio_data = base64.b64decode(response["delta"])
                self._audio_queue.put(audio_data)
            elif event_type == "session.finished":
                self._audio_queue.put(None)
                self._finished.set()
        except Exception:
            self._audio_queue.put(None)
            self._finished.set()


def _run_tts_sync(
    api_key: str,
    model: str,
    voice_id: str,
    ws_url: str,
    text_queue: Queue,
    audio_queue: Queue,
    cancel_event: threading.Event,
    client_holder: list[Any],
) -> None:
    """Run in thread: connect, feed text from text_queue, push PCM to audio_queue."""
    dashscope.api_key = api_key
    callback = _TTSCallback(audio_queue, cancel_event)
    client = QwenTtsRealtime(model=model, callback=callback, url=ws_url)
    client_holder.append(client)
    try:
        logger.info("Connecting Qwen TTS websocket: %s", ws_url)
        client.connect()
        client.update_session(
            voice=voice_id,
            response_format=AudioFormat.PCM_24000HZ_MONO_16BIT,
            mode="server_commit",
        )
        logger.info("Qwen TTS session updated with voice_id")
        while True:
            if cancel_event.is_set():
                logger.info("TTS sync worker: cancel detected in text loop")
                break
            try:
                text = text_queue.get(timeout=0.5)
            except Empty:
                continue
            if text is None:
                break
            if isinstance(text, str) and text.strip():
                try:
                    client.append_text(text)
                except Exception:
                    if cancel_event.is_set():
                        break
                    raise
        if not cancel_event.is_set():
            client.finish()
            callback._finished.wait(timeout=30)
            logger.info("Qwen TTS finished normally")
        else:
            logger.info("Qwen TTS cancelled, skipping finish")
    except Exception:
        if not cancel_event.is_set():
            logger.exception("Qwen TTS sync worker crashed")
    finally:
        audio_queue.put(None)


class TTSClient:
    """Stream text to TTS and asynchronously iterate over PCM chunks (24kHz, mono, 16-bit)."""

    def __init__(
        self,
        api_key: str,
        model: str,
        voice_id: str,
        ws_url: str,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._voice_id = voice_id
        self._ws_url = ws_url
        # Per-active-stream state (set during stream_speech, cleared on exit).
        self._cancel_event: threading.Event | None = None
        self._client_holder: list[Any] = []
        self._audio_queue: Queue | None = None

    async def cancel(self) -> None:
        """Cancel in-progress TTS synthesis immediately.

        Safe to call even when no stream is active (becomes a no-op).
        """
        if self._cancel_event is None:
            return
        self._cancel_event.set()
        if self._client_holder:
            client: QwenTtsRealtime = self._client_holder[0]
            try:
                client.cancel_response()
            except Exception:
                logger.debug("cancel_response failed (connection may already be closed)", exc_info=True)
            try:
                client.close()
            except Exception:
                logger.debug("close failed (connection may already be closed)", exc_info=True)
        # Safety net: ensure the audio consumer loop can exit even if on_close
        # callback doesn't fire quickly enough.
        if self._audio_queue is not None:
            self._audio_queue.put(None)
        logger.info("TTS cancel complete")

    async def stream_speech(
        self, text_iter: AsyncIterator[str]
    ) -> AsyncIterator[bytes]:
        """Feed text from async iterator into TTS; yield PCM audio chunks."""
        text_queue: Queue = Queue()
        audio_queue: Queue = Queue()
        cancel_event = threading.Event()
        client_holder: list[Any] = []
        loop = asyncio.get_running_loop()

        # Expose per-stream state so cancel() can reach them.
        self._cancel_event = cancel_event
        self._client_holder = client_holder
        self._audio_queue = audio_queue

        async def feed_text() -> None:
            try:
                async for chunk in text_iter:
                    if cancel_event.is_set():
                        break
                    await loop.run_in_executor(None, lambda c=chunk: text_queue.put(c))
                await loop.run_in_executor(None, lambda: text_queue.put(None))
            except asyncio.CancelledError:
                text_queue.put(None)

        feed_task = asyncio.create_task(feed_text())
        thread = threading.Thread(
            target=_run_tts_sync,
            args=(
                self._api_key,
                self._model,
                self._voice_id,
                self._ws_url,
                text_queue,
                audio_queue,
                cancel_event,
                client_holder,
            ),
            daemon=True,
        )
        thread.start()
        try:
            while True:
                chunk = await loop.run_in_executor(None, audio_queue.get)
                if chunk is None:
                    break
                yield chunk
        finally:
            cancel_event.set()
            feed_task.cancel()
            try:
                await feed_task
            except asyncio.CancelledError:
                pass
            # Clear per-stream state.
            self._cancel_event = None
            self._client_holder = []
            self._audio_queue = None
