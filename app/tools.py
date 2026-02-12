"""Tool registry and built-in tools for the voice agent (inspired by Pi AgentTool)."""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Awaitable, TYPE_CHECKING

if TYPE_CHECKING:
    from app.memory import SoulManager
    from app.skills import SkillManager

logger = logging.getLogger("tinyagent.tools")


@dataclass
class ToolResult:
    """Result returned by a tool execution."""

    content: str
    is_error: bool = False


# Type for tool execute functions
ToolExecuteFn = Callable[..., Awaitable[ToolResult]]


@dataclass
class ToolDefinition:
    """A tool that the LLM can call."""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema
    execute: ToolExecuteFn


class ToolRegistry:
    """Registry for tools available to the agent loop."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        self._tools[tool.name] = tool
        logger.debug("Registered tool: %s", tool.name)

    def get(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    @property
    def tool_names(self) -> list[str]:
        return list(self._tools.keys())

    def get_openai_tools(self) -> list[dict[str, Any]]:
        """Return tool definitions in OpenAI function-calling format."""
        result = []
        for t in self._tools.values():
            result.append(
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
            )
        return result

    async def execute(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """Execute a tool by name with given arguments."""
        tool = self._tools.get(name)
        if not tool:
            return ToolResult(content=f"Unknown tool: {name}", is_error=True)
        try:
            return await tool.execute(arguments)
        except Exception as exc:
            logger.exception("Tool %s execution failed", name)
            return ToolResult(content=f"Tool error: {type(exc).__name__}: {exc}", is_error=True)


# ---------------------------------------------------------------------------
# Built-in tools
# ---------------------------------------------------------------------------


def _make_get_datetime() -> ToolDefinition:
    async def execute(args: dict[str, Any]) -> ToolResult:
        tz_name = args.get("timezone", "")
        try:
            if tz_name:
                import zoneinfo
                tz = zoneinfo.ZoneInfo(tz_name)
            else:
                tz = None
            now = datetime.datetime.now(tz=tz)
            return ToolResult(
                content=now.strftime("%Y-%m-%d %H:%M:%S %Z (星期%w)")
                .replace("星期0", "星期日")
                .replace("星期1", "星期一")
                .replace("星期2", "星期二")
                .replace("星期3", "星期三")
                .replace("星期4", "星期四")
                .replace("星期5", "星期五")
                .replace("星期6", "星期六")
            )
        except Exception as exc:
            return ToolResult(content=f"Error: {exc}", is_error=True)

    return ToolDefinition(
        name="get_datetime",
        description="获取当前日期和时间。可选指定时区（如 Asia/Shanghai, America/New_York）。",
        parameters={
            "type": "object",
            "properties": {
                "timezone": {
                    "type": "string",
                    "description": "IANA时区名称，如 Asia/Shanghai。留空使用服务器本地时间。",
                },
            },
            "required": [],
        },
        execute=execute,
    )


def _make_calculate() -> ToolDefinition:
    # Safe math evaluation using a restricted namespace
    _SAFE_NAMES: dict[str, Any] = {
        "abs": abs, "round": round, "min": min, "max": max, "sum": sum,
        "int": int, "float": float, "pow": pow, "len": len,
        "pi": math.pi, "e": math.e,
        "sqrt": math.sqrt, "log": math.log, "log10": math.log10, "log2": math.log2,
        "sin": math.sin, "cos": math.cos, "tan": math.tan,
        "asin": math.asin, "acos": math.acos, "atan": math.atan,
        "ceil": math.ceil, "floor": math.floor,
        "factorial": math.factorial, "gcd": math.gcd,
        "__builtins__": {},
    }

    async def execute(args: dict[str, Any]) -> ToolResult:
        expression = args.get("expression", "")
        if not expression:
            return ToolResult(content="No expression provided.", is_error=True)
        try:
            result = eval(expression, _SAFE_NAMES)  # noqa: S307
            return ToolResult(content=f"{expression} = {result}")
        except Exception as exc:
            return ToolResult(content=f"Calculation error: {exc}", is_error=True)

    return ToolDefinition(
        name="calculate",
        description="计算数学表达式。支持基本运算(+,-,*,/,**)、数学函数(sqrt,sin,cos,log等)和常量(pi,e)。",
        parameters={
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "要计算的数学表达式，如 'sqrt(144) + 3**2' 或 '2*pi*6.371e6'。",
                },
            },
            "required": ["expression"],
        },
        execute=execute,
    )


def _make_web_search() -> ToolDefinition:
    async def execute(args: dict[str, Any]) -> ToolResult:
        query = args.get("query", "")
        max_results = args.get("max_results", 3)
        if not query:
            return ToolResult(content="No search query.", is_error=True)
        try:
            from duckduckgo_search import DDGS

            def _search() -> str:
                with DDGS() as ddgs:
                    results = list(ddgs.text(query, max_results=min(max_results, 5)))
                if not results:
                    return "No results found."
                lines = []
                for i, r in enumerate(results, 1):
                    title = r.get("title", "")
                    body = r.get("body", "")
                    href = r.get("href", "")
                    lines.append(f"{i}. {title}\n   {body}\n   {href}")
                return "\n\n".join(lines)

            text = await asyncio.get_event_loop().run_in_executor(None, _search)
            return ToolResult(content=text)
        except ImportError:
            return ToolResult(
                content="Web search unavailable (duckduckgo-search not installed).",
                is_error=True,
            )
        except Exception as exc:
            return ToolResult(content=f"Search error: {exc}", is_error=True)

    return ToolDefinition(
        name="web_search",
        description="搜索互联网获取实时信息。使用DuckDuckGo搜索引擎，无需API密钥。",
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词",
                },
                "max_results": {
                    "type": "integer",
                    "description": "最大结果数（1-5，默认3）",
                },
            },
            "required": ["query"],
        },
        execute=execute,
    )


def _make_read_file() -> ToolDefinition:
    async def execute(args: dict[str, Any]) -> ToolResult:
        path_str = args.get("path", "")
        if not path_str:
            return ToolResult(content="No path provided.", is_error=True)
        path = Path(path_str).expanduser()
        if not path.exists():
            return ToolResult(content=f"File not found: {path}", is_error=True)
        if not path.is_file():
            return ToolResult(content=f"Not a file: {path}", is_error=True)
        try:
            size = path.stat().st_size
            if size > 100_000:
                return ToolResult(
                    content=f"File too large ({size} bytes). Max 100KB.",
                    is_error=True,
                )
            content = path.read_text(encoding="utf-8", errors="replace")
            return ToolResult(content=content)
        except Exception as exc:
            return ToolResult(content=f"Read error: {exc}", is_error=True)

    return ToolDefinition(
        name="read_file",
        description="读取文件内容（最大100KB）。",
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "文件路径",
                },
            },
            "required": ["path"],
        },
        execute=execute,
    )


def _make_write_file() -> ToolDefinition:
    async def execute(args: dict[str, Any]) -> ToolResult:
        path_str = args.get("path", "")
        content = args.get("content", "")
        if not path_str:
            return ToolResult(content="No path provided.", is_error=True)
        path = Path(path_str).expanduser()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            return ToolResult(content=f"Written {len(content)} chars to {path}")
        except Exception as exc:
            return ToolResult(content=f"Write error: {exc}", is_error=True)

    return ToolDefinition(
        name="write_file",
        description="写入内容到文件。如果目录不存在会自动创建。",
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "文件路径",
                },
                "content": {
                    "type": "string",
                    "description": "要写入的内容",
                },
            },
            "required": ["path", "content"],
        },
        execute=execute,
    )


def _make_run_command(allowed: bool = False) -> ToolDefinition:
    async def execute(args: dict[str, Any]) -> ToolResult:
        if not allowed:
            return ToolResult(
                content="Shell commands are disabled. Set TOOLS_ALLOW_SHELL=true to enable.",
                is_error=True,
            )
        command = args.get("command", "")
        if not command:
            return ToolResult(content="No command provided.", is_error=True)
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=os.getcwd(),
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
            out = stdout.decode("utf-8", errors="replace")[:8000]
            err = stderr.decode("utf-8", errors="replace")[:2000]
            code = proc.returncode
            result = f"Exit code: {code}\n"
            if out:
                result += f"stdout:\n{out}\n"
            if err:
                result += f"stderr:\n{err}\n"
            return ToolResult(content=result, is_error=code != 0)
        except asyncio.TimeoutError:
            return ToolResult(content="Command timed out (30s limit).", is_error=True)
        except Exception as exc:
            return ToolResult(content=f"Command error: {exc}", is_error=True)

    return ToolDefinition(
        name="run_command",
        description="执行Shell命令（30秒超时）。需要在配置中启用 TOOLS_ALLOW_SHELL=true。",
        parameters={
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "要执行的Shell命令",
                },
            },
            "required": ["command"],
        },
        execute=execute,
    )


def _make_list_skills(skill_manager: SkillManager) -> ToolDefinition:
    async def execute(args: dict[str, Any]) -> ToolResult:
        skills = skill_manager.all_skills
        if not skills:
            return ToolResult(content="当前没有可用的技能。")
        lines = []
        for s in skills:
            status = "[已激活]" if s.name in skill_manager.active_names else "[未激活]"
            lines.append(f"- {s.name} {status}: {s.description}")
        return ToolResult(content="\n".join(lines))

    return ToolDefinition(
        name="list_skills",
        description="列出所有可用的Agent技能及其激活状态。",
        parameters={"type": "object", "properties": {}, "required": []},
        execute=execute,
    )


def _make_activate_skill(skill_manager: SkillManager) -> ToolDefinition:
    async def execute(args: dict[str, Any]) -> ToolResult:
        name = args.get("skill_name", "")
        if not name:
            return ToolResult(content="No skill name provided.", is_error=True)
        if skill_manager.activate(name):
            skill = skill_manager.get_skill(name)
            return ToolResult(content=f"已激活技能: {name} - {skill.description if skill else ''}")
        available = ", ".join(s.name for s in skill_manager.all_skills)
        return ToolResult(
            content=f"未找到技能 '{name}'。可用技能: {available}",
            is_error=True,
        )

    return ToolDefinition(
        name="activate_skill",
        description="激活一个Agent技能。激活后，技能的专业指令会加入到对话上下文中，增强该领域的能力。",
        parameters={
            "type": "object",
            "properties": {
                "skill_name": {
                    "type": "string",
                    "description": "技能名称",
                },
            },
            "required": ["skill_name"],
        },
        execute=execute,
    )


def _make_deactivate_skill(skill_manager: SkillManager) -> ToolDefinition:
    async def execute(args: dict[str, Any]) -> ToolResult:
        name = args.get("skill_name", "")
        if not name:
            return ToolResult(content="No skill name provided.", is_error=True)
        if skill_manager.deactivate(name):
            return ToolResult(content=f"已停用技能: {name}")
        return ToolResult(content=f"技能 '{name}' 未处于激活状态。", is_error=True)

    return ToolDefinition(
        name="deactivate_skill",
        description="停用一个已激活的Agent技能。",
        parameters={
            "type": "object",
            "properties": {
                "skill_name": {
                    "type": "string",
                    "description": "技能名称",
                },
            },
            "required": ["skill_name"],
        },
        execute=execute,
    )


def _make_recall_memory(soul_manager: SoulManager) -> ToolDefinition:
    async def execute(args: dict[str, Any]) -> ToolResult:
        max_chars = args.get("max_chars", 4000)
        memory = soul_manager.get_memory(max_chars=max_chars)
        if not memory:
            return ToolResult(content="暂无对话记忆。这可能是第一次对话。")
        return ToolResult(content=memory)

    return ToolDefinition(
        name="recall_memory",
        description="回忆过去的对话记忆。当用户提到过去的对话内容、之前聊过的话题，或你需要参考历史上下文时使用。",
        parameters={
            "type": "object",
            "properties": {
                "max_chars": {
                    "type": "integer",
                    "description": "最多读取的字符数（默认4000）",
                },
            },
            "required": [],
        },
        execute=execute,
    )


def _make_update_user_profile(soul_manager: SoulManager) -> ToolDefinition:
    async def execute(args: dict[str, Any]) -> ToolResult:
        info = args.get("info", "")
        if not info:
            return ToolResult(content="No info provided.", is_error=True)
        soul_manager.update_user(info)
        return ToolResult(content=f"已记录用户信息: {info}")

    return ToolDefinition(
        name="update_user_profile",
        description="记录关于用户的新信息到用户档案。当你在对话中了解到用户的姓名、偏好、兴趣、工作等重要信息时调用。",
        parameters={
            "type": "object",
            "properties": {
                "info": {
                    "type": "string",
                    "description": "要记录的用户信息，如'用户名叫小明，是一名软件工程师'",
                },
            },
            "required": ["info"],
        },
        execute=execute,
    )


def _make_save_note(soul_manager: SoulManager) -> ToolDefinition:
    async def execute(args: dict[str, Any]) -> ToolResult:
        note = args.get("note", "")
        if not note:
            return ToolResult(content="No note provided.", is_error=True)
        soul_manager.append_memory(note)
        return ToolResult(content=f"已保存笔记到记忆中。")

    return ToolDefinition(
        name="save_note",
        description="保存重要信息到长期记忆。当对话中出现重要的事实、决定或用户明确要求你记住的内容时使用。",
        parameters={
            "type": "object",
            "properties": {
                "note": {
                    "type": "string",
                    "description": "要保存的笔记内容",
                },
            },
            "required": ["note"],
        },
        execute=execute,
    )


def _make_run_python(enabled: bool = True) -> ToolDefinition:
    import sys

    async def execute(args: dict[str, Any]) -> ToolResult:
        if not enabled:
            return ToolResult(
                content="Python execution is disabled. Set PYTHON_EXEC_ENABLED=true to enable.",
                is_error=True,
            )
        code = args.get("code", "")
        if not code:
            return ToolResult(content="No code provided.", is_error=True)
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-c", code,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=os.getcwd(),
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
            out = stdout.decode("utf-8", errors="replace")[:8000]
            err = stderr.decode("utf-8", errors="replace")[:2000]
            rc = proc.returncode
            result = ""
            if out:
                result += out
            if err:
                result += f"\n[stderr]\n{err}" if result else f"[stderr]\n{err}"
            if rc != 0:
                result += f"\n[exit code: {rc}]"
            return ToolResult(content=result.strip() or "(no output)", is_error=rc != 0)
        except asyncio.TimeoutError:
            return ToolResult(content="Python execution timed out (30s limit).", is_error=True)
        except Exception as exc:
            return ToolResult(content=f"Execution error: {exc}", is_error=True)

    return ToolDefinition(
        name="run_python",
        description="执行Python代码并返回输出。可以用来做数据处理、文件操作、数学计算等任何Python能做的事。代码通过print()输出结果。30秒超时。",
        parameters={
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "要执行的Python代码。用print()输出需要的结果。",
                },
            },
            "required": ["code"],
        },
        execute=execute,
    )


def _make_list_directory() -> ToolDefinition:
    async def execute(args: dict[str, Any]) -> ToolResult:
        path_str = args.get("path", ".")
        path = Path(path_str).expanduser().resolve()
        if not path.exists():
            return ToolResult(content=f"Directory not found: {path}", is_error=True)
        if not path.is_dir():
            return ToolResult(content=f"Not a directory: {path}", is_error=True)
        try:
            entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
            lines = [f"Directory: {path}\n"]
            for entry in entries[:100]:  # Cap at 100 entries
                try:
                    stat = entry.stat()
                    size = stat.st_size
                    mtime = datetime.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
                    if entry.is_dir():
                        lines.append(f"  [DIR]  {entry.name}/")
                    elif size < 1024:
                        lines.append(f"  {size:>8d} B  {mtime}  {entry.name}")
                    elif size < 1024 * 1024:
                        lines.append(f"  {size/1024:>7.1f} KB  {mtime}  {entry.name}")
                    else:
                        lines.append(f"  {size/1024/1024:>7.1f} MB  {mtime}  {entry.name}")
                except OSError:
                    lines.append(f"  [???]  {entry.name}")
            total = len(list(path.iterdir()))
            if total > 100:
                lines.append(f"\n  ... and {total - 100} more entries")
            lines.append(f"\nTotal: {total} items")
            return ToolResult(content="\n".join(lines))
        except PermissionError:
            return ToolResult(content=f"Permission denied: {path}", is_error=True)
        except Exception as exc:
            return ToolResult(content=f"Error listing directory: {exc}", is_error=True)

    return ToolDefinition(
        name="list_directory",
        description="列出目录中的文件和文件夹，显示大小和修改时间。用于探索文件系统。",
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "目录路径。默认为当前目录。支持 ~ 表示用户主目录。",
                },
            },
            "required": [],
        },
        execute=execute,
    )


def _make_search_files() -> ToolDefinition:
    async def execute(args: dict[str, Any]) -> ToolResult:
        pattern = args.get("pattern", "")
        directory = args.get("directory", ".")
        if not pattern:
            return ToolResult(content="No search pattern provided.", is_error=True)
        path = Path(directory).expanduser().resolve()
        if not path.is_dir():
            return ToolResult(content=f"Not a directory: {path}", is_error=True)
        try:
            matches = list(path.rglob(pattern))[:50]  # Cap at 50 results
            if not matches:
                return ToolResult(content=f"No files matching '{pattern}' in {path}")
            lines = [f"Found {len(matches)} file(s) matching '{pattern}' in {path}:\n"]
            for m in matches:
                try:
                    rel = m.relative_to(path)
                    size = m.stat().st_size
                    if size < 1024:
                        lines.append(f"  {rel}  ({size} B)")
                    elif size < 1024 * 1024:
                        lines.append(f"  {rel}  ({size/1024:.1f} KB)")
                    else:
                        lines.append(f"  {rel}  ({size/1024/1024:.1f} MB)")
                except (OSError, ValueError):
                    lines.append(f"  {m}")
            total = len(list(path.rglob(pattern)))
            if total > 50:
                lines.append(f"\n  ... and {total - 50} more matches")
            return ToolResult(content="\n".join(lines))
        except Exception as exc:
            return ToolResult(content=f"Search error: {exc}", is_error=True)

    return ToolDefinition(
        name="search_files",
        description="按文件名模式搜索文件。使用glob语法，如 '*.py' 搜索Python文件，'*.csv' 搜索CSV文件。递归搜索子目录。",
        parameters={
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "文件名匹配模式（glob语法），如 '*.py', '*.csv', 'report*'",
                },
                "directory": {
                    "type": "string",
                    "description": "搜索起始目录。默认为当前目录。支持 ~ 表示用户主目录。",
                },
            },
            "required": ["pattern"],
        },
        execute=execute,
    )


def create_default_registry(
    *,
    skill_manager: SkillManager,
    soul_manager: SoulManager | None = None,
    enabled_tools: list[str] | None = None,
    allow_shell: bool = False,
    python_exec_enabled: bool = True,
    browser_enabled: bool = False,
) -> ToolRegistry:
    """Create a ToolRegistry with the standard built-in tools."""
    registry = ToolRegistry()

    all_tools: dict[str, ToolDefinition] = {
        "get_datetime": _make_get_datetime(),
        "calculate": _make_calculate(),
        "web_search": _make_web_search(),
        "read_file": _make_read_file(),
        "write_file": _make_write_file(),
        "run_command": _make_run_command(allowed=allow_shell),
        "run_python": _make_run_python(enabled=python_exec_enabled),
        "list_directory": _make_list_directory(),
        "search_files": _make_search_files(),
        "list_skills": _make_list_skills(skill_manager),
        "activate_skill": _make_activate_skill(skill_manager),
        "deactivate_skill": _make_deactivate_skill(skill_manager),
    }

    # Soul/memory tools (require SoulManager)
    if soul_manager is not None:
        all_tools["recall_memory"] = _make_recall_memory(soul_manager)
        all_tools["update_user_profile"] = _make_update_user_profile(soul_manager)
        all_tools["save_note"] = _make_save_note(soul_manager)

    # Browser tool (optional, requires browser-use)
    if browser_enabled:
        try:
            from app.browser import make_browse_web_tool
            all_tools["browse_web"] = make_browse_web_tool()
            logger.info("Browser tool enabled")
        except ImportError:
            logger.warning("Browser tool requested but browser-use not installed. Run: pip install browser-use")

    if enabled_tools is None:
        # Default: everything except shell and browser for safety
        enabled_tools = [
            "get_datetime", "calculate", "web_search", "read_file",
            "run_python", "list_directory", "search_files",
            "list_skills", "activate_skill", "deactivate_skill",
            "recall_memory", "update_user_profile", "save_note",
        ]
        if browser_enabled and "browse_web" in all_tools:
            enabled_tools.append("browse_web")

    for name in enabled_tools:
        if name in all_tools:
            registry.register(all_tools[name])
        else:
            logger.warning("Unknown tool in TOOLS_ENABLED: %s", name)

    logger.info("Tool registry created with %d tools: %s", len(registry.tool_names), registry.tool_names)
    return registry
