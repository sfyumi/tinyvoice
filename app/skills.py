"""Agent Skills engine: discover, parse, activate SKILL.md files (Agent Skills spec)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger("tinyagent.skills")


@dataclass
class Skill:
    """A single agent skill loaded from a SKILL.md file."""

    name: str
    description: str
    instructions: str  # markdown body after frontmatter
    path: Path  # directory containing SKILL.md
    metadata: dict[str, str] = field(default_factory=dict)

    @property
    def short_info(self) -> str:
        return f"{self.name}: {self.description}"


def _parse_skill_md(skill_dir: Path) -> Skill | None:
    """Parse a SKILL.md file from a skill directory."""
    skill_file = skill_dir / "SKILL.md"
    if not skill_file.exists():
        return None
    try:
        content = skill_file.read_text(encoding="utf-8")
    except Exception:
        logger.exception("Failed to read %s", skill_file)
        return None

    # Split YAML frontmatter from body
    fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", content, re.DOTALL)
    if not fm_match:
        logger.warning("No YAML frontmatter in %s", skill_file)
        return None

    try:
        frontmatter = yaml.safe_load(fm_match.group(1)) or {}
    except yaml.YAMLError:
        logger.exception("Invalid YAML frontmatter in %s", skill_file)
        return None

    name = frontmatter.get("name", "")
    description = frontmatter.get("description", "")
    if not name or not description:
        logger.warning("Skill %s missing required name/description", skill_file)
        return None

    metadata = frontmatter.get("metadata", {}) or {}
    body = fm_match.group(2).strip()

    return Skill(
        name=name,
        description=description,
        instructions=body,
        path=skill_dir,
        metadata=metadata,
    )


class SkillManager:
    """Discovers, loads, and manages agent skills."""

    def __init__(self, skill_dirs: list[Path] | None = None) -> None:
        self._skill_dirs = skill_dirs or []
        self._all_skills: dict[str, Skill] = {}
        self._active: set[str] = set()

    def discover(self) -> list[Skill]:
        """Scan configured directories for SKILL.md files."""
        self._all_skills.clear()
        for d in self._skill_dirs:
            if not d.is_dir():
                logger.debug("Skills directory does not exist: %s", d)
                continue
            for child in sorted(d.iterdir()):
                if not child.is_dir():
                    continue
                skill = _parse_skill_md(child)
                if skill:
                    self._all_skills[skill.name] = skill
                    logger.info("Discovered skill: %s (%s)", skill.name, skill.path)
        logger.info("Total skills discovered: %d", len(self._all_skills))
        return list(self._all_skills.values())

    @property
    def all_skills(self) -> list[Skill]:
        return list(self._all_skills.values())

    def get_skill(self, name: str) -> Skill | None:
        return self._all_skills.get(name)

    def activate(self, name: str) -> bool:
        """Activate a skill by name. Returns True if successful."""
        if name in self._all_skills:
            self._active.add(name)
            logger.info("Skill activated: %s", name)
            return True
        logger.warning("Cannot activate unknown skill: %s", name)
        return False

    def deactivate(self, name: str) -> bool:
        """Deactivate a skill. Returns True if it was active."""
        if name in self._active:
            self._active.discard(name)
            logger.info("Skill deactivated: %s", name)
            return True
        return False

    def get_active_skills(self) -> list[Skill]:
        return [self._all_skills[n] for n in self._active if n in self._all_skills]

    @property
    def active_names(self) -> list[str]:
        return sorted(self._active)

    def build_system_prompt(self, base_prompt: str) -> str:
        """Build a system prompt with skill metadata and active skill instructions injected."""
        parts = [base_prompt]

        # Always include available skills metadata (progressive disclosure)
        if self._all_skills:
            skills_xml = "\n<available_skills>\n"
            for skill in self._all_skills.values():
                active_tag = ' active="true"' if skill.name in self._active else ""
                skills_xml += (
                    f"<skill{active_tag}>\n"
                    f"  <name>{skill.name}</name>\n"
                    f"  <description>{skill.description}</description>\n"
                    f"</skill>\n"
                )
            skills_xml += "</available_skills>\n"
            skills_xml += (
                "\n你可以通过调用 activate_skill 工具来激活技能，或通过 list_skills 查看所有可用技能。"
                "当用户的请求匹配某个技能的描述时，你应该主动激活它。\n"
            )
            parts.append(skills_xml)

        # Include full instructions for active skills
        active = self.get_active_skills()
        if active:
            parts.append("\n<active_skill_instructions>")
            for skill in active:
                parts.append(f"\n## 技能: {skill.name}\n")
                parts.append(skill.instructions)
            parts.append("\n</active_skill_instructions>")

        return "\n".join(parts)

    def to_info_dict(self) -> list[dict]:
        """Return skill info for WebSocket broadcast."""
        return [
            {
                "name": s.name,
                "description": s.description,
                "active": s.name in self._active,
            }
            for s in self._all_skills.values()
        ]
