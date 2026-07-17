// Career Engine reports: market gaps, certification plan, and project masterplan.
// Classic R3 module, defer, after app.js; all bindings and rendering stay local.
(function () {
  const $ = (id) => document.getElementById(id);
  const api = (...args) => window.api(...args);
  const escapeHtml = (value) => window.escapeHtml(value);
  const metric = (...args) => window.metric(...args);
  const setBusy = (...args) => window.setBusy(...args);
  const setNotice = (...args) => window.setNotice(...args);

function renderLoading() {
  $("careerMetrics").innerHTML = [
    metric("Scored jobs", "—"), metric("Below threshold", "—"),
    metric("Gap clusters", "—"), metric("Project plan", "—"),
  ].join("");
  const loading = `<div class="empty-state"><span class="empty-glyph">◎</span><strong>Loading Career Engine…</strong><span>Reading scored jobs and local profile evidence.</span></div>`;
  $("careerGapContent").innerHTML = loading;
  $("careerCerts").innerHTML = "<li class='muted'>Loading targeted credentials…</li>";
  $("careerVerdicts").innerHTML = "<li class='muted'>Auditing existing projects…</li>";
  $("careerMasterplan").innerHTML = "<li class='muted'>Building the project masterplan…</li>";
}

function renderGapTable(report) {
  const clusters = report.clusters || [];
  if (!report.scored_job_count) {
    $("careerGapContent").innerHTML = `<div class="empty-state"><span class="empty-glyph">◇</span><strong>No scored jobs yet</strong><span>Score a few tracked jobs first. Career gaps need real market evidence, so this report will not guess.</span></div>`;
    return;
  }
  if (!clusters.length) {
    $("careerGapContent").innerHTML = `<div class="empty-state"><span class="empty-glyph">✓</span><strong>No jobs below ${report.threshold}</strong><span>${report.scored_job_count} scored job(s) checked. Raise the threshold to inspect smaller gaps.</span></div>`;
    return;
  }
  const rows = clusters.map((cluster, index) => {
    const jobs = new Set((cluster.evidence || []).map((row) => row.job_id)).size;
    const lift = cluster.simulated_score_lift || {};
    return `<tr><td>${index + 1}</td><td><strong>${escapeHtml(cluster.name)}</strong></td><td>${jobs}</td><td>${Number(cluster.market_share_pct || 0).toFixed(2)}%</td><td><strong>+${Number(lift.average_points || 0).toFixed(2)} pts</strong> <span class="badge warn">${escapeHtml(lift.label || "simulated")}</span></td></tr>`;
  }).join("");
  $("careerGapContent").innerHTML = `<div class="table-wrap"><table><thead><tr><th>Rank</th><th>Gap cluster</th><th>Jobs</th><th>Share</th><th>Simulated lift</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

function renderCertPlan(plan, hasScoredJobs) {
  const rows = plan.recommendations || [];
  if (!hasScoredJobs) {
    $("careerCerts").innerHTML = "<li class='muted'>Cert recommendations appear after scored jobs reveal evidence-backed gaps.</li>";
    return;
  }
  $("careerCerts").innerHTML = rows.length ? rows.map((row) => {
    const cert = row.certification || {};
    return `<li><div><span class="coach-title">${escapeHtml(cert.name || "")}</span><span class="coach-sub">${escapeHtml(cert.issuer || "Unknown issuer")} · ${escapeHtml(cert.cost || "")} · ${escapeHtml((row.matched_gaps || []).join(", "))}</span></div><strong>${Number(row.signal_per_hour || 0).toFixed(4)}<br>signal/hour</strong></li>`;
  }).join("") : "<li class='muted'>No catalog certifications match the current gap clusters.</li>";
}

function verdictTone(verdict) {
  if (verdict === "signal") return "good";
  if (verdict === "dilutive") return "bad";
  return "warn";
}

function renderProjectPlan(report) {
  const verdicts = report.project_verdicts || [];
  $("careerVerdicts").innerHTML = verdicts.length ? verdicts.map((row) =>
    `<li><div><span class="coach-title">${escapeHtml(row.name || "")}</span><span class="coach-sub">${escapeHtml((row.reasons || []).join("; "))}${row.matched_target_stack && row.matched_target_stack.length ? `<br>Stack: ${escapeHtml(row.matched_target_stack.join(", "))}` : ""}</span></div><strong><span class="badge ${verdictTone(row.verdict)}">${escapeHtml(row.verdict || "neutral")}</span></strong></li>`
  ).join("") : "<li class='muted'>No existing projects were found in the local CV.</li>";
  const plans = report.masterplan || [];
  $("careerMasterplan").innerHTML = plans.length ? plans.map((row, index) =>
    `<li><div><span class="coach-title">${index + 1}. ${escapeHtml(row.name || "")}</span><span class="coach-sub">${escapeHtml(row.problem || "")}<br><strong>Hard part:</strong> ${escapeHtml(row.hard_part || "")}<br><strong>Deliverable:</strong> ${escapeHtml(row.deliverable || "")}<br>Stack: ${escapeHtml((row.stack || []).join(", "))} · Covers: ${escapeHtml((row.covered_gaps || []).join(", ") || "role-strengthening")}</span></div><strong>${Number(row.time_budget_h || 0)}h<br>visibility ${Number(row.recruiter_visibility || 0)}/3</strong></li>`
  ).join("") : "<li class='muted'>No project specifications are available.</li>";
}

function renderIdentity(identity) {
  $("careerEvidenceCount").textContent = Number(identity.evidence || 0);
  $("careerClaimedCount").textContent = Number(identity.claimed || 0);
}

function renderAll(gaps, certs, projects) {
  renderIdentity(gaps.identity || {});
  const navMetric = (label, value, target, anchor = "") => `<button type="button" class="metric metric-link" ${target ? `data-goto="${escapeHtml(target)}"` : `data-career-anchor="${escapeHtml(anchor)}"`}><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong><small>${target ? `Open ${escapeHtml(target)}` : "Jump to section"}</small></button>`;
  const skillTreeMetric = (label, value) => `<button type="button" class="metric metric-link" data-skill-tree-link><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong><small>Open Skill Tree â†’</small></button>`;
  $("careerMetrics").innerHTML = [
    navMetric("Scored jobs", gaps.scored_job_count || 0, "jobs"),
    navMetric(`Below ${gaps.threshold}`, gaps.low_score_job_count || 0, "", "careerGapContent"),
    skillTreeMetric("Gap clusters", (gaps.clusters || []).length),
    navMetric("Project plan", (projects.masterplan || []).length, "", "careerMasterplan"),
  ].join("");
  renderGapTable(gaps);
  renderCertPlan(certs, Boolean(gaps.scored_job_count));
  renderProjectPlan(projects);
  const warnings = certs.warnings || [];
  setNotice("careerNotice", warnings.join("\n"), false);
}

function renderError(error) {
  setNotice("careerNotice", `Career Engine could not load: ${error.message}`, true);
  const message = `<div class="empty-state"><span class="empty-glyph">!</span><strong>Career Engine could not load</strong><span>${escapeHtml(error.message)}</span></div>`;
  $("careerGapContent").innerHTML = message;
  $("careerCerts").innerHTML = "<li class='muted'>Certification plan unavailable.</li>";
  $("careerVerdicts").innerHTML = "<li class='muted'>Project audit unavailable.</li>";
  $("careerMasterplan").innerHTML = "<li class='muted'>Project masterplan unavailable.</li>";
}

async function loadCareer() {
  const button = $("careerRefreshBtn");
  const threshold = Number($("careerThreshold").value || 70);
  setBusy(button, true);
  setNotice("careerNotice", "");
  renderLoading();
  try {
    const [gaps, certs, projects] = await Promise.all([
      api(`/api/career/gap-report?threshold=${threshold}`),
      api("/api/career/cert-plan"),
      api("/api/career/project-plan"),
    ]);
    renderAll(gaps, certs, projects);
  } catch (error) {
    renderError(error);
  } finally {
    setBusy(button, false);
  }
}

  const refreshBtn = $("careerRefreshBtn");
  if (refreshBtn) refreshBtn.addEventListener("click", loadCareer);
  const thresholdSelect = $("careerThreshold");
  if (thresholdSelect) thresholdSelect.addEventListener("change", loadCareer);
  $("careerMetrics").addEventListener("click", (event) => {
    const target = event.target.closest("[data-goto]");
    if (target) {
      window.activateTab(target.dataset.goto);
      return;
    }
    if (event.target.closest("[data-skill-tree-link]")) {
      window.activateTab("skill-tree");
      return;
    }
    const anchor = event.target.closest("[data-career-anchor]");
    if (anchor) $(anchor.dataset.careerAnchor)?.scrollIntoView({ behavior: "smooth", block: "start" });
  });
  renderLoading();

  const load = loadCareer;
  window.JobAgentCareer = { load };
})();
