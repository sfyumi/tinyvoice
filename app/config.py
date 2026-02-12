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
        default=(
            "get_datetime,calculate,web_search,fetch_webpage,read_file,run_python,"
            "list_directory,search_files,list_skills,activate_skill,deactivate_skill,"
            "recall_memory,update_user_profile,save_note,add_todo,list_todos,add_reading_item,browse_web"
        ),
        alias="TOOLS_ENABLED",
    )
    agent_max_tool_rounds: int = Field(default=5, alias="AGENT_MAX_TOOL_ROUNDS")
    tools_allow_shell: bool = Field(default=False, alias="TOOLS_ALLOW_SHELL")
    python_exec_enabled: bool = Field(default=True, alias="PYTHON_EXEC_ENABLED")
    browser_enabled: bool = Field(default=False, alias="BROWSER_ENABLED")
    web_search_content_budget: int = Field(default=6000, alias="WEB_SEARCH_CONTENT_BUDGET")
    web_search_fetch_top_k: int = Field(default=3, alias="WEB_SEARCH_FETCH_TOP_K")
    ui_tool_result_max_chars: int = Field(default=2000, alias="UI_TOOL_RESULT_MAX_CHARS")
    google_project: str = Field(default="", alias="GOOGLE_PROJECT")
    google_location: str = Field(default="global", alias="GOOGLE_LOCATION")
    google_credentials_path: str = Field(default="", alias="GOOGLE_CREDENTIALS_PATH")
    web_search_gemini_model: str = Field(default="gemini-2.5-flash", alias="WEB_SEARCH_GEMINI_MODEL")
    web_search_synthesis_temperature: float = Field(default=0.3, alias="WEB_SEARCH_SYNTHESIS_TEMPERATURE")
    web_search_synthesis_max_tokens: int = Field(default=1024, alias="WEB_SEARCH_SYNTHESIS_MAX_TOKENS")

    def llm_configured(self) -> bool:
        return bool(self.llm_base_url and self.llm_api_key and self.llm_model)

    def asr_configured(self) -> bool:
        return bool(self.soniox_api_key)

    def tts_configured(self) -> bool:
        return bool(self.dashscope_api_key and self.tts_voice_id)

    @staticmethod
    def _parse_csv(value: str) -> list[str]:
        return [item.strip() for item in value.split(",") if item.strip()]

    def get_skills_dirs(self) -> list[str]:
        """Parse comma-separated skills directories."""
        return self._parse_csv(self.skills_dirs)

    def get_enabled_tools(self) -> list[str]:
        """Parse comma-separated enabled tools list."""
        return self._parse_csv(self.tools_enabled)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
