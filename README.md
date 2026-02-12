# TinyAgent

**Voice-first AI agent with soul, skills, and tools.**

用语音驱动一个有灵魂、有记忆、能行动的智能体。

---

## What is this?

TinyAgent 是一个实时语音智能体。你用语音和它对话，它能：

- 执行 Python 代码，处理数据和文件
- 搜索互联网，回答实时问题
- 浏览网页，提取信息（可选）
- 探索文件系统，找到并读取文件
- 记住你是谁，记住你们聊过什么
- 根据不同场景切换专业技能

它不是一个"语音转文字然后调 ChatGPT"的壳。它有自己的灵魂（`SOUL.md`），了解你（`USER.md`），记得过去的对话（`MEMORY.md`），并且能自主决定调用哪些工具来完成你的请求。

## Core Design

```
    你说话                   它回答
      │                       ▲
      ▼                       │
   ┌─────┐               ┌──────┐
   │ ASR │               │ TTS  │
   └──┬──┘               └──┬───┘
      │                      │
      ▼                      │
   ┌─────────────────────────┴──┐
   │        Agent Brain          │
   │                             │
   │  Soul ← who I am           │
   │  User ← who you are        │
   │  LLM  ← thinks             │
   │  Tools ← acts (13 tools)   │
   │  Skills ← specializes      │
   └─────────────────────────────┘
```

详细架构见 [ARCHITECTURE.md](ARCHITECTURE.md)。

## Quick Start

```bash
# 1. 环境
python -m venv .venv && source .venv/bin/activate
pip install -i https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple -r requirements.txt

# 2. 配置
cp .env.example .env
# 编辑 .env，填入 API keys

# 3. 运行
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

打开 http://localhost:8000，点"开始会话"，说话。

## Make it yours

**改变它的性格** -- 编辑 `soul/SOUL.md`。这是它的灵魂，定义了说话风格、价值观和个性。

**让它了解你** -- 编辑 `soul/USER.md`，或者直接在对话中告诉它。它会自动记住。

**添加技能** -- 在 `skills/` 下创建一个目录，写一个 `SKILL.md`，遵循 [Agent Skills](https://agentskills.io) 标准。

## Built-in capabilities

**13 Tools:**
`run_python` `list_directory` `search_files` `read_file` `write_file` `web_search` `browse_web` `calculate` `get_datetime` `recall_memory` `update_user_profile` `save_note` `activate_skill`

**5 Skills:**
`assistant` `coder` `translator` `analyst` `planner`

**Voice:**
Soniox ASR (中英双语) + Qwen TTS (支持声音克隆) + 实时打断

## Requirements

- Python 3.11+
- [Soniox](https://soniox.com) API key (ASR)
- [DashScope](https://dashscope.aliyun.com) API key (TTS)
- Any OpenAI-compatible LLM API

## Inspired by

- [OpenClaw](https://github.com/openclaw) -- Agent Soul & User Memory
- [Anthropic Skills](https://github.com/anthropics/skills) -- Agent Skills standard
- [Pi](https://github.com/badlogic/pi-mono) -- Agent loop & tool architecture

## License

MIT
