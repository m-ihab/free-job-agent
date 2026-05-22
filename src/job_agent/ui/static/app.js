const state = {
  profile: null,
  statuses: [],
  jobs: [],
  selectedJobs: new Set(),
  activeJobId: null,
  insightsCache: null,
  chord: { key: "", at: 0 },
};

const $ = (id) => document.getElementById(id);

async function api(path, body = null, method = body ? "POST" : "GET") {
  const options = { method, headers: {} };
  if (body) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  const response = await fetch(path, options);
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
  const ollamaBadge = profile.ollama_enabled
    ? renderBadge(profile.ollama_ready ? `Ollama: ${profile.ollama_model}` : "Ollama enabled, not reachable", profile.ollama_ready ? "good" : "warn")
    : "";
  $("statusStrip").innerHTML = [
    renderBadge(profile.valid ? "Profile ready" : "Profile needs review", profile.valid ? "good" : "bad"),
    renderBadge(profile.france_travail_configured ? "France Travail API ready" : "API not configured", profile.france_travail_configured ? "good" : "warn"),
    renderBadge(profile.latex_ready ? `LaTeX: ${profile.latex_compiler}` : "LaTeX compiler missing", profile.latex_ready ? "good" : "warn"),
    ollamaBadge,
    renderBadge(`${state.jobs.length} jobs`, "good"),
  ].filter(Boolean).join("");

  $("statusFilter").innerHTML = `<option value="">All statuses</option>${state.statuses
    .map((status) => `<option value="${escapeHtml(status)}">${escapeHtml(status)}</option>`)
    .join("")}`;

  $("profileMetrics").innerHTML = [
    metric("Profile", profile.valid ? "Ready" : "Review"),
    metric("France Travail", profile.france_travail_configured ? "Ready" : "Missing"),
    metric("LaTeX", profile.latex_ready ? profile.latex_compiler : "Missing"),
    metric("Tracked jobs", state.jobs.length),
  ].join("");

  $("apiReadiness").innerHTML = [
    readinessRow(".env.local", profile.env_local_present ? "Loaded" : "Missing"),
    readinessRow("Endpoints map", profile.endpoints_file_present ? "Configured" : "Missing"),
    readinessRow("Endpoint base", profile.endpoints_summary?.base_url || "-"),
    readinessRow(
      "Enabled endpoints",
      `${profile.endpoints_summary?.enabled || 0}/${profile.endpoints_summary?.configured || 0} (${profile.endpoints_summary?.total || 0} total)`
    ),
  ].join("");

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
  return `<div class="metric"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong>${subLine}</div>`;
}

function pathRow(label, value) {
  return `<dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value || "")}</dd>`;
}

function searchPayload() {
  return {
    query: $("queryInput").value.trim() || "data scientist",
    location: $("locationInput").value.trim() || "Paris",
    language: $("languageSelect").value,
    boards: $("boardsSelect").value,
    limit: Number($("variantLimit").value || 8),
    limit_queries: Number($("variantLimit").value || 8),
    limit_per_query: Number($("apiLimit").value || 5),
    limit_per_source: Number($("apiLimit").value || 5),
    internships_only: $("internshipsOnly").checked,
    prepare_packets: $("preparePackets").checked,
    force_packets: $("forcePackets").checked,
  };
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
  if (render) renderJobs();
}

function renderSearchMetrics(payload) {
  $("searchMetrics").innerHTML = [
    metric("Queries", payload.query_count ?? "-"),
    metric("Links", payload.link_count ?? "-"),
    metric("Imported", payload.imported ?? "-"),
    metric("Packets", payload.prepared ?? "-"),
  ].join("");
}

function renderManualGroups(groups) {
  if (!groups || !groups.length) {
    $("manualResults").innerHTML = "";
    return;
  }
  $("manualResults").innerHTML = groups
    .map(
      (group, index) => {
        const rows = group.links
          .map(
            (link) => `<tr>
              <td>${escapeHtml(link.board)}</td>
              <td><a href="${escapeHtml(link.url)}" target="_blank" rel="noreferrer">Open search</a></td>
              <td>${escapeHtml(link.note)}</td>
            </tr>`,
          )
          .join("");
        return `<details class="query-group" ${index < 2 ? "open" : ""}>
          <summary>${escapeHtml(group.query)} - ${group.links.length} boards</summary>
          <div class="table-wrap">
            <table>
              <thead><tr><th>Board</th><th>Link</th><th>Note</th></tr></thead>
              <tbody>${rows}</tbody>
            </table>
          </div>
        </details>`;
      },
    )
    .join("");
}

function renderMultiSourceResults(payload) {
  const errors = payload.errors || {};
  const counts = payload.per_source || {};
  const sources = Object.keys(counts);
  if (!sources.length && !Object.keys(errors).length) {
    $("multiSourceResults").innerHTML = "";
    return;
  }
  const tiles = sources
    .map((name) => {
      const err = errors[name];
      const tone = err ? "warn" : counts[name] ? "good" : "";
      return `<div class="metric"><span>${escapeHtml(name)}</span><strong>${counts[name] ?? 0}</strong>${err ? `<div class="muted" style="margin-top:0.2rem">${escapeHtml(err.slice(0, 80))}</div>` : ""}<div>${renderBadge(err ? "Error" : counts[name] ? "OK" : "Empty", tone)}</div></div>`;
    })
    .join("");
  $("multiSourceResults").innerHTML = `<div class="panel">
    <div class="section-header" style="margin-bottom:0.5rem">
      <h3 style="margin:0">Multi-source summary</h3>
      <span class="muted">Imported ${payload.imported ?? 0} new, ${payload.duplicates ?? 0} duplicates</span>
    </div>
    <div class="metric-grid">${tiles}</div>
  </div>`;
}

function renderApiResults(jobs, failures = []) {
  if ((!jobs || !jobs.length) && (!failures || !failures.length)) {
    $("apiResults").innerHTML = "";
    return;
  }
  const jobRows = (jobs || [])
    .slice(0, 80)
    .map(
      (job) => `<tr>
        <td><strong>${escapeHtml(job.title)}</strong><br><span class="muted">${escapeHtml(job.company)}</span></td>
        <td>${escapeHtml(job.location || "")}</td>
        <td>${scorePill(job.fit_score)}</td>
        <td>${escapeHtml(job.status || "")}</td>
        <td class="actions">${jobActions(job)}</td>
      </tr>`,
    )
    .join("");
  const failureBlock = failures.length
    ? `<div class="notice error">${failures.slice(0, 8).map(escapeHtml).join("<br>")}</div>`
    : "";
  $("apiResults").innerHTML = `${failureBlock}<div class="table-wrap">
    <table>
      <thead><tr><th>Job</th><th>Location</th><th>Score</th><th>Status</th><th>Actions</th></tr></thead>
      <tbody>${jobRows}</tbody>
    </table>
  </div>`;
}

function jobActions(job) {
  const apply = job.apply_url ? `<a href="${escapeHtml(job.apply_url)}" target="_blank" rel="noreferrer">Apply</a>` : "";
  const assistant = job.assistant_page ? `<a href="${fileHref(job.assistant_page)}" target="_blank">Assistant</a>` : "";
  const cv = job.cv_pdf ? `<a href="${fileHref(job.cv_pdf)}" target="_blank">CV</a>` : "";
  const letter = job.cover_letter_pdf ? `<a href="${fileHref(job.cover_letter_pdf)}" target="_blank">Letter</a>` : "";
  const submitted = job.status === "MANUALLY_SUBMITTED" ? "" : `<button data-action="status" data-status="MANUALLY_SUBMITTED" data-job="${escapeHtml(job.id)}" title="Mark as manually submitted">Submitted</button>`;
  const rejected = job.status === "REJECTED" ? "" : `<button data-action="status" data-status="REJECTED" data-job="${escapeHtml(job.id)}" title="Mark as rejected">Reject</button>`;
  return `<div class="row-actions">
    <button data-action="packet" data-job="${escapeHtml(job.id)}" title="Generate tailored CV + cover letter">Optimize</button>
    <button data-action="enrich" data-job="${escapeHtml(job.id)}" title="Enrich with France Travail data">Enrich</button>
    ${submitted}${rejected}
    ${apply}${assistant}${cv}${letter}
  </div>`;
}

function isInternship(job) {
  const text = `${job.title} ${job.company} ${job.job_type || ""}`.toLowerCase();
  return ["intern", "internship", "stage", "stagiaire", "alternance", "apprentissage", "apprenti", "trainee"]
    .some((term) => text.includes(term));
}

function jobMatchesText(job, query) {
  if (!query) return true;
  const haystack = `${job.title} ${job.company} ${job.location} ${(job.tech_stack || []).join(" ")}`.toLowerCase();
  return haystack.includes(query.toLowerCase());
}

function sortJobs(jobs, mode) {
  const list = [...jobs];
  if (mode === "score") {
    return list.sort((a, b) => (b.fit_score ?? -1) - (a.fit_score ?? -1));
  }
  if (mode === "company") {
    return list.sort((a, b) => String(a.company).localeCompare(String(b.company)));
  }
  return list.sort((a, b) => String(b.updated_at || b.created_at).localeCompare(String(a.updated_at || a.created_at)));
}

function renderJobsMetrics(jobs) {
  const enriched = jobs.filter((job) => job.enriched).length;
  const internships = jobs.filter((job) => isInternship(job)).length;
  const applied = jobs.filter((job) => ["APPLIED", "MANUALLY_SUBMITTED"].includes(job.status)).length;
  $("jobsMetrics").innerHTML = [
    metric("Visible", jobs.length),
    metric("Enriched", enriched),
    metric("Internships", internships),
    metric("Applied", applied),
  ].join("");
}

function renderEnrichmentDetails(job) {
  if (!job) {
    $("enrichmentDetails").innerHTML = "Click a job to see details, enrichment, and a preview of the tailored docs.";
    return;
  }
  state.activeJobId = job.id;
  const sources = job.enrichment_sources || {};
  const okCount = Object.values(sources).filter((value) => String(value).startsWith("ok")).length;
  const items = Object.entries(sources).map(
    ([key, value]) => `<li><strong>${escapeHtml(key)}</strong> - ${escapeHtml(value)}</li>`
  );
  const rome = (job.rome_skills || []).join(", ");
  const training = (job.training_recommendations || []).join(", ");
  const market = (job.labour_market_signals || []).join(", ");
  const techStack = (job.tech_stack || []).slice(0, 10).join(", ");
  const apply = job.apply_url
    ? `<a href="${escapeHtml(job.apply_url)}" target="_blank" rel="noreferrer">Apply URL</a>`
    : "<span class='muted'>No apply URL.</span>";
  $("enrichmentDetails").innerHTML = `
    <div class="detail-block">
      <div class="detail-row"><span>Job</span><strong>${escapeHtml(job.title)}</strong></div>
      <div class="detail-row"><span>Company</span><strong>${escapeHtml(job.company)}</strong></div>
      <div class="detail-row"><span>Location</span><strong>${escapeHtml(job.location || "-")}</strong></div>
      <div class="detail-row"><span>Score</span>${scorePill(job.fit_score)}</div>
      <div class="detail-row"><span>Decision</span><strong>${escapeHtml(job.fit_decision || "-")}</strong></div>
      <div class="detail-row"><span>Status</span><strong>${escapeHtml(job.status || "-")}</strong></div>
      <div class="detail-row"><span>Apply</span>${apply}</div>
    </div>
    <div class="detail-block">
      <h4>Tech stack</h4>
      <p>${escapeHtml(techStack || "No tech stack signals.")}</p>
      <h4>Missing requirements</h4>
      <p>${escapeHtml((job.missing_requirements || []).join(", ") || "None tracked.")}</p>
    </div>
    <div class="detail-block">
      <div class="detail-row"><span>Endpoints OK</span><strong>${okCount}/${Object.keys(sources).length}</strong></div>
      <div class="detail-row"><span>Anotea rating</span><strong>${escapeHtml(job.anotea_rating ?? "-")}</strong></div>
      <div class="detail-row"><span>Updated</span><strong>${escapeHtml(job.enrichment_updated_at || "-")}</strong></div>
    </div>
    <div class="detail-block">
      <h4>ROME skills</h4>
      <p>${escapeHtml(rome || "No skills yet.")}</p>
      <h4>Training</h4>
      <p>${escapeHtml(training || "No training signals yet.")}</p>
      <h4>Labour market</h4>
      <p>${escapeHtml(market || "No market signals yet.")}</p>
    </div>
    <div class="detail-block">
      <h4>Endpoint status</h4>
      <ul>${items.join("") || "<li>No endpoint data.</li>"}</ul>
    </div>
  `;
}

function renderJobs() {
  if (!state.jobs.length) {
    $("jobsTableWrap").innerHTML = `<div class="notice">No tracked jobs yet. Run a search or import a URL/text from the Add Job tab.</div>`;
    $("jobsMetrics").innerHTML = "";
    return;
  }
  const text = $("jobsSearchInput").value.trim();
  const remoteOnly = $("filterRemote").checked;
  const internshipOnly = $("filterInternship").checked;
  const enrichedOnly = $("filterEnriched").checked;
  const sortMode = $("jobsSortSelect").value;

  let jobs = state.jobs.filter((job) => jobMatchesText(job, text));
  if (remoteOnly) jobs = jobs.filter((job) => job.remote);
  if (internshipOnly) jobs = jobs.filter((job) => isInternship(job));
  if (enrichedOnly) jobs = jobs.filter((job) => job.enriched);
  jobs = sortJobs(jobs, sortMode);

  renderJobsMetrics(jobs);

  const rows = jobs
    .map(
      (job) => {
        const checked = state.selectedJobs.has(job.id) ? "checked" : "";
        const enrichLabel = job.enriched ? "Enriched" : "—";
        const activeClass = state.activeJobId === job.id ? "active-row" : "";
        return `<tr data-job-row="${escapeHtml(job.id)}" class="${activeClass}">
          <td><input type="checkbox" data-select-job="${escapeHtml(job.id)}" ${checked} /></td>
          <td><strong>${escapeHtml(job.title)}</strong><br><span class="muted">${escapeHtml(job.company)}</span></td>
          <td>${escapeHtml(job.location || "")}${job.remote ? ` ${renderBadge("Remote", "good")}` : ""}</td>
          <td>${escapeHtml(job.status)}</td>
          <td>${scorePill(job.fit_score)}</td>
          <td>${escapeHtml((job.tech_stack || []).slice(0, 5).join(", "))}</td>
          <td>${escapeHtml(enrichLabel)}</td>
          <td class="actions">${jobActions(job)}</td>
        </tr>`;
      },
    )
    .join("");
  $("jobsTableWrap").innerHTML = `<table>
    <thead><tr><th></th><th>Job</th><th>Location</th><th>Status</th><th>Score</th><th>Signals</th><th>Enrich</th><th>Actions</th></tr></thead>
    <tbody>${rows}</tbody>
  </table>`;
  $("selectionCount").textContent = `${state.selectedJobs.size} selected`;
}

async function buildLinks() {
  const button = $("linksBtn");
  setBusy(button, true);
  setNotice("searchNotice", "");
  try {
    const payload = await api("/api/search-links", searchPayload());
    renderSearchMetrics(payload);
    renderManualGroups(payload.groups);
    renderApiResults([]);
    $("multiSourceResults").innerHTML = "";
    toast("Search links ready.");
  } catch (error) {
    setNotice("searchNotice", error.message, true);
  } finally {
    setBusy(button, false);
  }
}

async function runApiSearch() {
  const button = $("apiSearchBtn");
  setBusy(button, true);
  setNotice("searchNotice", "");
  try {
    const payload = await api("/api/api-search", { ...searchPayload(), source: "francetravail", save: true, limit: Number($("apiLimit").value || 5) });
    renderSearchMetrics(payload);
    renderApiResults(payload.jobs, payload.failures || []);
    await loadJobs(false);
    renderState();
    toast(`Imported ${payload.imported} new jobs.`);
  } catch (error) {
    setNotice("searchNotice", error.message, true);
  } finally {
    setBusy(button, false);
  }
}

async function runMultiSearch() {
  const button = $("multiSearchBtn");
  setBusy(button, true);
  setNotice("searchNotice", "");
  try {
    const payload = await api("/api/multi-search", { ...searchPayload(), save: true });
    renderSearchMetrics({
      query_count: Object.keys(payload.per_source || {}).length,
      link_count: payload.found,
      imported: payload.imported,
      prepared: payload.prepared,
    });
    renderMultiSourceResults(payload);
    renderApiResults(payload.jobs, payload.failures || []);
    await loadJobs(false);
    renderState();
    toast(`Multi-source: imported ${payload.imported}, ${payload.duplicates} duplicates.`);
  } catch (error) {
    setNotice("searchNotice", error.message, true);
  } finally {
    setBusy(button, false);
  }
}

async function oneClickHunt() {
  const button = $("oneClickBtn");
  setBusy(button, true);
  setNotice("searchNotice", "");
  try {
    const payload = await api("/api/one-click-hunt", searchPayload());
    renderSearchMetrics({ ...payload, query_count: payload.manual?.query_count, link_count: payload.manual?.link_count });
    renderManualGroups(payload.manual?.groups || []);
    renderApiResults(payload.jobs || [], payload.failures || []);
    $("multiSourceResults").innerHTML = "";
    await loadJobs(false);
    renderState();
    setNotice("searchNotice", payload.message || "1-click hunt complete.");
  } catch (error) {
    setNotice("searchNotice", error.message, true);
  } finally {
    setBusy(button, false);
  }
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

async function generatePacket(jobId, button) {
  setBusy(button, true);
  try {
    const payload = await api("/api/generate-packet", { job_id: jobId, force: $("forcePackets").checked });
    toast(`Packet ready: ${payload.packet.id}`);
    await loadJobs();
    renderState();
  } catch (error) {
    toast(error.message);
  } finally {
    setBusy(button, false);
  }
}

async function generatePacketsBatch(jobIds) {
  if (!jobIds.length) {
    toast("No jobs selected for packet generation.");
    return;
  }
  let success = 0;
  for (const jobId of jobIds) {
    try {
      await api("/api/generate-packet", { job_id: jobId, force: $("forcePackets").checked });
      success += 1;
    } catch (error) {
      console.warn(`Packet generation failed for ${jobId}: ${error.message}`);
    }
  }
  toast(`Generated ${success}/${jobIds.length} packets.`);
  await loadJobs();
  renderState();
}

async function enrichJob(jobId, button) {
  setBusy(button, true);
  try {
    const payload = await api("/api/enrich", { job_id: jobId });
    const sources = payload.report?.sources || {};
    const okCount = Object.values(sources).filter((value) => String(value).startsWith("ok")).length;
    const total = Object.keys(sources).length || 0;
    toast(`Enrichment done: ${okCount}/${total} endpoints`);
    await loadJobs();
    renderState();
  } catch (error) {
    toast(error.message);
  } finally {
    setBusy(button, false);
  }
}

async function enrichBatch(jobIds) {
  if (!jobIds.length) {
    toast("No jobs selected for enrichment.");
    return;
  }
  const payload = await api("/api/enrich-batch", { job_ids: jobIds });
  const okCount = payload.results?.filter((row) => row.ok).length || 0;
  toast(`Batch enrichment complete: ${okCount}/${payload.count}`);
  await loadJobs();
  renderState();
}

async function updateJobStatus(jobId, status, button) {
  setBusy(button, true);
  try {
    await api("/api/status", { job_id: jobId, status, note: `Dashboard update to ${status}` });
    toast(`Status updated: ${status}`);
    await loadJobs();
    renderState();
  } catch (error) {
    toast(error.message);
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

async function loadInsights() {
  try {
    const payload = await api("/api/stats");
    state.insightsCache = payload;
    renderInsights(payload);
  } catch (error) {
    toast(`Insights error: ${error.message}`);
  }
}

function renderInsights(stats) {
  const total = stats.total || 0;
  const submitted = stats.submitted_count || 0;
  const interviews = stats.interview_count || 0;
  $("insightsMetrics").innerHTML = [
    metric("Total tracked", total),
    metric("Submitted", submitted),
    metric("Interviews+", interviews),
    metric("Response rate", `${stats.response_rate ?? 0}%`, `avg score ${stats.avg_score ?? "—"}`),
  ].join("");

  const maxFunnel = Math.max(...(stats.funnel || []).map((row) => row.count || 0), 1);
  $("funnelView").innerHTML = (stats.funnel || [])
    .map((row) => {
      const pct = Math.round((row.count / maxFunnel) * 100);
      return `<div class="funnel-row">
        <span>${escapeHtml(row.label)}</span>
        <div class="funnel-bar"><div class="funnel-fill" style="width:${pct}%"></div></div>
        <strong>${row.count}</strong>
      </div>`;
    })
    .join("");

  const weeks = stats.weekly || [];
  const maxWeek = Math.max(1, ...weeks.flatMap((row) => [row.added, row.applied]));
  $("weeklyView").innerHTML = `${weeks
    .map((row) => {
      const widthAdded = Math.round((row.added / maxWeek) * 100);
      const widthApplied = Math.round((row.applied / maxWeek) * 100);
      return `<div class="weekly-row">
        <span>${escapeHtml(row.week)}</span>
        <div class="weekly-bar-wrap">
          <div class="weekly-bar added" style="width:${widthAdded}%" title="Added"></div>
          <div class="weekly-bar applied" style="width:${widthApplied}%" title="Applied"></div>
        </div>
        <strong>${row.added}/${row.applied}</strong>
      </div>`;
    })
    .join("")}
    <div class="weekly-legend"><span><span class="legend-swatch" style="background:var(--accent-3)"></span>Added</span><span><span class="legend-swatch" style="background:var(--accent)"></span>Applied</span></div>`;

  $("topCompaniesView").innerHTML = (stats.top_companies || [])
    .map((row) => `<li><span>${escapeHtml(row.name)}</span><strong>${row.count}</strong></li>`)
    .join("") || "<li class='muted'>No data yet.</li>";
  $("topSourcesView").innerHTML = (stats.top_sources || [])
    .map((row) => `<li><span>${escapeHtml(row.name)}</span><strong>${row.count}</strong></li>`)
    .join("") || "<li class='muted'>No data yet.</li>";
  $("topLocationsView").innerHTML = (stats.top_locations || [])
    .map((row) => `<li><span>${escapeHtml(row.name)}</span><strong>${row.count}</strong></li>`)
    .join("") || "<li class='muted'>No data yet.</li>";

  const buckets = stats.score_buckets || {};
  const maxBucket = Math.max(1, ...Object.values(buckets));
  $("scoreDistView").innerHTML = Object.entries(buckets)
    .map(([key, value]) => {
      const pct = Math.round((value / maxBucket) * 100);
      return `<div class="score-dist-row"><span>${escapeHtml(key)}</span><div class="score-dist-bar"><div class="score-dist-fill" style="width:${pct}%"></div></div><strong>${value}</strong></div>`;
    })
    .join("");
}

function activateTab(name) {
  document.querySelectorAll(".tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.tab === name));
  document.querySelectorAll(".tab-panel").forEach((panel) => panel.classList.toggle("active", panel.id === `tab-${name}`));
  if (name === "jobs") renderJobs();
  if (name === "insights" && !state.insightsCache) loadInsights();
}

function toggleShortcuts(show) {
  $("shortcutsHelp").classList.toggle("hidden", !show);
}

function bindKeyboardShortcuts() {
  const tabOrder = ["search", "jobs", "insights", "add", "profile"];
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
        oneClickHunt();
        return;
      }
      if (event.key === "m") {
        runMultiSearch();
        return;
      }
    }
  });
}

function bindEvents() {
  document.querySelectorAll(".tab").forEach((button) => {
    button.addEventListener("click", () => activateTab(button.dataset.tab));
  });

  $("linksBtn").addEventListener("click", buildLinks);
  $("apiSearchBtn").addEventListener("click", runApiSearch);
  $("oneClickBtn").addEventListener("click", oneClickHunt);
  $("multiSearchBtn").addEventListener("click", runMultiSearch);
  $("refreshJobsBtn").addEventListener("click", async () => {
    await loadJobs();
    renderState();
  });
  $("jobsRefreshBtn").addEventListener("click", async () => {
    await loadJobs();
    renderState();
  });
  $("insightsRefreshBtn").addEventListener("click", loadInsights);
  $("statusFilter").addEventListener("change", loadJobs);
  $("jobsSearchInput").addEventListener("input", renderJobs);
  $("jobsSortSelect").addEventListener("change", renderJobs);
  $("filterRemote").addEventListener("change", renderJobs);
  $("filterInternship").addEventListener("change", renderJobs);
  $("filterEnriched").addEventListener("change", renderJobs);
  $("selectAllJobs").addEventListener("change", (event) => {
    if (event.target.checked) state.jobs.forEach((job) => state.selectedJobs.add(job.id));
    else state.selectedJobs.clear();
    renderJobs();
  });
  $("enrichSelectedBtn").addEventListener("click", async () => {
    await enrichBatch([...state.selectedJobs]);
  });
  $("packetSelectedBtn").addEventListener("click", async () => {
    await generatePacketsBatch([...state.selectedJobs]);
  });
  $("enrichVisibleBtn").addEventListener("click", async () => {
    const visibleIds = Array.from(document.querySelectorAll("[data-job-row]")).map((row) => row.dataset.jobRow);
    await enrichBatch(visibleIds);
  });
  $("clearSelectionBtn").addEventListener("click", () => {
    state.selectedJobs.clear();
    renderJobs();
  });
  $("addUrlBtn").addEventListener("click", addUrl);
  $("addTextBtn").addEventListener("click", addText);
  $("profileRefreshBtn").addEventListener("click", loadState);
  $("exportInternshipsBtn").addEventListener("click", exportInternships);
  $("copyApiTextBtn").addEventListener("click", async () => {
    const text = `App name: ${$("apiAppName").value}\nURL: ${$("apiAppUrl").value}\nDescription: ${$("apiAppDescription").value}`;
    await navigator.clipboard.writeText(text);
    toast("Copied API application text.");
  });
  $("closeShortcuts").addEventListener("click", () => toggleShortcuts(false));
  $("shortcutsHelp").addEventListener("click", (event) => {
    if (event.target === $("shortcutsHelp")) toggleShortcuts(false);
  });

  document.body.addEventListener("click", (event) => {
    const target = event.target.closest("[data-action='packet']");
    if (target) {
      generatePacket(target.dataset.job, target);
      return;
    }
    const enrichTarget = event.target.closest("[data-action='enrich']");
    if (enrichTarget) {
      enrichJob(enrichTarget.dataset.job, enrichTarget);
      return;
    }
    const statusTarget = event.target.closest("[data-action='status']");
    if (statusTarget) {
      updateJobStatus(statusTarget.dataset.job, statusTarget.dataset.status, statusTarget);
      return;
    }
    const checkbox = event.target.closest("[data-select-job]");
    if (checkbox) {
      const jobId = checkbox.dataset.selectJob;
      if (checkbox.checked) state.selectedJobs.add(jobId);
      else state.selectedJobs.delete(jobId);
      $("selectionCount").textContent = `${state.selectedJobs.size} selected`;
      return;
    }
    const row = event.target.closest("[data-job-row]");
    if (row && !event.target.matches("input[type='checkbox']")) {
      const job = state.jobs.find((item) => item.id === row.dataset.jobRow);
      renderEnrichmentDetails(job);
      renderJobs();
    }
  });
}

bindEvents();
bindKeyboardShortcuts();
loadState()
  .then(() => buildLinks())
  .catch((error) => {
    setNotice("searchNotice", error.message, true);
  });
