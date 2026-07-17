(function () {
  function $(id) { return document.getElementById(id); }
  const api = (...args) => window.api(...args);
  const escapeHtml = (value) => window.escapeHtml(value);
  const toast = (message) => window.toast(message);

  function noteBtn(jobId) {
    return `<button class="ghost" data-pipeline-note="${escapeHtml(jobId)}" title="Open this job in the notes editor">📝</button>`;
  }

  function row(item) {
    return `<div class="pipeline-row" role="button" tabindex="0" data-pipeline-job="${escapeHtml(item.job_id)}" title="Open job details and act on it">
      <span><strong>${escapeHtml(item.action)}</strong><small>${escapeHtml(item.title)} · ${escapeHtml(item.company)}</small></span>
      <span>${escapeHtml(item.stage)} ${item.fit_score === null || item.fit_score === undefined ? "" : `· ${Math.round(item.fit_score)}`}</span>
      <em>${escapeHtml(item.reason)}</em>
      ${noteBtn(item.job_id)}
    </div>`;
  }

  function staleRow(item) {
    return `<div class="pipeline-row warn" role="button" tabindex="0" data-pipeline-job="${escapeHtml(item.job_id)}" title="Open job details and act on it">
      <span><strong>${escapeHtml(item.next_action)}</strong><small>${escapeHtml(item.title)} · ${escapeHtml(item.company)}</small></span>
      <span>${escapeHtml(item.status)} · ${item.days_idle}d</span>
      ${noteBtn(item.job_id)}
    </div>`;
  }

  function followupRow(item) {
    return `<div class="pipeline-row compact-row">
      <span><strong>${escapeHtml(item.kind)}</strong><small>${escapeHtml(item.title)} &middot; ${escapeHtml(item.company)}</small></span>
      <span>${escapeHtml(item.days_overdue)}d overdue</span>
      <button class="ghost" data-followup-done="${escapeHtml(item.task_id)}">Done</button>
    </div>`;
  }

  function signalRow(item) {
    return `<div class="pipeline-row compact-row">
      <span><strong>${escapeHtml(item.label)}</strong><small>${escapeHtml(item.submitted)} submitted &middot; ${escapeHtml(item.interviews)} interview(s)</small></span>
      <span>${Math.round((item.conversion_rate || 0) * 100)}%</span>
    </div>`;
  }

  function contactRow(item) {
    return `<div class="pipeline-row compact-row">
      <span><strong>${escapeHtml(item.name)}</strong><small>${escapeHtml([item.company, item.role, item.relationship].filter(Boolean).join(" · "))}</small></span>
      <span>${escapeHtml(item.source || "manual")}</span>
    </div>`;
  }

  function referralRow(item) {
    const contact = item.contact || {};
    return `<button class="pipeline-row compact-row" data-referral-contact="${escapeHtml(contact.id)}">
      <span><strong>${escapeHtml(contact.name || "Contact")}</strong><small>${escapeHtml([contact.company, contact.role].filter(Boolean).join(" · "))}</small></span>
      <span>${escapeHtml(item.score || 0)} pts</span>
      <em>${escapeHtml((item.reasons || []).join(", "))}</em>
    </button>`;
  }

  function metric(label, value) {
    return `<div class="metric"><strong>${escapeHtml(value)}</strong><span>${escapeHtml(label)}</span></div>`;
  }

  function setNotice(message, isError = false) {
    const node = $("pipelineNotice");
    if (!node) return;
    node.textContent = message || "";
    node.classList.toggle("hidden", !message);
    node.classList.toggle("error", isError);
  }

  async function load() {
    try {
      return await loadPipeline();
    } catch (error) {
      if (error instanceof TypeError) {
        window.renderConnectionLost("pipelineNotice", load);
        return;
      }
      throw error;
    }
  }

  async function loadPipeline() {
    const [today, stale, metrics, followups, learning] = await Promise.all([
      api("/api/pipeline/today?limit=8"),
      api("/api/pipeline/stale"),
      api("/api/pipeline/metrics"),
      api("/api/pipeline/followups"),
      api("/api/pipeline/learning"),
    ]);
    const metricNode = $("pipelineMetrics");
    if (metricNode) {
      metricNode.innerHTML = [
        metric("Tracked", metrics.total || 0),
        metric("Submitted", metrics.submitted || 0),
        metric("Reply rate", `${Math.round((metrics.reply_rate || 0) * 100)}%`),
        metric("Interview rate", `${Math.round((metrics.interview_rate || 0) * 100)}%`),
        metric("Offer rate", `${Math.round((metrics.offer_rate || 0) * 100)}%`),
      ].join("");
    }
    const todayNode = $("pipelineToday");
    if (todayNode) {
      todayNode.innerHTML = (today.items || []).length
        ? (today.items || []).map(row).join("")
        : `<p class="muted">No immediate actions. Nice, rare little dashboard silence.</p>`;
    }
    const staleNode = $("pipelineStale");
    if (staleNode) {
      staleNode.innerHTML = (stale.jobs || []).length
        ? (stale.jobs || []).map(staleRow).join("")
        : `<p class="muted">No stale jobs.</p>`;
    }
    const followupsNode = $("pipelineFollowups");
    if (followupsNode) {
      followupsNode.innerHTML = (followups.items || []).length
        ? (followups.items || []).map(followupRow).join("")
        : `<p class="muted">No follow-ups due.</p>`;
    }
    const learningNode = $("pipelineLearning");
    if (learningNode) {
      const signals = [...(learning.sources || []).slice(0, 4), ...(learning.skills || []).slice(0, 4)];
      learningNode.innerHTML = signals.length
        ? signals.map(signalRow).join("")
        : `<p class="muted">No conversion signals yet. Submit and update outcomes to teach the queue.</p>`;
    }
    await loadContacts(false);
  }

  async function loadNotes() {
    const jobId = ($("pipelineNotesJobId")?.value || "").trim();
    if (!jobId) return setNotice("Paste a job id first.", true);
    try {
      const data = await api(`/api/job-notes?job_id=${encodeURIComponent(jobId)}`);
      const box = $("pipelineNotesText");
      if (box) box.value = data.notes || "";
      setNotice("Notes loaded.");
    } catch (error) {
      setNotice(error.message, true);
    }
  }

  async function saveNotes() {
    const jobId = ($("pipelineNotesJobId")?.value || "").trim();
    const notes = $("pipelineNotesText")?.value || "";
    if (!jobId) return setNotice("Paste a job id first.", true);
    try {
      await api("/api/job-notes", { job_id: jobId, notes });
      setNotice("Notes saved locally.");
      toast("Pipeline notes saved.");
    } catch (error) {
      setNotice(error.message, true);
    }
  }

  function parseContactLines() {
    const text = $("pipelineContactsText")?.value || "";
    return text.split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean)
      .map((line) => {
        const [name = "", company = "", role = "", relationship = "", notes = ""] = line.split("|").map((part) => part.trim());
        return { name, company, role, relationship, notes, source: "dashboard" };
      })
      .filter((item) => item.name);
  }

  async function importContacts() {
    const contacts = parseContactLines();
    if (!contacts.length) return setNotice("Paste at least one contact line first.", true);
    try {
      const data = await api("/api/contacts/import", { contacts });
      setNotice(`Imported ${data.imported || 0} contact(s).`);
      toast("Contacts imported locally.");
      await loadContacts(false);
    } catch (error) {
      setNotice(error.message, true);
    }
  }

  async function loadContacts(showNotice = true) {
    const node = $("pipelineContacts");
    if (!node) return;
    try {
      const data = await api("/api/contacts");
      node.innerHTML = (data.contacts || []).length
        ? (data.contacts || []).slice(0, 8).map(contactRow).join("")
        : `<p class="muted">No local contacts yet.</p>`;
      if (showNotice) setNotice("Contacts loaded.");
    } catch (error) {
      if (showNotice) setNotice(error.message, true);
    }
  }

  async function findReferrals() {
    const jobId = ($("pipelineNotesJobId")?.value || "").trim();
    const node = $("pipelineReferrals");
    if (!jobId) return setNotice("Click a queue item or paste a job id first.", true);
    if (!node) return;
    try {
      const data = await api(`/api/referrals?job_id=${encodeURIComponent(jobId)}`);
      node.innerHTML = (data.matches || []).length
        ? (data.matches || []).map(referralRow).join("")
        : `<p class="muted">No warm paths yet. Import contacts, then try again.</p>`;
      setNotice("Warm paths refreshed.");
    } catch (error) {
      setNotice(error.message, true);
    }
  }

  async function draftReferral(contactId) {
    const jobId = ($("pipelineNotesJobId")?.value || "").trim();
    if (!jobId || !contactId) return;
    try {
      const data = await api("/api/referral-ask", { job_id: jobId, contact_id: contactId });
      const box = $("pipelineReferralDraft");
      if (box) box.value = data.message || "";
      setNotice("Referral ask drafted.");
    } catch (error) {
      setNotice(error.message, true);
    }
  }

  document.addEventListener("click", (event) => {
    const followup = event.target.closest("[data-followup-done]");
    if (followup) {
      api("/api/pipeline/followup-done", { task_id: followup.dataset.followupDone })
        .then(() => load())
        .then(() => toast("Follow-up marked done."))
        .catch((error) => setNotice(error.message, true));
      return;
    }
    const referral = event.target.closest("[data-referral-contact]");
    if (referral) {
      draftReferral(referral.dataset.referralContact || "");
      return;
    }
    // A queue row's small 📝 button routes to the notes editor; clicking the
    // row itself opens the job drawer so the action can actually be taken.
    const note = event.target.closest("[data-pipeline-note]");
    if (note) {
      const input = $("pipelineNotesJobId");
      if (input) input.value = note.dataset.pipelineNote || "";
      loadNotes();
      return;
    }
    const item = event.target.closest("[data-pipeline-job]");
    if (!item) return;
    if (window.JobDrawer && typeof window.JobDrawer.open === "function") {
      window.JobDrawer.open(item.dataset.pipelineJob);
    } else {
      const input = $("pipelineNotesJobId");
      if (input) input.value = item.dataset.pipelineJob || "";
      loadNotes();
    }
  });

  document.addEventListener("DOMContentLoaded", () => {
    const refresh = $("pipelineRefreshBtn");
    const loadBtn = $("pipelineLoadNotesBtn");
    const saveBtn = $("pipelineSaveNotesBtn");
    const importContactsBtn = $("pipelineImportContactsBtn");
    const loadContactsBtn = $("pipelineLoadContactsBtn");
    const findReferralsBtn = $("pipelineFindReferralsBtn");
    if (refresh) refresh.addEventListener("click", () => load().catch((error) => setNotice(error.message, true)));
    if (loadBtn) loadBtn.addEventListener("click", loadNotes);
    if (saveBtn) saveBtn.addEventListener("click", saveNotes);
    if (importContactsBtn) importContactsBtn.addEventListener("click", importContacts);
    if (loadContactsBtn) loadContactsBtn.addEventListener("click", () => loadContacts(true));
    if (findReferralsBtn) findReferralsBtn.addEventListener("click", findReferrals);
  });

  window.JobAgentPipeline = { load };
})();
