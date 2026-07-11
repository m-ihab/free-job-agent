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
              <td><a href="${safeHref(link.url)}" target="_blank" rel="noreferrer">Open search</a></td>
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

function searchResultRow(job) {
  return `<tr>
        <td><strong>${escapeHtml(job.title)}</strong><br>${companyLine(job)}</td>
        <td>${escapeHtml(job.location || "")}</td>
        <td>${scorePill(job.fit_score)}</td>
        <td>${escapeHtml(job.status || "")}</td>
        <td class="actions">${jobActions(job)}</td>
      </tr>`;
}

function renderApiResults(jobs, failures = []) {
  if ((!jobs || !jobs.length) && (!failures || !failures.length)) {
    $("apiResults").innerHTML = "";
    return;
  }
  const jobRows = (jobs || []).slice(0, 80).map((job) => searchResultRow(job)).join("");
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

// Jobs-tab pins: tick a tracked job to keep it visible (floated to the top, and
// shown even when the current search/filter would otherwise hide it).
const pinnedJobIds = new Set();

function toggleJobPin(jobId) {
  if (pinnedJobIds.has(jobId)) pinnedJobIds.delete(jobId);
  else pinnedJobIds.add(jobId);
  renderJobs();
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

function workAuthBadge(job) {
  const value = job.work_auth_class || "";
  if (value === "directly_applicable") return renderBadge("Work auth: direct", "good");
  if (value === "sponsorship_gated") return renderBadge("Needs sponsorship", "warn");
  if (value === "unknown") return renderBadge("Work auth: verify", "");
  return "";
}

function gratificationBadge(job) {
  const warning = job.gratification_warning || {};
  if (!warning.flagged) return "";
  return `<span class="badge warn" title="${escapeHtml(warning.reason || "Check stage gratification")}">Gratification</span>`;
}

function preflightVerdictBadge(result) {
  if (!result || !result.verdict) return "";
  const tone = result.verdict === "APPLY" ? "good"
    : result.verdict === "SKIP" ? "bad"
      : result.verdict === "NEEDS_MANUAL" ? "warn"
        : "";
  return renderBadge(`Preflight: ${result.verdict.replaceAll("_", " ")}`, tone);
}

function renderPreflightPanel(job) {
  const result = state.preflight[job.id];
  if (!result) {
    return `<div class="detail-block">
      <h4>Application preflight</h4>
      <p class="muted">Run Preflight to check must-have coverage, ATS keywords, manual blockers, and defensible evidence before spending time on this role.</p>
      <button data-action="preflight" data-job="${escapeHtml(job.id)}">Run preflight</button>
    </div>`;
  }
  const safe = (result.safe_keywords_to_add || []).slice(0, 10);
  const unsafe = (result.unsafe_claims_to_avoid || []).slice(0, 10);
  const missing = (result.missing_must_haves || []).slice(0, 8);
  const unknown = (result.unknown_screening_answers || []).slice(0, 5);
  const evidence = (result.best_evidence_items || []).slice(0, 4);
  return `<div class="detail-block">
    <h4>Application preflight</h4>
    <div class="detail-row"><span>Verdict</span>${preflightVerdictBadge(result)}</div>
    <div class="detail-row"><span>Fit</span>${scorePill(result.fit_score)}</div>
    <div class="detail-row"><span>Must-haves</span><strong>${Math.round((result.must_have_coverage || 0) * 100)}%</strong></div>
    <div class="detail-row"><span>ATS keywords</span><strong>${Math.round((result.keyword_coverage || 0) * 100)}%</strong></div>
    <div class="detail-row"><span>Effort</span><strong>${escapeHtml(result.application_effort || "-")}</strong></div>
    <div class="detail-row"><span>Recruiter confidence</span><strong>${Math.round((result.recruiter_confidence || 0) * 100)}%</strong></div>
    ${missing.length ? `<h4>Missing must-haves</h4><p>${missing.map(escapeHtml).join(", ")}</p>` : ""}
    ${safe.length ? `<h4>Safe keywords</h4><p>${safe.map((item) => `<span class="badge good">${escapeHtml(item)}</span>`).join(" ")}</p>` : ""}
    ${unsafe.length ? `<h4>Do not claim without proof</h4><p>${unsafe.map((item) => `<span class="badge bad">${escapeHtml(item)}</span>`).join(" ")}</p>` : ""}
    ${unknown.length ? `<h4>Manual screening answers</h4><ul>${unknown.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>` : ""}
    ${evidence.length ? `<h4>Best evidence</h4><ul>${evidence.map((item) => `<li><strong>${escapeHtml(item.label || "")}</strong> - ${escapeHtml(item.value || "")}</li>`).join("")}</ul>` : ""}
  </div>`;
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
  const applied = jobs.filter((job) => ["APPLIED", "MANUALLY_SUBMITTED", "AUTO_SUBMITTED"].includes(job.status)).length;
  const sponsorship = jobs.filter((job) => job.work_auth_class === "sponsorship_gated").length;
  $("jobsMetrics").innerHTML = [
    metric("Visible", jobs.length),
    metric("Enriched", enriched),
    metric("Internships", internships),
    metric("Applied", applied),
    metric("Sponsorship gated", sponsorship),
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
    ? `<a href="${safeHref(job.apply_url)}" target="_blank" rel="noreferrer">Apply URL</a>`
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
      <div class="detail-row"><span>Work auth</span><strong>${workAuthBadge(job) || escapeHtml(job.work_auth_rationale || "Verify")}</strong></div>
      ${job.gratification_warning?.flagged ? `<div class="detail-row"><span>Gratification</span><strong>${gratificationBadge(job)} ${escapeHtml(job.gratification_warning.reason || "")}</strong></div>` : ""}
      <div class="detail-row"><span>Apply</span>${apply}</div>
    </div>
    <div class="detail-block">
      <h4>Tech stack</h4>
      <p>${escapeHtml(techStack || "No tech stack signals.")}</p>
      <h4>Missing requirements</h4>
      <p>${escapeHtml((job.missing_requirements || []).join(", ") || "None tracked.")}</p>
    </div>
    ${renderPreflightPanel(job)}
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
  const workAuthFilter = $("filterWorkAuth") ? $("filterWorkAuth").value : "";
  const hideSponsorship = $("filterHideSponsorship") ? $("filterHideSponsorship").checked : false;
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
  if (workAuthFilter) jobs = jobs.filter((job) => (job.work_auth_class || "unknown") === workAuthFilter);
  if (hideSponsorship) jobs = jobs.filter((job) => job.work_auth_class !== "sponsorship_gated");
  if (aiVerdictFilter) {
    if (aiVerdictFilter === "unknown") jobs = jobs.filter((job) => !job.ai_verdict);
    else jobs = jobs.filter((job) => job.ai_verdict === aiVerdictFilter);
  }
  if (minScore > 0) jobs = jobs.filter((job) => (job.fit_score ?? 0) >= minScore);
  jobs = sortJobs(jobs, sortMode);

  // Pinned jobs stay visible: re-add any the filter hid, then float all pinned
  // jobs to the top so they remain in view while you search/filter the rest.
  let hiddenPinnedCount = 0;
  if (pinnedJobIds.size) {
    const present = new Set(jobs.map((job) => job.id));
    const hiddenPinned = state.jobs.filter((job) => pinnedJobIds.has(job.id) && !present.has(job.id));
    hiddenPinnedCount = hiddenPinned.length;
    const pinned = [];
    const rest = [];
    for (const job of [...hiddenPinned, ...jobs]) {
      (pinnedJobIds.has(job.id) ? pinned : rest).push(job);
    }
    jobs = [...pinned, ...rest];
  }

  renderJobsMetrics(jobs);

  const pinGlyph = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 17v5M9 4h6l1 7 2.5 2.5H5.5L8 11z"/></svg>`;
  const rows = jobs
    .map(
      (job) => {
        const checked = state.selectedJobs.has(job.id) ? "checked" : "";
        const isPinned = pinnedJobIds.has(job.id);
        const pinnedClass = isPinned ? " pinned-row" : "";
        const activeClass = state.activeJobId === job.id ? "active-row" : "";
        const summary = job.ai_summary ? `<div class="row-summary">${escapeHtml(job.ai_summary)}</div>` : "";
        const aiBadge = aiVerdictBadge(job);
        const authBadge = workAuthBadge(job);
        const grantBadge = gratificationBadge(job);
        const preflightBadge = preflightVerdictBadge(state.preflight[job.id]);
        const tags = aiTagsHtml(job);
        const langWarn = (job.risk_flags || []).includes("LANGUAGE_MISMATCH")
          ? `<span class="badge-lang-warn" title="This job requires French — your profile is English-only">⚠ French required</span>`
          : "";
        // One "Job" cell carries title + pin toggle + company + meta row
        // (location/remote/status/enriched) so the table fits without
        // horizontal scrolling.
        const pinBtn = `<button class="pin-btn${isPinned ? " pinned" : ""}" data-action="job-pin" data-job="${escapeHtml(job.id)}" title="${isPinned ? "Unpin" : "Pin to keep visible while filtering"}" aria-pressed="${isPinned}">${pinGlyph}</button>`;
        const metaBits = [
          job.location ? escapeHtml(job.location) : "",
          job.remote ? renderBadge("Remote", "good") : "",
          statusBadge(job.status),
          job.enriched ? `<span class="row-tag" title="Enriched with France Travail data">enriched</span>` : "",
        ].filter(Boolean).join(" ");
        return `<tr data-job-row="${escapeHtml(job.id)}" class="${activeClass}${pinnedClass}">
          <td><input type="checkbox" data-select-job="${escapeHtml(job.id)}" ${checked} /></td>
          <td><strong>${escapeHtml(job.title)}</strong>${pinBtn}${langWarn}<br>${companyLine(job)}<div class="job-meta-row">${metaBits}</div>${summary}${tags}</td>
          <td>${scorePill(job.fit_score)}${preflightBadge ? `<br>${preflightBadge}` : ""}${aiBadge ? `<br>${aiBadge}` : ""}${authBadge ? `<br>${authBadge}` : ""}${grantBadge ? `<br>${grantBadge}` : ""}</td>
          <td class="actions">${jobActions(job)}</td>
        </tr>`;
      },
    )
    .join("");
  const pinNote = hiddenPinnedCount
    ? ` <span class="row-tag">+${hiddenPinnedCount} pinned kept visible</span>`
    : "";
  const countLine = `<div class="jobs-count muted">Showing <strong>${jobs.length}</strong> of <strong>${state.jobs.length}</strong> tracked jobs${pinNote}</div>`;
  $("jobsTableWrap").innerHTML = countLine + `<table>
    <thead><tr><th></th><th>Job</th><th>Score</th><th>Actions</th></tr></thead>
    <tbody>${rows}</tbody>
  </table>`;
  refreshSelectionUi();
}

// Map a job status to a small tone-coded pill.
const _STATUS_TONE = {
  REJECTED: "bad",
  NEEDS_MANUAL: "warn",
  APPLIED: "good",
  SUBMITTED: "good",
  INTERVIEW: "good",
  OFFERED: "good",
  ACCEPTED: "good",
};

function statusBadge(status) {
  const key = String(status || "").toUpperCase();
  const tone = _STATUS_TONE[key] || "";
  const label = key.replace(/_/g, " ").toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase());
  return renderBadge(label || "—", tone);
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

// Outreach engine toggle: "auto" tries local Ollama (with template fallback),
// "standard" forces the deterministic templates. Read once per request.
function outreachEngine() {
  const select = document.getElementById("outreachEngine");
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
    const payload = await api("/api/followup-email", { job_id: jobId, type: "week1", engine: outreachEngine() });
    openTextModal(`Follow-up Email Draft${engineSuffix(payload.engine)}`, payload.email_md, "Copy");
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
  toast("Tailoring application packet…");
  try {
    const payload = await api("/api/generate-packet", { job_id: jobId, force });
    toast("Packet ready: open the available document links on this row.");
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

async function generateCoverLetter(jobId, button) {
  setBusy(button, true);
  try {
    await api("/api/cover-letter", { job_id: jobId }, "POST", 120000);
    toast("Cover letter generated.");
    await loadJobs();
    renderState();
  } catch (error) {
    toast(`Cover letter failed: ${error.message}`);
  } finally {
    setBusy(button, false);
  }
}

async function runPreflight(jobId, button) {
  setBusy(button, true);
  try {
    const payload = await api("/api/preflight", { job_id: jobId }, "POST", 60000);
    state.preflight[jobId] = payload.preflight || {};
    const job = state.jobs.find((item) => item.id === jobId);
    if (job) renderEnrichmentDetails(job);
    renderJobs();
    toast(`Preflight: ${(state.preflight[jobId].verdict || "ready").replaceAll("_", " ")}`);
  } catch (error) {
    toast(`Preflight failed: ${error.message}`);
  } finally {
    setBusy(button, false);
  }
}

async function enrichBatch(jobIds) {
  if (!jobIds.length) {
    toast("No jobs selected for enrichment.");
    return;
  }
  try {
    const payload = await api("/api/enrich-batch", { job_ids: jobIds });
    const okCount = payload.results?.filter((row) => row.ok).length || 0;
    toast(`Batch enrichment complete: ${okCount}/${payload.count}`);
    await loadJobs();
    renderState();
  } catch (error) {
    toast(`Batch enrichment failed: ${error.message}`);
  }
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
// NOTE: tracker stays in app.js on purpose — kanban.js monkey-patches
// window.renderTracker (top-level declaration binding); an IIFE move
// would bypass that patch. Refactor to events before extracting.
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
  if (name === "jobs") renderJobs();
  if (name === "pipeline" && window.JobAgentPipeline) window.JobAgentPipeline.load();
  if (name === "tracker") loadTracker();
  if (name === "insights" && !state.insightsCache && window.JobAgentInsights) window.JobAgentInsights.load();
  if (name === "autopilot") {
    if (window.JobAgentAutopilot) window.JobAgentAutopilot.load();
    loadAiSetup();
    loadAiTrace();
    loadNeedsManual();
  }
  if (name === "studio") {
    if (window.JobAgentStudio) window.JobAgentStudio.load();
    if (window.JobAgentStudioTools) {
      window.JobAgentStudioTools.loadAssets();
      window.JobAgentStudioTools.loadGithubProjects();
    }
  }
  if (name === "portfolio" && window.JobAgentPortfolio) window.JobAgentPortfolio.load();
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
  const needsManualRefreshBtn = document.getElementById("needsManualRefreshBtn");
  if (needsManualRefreshBtn) needsManualRefreshBtn.addEventListener("click", loadNeedsManual);
  $("statusFilter").addEventListener("change", loadJobs);
  $("jobsSearchInput").addEventListener("input", renderJobs);
  $("jobsSortSelect").addEventListener("change", renderJobs);
  $("filterRemote").addEventListener("change", renderJobs);
  $("filterInternship").addEventListener("change", renderJobs);
  $("filterEnriched").addEventListener("change", renderJobs);
  const extraFilters = [
    "filterContract",
    "filterRoleFamily",
    "filterAiVerdict",
    "filterWorkAuth",
    "filterMinScore",
    "filterLocalOnly",
    "filterHideSponsorship",
    "filterHideRejected",
  ];
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

  bindAutoApplyEvents();
  const launchBtn = document.getElementById("launchOllamaBtn");
  if (launchBtn) launchBtn.addEventListener("click", launchOllama);
  const pullBtn = document.getElementById("pullFastModelBtn");
  if (pullBtn) pullBtn.addEventListener("click", pullFastModel);
  const refreshAiBtn = document.getElementById("refreshAiSetupBtn");
  if (refreshAiBtn) refreshAiBtn.addEventListener("click", () => { loadAiSetup(); loadAiStatus(); });
  const aiTraceRefreshBtn = document.getElementById("aiTraceRefreshBtn");
  if (aiTraceRefreshBtn) aiTraceRefreshBtn.addEventListener("click", loadAiTrace);
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

  // Insights / headhunter extras (bindings stay with app.js functions)
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
      runPreflight(preflightTarget.dataset.job, preflightTarget);
      return;
    }
    const target = event.target.closest("[data-action='packet']");
    if (target) {
      generatePacket(target.dataset.job, target);
      return;
    }
    const coverLetterTarget = event.target.closest("[data-action='cover-letter']");
    if (coverLetterTarget) {
      generateCoverLetter(coverLetterTarget.dataset.job, coverLetterTarget);
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
    const jobPinTarget = event.target.closest("[data-action='job-pin']");
    if (jobPinTarget) {
      toggleJobPin(jobPinTarget.dataset.job);
      return;
    }
    const briefTarget = event.target.closest("[data-action='brief']");
    if (briefTarget) {
      generateBrief(briefTarget.dataset.job, briefTarget);
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
