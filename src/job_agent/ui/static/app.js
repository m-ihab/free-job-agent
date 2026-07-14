const state = {
  profile: null,
  statuses: [],
  jobs: [],
  selectedJobs: new Set(),
  activeJobId: null,
  insightsCache: null,
  autopilotCache: null,
  autopilotTimer: null,
  autopilotStream: null,
  chord: { key: "", at: 0 },
  charts: {},
  aiStatus: null,
  chatJobId: null,
  chatHistory: [],
  preflight: {},
  studioActiveAsset: null,
  studioActiveAssetKind: null,
  ollamaPullWatcher: null,
};

const $ = (id) => document.getElementById(id);

async function api(path, body = null, method = body ? "POST" : "GET", timeoutMs = 120000) {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  const options = { method, headers: {}, signal: controller.signal };
  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content;
  if (csrfToken) {
    options.headers["X-Job-Agent-Token"] = csrfToken;
  }
  if (body) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  try {
    const response = await fetch(path, options);
    window.clearTimeout(timer);
    const text = await response.text();
    let payload = {};
    try {
      payload = text ? JSON.parse(text) : {};
    } catch {
      payload = { error: text || response.statusText };
    }
    if (!response.ok) {
      throw new Error(payload.error || response.statusText);
    }
    return payload;
  } catch (err) {
    window.clearTimeout(timer);
    if (err.name === "AbortError") {
      throw new Error("Request timed out. The server is taking too long to respond.");
    }
    throw err;
  }
}

function toast(message) {
  const node = $("toast");
  node.textContent = message;
  node.classList.remove("hidden");
  window.clearTimeout(toast._timer);
  toast._timer = window.setTimeout(() => node.classList.add("hidden"), 3500);
}

function setNotice(id, message, isError = false) {
  const node = $(id);
  if (!message) {
    node.classList.add("hidden");
    node.textContent = "";
    return;
  }
  node.textContent = message;
  node.classList.toggle("error", isError);
  node.classList.remove("hidden");
}

function setBusy(button, busy) {
  if (!button) return;
  button.disabled = busy;
  if (!button.dataset.label) button.dataset.label = button.textContent;
  button.textContent = busy ? "Working..." : button.dataset.label;
}

function fileHref(path) {
  return path ? `/file?path=${encodeURIComponent(path)}` : "";
}

function safeHref(value) {
  try {
    const parsed = new URL(String(value || ""), window.location.href);
    const protocol = parsed.protocol;
    if (protocol === "http:" || protocol === "https:") {
      return escapeHtml(parsed.href);
    }
  } catch {
    // Invalid URLs are rendered inert instead of entering an href attribute.
  }
  return "#";
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function renderBadge(label, tone = "") {
  return `<span class="badge ${tone}">${escapeHtml(label)}</span>`;
}

function scoreTone(score) {
  if (score === null || score === undefined || score === "") return "score-na";
  const value = Number(score);
  if (Number.isNaN(value)) return "score-na";
  if (value >= 80) return "score-high";
  if (value >= 60) return "score-mid";
  return "score-low";
}

function scorePill(score) {
  const tone = scoreTone(score);
  const display = score === null || score === undefined || score === "" ? "—" : Math.round(Number(score));
  return `<span class="score-pill ${tone}">${display}</span>`;
}

function renderState() {
  const profile = state.profile || {};
  const aiModelLabel = (profile.ollama_model || "").replace(":latest", "") || "ready";
  const ollamaBadge = profile.ollama_ready
    ? renderBadge(`Local AI: ${aiModelLabel}`, "good")
    : renderBadge("Local AI offline", "warn");
  const compiler = (profile.latex_compiler || "").split(/[\\/]/).pop();
  const badgesHtml = [
    renderBadge(profile.valid ? "Profile ready" : "Profile needs review", profile.valid ? "good" : "bad"),
    renderBadge(profile.france_travail_configured ? "France Travail ready" : "France Travail off", profile.france_travail_configured ? "good" : "warn"),
    renderBadge(profile.apprentissage_configured ? "Alternance API ready" : "Alternance API off", profile.apprentissage_configured ? "good" : "warn"),
    renderBadge(profile.latex_ready ? `LaTeX: ${compiler}` : "LaTeX missing", profile.latex_ready ? "good" : "warn"),
    ollamaBadge,
    renderBadge(`${state.jobs.length} jobs`, "good"),
  ].filter(Boolean).join("");
  const themeButton = document.getElementById("themeToggleBtn");
  const cmdkButton = document.getElementById("cmdkOpenBtn");
  $("statusStrip").innerHTML = badgesHtml;
  if (cmdkButton) $("statusStrip").prepend(cmdkButton);
  if (themeButton) $("statusStrip").appendChild(themeButton);

  $("statusFilter").innerHTML = `<option value="">All statuses</option>${state.statuses
    .map((status) => `<option value="${escapeHtml(status)}">${escapeHtml(status)}</option>`)
    .join("")}`;

  $("profileMetrics").innerHTML = [
    metric("Profile", profile.valid ? "Ready" : "Review"),
    metric("France Travail", profile.france_travail_configured ? "Ready" : "Missing"),
    metric("Alternance API", profile.apprentissage_configured ? "Ready" : "Missing"),
    metric("LaTeX", profile.latex_ready ? profile.latex_compiler : "Missing"),
    metric("Local AI", profile.ollama_ready ? profile.ollama_model : "Offline", profile.ollama_polish_enabled ? "Polish enabled" : "Fit/query AI auto-ready when Ollama runs"),
    metric("Notifier", profile.email_notifier?.enabled ? "Email on" : "Local outbox", profile.email_notifier?.smtp_configured ? "SMTP configured" : "No SMTP"),
    metric("Tracked jobs", state.jobs.length),
  ].join("");

  $("apiReadiness").innerHTML = [
    readinessRow("Job search (ID + secret)", profile.france_travail_configured ? "Ready" : "Set FRANCE_TRAVAIL_CLIENT_ID/SECRET"),
    readinessRow("La bonne alternance token", profile.apprentissage_configured ? "Ready" : "Set APPRENTISSAGE_API_TOKEN"),
    readinessRow(".env.local", profile.env_local_present ? "Loaded" : "Optional"),
    readinessRow("OpenClaw", profile.local_tools?.openclaw ? "Installed" : "Not on PATH"),
    readinessRow("npm", profile.local_tools?.npm ? "Installed" : "Not on PATH"),
    readinessRow("Perl", profile.local_tools?.perl ? "Installed" : "Only needed for latexmk"),
    readinessRow("Endpoints map (enrichment only — optional)", profile.endpoints_file_present ? "Configured" : "Not configured"),
    readinessRow(
      "Enabled enrichment endpoints",
      `${profile.endpoints_summary?.enabled || 0}/${profile.endpoints_summary?.configured || 0} (${profile.endpoints_summary?.total || 0} total)`
    ),
  ].join("") + `<div class="muted" style="margin-top:0.4rem">${escapeHtml(profile.endpoints_explainer || "")}</div>`;

  $("apiAppName").value = profile.app_name || "";
  $("apiAppUrl").value = profile.app_url || "";
  $("apiAppDescription").value = profile.app_description || "";
  $("pathList").innerHTML = [
    pathRow("Profiles", profile.profiles_dir),
    pathRow("Data", profile.data_dir),
    pathRow("Outputs", profile.outputs_dir),
  ].join("");
  const messages = [...(profile.errors || []), ...(profile.warnings || [])];
  $("profileMessages").innerHTML = messages.length
    ? `<div class="notice">${messages.map(escapeHtml).join("<br>")}</div>`
    : `<div class="notice">Profile validation is clean.</div>`;
}

function readinessRow(label, value) {
  return `<div class="readiness-row"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`;
}

function metric(label, value, sub = "") {
  const subLine = sub ? `<div class="muted" style="margin-top:0.2rem">${escapeHtml(sub)}</div>` : "";
  const long = String(value ?? "").length > 42 ? " metric-long" : "";
  return `<div class="metric${long}"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong>${subLine}</div>`;
}

function pathRow(label, value) {
  return `<dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value || "")}</dd>`;
}

async function loadState() {
  const payload = await api("/api/state");
  state.profile = payload.profile;
  state.statuses = payload.statuses || [];
  await loadJobs(false);
  renderState();
}

async function loadJobs(render = true) {
  const status = $("statusFilter") ? $("statusFilter").value : "";
  const payload = await api(`/api/jobs?status=${encodeURIComponent(status)}`);
  state.jobs = payload.jobs || [];
  const available = new Set(state.jobs.map((job) => job.id));
  state.selectedJobs.forEach((jobId) => {
    if (!available.has(jobId)) state.selectedJobs.delete(jobId);
  });
  if (render && window.JobAgentJobs) window.JobAgentJobs.renderJobs();
}

function companyLine(job) {
  const display = job.company_display || job.company || "Employer not disclosed";
  const source = job.company_source && job.company_source !== display
    ? ` <span class="row-tag">via ${escapeHtml(job.company_source)}</span>`
    : "";
  const unresolved = job.company_unresolved ? ` <span class="row-tag warn">undisclosed</span>` : "";
  return `<span class="muted">${escapeHtml(display)}</span>${source}${unresolved}`;
}

// eslint-disable-next-line no-unused-vars -- consumed by search.js/jobs.js via window
function jobActions(job) {
  const apply = job.apply_url ? `<a href="${safeHref(job.apply_url)}" target="_blank" rel="noreferrer">Apply</a>` : "";
  const assistant = job.assistant_page ? `<a href="${fileHref(job.assistant_page)}" target="_blank">Assistant</a>` : "";
  const cv = job.cv_pdf ? `<a href="${fileHref(job.cv_pdf)}" target="_blank">CV</a>` : "";
  const letter = job.cover_letter_pdf ? `<a href="${fileHref(job.cover_letter_pdf)}" target="_blank">Letter</a>` : "";
  const letterButton = job.latest_packet_id && !job.cover_letter_pdf
    ? `<button data-action="cover-letter" data-job="${escapeHtml(job.id)}" title="Generate the cover letter only if you actually need it">Generate letter</button>`
    : "";
  const submitted = job.status === "MANUALLY_SUBMITTED" ? "" : `<button data-action="status" data-status="MANUALLY_SUBMITTED" data-job="${escapeHtml(job.id)}" title="Mark as manually submitted">Submitted</button>`;
  const rejected = job.status === "REJECTED" ? "" : `<button data-action="status" data-status="REJECTED" data-job="${escapeHtml(job.id)}" title="Mark as rejected">Reject</button>`;
  const remove = `<button data-action="delete-job" data-job="${escapeHtml(job.id)}" title="Remove this job from the local tracker">Remove</button>`;
  return `<div class="row-actions">
    <button data-action="preflight" data-job="${escapeHtml(job.id)}" title="Check fit, must-haves, ATS gaps, and manual blockers before applying">Preflight</button>
    <button data-action="packet" data-job="${escapeHtml(job.id)}" title="Generate a tailored CV + cover letter for this job">Tailor CV</button>
    <button data-action="brief" data-job="${escapeHtml(job.id)}" title="Write a headline, summary, and the most relevant keywords for this application">Brief</button>
    <button data-action="outreach" data-job="${escapeHtml(job.id)}" title="Draft a cold outreach email to the recruiter/hiring manager">Outreach</button>
    <button data-action="linkedin" data-job="${escapeHtml(job.id)}" title="Draft a LinkedIn message to the recruiter">LinkedIn</button>
    <button data-action="interview" data-job="${escapeHtml(job.id)}" title="Generate interview prep questions">Prep</button>
    <button data-action="followup" data-job="${escapeHtml(job.id)}" title="Generate a follow-up email">Follow-up</button>
    <button data-action="ai-analyze" data-job="${escapeHtml(job.id)}" title="AI fit analysis">AI fit</button>
    <button data-action="ai-chat" data-job="${escapeHtml(job.id)}" title="Chat about this role">Chat</button>
    <button data-action="enrich" data-job="${escapeHtml(job.id)}" title="Enrich with France Travail data">Enrich</button>
    ${letterButton}${submitted}${rejected}${remove}
    ${apply}${assistant}${cv}${letter}
  </div>`;
}

async function addUrl() {
  const button = $("addUrlBtn");
  setBusy(button, true);
  setNotice("addNotice", "");
  try {
    const payload = await api("/api/add-url", { url: $("addUrlInput").value.trim() });
    setNotice("addNotice", payload.created ? "Job imported." : "Duplicate found; existing job loaded.");
    await loadJobs(false);
    renderState();
  } catch (error) {
    setNotice("addNotice", error.message, true);
  } finally {
    setBusy(button, false);
  }
}

async function addBulk() {
  const button = $("bulkAddBtn");
  const text = $("bulkAddInput").value.trim();
  if (!text) {
    setNotice("addNotice", "Paste at least one job posting or URL first.", true);
    return;
  }
  setBusy(button, true);
  setNotice("addNotice", "");
  try {
    const payload = await api("/api/add-bulk", { text });
    const errors = payload.errors || [];
    const parts = [`Added ${payload.added}`, `${payload.duplicates} duplicate(s)`];
    if (errors.length) parts.push(`${errors.length} error(s)`);
    setNotice("addNotice", parts.join(" · ") + (errors.length ? `\n${errors.join("\n")}` : ""), errors.length > 0);
    if (payload.added > 0) {
      $("bulkAddInput").value = "";
      await loadJobs(false);
      renderState();
    }
  } catch (error) {
    setNotice("addNotice", error.message, true);
  } finally {
    setBusy(button, false);
  }
}

async function addText() {
  const button = $("addTextBtn");
  setBusy(button, true);
  setNotice("addNotice", "");
  try {
    const payload = await api("/api/add-text", {
      title: $("textTitleInput").value.trim(),
      company: $("textCompanyInput").value.trim(),
      url: $("textUrlInput").value.trim(),
      text: $("jobTextInput").value.trim(),
    });
    setNotice("addNotice", payload.created ? "Job imported." : "Duplicate found; existing job loaded.");
    await loadJobs(false);
    renderState();
  } catch (error) {
    setNotice("addNotice", error.message, true);
  } finally {
    setBusy(button, false);
  }
}

function openTextModal(title, content, copyLabel) {
  let modal = document.getElementById("genericTextModal");
  if (!modal) {
    modal = document.createElement("div");
    modal.id = "genericTextModal";
    modal.className = "modal-overlay";
    modal.innerHTML = `
      <div class="modal-box" style="max-width:680px">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.75rem">
          <strong id="genericModalTitle"></strong>
          <button id="genericModalCopyBtn" style="margin-left:auto;margin-right:0.5rem">Copy</button>
          <button id="genericModalCloseBtn">✕</button>
        </div>
        <pre id="genericModalContent" style="white-space:pre-wrap;font-size:0.83rem;background:var(--surface,#f5f5f5);padding:1rem;border-radius:6px;max-height:480px;overflow:auto"></pre>
      </div>`;
    document.body.appendChild(modal);
    document.getElementById("genericModalCloseBtn").addEventListener("click", () => { modal.style.display = "none"; });
    document.getElementById("genericModalCopyBtn").addEventListener("click", () => {
      navigator.clipboard.writeText(document.getElementById("genericModalContent").textContent).then(() => toast("Copied to clipboard."));
    });
    modal.addEventListener("click", (e) => { if (e.target === modal) modal.style.display = "none"; });
  }
  document.getElementById("genericModalTitle").textContent = title;
  document.getElementById("genericModalCopyBtn").textContent = copyLabel || "Copy";
  const text = (content || "").replace(/\*\*([^*]+)\*\*/g, "$1").replace(/---\n\n/, "");
  document.getElementById("genericModalContent").textContent = text;
  modal.style.display = "flex";
}

// eslint-disable-next-line no-unused-vars -- bound in coach.js via window
async function runRecruiterAudit() {
  const button = document.getElementById("coachAuditBtn");
  setBusy(button, true);
  toast("Auditing your profile…");
  try {
    const r = await api("/api/audit-profile", {});
    openTextModal(`Recruiter Audit — ${r.grade || "?"} (${r.score ?? "?"}/100)`, r.markdown || "No audit available.", "Copy");
  } catch (error) {
    toast(`Audit failed: ${error.message}`);
  } finally {
    setBusy(button, false);
  }
}

// eslint-disable-next-line no-unused-vars -- bound in coach.js via window
async function runSkillSuggestions() {
  const button = document.getElementById("coachSkillsBtn");
  setBusy(button, true);
  try {
    const r = await api("/api/suggest-skills", {});
    const implied = (r.implied || []).map((s) => `• ${s.name}${s.implied_by ? ` (from ${s.implied_by})` : ""}`).join("\n") || "None detected.";
    const gaps = (r.trending_gaps || []).map((g) => `• ${g}`).join("\n") || "None detected.";
    openTextModal("Skill Suggestions", `IMPLIED SKILLS (already shown by your profile/projects)\n${implied}\n\nTRENDING GAPS WORTH ADDING\n${gaps}`, "Copy");
  } catch (error) {
    toast(`Suggestions failed: ${error.message}`);
  } finally {
    setBusy(button, false);
  }
}

async function exportInternships() {
  const button = $("exportInternshipsBtn");
  setBusy(button, true);
  setNotice("profileNotice", "");
  try {
    const payload = await api("/api/export-internships", {
      workbook: $("internshipWorkbookPath").value.trim(),
      sheet: $("internshipSheetName").value.trim(),
    });
    setNotice("profileNotice", `Exported ${payload.count} internship applications to ${payload.workbook}`);
  } catch (error) {
    setNotice("profileNotice", error.message, true);
  } finally {
    setBusy(button, false);
  }
}

async function importTracker() {
  const button = $("importTrackerBtn");
  setBusy(button, true);
  setNotice("profileNotice", "");
  try {
    const payload = await api("/api/tracker-import", {});
    const errors = payload.errors || [];
    const parts = [`Synced ${payload.updated} status change(s)`, `${payload.unmatched} unmatched row(s)`];
    setNotice("profileNotice", parts.join(" · ") + (errors.length ? `\n${errors.join("\n")}` : ""), errors.length > 0);
    if (payload.updated > 0) {
      await loadJobs(false);
      renderState();
    }
  } catch (error) {
    setNotice("profileNotice", error.message, true);
  } finally {
    setBusy(button, false);
  }
}

function arrayBufferToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  const chunkSize = 0x8000;
  for (let i = 0; i < bytes.length; i += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunkSize));
  }
  return btoa(binary);
}

async function importCvTemplate() {
  const input = $("cvTemplateFile");
  const file = input?.files?.[0];
  if (!file) {
    setNotice("profileNotice", "Choose a .tex, .pdf, .docx, image, .sty, or .cls file first.", true);
    return;
  }
  const button = $("importCvTemplateBtn");
  setBusy(button, true);
  setNotice("profileNotice", "");
  try {
    const content = arrayBufferToBase64(await file.arrayBuffer());
    const payload = await api("/api/import-cv-template", {
      filename: file.name,
      content_base64: content,
    });
    setNotice("profileNotice", `${payload.note} Stored at ${payload.target}`);
    await loadState();
  } catch (error) {
    setNotice("profileNotice", error.message, true);
  } finally {
    setBusy(button, false);
  }
}

// ===== Tracker tab =====
// Tracker rendering publishes jobagent:tracker-rendered; kanban.js subscribes
// to keep its board view in sync without replacing window.renderTracker.
// This event contract keeps a future IIFE extraction compatible.
// The application funnel: tracked jobs grouped into pipeline stages, each row's
// status editable inline (saves via /api/status), with the Excel export/import.
const TRACKER_STAGES = [
  { label: "To apply", statuses: ["NEW", "SCORED", "PACKET_READY", "NEEDS_REVIEW"] },
  { label: "Applied", statuses: ["APPLYING", "APPLIED", "MANUALLY_SUBMITTED", "AUTO_SUBMITTED", "ASSISTED_APPLY_OPENED"] },
  { label: "Interviewing", statuses: ["INTERVIEW"] },
  { label: "Offers", statuses: ["OFFERED", "ACCEPTED"] },
  { label: "Closed", statuses: ["REJECTED", "WITHDRAWN", "FAILED"] },
  { label: "Needs manual", statuses: ["NEEDS_MANUAL"] },
];
const TRACKER_STATUS_OPTIONS = [
  "NEW", "APPLYING", "APPLIED", "MANUALLY_SUBMITTED", "AUTO_SUBMITTED", "INTERVIEW",
  "OFFERED", "ACCEPTED", "REJECTED", "WITHDRAWN", "NEEDS_MANUAL",
];

function trackerStatusSelect(job) {
  const current = job.status || "NEW";
  const known = TRACKER_STATUS_OPTIONS.includes(current)
    ? TRACKER_STATUS_OPTIONS
    : [current, ...TRACKER_STATUS_OPTIONS];
  const opts = known
    .map((s) => `<option value="${s}" ${s === current ? "selected" : ""}>${escapeHtml(s.replace(/_/g, " "))}</option>`)
    .join("");
  return `<select class="tracker-status" data-action="status-select" data-job="${escapeHtml(job.id)}">${opts}</select>`;
}

function renderTracker() {
  const jobs = state.jobs || [];
  const funnel = TRACKER_STAGES.map((stage) => {
    const count = jobs.filter((j) => stage.statuses.includes(j.status)).length;
    return `<div class="metric"><div class="metric-value">${count}</div><div class="metric-label">${stage.label}</div></div>`;
  }).join("");
  if ($("trackerFunnel")) $("trackerFunnel").innerHTML = funnel;

  const rows = jobs.map((job) => `<tr>
      <td><strong>${escapeHtml(job.title)}</strong><br>${companyLine(job)}</td>
      <td>${scorePill(job.fit_score)}</td>
      <td>${trackerStatusSelect(job)}</td>
      <td class="actions">
        <button data-action="brief" data-job="${escapeHtml(job.id)}" title="Headline, summary, keywords">Brief</button>
        <button data-action="outreach" data-job="${escapeHtml(job.id)}" title="Outreach email">Outreach</button>
        <button data-action="followup" data-job="${escapeHtml(job.id)}" title="Follow-up email">Follow-up</button>
        ${job.apply_url ? `<a href="${safeHref(job.apply_url)}" target="_blank" rel="noreferrer">Apply</a>` : ""}
      </td>
    </tr>`).join("");
  if ($("trackerTableWrap")) {
    $("trackerTableWrap").innerHTML = jobs.length
      ? `<div class="table-wrap"><table>
          <thead><tr><th>Application</th><th>Score</th><th>Status</th><th>Actions</th></tr></thead>
          <tbody>${rows}</tbody></table></div>`
      : `<p class="muted">No tracked applications yet. Add jobs from the Search or Add Job tabs.</p>`;
  }
  // eslint-disable-next-line no-undef
  document.dispatchEvent(new CustomEvent('jobagent:tracker-rendered'));
}

async function loadTracker() {
  if (!state.jobs || !state.jobs.length) {
    try {
      await loadJobs(false);
    } catch (error) {
      setNotice("trackerNotice", error.message, true);
    }
  }
  renderTracker();
}

async function trackerSetStatus(jobId, status, el) {
  if (el) el.disabled = true;
  try {
    await api("/api/status", { job_id: jobId, status, note: "Tracker update" });
    await loadJobs(false);
    renderTracker();
    toast(`Status → ${status.replace(/_/g, " ")}`);
  } catch (error) {
    setNotice("trackerNotice", error.message, true);
  } finally {
    if (el) el.disabled = false;
  }
}

async function trackerExport() {
  const button = $("trackerExportBtn");
  setBusy(button, true);
  setNotice("trackerNotice", "");
  try {
    const payload = await api("/api/export-internships", {});
    setNotice("trackerNotice", `Exported ${payload.count} application(s) to ${payload.workbook}`);
  } catch (error) {
    setNotice("trackerNotice", error.message, true);
  } finally {
    setBusy(button, false);
  }
}

async function trackerImport() {
  const button = $("trackerImportBtn");
  setBusy(button, true);
  setNotice("trackerNotice", "");
  try {
    const payload = await api("/api/tracker-import", {});
    const errors = payload.errors || [];
    setNotice("trackerNotice",
      `Synced ${payload.updated} status change(s) · ${payload.unmatched} unmatched` + (errors.length ? `\n${errors.join("\n")}` : ""),
      errors.length > 0);
    if (payload.updated > 0) {
      await loadJobs(false);
      renderTracker();
    }
  } catch (error) {
    setNotice("trackerNotice", error.message, true);
  } finally {
    setBusy(button, false);
  }
}

function activateTab(name) {
  document.querySelectorAll(".tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.tab === name));
  document.querySelectorAll(".tab-panel").forEach((panel) => panel.classList.toggle("active", panel.id === `tab-${name}`));
  if (name === "jobs" && window.JobAgentJobs) window.JobAgentJobs.renderJobs();
  if (name === "pipeline" && window.JobAgentPipeline) window.JobAgentPipeline.load();
  if (name === "tracker") loadTracker();
  if (name === "insights" && !state.insightsCache && window.JobAgentInsights) window.JobAgentInsights.load();
  if (name === "autopilot") {
    if (window.JobAgentAutopilot) window.JobAgentAutopilot.load();
    if (window.JobAgentAi) {
      window.JobAgentAi.loadSetup();
      window.JobAgentAi.loadTrace();
    }
    if (window.JobAgentAutoApply) window.JobAgentAutoApply.loadNeedsManual();
  }
  if (name === "studio") {
    if (window.JobAgentStudio) window.JobAgentStudio.load();
    if (window.JobAgentStudioTools) {
      window.JobAgentStudioTools.loadAssets();
      window.JobAgentStudioTools.loadGithubProjects();
    }
  }
  if (name === "portfolio" && window.JobAgentPortfolio) window.JobAgentPortfolio.load();
  if (name === "career" && window.JobAgentCareer) window.JobAgentCareer.load();
  if (name === "filtered-out" && window.JobAgentFilters) window.JobAgentFilters.load();
  if (name === "coach" && !state.coachCache && window.JobAgentCoach) window.JobAgentCoach.renderShell();
}

function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  try {
    localStorage.setItem("job-agent-theme", theme);
  } catch (error) {
    console.debug("Could not persist dashboard theme", error);
  }
  // Charts must be re-drawn to pick up new CSS-variable colors
  if (state.insightsCache && window.JobAgentInsights) window.JobAgentInsights.render(state.insightsCache);
}

function initTheme() {
  // Dark-first: the premium glass direction is designed dark; light remains a
  // deliberate "frosted daylight" variant for users who prefer it.
  let theme = "dark";
  try {
    theme = localStorage.getItem("job-agent-theme") || (window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");
  } catch {
    theme = "dark";
  }
  applyTheme(theme);
}

function toggleTheme() {
  const current = document.documentElement.getAttribute("data-theme") || "light";
  applyTheme(current === "light" ? "dark" : "light");
}

async function enrichGithub() {
  const button = $("enrichGithubBtn");
  setBusy(button, true);
  setNotice("autopilotNotice", "");
  try {
    const payload = await api("/api/enrich-github", {});
    const r = payload.report || {};
    const lines = [
      `GitHub: ${r.handle} (${r.public_repos} repos)`,
      `Languages: ${(r.languages_seen || []).slice(0, 6).join(", ")}`,
      `Skills added: ${(r.added_skills || []).join(", ") || "none"}`,
      `Projects added: ${(r.added_projects || []).join(", ") || "none"}`,
    ];
    setNotice("autopilotNotice", lines.join("\n"));
    toast("GitHub enrichment complete.");
  } catch (error) {
    setNotice("autopilotNotice", error.message, true);
  } finally {
    setBusy(button, false);
  }
}

function openLinkedinModal() {
  $("linkedinModal").classList.remove("hidden");
  $("linkedinNotice").classList.add("hidden");
  $("linkedinTextarea").focus();
}

async function submitLinkedinSkills() {
  const text = $("linkedinTextarea").value;
  if (!text.trim()) {
    setNotice("linkedinNotice", "Paste at least one skill first.", true);
    return;
  }
  const button = $("linkedinSubmitBtn");
  setBusy(button, true);
  try {
    const payload = await api("/api/enrich-linkedin", { text });
    const r = payload.report || {};
    setNotice("linkedinNotice", `Parsed ${r.parsed_count} skills. Added ${(r.added_skills || []).length} new ones.`);
    toast(`Added ${(r.added_skills || []).length} LinkedIn skills.`);
  } catch (error) {
    setNotice("linkedinNotice", error.message, true);
  } finally {
    setBusy(button, false);
  }
}

function toggleShortcuts(show) {
  $("shortcutsHelp").classList.toggle("hidden", !show);
}

function bindKeyboardShortcuts() {
  const tabOrder = ["search", "jobs", "autopilot", "studio", "portfolio", "coach", "insights", "add", "profile"];
  document.addEventListener("keydown", (event) => {
    const target = event.target;
    const inEditable = target instanceof HTMLElement && (target.matches("input, textarea, select") || target.isContentEditable);
    if (event.key === "Escape") {
      toggleShortcuts(false);
      return;
    }
    if (inEditable) return;
    if (event.key === "?" || (event.shiftKey && event.key === "/")) {
      event.preventDefault();
      toggleShortcuts(true);
      return;
    }
    const digit = Number(event.key);
    if (!Number.isNaN(digit) && digit >= 1 && digit <= tabOrder.length) {
      activateTab(tabOrder[digit - 1]);
      return;
    }
    if (event.key === "/") {
      event.preventDefault();
      $("jobsSearchInput").focus();
      activateTab("jobs");
      return;
    }
    if (event.key === "r") {
      loadJobs().then(renderState);
      return;
    }
    if (event.key === "g") {
      state.chord = { key: "g", at: Date.now() };
      return;
    }
    if (state.chord.key === "g" && Date.now() - state.chord.at < 1200) {
      state.chord = { key: "", at: 0 };
      if (event.key === "h") {
        if (window.JobAgentSearch) window.JobAgentSearch.oneClickHunt();
        return;
      }
      if (event.key === "m") {
        if (window.JobAgentSearch) window.JobAgentSearch.runMultiSearch();
        return;
      }
      if (event.key === "a") {
        activateTab("autopilot");
        return;
      }
      if (event.key === "p") {
        activateTab("portfolio");
        return;
      }
    }
  });
}

function bindEvents() {
  document.querySelectorAll(".tab").forEach((button) => {
    button.addEventListener("click", () => activateTab(button.dataset.tab));
  });

  $("addUrlBtn").addEventListener("click", addUrl);
  $("addTextBtn").addEventListener("click", addText);
  if ($("bulkAddBtn")) $("bulkAddBtn").addEventListener("click", addBulk);
  if ($("trackerRefreshBtn")) $("trackerRefreshBtn").addEventListener("click", loadTracker);
  if ($("trackerExportBtn")) $("trackerExportBtn").addEventListener("click", trackerExport);
  if ($("trackerImportBtn")) $("trackerImportBtn").addEventListener("click", trackerImport);
  document.body.addEventListener("change", (event) => {
    const statusSelect = event.target.closest("[data-action='status-select']");
    if (statusSelect) trackerSetStatus(statusSelect.dataset.job, statusSelect.value, statusSelect);
  });
  $("profileRefreshBtn").addEventListener("click", loadState);
  $("exportInternshipsBtn").addEventListener("click", exportInternships);
  if ($("importTrackerBtn")) $("importTrackerBtn").addEventListener("click", importTracker);
  const importCvBtn = document.getElementById("importCvTemplateBtn");
  if (importCvBtn) importCvBtn.addEventListener("click", importCvTemplate);
  $("copyApiTextBtn").addEventListener("click", async () => {
    const text = `App name: ${$("apiAppName").value}\nURL: ${$("apiAppUrl").value}\nDescription: ${$("apiAppDescription").value}`;
    await navigator.clipboard.writeText(text);
    toast("Copied API application text.");
  });
  $("closeShortcuts").addEventListener("click", () => toggleShortcuts(false));
  $("shortcutsHelp").addEventListener("click", (event) => {
    if (event.target === $("shortcutsHelp")) toggleShortcuts(false);
  });

  $("enrichGithubBtn").addEventListener("click", enrichGithub);
  $("enrichLinkedinBtn").addEventListener("click", openLinkedinModal);
  $("linkedinSubmitBtn").addEventListener("click", submitLinkedinSkills);
  $("linkedinCancelBtn").addEventListener("click", () => $("linkedinModal").classList.add("hidden"));
  $("closeLinkedin").addEventListener("click", () => $("linkedinModal").classList.add("hidden"));
  $("linkedinModal").addEventListener("click", (event) => {
    if (event.target === $("linkedinModal")) $("linkedinModal").classList.add("hidden");
  });
  const themeBtn = document.getElementById("themeToggleBtn");
  if (themeBtn) themeBtn.addEventListener("click", toggleTheme);

  // Maintenance
  const rescanBtn = document.getElementById("rescanCompaniesBtn");
  if (rescanBtn) rescanBtn.addEventListener("click", async () => {
    if (!window.confirm("Re-extract the real employer name from each job's description? Old aggregator-only entries (France Travail etc.) get updated.")) return;
    setBusy(rescanBtn, true);
    try {
      const result = await api("/api/maintenance/rescan-companies", {});
      toast(`Updated ${result.updated} / ${result.checked} jobs.`);
      await loadJobs();
    } catch (error) {
      toast(`Rescan failed: ${error.message}`);
    } finally {
      setBusy(rescanBtn, false);
    }
  });
  const chromeSessionBtn = document.getElementById("chromeSessionBtn");
  if (chromeSessionBtn) chromeSessionBtn.addEventListener("click", async () => {
    setBusy(chromeSessionBtn, true);
    toast("Building Chrome apply session…");
    try {
      const result = await api("/api/chrome-session", { min_score: 65, limit: 10 });
      toast(result.message || `Chrome session ready: ${result.path}`);
      if (result.count === 0) toast("No ready packets found. Generate packets first (Tailor CV) then try again.");
    } catch (error) {
      toast(`Chrome session failed: ${error.message}`);
    } finally {
      setBusy(chromeSessionBtn, false);
    }
  });
  const validateSourcesBtn = document.getElementById("validateSourcesBtn");
  if (validateSourcesBtn) validateSourcesBtn.addEventListener("click", async () => {
    setBusy(validateSourcesBtn, true);
    try {
      const result = await api("/api/maintenance/validate-sources", {});
      toast(`Validated ${result.total} boards · ${result.healthy} OK · ${result.broken} marked dead.`);
      if (window.JobAgentAutopilot) await window.JobAgentAutopilot.load();
    } catch (error) {
      toast(`Validate failed: ${error.message}`);
    } finally {
      setBusy(validateSourcesBtn, false);
    }
  });
  const clearBrokenBtn = document.getElementById("clearBrokenBtn");
  if (clearBrokenBtn) clearBrokenBtn.addEventListener("click", async () => {
    setBusy(clearBrokenBtn, true);
    try {
      const result = await api("/api/maintenance/clear-broken", {});
      toast(`Cleared ${result.cleared} dead-board entries.`);
      if (window.JobAgentAutopilot) await window.JobAgentAutopilot.load();
    } catch (error) {
      toast(`Clear failed: ${error.message}`);
    } finally {
      setBusy(clearBrokenBtn, false);
    }
  });

  const obsidianBtn = document.getElementById("obsidianSyncBtn");
  if (obsidianBtn) obsidianBtn.addEventListener("click", async () => {
    setBusy(obsidianBtn, true);
    try {
      const result = await api("/api/obsidian-sync", {});
      toast(`Synced ${result.count} job(s) to Obsidian. Open ${result.vault} and view the graph (start at Dashboard.md).`);
    } catch (error) {
      toast(`Obsidian sync failed: ${error.message}`);
    } finally {
      setBusy(obsidianBtn, false);
    }
  });

  const dedupeBtn = document.getElementById("dedupeJobsBtn");
  if (dedupeBtn) dedupeBtn.addEventListener("click", async () => {
    if (!window.confirm("Collapse duplicate jobs using the new fingerprint? Older copies will be deleted; newest copy is kept.")) return;
    setBusy(dedupeBtn, true);
    try {
      const result = await api("/api/maintenance/dedupe", {});
      toast(`Removed ${result.removed} duplicates (${result.fingerprints_refreshed} fingerprints refreshed).`);
      await loadJobs();
    } catch (error) {
      toast(`Dedupe failed: ${error.message}`);
    } finally {
      setBusy(dedupeBtn, false);
    }
  });

  document.body.addEventListener("click", (event) => {
    const preflightTarget = event.target.closest("[data-action='preflight']");
    if (preflightTarget) {
      if (window.JobAgentJobs) window.JobAgentJobs.runPreflight(preflightTarget.dataset.job, preflightTarget);
      return;
    }
    const target = event.target.closest("[data-action='packet']");
    if (target) {
      if (window.JobAgentJobs) window.JobAgentJobs.generatePacket(target.dataset.job, target);
      return;
    }
    const coverLetterTarget = event.target.closest("[data-action='cover-letter']");
    if (coverLetterTarget) {
      if (window.JobAgentJobs) window.JobAgentJobs.generateCoverLetter(coverLetterTarget.dataset.job, coverLetterTarget);
      return;
    }
    const enrichTarget = event.target.closest("[data-action='enrich']");
    if (enrichTarget) {
      if (window.JobAgentJobs) window.JobAgentJobs.enrichJob(enrichTarget.dataset.job, enrichTarget);
      return;
    }
    const aiTarget = event.target.closest("[data-action='ai-analyze']");
    if (aiTarget) {
      if (window.JobAgentAi) window.JobAgentAi.analyze(aiTarget.dataset.job, aiTarget);
      return;
    }
    const chatTarget = event.target.closest("[data-action='ai-chat']");
    if (chatTarget) {
      const jobId = chatTarget.dataset.job;
      const job = state.jobs.find((item) => item.id === jobId);
      if (job && window.JobAgentAi) window.JobAgentAi.openChat(job);
      return;
    }
    const jobPinTarget = event.target.closest("[data-action='job-pin']");
    if (jobPinTarget) {
      if (window.JobAgentJobs) window.JobAgentJobs.toggleJobPin(jobPinTarget.dataset.job);
      return;
    }
    const briefTarget = event.target.closest("[data-action='brief']");
    if (briefTarget) {
      if (window.JobAgentOutreach) window.JobAgentOutreach.brief(briefTarget.dataset.job, briefTarget);
      return;
    }
    const outreachTarget = event.target.closest("[data-action='outreach']");
    if (outreachTarget) {
      if (window.JobAgentOutreach) window.JobAgentOutreach.outreach(outreachTarget.dataset.job, outreachTarget);
      return;
    }
    const linkedinTarget = event.target.closest("[data-action='linkedin']");
    if (linkedinTarget) {
      if (window.JobAgentOutreach) window.JobAgentOutreach.linkedin(linkedinTarget.dataset.job, linkedinTarget);
      return;
    }
    const interviewTarget = event.target.closest("[data-action='interview']");
    if (interviewTarget) {
      if (window.JobAgentOutreach) window.JobAgentOutreach.interviewPrep(interviewTarget.dataset.job, interviewTarget);
      return;
    }
    const followupTarget = event.target.closest("[data-action='followup']");
    if (followupTarget) {
      if (window.JobAgentOutreach) window.JobAgentOutreach.followup(followupTarget.dataset.job, followupTarget);
      return;
    }
    const statusTarget = event.target.closest("[data-action='status']");
    if (statusTarget) {
      if (window.JobAgentJobs) window.JobAgentJobs.updateJobStatus(statusTarget.dataset.job, statusTarget.dataset.status, statusTarget);
      return;
    }
    const needsManualDone = event.target.closest("[data-action='needs-manual-done']");
    if (needsManualDone) {
      if (window.JobAgentAutoApply) window.JobAgentAutoApply.markNeedsManualDone(needsManualDone.dataset.job, needsManualDone);
      return;
    }
    const deleteTarget = event.target.closest("[data-action='delete-job']");
    if (deleteTarget) {
      if (window.JobAgentJobs) window.JobAgentJobs.deleteJob(deleteTarget.dataset.job, deleteTarget);
      return;
    }
    const checkbox = event.target.closest("[data-select-job]");
    if (checkbox) {
      const jobId = checkbox.dataset.selectJob;
      if (checkbox.checked) state.selectedJobs.add(jobId);
      else state.selectedJobs.delete(jobId);
      if (window.JobAgentJobs) window.JobAgentJobs.refreshSelectionUi();
      return;
    }
    const row = event.target.closest("[data-job-row]");
    if (row && !event.target.matches("input[type='checkbox']")) {
      const job = state.jobs.find((item) => item.id === row.dataset.jobRow);
      if (window.JobAgentJobs) {
        window.JobAgentJobs.renderEnrichmentDetails(job);
        window.JobAgentJobs.renderJobs();
      }
    }
  });
}

// ── Auto-Apply ───────────────────────────────────────────────────────────────
// The session logic lives in autoapply.js (R3 split). Only the shared run
// state stays here: sibling classic scripts read it as a bare script-scope
// global at call time (autopilot.js reads .mode), same contract as `state`.
// eslint-disable-next-line no-unused-vars -- consumed by autoapply.js/autopilot.js via shared script scope
const autoApplyState = { mode: "fill_and_confirm", stream: null, countdown: null };

initTheme();
bindEvents();
bindKeyboardShortcuts();
loadState()
  .then(() => window.JobAgentSearch && window.JobAgentSearch.buildLinks())
  .catch((error) => {
    setNotice("searchNotice", error.message, true);
  });
