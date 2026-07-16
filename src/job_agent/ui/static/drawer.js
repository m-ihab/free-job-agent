/* Job detail drawer — slide-over with score ring, A-F evaluation dimensions,
   salary context, AI read, and relevant STAR stories. Uses app.js globals;
   `state` is app.js's top-level const (bare global, not window.state). */
(function () {
  const $ = (id) => document.getElementById(id);
  const esc = (value) => window.escapeHtml(String(value ?? ""));

  let currentJob = null;

  function ringColor(score) {
    if (score === null || score === undefined) return "var(--muted)";
    if (score >= 85) return "var(--grade-a)";
    if (score >= 70) return "var(--grade-b)";
    if (score >= 55) return "var(--grade-c)";
    if (score >= 40) return "var(--grade-d)";
    return "var(--grade-f)";
  }

  function gradeChip(grade) {
    if (!grade) return "";
    return `<span class="grade-chip grade-${esc(grade)}">${esc(grade)}</span>`;
  }

  function findJob(jobId) {
    return (state.jobs || []).find((job) => job.id === jobId) || null;
  }

  function renderHead(job) {
    const score = job.fit_score === null || job.fit_score === undefined ? null : Math.round(job.fit_score);
    const ring = $("drawerRing");
    ring.style.setProperty("--ring-value", score ?? 0);
    ring.style.setProperty("--ring-color", ringColor(score));
    ring.textContent = score === null ? "–" : String(score);
    $("drawerTitle").textContent = job.title;
    $("drawerCompany").textContent = [job.company_display || job.company, job.location].filter(Boolean).join(" · ");
    const tags = [];
    if (job.status) tags.push(`<span class="row-tag">${esc(job.status.replace(/_/g, " "))}</span>`);
    if (job.ai_contract) tags.push(`<span class="row-tag">${esc(job.ai_contract)}</span>`);
    if (job.remote) tags.push(`<span class="row-tag">remote</span>`);
    (job.ai_tags || []).slice(0, 4).forEach((tag) => tags.push(`<span class="row-tag">${esc(tag)}</span>`));
    $("drawerTags").innerHTML = tags.join("");
  }

  function renderActions(job) {
    const applyLink = job.apply_url
      ? `<a class="button-link" href="${window.safeHref(job.apply_url)}" target="_blank" rel="noreferrer">Open posting ↗</a>`
      : "";
    $("drawerActions").innerHTML = `
      <button class="primary" data-drawer-action="packet">Tailor CV</button>
      <button data-drawer-action="cover-letter">Cover letter</button>
      <button data-drawer-action="preflight">Preflight</button>
      <button data-drawer-action="ai-fit">AI fit</button>
      <button data-drawer-action="chat">Chat</button>
      <button data-drawer-action="brain">Open in Brain</button>
      ${applyLink}
      <button class="ghost" data-drawer-action="delete">Remove</button>`;
  }

  function renderAi(job) {
    const parts = [];
    if (job.ai_verdict) parts.push(`<strong>${esc(job.ai_verdict)}</strong>${job.ai_score ? ` (${esc(job.ai_score)}/100)` : ""}`);
    if (job.ai_summary) parts.push(esc(job.ai_summary));
    if ((job.ai_must_haves || []).length) parts.push(`<span class="muted">Must-haves:</span> ${job.ai_must_haves.slice(0, 6).map(esc).join(", ")}`);
    $("drawerAi").innerHTML = parts.length ? parts.join("<br>") : `<span class="muted">No cached AI analysis yet — click "AI fit".</span>`;
  }

  async function renderEvaluation(job) {
    const dims = $("drawerDims");
    const salary = $("drawerSalary");
    dims.innerHTML = `<span class="muted">Evaluating locally…</span>`;
    try {
      const payload = await window.api("/api/evaluate", { job_id: job.id });
      const evaluation = payload.evaluation || {};
      $("drawerGrade").innerHTML = `${gradeChip(evaluation.overall_grade)} <span class="muted">${esc(evaluation.overall_score)}/100 · ${esc(evaluation.recommendation || "")}</span>`;
      dims.innerHTML = (evaluation.dimensions || []).map((dim) => `
        <div class="dim-row">
          <span class="muted">${esc(dim.name.replace(/_/g, " "))}</span>
          <span class="dim-bar"><span class="dim-fill" style="width:${Math.max(2, dim.score)}%"></span></span>
          <span style="font-variant-numeric:tabular-nums">${esc(dim.score)}</span>
          <span class="dim-grade" style="color:${ringColor(dim.score)}">${esc(dim.grade)}</span>
        </div>`).join("")
        + ((evaluation.notes || []).length ? `<p class="muted" style="margin:0.5rem 0 0">${evaluation.notes.map(esc).join("<br>")}</p>` : "");
      salary.innerHTML = (payload.salary_context || []).map((line) => `<div>· ${esc(line)}</div>`).join("")
        || `<span class="muted">No local salary evidence.</span>`;
    } catch (error) {
      dims.innerHTML = `<span class="muted">Evaluation unavailable: ${esc(error.message)}</span>`;
      salary.innerHTML = "";
    }
  }

  async function renderStories(job) {
    const node = $("drawerStories");
    try {
      const payload = await window.api("/api/stories");
      const stories = payload.stories || [];
      if (!stories.length) {
        node.innerHTML = `<span class="muted">Story bank is empty — seed it from the Career Coach tab.</span>`;
        return;
      }
      const jobTokens = new Set(
        [job.title, ...(job.tech_stack || []), ...(job.ai_must_haves || [])]
          .join(" ").toLowerCase().split(/[^a-z0-9+#.]+/).filter((token) => token.length >= 3),
      );
      const scored = stories
        .map((story) => {
          const text = [story.title, ...(story.skills || []), story.action].join(" ").toLowerCase();
          let score = 0;
          jobTokens.forEach((token) => { if (text.includes(token)) score += 1; });
          return { story, score };
        })
        .sort((a, b) => b.score - a.score)
        .slice(0, 3);
      node.innerHTML = scored.map(({ story }) => `
        <div class="story-mini">
          <strong>${esc(story.title)}</strong>
          <span class="muted">${(story.skills || []).slice(0, 5).map(esc).join(" · ")}</span>
        </div>`).join("");
    } catch {
      node.innerHTML = `<span class="muted">Stories unavailable.</span>`;
    }
  }

  async function renderHistory(job) {
    const node = $("drawerHistory");
    node.innerHTML = `<span class="muted">Loading history…</span>`;
    try {
      const payload = await window.api(`/api/job-history?job_id=${encodeURIComponent(job.id)}`);
      const events = payload.events || [];
      node.innerHTML = events.length ? events.map((event) => `
        <div class="story-mini">
          <strong>${esc(String(event.event_type || "Event").replace(/_/g, " "))}</strong>
          <span class="muted">${esc(String(event.created_at || "").slice(0, 19))}</span>
        </div>`).join("") : `<span class="muted">No events recorded.</span>`;
    } catch (error) {
      node.innerHTML = `<span class="muted">History unavailable: ${esc(error.message)}</span>`;
    }
  }

  function renderNotes(job) {
    const node = $("drawerDescription");
    const notes = job.fit_notes || [];
    node.innerHTML = notes.length
      ? `<ul style="margin:0;padding-left:1.1rem">${notes.slice(0, 12).map((note) => `<li>${esc(note)}</li>`).join("")}</ul>`
      : `<span class="muted">No fit notes yet — score the job first.</span>`;
  }

  async function open(jobId) {
    if (!state.jobs.length) {
      try { await window.loadJobs(false); } catch { /* drawer still opens with what we have */ }
    }
    const job = findJob(jobId);
    if (!job) {
      window.toast("Job not found in the local tracker.");
      return;
    }
    currentJob = job;
    renderHead(job);
    renderActions(job);
    renderAi(job);
    renderNotes(job);
    $("drawerGrade").innerHTML = "";
    $("drawerOverlay").classList.remove("hidden");
    $("jobDrawer").classList.remove("hidden");
    renderEvaluation(job);
    renderStories(job);
    renderHistory(job);
    $("drawerCloseBtn").focus();
  }

  function close() {
    $("drawerOverlay").classList.add("hidden");
    $("jobDrawer").classList.add("hidden");
    currentJob = null;
  }

  async function runAction(action, button) {
    if (!currentJob) return;
    const job = currentJob;
    switch (action) {
      case "packet": return window.generatePacket(job.id, button);
      case "cover-letter": return window.generateCoverLetter(job.id, button);
      case "preflight": { close(); window.activateTab("jobs"); return window.runPreflight(job.id, button); }
      case "ai-fit": return window.JobAgentAi && window.JobAgentAi.analyze(job.id, button);
      case "chat": { close(); return window.JobAgentAi && window.JobAgentAi.openChat(job); }
      case "brain": { close(); return window.JobAgentBrain && window.JobAgentBrain.openJob(job.id); }
      case "delete": { close(); return window.deleteJob(job.id, button); }
      default: return undefined;
    }
  }

  function bind() {
    if (!$("jobDrawer")) return;
    $("drawerCloseBtn").addEventListener("click", close);
    $("drawerOverlay").addEventListener("click", close);
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !$("jobDrawer").classList.contains("hidden")) close();
    });
    $("drawerActions").addEventListener("click", (event) => {
      const button = event.target.closest("[data-drawer-action]");
      if (button) runAction(button.dataset.drawerAction, button);
    });
    // Open from the Jobs table: click on row text (not its buttons/links/inputs).
    const jobsTab = document.getElementById("tab-jobs");
    if (jobsTab) {
      jobsTab.addEventListener("click", (event) => {
        if (event.target.closest("button, a, input, select, textarea, label")) return;
        const row = event.target.closest("tbody tr");
        if (!row) return;
        const jobId = row.querySelector("[data-job]")?.dataset.job;
        if (jobId) open(jobId);
      });
    }
  }

  bind();
  window.JobDrawer = { open, close };
})();
