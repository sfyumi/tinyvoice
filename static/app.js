/* TinyAgent - Frontend with Soul + Skills + Tools support */

const chatEl = document.getElementById("chat");
const startBtn = document.getElementById("startBtn");
const stopBtn = document.getElementById("stopBtn");
const interruptBtn = document.getElementById("interruptBtn");
const stateDot = document.getElementById("stateDot");
const stateText = document.getElementById("stateText");
const levelBar = document.getElementById("levelBar");

const mAsrEndpoint = document.getElementById("mAsrEndpoint");
const mLlmFirst = document.getElementById("mLlmFirst");
const mTtsFirst = document.getElementById("mTtsFirst");
const mE2E = document.getElementById("mE2E");
const stageListening = document.getElementById("stageListening");
const stageThinking = document.getElementById("stageThinking");
const stageSpeaking = document.getElementById("stageSpeaking");
const stageListeningLabel = document.getElementById("stageListeningLabel");
const stageThinkingLabel = document.getElementById("stageThinkingLabel");
const stageSpeakingLabel = document.getElementById("stageSpeakingLabel");

const liveLlmTokens = document.getElementById("liveLlmTokens");
const liveLlmRate = document.getElementById("liveLlmRate");
const liveTtsChunks = document.getElementById("liveTtsChunks");
const liveTtsDuration = document.getElementById("liveTtsDuration");
const liveListeningDuration = document.getElementById("liveListeningDuration");
const liveToolCalls = document.getElementById("liveToolCalls");

const connWs = document.getElementById("connWs");
const connAsr = document.getElementById("connAsr");
const connLlm = document.getElementById("connLlm");
const connTts = document.getElementById("connTts");
const wsUptime = document.getElementById("wsUptime");

const sessionDuration = document.getElementById("sessionDuration");
const sessionTurns = document.getElementById("sessionTurns");
const sessionAvgE2E = document.getElementById("sessionAvgE2E");
const sessionTokens = document.getElementById("sessionTokens");
const sessionTtsDuration = document.getElementById("sessionTtsDuration");
const sessionToolCalls = document.getElementById("sessionToolCalls");

const cfgLlmModel = document.getElementById("cfgLlmModel");
const cfgTtsModel = document.getElementById("cfgTtsModel");
const cfgTtsVoice = document.getElementById("cfgTtsVoice");
const cfgLlmBaseUrl = document.getElementById("cfgLlmBaseUrl");
const cfgSonioxWsUrl = document.getElementById("cfgSonioxWsUrl");
const cfgTtsWsUrl = document.getElementById("cfgTtsWsUrl");
const cfgAsrReady = document.getElementById("cfgAsrReady");
const cfgLlmReady = document.getElementById("cfgLlmReady");
const cfgTtsReady = document.getElementById("cfgTtsReady");
const cfgTools = document.getElementById("cfgTools");

const skillsList = document.getElementById("skillsList");
const skillCount = document.getElementById("skillCount");
const toolLog = document.getElementById("toolLog");
const soulStatus = document.getElementById("soulStatus");
const soulLoaded = document.getElementById("soulLoaded");
const userLoaded = document.getElementById("userLoaded");
const memoryEntries = document.getElementById("memoryEntries");

let ws = null;
let audioCtx = null;
let micStream = null;
let captureNode = null;
let playbackNode = null;
let sourceNode = null;

let pendingUserBubble = null;
let pendingAgentBubble = null;
let sentAudioChunks = 0;
let recvAudioChunks = 0;
let lastFinalAsrText = "";
let lastFinalAsrAt = 0;
let activeTurnId = null;

let wsConnectedAt = 0;
let sessionStartedAt = 0;
let listeningStartedAt = 0;
let tickTimer = null;
let liveTurn = { llmTokens: 0, llmRate: 0, ttsChunks: 0, ttsDurationMs: 0, listeningMs: 0, toolCalls: 0 };
let sessionStats = { turns: 0, sumE2E: 0, totalTokens: 0, totalTtsMs: 0, totalToolCalls: 0 };
let currentSkills = [];
let toolLogEntries = [];
let activeToolBubbles = {};

// ---- Bubble helpers ----
function addBubble(role, text) {
  const div = document.createElement("div");
  div.className = `bubble ${role}`;
  div.textContent = text;
  chatEl.appendChild(div);
  chatEl.scrollTop = chatEl.scrollHeight;
  return div;
}

function addToolBubble(toolCallId, name, args) {
  const div = document.createElement("div");
  div.className = "bubble tool";
  const argsStr = typeof args === "object" ? Object.entries(args).map(([k, v]) => `${k}: ${typeof v === "string" ? v : JSON.stringify(v)}`).join(", ") : String(args);
  div.innerHTML = `
    <div class="tool-header">
      <div class="tool-spinner"></div>
      <span>${name}</span>
      <span class="tool-time">执行中...</span>
    </div>
    <div class="tool-args" style="font-size:11px;color:#64748b;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${argsStr}</div>
  `;
  chatEl.appendChild(div);
  chatEl.scrollTop = chatEl.scrollHeight;
  activeToolBubbles[toolCallId] = div;
  return div;
}

function updateToolBubble(toolCallId, content, isError, elapsedMs) {
  const div = activeToolBubbles[toolCallId];
  if (!div) return;
  // Remove spinner
  const spinner = div.querySelector(".tool-spinner");
  if (spinner) spinner.remove();
  // Update time
  const timeEl = div.querySelector(".tool-time");
  if (timeEl) timeEl.textContent = `${elapsedMs}ms`;
  // Add result
  const resultDiv = document.createElement("div");
  resultDiv.className = `tool-result ${isError ? "error" : ""}`;
  const maxLen = 150;
  const short = content.length > maxLen ? content.slice(0, maxLen) + "..." : content;
  resultDiv.textContent = isError ? `错误: ${short}` : short;
  div.appendChild(resultDiv);
  // Mark done
  const header = div.querySelector(".tool-header span:not(.tool-time)");
  if (header && !isError) header.classList.add("tool-done");
  chatEl.scrollTop = chatEl.scrollHeight;
  delete activeToolBubbles[toolCallId];
}

function addSkillChangeBubble(action, name) {
  const text = action === "activate_skill" || action === "activated"
    ? `已激活技能: ${name}`
    : `已停用技能: ${name}`;
  const div = document.createElement("div");
  div.className = "bubble skill-change";
  div.textContent = text;
  chatEl.appendChild(div);
  chatEl.scrollTop = chatEl.scrollHeight;
}

// ---- Format helpers ----
function formatMs(ms) {
  if (typeof ms !== "number" || Number.isNaN(ms)) return "-";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(2)} s`;
}

function formatDuration(ms) {
  const sec = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

function setMetricChip(el, ms) {
  el.textContent = formatMs(ms);
  el.classList.remove("lat-good", "lat-mid", "lat-bad", "lat-unknown");
  if (typeof ms !== "number") {
    el.classList.add("lat-unknown");
    return;
  }
  if (ms < 500) el.classList.add("lat-good");
  else if (ms <= 1000) el.classList.add("lat-mid");
  else el.classList.add("lat-bad");
}

function setConnBadge(el, status, detail = "") {
  el.classList.remove("unknown", "connected", "disconnected", "error", "idle");
  el.classList.add(status || "unknown");
  const maxLen = 48;
  const shortDetail =
    detail && detail.length > maxLen ? `${detail.slice(0, maxLen - 1)}…` : detail;
  el.textContent = shortDetail ? `${status}: ${shortDetail}` : status || "unknown";
}

function maskUrl(url) {
  if (!url || typeof url !== "string") return "-";
  try {
    const u = new URL(url);
    const host = u.hostname || "unknown";
    const path = u.pathname && u.pathname !== "/" ? u.pathname : "";
    return `${u.protocol}//${host}${path}`;
  } catch {
    return url;
  }
}

// ---- Stage Bar ----
function renderStageBar(listeningMs, thinkingMs, speakingMs) {
  const l = typeof listeningMs === "number" ? Math.max(0, listeningMs) : 0;
  const t = typeof thinkingMs === "number" ? Math.max(0, thinkingMs) : 0;
  const s = typeof speakingMs === "number" ? Math.max(0, speakingMs) : 0;
  const total = l + t + s;

  if (total <= 0) {
    stageListening.style.width = "0%";
    stageThinking.style.width = "0%";
    stageSpeaking.style.width = "0%";
    stageListeningLabel.textContent = "L: -";
    stageThinkingLabel.textContent = "T: -";
    stageSpeakingLabel.textContent = "S: -";
    return;
  }

  stageListening.style.width = `${(l / total) * 100}%`;
  stageThinking.style.width = `${(t / total) * 100}%`;
  stageSpeaking.style.width = `${(s / total) * 100}%`;
  stageListeningLabel.textContent = `L: ${formatMs(l)}`;
  stageThinkingLabel.textContent = `T: ${formatMs(t)}`;
  stageSpeakingLabel.textContent = `S: ${formatMs(s)}`;
}

// ---- Live Turn & Session Stats ----
function renderLiveTurn() {
  liveLlmTokens.textContent = String(liveTurn.llmTokens);
  liveLlmRate.textContent = `${liveTurn.llmRate.toFixed(2)} tok/s`;
  liveTtsChunks.textContent = String(liveTurn.ttsChunks);
  liveTtsDuration.textContent = formatMs(liveTurn.ttsDurationMs);
  liveListeningDuration.textContent = formatMs(liveTurn.listeningMs);
  liveToolCalls.textContent = String(liveTurn.toolCalls);
}

function renderSessionStats() {
  sessionTurns.textContent = String(sessionStats.turns);
  sessionTokens.textContent = String(sessionStats.totalTokens);
  sessionTtsDuration.textContent = formatMs(sessionStats.totalTtsMs);
  sessionToolCalls.textContent = String(sessionStats.totalToolCalls);
  if (sessionStats.turns > 0) {
    sessionAvgE2E.textContent = formatMs(sessionStats.sumE2E / sessionStats.turns);
  } else {
    sessionAvgE2E.textContent = "-";
  }
  if (sessionStartedAt > 0) {
    sessionDuration.textContent = formatDuration(Date.now() - sessionStartedAt);
  } else {
    sessionDuration.textContent = "0s";
  }
  if (wsConnectedAt > 0) {
    wsUptime.textContent = formatDuration(Date.now() - wsConnectedAt);
  } else {
    wsUptime.textContent = "0s";
  }
}

function startTicker() {
  if (tickTimer) return;
  tickTimer = setInterval(() => {
    if (listeningStartedAt > 0 && stateText.textContent === "listening") {
      liveTurn.listeningMs = Date.now() - listeningStartedAt;
      renderLiveTurn();
    }
    renderSessionStats();
  }, 500);
}

function resetLiveTurn() {
  liveTurn = { llmTokens: 0, llmRate: 0, ttsChunks: 0, ttsDurationMs: 0, listeningMs: 0, toolCalls: 0 };
  renderLiveTurn();
}

function updateState(state) {
  stateText.textContent = state;
  stateDot.className = `state-dot ${state}`;
  if (state === "listening") {
    listeningStartedAt = Date.now();
  }
  if (state === "thinking") {
    resetLiveTurn();
  }
}

// ---- Skills Panel ----
function renderSkills(skills) {
  currentSkills = skills || [];
  skillCount.textContent = `${currentSkills.length} 可用`;
  if (currentSkills.length === 0) {
    skillsList.innerHTML = '<div class="text-xs text-slate-400">没有可用技能</div>';
    return;
  }
  skillsList.innerHTML = "";
  for (const s of currentSkills) {
    const item = document.createElement("div");
    item.className = `skill-item ${s.active ? "active" : ""}`;
    item.innerHTML = `
      <div style="flex:1;min-width:0;">
        <div class="skill-name">${s.name}</div>
        <div class="skill-desc">${s.description}</div>
      </div>
      <div class="skill-toggle"></div>
    `;
    item.addEventListener("click", () => {
      if (!ws || ws.readyState !== WebSocket.OPEN) return;
      const action = s.active ? "deactivate_skill" : "activate_skill";
      ws.send(JSON.stringify({ type: action, name: s.name }));
    });
    skillsList.appendChild(item);
  }
}

// ---- Soul Status ----
function renderSoulInfo(soul) {
  if (!soul) return;
  soulLoaded.textContent = soul.soul_loaded ? `已加载 (${soul.soul_chars} 字)` : "未找到";
  soulLoaded.style.color = soul.soul_loaded ? "#059669" : "#94a3b8";
  userLoaded.textContent = soul.user_loaded ? `已加载 (${soul.user_chars} 字)` : "未找到";
  userLoaded.style.color = soul.user_loaded ? "#059669" : "#94a3b8";
  memoryEntries.textContent = String(soul.memory_entries);
  const parts = [];
  if (soul.soul_loaded) parts.push("Soul");
  if (soul.user_loaded) parts.push("User");
  if (soul.memory_entries > 0) parts.push(`${soul.memory_entries} 记忆`);
  soulStatus.textContent = parts.length > 0 ? parts.join(" + ") : "未配置";
}

// ---- Tool Log ----
function addToolLogEntry(name, isError, content, elapsedMs) {
  if (toolLogEntries.length === 0) {
    toolLog.innerHTML = "";
  }
  const entry = { name, isError, content, elapsedMs, time: new Date() };
  toolLogEntries.push(entry);
  if (toolLogEntries.length > 20) toolLogEntries.shift();

  const div = document.createElement("div");
  div.className = `tool-log-entry ${isError ? "error" : ""}`;
  const maxLen = 60;
  const short = content.length > maxLen ? content.slice(0, maxLen) + "..." : content;
  div.innerHTML = `
    <div class="tool-log-body">
      <span class="tool-log-name">${name}</span>
      <span style="color:#94a3b8;margin-left:4px;">${elapsedMs}ms</span>
      <div class="tool-log-content">${short}</div>
    </div>
  `;
  toolLog.appendChild(div);
  toolLog.scrollTop = toolLog.scrollHeight;
}

// ---- Audio ----
function pcm16ToFloat32(int16Array) {
  const out = new Float32Array(int16Array.length);
  for (let i = 0; i < int16Array.length; i += 1) {
    out[i] = Math.max(-1, Math.min(1, int16Array[i] / 32768));
  }
  return out;
}

function resampleLinear(input, inRate, outRate) {
  if (inRate === outRate) return input;
  const outLen = Math.max(1, Math.round((input.length * outRate) / inRate));
  const out = new Float32Array(outLen);
  const scale = (input.length - 1) / Math.max(1, outLen - 1);
  for (let i = 0; i < outLen; i += 1) {
    const x = i * scale;
    const x0 = Math.floor(x);
    const x1 = Math.min(input.length - 1, x0 + 1);
    const t = x - x0;
    out[i] = input[x0] * (1 - t) + input[x1] * t;
  }
  return out;
}

function createCaptureWorkletURL() {
  const code = `
class CaptureProcessor extends AudioWorkletProcessor {
  process(inputs) {
    const input = inputs[0];
    if (!input || !input[0]) return true;
    const channel = input[0];
    let sumSq = 0;
    for (let i = 0; i < channel.length; i++) {
      sumSq += channel[i] * channel[i];
    }
    const rms = Math.sqrt(sumSq / Math.max(1, channel.length));
    this.port.postMessage({ type: "level", value: rms });

    const targetRate = 16000;
    const ratio = sampleRate / targetRate;
    const outLen = Math.max(1, Math.floor(channel.length / ratio));
    const out = new Int16Array(outLen);
    let sourceIndex = 0;
    for (let i = 0; i < outLen; i++) {
      const idx = Math.floor(sourceIndex);
      const s = Math.max(-1, Math.min(1, channel[idx] || 0));
      out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
      sourceIndex += ratio;
    }
    this.port.postMessage(out.buffer, [out.buffer]);
    return true;
  }
}
registerProcessor("capture-processor", CaptureProcessor);
`;
  return URL.createObjectURL(new Blob([code], { type: "application/javascript" }));
}

function createPlaybackWorkletURL() {
  const code = `
class PlaybackProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.queue = [];
    this.current = null;
    this.offset = 0;
    this.port.onmessage = (event) => {
      const arr = event.data;
      if (arr && arr.length) {
        this.queue.push(arr);
      }
    };
  }

  process(inputs, outputs) {
    const output = outputs[0];
    const left = output[0];
    const right = output[1] || left;
    for (let i = 0; i < left.length; i++) {
      if (!this.current || this.offset >= this.current.length) {
        this.current = this.queue.shift() || null;
        this.offset = 0;
      }
      const sample = this.current ? this.current[this.offset++] : 0;
      left[i] = sample;
      right[i] = sample;
    }
    return true;
  }
}
registerProcessor("playback-processor", PlaybackProcessor);
`;
  return URL.createObjectURL(new Blob([code], { type: "application/javascript" }));
}

async function initAudio() {
  if (audioCtx) return;
  audioCtx = new AudioContext({ latencyHint: "interactive" });

  const captureURL = createCaptureWorkletURL();
  const playbackURL = createPlaybackWorkletURL();
  await audioCtx.audioWorklet.addModule(captureURL);
  await audioCtx.audioWorklet.addModule(playbackURL);

  playbackNode = new AudioWorkletNode(audioCtx, "playback-processor", {
    numberOfInputs: 0,
    numberOfOutputs: 1,
    outputChannelCount: [2],
  });
  playbackNode.connect(audioCtx.destination);

  micStream = await navigator.mediaDevices.getUserMedia({
    audio: {
      channelCount: 1,
      noiseSuppression: true,
      echoCancellation: true,
      autoGainControl: true,
    },
    video: false,
  });
  sourceNode = audioCtx.createMediaStreamSource(micStream);
  captureNode = new AudioWorkletNode(audioCtx, "capture-processor", {
    numberOfInputs: 1,
    numberOfOutputs: 0,
  });
  sourceNode.connect(captureNode);

  captureNode.port.onmessage = (event) => {
    const data = event.data;
    if (data && data.type === "level") {
      const width = Math.min(100, Math.floor(data.value * 280));
      levelBar.style.width = `${width}%`;
      return;
    }
    if (ws && ws.readyState === WebSocket.OPEN && data instanceof ArrayBuffer) {
      sentAudioChunks += 1;
      if (sentAudioChunks % 50 === 0) {
        console.info("[tinyagent] sent mic audio chunks:", sentAudioChunks);
      }
      ws.send(data);
    }
  };
}

// ---- Server message handler ----
function handleServerMessage(msg) {
  if (msg.type === "state") {
    updateState(msg.state);
    if (msg.state !== "speaking") pendingAgentBubble = null;
    if (msg.state !== "listening") pendingUserBubble = null;
    if (msg.state === "idle") {
      lastFinalAsrText = "";
      lastFinalAsrAt = 0;
      activeTurnId = null;
      listeningStartedAt = 0;
      resetLiveTurn();
    }
    return;
  }

  if (msg.type === "session_info") {
    cfgLlmModel.textContent = msg.llm_model || "-";
    cfgTtsModel.textContent = msg.tts_model || "-";
    cfgTtsVoice.textContent = msg.tts_voice || "-";
    cfgLlmBaseUrl.textContent = maskUrl(msg.llm_base_url);
    cfgSonioxWsUrl.textContent = maskUrl(msg.soniox_ws_url);
    cfgTtsWsUrl.textContent = maskUrl(msg.tts_ws_url);
    cfgAsrReady.textContent = msg.asr_configured ? "ready" : "missing";
    cfgLlmReady.textContent = msg.llm_configured ? "ready" : "missing";
    cfgTtsReady.textContent = msg.tts_configured ? "ready" : "missing";
    if (msg.tools) {
      cfgTools.textContent = msg.tools.join(", ");
    }
    if (msg.skills) {
      renderSkills(msg.skills);
    }
    if (msg.soul) {
      renderSoulInfo(msg.soul);
    }
    return;
  }

  if (msg.type === "connection_status") {
    if (msg.service === "asr") setConnBadge(connAsr, msg.status, msg.detail || "");
    if (msg.service === "llm") setConnBadge(connLlm, msg.status, msg.detail || "");
    if (msg.service === "tts") setConnBadge(connTts, msg.status, msg.detail || "");
    return;
  }

  // Skills list update
  if (msg.type === "skills_list") {
    renderSkills(msg.skills);
    return;
  }

  // Skill change event
  if (msg.type === "skill") {
    if (msg.skills) renderSkills(msg.skills);
    if (msg.event && msg.name) {
      addSkillChangeBubble(msg.event, msg.name);
    }
    return;
  }

  // Tool events
  if (msg.type === "tool") {
    if (msg.event === "start") {
      liveTurn.toolCalls += 1;
      renderLiveTurn();
      addToolBubble(msg.turn_id + "_" + msg.name, msg.name, msg.arguments || {});
    }
    if (msg.event === "result") {
      updateToolBubble(
        msg.turn_id + "_" + msg.name,
        msg.content || "",
        msg.is_error || false,
        msg.elapsed_ms || 0
      );
      addToolLogEntry(msg.name, msg.is_error, msg.content || "", msg.elapsed_ms || 0);
    }
    return;
  }

  if (msg.type === "metrics") {
    setMetricChip(mAsrEndpoint, msg.listening_duration_ms);
    setMetricChip(mLlmFirst, msg.llm_first_token_ms);
    setMetricChip(mTtsFirst, msg.tts_first_audio_ms);
    setMetricChip(mE2E, msg.e2e_latency_ms);
    renderStageBar(msg.listening_duration_ms, msg.thinking_ms, msg.speaking_ms);

    liveTurn.ttsChunks = msg.tts_audio_chunks || 0;
    liveTurn.ttsDurationMs = msg.tts_est_duration_ms || 0;
    liveTurn.listeningMs = msg.listening_duration_ms || 0;
    if (typeof msg.llm_tokens === "number") liveTurn.llmTokens = msg.llm_tokens;
    if (typeof msg.llm_tok_per_sec === "number") liveTurn.llmRate = msg.llm_tok_per_sec;
    if (typeof msg.tool_calls === "number") liveTurn.toolCalls = msg.tool_calls;
    renderLiveTurn();

    sessionStats.turns += 1;
    sessionStats.totalTokens += msg.llm_tokens || 0;
    sessionStats.totalTtsMs += msg.tts_est_duration_ms || 0;
    sessionStats.totalToolCalls += msg.tool_calls || 0;
    if (typeof msg.e2e_latency_ms === "number") {
      sessionStats.sumE2E += msg.e2e_latency_ms;
    }
    renderSessionStats();
    return;
  }

  if (msg.type === "turn") {
    if (msg.event === "user_committed") {
      activeTurnId = msg.turn_id || null;
      if (!pendingUserBubble) {
        pendingUserBubble = addBubble("user", msg.text || "");
      } else {
        pendingUserBubble.textContent = msg.text || "";
      }
      if (activeTurnId) {
        pendingUserBubble.dataset.turnId = activeTurnId;
      }
      return;
    }
    if (msg.event === "finished") {
      if (!activeTurnId || msg.turn_id === activeTurnId) {
        activeTurnId = null;
        pendingAgentBubble = null;
        pendingUserBubble = null;
      }
      return;
    }
  }

  if (msg.type === "asr") {
    const text = typeof msg.text === "string" ? msg.text : "";
    if (!text.trim()) return;

    if (activeTurnId && msg.is_final) return;

    if (msg.is_final) {
      const now = Date.now();
      if (text === lastFinalAsrText && now - lastFinalAsrAt < 2500) {
        return;
      }
      lastFinalAsrText = text;
      lastFinalAsrAt = now;
    }

    if (!pendingUserBubble) {
      pendingUserBubble = addBubble("user", msg.text);
    } else {
      pendingUserBubble.textContent = msg.text;
    }
    return;
  }

  if (msg.type === "llm") {
    if (!msg.turn_id) return;
    if (activeTurnId && msg.turn_id !== activeTurnId) return;
    activeTurnId = msg.turn_id;

    if (typeof msg.token_index === "number") {
      liveTurn.llmTokens = msg.token_index;
      if (typeof msg.elapsed_ms === "number" && msg.elapsed_ms > 0) {
        liveTurn.llmRate = msg.token_index / (msg.elapsed_ms / 1000);
      }
      renderLiveTurn();
    }

    if (msg.done) {
      pendingAgentBubble = null;
      return;
    }
    if (!pendingAgentBubble || pendingAgentBubble.dataset.turnId !== activeTurnId) {
      pendingAgentBubble = addBubble("agent", msg.text);
      pendingAgentBubble.dataset.turnId = activeTurnId;
    } else {
      pendingAgentBubble.textContent += msg.text;
    }
    return;
  }

  if (msg.type === "error") {
    addBubble("system", `错误: ${msg.message}`);
  }
}

// ---- WebSocket ----
function connectWebSocket() {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${window.location.host}/ws`);
  ws.binaryType = "arraybuffer";

  ws.onopen = () => {
    wsConnectedAt = Date.now();
    setConnBadge(connWs, "connected");
    console.info("[tinyagent] ws open");
    addBubble("system", "WebSocket 已连接");
    startTicker();
  };
  ws.onclose = (event) => {
    wsConnectedAt = 0;
    setConnBadge(connWs, "disconnected");
    console.warn("[tinyagent] ws close", event.code, event.reason);
    addBubble("system", "WebSocket 已断开");
  };
  ws.onerror = (event) => {
    setConnBadge(connWs, "error");
    console.error("[tinyagent] ws error", event);
    addBubble("system", "WebSocket 错误");
  };
  ws.onmessage = (event) => {
    if (typeof event.data === "string") {
      try {
        handleServerMessage(JSON.parse(event.data));
      } catch (err) {
        addBubble("system", `服务端消息解析失败: ${String(err)}`);
      }
      return;
    }

    if (event.data instanceof ArrayBuffer && playbackNode && audioCtx) {
      recvAudioChunks += 1;
      if (recvAudioChunks % 20 === 0) {
        console.info("[tinyagent] recv tts audio chunks:", recvAudioChunks);
      }
      const pcm16 = new Int16Array(event.data);
      const float24k = pcm16ToFloat32(pcm16);
      const floatOut = resampleLinear(float24k, 24000, audioCtx.sampleRate);
      playbackNode.port.postMessage(floatOut);
    }
  };
}

// ---- Button handlers ----
startBtn.addEventListener("click", async () => {
  await initAudio();
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    connectWebSocket();
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "start_session" }));
    sessionStartedAt = Date.now();
    sessionStats = { turns: 0, sumE2E: 0, totalTokens: 0, totalTtsMs: 0, totalToolCalls: 0 };
    renderSessionStats();
    addBubble("system", "会话已开始 - TinyAgent (Soul + Skills + Tools)");
  }
});

stopBtn.addEventListener("click", () => {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "stop_session" }));
    addBubble("system", "会话已停止");
  }
});

interruptBtn.addEventListener("click", () => {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "interrupt" }));
    addBubble("system", "已发送打断请求");
  }
});

// ---- Init ----
setConnBadge(connWs, "unknown");
setConnBadge(connAsr, "unknown");
setConnBadge(connLlm, "unknown");
setConnBadge(connTts, "unknown");
renderStageBar(null, null, null);
renderLiveTurn();
renderSessionStats();
