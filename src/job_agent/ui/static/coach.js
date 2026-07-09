// Career Coach (R3 split from app.js). Classic script, defer, after app.js.
// runRecruiterAudit / runSkillSuggestions stay in app.js (shared AI tools);
// their coach-panel buttons bind here through window.* lookups.
(function () {
  const api = (...args) => window.api(...args);
  const setNotice = (...args) => window.setNotice(...args);
  const setBusy = (...args) => window.setBusy(...args);
  const escapeHtml = (value) => window.escapeHtml(value);
  const metric = (...args) => window.metric(...args);
  const safeHref = (value) => window.safeHref(value);
  const runRecruiterAudit = (...args) => window.runRecruiterAudit(...args);
  const runSkillSuggestions = (...args) => window.runSkillSuggestions(...args);

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
            <span class="coach-title">${cert.url ? `<a href="${safeHref(cert.url)}" target="_blank" rel="noreferrer">${escapeHtml(cert.name)}</a>` : escapeHtml(cert.name)}</span>
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


  // ---- event bindings (moved from bindEvents) ----
  // Career Coach
  const coachBtn = document.getElementById("coachRefreshBtn");
  if (coachBtn) coachBtn.addEventListener("click", generateCoachPlan);
  const coachAuditBtn = document.getElementById("coachAuditBtn");
  if (coachAuditBtn) coachAuditBtn.addEventListener("click", runRecruiterAudit);
  const coachSkillsBtn = document.getElementById("coachSkillsBtn");
  if (coachSkillsBtn) coachSkillsBtn.addEventListener("click", runSkillSuggestions);


  window.JobAgentCoach = {
    renderShell: renderCoachShell,
  };
})();
