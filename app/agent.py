"""Agent loop: multi-turn LLM-tool execution cycle (inspired by Pi agent-core)."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Callable, Awaitable

from app.llm import LLMClient, LLMResponse, AGENT_INSTRUCTIONS
from app.memory import SoulManager
from app.skills import SkillManager
from app.tools import ToolRegistry, ToolResult

logger = logging.getLogger("tinyagent.agent")

MAX_TOOL_ROUNDS = 5


@dataclass
class AgentEvent:
    """Events emitted by the agent loop for UI updates."""

    type: str  # "tool_start", "tool_result", "skill_changed", "text_delta", "thinking"
    data: dict[str, Any]


# Callback type for events
OnAgentEvent = Callable[[AgentEvent], Awaitable[None]]


class AgentLoop:
    """Orchestrates multi-turn LLM + tool execution for a single voice turn.

    Inspired by Pi's agentLoop: the LLM can call tools, get results,
    and continue reasoning until it produces a final text response.
    """

    def __init__(
        self,
        *,
        llm: LLMClient,
        tools: ToolRegistry,
        skills: SkillManager,
        soul: SoulManager,
        max_rounds: int = MAX_TOOL_ROUNDS,
    ) -> None:
        self._llm = llm
        self._tools = tools
        self._skills = skills
        self._soul = soul
        self._max_rounds = max_rounds

    def _update_system_prompt(self) -> None:
        """Rebuild the system prompt: soul + user + agent instructions + skills."""
        parts: list[str] = []

        # 1. Soul (who the agent is)
        soul_prompt = self._soul.build_soul_system_prompt()
        if soul_prompt:
            parts.append(soul_prompt)

        # 2. Agent instructions (capabilities and rules)
        parts.append(AGENT_INSTRUCTIONS)

        # 3. Skills (available capabilities + active skill instructions)
        base = "\n".join(parts)
        prompt = self._skills.build_system_prompt(base)
        self._llm.system_prompt = prompt

    async def run_turn(
        self,
        user_text: str,
        *,
        on_event: OnAgentEvent | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> AsyncIterator[str]:
        """Run a full agent turn: user_text -> (tool loops) -> text stream.

        Yields text tokens for TTS as they arrive from the final LLM response.
        Emits AgentEvents for tool calls and skill changes via on_event callback.
        """
        self._update_system_prompt()
        self._llm.add_user_message(user_text)

        openai_tools = self._tools.get_openai_tools() or None
        rounds = 0

        while rounds < self._max_rounds:
            if cancel_event and cancel_event.is_set():
                logger.info("Agent turn cancelled before round %d", rounds)
                return

            rounds += 1
            collected_text: list[str] = []

            async def on_text_delta(token: str) -> None:
                collected_text.append(token)

            if on_event:
                await on_event(AgentEvent(type="thinking", data={"round": rounds}))

            response: LLMResponse = await self._llm.stream_chat_with_tools(
                tools=openai_tools,
                on_text_delta=on_text_delta,
            )

            if cancel_event and cancel_event.is_set():
                logger.info("Agent turn cancelled after LLM round %d", rounds)
                return

            # If LLM returned tool calls, execute them and loop
            if response.has_tool_calls:
                for tc in response.tool_calls:
                    logger.info("Tool call: %s(%s)", tc.name, tc.arguments)

                    if on_event:
                        await on_event(
                            AgentEvent(
                                type="tool_start",
                                data={
                                    "tool_call_id": tc.id,
                                    "name": tc.name,
                                    "arguments": tc.arguments,
                                },
                            )
                        )

                    if cancel_event and cancel_event.is_set():
                        logger.info("Agent cancelled during tool execution")
                        return

                    started = time.monotonic()
                    result = await self._tools.execute(tc.name, tc.arguments)
                    elapsed_ms = int((time.monotonic() - started) * 1000)

                    logger.info(
                        "Tool result: %s -> %s (error=%s, %dms)",
                        tc.name,
                        result.content[:100],
                        result.is_error,
                        elapsed_ms,
                    )

                    # Record tool result in LLM history
                    self._llm.add_tool_result(tc.id, tc.name, result.content)

                    if on_event:
                        await on_event(
                            AgentEvent(
                                type="tool_result",
                                data={
                                    "tool_call_id": tc.id,
                                    "name": tc.name,
                                    "content": result.content[:500],
                                    "is_error": result.is_error,
                                    "elapsed_ms": elapsed_ms,
                                },
                            )
                        )

                    # Check if a skill was activated/deactivated
                    if tc.name in ("activate_skill", "deactivate_skill"):
                        self._update_system_prompt()
                        if on_event:
                            await on_event(
                                AgentEvent(
                                    type="skill_changed",
                                    data={
                                        "action": tc.name,
                                        "skill_name": tc.arguments.get("skill_name", ""),
                                        "skills": self._skills.to_info_dict(),
                                    },
                                )
                            )

                # Continue the loop -- LLM will see tool results
                continue

            # No tool calls -- yield text tokens for TTS
            # The text was already streamed via on_text_delta, but we yield it here
            # for the pipeline to feed into TTS
            if response.text:
                for token in collected_text:
                    yield token
            return

        # Max rounds reached -- force a text response without tools
        logger.warning("Agent hit max %d tool rounds, forcing text-only response", self._max_rounds)
        collected_text = []

        async def on_final_delta(token: str) -> None:
            collected_text.append(token)

        self._llm.add_user_message(
            "(系统提示：你已经使用了多轮工具调用。请直接用文字回复用户。)"
        )
        response = await self._llm.stream_chat_with_tools(
            tools=None,  # No tools this time
            on_text_delta=on_final_delta,
        )
        for token in collected_text:
            yield token
