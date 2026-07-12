// Local AI status, setup, trace, fit analysis, and job chat (R3 split from app.js).
// Classic script, defer, after app.js; `state` is app.js's shared script-scope global.
(function () {
  const $ = (id) => document.getElementById(id);
  const api = (...args) => window.api(...args);
  const toast = (...args) => window.toast(...args);
  const setBusy = (...args) => window.setBusy(...args);
  const setNotice = (...args) => window.setNotice(...args);
  const escapeHtml = (value) => window.escapeHtml(value);
  const metric = (...args) => window.metric(...args);
  const renderBadge = (...args) => window.renderBadge(...args);
  const scorePill = (...args) => window.scorePill(...args);
  const renderState = (...args) => window.renderState(...args);

async function loadAiStatus() {
  try {
    const payload = await api("/api/ai-status");
    state.aiStatus = payload;
    renderState();
  } catch {
    state.aiStatus = { reachable: false };
    renderState();
  }
}

async function loadAiSetup() {
  try {
    const install = await api("/api/ollama-install");
    state.aiInstall = install;
    renderAiSetup();
  } catch (error) {
    setNotice("aiSetupNotice", `Could not query Ollama: ${error.message}`, true);
  }
}

const AI_TIER_LABELS = { L1: "Sentry (L1)", L2: "Worker (L2)", L3: "Architect (L3)" };

async function loadAiTrace() {
  const tiers = document.getElementById("aiTraceTiers");
  const recent = document.getElementById("aiTraceRecent");
  if (!tiers || !recent) return;
  try {
    const data = await api("/api/ai-trace");
    const byTier = (data && data.tiers) || {};
    const order = ["L1", "L2", "L3"];
    const tileHtml = order
      .filter((t) => byTier[t])
      .map((t) => metric(AI_TIER_LABELS[t], `${byTier[t].count}`,
        `${Math.round(byTier[t].success_rate * 100)}% ok · ${byTier[t].avg_ms} ms avg`))
      .join("");
    tiers.innerHTML = tileHtml || `<div class="muted">No AI tasks recorded yet — run an AI action to populate this.</div>`;
    const rows = (data && data.recent) || [];
    recent.innerHTML = rows.slice(0, 8).map((r) => `<li class="version-row">
      <span class="version-name">${escapeHtml((r.tier || "?") + " · " + (r.task || "task"))}</span>
      <span class="muted">${escapeHtml((r.model || "").replace(":latest", ""))}</span>
      <span class="version-size ${r.ok ? "" : "muted"}">${r.ok ? "ok" : "fail"} · ${r.elapsed_ms || 0} ms</span>
    </li>`).join("");
  } catch (error) {
    tiers.innerHTML = `<div class="muted">${escapeHtml(error.message)}</div>`;
  }
}

function renderAiSetup() {
  const info = state.aiInstall || {};
  const status = state.aiStatus || {};
  const tiles = [
    metric("Installed", info.installed ? "Yes" : "No", info.binary ? info.binary.split(/[\\/]/).pop() : ""),
    metric("Daemon", info.reachable ? "Reachable" : "Stopped"),
    metric("Heavy model", (status.selected_model || "—").replace(":latest", "")),
    metric("Fast model", (status.selected_fast_model || "—").replace(":latest", "")),
  ].join("");
  $("aiSetupMetrics").innerHTML = tiles;
  const btn = $("launchOllamaBtn");
  if (info.installed && info.reachable) {
    btn.disabled = true;
    btn.textContent = "Ollama running ✓";
  } else if (info.installed) {
    btn.disabled = false;
    btn.textContent = "Start Ollama";
  } else {
    btn.disabled = false;
    btn.textContent = "Install Ollama (opens site)";
  }
}

async function launchOllama() {
  const btn = $("launchOllamaBtn");
  const info = state.aiInstall || {};
  if (!info.installed) {
    window.open("https://ollama.com/download", "_blank", "noreferrer");
    setNotice("aiSetupNotice", "Opened the Ollama install page in a new tab.");
    return;
  }
  setBusy(btn, true);
  setNotice("aiSetupNotice", "");
  try {
    const result = await api("/api/ollama-launch", {});
    if (result.ok && result.running) {
      setNotice("aiSetupNotice", result.started ? "Ollama daemon started. AI features are ready." : "Ollama was already running.", false);
    } else {
      setNotice("aiSetupNotice", `Could not start Ollama: ${result.reason || "unknown"}`, true);
    }
  } catch (error) {
    setNotice("aiSetupNotice", error.message, true);
  } finally {
    setBusy(btn, false);
    await Promise.all([loadAiSetup(), loadAiStatus()]);
  }
}

async function pullFastModel() {
  const btn = $("pullFastModelBtn");
  if (state.ollamaPullWatcher) {
    window.clearInterval(state.ollamaPullWatcher);
    state.ollamaPullWatcher = null;
  }
  setBusy(btn, true);
  setNotice("aiSetupNotice", "Checking llama3.2:3b...");
  try {
    const result = await api("/api/ollama-pull", { model: "llama3.2:3b" });
    if (!result.ok) {
      setNotice("aiSetupNotice", `Pull failed: ${result.reason}`, true);
      return;
    }
    if (result.state === "success" || result.already_installed) {
      setNotice("aiSetupNotice", result.already_installed ? "Fast chat model is already installed." : "Fast chat model installed.");
      await Promise.all([loadAiSetup(), loadAiStatus()]);
      return;
    }
    setNotice("aiSetupNotice", "Downloading llama3.2:3b - this can take a few minutes.");
    // Poll progress until done
    const watcher = window.setInterval(async () => {
      try {
        const status = await api("/api/ollama-pull-status?model=llama3.2:3b");
        const s = status.status || {};
        if (s.state === "running") {
          setNotice("aiSetupNotice", `Downloading… ${s.last_line || ""}`);
        } else if (s.state === "success") {
          window.clearInterval(state.ollamaPullWatcher || watcher);
          state.ollamaPullWatcher = null;
          setNotice("aiSetupNotice", "Fast chat model installed.");
          setBusy(btn, false);
          await Promise.all([loadAiSetup(), loadAiStatus()]);
        } else if (s.state === "failed") {
          window.clearInterval(state.ollamaPullWatcher || watcher);
          state.ollamaPullWatcher = null;
          setNotice("aiSetupNotice", `Pull failed: ${s.error || "unknown"}`, true);
          setBusy(btn, false);
        }
      } catch (error) {
        window.clearInterval(state.ollamaPullWatcher || watcher);
        state.ollamaPullWatcher = null;
        setNotice("aiSetupNotice", error.message, true);
        setBusy(btn, false);
      }
    }, 2500);
    state.ollamaPullWatcher = watcher;
  } catch (error) {
    setNotice("aiSetupNotice", error.message, true);
    setBusy(btn, false);
  } finally {
    if (!state.ollamaPullWatcher) setBusy(btn, false);
  }
}

async function runAiAnalysis(jobId, button) {
  setBusy(button, true);
  try {
    const payload = await api("/api/ai-analyze", { job_id: jobId });
    showAiAnalysis(payload.analysis);
  } catch (error) {
    toast(error.message);
  } finally {
    setBusy(button, false);
  }
}

function showAiAnalysis(analysis) {
  const tone = analysis.verdict === "strong" ? "good" : analysis.verdict === "weak" ? "bad" : "warn";
  const strengths = (analysis.strengths || []).map((s) => `<li>${escapeHtml(s)}</li>`).join("") || "<li class='muted'>None.</li>";
  const gaps = (analysis.gaps || []).map((s) => `<li>${escapeHtml(s)}</li>`).join("") || "<li class='muted'>None.</li>";
  const emphasis = (analysis.suggested_emphasis || []).map((s) => `<li>${escapeHtml(s)}</li>`).join("") || "<li class='muted'>None.</li>";
  $("aiAnalysisBody").innerHTML = `
    <div class="detail-block">
      <div class="detail-row"><span>Verdict</span>${renderBadge(analysis.verdict, tone)}</div>
      <div class="detail-row"><span>AI score</span>${scorePill(analysis.score)}</div>
      <div class="detail-row"><span>Confidence</span><strong>${Math.round((analysis.confidence || 0) * 100)}%</strong></div>
    </div>
    <div class="detail-block">
      <h4>Summary</h4>
      <p>${escapeHtml(analysis.summary || "")}</p>
    </div>
    <div class="split" style="margin-top:0">
      <div class="detail-block"><h4>Strengths</h4><ul>${strengths}</ul></div>
      <div class="detail-block"><h4>Gaps</h4><ul>${gaps}</ul></div>
    </div>
    <div class="detail-block">
      <h4>Suggested emphasis</h4>
      <ul>${emphasis}</ul>
    </div>
  `;
  $("aiAnalysisModal").classList.remove("hidden");
}

function openChatModal(job) {
  state.chatJobId = job.id;
  state.chatHistory = [];
  $("aiChatTitle").textContent = `Chat: ${job.title}`.slice(0, 80);
  $("aiChatSubtitle").textContent = `${job.company || ""} ${job.location ? "· " + job.location : ""}`;
  $("aiChatStream").innerHTML = "";
  $("aiChatInput").value = "";
  if (job.ai_summary) {
    appendChatBubble("assistant", job.ai_summary);
  } else {
    appendChatBubble("assistant", "Ask anything: should I apply, what to emphasize in the CV, what gaps you see, how to write the opener…");
  }
  $("aiChatModal").classList.remove("hidden");
  $("aiChatInput").focus();
}

function appendChatBubble(role, text) {
  const el = document.createElement("div");
  el.className = `chat-bubble ${role}`;
  el.textContent = text;
  $("aiChatStream").appendChild(el);
  $("aiChatStream").scrollTop = $("aiChatStream").scrollHeight;
  return el;
}

async function sendChatMessage() {
  const text = $("aiChatInput").value.trim();
  if (!text || !state.chatJobId) return;
  appendChatBubble("user", text);
  state.chatHistory.push({ role: "user", content: text });
  $("aiChatInput").value = "";
  const thinking = appendChatBubble("thinking", "Thinking locally…");
  const button = $("aiChatSendBtn");
  setBusy(button, true);
  try {
    const payload = await api("/api/ai-chat", {
      job_id: state.chatJobId,
      question: text,
      history: state.chatHistory.slice(0, -1),
    });
    thinking.remove();
    if (payload.reply) {
      appendChatBubble("assistant", payload.reply);
      state.chatHistory.push({ role: "assistant", content: payload.reply });
    } else {
      appendChatBubble("assistant", "(AI returned no usable reply. Try rephrasing.)");
    }
  } catch (error) {
    thinking.remove();
    appendChatBubble("assistant", `Error: ${error.message}`);
  } finally {
    setBusy(button, false);
  }
}

  // ---- event bindings (moved from bindEvents) ----
  const launchBtn = $("launchOllamaBtn");
  if (launchBtn) launchBtn.addEventListener("click", launchOllama);
  const pullBtn = $("pullFastModelBtn");
  if (pullBtn) pullBtn.addEventListener("click", pullFastModel);
  const refreshAiBtn = $("refreshAiSetupBtn");
  if (refreshAiBtn) refreshAiBtn.addEventListener("click", () => { loadAiSetup(); loadAiStatus(); });
  const aiTraceRefreshBtn = $("aiTraceRefreshBtn");
  if (aiTraceRefreshBtn) aiTraceRefreshBtn.addEventListener("click", loadAiTrace);
  $("closeAiAnalysis").addEventListener("click", () => $("aiAnalysisModal").classList.add("hidden"));
  $("aiAnalysisModal").addEventListener("click", (event) => {
    if (event.target === $("aiAnalysisModal")) $("aiAnalysisModal").classList.add("hidden");
  });
  $("closeAiChat").addEventListener("click", () => $("aiChatModal").classList.add("hidden"));
  $("aiChatModal").addEventListener("click", (event) => {
    if (event.target === $("aiChatModal")) $("aiChatModal").classList.add("hidden");
  });
  $("aiChatSendBtn").addEventListener("click", sendChatMessage);
  $("aiChatInput").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      sendChatMessage();
    }
  });

  // ---- module init (moved from app.js tail) ----
  loadAiStatus();
  function _pollAiIfVisible() {
    if (document.visibilityState === "visible") loadAiStatus();
  }
  window.setInterval(_pollAiIfVisible, 120000);
  document.addEventListener("visibilitychange", _pollAiIfVisible);

  const loadStatus = loadAiStatus;
  const loadSetup = loadAiSetup;
  const loadTrace = loadAiTrace;
  const analyze = runAiAnalysis;
  const openChat = openChatModal;
  window.JobAgentAi = { loadStatus, loadSetup, loadTrace, analyze, openChat };
})();
