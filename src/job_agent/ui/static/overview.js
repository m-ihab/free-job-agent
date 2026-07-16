/* Overview home tab — metric hero, today's queue, top matches, funnel,
   readiness checklist. Uses app.js globals (api, state, escapeHtml,
   activateTab, oneClickHunt, toast); loaded with defer so they exist.
   NOTE: `state` is a top-level const in app.js — reachable as a bare global
   identifier from classic scripts, but NOT as window.state. */
(function () {
  const $ = (id) => document.getElementById(id);
  const esc = (value) => window.escapeHtml(String(value ?? ""));

  function ringColor(score) {
    if (score === null || score === undefined) return "var(--muted)";
    if (score >= 85) return "var(--grade-a)";
    if (score >= 70) return "var(--grade-b)";
    if (score >= 55) return "var(--grade-c)";
    if (score >= 40) return "var(--grade-d)";
    return "var(--grade-f)";
  }

  function ring(score, size = "") {
    const value = score === null || score === undefined ? 0 : Math.round(score);
    const label = score === null || score === undefined ? "–" : String(value);
    return `<span class="score-ring ${size}" style="--ring-value:${value};--ring-color:${ringColor(score)}">${label}</span>`;
  }

  function heroStat(num, label) {
    return `<div class="ov-card ov-stat"><span class="ov-num">${esc(num)}</span><span class="ov-label">${esc(label)}</span></div>`;
  }

  function emptyState(glyph, title, hint) {
    return `<div class="empty-state"><span class="empty-glyph">${glyph}</span><strong>${esc(title)}</strong>${esc(hint)}</div>`;
  }

  function openJob(jobId) {
    if (window.JobDrawer && typeof window.JobDrawer.open === "function") {
      window.JobDrawer.open(jobId);
    } else {
      window.activateTab("jobs");
    }
  }

  function renderQueue(items) {
    const node = $("ovQueue");
    if (!node) return;
    $("ovQueueCount").textContent = items.length ? `· ${items.length} actions` : "";
    if (!items.length) {
      node.innerHTML = emptyState("✦", "Queue is clear", "Run a hunt or start Autopilot to fill today's queue.");
      return;
    }
    node.innerHTML = items.map((item) => `
      <li class="ov-row" data-job="${esc(item.job_id)}" role="button" tabindex="0">
        ${ring(item.fit_score, "ring-sm")}
        <span class="ov-row-main">
          <span class="ov-row-title">${esc(item.action)}</span>
          <span class="ov-row-sub">${esc(item.title)} · ${esc(item.company)} — ${esc(item.reason)}</span>
        </span>
        <span class="row-tag">${esc(item.stage || "")}</span>
      </li>`).join("");
  }

  function renderMatches(jobs) {
    const node = $("ovMatches");
    if (!node) return;
    const ranked = jobs
      .filter((job) => job.fit_score !== null && job.fit_score !== undefined)
      .sort((a, b) => (b.fit_score || 0) - (a.fit_score || 0))
      .slice(0, 5);
    if (!ranked.length) {
      node.innerHTML = emptyState("◎", "No scored matches yet", "Add or hunt jobs — scoring runs automatically.");
      return;
    }
    node.innerHTML = ranked.map((job) => `
      <li class="ov-row" data-job="${esc(job.id)}" role="button" tabindex="0">
        ${ring(job.fit_score, "ring-sm")}
        <span class="ov-row-main">
          <span class="ov-row-title">${esc(job.title)}</span>
          <span class="ov-row-sub">${esc(job.company)}${job.location ? " · " + esc(job.location) : ""}</span>
        </span>
        <span class="row-tag">${esc(job.status || "")}</span>
      </li>`).join("");
  }

  function renderFunnel(funnel) {
    const node = $("ovFunnel");
    if (!node) return;
    const max = Math.max(1, ...funnel.map((row) => row.count));
    node.innerHTML = funnel.map((row) => `
      <div class="ov-funnel-row">
        <span class="muted">${esc(row.label)}</span>
        <span class="ov-funnel-bar"><span class="ov-funnel-fill" style="width:${Math.round((row.count / max) * 100)}%"></span></span>
        <strong style="font-variant-numeric:tabular-nums">${esc(row.count)}</strong>
      </div>`).join("");
  }

  function checkItem(done, label, cta, tab) {
    const button = done ? "" : `<button class="ghost check-cta" data-goto="${esc(tab)}">${esc(cta)}</button>`;
    return `<div class="ov-check ${done ? "done" : ""}">
      <span class="check-dot">${done ? "✓" : "·"}</span>
      <span>${esc(label)}</span>${button}
    </div>`;
  }

  function renderChecklist(profile, jobCount, submitted) {
    const node = $("ovChecklist");
    if (!node) return;
    node.innerHTML = [
      checkItem(Boolean(profile.valid), "Profile files validated", "Fix profile", "profile"),
      checkItem(Boolean(profile.france_travail_configured), "France Travail API connected", "Set up", "profile"),
      checkItem(Boolean(profile.ollama_ready), "Local AI (Ollama) running", "AI setup", "autopilot"),
      checkItem(Boolean(profile.latex_ready), "LaTeX CV compiler installed", "Details", "profile"),
      checkItem(jobCount > 0, "First jobs tracked", "Run a hunt", "search"),
      checkItem(submitted > 0, "First application submitted", "Open pipeline", "pipeline"),
    ].join("");
  }

  async function loadOverview() {
    try {
      if (!state.profile) await window.loadState();
      if (!state.jobs.length) await window.loadJobs(false);
      const [metrics, today] = await Promise.all([
        window.api("/api/metrics"),
        window.api("/api/pipeline/today?limit=6"),
      ]);
      const jobs = state.jobs || [];
      const kpis = metrics.kpis || {};
      $("ovHero").innerHTML = [
        heroStat(kpis.tracked ?? jobs.length, "Tracked jobs"),
        heroStat(kpis.scored ?? 0, "Scored"),
        heroStat(kpis.packets ?? 0, "Packet ready"),
        heroStat(kpis.applied ?? 0, "Applied"),
        heroStat(`${kpis.response_rate ?? 0}%`, "Response rate"),
        heroStat(kpis.interviews ?? 0, "Interviews"),
      ].join("");
      renderQueue(today.items || today.queue || []);
      renderMatches(jobs);
      renderFunnel(metrics.funnel || []);
      renderChecklist(state.profile || {}, jobs.length, kpis.applied || 0);
    } catch (error) {
      const node = $("ovHero");
      if (node) node.innerHTML = `<div class="notice error">Overview failed to load: ${esc(error.message)}</div>`;
    }
  }

  function bind() {
    const grid = document.getElementById("tab-overview");
    if (!grid) return;
    grid.addEventListener("click", (event) => {
      const goto = event.target.closest("[data-goto]");
      if (goto) {
        window.activateTab(goto.dataset.goto);
        return;
      }
      const row = event.target.closest(".ov-row[data-job]");
      if (row) openJob(row.dataset.job);
    });
    grid.addEventListener("keydown", (event) => {
      if (event.key !== "Enter") return;
      const row = event.target.closest(".ov-row[data-job]");
      if (row) openJob(row.dataset.job);
    });
    const hunt = $("ovHuntBtn");
    if (hunt) hunt.addEventListener("click", () => window.oneClickHunt());
    const refresh = $("ovRefreshBtn");
    if (refresh) refresh.addEventListener("click", loadOverview);

    // Re-load the overview whenever its tab is activated.
    const original = window.activateTab;
    window.activateTab = function patchedActivateTab(name) {
      original(name);
      if (name === "overview") loadOverview();
    };
  }

  bind();
  loadOverview();
  window.JobAgentOverview = { load: loadOverview };
})();
