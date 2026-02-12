"""OpenAI-compatible streaming chat client with conversation history."""
from collections.abc import AsyncIterator
from typing import Any

from openai import AsyncOpenAI


SYSTEM_PROMPT = """你是一个友好的中文语音助手。请用简洁、口语化的中文回复，适合语音播报。回复尽量短一些，一两句话为宜。"""


class LLMClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        system_prompt: str = SYSTEM_PROMPT,
    ) -> None:
        self._client = AsyncOpenAI(base_url=base_url, api_key=api_key)
        self._model = model
        self._system_prompt = system_prompt
        self._history: list[dict[str, str]] = []

    def add_user_message(self, content: str) -> None:
        self._history.append({"role": "user", "content": content})

    def add_assistant_message(self, content: str) -> None:
        self._history.append({"role": "assistant", "content": content})

    def clear_history(self) -> None:
        self._history.clear()

    def get_messages_for_api(self) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": self._system_prompt},
            *self._history,
        ]

    async def stream_chat(self, user_text: str) -> AsyncIterator[str]:
        """Append user message, stream assistant reply tokens, then append full reply to history."""
        self.add_user_message(user_text)
        messages = self.get_messages_for_api()
        full_content: list[str] = []
        stream = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            stream=True,
        )
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta and getattr(delta, "content", None):
                full_content.append(delta.content)
                yield delta.content
        reply = "".join(full_content)
        if reply:
            self.add_assistant_message(reply)
