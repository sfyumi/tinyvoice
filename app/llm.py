"""OpenAI-compatible streaming chat client with conversation history and tool calling."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from openai import AsyncOpenAI

logger = logging.getLogger("tinyagent.llm")

DEFAULT_SYSTEM_PROMPT = """你是一个友好的中文语音助手。请用简洁、口语化的中文回复，适合语音播报。回复尽量短一些，一两句话为宜。"""

AGENT_INSTRUCTIONS = """\
<agent_instructions>
你是一个强大的语音智能体。你具备以下能力：
1. 使用工具来获取实时信息、执行计算、搜索互联网、读写文件等。
2. 动态加载和使用技能（Skills）来增强特定领域的能力。
3. 回忆过去的对话（recall_memory）和记录用户信息（update_user_profile）。
4. 用简洁、口语化的中文回复，适合语音播报。

重要规则：
- 回复要简洁自然，适合语音朗读。不要使用 markdown 格式、代码块或特殊符号。
- 当需要获取实时信息（时间、天气、新闻等）时，主动使用对应工具。
- 当用户的请求涉及特定领域时，考虑激活相应技能。
- 工具调用的结果要自然地融入回复中，而不是直接念出原始数据。
- 如果工具调用失败，简要告知用户并提供替代方案。
- 当你了解到用户的重要信息（姓名、偏好、兴趣等）时，用 update_user_profile 记录下来。
- 当用户提到过去的对话或你需要上下文时，用 recall_memory 查看记忆。
</agent_instructions>
"""


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
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = ""

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0


class LLMClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
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

    def clear_history(self) -> None:
        self._history.clear()

    def get_messages_for_api(self) -> list[dict[str, Any]]:
        return [
            {"role": "system", "content": self._system_prompt},
            *self._history,
        ]

    async def stream_chat(self, user_text: str) -> AsyncIterator[str]:
        """Simple text-only streaming (backward compatible)."""
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

    async def stream_chat_with_tools(
        self,
        tools: list[dict[str, Any]] | None = None,
        on_text_delta: Any | None = None,
    ) -> LLMResponse:
        """Stream a chat completion that may include tool calls.

        Args:
            tools: OpenAI-format tool definitions. Pass None to disable tools.
            on_text_delta: async callback(token: str) called for each text token.

        Returns:
            LLMResponse with either text content or tool_calls.
        """
        messages = self.get_messages_for_api()
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "stream": True,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        stream = await self._client.chat.completions.create(**kwargs)

        full_text: list[str] = []
        # Accumulate tool calls from streaming deltas
        tool_call_accum: dict[int, dict[str, Any]] = {}
        finish_reason = ""

        async for chunk in stream:
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            delta = choice.delta

            # Capture finish reason
            if choice.finish_reason:
                finish_reason = choice.finish_reason

            # Text content
            if delta and getattr(delta, "content", None):
                full_text.append(delta.content)
                if on_text_delta:
                    await on_text_delta(delta.content)

            # Tool calls (streamed incrementally)
            if delta and getattr(delta, "tool_calls", None):
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
            text="".join(full_text),
            finish_reason=finish_reason,
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
