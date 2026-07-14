// Jobs rendering, filters, selection, preflight, and job actions (R3 split from app.js).
// Classic script, defer, after app.js; `state` is app.js's shared script-scope global.
(function () {
  const $ = (id) => document.getElementById(id);
  const api = (...args) => window.api(...args);
  const toast = (...args) => window.toast(...args);
  const setBusy = (...args) => window.setBusy(...args);
  const escapeHtml = (value) => window.escapeHtml(value);
  const renderBadge = (...args) => window.renderBadge(...args);
  const scorePill = (...args) => window.scorePill(...args);
  const metric = (...args) => window.metric(...args);
  const safeHref = (value) => window.safeHref(value);
  const fileHref = (value) => window.fileHref(value);
  const companyLine = (job) => window.companyLine(job);
  const jobActions = (job) => window.jobActions(job);
  const feedbackControls = (job) => window.JobAgentFeedback?.controls(job) || "";
  const loadJobs = (...args) => window.loadJobs(...args);
  const renderState = (...args) => window.renderState(...args);

// Jobs-tab pins: tick a tracked job to keep it visible (floated to the top, and
// shown even when the current search/filter would otherwise hide it).
const pinnedJobIds = new Set();

function toggleJobPin(jobId) {
  if (pinnedJobIds.has(jobId)) pinnedJobIds.delete(jobId);
  else pinnedJobIds.add(jobId);
  renderJobs();
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
    return list.sort((a, b) => (b.adjusted_fit_score ?? b.fit_score ?? -1) - (a.adjusted_fit_score ?? a.fit_score ?? -1));
  }
  if (mode === "ai") {
    return list.sort((a, b) => {
      const va = _AI_VERDICT_RANK[a.ai_verdict || ""] || 0;
      const vb = _AI_VERDICT_RANK[b.ai_verdict || ""] || 0;
      if (vb !== va) return vb - va;
      return (b.ai_score ?? b.adjusted_fit_score ?? b.fit_score ?? -1) - (a.ai_score ?? a.adjusted_fit_score ?? a.fit_score ?? -1);
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
      <div class="detail-row"><span>Score</span>${scorePill(job.adjusted_fit_score ?? job.fit_score)}</div>
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
  if (minScore > 0) jobs = jobs.filter((job) => (job.adjusted_fit_score ?? job.fit_score ?? 0) >= minScore);
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
          <td>${scorePill(job.adjusted_fit_score ?? job.fit_score)}${feedbackControls(job)}${preflightBadge ? `<br>${preflightBadge}` : ""}${aiBadge ? `<br>${aiBadge}` : ""}${authBadge ? `<br>${authBadge}` : ""}${grantBadge ? `<br>${grantBadge}` : ""}</td>
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

  // ---- event bindings (moved from bindEvents) ----
  $("refreshJobsBtn").addEventListener("click", async () => {
    await loadJobs();
    renderState();
  });
  $("jobsRefreshBtn").addEventListener("click", async () => {
    await loadJobs();
    renderState();
  });
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

  window.generatePacket = generatePacket;
  window.generateCoverLetter = generateCoverLetter;
  window.runPreflight = runPreflight;
  window.deleteJob = deleteJob;

  window.JobAgentJobs = {
    renderJobs,
    renderJobsMetrics,
    refreshSelectionUi,
    toggleJobPin,
    renderEnrichmentDetails,
    generatePacket,
    generateCoverLetter,
    runPreflight,
    enrichJob,
    updateJobStatus,
    deleteJob,
  };
})();
