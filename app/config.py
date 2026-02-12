"""Application settings loaded from `.env` via Pydantic."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    soniox_api_key: str = Field(default="", alias="SONIOX_API_KEY")
    soniox_ws_url: str = Field(
        default="wss://stt-rt.soniox.com/transcribe-websocket", alias="SONIOX_WS_URL"
    )

    dashscope_api_key: str = Field(default="", alias="DASHSCOPE_API_KEY")
    tts_voice_id: str = Field(
        default="qwen-tts-vc-guanyu-voice-20260202204902188-2ed0", alias="TTS_VOICE_ID"
    )
    tts_model: str = Field(
        default="qwen3-tts-vc-realtime-2026-01-15", alias="TTS_MODEL"
    )
    tts_ws_url: str = Field(
        default="wss://dashscope-intl.aliyuncs.com/api-ws/v1/realtime",
        alias="TTS_WS_URL",
    )

    llm_base_url: str = Field(default="", alias="LLM_BASE_URL")
    llm_api_key: str = Field(default="", alias="LLM_API_KEY")
    llm_model: str = Field(default="", alias="LLM_MODEL")

    # Agent / Skills / Tools settings
    skills_dirs: str = Field(default="skills", alias="SKILLS_DIRS")
    tools_enabled: str = Field(
        default="get_datetime,calculate,web_search,read_file,run_python,list_directory,search_files,list_skills,activate_skill,deactivate_skill",
        alias="TOOLS_ENABLED",
    )
    agent_max_tool_rounds: int = Field(default=5, alias="AGENT_MAX_TOOL_ROUNDS")
    tools_allow_shell: bool = Field(default=False, alias="TOOLS_ALLOW_SHELL")
    python_exec_enabled: bool = Field(default=True, alias="PYTHON_EXEC_ENABLED")
    browser_enabled: bool = Field(default=False, alias="BROWSER_ENABLED")

    def llm_configured(self) -> bool:
        return bool(self.llm_base_url and self.llm_api_key and self.llm_model)

    def asr_configured(self) -> bool:
        return bool(self.soniox_api_key)

    def tts_configured(self) -> bool:
        return bool(self.dashscope_api_key and self.tts_voice_id)

    def get_skills_dirs(self) -> list[str]:
        """Parse comma-separated skills directories."""
        return [d.strip() for d in self.skills_dirs.split(",") if d.strip()]

    def get_enabled_tools(self) -> list[str]:
        """Parse comma-separated enabled tools list."""
        return [t.strip() for t in self.tools_enabled.split(",") if t.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
