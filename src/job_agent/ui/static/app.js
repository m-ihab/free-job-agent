const state = {
  profile: null,
  statuses: [],
  jobs: [],
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
  window.setTimeout(() => node.classList.add("hidden"), 3200);
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

function renderState() {
  const profile = state.profile || {};
  $("statusStrip").innerHTML = [
    renderBadge(profile.valid ? "Profile ready" : "Profile needs review", profile.valid ? "good" : "bad"),
    renderBadge(profile.france_travail_configured ? "France Travail API ready" : "API not configured", profile.france_travail_configured ? "good" : "warn"),
    renderBadge(profile.latex_ready ? `LaTeX: ${profile.latex_compiler}` : "LaTeX compiler missing", profile.latex_ready ? "good" : "warn"),
  ].join("");

  $("statusFilter").innerHTML = `<option value="">All statuses</option>${state.statuses
    .map((status) => `<option value="${escapeHtml(status)}">${escapeHtml(status)}</option>`)
    .join("")}`;

  $("profileMetrics").innerHTML = [
    metric("Profile", profile.valid ? "Ready" : "Review"),
    metric("France Travail", profile.france_travail_configured ? "Ready" : "Missing"),
    metric("LaTeX", profile.latex_ready ? profile.latex_compiler : "Missing"),
    metric("Tracked jobs", state.jobs.length),
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

function metric(label, value) {
  return `<div class="metric"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`;
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
    .map((group, index) => {
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
        <summary>${escapeHtml(group.query)} · ${group.links.length} boards</summary>
        <div class="table-wrap">
          <table>
            <thead><tr><th>Board</th><th>Link</th><th>Note</th></tr></thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
      </details>`;
    })
    .join("");
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
        <td><strong>${escapeHtml(job.title)}</strong><br>${escapeHtml(job.company)}</td>
        <td>${escapeHtml(job.location || "")}</td>
        <td>${escapeHtml(job.fit_score ?? "")}</td>
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
  return `<div class="row-actions">
    <button data-action="packet" data-job="${escapeHtml(job.id)}">Optimize</button>
    ${apply}${assistant}${cv}${letter}
  </div>`;
}

function renderJobs() {
  if (!state.jobs.length) {
    $("jobsTableWrap").innerHTML = `<div class="notice">No tracked jobs yet.</div>`;
    return;
  }
  const rows = state.jobs
    .map(
      (job) => `<tr>
        <td><strong>${escapeHtml(job.title)}</strong><br>${escapeHtml(job.company)}</td>
        <td>${escapeHtml(job.location || "")}</td>
        <td>${escapeHtml(job.status)}</td>
        <td>${escapeHtml(job.fit_score ?? "")}</td>
        <td>${escapeHtml((job.tech_stack || []).slice(0, 5).join(", "))}</td>
        <td class="actions">${jobActions(job)}</td>
      </tr>`,
    )
    .join("");
  $("jobsTableWrap").innerHTML = `<table>
    <thead><tr><th>Job</th><th>Location</th><th>Status</th><th>Score</th><th>Signals</th><th>Actions</th></tr></thead>
    <tbody>${rows}</tbody>
  </table>`;
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

async function oneClickHunt() {
  const button = $("oneClickBtn");
  setBusy(button, true);
  setNotice("searchNotice", "");
  try {
    const payload = await api("/api/one-click-hunt", searchPayload());
    renderSearchMetrics({ ...payload, query_count: payload.manual?.query_count, link_count: payload.manual?.link_count });
    renderManualGroups(payload.manual?.groups || []);
    renderApiResults(payload.jobs || [], payload.failures || []);
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

function bindEvents() {
  document.querySelectorAll(".tab").forEach((button) => {
    button.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((tab) => tab.classList.remove("active"));
      document.querySelectorAll(".tab-panel").forEach((panel) => panel.classList.remove("active"));
      button.classList.add("active");
      $(`tab-${button.dataset.tab}`).classList.add("active");
      if (button.dataset.tab === "jobs") renderJobs();
    });
  });

  $("linksBtn").addEventListener("click", buildLinks);
  $("apiSearchBtn").addEventListener("click", runApiSearch);
  $("oneClickBtn").addEventListener("click", oneClickHunt);
  $("refreshJobsBtn").addEventListener("click", async () => {
    await loadJobs();
    renderState();
  });
  $("jobsRefreshBtn").addEventListener("click", async () => {
    await loadJobs();
    renderState();
  });
  $("statusFilter").addEventListener("change", loadJobs);
  $("addUrlBtn").addEventListener("click", addUrl);
  $("addTextBtn").addEventListener("click", addText);
  $("profileRefreshBtn").addEventListener("click", loadState);
  $("exportInternshipsBtn").addEventListener("click", exportInternships);
  $("copyApiTextBtn").addEventListener("click", async () => {
    const text = `App name: ${$("apiAppName").value}\nURL: ${$("apiAppUrl").value}\nDescription: ${$("apiAppDescription").value}`;
    await navigator.clipboard.writeText(text);
    toast("Copied API application text.");
  });

  document.body.addEventListener("click", (event) => {
    const target = event.target.closest("[data-action='packet']");
    if (target) {
      generatePacket(target.dataset.job, target);
    }
  });
}

bindEvents();
loadState()
  .then(() => buildLinks())
  .catch((error) => {
    setNotice("searchNotice", error.message, true);
  });

