# TinyAgent Architecture

## One sentence

**TinyAgent = Voice Interface + Agent Brain + Persistent Soul**

A real-time Chinese voice agent that hears you, thinks with tools, and speaks back -- while remembering who it is and who you are across sessions.

## Core Design: Three Layers

```
┌─────────────────────────────────────────────────┐
│                  Voice Layer                      │
│         ASR (Soniox) ◄──► TTS (Qwen)            │
│     16kHz PCM in         24kHz PCM out           │
├─────────────────────────────────────────────────┤
│                  Agent Brain                      │
│  ┌───────────┐  ┌──────────┐  ┌──────────────┐  │
│  │ Agent Loop │──│  Tools   │──│   Skills     │  │
│  │ (LLM +    │  │ 13 built │  │  5 loadable  │  │
│  │  tool call │  │  -in     │  │  SKILL.md    │  │
│  │  cycles)  │  │          │  │              │  │
│  └───────────┘  └──────────┘  └──────────────┘  │
├─────────────────────────────────────────────────┤
│               Persistent Soul                     │
│       SOUL.md        USER.md       MEMORY.md     │
│     (who I am)    (who you are)  (what we said)  │
└─────────────────────────────────────────────────┘
```

### Layer 1: Voice -- the interface

Real-time bidirectional voice over a single WebSocket. Browser captures mic audio, streams 16kHz PCM to server. Server sends back 24kHz TTS audio. All JSON control messages multiplexed on the same connection.

- **ASR**: Soniox Realtime STT with semantic endpoint detection
- **TTS**: Qwen DashScope Realtime with voice cloning support
- **Barge-in**: user can interrupt at any time; TTS cancels instantly

### Layer 2: Agent Brain -- the intelligence

When the user finishes a sentence, the Agent Brain takes over. It's not a simple "send to LLM, read back the response" -- it's a multi-turn execution loop:

```
User sentence
    │
    ▼
┌─ Agent Loop (max 5 rounds) ─────────────────┐
│                                               │
│   LLM decides: text response? or tool call?   │
│        │                    │                 │
│        ▼                    ▼                 │
│   [text tokens]      [tool_calls]             │
│        │                    │                 │
│        ▼                    ▼                 │
│     → TTS            Execute tools            │
│                             │                 │
│                             ▼                 │
│                    Feed results back to LLM    │
│                             │                 │
│                             └──→ next round    │
└───────────────────────────────────────────────┘
```

The LLM autonomously decides which tools to use, chains multiple steps, and only speaks when it has the final answer.

**13 built-in tools:**

| Tool | What it does |
|------|-------------|
| `run_python` | Execute arbitrary Python code |
| `list_directory` | Explore the file system |
| `search_files` | Find files by pattern |
| `read_file` / `write_file` | Read and write files |
| `web_search` | Search the internet (DuckDuckGo) |
| `browse_web` | Full browser automation (optional) |
| `calculate` | Math expressions |
| `get_datetime` | Current time/date |
| `recall_memory` | Search conversation history |
| `update_user_profile` | Learn about the user |
| `save_note` | Remember important facts |
| `activate_skill` / `list_skills` | Manage skills |

**5 built-in skills** (Agent Skills standard, SKILL.md):

| Skill | Purpose |
|-------|---------|
| `assistant` | Enhanced general conversation |
| `coder` | Code generation and explanation |
| `translator` | Multi-language translation |
| `analyst` | Data analysis and fact-checking |
| `planner` | Multi-step task decomposition |

### Layer 3: Persistent Soul -- the identity

Inspired by OpenClaw's identity architecture. Three markdown files that persist across sessions:

- **`soul/SOUL.md`** -- Defines who the agent IS. Personality, values, speaking style. Injected into every system prompt. Editable by the user.
- **`soul/USER.md`** -- What the agent knows about YOU. Updated automatically as the agent learns your name, preferences, interests.
- **`soul/MEMORY.md`** -- Conversation memory. Session summaries auto-appended. The agent can recall past conversations on demand.

The prompt hierarchy: `Soul → User → Agent Instructions → Active Skills → Tools`.

## State Machine

```
idle ──start_session──► listening
                           │
                      ASR endpoint
                           │
                           ▼
                       thinking ◄──────────────┐
                           │                    │
                     LLM responds               │
                      ┌────┴────┐               │
                      │         │               │
                      ▼         ▼               │
                  speaking   executing          │
                      │         │               │
                TTS done    tool result ─────────┘
                      │
                      ▼
                   listening
```

- **interrupt** works from `speaking` or `executing` → back to `listening`
- **stop_session** from any state → `idle`

## Project Structure

```
tinyagent/
├── app/                    # Backend (Python/FastAPI)
│   ├── main.py             #   WebSocket server + routing
│   ├── pipeline.py         #   Session orchestrator + state machine
│   ├── agent.py            #   Agent loop (LLM + tool cycles)
│   ├── llm.py              #   LLM client with tool calling
│   ├── tools.py            #   Tool registry + 13 built-in tools
│   ├── skills.py           #   Skills engine (Agent Skills spec)
│   ├── memory.py           #   Soul & memory manager
│   ├── asr.py              #   Soniox ASR client
│   ├── tts.py              #   Qwen TTS client
│   ├── browser.py          #   Browser automation (optional)
│   └── config.py           #   Settings from .env
│
├── soul/                   # Persistent identity (editable)
│   ├── SOUL.md             #   Agent personality
│   ├── USER.md             #   User profile (auto-updated)
│   └── MEMORY.md           #   Conversation memory (auto-appended)
│
├── skills/                 # Loadable skills (Agent Skills standard)
│   ├── assistant/SKILL.md
│   ├── coder/SKILL.md
│   ├── translator/SKILL.md
│   ├── analyst/SKILL.md
│   └── planner/SKILL.md
│
├── static/                 # Frontend (vanilla JS)
│   ├── index.html
│   ├── app.js
│   └── style.css
│
└── refdoc/                 # Reference documentation
```

## Key Design Decisions

**Why voice-first, not text-first?**
Text agents are commodity. Voice changes the interaction model: hands-free, eyes-free, conversational pace. The constraint of speaking forces conciseness and clarity.

**Why Soul files instead of database?**
Markdown files are human-readable, git-trackable, and editable with any text editor. No database to manage. The user can open SOUL.md and change the agent's personality in 30 seconds.

**Why built-in tools instead of MCP/plugins?**
Each tool is 40-60 lines of Python, zero external dependencies (except optional browser-use). No process management, no protocol translation, no Node.js. When you need it, `run_python` can do anything Python can do.

**Why Skills as markdown, not code?**
Skills are LLM instructions, not executable code. They're safe, portable, and anyone can write one. The LLM's tool-calling ability provides the execution layer.

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Server | FastAPI + WebSocket |
| ASR | Soniox Realtime STT |
| LLM | Any OpenAI-compatible API |
| TTS | Qwen DashScope Realtime |
| Frontend | Vanilla JS + Tailwind |
| Transport | Single WebSocket (JSON + binary PCM) |
| Identity | Markdown files (SOUL.md / USER.md / MEMORY.md) |
| Skills | Agent Skills standard (SKILL.md) |
| Tools | Python stdlib (+ optional browser-use) |
