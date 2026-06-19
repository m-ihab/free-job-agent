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
  studioActiveAsset: null,
  studioActiveAssetKind: null,
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
  $("statusStrip").innerHTML = badgesHtml;
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

function searchPayload() {
  const smartRefine = $("smartRefine") ? $("smartRefine").checked : false;
  return {
    query: $("queryInput").value.trim() || "data scientist",
    location: $("locationInput").value.trim() || "Paris",
    radius_km: Number($("radiusInput")?.value || 0),
    min_relevance: smartRefine ? 50 : 0,
    france_eu_only: $("franceEuOnly") ? $("franceEuOnly").checked : false,
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

function applyLocationPreset() {
  const preset = $("locationScopeSelect")?.value || "custom";
  if (preset && preset !== "custom") {
    $("locationInput").value = preset;
  }
  const radius = $("radiusInput");
  if (!radius) return;
  if (preset === "Paris" && !radius.value) radius.value = 25;
  if (preset === "Ile-de-France") radius.value = 0;
  if (preset === "France" || preset === "Europe" || preset === "Remote") radius.value = 0;
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

function renderSmartPlan(plan, multiSource = null) {
  if (!plan && !multiSource) {
    $("multiSourceResults").innerHTML = "";
    return;
  }
  const queries = (plan?.queries || []).map((q) => `<span class="badge">${escapeHtml(q)}</span>`).join("");
  const sourceLine = plan?.used_ai
    ? `AI query plan via ${escapeHtml(plan.model || "local model")}`
    : "Deterministic query plan";
  const multiLine = multiSource
    ? `<div class="detail-row"><span>Multi-source</span><strong>${multiSource.found || 0} found, ${multiSource.imported || 0} imported</strong></div>`
    : "";
  const errors = multiSource?.errors && Object.keys(multiSource.errors).length
    ? `<div class="muted" style="margin-top:0.4rem">${escapeHtml(Object.entries(multiSource.errors).slice(0, 3).map(([k, v]) => `${k}: ${String(v).slice(0, 90)}`).join(" | "))}</div>`
    : "";
  $("multiSourceResults").innerHTML = `<div class="panel">
    <div class="section-header" style="margin-bottom:0.5rem">
      <h3 style="margin:0">Smart search plan</h3>
      <span class="muted">${sourceLine}</span>
    </div>
    <p class="muted" style="margin-top:0">${escapeHtml(plan?.rationale || "")}</p>
    <div class="tag-cloud">${queries}</div>
    ${multiLine}
    ${errors}
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
        <td><strong>${escapeHtml(job.title)}</strong><br>${companyLine(job)}</td>
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

function companyLine(job) {
  const display = job.company_display || job.company || "Employer not disclosed";
  const source = job.company_source && job.company_source !== display
    ? ` <span class="row-tag">via ${escapeHtml(job.company_source)}</span>`
    : "";
  const unresolved = job.company_unresolved ? ` <span class="row-tag warn">undisclosed</span>` : "";
  return `<span class="muted">${escapeHtml(display)}</span>${source}${unresolved}`;
}

function jobActions(job) {
  const apply = job.apply_url ? `<a href="${escapeHtml(job.apply_url)}" target="_blank" rel="noreferrer">Apply</a>` : "";
  const assistant = job.assistant_page ? `<a href="${fileHref(job.assistant_page)}" target="_blank">Assistant</a>` : "";
  const cv = job.cv_pdf ? `<a href="${fileHref(job.cv_pdf)}" target="_blank">CV</a>` : "";
  const letter = job.cover_letter_pdf ? `<a href="${fileHref(job.cover_letter_pdf)}" target="_blank">Letter</a>` : "";
  const submitted = job.status === "MANUALLY_SUBMITTED" ? "" : `<button data-action="status" data-status="MANUALLY_SUBMITTED" data-job="${escapeHtml(job.id)}" title="Mark as manually submitted">Submitted</button>`;
  const rejected = job.status === "REJECTED" ? "" : `<button data-action="status" data-status="REJECTED" data-job="${escapeHtml(job.id)}" title="Mark as rejected">Reject</button>`;
  const remove = `<button data-action="delete-job" data-job="${escapeHtml(job.id)}" title="Remove this job from the local tracker">Remove</button>`;
  return `<div class="row-actions">
    <button data-action="packet" data-job="${escapeHtml(job.id)}" title="Generate a tailored CV + cover letter for this job">Tailor CV</button>
    <button data-action="outreach" data-job="${escapeHtml(job.id)}" title="Draft a cold outreach email to the recruiter/hiring manager">Outreach</button>
    <button data-action="linkedin" data-job="${escapeHtml(job.id)}" title="Draft a LinkedIn message to the recruiter">LinkedIn</button>
    <button data-action="interview" data-job="${escapeHtml(job.id)}" title="Generate interview prep questions">Prep</button>
    <button data-action="followup" data-job="${escapeHtml(job.id)}" title="Generate a follow-up email">Follow-up</button>
    <button data-action="ai-analyze" data-job="${escapeHtml(job.id)}" title="AI fit analysis">AI fit</button>
    <button data-action="ai-chat" data-job="${escapeHtml(job.id)}" title="Chat about this role">Chat</button>
    <button data-action="enrich" data-job="${escapeHtml(job.id)}" title="Enrich with France Travail data">Enrich</button>
    ${submitted}${rejected}${remove}
    ${apply}${assistant}${cv}${letter}
  </div>`;
}

function aiTagsHtml(job) {
  const tags = (job.ai_tags || []).slice(0, 4);
  if (!tags.length) return "";
  return `<div class="row-tags">${tags.map((t) => `<span class="row-tag">${escapeHtml(t)}</span>`).join("")}</div>`;
}

function aiVerdictBadge(job) {
  if (!job.ai_verdict) return "";
  const tone = job.ai_verdict === "strong" ? "good" : job.ai_verdict === "weak" ? "bad" : "warn";
  return renderBadge(`AI: ${job.ai_verdict}`, tone);
}

function isInternship(job) {
  const text = `${job.title} ${job.company} ${job.job_type || ""}`.toLowerCase();
  return ["intern", "internship", "stage", "stagiaire", "alternance", "apprentissage", "apprenti", "trainee"]
    .some((term) => text.includes(term));
}

function jobMatchesText(job, query) {
  if (!query) return true;
  const haystack = `${job.title} ${job.company} ${job.company_display || ""} ${job.location} ${(job.tech_stack || []).join(" ")}`.toLowerCase();
  return haystack.includes(query.toLowerCase());
}

const _AI_VERDICT_RANK = { strong: 3, moderate: 2, weak: 1, "": 0 };
const _NON_EU_LOCATION_RE = /(united states|usa|canada|mexico|brazil|argentina|chile|peru|colombia|australia|new zealand|india|singapore|japan|china|hong kong|south africa|israel|uae)/i;

function isFranceOrEu(job) {
  const text = `${job.location || ""} ${job.company || ""}`;
  if (_NON_EU_LOCATION_RE.test(text)) return false;
  return true;
}

function sortJobs(jobs, mode) {
  const list = [...jobs];
  if (mode === "score") {
    return list.sort((a, b) => (b.fit_score ?? -1) - (a.fit_score ?? -1));
  }
  if (mode === "ai") {
    return list.sort((a, b) => {
      const va = _AI_VERDICT_RANK[a.ai_verdict || ""] || 0;
      const vb = _AI_VERDICT_RANK[b.ai_verdict || ""] || 0;
      if (vb !== va) return vb - va;
      return (b.ai_score ?? b.fit_score ?? -1) - (a.ai_score ?? a.fit_score ?? -1);
    });
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
  const cvPreview = job.cv_pdf
    ? `<iframe class="doc-preview" title="Tailored CV preview" src="${fileHref(job.cv_pdf)}"></iframe>`
    : `<div class="notice">Generate a packet to preview the tailored CV here.</div>`;
  const latexWarn = job.latex_warning
    ? `<div class="notice" style="color:#b45309;border-color:#fbbf24;background:#fffbeb;margin-top:0.4rem;font-size:0.78rem">⚠ PDF used a fallback renderer (LaTeX compile failed). The <code>cv.tex</code> file is correct — install MiKTeX / TeX Live and regenerate to get your full-quality PDF. <details style="margin-top:0.3rem"><summary>Details</summary><pre style="white-space:pre-wrap;font-size:0.72rem;max-height:160px;overflow:auto">${escapeHtml(job.latex_warning)}</pre></details></div>`
    : "";
  const letterLink = job.cover_letter_pdf
    ? `<a href="${fileHref(job.cover_letter_pdf)}" target="_blank">Open cover letter PDF</a>`
    : `<span class="muted">No cover letter yet.</span>`;
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
    <div class="detail-block">
      <h4>Tailored CV preview</h4>
      ${latexWarn}
      ${cvPreview}
      <p>${letterLink}</p>
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
  const localOnly = $("filterLocalOnly") ? $("filterLocalOnly").checked : false;
  const hideRejected = $("filterHideRejected") ? $("filterHideRejected").checked : false;
  const contract = $("filterContract") ? $("filterContract").value : "";
  const roleFamily = $("filterRoleFamily") ? $("filterRoleFamily").value : "";
  const aiVerdictFilter = $("filterAiVerdict") ? $("filterAiVerdict").value : "";
  const minScore = $("filterMinScore") ? Number($("filterMinScore").value || 0) : 0;
  const sortMode = $("jobsSortSelect").value;

  let jobs = state.jobs.filter((job) => jobMatchesText(job, text));
  if (remoteOnly) jobs = jobs.filter((job) => job.remote);
  if (internshipOnly) jobs = jobs.filter((job) => isInternship(job));
  if (enrichedOnly) jobs = jobs.filter((job) => job.enriched);
  if (localOnly) jobs = jobs.filter(isFranceOrEu);
  if (hideRejected) jobs = jobs.filter((job) => job.status !== "REJECTED");
  if (contract) jobs = jobs.filter((job) => (job.ai_contract || "").toLowerCase() === contract);
  if (roleFamily) jobs = jobs.filter((job) => (job.ai_role_family || "") === roleFamily);
  if (aiVerdictFilter) {
    if (aiVerdictFilter === "unknown") jobs = jobs.filter((job) => !job.ai_verdict);
    else jobs = jobs.filter((job) => job.ai_verdict === aiVerdictFilter);
  }
  if (minScore > 0) jobs = jobs.filter((job) => (job.fit_score ?? 0) >= minScore);
  jobs = sortJobs(jobs, sortMode);

  renderJobsMetrics(jobs);

  const rows = jobs
    .map(
      (job) => {
        const checked = state.selectedJobs.has(job.id) ? "checked" : "";
        const enrichLabel = job.enriched ? "Enriched" : "—";
        const activeClass = state.activeJobId === job.id ? "active-row" : "";
        const summary = job.ai_summary ? `<div class="row-summary">${escapeHtml(job.ai_summary)}</div>` : "";
        const aiBadge = aiVerdictBadge(job);
        const tags = aiTagsHtml(job);
        const langWarn = (job.risk_flags || []).includes("LANGUAGE_MISMATCH")
          ? `<span class="badge-lang-warn" title="This job requires French — your profile is English-only">⚠ French required</span>`
          : "";
        return `<tr data-job-row="${escapeHtml(job.id)}" class="${activeClass}">
          <td><input type="checkbox" data-select-job="${escapeHtml(job.id)}" ${checked} /></td>
          <td><strong>${escapeHtml(job.title)}</strong>${langWarn}<br>${companyLine(job)}${summary}${tags}</td>
          <td>${escapeHtml(job.location || "")}${job.remote ? ` ${renderBadge("Remote", "good")}` : ""}</td>
          <td>${escapeHtml(job.status)}</td>
          <td>${scorePill(job.fit_score)}${aiBadge ? `<br>${aiBadge}` : ""}</td>
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
  refreshSelectionUi();
}

function refreshSelectionUi() {
  const count = state.selectedJobs.size;
  const label = count === 0 ? "Nothing selected" : `${count} selected`;
  const node = document.getElementById("selectionCount");
  if (node) node.textContent = label;
  const btn = document.getElementById("packetSelectedBtn");
  if (btn) {
    btn.textContent = count > 0 ? `Generate ${count} packet${count === 1 ? "" : "s"}` : "Generate packets";
    btn.disabled = false;
  }
  const enrichBtn = document.getElementById("enrichSelectedBtn");
  if (enrichBtn) {
    enrichBtn.textContent = count > 0 ? `Enrich ${count} selected` : "Enrich selected";
  }
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
    renderSmartPlan(payload.query_plan, payload.multi_source);
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

async function generateLinkedInMessage(jobId, button) {
  setBusy(button, true);
  toast("Drafting LinkedIn message…");
  try {
    const payload = await api("/api/linkedin-message", { job_id: jobId, type: "recruiter" });
    openTextModal("LinkedIn Message Draft", payload.message, "Copy to clipboard");
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
    const panel = document.getElementById("prepPanel");
    const title = document.getElementById("prepPanelTitle");
    const body = document.getElementById("prepPanelBody");
    const copyBtn = document.getElementById("prepPanelCopyBtn");
    const closeBtn = document.getElementById("prepPanelCloseBtn");
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
    const payload = await api("/api/followup-email", { job_id: jobId, type: "week1" });
    openTextModal("Follow-up Email Draft", payload.email_md, "Copy");
  } catch (error) {
    toast(`Follow-up failed: ${error.message}`);
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

async function runMarketReport() {
  const button = document.getElementById("insightsMarketBtn");
  setBusy(button, true);
  toast("Building market report…");
  try {
    const r = await api("/api/market-report", {});
    openTextModal("Market Report", r.markdown || "No market data yet — track some jobs first.", "Copy");
  } catch (error) {
    toast(`Market report failed: ${error.message}`);
  } finally {
    setBusy(button, false);
  }
}

async function runHeadhunter() {
  const button = document.getElementById("headhunterBtn");
  setBusy(button, true);
  toast("Building outreach packs…");
  try {
    const [batch, strategy] = await Promise.all([
      api("/api/headhunter-batch", { min_score: 50 }),
      api("/api/headhunter-strategy", {}),
    ]);
    const packs = (batch.packs || []).map((p) =>
      `${p.job_title} — ${p.company} (score ${p.score}${p.is_english_first ? ", English-first" : ""})\n\nCONNECT:\n${p.connect_request}\n\nRECRUITER MESSAGE:\n${p.recruiter_message}\n\nFOLLOW-UP:\n${p.followup_message}`
    ).join("\n\n────────────────────\n\n");
    const text = `${strategy.report_md || ""}\n\n====================\n${batch.count || 0} OUTREACH PACK(S)\n====================\n\n${packs || "No tracked jobs above the score threshold yet."}`;
    openTextModal("Headhunter Outreach", text, "Copy all");
  } catch (error) {
    toast(`Headhunter failed: ${error.message}`);
  } finally {
    setBusy(button, false);
  }
}

async function generateOutreachEmail(jobId, button) {
  setBusy(button, true);
  toast("Drafting outreach email…");
  try {
    const payload = await api("/api/generate-outreach", { job_id: jobId });
    openOutreachModal(payload);
  } catch (error) {
    toast(`Outreach failed: ${error.message}`);
  } finally {
    setBusy(button, false);
  }
}

function openOutreachModal(payload) {
  let modal = document.getElementById("outreachModal");
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
    document.getElementById("outreachCloseBtn").addEventListener("click", () => { modal.style.display = "none"; });
    document.getElementById("outreachCopyBtn").addEventListener("click", () => {
      const text = document.getElementById("outreachContent").textContent;
      navigator.clipboard.writeText(text).then(() => toast("Copied to clipboard."));
    });
    modal.addEventListener("click", (e) => { if (e.target === modal) modal.style.display = "none"; });
  }
  const emailText = (payload.email_md || "").replace(/\*\*Subject:\*\*/g, "Subject:").replace(/---\n\n/, "");
  document.getElementById("outreachContent").textContent = emailText;
  const info = [];
  if (payload.recruiter_name) info.push(`Recruiter: ${payload.recruiter_name}`);
  if (payload.recruiter_email) info.push(`Email: ${payload.recruiter_email}`);
  document.getElementById("outreachRecruiterInfo").textContent = info.join("  ·  ") || "No recruiter contact found in description.";
  modal.style.display = "flex";
}

async function generatePacket(jobId, button) {
  const force = $("forcePackets") ? $("forcePackets").checked : false;
  setBusy(button, true);
  toast("Tailoring CV + cover letter…");
  try {
    const payload = await api("/api/generate-packet", { job_id: jobId, force });
    toast(`Packet ready: open the CV / Letter links on this row.`);
    await loadJobs();
    renderState();
    return payload;
  } catch (error) {
    toast(`Packet failed: ${error.message}`);
    console.error("generate-packet failed", error);
    throw error;
  } finally {
    setBusy(button, false);
  }
}

async function generatePacketsBatch(jobIds) {
  if (!jobIds.length) {
    toast("Tick the checkbox on at least one job, then click Generate packets.");
    return;
  }
  const button = document.getElementById("packetSelectedBtn");
  setBusy(button, true);
  let success = 0;
  const failures = [];
  for (let i = 0; i < jobIds.length; i++) {
    const jobId = jobIds[i];
    toast(`Building packet ${i + 1}/${jobIds.length}…`);
    try {
      await api("/api/generate-packet", { job_id: jobId, force: $("forcePackets") ? $("forcePackets").checked : false });
      success += 1;
    } catch (error) {
      failures.push(`${jobId.slice(0, 8)}: ${error.message}`);
      console.warn(`Packet generation failed for ${jobId}: ${error.message}`);
    }
  }
  setBusy(button, false);
  if (failures.length) {
    toast(`Generated ${success}/${jobIds.length}. ${failures.length} failed (see console).`);
  } else {
    toast(`Generated ${success}/${jobIds.length} packets.`);
  }
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

async function deleteJob(jobId, button) {
  const job = state.jobs.find((item) => item.id === jobId);
  const label = job ? `${job.title} at ${job.company}` : jobId;
  if (!window.confirm(`Remove this job from your local tracker?\n\n${label}`)) return;
  setBusy(button, true);
  try {
    await api("/api/delete-job", { job_id: jobId, note: "Removed from dashboard" });
    state.selectedJobs.delete(jobId);
    if (state.activeJobId === jobId) {
      state.activeJobId = null;
      renderEnrichmentDetails(null);
    }
    toast("Job removed.");
    await loadJobs();
    renderState();
  } catch (error) {
    toast(error.message);
  } finally {
    setBusy(button, false);
  }
}

async function deleteJobsBatch(jobIds) {
  if (!jobIds.length) {
    toast("No jobs selected to remove.");
    return;
  }
  if (!window.confirm(`Remove ${jobIds.length} selected job(s) from your local tracker?`)) return;
  let removed = 0;
  for (const jobId of jobIds) {
    try {
      await api("/api/delete-job", { job_id: jobId, note: "Batch removed from dashboard" });
      state.selectedJobs.delete(jobId);
      removed += 1;
    } catch (error) {
      console.warn(`Delete failed for ${jobId}: ${error.message}`);
    }
  }
  toast(`Removed ${removed}/${jobIds.length} jobs.`);
  await loadJobs();
  renderState();
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

async function loadInsights() {
  try {
    const payload = await api("/api/stats");
    state.insightsCache = payload;
    renderInsights(payload);
  } catch (error) {
    toast(`Insights error: ${error.message}`);
  }
}

function readVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#888";
}

function destroyChart(key) {
  const existing = state.charts[key];
  if (existing && typeof existing.destroy === "function") existing.destroy();
  state.charts[key] = null;
}

function renderFunnelChart(funnel) {
  if (typeof Chart === "undefined") return;
  destroyChart("funnel");
  const ctx = document.getElementById("funnelChart");
  if (!ctx) return;
  const labels = funnel.map((row) => row.label);
  const values = funnel.map((row) => row.count);
  state.charts.funnel = new Chart(ctx, {
    type: "bar",
    data: {
      labels,
      datasets: [{
        label: "Jobs",
        data: values,
        backgroundColor: labels.map((_, i) => `rgba(${i % 2 ? "28,63,114" : "11,139,127"}, 0.85)`),
        borderRadius: 6,
        borderSkipped: false,
      }],
    },
    options: {
      indexAxis: "y",
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { beginAtZero: true, grid: { color: readVar("--line") }, ticks: { color: readVar("--muted") } },
        y: { grid: { display: false }, ticks: { color: readVar("--ink") } },
      },
    },
  });
}

function renderWeeklyChart(weeks) {
  if (typeof Chart === "undefined") return;
  destroyChart("weekly");
  const ctx = document.getElementById("weeklyChart");
  if (!ctx) return;
  const labels = weeks.map((row) => row.week.replace(/^\d{4}-/, ""));
  const added = weeks.map((row) => row.added);
  const applied = weeks.map((row) => row.applied);
  state.charts.weekly = new Chart(ctx, {
    type: "bar",
    data: {
      labels,
      datasets: [
        { label: "Added", data: added, backgroundColor: "rgba(28,63,114,0.75)", borderRadius: 4 },
        { label: "Applied", data: applied, backgroundColor: "rgba(11,139,127,0.85)", borderRadius: 4 },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { labels: { color: readVar("--muted") } } },
      scales: {
        x: { grid: { display: false }, ticks: { color: readVar("--muted") } },
        y: { beginAtZero: true, grid: { color: readVar("--line") }, ticks: { color: readVar("--muted") } },
      },
    },
  });
}

function renderPipelineChart(funnel) {
  if (typeof Chart === "undefined") return;
  destroyChart("pipeline");
  const ctx = document.getElementById("pipelineChart");
  if (!ctx) return;
  if (!funnel || !funnel.length) return;
  const labels = funnel.map((row) => row.label);
  const values = funnel.map((row) => row.count);
  const conversions = values.map((value, idx) => {
    if (idx === 0 || !values[idx - 1]) return "100%";
    return `${Math.round((value / values[idx - 1]) * 100)}%`;
  });
  state.charts.pipeline = new Chart(ctx, {
    type: "bar",
    data: {
      labels,
      datasets: [{
        label: "Jobs",
        data: values,
        backgroundColor: labels.map((_, i) => {
          const ratio = i / Math.max(1, labels.length - 1);
          return `rgba(${Math.round(11 + (28 - 11) * ratio)}, ${Math.round(139 - (139 - 63) * ratio)}, ${Math.round(127 - (127 - 114) * ratio)}, 0.85)`;
        }),
        borderRadius: 8,
        borderSkipped: false,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (item) => `${item.raw} jobs · ${conversions[item.dataIndex]} of previous`,
          },
        },
      },
      scales: {
        x: { grid: { display: false }, ticks: { color: readVar("--muted") } },
        y: { beginAtZero: true, grid: { color: readVar("--line") }, ticks: { color: readVar("--muted") } },
      },
    },
  });
}

function renderScoreChart(buckets) {
  if (typeof Chart === "undefined") return;
  destroyChart("score");
  const ctx = document.getElementById("scoreChart");
  if (!ctx) return;
  const labels = Object.keys(buckets);
  const values = Object.values(buckets);
  state.charts.score = new Chart(ctx, {
    type: "doughnut",
    data: {
      labels,
      datasets: [{
        data: values,
        backgroundColor: [
          "rgba(192,57,43,0.85)",
          "rgba(244,184,96,0.85)",
          "rgba(11,139,127,0.85)",
          "rgba(28,63,114,0.85)",
        ],
        borderColor: readVar("--surface"),
        borderWidth: 2,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { position: "bottom", labels: { color: readVar("--muted") } } },
    },
  });
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

  renderFunnelChart(stats.funnel || []);
  renderWeeklyChart(stats.weekly || []);
  renderScoreChart(stats.score_buckets || {});
  renderPipelineChart(stats.funnel || []);

  $("topCompaniesView").innerHTML = (stats.top_companies || [])
    .map((row) => `<li><span>${escapeHtml(row.name)}</span><strong>${row.count}</strong></li>`)
    .join("") || "<li class='muted'>No data yet.</li>";
  $("topSourcesView").innerHTML = (stats.top_sources || [])
    .map((row) => `<li><span>${escapeHtml(row.name)}</span><strong>${row.count}</strong></li>`)
    .join("") || "<li class='muted'>No data yet.</li>";
  $("topLocationsView").innerHTML = (stats.top_locations || [])
    .map((row) => `<li><span>${escapeHtml(row.name)}</span><strong>${row.count}</strong></li>`)
    .join("") || "<li class='muted'>No data yet.</li>";
}

function activateTab(name) {
  document.querySelectorAll(".tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.tab === name));
  document.querySelectorAll(".tab-panel").forEach((panel) => panel.classList.toggle("active", panel.id === `tab-${name}`));
  if (name === "jobs") renderJobs();
  if (name === "insights" && !state.insightsCache) loadInsights();
  if (name === "autopilot") {
    loadAutopilot();
    loadAiSetup();
    loadNeedsManual();
  }
  if (name === "studio") {
    loadStudio();
    loadStudioAssets();
    loadStudioGithubProjects();
  }
  if (name === "portfolio") loadPortfolio();
  if (name === "coach" && !state.coachCache) renderCoachShell();
}

// ===== CV Studio =====
async function loadStudio() {
  try {
    const data = await api("/api/cv-studio");
    state.studio = data;
    const textarea = document.getElementById("studioTextarea");
    if (textarea && !textarea.dataset.dirty) textarea.value = data.text || "";
    renderStudioSections(data.sections || [], data.section_display || {});
    const langSel = document.getElementById("studioLanguage");
    if (langSel && data.language) langSel.value = data.language;
    const status = document.getElementById("studioStatus");
    if (status) {
      status.textContent = data.origin === "draft" ? "Editing draft (unsaved promotion to main.tex)" : "Loaded main.tex";
    }
  } catch (error) {
    setNotice("studioNotice", error.message, true);
  }
}

function renderStudioSections(titles, display) {
  const list = document.getElementById("studioSections");
  if (!list) return;
  display = display || {};
  if (!titles.length) {
    list.innerHTML = "<li class='muted'>No \\section{...} blocks found yet.</li>";
    return;
  }
  list.innerHTML = titles
    .map((title) => `<li draggable="true" data-section="${escapeHtml(title)}">${escapeHtml(display[title] || title)}</li>`)
    .join("");
  attachSectionDnd(list);
}

function attachSectionDnd(list) {
  let dragEl = null;
  list.querySelectorAll("li").forEach((li) => {
    li.addEventListener("dragstart", () => { dragEl = li; li.classList.add("dragging"); });
    li.addEventListener("dragend", () => { if (dragEl) dragEl.classList.remove("dragging"); dragEl = null; list.querySelectorAll("li").forEach((x) => x.classList.remove("drop-target")); });
    li.addEventListener("dragover", (e) => { e.preventDefault(); list.querySelectorAll("li").forEach((x) => x.classList.remove("drop-target")); li.classList.add("drop-target"); });
    li.addEventListener("drop", (e) => {
      e.preventDefault();
      if (dragEl && dragEl !== li) {
        const rect = li.getBoundingClientRect();
        const before = (e.clientY - rect.top) < rect.height / 2;
        list.insertBefore(dragEl, before ? li : li.nextSibling);
      }
    });
  });
}

async function studioSetLanguage(lang) {
  const textarea = document.getElementById("studioTextarea");
  try {
    const result = await api("/api/cv-studio/language", { language: lang });
    if (!result.ok) {
      setNotice("studioNotice", result.reason === "no_language_toggle"
        ? "This template has no \\cvlang toggle, so the language can't be switched automatically."
        : "Could not switch language.", true);
      return;
    }
    if (textarea) { textarea.value = result.text || textarea.value; delete textarea.dataset.dirty; }
    await studioCompile();
    toast(`CV language set to ${result.language === "fr" ? "Français" : "English"}.`);
  } catch (error) {
    setNotice("studioNotice", error.message, true);
  }
}

async function studioSwapEduExp() {
  const button = document.getElementById("studioSwapEduExpBtn");
  const textarea = document.getElementById("studioTextarea");
  setBusy(button, true);
  setNotice("studioNotice", "");
  try {
    const result = await api("/api/cv-studio/swap-sections", { a: "Education", b: "Professional Experience" });
    if (!result.ok) {
      setNotice("studioNotice", result.reason === "section_not_found"
        ? "Couldn't find both Education and Professional Experience sections to swap."
        : "Swap failed.", true);
      return;
    }
    if (textarea) { textarea.value = result.text || textarea.value; delete textarea.dataset.dirty; }
    renderStudioSections(result.sections || [], result.section_display || {});
    await studioCompile();
    toast("Swapped Education and Professional Experience.");
  } catch (error) {
    setNotice("studioNotice", error.message, true);
  } finally {
    setBusy(button, false);
  }
}

async function studioCompile() {
  const button = document.getElementById("studioCompileBtn");
  const textarea = document.getElementById("studioTextarea");
  setBusy(button, true);
  setNotice("studioNotice", "");
  try {
    const text = textarea ? textarea.value : "";
    const result = await api("/api/cv-studio/compile", { text });
    if (!result.ok) {
      const reason = result.reason || "compile_failed";
      const log = (result.log || "").slice(-2000);
      const logHtml = log
        ? `<details style="margin-top:0.5rem"><summary style="cursor:pointer;font-size:0.8rem">LaTeX error log ▸</summary><pre style="font-size:0.75rem;max-height:280px;overflow:auto;white-space:pre-wrap;margin-top:0.4rem">${escapeHtml(log)}</pre></details>`
        : "";
      const noticeEl = document.getElementById("studioNotice");
      if (noticeEl) {
        noticeEl.className = "notice error";
        noticeEl.innerHTML = `Compile failed (${escapeHtml(reason)}).${logHtml}`;
      }
      return;
    }
    const iframe = document.getElementById("studioPreview");
    if (iframe) iframe.src = `/api/cv-studio/preview-pdf?t=${Date.now()}`;
    toast("Preview rebuilt.");
  } catch (error) {
    setNotice("studioNotice", error.message, true);
  } finally {
    setBusy(button, false);
  }
}

async function studioSaveDraft() {
  const button = document.getElementById("studioSaveBtn");
  const textarea = document.getElementById("studioTextarea");
  setBusy(button, true);
  try {
    await api("/api/cv-studio/save", { text: textarea ? textarea.value : "" });
    if (textarea) textarea.dataset.dirty = "";
    toast("Draft saved locally.");
    await loadStudio();
  } catch (error) {
    setNotice("studioNotice", error.message, true);
  } finally {
    setBusy(button, false);
  }
}

async function studioReset() {
  if (!window.confirm("Discard the working draft and reload main.tex?")) return;
  await api("/api/cv-studio/reset", {});
  const textarea = document.getElementById("studioTextarea");
  if (textarea) delete textarea.dataset.dirty;
  await loadStudio();
}

async function studioPromote() {
  if (!window.confirm("Overwrite profiles/main.tex with the current draft? A .bak backup will be kept.")) return;
  const result = await api("/api/cv-studio/promote", {});
  if (result.ok) {
    toast("Promoted draft to main.tex.");
  } else {
    setNotice("studioNotice", `Could not promote: ${result.reason}`, true);
  }
}

async function studioSuggest() {
  const button = document.getElementById("studioSuggestBtn");
  const textarea = document.getElementById("studioTextarea");
  const target = document.getElementById("studioSuggestionList");
  setBusy(button, true);
  if (target) target.innerHTML = "<div class='muted'>Thinking locally…</div>";
  try {
    const result = await api("/api/cv-studio/suggest", { text: textarea ? textarea.value : "" });
    if (!result.available) {
      if (target) target.innerHTML = "<div class='muted'>Start Ollama (Autopilot tab) to unlock AI suggestions.</div>";
      return;
    }
    const items = result.suggestions || [];
    if (!items.length) {
      if (target) target.innerHTML = "<div class='muted'>No suggestions — your CV already looks tight.</div>";
      return;
    }
    state.studioSuggestions = items;
    if (target) target.innerHTML = items.map((s, idx) => `
      <div class="studio-suggestion" data-suggest-idx="${idx}">
        <div class="suggest-head">
          <strong>${escapeHtml(s.title)}</strong>
          <span class="row-tag">${escapeHtml(s.priority || "")} · ${escapeHtml(s.section || "")}</span>
        </div>
        <p class="muted" style="margin:0 0 0.3rem">${escapeHtml(s.rationale || "")}</p>
        ${s.before ? `<code class="suggest-before" title="Current text in your CV">${escapeHtml(s.before)}</code>` : ""}
        ${s.after ? `<label class="suggest-edit-label">Edit before applying${/\[[A-Za-z0-9_\- ]+\]/.test(s.after) ? ' <span class="row-tag warn">has placeholders</span>' : ""}</label>` : ""}
        ${s.after ? `<textarea class="suggest-after-edit" data-suggest-after-edit="${idx}" rows="3">${escapeHtml(s.after)}</textarea>` : ""}
        ${s.before && s.after ? `<div class="action-row" style="margin-top:0.4rem">
          <button data-suggest-apply-idx="${idx}" class="primary-soft">Apply</button>
          <button data-suggest-reset-idx="${idx}">Reset edit</button>
          <button data-suggest-dismiss-idx="${idx}">Dismiss</button>
        </div>` : ""}
      </div>
    `).join("");
  } catch (error) {
    if (target) target.innerHTML = `<div class='notice error'>${escapeHtml(error.message)}</div>`;
  } finally {
    setBusy(button, false);
  }
}

function studioApplySuggestion(before, after) {
  const textarea = document.getElementById("studioTextarea");
  if (!textarea || !before) return;
  if (!textarea.value.includes(before)) {
    toast("Suggestion's 'before' text isn't an exact match — apply manually.");
    return;
  }
  textarea.value = textarea.value.replace(before, after);
  textarea.dataset.dirty = "1";
  toast("Suggestion applied. Click Compile preview to render.");
}

// ===== Studio v2: assets, photo, icon pack, single-page, GitHub import =====
async function loadStudioAssets() {
  const node = document.getElementById("studioAssetList");
  if (!node) return;
  try {
    const data = await api("/api/cv-studio/assets");
    state.studioAssets = data.assets || [];
    if (!state.studioAssets.length) {
      node.innerHTML = "<li class='muted'>No assets found in profiles/.</li>";
      return;
    }
    node.innerHTML = state.studioAssets.map((a) => {
      const size = a.kind === "image" ? `${Math.round(a.size / 1024)} KB` : `${a.size} B`;
      return `<li data-asset="${escapeHtml(a.name)}"><span class="coach-title">${escapeHtml(a.name)}</span><span class="row-tag">${escapeHtml(a.kind)} · ${size}</span></li>`;
    }).join("");
    Array.from(node.querySelectorAll("li[data-asset]")).forEach((li) => {
      li.addEventListener("click", () => openStudioAsset(li.dataset.asset));
    });
    const select = document.getElementById("studioIconPack");
    if (select && data.icon_packs) {
      select.innerHTML = data.icon_packs.map((p) => `<option value="${escapeHtml(p.key)}">${escapeHtml(p.label)}</option>`).join("");
    }
  } catch (error) {
    node.innerHTML = `<li class="notice error">${escapeHtml(error.message)}</li>`;
  }
}

async function uploadStudioPhoto() {
  const input = document.getElementById("studioPhotoInput");
  const notice = document.getElementById("studioPhotoNotice");
  if (!input || !input.files || !input.files[0]) {
    if (notice) notice.textContent = "Pick a JPG or PNG first.";
    return;
  }
  const file = input.files[0];
  const reader = new FileReader();
  reader.onload = async () => {
    try {
      const result = await api("/api/cv-studio/replace-photo", {
        name: file.name,
        data: reader.result,
      });
      if (result.ok) {
        toast(`Photo updated (${Math.round(result.bytes / 1024)} KB).`);
        if (notice) notice.textContent = "Recompile to see the new photo.";
        loadStudioAssets();
      } else {
        if (notice) notice.textContent = `Failed: ${result.reason}`;
      }
    } catch (error) {
      if (notice) notice.textContent = error.message;
    }
  };
  reader.readAsDataURL(file);
}

async function removeStudioPhoto() {
  if (!window.confirm("Remove the CV photo and comment out \\photo{...} in main.tex?")) return;
  const result = await api("/api/cv-studio/remove-photo", {});
  toast(result.ok ? "Photo removed (backup kept)." : `Failed: ${result.reason}`);
  loadStudioAssets();
}

async function loadStudioGithubProjects() {
  try {
    const data = await api(`/api/cv-studio/asset?name=master_cv.json`);
    if (!data.ok || data.kind !== "text") return;
    let parsed;
    try { parsed = JSON.parse(data.text); } catch { return; }
    const projects = (parsed.projects || []).map((p) => p.name).filter(Boolean);
    const select = document.getElementById("studioGithubProjectSelect");
    if (!select) return;
    select.innerHTML = '<option value="">— select a project —</option>' + projects.map((name) => `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`).join("");
  } catch {}
}

async function checkSinglePage() {
  const button = document.getElementById("studioSinglePageBtn");
  const target = document.getElementById("studioSinglePageResult");
  const textarea = document.getElementById("studioTextarea");
  if (!target) return;
  setBusy(button, true);
  target.innerHTML = "Compiling and counting pages…";
  try {
    const result = await api("/api/cv-studio/single-page-check", { text: textarea ? textarea.value : null });
    if (!result.ok) {
      target.innerHTML = `<span class="notice error">${escapeHtml(result.reason)}</span>`;
      return;
    }
    if (result.single_page) {
      target.innerHTML = `<span class="badge good">✓ Fits on 1 page (${result.page_count})</span>`;
      return;
    }
    if (result.single_page === null) {
      target.innerHTML = `<span class="muted">Could not count pages — compile succeeded though.</span>`;
      return;
    }
    target.innerHTML = `<div><span class="badge warn">Overflowing (${result.page_count} pages)</span></div>
      <p class="muted" style="margin:0.5rem 0">Try these conservative trims in order:</p>
      <ol class="coach-list">${(result.trims || []).map((t) => `<li>
        <div><span class="coach-title">${escapeHtml(t.title)}</span><span class="coach-sub">${escapeHtml(t.note)} — search for <code>${escapeHtml(t.where)}</code></span></div>
        <strong></strong>
      </li>`).join("")}</ol>`;
  } catch (error) {
    target.innerHTML = `<span class="notice error">${escapeHtml(error.message)}</span>`;
  } finally {
    setBusy(button, false);
  }
}

async function autoFitStudioDraft() {
  const button = document.getElementById("studioAutoFitBtn");
  const target = document.getElementById("studioSinglePageResult");
  const textarea = document.getElementById("studioTextarea");
  if (!textarea || !target) return;
  setBusy(button, true);
  target.innerHTML = "Trying conservative layout tightening...";
  try {
    const result = await api("/api/cv-studio/auto-fit", { text: textarea.value });
    if (!result.ok) {
      target.innerHTML = `<span class="notice error">${escapeHtml(result.reason || result.log || "Auto-fit failed")}</span>`;
      return;
    }
    if (result.changed) {
      textarea.value = result.text || textarea.value;
      textarea.dataset.dirty = "1";
    }
    const stepList = (result.steps || []).map((step) => `<li>${escapeHtml(step)}</li>`).join("");
    target.innerHTML = `<div><span class="badge ${result.single_page ? "good" : "warn"}">${result.single_page ? "Fits after auto-fit" : "Still needs manual trim"}${result.page_count ? ` (${result.page_count} page${result.page_count === 1 ? "" : "s"})` : ""}</span></div>
      <ol class="coach-list" style="margin-top:0.5rem">${stepList}</ol>`;
    toast(result.changed ? "Auto-fit applied to the draft." : "Draft already fits.");
    await studioCompile();
  } catch (error) {
    target.innerHTML = `<span class="notice error">${escapeHtml(error.message)}</span>`;
  } finally {
    setBusy(button, false);
  }
}

async function analyzeStudioAtsKeywords() {
  const button = document.getElementById("studioAtsBtn");
  const textarea = document.getElementById("studioTextarea");
  const role = document.getElementById("studioAtsRole")?.value || "data_scientist";
  const target = document.getElementById("studioAtsResult");
  if (!textarea || !target) return;
  setBusy(button, true);
  target.innerHTML = "Scanning the current draft...";
  try {
    const result = await api("/api/cv-studio/ats-keywords", { text: textarea.value, role });
    if (!result.ok) {
      target.innerHTML = `<span class="notice error">${escapeHtml(result.reason || "ATS scan failed")}</span>`;
      return;
    }
    const chips = (result.present || []).map((kw) => `<span class="chip good">${escapeHtml(kw)}</span>`).join("");
    const missing = (result.missing || []).map((kw) => `<span class="chip warn">${escapeHtml(kw)}</span>`).join("");
    const suggestions = (result.suggestions || []).map((item) => `<li>
      <div><span class="coach-title">${escapeHtml(item.keyword)}</span><span class="coach-sub">${escapeHtml(item.note)} Suggested place: ${escapeHtml(item.where)}.</span></div>
      <strong>gap</strong>
    </li>`).join("");
    target.innerHTML = `
      <div><span class="badge ${result.coverage >= 70 ? "good" : "warn"}">${result.coverage}% coverage</span></div>
      <p class="muted" style="margin:0.5rem 0 0.25rem">Present</p><div class="chips">${chips || "<span class='muted'>None yet.</span>"}</div>
      <p class="muted" style="margin:0.7rem 0 0.25rem">Missing / optional</p><div class="chips">${missing || "<span class='muted'>No obvious gaps.</span>"}</div>
      <ol class="coach-list" style="margin-top:0.7rem">${suggestions}</ol>`;
  } catch (error) {
    target.innerHTML = `<span class="notice error">${escapeHtml(error.message)}</span>`;
  } finally {
    setBusy(button, false);
  }
}

async function studioApplyReorder() {
  const list = document.getElementById("studioSections");
  const textarea = document.getElementById("studioTextarea");
  if (!list || !textarea) return;
  const order = Array.from(list.querySelectorAll("li")).map((li) => li.dataset.section).filter(Boolean);
  if (!order.length) {
    toast("No reorderable sections.");
    return;
  }
  const result = await api("/api/cv-studio/reorder", { text: textarea.value, order });
  if (result.ok) {
    textarea.value = result.text;
    textarea.dataset.dirty = "1";
    toast("Reorder applied. Click Compile preview to verify.");
  }
}

// CV Studio asset/project overrides. These intentionally appear after the
// first Studio helpers so the browser binds the safer split-editor behavior:
// Compile preview always reads #studioTextarea, while assets use
// #studioAssetTextarea.
async function openStudioAsset(name) {
  if (!name) return;
  state.studioActiveAsset = name;
  state.studioActiveAssetKind = null;
  const status = document.getElementById("studioAssetActive");
  const assetEditor = document.getElementById("studioAssetTextarea");
  const assetPreview = document.getElementById("studioAssetPreview");
  const assetSave = document.getElementById("studioAssetSaveBtn");
  if (status) status.textContent = `Editing ${name}`;
  if (assetEditor) {
    assetEditor.value = "";
    assetEditor.classList.add("hidden");
    delete assetEditor.dataset.dirty;
  }
  if (assetPreview) {
    assetPreview.classList.remove("hidden");
    assetPreview.textContent = "Loading asset...";
  }
  try {
    const data = await api(`/api/cv-studio/asset?name=${encodeURIComponent(name)}`);
    if (!data.ok) {
      toast(`Could not open ${name}: ${data.reason}`);
      return;
    }
    state.studioActiveAssetKind = data.kind;
    if (data.kind === "text") {
      if (assetEditor) {
        assetEditor.value = data.text || "";
        assetEditor.classList.remove("hidden");
        assetEditor.dataset.dirty = "";
      }
      if (assetPreview) {
        const isMainTex = name.toLowerCase() === "main.tex";
        assetPreview.innerHTML = isMainTex
          ? "This is your source CV. Inspect or edit it here; Compile preview still renders the LaTeX draft above."
          : "Text asset loaded below. This side editor is intentionally separate from the CV preview draft.";
      }
      if (assetSave) assetSave.disabled = false;
      toast(`Loaded ${name} in the asset editor.`);
    } else {
      if (assetSave) assetSave.disabled = true;
      const url = data.url || "";
      if (assetPreview) {
        const lower = name.toLowerCase();
        assetPreview.innerHTML = lower.endsWith(".pdf")
          ? `<iframe src="${escapeHtml(url)}" title="${escapeHtml(name)} preview"></iframe>`
          : `<img src="${escapeHtml(url)}" alt="${escapeHtml(name)} preview" />`;
      }
      toast(`${name} is preview-only here.`);
    }
  } catch (error) {
    toast(error.message);
  }
}

async function saveStudioAsset() {
  const name = state.studioActiveAsset;
  if (!name) {
    toast("Open an asset from the list first.");
    return;
  }
  if (state.studioActiveAssetKind !== "text") {
    toast("This asset is not text-editable.");
    return;
  }
  const textarea = document.getElementById("studioAssetTextarea");
  try {
    const result = await api("/api/cv-studio/asset-save", { name, text: textarea ? textarea.value : "" });
    if (result.ok) {
      toast(`Saved ${name}.`);
      if (textarea) delete textarea.dataset.dirty;
      if (name.toLowerCase() === "main.tex") {
        const draft = document.getElementById("studioTextarea");
        if (draft && !draft.dataset.dirty) draft.value = textarea ? textarea.value : "";
        await loadStudio();
      }
    } else {
      toast(`Could not save: ${result.reason}`);
    }
  } catch (error) {
    toast(error.message);
  }
}

async function applyIconPack() {
  const select = document.getElementById("studioIconPack");
  const notice = document.getElementById("studioIconPackNotice");
  if (!select) return;
  try {
    const result = await api("/api/cv-studio/icon-pack", { pack: select.value });
    if (result.ok) {
      if (notice) notice.textContent = `Applied ${result.label}. Recompile to preview.`;
      toast("Icon pack updated.");
      const ta = document.getElementById("studioTextarea");
      if (ta && result.text) {
        ta.value = result.text;
        ta.dataset.dirty = "1";
      } else if (ta) {
        delete ta.dataset.dirty;
        await loadStudio();
      }
      await loadStudioAssets();
    } else if (notice) {
      notice.textContent = `Failed: ${result.reason}`;
    }
  } catch (error) {
    if (notice) notice.textContent = error.message;
  }
}

async function importGithubProject() {
  const select = document.getElementById("studioGithubProjectSelect");
  const notice = document.getElementById("studioGithubNotice");
  if (!select || !select.value) {
    if (notice) notice.textContent = "Pick a project first.";
    return;
  }
  try {
    const result = await api("/api/cv-studio/import-github-project", { name: select.value });
    if (result.ok) {
      if (notice) notice.textContent = result.draft_updated
        ? `Promoted "${result.promoted}" and updated the preview draft. Compile to see it.`
        : `Promoted "${result.promoted}" to top of projects. ${result.note || ""}`;
      toast("Project promoted.");
      if (result.text) {
        const ta = document.getElementById("studioTextarea");
        if (ta) {
          ta.value = result.text;
          ta.dataset.dirty = "1";
        }
        renderStudioSections(state.studio?.sections || []);
      }
      await loadStudioGithubProjects();
      if (state.studioActiveAsset === "master_cv.json") await openStudioAsset("master_cv.json");
    } else if (notice) {
      notice.textContent = `Failed: ${result.reason}`;
    }
  } catch (error) {
    if (notice) notice.textContent = error.message;
  }
}

function fillDeepLearningProjectTemplate() {
  const set = (id, value) => {
    const node = document.getElementById(id);
    if (node) node.value = value;
  };
  set("studioProjectName", "DSTI Deep Learning AG News Classifier");
  set("studioProjectUrl", "https://github.com/fractalical/dsti-deep-learning");
  set("studioProjectTech", "Python, Jupyter Notebook, Transformers, DistilBERT, RoBERTa, scikit-learn, NLP, Deep Learning");
  set("studioProjectDescription", "Deep learning group project for AG News topic classification comparing classical baselines with transformer-based models.");
  set("studioProjectBullets", [
    "Owned the model-development and training workflow for transformer-based text classification experiments.",
    "Compared TF-IDF + Logistic Regression baselines against DistilBERT and RoBERTa improvements.",
    "Tracked accuracy, macro-F1, configuration snapshots, predictions, and reproducible run artefacts."
  ].join("\n"));
}

async function saveStudioProject() {
  const notice = document.getElementById("studioGithubNotice");
  const read = (id) => (document.getElementById(id)?.value || "").trim();
  const name = read("studioProjectName");
  if (!name) {
    if (notice) notice.textContent = "Project name is required.";
    return;
  }
  const technologies = read("studioProjectTech").split(",").map((x) => x.trim()).filter(Boolean);
  const bullet_points = read("studioProjectBullets").split(/\r?\n/).map((x) => x.trim()).filter(Boolean);
  try {
    const result = await api("/api/cv-studio/project-save", {
      name,
      url: read("studioProjectUrl"),
      description: read("studioProjectDescription"),
      technologies,
      bullet_points,
      promote: true,
    });
    if (result.ok) {
      if (notice) notice.textContent = `Saved "${result.project?.name || name}" locally and promoted it.`;
      toast("Project saved to local profile.");
      if (result.text) {
        const ta = document.getElementById("studioTextarea");
        if (ta) {
          ta.value = result.text;
          ta.dataset.dirty = "1";
        }
      }
      await loadStudioGithubProjects();
      if (state.studioActiveAsset === "master_cv.json") await openStudioAsset("master_cv.json");
    } else if (notice) {
      notice.textContent = `Failed: ${result.reason}`;
    }
  } catch (error) {
    if (notice) notice.textContent = error.message;
  }
}

// ===== Portfolio Builder =====
function renderPortfolioOptions(data) {
  const cfg = (data && data.config) || {};
  const theme = document.getElementById("portfolioTheme");
  const font = document.getElementById("portfolioFont");
  const layout = document.getElementById("portfolioLayout");
  if (theme && data.themes) {
    const current = cfg.theme || theme.value || "signal";
    theme.innerHTML = data.themes.map((item) => `<option value="${escapeHtml(item.key)}">${escapeHtml(item.label)} · ${escapeHtml(item.preset || "")}</option>`).join("");
    theme.value = data.themes.some((item) => item.key === current) ? current : "signal";
  }
  if (font && data.fonts) {
    const current = cfg.font || font.value || "inter";
    font.innerHTML = data.fonts.map((item) => `<option value="${escapeHtml(item.key)}">${escapeHtml(item.label)}</option>`).join("");
    font.value = data.fonts.some((item) => item.key === current) ? current : "inter";
  }
  if (layout && data.layouts) {
    const current = cfg.layout || layout.value || "split";
    layout.innerHTML = data.layouts.map((item) => `<option value="${escapeHtml(item.key)}">${escapeHtml(item.label)}</option>`).join("");
    layout.value = data.layouts.some((item) => item.key === current) ? current : "split";
  }
  const accent = document.getElementById("portfolioAccent");
  if (accent) accent.value = (cfg.custom_accent && /^#[0-9a-fA-F]{6}$/.test(cfg.custom_accent)) ? cfg.custom_accent : "#2563eb";
  const tagline = document.getElementById("portfolioTagline");
  if (tagline) tagline.value = cfg.tagline || "";
  const siteUrl = document.getElementById("portfolioSiteUrl");
  if (siteUrl) siteUrl.value = cfg.site_url || "";
  const darkToggle = document.getElementById("portfolioDarkToggle");
  if (darkToggle) darkToggle.checked = cfg.enable_dark_toggle !== false;
  const animations = document.getElementById("portfolioAnimations");
  if (animations) animations.checked = cfg.enable_animations !== false;
  renderPortfolioSections(data, cfg);
  const path = document.getElementById("portfolioPath");
  if (path) path.textContent = data.path ? `Local folder: ${data.path}` : "";
}

function renderPortfolioSections(data, cfg) {
  const wrap = document.getElementById("portfolioSections");
  if (!wrap || !data.optional_sections) return;
  const sectionLabels = {
    open_source: "Open Source",
    speaking: "Speaking",
    awards: "Awards",
    testimonials: "Testimonials",
    blog: "Writing",
  };
  const checks = (cfg.sections || {});
  wrap.innerHTML = `<span class="muted" style="margin-right:0.4rem">Optional sections:</span>` + data.optional_sections.map((key) =>
    `<label class="check-row"><input type="checkbox" data-portfolio-section="${escapeHtml(key)}" ${checks[key] ? "checked" : ""} /> ${escapeHtml(sectionLabels[key] || key)}</label>`
  ).join("");
}

function readPortfolioSections() {
  const checks = {};
  document.querySelectorAll('[data-portfolio-section]').forEach((el) => {
    checks[el.dataset.portfolioSection] = el.checked;
  });
  return checks;
}

function portfolioPayload() {
  return {
    theme: document.getElementById("portfolioTheme")?.value || "signal",
    font: document.getElementById("portfolioFont")?.value || "inter",
    layout: document.getElementById("portfolioLayout")?.value || "split",
    custom_accent: document.getElementById("portfolioAccent")?.value || "",
    tagline: document.getElementById("portfolioTagline")?.value || "",
    site_url: document.getElementById("portfolioSiteUrl")?.value || "",
    sections: readPortfolioSections(),
    enable_dark_toggle: document.getElementById("portfolioDarkToggle")?.checked !== false,
    enable_animations: document.getElementById("portfolioAnimations")?.checked !== false,
  };
}

function setPortfolioEditors(data) {
  const htmlEditor = document.getElementById("portfolioHtmlEditor");
  const cssEditor = document.getElementById("portfolioCssEditor");
  if (htmlEditor && data.html) htmlEditor.value = data.html;
  if (cssEditor && data.css) cssEditor.value = data.css;
  const iframe = document.getElementById("portfolioPreview");
  if (iframe) iframe.src = `/api/portfolio/preview?t=${Date.now()}`;
}

async function loadPortfolio() {
  try {
    const data = await api("/api/portfolio");
    state.portfolio = data;
    renderPortfolioOptions(data);
    setPortfolioEditors(data);
  } catch (error) {
    setNotice("portfolioNotice", error.message, true);
  }
}

async function generatePortfolio() {
  const button = document.getElementById("portfolioGenerateBtn");
  setBusy(button, true);
  setNotice("portfolioNotice", "");
  try {
    const data = await api("/api/portfolio/generate", portfolioPayload());
    state.portfolio = data;
    // Re-read full state to refresh the controls (themes, layouts, etc.)
    try { state.portfolio = await api("/api/portfolio"); } catch {}
    setPortfolioEditors(data);
    renderPortfolioOptions(state.portfolio || data);
    toast("Portfolio regenerated locally.");
  } catch (error) {
    setNotice("portfolioNotice", error.message, true);
  } finally {
    setBusy(button, false);
  }
}

async function fetchAiTagline() {
  const button = document.getElementById("portfolioAiTaglineBtn");
  const input = document.getElementById("portfolioTagline");
  if (!input) return;
  setBusy(button, true);
  try {
    const result = await api("/api/portfolio/tagline", {});
    if (result.tagline) {
      input.value = result.tagline;
      toast(result.available ? "AI tagline ready." : "Used deterministic tagline.");
    }
  } catch (error) {
    setNotice("portfolioNotice", error.message, true);
  } finally {
    setBusy(button, false);
  }
}

async function loadGithubReposForPortfolio() {
  const button = document.getElementById("portfolioGithubLoadBtn");
  const panel = document.getElementById("portfolioGithubPanel");
  const list = document.getElementById("portfolioGithubRepos");
  if (!panel || !list) return;
  setBusy(button, true);
  panel.classList.remove("hidden");
  list.innerHTML = "<p class='muted'>Loading…</p>";
  try {
    const data = await api("/api/portfolio/github-repos", {});
    state.portfolioRepos = data.repos || [];
    if (!state.portfolioRepos.length) {
      list.innerHTML = "<p class='muted'>No repos found on GitHub for that handle.</p>";
      return;
    }
    list.innerHTML = state.portfolioRepos.map((repo) => `
      <label class="check-row" style="display:grid;grid-template-columns:auto 1fr auto;gap:0.5rem;border-bottom:1px dashed var(--line);padding:0.4rem 0;align-items:start">
        <input type="checkbox" data-portfolio-repo="${escapeHtml(repo.name)}" />
        <div>
          <strong>${escapeHtml(repo.name)}</strong>
          <span class="coach-sub">${escapeHtml(repo.description || "—")}</span>
          <span class="row-tag">${escapeHtml(repo.language || "")} · ★ ${repo.stars || 0}</span>
        </div>
        <a href="${escapeHtml(repo.url)}" target="_blank" rel="noreferrer" class="muted">Open</a>
      </label>
    `).join("");
  } catch (error) {
    list.innerHTML = `<p class="notice error">${escapeHtml(error.message)}</p>`;
  } finally {
    setBusy(button, false);
  }
}

async function importSelectedGithubRepos() {
  const list = document.getElementById("portfolioGithubRepos");
  const button = document.getElementById("portfolioGithubImportBtn");
  if (!list) return;
  const names = Array.from(list.querySelectorAll('[data-portfolio-repo]:checked')).map((el) => el.dataset.portfolioRepo);
  if (!names.length) {
    toast("Tick at least one repo first.");
    return;
  }
  setBusy(button, true);
  try {
    const handle = (state.portfolio && state.portfolio.handle) || "";
    const data = await api("/api/portfolio/import-github", { repos: names, handle });
    if (data.ok) {
      toast(`Added ${data.added.length} project(s). Regenerate to see them.`);
      // Auto-regenerate so the user sees the result right away.
      await generatePortfolio();
    } else {
      toast(`Import failed: ${data.reason || "unknown"}`);
    }
  } catch (error) {
    toast(error.message);
  } finally {
    setBusy(button, false);
  }
}

async function savePortfolioEdits() {
  const button = document.getElementById("portfolioSaveBtn");
  const htmlEditor = document.getElementById("portfolioHtmlEditor");
  const cssEditor = document.getElementById("portfolioCssEditor");
  setBusy(button, true);
  try {
    const result = await api("/api/portfolio/save", {
      html: htmlEditor ? htmlEditor.value : "",
      css: cssEditor ? cssEditor.value : "",
    });
    if (result.ok) {
      const iframe = document.getElementById("portfolioPreview");
      if (iframe) iframe.src = `/api/portfolio/preview?t=${Date.now()}`;
      toast("Portfolio edits saved.");
    }
  } catch (error) {
    setNotice("portfolioNotice", error.message, true);
  } finally {
    setBusy(button, false);
  }
}

async function suggestPortfolioDesign() {
  const button = document.getElementById("portfolioSuggestBtn");
  const list = document.getElementById("portfolioSuggestions");
  setBusy(button, true);
  if (list) list.innerHTML = "<li class='muted'>Thinking locally...</li>";
  try {
    const result = await api("/api/portfolio/suggest", {});
    const items = result.suggestions || [];
    if (list) {
      list.innerHTML = items.length
        ? items.map((item) => `<li><div><span class="coach-title">${escapeHtml(item.title || "")}</span><span class="coach-sub">${escapeHtml(item.detail || "")}</span></div><strong>${result.available ? "AI" : "local"}</strong></li>`).join("")
        : "<li class='muted'>No suggestions yet.</li>";
    }
  } catch (error) {
    if (list) list.innerHTML = `<li class="notice error">${escapeHtml(error.message)}</li>`;
  } finally {
    setBusy(button, false);
  }
}

async function buildPublishGuide() {
  const button = document.getElementById("portfolioPublishBtn");
  const target = document.getElementById("portfolioPublishResult");
  setBusy(button, true);
  try {
    const result = await api("/api/portfolio/publish-guide", {});
    if (target) target.innerHTML = result.ok
      ? `Created local checklist: <code>${escapeHtml(result.path)}</code>`
      : `Failed: ${escapeHtml(result.reason || "unknown")}`;
    toast("Publish checklist ready.");
  } catch (error) {
    if (target) target.textContent = error.message;
  } finally {
    setBusy(button, false);
  }
}

// ===== Career Coach =====
function renderCoachShell() {
  document.getElementById("coachMetrics").innerHTML = [
    metric("Tracked jobs", "—"),
    metric("Avg fit", "—"),
    metric("Top gap", "—"),
    metric("Next move", "—"),
  ].join("");
}

async function generateCoachPlan() {
  const button = document.getElementById("coachRefreshBtn");
  setBusy(button, true);
  setNotice("coachNotice", "");
  try {
    const result = await api("/api/coach-plan", {});
    state.coachCache = result;
    renderCoachPlan(result);
  } catch (error) {
    setNotice("coachNotice", error.message, true);
  } finally {
    setBusy(button, false);
  }
}

function renderCoachPlan(plan) {
  const total = plan.total_tracked ?? 0;
  document.getElementById("coachMetrics").innerHTML = [
    metric("Tracked jobs", total),
    metric("Avg fit", plan.avg_score ?? "—"),
    metric("Top gap", plan.top_gap || "—"),
    metric("Next move", plan.headline || "—"),
  ].join("");
  const rankSimple = (id, items, valueKey = "count") => {
    const node = document.getElementById(id);
    if (!node) return;
    if (!items || !items.length) {
      node.innerHTML = "<li class='muted'>No data yet.</li>";
      return;
    }
    node.innerHTML = items.map((row) =>
      `<li><span class="coach-title">${escapeHtml(row.name || row.label || "")}</span><strong>${escapeHtml(String(row[valueKey] ?? row.value ?? ""))}</strong></li>`
    ).join("");
  };
  rankSimple("coachMarketSkills", plan.market_skills || []);
  rankSimple("coachGapSkills", plan.gap_skills || []);

  const focus = plan.focus || [];
  document.getElementById("coachFocus").innerHTML = focus.length
    ? focus.map((row) => `<li>
        <div>
          <span class="coach-title">${escapeHtml(row.title || row.name || "")}</span>
          <span class="coach-sub">${escapeHtml(row.why || "")}</span>
        </div>
        <strong>focus</strong>
      </li>`).join("")
    : "<li class='muted'>No data yet.</li>";

  const steps = plan.steps || [];
  document.getElementById("coachSteps").innerHTML = steps.length
    ? steps.map((step) => `<li>
        <span class="coach-title">${escapeHtml(step.title || step.text || "")}</span>
        <strong>${escapeHtml(step.deadline || step.eta || "")}</strong>
      </li>`).join("")
    : "<li class='muted'>No data yet.</li>";

  const certs = plan.certifications || [];
  const certsNode = document.getElementById("coachCerts");
  if (certsNode) {
    certsNode.innerHTML = certs.length
      ? certs.map((cert) => `<li>
          <div>
            <span class="coach-title">${cert.url ? `<a href="${escapeHtml(cert.url)}" target="_blank" rel="noreferrer">${escapeHtml(cert.name)}</a>` : escapeHtml(cert.name)}</span>
            <span class="coach-sub">Closes <em>${escapeHtml(cert.because || "")}</em> gap. ${escapeHtml(cert.free_path || "")}</span>
          </div>
          <strong>${escapeHtml(cert.duration || "")}</strong>
        </li>`).join("")
      : "<li class='muted'>Strong skill match — no obvious certs to chase.</li>";
  }

  const projects = plan.projects || [];
  const projectsNode = document.getElementById("coachProjects");
  if (projectsNode) {
    projectsNode.innerHTML = projects.length
      ? projects.map((p) => `<li>
          <div>
            <span class="coach-title">${escapeHtml(p.title || "")}</span>
            <span class="coach-sub">${escapeHtml(p.summary || "")} <br>Deliverable: ${escapeHtml(p.deliverable || "")}</span>
          </div>
          <strong>${escapeHtml(p.duration || "")}</strong>
        </li>`).join("")
      : "<li class='muted'>No project ideas — you already cover the main gaps.</li>";
  }

  const schedule = plan.schedule || [];
  const scheduleNode = document.getElementById("coachSchedule");
  if (scheduleNode) {
    scheduleNode.innerHTML = schedule.length
      ? schedule.map((row) => `<li>
          <div>
            <span class="coach-title">${escapeHtml(row.title || "")}</span>
            <span class="coach-sub">${escapeHtml(row.deadline || "")}</span>
          </div>
          <strong>${escapeHtml(row.week || "")}</strong>
        </li>`).join("")
      : "<li class='muted'>Generate a plan to see the schedule.</li>";
  }

  const interview = plan.interview_prep || {};
  const questionsNode = document.getElementById("coachQuestions");
  if (questionsNode) {
    const qs = interview.questions || [];
    questionsNode.innerHTML = qs.length
      ? qs.map((q) => `<li><div><span class="coach-title">${escapeHtml(q)}</span></div><strong></strong></li>`).join("")
      : "<li class='muted'>Generate a plan to see questions.</li>";
  }
  const scaffoldsNode = document.getElementById("coachStarScaffolds");
  if (scaffoldsNode) {
    const scaffolds = interview.star_scaffolds || [];
    scaffoldsNode.innerHTML = scaffolds.length
      ? scaffolds.map((s) => `<li>
          <div>
            <span class="coach-title">${escapeHtml(s.label || "")}</span>
            <span class="coach-sub"><strong>S:</strong> ${escapeHtml(s.situation || "")}<br>
              <strong>T:</strong> ${escapeHtml(s.task || "")}<br>
              <strong>A:</strong> ${escapeHtml(s.action || "")}<br>
              <strong>R:</strong> ${escapeHtml(s.result || "")}</span>
          </div>
          <strong>STAR</strong>
        </li>`).join("")
      : "<li class='muted'>Generate a plan to see STAR scaffolds.</li>";
  }
}

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
    try { state.autopilotStream.close(); } catch {}
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

function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  try { localStorage.setItem("job-agent-theme", theme); } catch {}
  // Charts must be re-drawn to pick up new CSS-variable colors
  if (state.insightsCache) renderInsights(state.insightsCache);
}

function initTheme() {
  let theme = "light";
  try {
    theme = localStorage.getItem("job-agent-theme") || (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  } catch {
    theme = "light";
  }
  applyTheme(theme);
}

function toggleTheme() {
  const current = document.documentElement.getAttribute("data-theme") || "light";
  applyTheme(current === "light" ? "dark" : "light");
}

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
          window.clearInterval(watcher);
          setNotice("aiSetupNotice", "Fast chat model installed.");
          await Promise.all([loadAiSetup(), loadAiStatus()]);
        } else if (s.state === "failed") {
          window.clearInterval(watcher);
          setNotice("aiSetupNotice", `Pull failed: ${s.error || "unknown"}`, true);
        }
      } catch (error) {
        window.clearInterval(watcher);
        setNotice("aiSetupNotice", error.message, true);
      }
    }, 2500);
  } catch (error) {
    setNotice("aiSetupNotice", error.message, true);
  } finally {
    setBusy(btn, false);
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
        oneClickHunt();
        return;
      }
      if (event.key === "m") {
        runMultiSearch();
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

  $("linksBtn").addEventListener("click", buildLinks);
  $("apiSearchBtn").addEventListener("click", runApiSearch);
  $("oneClickBtn").addEventListener("click", oneClickHunt);
  $("multiSearchBtn").addEventListener("click", runMultiSearch);
  const locationScope = document.getElementById("locationScopeSelect");
  if (locationScope) locationScope.addEventListener("change", applyLocationPreset);
  $("refreshJobsBtn").addEventListener("click", async () => {
    await loadJobs();
    renderState();
  });
  $("jobsRefreshBtn").addEventListener("click", async () => {
    await loadJobs();
    renderState();
  });
  $("insightsRefreshBtn").addEventListener("click", loadInsights);
  const needsManualRefreshBtn = document.getElementById("needsManualRefreshBtn");
  if (needsManualRefreshBtn) needsManualRefreshBtn.addEventListener("click", loadNeedsManual);
  $("statusFilter").addEventListener("change", loadJobs);
  $("jobsSearchInput").addEventListener("input", renderJobs);
  $("jobsSortSelect").addEventListener("change", renderJobs);
  $("filterRemote").addEventListener("change", renderJobs);
  $("filterInternship").addEventListener("change", renderJobs);
  $("filterEnriched").addEventListener("change", renderJobs);
  const extraFilters = ["filterContract", "filterRoleFamily", "filterAiVerdict", "filterMinScore", "filterLocalOnly", "filterHideRejected"];
  extraFilters.forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.addEventListener("change", renderJobs);
    if (el && el.tagName === "INPUT" && el.type === "number") el.addEventListener("input", renderJobs);
  });
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
  const removeSelectedBtn = document.getElementById("removeSelectedBtn");
  if (removeSelectedBtn) removeSelectedBtn.addEventListener("click", async () => {
    await deleteJobsBatch([...state.selectedJobs]);
  });
  $("clearSelectionBtn").addEventListener("click", () => {
    state.selectedJobs.clear();
    renderJobs();
  });
  $("addUrlBtn").addEventListener("click", addUrl);
  $("addTextBtn").addEventListener("click", addText);
  $("profileRefreshBtn").addEventListener("click", loadState);
  $("exportInternshipsBtn").addEventListener("click", exportInternships);
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

  $("autopilotStartBtn").addEventListener("click", startAutopilot);
  $("autopilotStopBtn").addEventListener("click", stopAutopilot);
  $("autopilotRefreshBtn").addEventListener("click", loadAutopilot);
  document.querySelectorAll("#contractTypeToggle .contract-btn").forEach((btn) => {
    btn.addEventListener("click", () => setContractType(btn.dataset.contract));
  });
  bindAutoApplyEvents();
  const launchBtn = document.getElementById("launchOllamaBtn");
  if (launchBtn) launchBtn.addEventListener("click", launchOllama);
  const pullBtn = document.getElementById("pullFastModelBtn");
  if (pullBtn) pullBtn.addEventListener("click", pullFastModel);
  const refreshAiBtn = document.getElementById("refreshAiSetupBtn");
  if (refreshAiBtn) refreshAiBtn.addEventListener("click", () => { loadAiSetup(); loadAiStatus(); });
  $("enrichGithubBtn").addEventListener("click", enrichGithub);
  $("enrichLinkedinBtn").addEventListener("click", openLinkedinModal);
  $("linkedinSubmitBtn").addEventListener("click", submitLinkedinSkills);
  $("linkedinCancelBtn").addEventListener("click", () => $("linkedinModal").classList.add("hidden"));
  $("closeLinkedin").addEventListener("click", () => $("linkedinModal").classList.add("hidden"));
  $("linkedinModal").addEventListener("click", (event) => {
    if (event.target === $("linkedinModal")) $("linkedinModal").classList.add("hidden");
  });
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
  const themeBtn = document.getElementById("themeToggleBtn");
  if (themeBtn) themeBtn.addEventListener("click", toggleTheme);

  // CV Studio
  const studioCompileBtn = document.getElementById("studioCompileBtn");
  if (studioCompileBtn) studioCompileBtn.addEventListener("click", studioCompile);
  const studioSaveBtn = document.getElementById("studioSaveBtn");
  if (studioSaveBtn) studioSaveBtn.addEventListener("click", studioSaveDraft);
  const studioResetBtn = document.getElementById("studioResetBtn");
  if (studioResetBtn) studioResetBtn.addEventListener("click", studioReset);
  const studioPromoteBtn = document.getElementById("studioPromoteBtn");
  if (studioPromoteBtn) studioPromoteBtn.addEventListener("click", studioPromote);
  const studioSuggestBtn = document.getElementById("studioSuggestBtn");
  if (studioSuggestBtn) studioSuggestBtn.addEventListener("click", studioSuggest);
  const studioReloadBtn = document.getElementById("studioReloadBtn");
  if (studioReloadBtn) studioReloadBtn.addEventListener("click", async () => {
    const ta = document.getElementById("studioTextarea");
    if (ta) delete ta.dataset.dirty;
    await loadStudio();
  });
  const studioReorderApplyBtn = document.getElementById("studioReorderApplyBtn");
  if (studioReorderApplyBtn) studioReorderApplyBtn.addEventListener("click", studioApplyReorder);
  const studioSwapBtn = document.getElementById("studioSwapEduExpBtn");
  if (studioSwapBtn) studioSwapBtn.addEventListener("click", studioSwapEduExp);
  const studioLangSel = document.getElementById("studioLanguage");
  if (studioLangSel) studioLangSel.addEventListener("change", (event) => studioSetLanguage(event.target.value));
  const studioTextarea = document.getElementById("studioTextarea");
  if (studioTextarea) studioTextarea.addEventListener("input", () => { studioTextarea.dataset.dirty = "1"; });

  // Studio v2 hooks
  const studioAssetReloadBtn = document.getElementById("studioAssetReloadBtn");
  if (studioAssetReloadBtn) studioAssetReloadBtn.addEventListener("click", loadStudioAssets);
  const studioAssetSaveBtn = document.getElementById("studioAssetSaveBtn");
  if (studioAssetSaveBtn) studioAssetSaveBtn.addEventListener("click", saveStudioAsset);
  const studioPhotoUploadBtn = document.getElementById("studioPhotoUploadBtn");
  if (studioPhotoUploadBtn) studioPhotoUploadBtn.addEventListener("click", uploadStudioPhoto);
  const studioPhotoRemoveBtn = document.getElementById("studioPhotoRemoveBtn");
  if (studioPhotoRemoveBtn) studioPhotoRemoveBtn.addEventListener("click", removeStudioPhoto);
  const studioIconPackApplyBtn = document.getElementById("studioIconPackApplyBtn");
  if (studioIconPackApplyBtn) studioIconPackApplyBtn.addEventListener("click", applyIconPack);
  const studioGithubImportBtn = document.getElementById("studioGithubImportBtn");
  if (studioGithubImportBtn) studioGithubImportBtn.addEventListener("click", importGithubProject);
  const studioSinglePageBtn = document.getElementById("studioSinglePageBtn");
  if (studioSinglePageBtn) studioSinglePageBtn.addEventListener("click", checkSinglePage);
  const studioAutoFitBtn = document.getElementById("studioAutoFitBtn");
  if (studioAutoFitBtn) studioAutoFitBtn.addEventListener("click", autoFitStudioDraft);
  const studioAtsBtn = document.getElementById("studioAtsBtn");
  if (studioAtsBtn) studioAtsBtn.addEventListener("click", analyzeStudioAtsKeywords);
  const studioAssetTextarea = document.getElementById("studioAssetTextarea");
  if (studioAssetTextarea) studioAssetTextarea.addEventListener("input", () => { studioAssetTextarea.dataset.dirty = "1"; });
  const studioProjectAddBtn = document.getElementById("studioProjectAddBtn");
  if (studioProjectAddBtn) studioProjectAddBtn.addEventListener("click", saveStudioProject);
  const studioProjectDeepLearningBtn = document.getElementById("studioProjectDeepLearningBtn");
  if (studioProjectDeepLearningBtn) studioProjectDeepLearningBtn.addEventListener("click", fillDeepLearningProjectTemplate);

  // Portfolio Builder
  const portfolioGenerateBtn = document.getElementById("portfolioGenerateBtn");
  if (portfolioGenerateBtn) portfolioGenerateBtn.addEventListener("click", generatePortfolio);
  const portfolioSaveBtn = document.getElementById("portfolioSaveBtn");
  if (portfolioSaveBtn) portfolioSaveBtn.addEventListener("click", savePortfolioEdits);
  const portfolioSuggestBtn = document.getElementById("portfolioSuggestBtn");
  if (portfolioSuggestBtn) portfolioSuggestBtn.addEventListener("click", suggestPortfolioDesign);
  const portfolioPublishBtn = document.getElementById("portfolioPublishBtn");
  if (portfolioPublishBtn) portfolioPublishBtn.addEventListener("click", buildPublishGuide);
  const portfolioTheme = document.getElementById("portfolioTheme");
  if (portfolioTheme) portfolioTheme.addEventListener("change", generatePortfolio);
  const portfolioFont = document.getElementById("portfolioFont");
  if (portfolioFont) portfolioFont.addEventListener("change", generatePortfolio);
  const portfolioLayout = document.getElementById("portfolioLayout");
  if (portfolioLayout) portfolioLayout.addEventListener("change", generatePortfolio);
  const portfolioAccent = document.getElementById("portfolioAccent");
  if (portfolioAccent) portfolioAccent.addEventListener("change", generatePortfolio);
  const portfolioDarkToggle = document.getElementById("portfolioDarkToggle");
  if (portfolioDarkToggle) portfolioDarkToggle.addEventListener("change", generatePortfolio);
  const portfolioAnimations = document.getElementById("portfolioAnimations");
  if (portfolioAnimations) portfolioAnimations.addEventListener("change", generatePortfolio);
  document.body.addEventListener("change", (event) => {
    if (event.target && event.target.matches('[data-portfolio-section]')) {
      generatePortfolio();
    }
  });
  const portfolioAiTaglineBtn = document.getElementById("portfolioAiTaglineBtn");
  if (portfolioAiTaglineBtn) portfolioAiTaglineBtn.addEventListener("click", fetchAiTagline);
  const portfolioGithubLoadBtn = document.getElementById("portfolioGithubLoadBtn");
  if (portfolioGithubLoadBtn) portfolioGithubLoadBtn.addEventListener("click", loadGithubReposForPortfolio);
  const portfolioGithubImportBtn = document.getElementById("portfolioGithubImportBtn");
  if (portfolioGithubImportBtn) portfolioGithubImportBtn.addEventListener("click", importSelectedGithubRepos);
  const portfolioGithubCloseBtn = document.getElementById("portfolioGithubCloseBtn");
  if (portfolioGithubCloseBtn) portfolioGithubCloseBtn.addEventListener("click", () => {
    document.getElementById("portfolioGithubPanel")?.classList.add("hidden");
  });

  // Studio suggestion apply / reset / dismiss (delegated)
  document.body.addEventListener("click", (event) => {
    const apply = event.target.closest("[data-suggest-apply-idx]");
    if (apply) {
      const idx = Number(apply.dataset.suggestApplyIdx);
      const suggestion = (state.studioSuggestions || [])[idx];
      if (!suggestion) return;
      const editEl = document.querySelector(`[data-suggest-after-edit="${idx}"]`);
      const after = editEl ? editEl.value : suggestion.after;
      if (/\[[A-Za-z0-9_\- ]+\]/.test(after)) {
        if (!window.confirm("Your text still contains placeholders like [X]. Apply anyway?")) return;
      }
      studioApplySuggestion(suggestion.before, after);
      const card = apply.closest("[data-suggest-idx]");
      if (card) card.style.opacity = "0.55";
      return;
    }
    const reset = event.target.closest("[data-suggest-reset-idx]");
    if (reset) {
      const idx = Number(reset.dataset.suggestResetIdx);
      const suggestion = (state.studioSuggestions || [])[idx];
      const editEl = document.querySelector(`[data-suggest-after-edit="${idx}"]`);
      if (suggestion && editEl) editEl.value = suggestion.after;
      return;
    }
    const dismiss = event.target.closest("[data-suggest-dismiss-idx]");
    if (dismiss) {
      const card = dismiss.closest("[data-suggest-idx]");
      if (card) card.remove();
      return;
    }
    // Backward-compat: the old data-suggest-apply attribute may still exist.
    const legacy = event.target.closest("[data-suggest-apply]");
    if (legacy) {
      const [before, after] = legacy.dataset.suggestApply.split("|||");
      studioApplySuggestion(before, after);
    }
  });

  // Career Coach
  const coachBtn = document.getElementById("coachRefreshBtn");
  if (coachBtn) coachBtn.addEventListener("click", generateCoachPlan);
  const coachAuditBtn = document.getElementById("coachAuditBtn");
  if (coachAuditBtn) coachAuditBtn.addEventListener("click", runRecruiterAudit);
  const coachSkillsBtn = document.getElementById("coachSkillsBtn");
  if (coachSkillsBtn) coachSkillsBtn.addEventListener("click", runSkillSuggestions);
  const insightsMarketBtn = document.getElementById("insightsMarketBtn");
  if (insightsMarketBtn) insightsMarketBtn.addEventListener("click", runMarketReport);
  const headhunterBtn = document.getElementById("headhunterBtn");
  if (headhunterBtn) headhunterBtn.addEventListener("click", runHeadhunter);

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
      await loadAutopilot();
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
      await loadAutopilot();
    } catch (error) {
      toast(`Clear failed: ${error.message}`);
    } finally {
      setBusy(clearBrokenBtn, false);
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
    const aiTarget = event.target.closest("[data-action='ai-analyze']");
    if (aiTarget) {
      runAiAnalysis(aiTarget.dataset.job, aiTarget);
      return;
    }
    const chatTarget = event.target.closest("[data-action='ai-chat']");
    if (chatTarget) {
      const jobId = chatTarget.dataset.job;
      const job = state.jobs.find((item) => item.id === jobId);
      if (job) openChatModal(job);
      return;
    }
    const outreachTarget = event.target.closest("[data-action='outreach']");
    if (outreachTarget) {
      generateOutreachEmail(outreachTarget.dataset.job, outreachTarget);
      return;
    }
    const linkedinTarget = event.target.closest("[data-action='linkedin']");
    if (linkedinTarget) {
      generateLinkedInMessage(linkedinTarget.dataset.job, linkedinTarget);
      return;
    }
    const interviewTarget = event.target.closest("[data-action='interview']");
    if (interviewTarget) {
      generateInterviewPrep(interviewTarget.dataset.job, interviewTarget);
      return;
    }
    const followupTarget = event.target.closest("[data-action='followup']");
    if (followupTarget) {
      generateFollowupEmail(followupTarget.dataset.job, followupTarget);
      return;
    }
    const statusTarget = event.target.closest("[data-action='status']");
    if (statusTarget) {
      updateJobStatus(statusTarget.dataset.job, statusTarget.dataset.status, statusTarget);
      return;
    }
    const needsManualDone = event.target.closest("[data-action='needs-manual-done']");
    if (needsManualDone) {
      markNeedsManualDone(needsManualDone.dataset.job, needsManualDone);
      return;
    }
    const deleteTarget = event.target.closest("[data-action='delete-job']");
    if (deleteTarget) {
      deleteJob(deleteTarget.dataset.job, deleteTarget);
      return;
    }
    const checkbox = event.target.closest("[data-select-job]");
    if (checkbox) {
      const jobId = checkbox.dataset.selectJob;
      if (checkbox.checked) state.selectedJobs.add(jobId);
      else state.selectedJobs.delete(jobId);
      refreshSelectionUi();
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

// ── Auto-Apply ───────────────────────────────────────────────────────────────

const autoApplyState = { mode: "fill_and_confirm", stream: null, countdown: null };

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
    try { autoApplyState.stream.close(); } catch {}
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
      const listing = job.apply_url ? `<a href="${escapeHtml(job.apply_url)}" target="_blank" rel="noreferrer">Open listing</a>` : "";
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

initTheme();
bindEvents();
bindKeyboardShortcuts();
loadAiStatus();
loadState()
  .then(() => buildLinks())
  .catch((error) => {
    setNotice("searchNotice", error.message, true);
  });
// Only poll AI status when the tab is visible — saves CPU when minimized.
function _pollAiIfVisible() {
  if (document.visibilityState === "visible") loadAiStatus();
}
window.setInterval(_pollAiIfVisible, 120000);
document.addEventListener("visibilitychange", _pollAiIfVisible);
