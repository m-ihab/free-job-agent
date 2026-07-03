/* Command palette (Ctrl/Cmd+K) — fuzzy jump to tabs, actions, and tracked
   jobs. Uses app.js globals; loaded with defer. `state` is app.js's top-level
   const, reachable as a bare global identifier (not window.state). */
(function () {
  const $ = (id) => document.getElementById(id);
  const esc = (value) => window.escapeHtml(String(value ?? ""));

  const TAB_LABELS = {
    overview: "Overview", search: "Search", jobs: "Jobs", pipeline: "Pipeline",
    tracker: "Tracker", autopilot: "Autopilot", studio: "CV Studio",
    portfolio: "Portfolio", coach: "Career Coach", insights: "Insights",
    add: "Add Job", profile: "Profile & API",
  };

  function staticCommands() {
    const commands = Object.entries(TAB_LABELS).map(([tab, label]) => ({
      kind: "tab", label: `Go to ${label}`, keywords: `${label} ${tab}`,
      run: () => window.activateTab(tab),
    }));
    commands.push(
      { kind: "action", label: "1-click hunt (France Travail + boards)", keywords: "hunt search france", run: () => window.oneClickHunt() },
      { kind: "action", label: "Multi-source search", keywords: "remotive remoteok search multi", run: () => { window.activateTab("search"); window.runMultiSearch(); } },
      { kind: "action", label: "Discover company career boards", keywords: "ats greenhouse lever slug discover boards", run: () => { window.activateTab("search"); document.getElementById("discoverBoardsPanel")?.scrollIntoView({ block: "start" }); } },
      { kind: "action", label: "Export tracked jobs to CSV", keywords: "export csv download", run: () => { window.location.href = "/api/export-csv"; } },
      { kind: "action", label: "Toggle theme (dark / light)", keywords: "theme dark light mode", run: () => window.toggleTheme() },
      { kind: "action", label: "Seed story bank from CV", keywords: "star stories interview seed", run: () => { window.activateTab("coach"); window.JobAgentFeatures?.syncStories(); } },
      { kind: "action", label: "Keyboard shortcuts help", keywords: "help keys shortcuts", run: () => window.toggleShortcuts(true) },
    );
    return commands;
  }

  function jobCommands() {
    return (state.jobs || []).map((job) => ({
      kind: "job",
      label: `${job.title} — ${job.company}`,
      keywords: `${job.title} ${job.company} ${job.location || ""}`,
      run: () => {
        if (window.JobDrawer) window.JobDrawer.open(job.id);
        else window.activateTab("jobs");
      },
    }));
  }

  /* Subsequence fuzzy score: all query chars must appear in order; earlier +
     denser matches score higher. */
  function fuzzyScore(query, text) {
    const q = query.toLowerCase();
    const t = text.toLowerCase();
    if (!q) return 1;
    let score = 0;
    let index = 0;
    for (const ch of q) {
      const found = t.indexOf(ch, index);
      if (found === -1) return 0;
      score += 10 - Math.min(9, found - index);
      index = found + 1;
    }
    if (t.startsWith(q)) score += 40;
    if (t.includes(q)) score += 20;
    return score;
  }

  let items = [];
  let selected = 0;

  function render() {
    const list = $("cmdkList");
    if (!items.length) {
      list.innerHTML = `<li class="cmdk-empty">No matches — try fewer letters.</li>`;
      return;
    }
    list.innerHTML = items.map((item, index) => `
      <li class="cmdk-item ${index === selected ? "selected" : ""}" data-index="${index}" role="option" aria-selected="${index === selected}">
        <span>${esc(item.label)}</span>
        <span class="cmdk-kind">${esc(item.kind)}</span>
      </li>`).join("");
    const active = list.querySelector(".cmdk-item.selected");
    if (active) active.scrollIntoView({ block: "nearest" });
  }

  function filter() {
    const query = $("cmdkInput").value.trim();
    const pool = [...staticCommands(), ...jobCommands()];
    items = pool
      .map((item) => ({ item, score: Math.max(fuzzyScore(query, item.label), fuzzyScore(query, item.keywords)) }))
      .filter(({ score }) => score > 0)
      .sort((a, b) => b.score - a.score)
      .slice(0, 12)
      .map(({ item }) => item);
    selected = 0;
    render();
  }

  function open() {
    $("cmdkOverlay").classList.remove("hidden");
    $("cmdkInput").value = "";
    filter();
    $("cmdkInput").focus();
  }

  function close() {
    $("cmdkOverlay").classList.add("hidden");
  }

  function isOpen() {
    return !$("cmdkOverlay").classList.contains("hidden");
  }

  function runSelected() {
    const item = items[selected];
    if (!item) return;
    close();
    try {
      item.run();
    } catch (error) {
      window.toast(`Command failed: ${error.message}`);
    }
  }

  function bind() {
    if (!$("cmdkOverlay")) return;
    $("cmdkOpenBtn")?.addEventListener("click", open);
    $("cmdkInput").addEventListener("input", filter);
    $("cmdkOverlay").addEventListener("click", (event) => {
      if (event.target === $("cmdkOverlay")) close();
      const row = event.target.closest(".cmdk-item[data-index]");
      if (row) {
        selected = Number(row.dataset.index);
        runSelected();
      }
    });
    document.addEventListener("keydown", (event) => {
      const modifier = event.ctrlKey || event.metaKey;
      if (modifier && event.key.toLowerCase() === "k") {
        event.preventDefault();
        if (isOpen()) close(); else open();
        return;
      }
      if (!isOpen()) return;
      if (event.key === "Escape") { event.preventDefault(); close(); }
      if (event.key === "ArrowDown") { event.preventDefault(); selected = Math.min(items.length - 1, selected + 1); render(); }
      if (event.key === "ArrowUp") { event.preventDefault(); selected = Math.max(0, selected - 1); render(); }
      if (event.key === "Enter") { event.preventDefault(); runSelected(); }
    });
  }

  bind();
  window.JobAgentPalette = { open, close };
})();
