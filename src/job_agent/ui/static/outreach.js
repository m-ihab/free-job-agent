// Outreach drafts, application briefs, interview prep, and market reports (R3 split from app.js).
// Classic script, defer, after app.js; `state` is app.js's shared script-scope global.
(function () {
  const $ = (id) => document.getElementById(id);
  const api = (...args) => window.api(...args);
  const toast = (...args) => window.toast(...args);
  const setBusy = (...args) => window.setBusy(...args);
  const openTextModal = (...args) => window.openTextModal(...args);

// Outreach engine toggle: "auto" tries local Ollama (with template fallback),
// "standard" forces the deterministic templates. Read once per request.
function outreachEngine() {
  const select = $("outreachEngine");
  return select ? select.value : "auto";
}

function engineSuffix(engine) {
  return engine === "smart" ? " (AI-enhanced)" : "";
}

async function generateLinkedInMessage(jobId, button) {
  setBusy(button, true);
  toast("Drafting LinkedIn message…");
  try {
    const payload = await api("/api/linkedin-message", { job_id: jobId, type: "recruiter", engine: outreachEngine() });
    openTextModal(`LinkedIn Message Draft${engineSuffix(payload.engine)}`, payload.message, "Copy to clipboard");
  } catch (error) {
    toast(`LinkedIn message failed: ${error.message}`);
  } finally {
    setBusy(button, false);
  }
}

async function generateInterviewPrep(jobId, button) {
  setBusy(button, true);
  toast("Generating interview prep…");
  try {
    const payload = await api("/api/interview-prep", { job_id: jobId });
    const panel = $("prepPanel");
    const title = $("prepPanelTitle");
    const body = $("prepPanelBody");
    const copyBtn = $("prepPanelCopyBtn");
    const closeBtn = $("prepPanelCloseBtn");
    if (panel && body) {
      const job = state.jobs.find((j) => j.id === jobId);
      if (title) title.textContent = `Prep — ${job ? job.title : "Interview"}`;
      body.textContent = (payload.prep_md || "").replace(/\*\*([^*]+)\*\*/g, "$1");
      panel.classList.remove("hidden");
      panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
      if (copyBtn) copyBtn.onclick = () => navigator.clipboard.writeText(payload.prep_md || "").then(() => toast("Prep copied."));
      if (closeBtn) closeBtn.onclick = () => panel.classList.add("hidden");
    } else {
      openTextModal("Interview Prep", payload.prep_md, "Copy");
    }
  } catch (error) {
    toast(`Interview prep failed: ${error.message}`);
  } finally {
    setBusy(button, false);
  }
}

async function generateFollowupEmail(jobId, button) {
  setBusy(button, true);
  toast("Drafting follow-up email…");
  try {
    const payload = await api("/api/followup-email", { job_id: jobId, type: "week1", engine: outreachEngine() });
    openTextModal(`Follow-up Email Draft${engineSuffix(payload.engine)}`, payload.email_md, "Copy");
  } catch (error) {
    toast(`Follow-up failed: ${error.message}`);
  } finally {
    setBusy(button, false);
  }
}

async function runMarketReport() {
  const button = $("insightsMarketBtn");
  setBusy(button, true);
  toast("Building market report…");
  try {
    const result = await api("/api/market-report", {});
    openTextModal("Market Report", result.markdown || "No market data yet — track some jobs first.", "Copy");
  } catch (error) {
    toast(`Market report failed: ${error.message}`);
  } finally {
    setBusy(button, false);
  }
}

async function runHeadhunter() {
  const button = $("headhunterBtn");
  setBusy(button, true);
  toast("Building outreach packs…");
  try {
    const [batch, strategy] = await Promise.all([
      api("/api/headhunter-batch", { min_score: 50 }),
      api("/api/headhunter-strategy", {}),
    ]);
    const packs = (batch.packs || []).map((pack) =>
      `${pack.job_title} — ${pack.company} (score ${pack.score}${pack.is_english_first ? ", English-first" : ""})\n\nCONNECT:\n${pack.connect_request}\n\nRECRUITER MESSAGE:\n${pack.recruiter_message}\n\nFOLLOW-UP:\n${pack.followup_message}`
    ).join("\n\n────────────────────\n\n");
    const text = `${strategy.report_md || ""}\n\n====================\n${batch.count || 0} OUTREACH PACK(S)\n====================\n\n${packs || "No tracked jobs above the score threshold yet."}`;
    openTextModal("Headhunter Outreach", text, "Copy all");
  } catch (error) {
    toast(`Headhunter failed: ${error.message}`);
  } finally {
    setBusy(button, false);
  }
}

async function generateBrief(jobId, button) {
  setBusy(button, true);
  toast("Writing application brief…");
  try {
    const payload = await api("/api/application-brief", { job_id: jobId, engine: outreachEngine() });
    const keywords = (payload.keywords || []).join(", ");
    const text = [
      `HEADLINE\n${payload.headline || ""}`,
      `SUMMARY\n${payload.summary || ""}`,
      `KEYWORDS (most relevant for this role)\n${keywords}`,
    ].join("\n\n");
    openTextModal(`Application Brief${engineSuffix(payload.engine)}`, text, "Copy");
  } catch (error) {
    toast(`Brief failed: ${error.message}`);
  } finally {
    setBusy(button, false);
  }
}

async function generateOutreachEmail(jobId, button) {
  setBusy(button, true);
  toast("Drafting outreach email…");
  try {
    const payload = await api("/api/generate-outreach", { job_id: jobId, engine: outreachEngine() });
    openOutreachModal(payload);
  } catch (error) {
    toast(`Outreach failed: ${error.message}`);
  } finally {
    setBusy(button, false);
  }
}

function openOutreachModal(payload) {
  let modal = $("outreachModal");
  if (!modal) {
    modal = document.createElement("div");
    modal.id = "outreachModal";
    modal.className = "modal-overlay";
    modal.innerHTML = `
      <div class="modal-box" style="max-width:640px">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.75rem">
          <strong>Outreach Email Draft</strong>
          <button id="outreachCopyBtn" style="margin-left:auto;margin-right:0.5rem">Copy</button>
          <button id="outreachCloseBtn">✕</button>
        </div>
        <pre id="outreachContent" style="white-space:pre-wrap;font-size:0.85rem;background:var(--surface,#f5f5f5);padding:1rem;border-radius:6px;max-height:420px;overflow:auto"></pre>
        <p id="outreachRecruiterInfo" style="font-size:0.8rem;color:var(--muted,#888);margin-top:0.5rem"></p>
      </div>`;
    document.body.appendChild(modal);
    $("outreachCloseBtn").addEventListener("click", () => { modal.style.display = "none"; });
    $("outreachCopyBtn").addEventListener("click", () => {
      const text = $("outreachContent").textContent;
      navigator.clipboard.writeText(text).then(() => toast("Copied to clipboard."));
    });
    modal.addEventListener("click", (event) => { if (event.target === modal) modal.style.display = "none"; });
  }
  const emailText = (payload.email_md || "").replace(/\*\*Subject:\*\*/g, "Subject:").replace(/---\n\n/, "");
  $("outreachContent").textContent = emailText;
  const info = [];
  if (payload.recruiter_name) info.push(`Recruiter: ${payload.recruiter_name}`);
  if (payload.recruiter_email) info.push(`Email: ${payload.recruiter_email}`);
  $("outreachRecruiterInfo").textContent = info.join("  ·  ") || "No recruiter contact found in description.";
  modal.style.display = "flex";
}

  // ---- event bindings (moved from bindEvents) ----
  const insightsMarketBtn = $("insightsMarketBtn");
  if (insightsMarketBtn) insightsMarketBtn.addEventListener("click", runMarketReport);
  const headhunterBtn = $("headhunterBtn");
  if (headhunterBtn) headhunterBtn.addEventListener("click", runHeadhunter);

  const brief = generateBrief;
  const outreach = generateOutreachEmail;
  const linkedin = generateLinkedInMessage;
  const interviewPrep = generateInterviewPrep;
  const followup = generateFollowupEmail;
  window.JobAgentOutreach = { brief, outreach, linkedin, interviewPrep, followup };
})();
