"""OpenAI-compatible streaming chat client with conversation history and tool calling."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from openai import AsyncOpenAI

logger = logging.getLogger("tinyagent.llm")


@dataclass
class ToolCall:
    """Represents a tool call from the LLM."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    """Structured response from the LLM, can be text or tool calls."""

    text: str = ""
    tokens: list[str] = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0


class LLMClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        system_prompt: str = "",
    ) -> None:
        self._client = AsyncOpenAI(base_url=base_url, api_key=api_key)
        self._model = model
        self._system_prompt = system_prompt
        self._history: list[dict[str, Any]] = []

    @property
    def system_prompt(self) -> str:
        return self._system_prompt

    @system_prompt.setter
    def system_prompt(self, value: str) -> None:
        self._system_prompt = value

    def add_user_message(self, content: str) -> None:
        self._history.append({"role": "user", "content": content})

    def add_assistant_message(self, content: str) -> None:
        self._history.append({"role": "assistant", "content": content})

    def add_assistant_tool_calls(self, tool_calls: list[ToolCall]) -> None:
        """Add an assistant message that contains tool calls."""
        tc_list = []
        for tc in tool_calls:
            tc_list.append(
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                    },
                }
            )
        self._history.append(
            {"role": "assistant", "content": None, "tool_calls": tc_list}
        )

    def add_tool_result(self, tool_call_id: str, name: str, content: str) -> None:
        """Add a tool result message."""
        self._history.append(
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "name": name,
                "content": content,
            }
        )

    def _get_messages_for_api(self) -> list[dict[str, Any]]:
        return [
            {"role": "system", "content": self._system_prompt},
            *self._history,
        ]

    async def stream_chat_with_tools(
        self,
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        """Stream a chat completion that may include tool calls.

        This method handles the NORMAL agent loop case: tools are available and
        the model freely decides whether to call them or reply with text.

        For forcing a text-only response (after max tool rounds), use
        ``stream_text_only`` instead.

        Args:
            tools: OpenAI-format tool definitions. Pass None or [] to disable tools.

        Returns:
            LLMResponse with either text content or tool_calls.
        """
        messages = self._get_messages_for_api()
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "stream": True,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        stream = await self._client.chat.completions.create(**kwargs)

        tokens: list[str] = []
        # Accumulate tool calls from streaming deltas
        tool_call_accum: dict[int, dict[str, Any]] = {}

        async for chunk in stream:
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            delta = choice.delta

            # Text content
            if delta and delta.content:
                tokens.append(delta.content)

            # Tool calls (streamed incrementally)
            if delta and delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index
                    if idx not in tool_call_accum:
                        tool_call_accum[idx] = {
                            "id": "",
                            "name": "",
                            "arguments": "",
                        }
                    acc = tool_call_accum[idx]
                    if tc_delta.id:
                        acc["id"] = tc_delta.id
                    if tc_delta.function:
                        if tc_delta.function.name:
                            acc["name"] = tc_delta.function.name
                        if tc_delta.function.arguments:
                            acc["arguments"] += tc_delta.function.arguments

        # Build response
        response = LLMResponse(
            text="".join(tokens),
            tokens=tokens,
        )

        # Parse accumulated tool calls
        for idx in sorted(tool_call_accum.keys()):
            acc = tool_call_accum[idx]
            try:
                args = json.loads(acc["arguments"]) if acc["arguments"] else {}
            except json.JSONDecodeError:
                logger.warning("Failed to parse tool args for %s: %s", acc["name"], acc["arguments"])
                args = {}
            response.tool_calls.append(
                ToolCall(id=acc["id"], name=acc["name"], arguments=args)
            )

        # Record in history
        if response.has_tool_calls:
            self.add_assistant_tool_calls(response.tool_calls)
        elif response.text:
            self.add_assistant_message(response.text)

        return response

    # ------------------------------------------------------------------
    # Text-only fallback (used after max tool rounds are exhausted)
    # ------------------------------------------------------------------

    def _build_text_only_messages(self) -> list[dict[str, Any]]:
        """Return a copy of the conversation with tool messages converted to
        plain text so that a regular (non-tool) chat completion can be used.

        * ``assistant`` messages with ``tool_calls`` → ``"[调用工具] ..."``
        * ``tool`` result messages → ``"[tool_name 返回] ..."``
        * Consecutive same-role messages are merged (some providers reject them).
        """
        messages = self._get_messages_for_api()
        converted: list[dict[str, Any]] = []
        for m in messages:
            if "tool_calls" in m:
                calls = m["tool_calls"]
                descs = []
                for tc in calls:
                    f = tc.get("function", {})
                    descs.append(
                        f"{f.get('name', '')}({f.get('arguments', '')})"
                    )
                converted.append({
                    "role": "assistant",
                    "content": "[调用工具] " + ", ".join(descs),
                })
            elif m.get("role") == "tool":
                converted.append({
                    "role": "assistant",
                    "content": f"[{m.get('name', '')} 返回] {m.get('content', '')}",
                })
            else:
                converted.append(m)

        # Merge consecutive same-role messages
        merged: list[dict[str, Any]] = []
        for msg in converted:
            if (
                merged
                and merged[-1]["role"] == msg["role"]
                and msg["role"] != "system"
            ):
                merged[-1]["content"] = (
                    (merged[-1].get("content") or "")
                    + "\n"
                    + (msg.get("content") or "")
                )
            else:
                merged.append(dict(msg))
        return merged

    async def stream_text_only(
        self,
        nudge: str | None = None,
    ) -> LLMResponse:
        """Force a text-only response.

        * Adds an optional *nudge* user message (e.g. "请直接回复").
        * Converts the full history (including tool calls / results) to plain
          text so the model keeps context but the API sees no tool format.
        * Sends a plain ``chat.completions`` request — **no** ``tools``,
          **no** ``tool_choice`` — so the provider cannot raise
          "tool_choice is none but model called a tool".
        * On any API error, falls back to a canned reply so the user always
          gets *something*.
        """
        if nudge:
            self.add_user_message(nudge)

        messages = self._build_text_only_messages()
        full_text: list[str] = []

        try:
            stream = await self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                stream=True,
            )
            async for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    full_text.append(delta.content)
        except Exception as exc:
            logger.warning("Text-only LLM call failed (%s), using fallback", exc)
            fallback = "抱歉，让我整理一下。我刚才查到了一些信息但处理过程中出了点问题，请再问我一次吧。"
            full_text = [fallback]

        text = "".join(full_text)
        if text:
            self.add_assistant_message(text)
        return LLMResponse(text=text, tokens=full_text)
