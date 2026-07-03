/* Kanban board view for the Tracker tab — drag a card between funnel columns
   to update its status via /api/status. Uses app.js globals; `state` is
   app.js's top-level const (bare global, not window.state). */
(function () {
  const $ = (id) => document.getElementById(id);
  const esc = (value) => window.escapeHtml(String(value ?? ""));

  const COLUMNS = [
    { key: "discovered", label: "Discovered", target: "DISCOVERED", statuses: ["NEW", "DISCOVERED", "SCORED", "NEEDS_REVIEW"] },
    { key: "qualified", label: "Qualified", target: "QUALIFIED", statuses: ["QUALIFIED"] },
    { key: "packet", label: "Packet ready", target: "PACKET_READY", statuses: ["PACKET_READY", "APPLYING", "ASSISTED_APPLY_OPENED", "APPLY_ATTEMPTED", "OUTREACH_DRAFTED"] },
    { key: "manual", label: "Needs manual", target: "NEEDS_MANUAL", statuses: ["NEEDS_MANUAL"] },
    { key: "submitted", label: "Submitted", target: "MANUALLY_SUBMITTED", statuses: ["SUBMITTED", "MANUALLY_SUBMITTED", "APPLIED", "OUTREACH_SENT", "FOLLOWUP_DUE", "FOLLOWUP_SENT", "REPLIED"] },
    { key: "interview", label: "Interviewing", target: "INTERVIEWING", statuses: ["INTERVIEW", "INTERVIEWING"] },
    { key: "offer", label: "Offer", target: "OFFER", statuses: ["OFFER", "OFFERED", "ACCEPTED"] },
  ];

  function ringColor(score) {
    if (score === null || score === undefined) return "var(--muted)";
    if (score >= 85) return "var(--grade-a)";
    if (score >= 70) return "var(--grade-b)";
    if (score >= 55) return "var(--grade-c)";
    if (score >= 40) return "var(--grade-d)";
    return "var(--grade-f)";
  }

  function daysSince(iso) {
    if (!iso) return null;
    const then = new Date(iso).getTime();
    if (Number.isNaN(then)) return null;
    return Math.max(0, Math.round((Date.now() - then) / 86400000));
  }

  function card(job) {
    const score = job.fit_score === null || job.fit_score === undefined ? null : Math.round(job.fit_score);
    const idle = daysSince(job.updated_at);
    return `<div class="kb-card" draggable="true" data-job="${esc(job.id)}" title="Drag to change stage · click to open details">
      <span class="score-ring ring-sm" style="--ring-value:${score ?? 0};--ring-color:${ringColor(score)}">${score === null ? "–" : score}</span>
      <span class="kb-main">
        <span class="kb-title">${esc(job.title)}</span>
        <span class="kb-sub">${esc(job.company_display || job.company)}${idle !== null ? ` · ${idle}d` : ""}</span>
      </span>
    </div>`;
  }

  function render() {
    const board = $("trackerBoardWrap");
    if (!board || board.classList.contains("hidden")) return;
    const jobs = state.jobs || [];
    board.innerHTML = COLUMNS.map((column) => {
      const items = jobs.filter((job) => column.statuses.includes(job.status));
      return `<div class="kb-col" data-column="${esc(column.key)}" data-target="${esc(column.target)}">
        <div class="kb-col-head"><span>${esc(column.label)}</span><span class="kb-count">${items.length}</span></div>
        ${items.map(card).join("") || `<div class="empty-state" style="padding:1rem 0.4rem"><span class="muted">—</span></div>`}
      </div>`;
    }).join("");
  }

  async function moveJob(jobId, targetStatus) {
    try {
      await window.api("/api/status", { job_id: jobId, status: targetStatus, note: "Kanban move" });
      await window.loadJobs(false);
      window.renderTracker();
      render();
      window.toast(`Moved → ${targetStatus.replace(/_/g, " ")}`);
    } catch (error) {
      window.setNotice("trackerNotice", error.message, true);
      render();
    }
  }

  function setView(board) {
    $("trackerViewTable").classList.toggle("active", !board);
    $("trackerViewBoard").classList.toggle("active", board);
    $("trackerTableWrap").classList.toggle("hidden", board);
    $("trackerBoardWrap").classList.toggle("hidden", !board);
    try { localStorage.setItem("job-agent-tracker-view", board ? "board" : "table"); } catch { /* private mode */ }
    if (board) render();
  }

  function bind() {
    const board = $("trackerBoardWrap");
    if (!board) return;
    $("trackerViewTable").addEventListener("click", () => setView(false));
    $("trackerViewBoard").addEventListener("click", () => setView(true));

    let draggedId = null;
    board.addEventListener("dragstart", (event) => {
      const cardNode = event.target.closest(".kb-card");
      if (!cardNode) return;
      draggedId = cardNode.dataset.job;
      cardNode.classList.add("dragging");
      event.dataTransfer.effectAllowed = "move";
    });
    board.addEventListener("dragend", (event) => {
      event.target.closest(".kb-card")?.classList.remove("dragging");
      board.querySelectorAll(".kb-col.drag-over").forEach((col) => col.classList.remove("drag-over"));
    });
    board.addEventListener("dragover", (event) => {
      const column = event.target.closest(".kb-col");
      if (!column) return;
      event.preventDefault();
      board.querySelectorAll(".kb-col.drag-over").forEach((col) => col.classList.remove("drag-over"));
      column.classList.add("drag-over");
    });
    board.addEventListener("drop", (event) => {
      const column = event.target.closest(".kb-col");
      if (!column || !draggedId) return;
      event.preventDefault();
      column.classList.remove("drag-over");
      moveJob(draggedId, column.dataset.target);
      draggedId = null;
    });
    board.addEventListener("click", (event) => {
      if (event.target.closest(".kb-card")) {
        const jobId = event.target.closest(".kb-card").dataset.job;
        if (window.JobDrawer) window.JobDrawer.open(jobId);
      }
    });

    // Board re-renders whenever the tracker reloads.
    const originalRenderTracker = window.renderTracker;
    window.renderTracker = function patchedRenderTracker() {
      originalRenderTracker();
      render();
    };

    let preferred = "table";
    try { preferred = localStorage.getItem("job-agent-tracker-view") || "table"; } catch { /* private mode */ }
    if (preferred === "board") setView(true);
  }

  bind();
  window.JobAgentKanban = { render, setView };
})();
