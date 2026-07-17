// Tracker table, funnel, inline status updates, and Excel sync (R3 split from app.js).
// Classic script, defer, after app.js; `state` is app.js's shared script-scope global.
(function () {
  const $ = (id) => document.getElementById(id);
  const api = (...args) => window.api(...args);
  const toast = (...args) => window.toast(...args);
  const setBusy = (...args) => window.setBusy(...args);
  const setNotice = (...args) => window.setNotice(...args);
  const escapeHtml = (value) => window.escapeHtml(value);
  const safeHref = (value) => window.safeHref(value);
  const scorePill = (...args) => window.scorePill(...args);
  const companyLine = (job) => window.companyLine(job);
  const loadJobs = (...args) => window.loadJobs(...args);
  const renderState = (...args) => window.renderState(...args);

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
  if (window.JobAgentActivity) await window.JobAgentActivity.load();
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

  if ($("trackerRefreshBtn")) $("trackerRefreshBtn").addEventListener("click", loadTracker);
  if ($("trackerExportBtn")) $("trackerExportBtn").addEventListener("click", trackerExport);
  if ($("trackerImportBtn")) $("trackerImportBtn").addEventListener("click", trackerImport);
  document.body.addEventListener("change", (event) => {
    const statusSelect = event.target.closest("[data-action='status-select']");
    if (statusSelect) trackerSetStatus(statusSelect.dataset.job, statusSelect.value, statusSelect);
  });
  if ($("importTrackerBtn")) $("importTrackerBtn").addEventListener("click", importTracker);

  window.importTracker = importTracker;
  window.trackerStatusSelect = trackerStatusSelect;
  window.renderTracker = renderTracker;
  window.loadTracker = loadTracker;
  window.trackerSetStatus = trackerSetStatus;
  window.trackerExport = trackerExport;
  window.trackerImport = trackerImport;
  window.JobAgentTracker = { load: loadTracker };
})();
