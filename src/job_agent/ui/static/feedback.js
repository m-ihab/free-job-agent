/* Local thumbs feedback controls for tracked-job rows. */
(function () {
  "use strict";

  const esc = (value) => window.escapeHtml(value);

  const style = document.createElement("style");
  style.textContent = `
    .feedback-controls{display:inline-flex;gap:3px;margin-top:5px}
    .feedback-btn{min-width:28px;padding:2px 6px;font-size:.78rem;line-height:1.3}
    .feedback-btn[aria-pressed="true"]{border-color:var(--accent,#7aa2ff);background:var(--accent-soft,#27345a)}
    .feedback-delta{display:block;margin-top:3px;color:var(--muted,#9aa1ad);font-size:.72rem}
  `;
  document.head.appendChild(style);

  function controls(job) {
    const verdict = job.feedback_verdict || "";
    const delta = Number(job.feedback_adjustment || 0);
    const deltaLabel = delta
      ? `<span class="feedback-delta">feedback ${delta > 0 ? "+" : ""}${delta}</span>`
      : "";
    return `<span class="feedback-controls" aria-label="Rate this job">
      <button class="feedback-btn" data-feedback="up" data-job="${esc(job.id)}" aria-pressed="${verdict === "up"}" title="Thumbs up">👍</button>
      <button class="feedback-btn" data-feedback="down" data-job="${esc(job.id)}" aria-pressed="${verdict === "down"}" title="Thumbs down">👎</button>
    </span>${deltaLabel}`;
  }

  async function rate(button) {
    const verdict = button.dataset.feedback;
    const jobId = button.dataset.job;
    window.setBusy(button, true);
    try {
      await window.api("/api/feedback", { job_id: jobId, verdict });
      window.toast(`Saved thumbs ${verdict}. Future score ranking updated.`);
      await window.loadJobs();
    } catch (error) {
      window.toast(`Feedback failed: ${error.message}`);
    } finally {
      window.setBusy(button, false);
    }
  }

  document.addEventListener("click", (event) => {
    const button = event.target.closest?.("[data-feedback]");
    if (!button) return;
    event.preventDefault();
    event.stopPropagation();
    rate(button);
  });

  window.JobAgentFeedback = { controls };
})();
