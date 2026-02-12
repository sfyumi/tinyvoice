# TinyVoice

ASR + LLM + TTS 三段式实时语音 Agent：

- ASR: Soniox Realtime STT
- LLM: OpenAI 兼容接口（可自定义 `base_url/model/api_key`）
- TTS: Qwen TTS Realtime（DashScope，支持 voice clone）

## 目录

- `app/main.py`: FastAPI + WebSocket 入口
- `app/pipeline.py`: `idle -> listening -> thinking -> speaking` 状态机
- `app/asr.py`: Soniox 实时识别客户端
- `app/llm.py`: OpenAI 兼容流式 LLM 客户端
- `app/tts.py`: Qwen TTS Realtime 客户端
- `static/index.html`: Web UI
- `static/app.js`: AudioWorklet 采集/播放 + WebSocket 协议

## 架构文档

- 详细架构说明见 `ARCHITECTURE.md`

## 环境准备

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

填写 `.env`：

```env
SONIOX_API_KEY=...
SONIOX_WS_URL=wss://stt-rt.soniox.com/transcribe-websocket

DASHSCOPE_API_KEY=...
TTS_VOICE_ID=qwen-tts-vc-guanyu-voice-20260202204902188-2ed0
TTS_MODEL=qwen3-tts-vc-realtime-2026-01-15
TTS_WS_URL=wss://dashscope-intl.aliyuncs.com/api-ws/v1/realtime

LLM_BASE_URL=...
LLM_API_KEY=...
LLM_MODEL=...
```

## 运行

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

打开 `http://localhost:8000`。

## WebSocket 协议

浏览器 -> 服务端：

- 二进制帧：麦克风 PCM 音频
- JSON: `{"type":"start_session"}` / `{"type":"stop_session"}` / `{"type":"interrupt"}`

服务端 -> 浏览器：

- `{"type":"state","state":"listening|thinking|speaking|idle"}`
- `{"type":"turn","event":"user_committed","turn_id":"...","text":"..."}`
- `{"type":"turn","event":"finished","turn_id":"..."}`
- `{"type":"asr","text":"...","is_final":true|false}`
- `{"type":"llm","turn_id":"...","text":"...","done":true|false}`
- `{"type":"error","turn_id":"...","message":"..."}`（可能出现）
- 二进制帧：TTS PCM 音频（24kHz mono 16-bit）
