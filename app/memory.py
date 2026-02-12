"""Soul & Memory manager: persistent agent identity and user understanding (inspired by OpenClaw)."""

from __future__ import annotations

import datetime
import logging
from pathlib import Path

logger = logging.getLogger("tinyagent.memory")

# Maximum characters to load from MEMORY.md on-demand
DEFAULT_MEMORY_MAX_CHARS = 4000


class SoulManager:
    """Manages the agent's soul (SOUL.md), user profile (USER.md), and conversation memory (MEMORY.md).

    Inspired by OpenClaw's identity system:
    - SOUL.md defines who the agent IS (personality, values, voice traits)
    - USER.md captures who the user IS (learned over time)
    - MEMORY.md accumulates conversation memory across sessions
    """

    def __init__(self, soul_dir: Path) -> None:
        self._soul_dir = soul_dir
        self._soul_dir.mkdir(parents=True, exist_ok=True)
        self._soul_content: str = ""
        self._user_content: str = ""
        self._agent_content: str = ""

    @property
    def soul_dir(self) -> Path:
        return self._soul_dir

    def load(self) -> None:
        """Read SOUL.md, USER.md and AGENT.md from disk. Called once per connection."""
        soul_path = self._soul_dir / "SOUL.md"
        user_path = self._soul_dir / "USER.md"
        agent_path = self._soul_dir / "AGENT.md"

        if soul_path.exists():
            self._soul_content = soul_path.read_text(encoding="utf-8").strip()
            logger.info("Loaded SOUL.md (%d chars)", len(self._soul_content))
        else:
            self._soul_content = ""
            logger.info("No SOUL.md found at %s", soul_path)

        if user_path.exists():
            self._user_content = user_path.read_text(encoding="utf-8").strip()
            logger.info("Loaded USER.md (%d chars)", len(self._user_content))
        else:
            self._user_content = ""
            logger.info("No USER.md found at %s", user_path)

        if agent_path.exists():
            self._agent_content = agent_path.read_text(encoding="utf-8").strip()
            logger.info("Loaded AGENT.md (%d chars)", len(self._agent_content))
        else:
            self._agent_content = ""
            logger.warning("No AGENT.md found at %s; agent instructions will be empty", agent_path)

    def get_memory(self, max_chars: int = DEFAULT_MEMORY_MAX_CHARS) -> str:
        """Read the most recent entries from MEMORY.md (on-demand, not auto-injected)."""
        memory_path = self._soul_dir / "MEMORY.md"
        if not memory_path.exists():
            return ""
        try:
            content = memory_path.read_text(encoding="utf-8").strip()
            if not content:
                return ""
            # Return the tail (most recent entries) if over limit
            if len(content) > max_chars:
                # Find a clean break point
                truncated = content[-max_chars:]
                # Try to start at a line boundary
                newline_pos = truncated.find("\n")
                if newline_pos > 0 and newline_pos < 200:
                    truncated = truncated[newline_pos + 1:]
                return f"(较早的记忆已省略)\n\n{truncated}"
            return content
        except Exception:
            logger.exception("Failed to read MEMORY.md")
            return ""

    def update_user(self, updates: str) -> str:
        """Merge updates into USER.md. Returns the new content."""
        user_path = self._soul_dir / "USER.md"

        # Read existing content
        existing = ""
        if user_path.exists():
            existing = user_path.read_text(encoding="utf-8").strip()

        if existing:
            # Append updates to the Context section if it exists
            if "## 上下文笔记" in existing:
                new_content = existing + f"\n- {updates}"
            else:
                new_content = existing + f"\n\n## 上下文笔记\n\n- {updates}"
        else:
            new_content = f"# 用户档案\n\n## 上下文笔记\n\n- {updates}"

        user_path.write_text(new_content + "\n", encoding="utf-8")
        self._user_content = new_content
        logger.info("Updated USER.md: +%d chars", len(updates))
        return new_content

    def append_memory(self, summary: str) -> None:
        """Append a session summary to MEMORY.md with timestamp."""
        memory_path = self._soul_dir / "MEMORY.md"

        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        entry = f"\n## {now}\n\n{summary.strip()}\n"

        if memory_path.exists():
            existing = memory_path.read_text(encoding="utf-8")
        else:
            existing = "# 对话记忆\n\n*此文件由 TinyAgent 自动维护，记录每次对话的关键摘要。*\n"

        memory_path.write_text(existing + entry, encoding="utf-8")
        logger.info("Appended session memory (%d chars) to MEMORY.md", len(summary))

    def build_soul_system_prompt(self) -> str:
        """Build the soul+user portion of the system prompt.

        This is called by the agent to compose the full system prompt:
        soul_prompt + user_context + agent_instructions + skills
        """
        parts: list[str] = []

        if self._soul_content:
            parts.append("<agent_soul>")
            parts.append(self._soul_content)
            parts.append("</agent_soul>")

        if self._user_content:
            parts.append("\n<user_profile>")
            parts.append(self._user_content)
            parts.append("</user_profile>")

        return "\n".join(parts)

    def get_agent_instructions_prompt(self) -> str:
        """Return AGENT.md content used as runtime agent instructions."""
        return self._agent_content

    def to_info_dict(self) -> dict:
        """Return soul/memory status for frontend display."""
        memory_path = self._soul_dir / "MEMORY.md"
        memory_entries = 0
        if memory_path.exists():
            try:
                content = memory_path.read_text(encoding="utf-8")
                memory_entries = content.count("\n## ")
            except Exception:
                pass

        return {
            "soul_loaded": bool(self._soul_content),
            "user_loaded": bool(self._user_content),
            "agent_loaded": bool(self._agent_content),
            "memory_entries": memory_entries,
            "soul_chars": len(self._soul_content),
            "user_chars": len(self._user_content),
            "agent_chars": len(self._agent_content),
        }
