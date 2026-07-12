// Auto-apply session UI (R3 split from app.js). Classic script, defer, after app.js.
// Owns: mode buttons, preview modal, SSE stream, needs-manual queue, apply log.
// `autoApplyState` stays a shared script-scope global declared in app.js
// (autopilot.js reads it too); this module reads/writes it as a bare identifier.
(function () {
  const $ = (id) => document.getElementById(id);
  const api = (...args) => window.api(...args);
  const toast = (...args) => window.toast(...args);
  const setBusy = (...args) => window.setBusy(...args);
  const setNotice = (...args) => window.setNotice(...args);
  const escapeHtml = (value) => window.escapeHtml(value);
  const safeHref = (value) => window.safeHref(value);
  const fileHref = (value) => window.fileHref(value);
  const companyLine = (job) => window.companyLine(job);
  const loadJobs = (...args) => window.loadJobs(...args);
  const renderState = (...args) => window.renderState(...args);

function autoApplyMode() { return autoApplyState.mode; }

function setAutoApplyMode(mode) {
  autoApplyState.mode = mode;
  document.querySelectorAll(".mode-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.mode === mode);
  });
}

function appendApplyLog(message, kind) {
  const wrap = $("autoApplyLogWrap");
  const log = $("autoApplyLog");
  if (!wrap || !log) return;
  wrap.classList.remove("hidden");
  const line = document.createElement("div");
  line.className = `log-line log-${kind || "progress"}`;
  const ts = new Date().toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  line.textContent = `${ts}  ${message}`;
  log.appendChild(line);
  log.scrollTop = log.scrollHeight;
}

function showConfirmModal(event) {
  const modal = $("applyConfirmModal");
  if (!modal) return;
  $("applyConfirmTitle").textContent = `Ready to Submit — ${event.message.replace("Form filled for ", "").replace(". Review and click Submit or Skip.", "")}`;
  $("applyConfirmSubtitle").textContent = event.summary ? event.summary.slice(0, 300) : "";
  const summaryDiv = $("applyConfirmSummary");
  if (summaryDiv) summaryDiv.textContent = event.summary ? event.summary.slice(0, 800) : "(No summary available)";
  modal.style.display = "flex";
}

function hideConfirmModal() {
  const modal = $("applyConfirmModal");
  if (modal) modal.style.display = "none";
}

function showPreSubmitToast(event) {
  const toast = $("preSubmitToast");
  const msg = $("preSubmitMsg");
  const cd = $("preSubmitCountdown");
  if (!toast || !msg || !cd) return;
  msg.textContent = event.message || "Submitting…";
  toast.classList.remove("hidden");
  let secs = (event.data && event.data.countdown) || 10;
  cd.textContent = secs;
  if (autoApplyState.countdown) clearInterval(autoApplyState.countdown);
  autoApplyState.countdown = setInterval(() => {
    secs -= 1;
    cd.textContent = secs;
    if (secs <= 0) {
      clearInterval(autoApplyState.countdown);
      toast.classList.add("hidden");
    }
  }, 1000);
}

function hidePreSubmitToast() {
  const toast = $("preSubmitToast");
  if (toast) toast.classList.add("hidden");
  if (autoApplyState.countdown) clearInterval(autoApplyState.countdown);
}

function subscribeAutoApplySse() {
  if (autoApplyState.stream) return;
  const es = new EventSource("/api/auto-apply/stream");
  autoApplyState.stream = es;
  es.addEventListener("apply", (event) => {
    let data;
    try { data = JSON.parse(event.data); } catch { return; }
    const kind = data.kind || "progress";
    appendApplyLog(data.message || "", kind);
    if (kind === "pending_confirm") showConfirmModal(data);
    if (kind === "pre_submit") showPreSubmitToast(data);
    if (kind === "needs_manual") {
      const reason = (data.data && data.data.reason) || "needs manual apply";
      toast(`Queued for manual apply (${reason}). Auto-apply continues.`);
      loadNeedsManual();
    }
    if (kind === "result") { hideConfirmModal(); hidePreSubmitToast(); }
    if (kind === "done" || kind === "error") {
      closeAutoApplySse();
      setNotice("autoApplyNotice", data.message || "Session ended.", kind === "error");
      setBusy($("autoApplyNowBtn"), false);
    }
  });
  es.onerror = () => closeAutoApplySse();
}

function closeAutoApplySse() {
  if (autoApplyState.stream) {
    try {
      autoApplyState.stream.close();
    } catch (error) {
      console.debug("Auto-apply SSE close failed", error);
    }
    autoApplyState.stream = null;
  }
}

// ── Needs-manual queue ───────────────────────────────────────────────────────
// Full-auto hands a job off here when it detects a CAPTCHA/login/anti-bot wall.
// The prepared draft is saved; the user opens the listing and finishes by hand.
async function loadNeedsManual() {
  const wrap = $("needsManualList");
  if (!wrap) return;
  try {
    const data = await api("/api/needs-manual");
    renderNeedsManual(data.jobs || []);
  } catch (error) {
    wrap.innerHTML = `<div class="notice error">${escapeHtml(error.message)}</div>`;
  }
}

function renderNeedsManual(jobs) {
  const wrap = $("needsManualList");
  if (!wrap) return;
  if (!jobs.length) {
    wrap.innerHTML = `<div class="notice">Nothing waiting. Jobs only land here when full-auto hits a human-presence wall.</div>`;
    return;
  }
  wrap.innerHTML = jobs
    .map((job) => {
      const reason = escapeHtml(job.needs_manual_reason || "human-presence wall");
      const listing = job.apply_url ? `<a href="${safeHref(job.apply_url)}" target="_blank" rel="noreferrer">Open listing</a>` : "";
      const assistant = job.assistant_page ? `<a href="${fileHref(job.assistant_page)}" target="_blank">Assistant</a>` : "";
      const cv = job.cv_pdf ? `<a href="${fileHref(job.cv_pdf)}" target="_blank">CV draft</a>` : "";
      const letter = job.cover_letter_pdf ? `<a href="${fileHref(job.cover_letter_pdf)}" target="_blank">Letter draft</a>` : "";
      return `<div style="padding:0.6rem 0;border-top:1px solid var(--border,#2a2a2a);display:flex;justify-content:space-between;gap:0.8rem;flex-wrap:wrap;align-items:flex-start">
        <div style="min-width:14rem;flex:1">
          <strong>${escapeHtml(job.title)}</strong> <span class="row-tag warn" title="Why full-auto handed this off">${reason}</span><br>
          ${companyLine(job)} <span class="muted">${escapeHtml(job.location || "")}</span>
        </div>
        <div class="row-actions">
          ${listing}${assistant}${cv}${letter}
          <button data-action="needs-manual-done" data-job="${escapeHtml(job.id)}" title="Mark as manually submitted and clear from this queue">Mark done</button>
        </div>
      </div>`;
    })
    .join("");
}

async function markNeedsManualDone(jobId, button) {
  setBusy(button, true);
  try {
    await api("/api/status", { job_id: jobId, status: "MANUALLY_SUBMITTED", note: "Completed from needs-manual queue" });
    toast("Marked as submitted.");
    await loadNeedsManual();
    await loadJobs();
    renderState();
  } catch (error) {
    toast(error.message);
  } finally {
    setBusy(button, false);
  }
}

// ── Pre-apply preview / selection ────────────────────────────────────────────

let _previewCandidates = [];

function renderPreviewModal(candidates) {
  const list = $("previewCandidateList");
  if (!list) return;
  if (!candidates.length) {
    list.innerHTML = '<p class="muted" style="padding:0.5rem">No ready packets found. Run the autopilot or generate packets first.</p>';
    return;
  }
  list.innerHTML = candidates.map((c, i) => `
    <label class="preview-candidate-row" style="display:flex;align-items:flex-start;gap:0.6rem;padding:0.55rem 0;border-bottom:1px solid var(--border,#e0e0e0)">
      <input type="checkbox" class="preview-check" data-index="${i}" checked style="margin-top:0.2rem;flex-shrink:0" />
      <div style="flex:1;min-width:0">
        <div style="font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${escapeHtml(c.title)} — ${escapeHtml(c.company)}</div>
        <div class="muted" style="font-size:0.82rem">${escapeHtml(c.location || "")} · Score ${c.fit_score != null ? Math.round(c.fit_score) : "—"}</div>
        <div class="muted" style="font-size:0.78rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${escapeHtml(c.apply_url || "")}</div>
      </div>
    </label>`).join("");
}

function getSelectedPreviewIds() {
  return [...document.querySelectorAll(".preview-check:checked")]
    .map((cb) => _previewCandidates[parseInt(cb.dataset.index, 10)]?.job_id)
    .filter(Boolean);
}

async function openPreviewModal() {
  const btn = $("autoApplyPreviewBtn");
  setBusy(btn, true);
  setNotice("autoApplyNotice", "");
  try {
    const minScore = parseFloat($("autoApplyMinScore")?.value || "70");
    const limit = parseInt($("autoApplyLimit")?.value || "10", 10);
    const result = await api(`/api/auto-apply/preview?min_score=${minScore}&limit=${limit}`, null, "GET");
    _previewCandidates = result.candidates || [];
    renderPreviewModal(_previewCandidates);
    const modal = $("previewModal");
    if (modal) modal.style.display = "flex";
  } catch (err) {
    setNotice("autoApplyNotice", err.message, true);
  } finally {
    setBusy(btn, false);
  }
}

async function startFromPreview() {
  const selectedIds = getSelectedPreviewIds();
  if (!selectedIds.length) {
    toast("Select at least one job to apply to.");
    return;
  }
  const modal = $("previewModal");
  if (modal) modal.style.display = "none";

  const nowBtn = $("autoApplyNowBtn");
  setBusy(nowBtn, true);
  setNotice("autoApplyNotice", "");
  const minScore = parseFloat($("autoApplyMinScore")?.value || "70");
  const limit = parseInt($("autoApplyLimit")?.value || "10", 10);
  try {
    const result = await api("/api/auto-apply/start", {
      mode: autoApplyMode(),
      min_score: minScore,
      limit,
      job_ids: selectedIds,
    });
    if (!result.ok) {
      setNotice("autoApplyNotice", result.error || "Could not start session.", true);
      setBusy(nowBtn, false);
      return;
    }
    appendApplyLog(`Session started for ${selectedIds.length} selected job(s)…`, "progress");
    subscribeAutoApplySse();
  } catch (err) {
    setNotice("autoApplyNotice", err.message, true);
    setBusy(nowBtn, false);
  }
}

async function openBrowserForLogin() {
  const btn = $("autoApplyLoginBtn");
  setBusy(btn, true);
  setNotice("autoApplyNotice", "");
  try {
    const result = await api("/api/auto-apply/open-browser", {});
    if (result.ok) {
      setNotice("autoApplyNotice", result.message || "Browser opened. Log in, then close it.");
    } else {
      setNotice("autoApplyNotice", result.error || "Could not open browser.", true);
    }
  } catch (err) {
    setNotice("autoApplyNotice", err.message, true);
  } finally {
    setBusy(btn, false);
  }
}

function bindAutoApplyEvents() {
  document.querySelectorAll(".mode-btn").forEach((btn) => {
    btn.addEventListener("click", () => setAutoApplyMode(btn.dataset.mode));
  });

  const previewBtn = $("autoApplyPreviewBtn");
  if (previewBtn) previewBtn.addEventListener("click", openPreviewModal);

  const loginBtn = $("autoApplyLoginBtn");
  if (loginBtn) loginBtn.addEventListener("click", openBrowserForLogin);

  // "Select all / deselect all" in preview modal
  const selectAllBtn = $("previewSelectAll");
  if (selectAllBtn) selectAllBtn.addEventListener("click", () => {
    document.querySelectorAll(".preview-check").forEach((cb) => { cb.checked = true; });
  });
  const deselectAllBtn = $("previewDeselectAll");
  if (deselectAllBtn) deselectAllBtn.addEventListener("click", () => {
    document.querySelectorAll(".preview-check").forEach((cb) => { cb.checked = false; });
  });

  const previewStartBtn = $("previewStartBtn");
  if (previewStartBtn) previewStartBtn.addEventListener("click", startFromPreview);

  const _hidePreviewModal = () => { const m = $("previewModal"); if (m) m.style.display = "none"; };
  const previewCloseBtn = $("previewCloseBtn");
  if (previewCloseBtn) previewCloseBtn.addEventListener("click", _hidePreviewModal);
  const previewCancelBtn = $("previewCancelBtn");
  if (previewCancelBtn) previewCancelBtn.addEventListener("click", _hidePreviewModal);
  const previewModal = $("previewModal");
  if (previewModal) previewModal.addEventListener("click", (e) => {
    if (e.target === previewModal) _hidePreviewModal();
  });

  // Legacy "Auto-Apply Now" still works (skips preview, uses all ready jobs)
  const nowBtn = $("autoApplyNowBtn");
  if (nowBtn) nowBtn.addEventListener("click", async () => {
    setBusy(nowBtn, true);
    setNotice("autoApplyNotice", "");
    const minScore = parseFloat($("autoApplyMinScore")?.value || "70");
    const limit = parseInt($("autoApplyLimit")?.value || "10", 10);
    try {
      const result = await api("/api/auto-apply/start", {
        mode: autoApplyMode(),
        min_score: minScore,
        limit,
      });
      if (!result.ok) {
        setNotice("autoApplyNotice", result.error || "Could not start session.", true);
        setBusy(nowBtn, false);
        return;
      }
      appendApplyLog("Session started…", "progress");
      subscribeAutoApplySse();
    } catch (err) {
      setNotice("autoApplyNotice", err.message, true);
      setBusy(nowBtn, false);
    }
  });

  const cancelBtn = $("autoApplyCancelBtn");
  if (cancelBtn) cancelBtn.addEventListener("click", async () => {
    closeAutoApplySse();
    hideConfirmModal();
    hidePreSubmitToast();
    try { await api("/api/auto-apply/cancel", {}); } catch (err) { toast(`Could not reach server to cancel: ${err.message}`); }
    appendApplyLog("Session cancelled.", "error");
    setBusy($("autoApplyNowBtn"), false);
  });

  const submitBtn = $("applyConfirmSubmitBtn");
  if (submitBtn) submitBtn.addEventListener("click", async () => {
    hideConfirmModal();
    try { await api("/api/auto-apply/confirm", {}); } catch (err) { toast(`Confirm failed: ${err.message}`); }
    appendApplyLog("Confirmed — submitting…", "progress");
  });

  const skipBtn = $("applyConfirmSkipBtn");
  if (skipBtn) skipBtn.addEventListener("click", async () => {
    hideConfirmModal();
    try { await api("/api/auto-apply/skip", {}); } catch (err) { toast(`Skip failed: ${err.message}`); }
    appendApplyLog("Skipped.", "result");
  });

  const preSubmitCancel = $("preSubmitCancelBtn");
  if (preSubmitCancel) preSubmitCancel.addEventListener("click", async () => {
    hidePreSubmitToast();
    try { await api("/api/auto-apply/skip", {}); } catch (err) { toast(`Cancel failed: ${err.message}`); }
    appendApplyLog("Full-auto submission cancelled.", "result");
  });

  const logClear = $("autoApplyLogClear");
  if (logClear) logClear.addEventListener("click", () => {
    const log = $("autoApplyLog");
    if (log) log.innerHTML = "";
  });
}

  // ---- module init (moved from bindEvents) ----
  bindAutoApplyEvents();
  const needsManualRefreshBtn = document.getElementById("needsManualRefreshBtn");
  if (needsManualRefreshBtn) needsManualRefreshBtn.addEventListener("click", loadNeedsManual);

  window.JobAgentAutoApply = {
    loadNeedsManual,
    markNeedsManualDone,
  };
})();
