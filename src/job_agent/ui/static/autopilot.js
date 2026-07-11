// Autopilot panel (R3 split from app.js). Classic script, defer, after
// app.js — pipeline.js idiom. Owns the autopilot SSE stream and its
// refresh timer (state.autopilotTimer / state.autopilotStream).
(function () {
  function $(id) { return document.getElementById(id); }
  const api = (...args) => window.api(...args);
  const toast = (...args) => window.toast(...args);
  const setNotice = (...args) => window.setNotice(...args);
  const setBusy = (...args) => window.setBusy(...args);
  const escapeHtml = (value) => window.escapeHtml(value);
  const metric = (...args) => window.metric(...args);

async function loadAutopilot() {
  try {
    const status = await api("/api/autopilot");
    state.autopilotCache = status;
    renderAutopilot(status);
  } catch (error) {
    setNotice("autopilotNotice", error.message, true);
  }
}

function renderAutopilot(status) {
  const cfg = status.config || {};
  $("autopilotMetrics").innerHTML = [
    metric("Running", status.running ? "Yes" : "No"),
    metric("Cycles", status.cycles_completed || 0),
    metric("Jobs added", status.jobs_added_total || 0),
    metric("Packets built", status.packets_built_total || 0),
  ].join("");
  if ($("autopilotInterval")) {
    if (cfg.interval_minutes) $("autopilotInterval").value = cfg.interval_minutes;
    if (cfg.location) $("autopilotLocation").value = cfg.location;
    if (cfg.radius_km != null && $("autopilotRadius")) $("autopilotRadius").value = cfg.radius_km;
    if (cfg.auto_packet_threshold != null) $("autopilotThreshold").value = cfg.auto_packet_threshold;
    if (cfg.min_relevance != null && $("autopilotMinRelevance")) $("autopilotMinRelevance").value = cfg.min_relevance;
    if (cfg.max_packets_per_cycle != null) $("autopilotMaxPackets").value = cfg.max_packets_per_cycle;
    if (cfg.queries && cfg.queries.length) $("autopilotQueries").value = cfg.queries.join("\n");
    $("autopilotUseFT").checked = cfg.use_france_travail !== false;
    $("autopilotUseMulti").checked = cfg.use_multi_source !== false;
    if ($("autopilotFranceEuOnly")) $("autopilotFranceEuOnly").checked = cfg.france_eu_only !== false;
    if ($("autopilotEmailNotify")) $("autopilotEmailNotify").checked = cfg.email_notify === true;
  }
  const summary = status.last_summary;
  if (summary) {
    const perQuery = Object.entries(summary.per_query || {})
      .map(([q, c]) => `${escapeHtml(q)}: ${c}`)
      .join("<br>");
    const plannedQueries = (summary.queries || []).map((q) => `<span class="badge">${escapeHtml(q)}</span>`).join("");
    $("autopilotLastSummary").innerHTML = `
      <div class="detail-row"><span>Last run</span><strong>${escapeHtml(status.last_run_at || "-")}</strong></div>
      <div class="detail-row"><span>Jobs added</span><strong>${summary.jobs_added || 0}</strong></div>
      <div class="detail-row"><span>Packets built</span><strong>${summary.packets_built || 0}</strong></div>
      <div class="detail-row"><span>France Travail</span><strong>${summary.france_travail_used ? "yes" : "no"}</strong></div>
      <div class="detail-row"><span>Multi-source</span><strong>${summary.multi_source_used ? "yes" : "no"}</strong></div>
      ${plannedQueries ? `<h4>Smart queries</h4><div class="tag-cloud">${plannedQueries}</div>` : ""}
      ${perQuery ? `<h4>Per query</h4><div class="muted">${perQuery}</div>` : ""}
    `;
  } else {
    $("autopilotLastSummary").innerHTML = "Autopilot has not run yet. Press <strong>Start autopilot</strong> to begin.";
  }
  const errs = (summary && summary.errors) || (status.last_error ? [status.last_error] : []);
  if (errs && errs.length) {
    $("autopilotErrors").innerHTML = errs.map(escapeHtml).join("<br>");
  } else {
    $("autopilotErrors").innerHTML = "None.";
  }
  const brokenNode = document.getElementById("autopilotBrokenSources");
  if (brokenNode) {
    const broken = (summary && summary.broken_sources) || status.broken_sources || [];
    if (!broken.length) {
      brokenNode.innerHTML = "None recorded.";
    } else {
      brokenNode.innerHTML = broken.map((b) =>
        `<div class="detail-row"><span>${escapeHtml(b.source)}/${escapeHtml(b.slug)}</span><strong>HTTP ${b.status_code || "?"} · until ${escapeHtml((b.broken_until || "").slice(0, 16))}</strong></div>`
      ).join("");
    }
  }
}

let _contractType = "stage_and_alternance";

function setContractType(type) {
  _contractType = type;
  document.querySelectorAll("#contractTypeToggle .contract-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.contract === type);
  });
}

function autopilotPayload() {
  return {
    interval_minutes: Number($("autopilotInterval").value || 30),
    location: $("autopilotLocation").value.trim() || "Paris",
    radius_km: Number($("autopilotRadius")?.value || 0),
    auto_packet_threshold: Number($("autopilotThreshold").value || 75),
    min_relevance: Number($("autopilotMinRelevance")?.value || 50),
    max_packets_per_cycle: Number($("autopilotMaxPackets").value || 5),
    queries: $("autopilotQueries").value.split("\n").map((q) => q.trim()).filter(Boolean),
    use_france_travail: $("autopilotUseFT").checked,
    use_multi_source: $("autopilotUseMulti").checked,
    contract_type: _contractType,
    france_eu_only: $("autopilotFranceEuOnly") ? $("autopilotFranceEuOnly").checked : true,
    email_notify: $("autopilotEmailNotify") ? $("autopilotEmailNotify").checked : false,
    auto_apply: $("autopilotAutoApply") ? $("autopilotAutoApply").checked : false,
    auto_apply_mode: autoApplyState ? autoApplyState.mode : "fill_and_confirm",
    auto_apply_min_score: parseFloat($("autoApplyMinScore")?.value || "75"),
  };
}

function subscribeAutopilotSse() {
  if (state.autopilotStream) return;
  if (typeof EventSource === "undefined") return;
  const es = new EventSource("/api/autopilot/stream");
  state.autopilotStream = es;
  es.addEventListener("status", (event) => {
    try {
      const status = JSON.parse(event.data);
      state.autopilotCache = status;
      renderAutopilot(status);
      if (!status.running) closeAutopilotSse();
    } catch {
      // ignore parse errors; keep stream open
    }
  });
  es.onerror = () => {
    closeAutopilotSse();
  };
}

function closeAutopilotSse() {
  if (state.autopilotStream) {
    try {
      state.autopilotStream.close();
    } catch (error) {
      console.debug("Autopilot SSE close failed", error);
    }
    state.autopilotStream = null;
  }
}

async function startAutopilot() {
  const button = $("autopilotStartBtn");
  setBusy(button, true);
  setNotice("autopilotNotice", "");
  try {
    const payload = await api("/api/autopilot/start", autopilotPayload());
    renderAutopilot(payload.status);
    toast("Autopilot started. It runs in the background.");
    if (state.autopilotTimer) window.clearInterval(state.autopilotTimer);
    state.autopilotTimer = window.setInterval(loadAutopilot, 30000);
    subscribeAutopilotSse();
  } catch (error) {
    setNotice("autopilotNotice", error.message, true);
  } finally {
    setBusy(button, false);
  }
}

async function stopAutopilot() {
  const button = $("autopilotStopBtn");
  setBusy(button, true);
  try {
    const payload = await api("/api/autopilot/stop", {});
    renderAutopilot(payload.status);
    if (state.autopilotTimer) {
      window.clearInterval(state.autopilotTimer);
      state.autopilotTimer = null;
    }
    closeAutopilotSse();
    toast("Autopilot stopped.");
  } catch (error) {
    setNotice("autopilotNotice", error.message, true);
  } finally {
    setBusy(button, false);
  }
}


  // ---- event bindings (moved from bindEvents) ----
  $("autopilotStartBtn").addEventListener("click", startAutopilot);
  $("autopilotStopBtn").addEventListener("click", stopAutopilot);
  $("autopilotRefreshBtn").addEventListener("click", loadAutopilot);
  document.querySelectorAll("#contractTypeToggle .contract-btn").forEach((btn) => {
    btn.addEventListener("click", () => setContractType(btn.dataset.contract));
  });

  window.JobAgentAutopilot = {
    load: loadAutopilot,
  };
})();
