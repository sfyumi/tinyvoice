"""Browser automation tool using browser-use library for voice-driven web browsing."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger("tinyagent.browser")


def make_browse_web_tool() -> Any:
    """Create the browse_web tool definition. Import browser-use at call time."""
    from app.tools import ToolDefinition, ToolResult

    async def execute(args: dict[str, Any]) -> ToolResult:
        task = args.get("task", "")
        if not task:
            return ToolResult(content="No browsing task provided.", is_error=True)

        try:
            from browser_use import Agent as BrowserAgent
            from langchain_openai import ChatOpenAI

            from app.config import get_settings

            settings = get_settings()
            if not settings.llm_configured():
                return ToolResult(
                    content="Browser tool requires LLM to be configured.",
                    is_error=True,
                )

            # Create LLM for browser-use (reuse our config)
            llm = ChatOpenAI(
                base_url=settings.llm_base_url,
                api_key=settings.llm_api_key,
                model=settings.llm_model,
            )

            agent = BrowserAgent(
                task=task,
                llm=llm,
            )

            # Run with timeout
            result = await asyncio.wait_for(agent.run(), timeout=120)

            # Extract the final result text
            if result and hasattr(result, "final_result"):
                text = str(result.final_result())
            elif result:
                text = str(result)
            else:
                text = "Browser task completed but returned no content."

            # Truncate very long results
            if len(text) > 4000:
                text = text[:4000] + "\n...(内容过长，已截断)"

            return ToolResult(content=text)

        except ImportError as exc:
            return ToolResult(
                content=f"Browser dependencies not installed. Run: pip install browser-use langchain-openai && playwright install chromium. Error: {exc}",
                is_error=True,
            )
        except asyncio.TimeoutError:
            return ToolResult(content="Browser task timed out (120s limit).", is_error=True)
        except Exception as exc:
            logger.exception("Browser task failed")
            return ToolResult(content=f"Browser error: {type(exc).__name__}: {exc}", is_error=True)

    return ToolDefinition(
        name="browse_web",
        description="用浏览器执行网页任务。可以打开网页、点击按钮、填写表单、提取信息等。输入一个自然语言描述的任务，浏览器会自动完成。适合需要实际访问网页的任务。120秒超时。",
        parameters={
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "浏览器要执行的任务描述，如 '打开百度搜索明天北京天气，告诉我结果' 或 'go to github.com and find the trending repositories'",
                },
            },
            "required": ["task"],
        },
        execute=execute,
    )
