// Hard-filter and search-noise transparency for jobs in the current local DB.
// Classic R3 module, defer, after app.js; bindings and rendering stay local.
(function () {
  const $ = (id) => document.getElementById(id);
  const api = (...args) => window.api(...args);
  const escapeHtml = (value) => window.escapeHtml(value);
  const metric = (...args) => window.metric(...args);
  const setBusy = (...args) => window.setBusy(...args);
  const setNotice = (...args) => window.setNotice(...args);
  let shownJobIds = [];

function emptyState(glyph, title, detail) {
  return `<div class="empty-state"><span class="empty-glyph">${glyph}</span><strong>${escapeHtml(title)}</strong><span>${escapeHtml(detail)}</span></div>`;
}

function renderLoading() {
  $("filteredOutMetrics").innerHTML = [
    metric("Evaluated", "â€”"),
    metric("Filtered out", "â€”"),
    metric("Passed", "â€”"),
    metric("Active rules", "â€”"),
  ].join("");
  $("filteredOutRules").innerHTML = emptyState("â—Ž", "Loading filtered jobsâ€¦", "Evaluating current jobs with the local quality gates.");
  $("filteredOutJobs").innerHTML = emptyState("â—Ž", "Loading rejection reasonsâ€¦", "No job data leaves this device.");
}

function renderRules(rules) {
  if (!rules.length) {
    $("filteredOutRules").innerHTML = emptyState("âœ“", "No active rejection rules", "Every current job passed the hard filters and noise gate.");
    return;
  }
  const maximum = Math.max(...rules.map((rule) => Number(rule.count || 0)), 1);
  $("filteredOutRules").innerHTML = rules.map((rule) => {
    const count = Number(rule.count || 0);
    const width = Math.max(4, Math.round((count / maximum) * 100));
    return `<div class="funnel-row"><span title="${escapeHtml(rule.rule || "")}">${escapeHtml(rule.label || rule.rule || "Rule")}</span><div class="funnel-bar"><div class="funnel-fill" style="width:${width}%"></div></div><strong>${count}</strong></div>`;
  }).join("");
}

function renderJobs(jobs) {
  shownJobIds = jobs.map((job) => job.id);
  if (!jobs.length) {
    $("filteredOutJobs").innerHTML = emptyState("âœ“", "Nothing filtered out", "All jobs in the current database pass the active quality gates.");
    return;
  }
  const rows = jobs.map((job) => {
    const reasons = (job.reasons || []).map((reason) =>
      `<span class="badge bad" title="${escapeHtml(reason.rule || "")}">${escapeHtml(reason.message || "Filtered")}</span>`
    ).join(" ");
    const context = [job.company, job.location, job.source].filter(Boolean).join(" Â· ");
    return `<li><div><span class="coach-title">${escapeHtml(job.title || "Untitled job")}</span><span class="coach-sub">${escapeHtml(context)}</span><div class="row-tags" style="margin-top:0.45rem">${reasons}</div></div><div class="row-actions"><button data-filtered-action="restore" data-job="${escapeHtml(job.id)}">Restore</button><button data-filtered-action="delete" data-job="${escapeHtml(job.id)}">Delete</button></div></li>`;
  }).join("");
  $("filteredOutJobs").innerHTML = `<div class="row-actions"><button id="filteredOutRestoreAllBtn">Restore all shown</button></div><ol class="coach-list">${rows}</ol>`;
}

function renderPayload(payload) {
  const rules = payload.rules || [];
  const jobs = payload.jobs || [];
  $("filteredOutMetrics").innerHTML = [
    metric("Evaluated", payload.evaluated_count || 0),
    metric("Filtered out", payload.filtered_count || 0),
    metric("Passed", payload.passed_count || 0),
    metric("Active rules", rules.length),
  ].join("");
  renderRules(rules);
  renderJobs(jobs);
}

function renderError(error) {
  setNotice("filteredOutNotice", `Filtered jobs could not load: ${error.message}`, true);
  const message = emptyState("!", "Filtered jobs could not load", error.message);
  $("filteredOutRules").innerHTML = message;
  $("filteredOutJobs").innerHTML = message;
}

async function loadFilteredOut() {
  const button = $("filteredOutRefreshBtn");
  setBusy(button, true);
  setNotice("filteredOutNotice", "");
  renderLoading();
  try {
    renderPayload(await api("/api/filtered-out"));
  } catch (error) {
    if (error instanceof TypeError) {
      window.renderConnectionLost("filteredOutNotice", loadFilteredOut);
      return;
    }
    renderError(error);
  } finally {
    setBusy(button, false);
  }
}

async function applyAction(jobId, action) {
  await api("/api/filtered-out/action", { job_id: jobId, action });
}

async function runAction(jobId, action) {
  if (action === "delete" && !window.confirm("Delete this filtered job permanently?")) return;
  try {
    await applyAction(jobId, action);
    await loadFilteredOut();
  } catch (error) {
    if (error instanceof TypeError) {
      window.renderConnectionLost("filteredOutNotice", () => runAction(jobId, action));
      return;
    }
    setNotice("filteredOutNotice", error.message, true);
  }
}

async function restoreAllShown() {
  const ids = [...shownJobIds];
  if (!ids.length) return;
  try {
    await Promise.all(ids.map((jobId) => applyAction(jobId, "restore")));
    await loadFilteredOut();
  } catch (error) {
    if (error instanceof TypeError) {
      window.renderConnectionLost("filteredOutNotice", restoreAllShown);
      return;
    }
    setNotice("filteredOutNotice", error.message, true);
  }
}

  const refreshBtn = $("filteredOutRefreshBtn");
  if (refreshBtn) refreshBtn.addEventListener("click", loadFilteredOut);
  $("filteredOutJobs")?.addEventListener("click", (event) => {
    const action = event.target.closest("[data-filtered-action]");
    if (action) runAction(action.dataset.job, action.dataset.filteredAction);
    if (event.target.closest("#filteredOutRestoreAllBtn")) restoreAllShown();
  });
  renderLoading();

  const load = loadFilteredOut;
  window.JobAgentFilters = { load };
})();
