"""Agent loop: multi-turn LLM-tool execution cycle (inspired by Pi agent-core)."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Callable, Awaitable

from app.llm import LLMClient, LLMResponse
from app.memory import SoulManager
from app.skills import SkillManager
from app.tools import ToolRegistry

logger = logging.getLogger("tinyagent.agent")

MAX_TOOL_ROUNDS = 5
TOOL_RESULT_PREVIEW_CHARS = 2000


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
        tool_result_preview_chars: int = TOOL_RESULT_PREVIEW_CHARS,
    ) -> None:
        self._llm = llm
        self._tools = tools
        self._skills = skills
        self._soul = soul
        self._max_rounds = max_rounds
        self._tool_result_preview_chars = max(200, tool_result_preview_chars)

    def _update_system_prompt(self) -> None:
        """Rebuild the system prompt: soul + user + agent instructions + skills."""
        parts: list[str] = []

        # 1. Soul (who the agent is)
        soul_prompt = self._soul.build_soul_system_prompt()
        if soul_prompt:
            parts.append(soul_prompt)

        # 2. Agent instructions (capabilities and rules from soul/AGENT.md)
        agent_instructions = self._soul.get_agent_instructions_prompt()
        if agent_instructions:
            parts.append(agent_instructions)

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

        Design:
          - Every round uses tool_choice="auto"; the model freely decides.
          - If the model replies with text at any point, we yield it and return.
          - If all ``max_rounds`` rounds are consumed by tool calls, we make
            one final text-only call (``stream_text_only``) that converts
            tool history to plain text so every provider can handle it.
        """
        self._update_system_prompt()
        self._llm.add_user_message(user_text)

        openai_tools = self._tools.get_openai_tools()
        rounds = 0
        tool_seq = 0

        async def _noop(_: AgentEvent) -> None:
            return

        emit = on_event or _noop

        while rounds < self._max_rounds:
            if cancel_event and cancel_event.is_set():
                logger.info("Agent turn cancelled before round %d", rounds)
                return

            rounds += 1
            await emit(AgentEvent(type="thinking", data={"round": rounds}))

            response: LLMResponse = await self._llm.stream_chat_with_tools(
                tools=openai_tools,
            )

            if cancel_event and cancel_event.is_set():
                logger.info("Agent turn cancelled after LLM round %d", rounds)
                return

            # If LLM returned tool calls, execute them and loop
            if response.tool_calls:
                for tc in response.tool_calls:
                    tool_seq += 1
                    tool_call_id = (tc.id or "").strip()
                    if not tool_call_id:
                        # Some providers may stream tool calls without ids.
                        # Ensure frontend can always correlate start/result events.
                        tool_call_id = f"fallback_{rounds}_{tool_seq}_{int(time.time() * 1000)}"
                    logger.info("Tool call: %s(%s)", tc.name, tc.arguments)

                    await emit(
                        AgentEvent(
                            type="tool_start",
                            data={
                                "tool_call_id": tool_call_id,
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
                    self._llm.add_tool_result(tool_call_id, tc.name, result.content)

                    await emit(
                        AgentEvent(
                            type="tool_result",
                            data={
                                "tool_call_id": tool_call_id,
                                "name": tc.name,
                                "content": result.content[: self._tool_result_preview_chars],
                                "is_error": result.is_error,
                                "elapsed_ms": elapsed_ms,
                            },
                        )
                    )

                    # Check if a skill was activated/deactivated
                    if tc.name in ("activate_skill", "deactivate_skill"):
                        self._update_system_prompt()
                        await emit(
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
            if response.tokens:
                for token in response.tokens:
                    yield token
            return

        # ------------------------------------------------------------------
        # Max rounds exhausted — every round produced tool calls.
        # Force a text-only response via a dedicated path that converts
        # tool history to plain text (no tools / tool_choice in the request),
        # with a built-in fallback if the API still errors.
        # ------------------------------------------------------------------
        logger.warning(
            "Agent hit max %d tool rounds, forcing text-only response",
            self._max_rounds,
        )
        await emit(AgentEvent(type="thinking", data={"round": "final"}))

        response = await self._llm.stream_text_only(
            nudge="(系统提示：你已经完成了多轮工具调用。请根据上面获得的工具结果，直接用语音友好的文字回复用户。不要再调用任何工具。)",
        )
        for token in response.tokens:
            yield token
