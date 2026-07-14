// Search planning, link generation, and API/multi-source search (R3 split from app.js).
// Classic script, defer, after app.js; kernel helpers remain window globals.
(function () {
  const $ = (id) => document.getElementById(id);
  const api = (...args) => window.api(...args);
  const toast = (...args) => window.toast(...args);
  const setBusy = (...args) => window.setBusy(...args);
  const setNotice = (...args) => window.setNotice(...args);
  const escapeHtml = (value) => window.escapeHtml(value);
  const safeHref = (value) => window.safeHref(value);
  const metric = (...args) => window.metric(...args);
  const renderBadge = (...args) => window.renderBadge(...args);
  const scorePill = (...args) => window.scorePill(...args);
  const companyLine = (job) => window.companyLine(job);
  const jobActions = (job) => window.jobActions(job);
  const loadJobs = (...args) => window.loadJobs(...args);
  const renderState = (...args) => window.renderState(...args);

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

  // ---- event bindings (moved from bindEvents) ----
  $("linksBtn").addEventListener("click", buildLinks);
  $("apiSearchBtn").addEventListener("click", runApiSearch);
  $("oneClickBtn").addEventListener("click", oneClickHunt);
  $("multiSearchBtn").addEventListener("click", runMultiSearch);
  const locationScope = document.getElementById("locationScopeSelect");
  if (locationScope) locationScope.addEventListener("change", applyLocationPreset);

  window.oneClickHunt = oneClickHunt;
  window.runMultiSearch = runMultiSearch;
  window.JobAgentSearch = { buildLinks, runMultiSearch, oneClickHunt };
})();
