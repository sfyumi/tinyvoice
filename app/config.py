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

    def llm_configured(self) -> bool:
        return bool(self.llm_base_url and self.llm_api_key and self.llm_model)

    def asr_configured(self) -> bool:
        return bool(self.soniox_api_key)

    def tts_configured(self) -> bool:
        return bool(self.dashscope_api_key and self.tts_voice_id)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
