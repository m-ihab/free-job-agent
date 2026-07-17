/* Urgency + fit shortlist renderer for the Overview tab. */
(function () {
  "use strict";
  const esc = (value) => window.escapeHtml(String(value ?? ""));

  function shortlistRank(item) {
    return Number(item.priority || 0) + Number(item.fit_score || 0);
  }

  function scoreBadge(label, score) {
    if (score === null || score === undefined) return "";
    return `<span class="ov-score-badge"><span>${esc(label)}</span><strong>${esc(Math.round(score))}</strong></span>`;
  }

  function render(items, jobs) {
    const node = document.getElementById("ovShortlist");
    if (!node) return;
    const byId = new Map(jobs.map((job) => [String(job.id), job]));
    const ranked = items
      .filter((item) => !["Wait", "No action"].includes(item.action) && byId.has(String(item.job_id)))
      .sort((a, b) => shortlistRank(b) - shortlistRank(a) || Number(b.fit_score || 0) - Number(a.fit_score || 0))
      .slice(0, 5);
    if (!ranked.length) {
      node.innerHTML = '<div class="empty-state"><span class="empty-glyph">-</span><strong>No actionable jobs right now</strong><span>Run a hunt or score tracked jobs. This list stays empty until a real next action exists.</span></div>';
      return;
    }
    node.innerHTML = ranked.map((item) => {
      const job = byId.get(String(item.job_id));
      return `<li class="ov-row ov-shortlist-row" data-job="${esc(item.job_id)}" role="button" tabindex="0">
        <span class="ov-score-badges">${scoreBadge("Fit", item.fit_score)}${scoreBadge("Signal", job.search_quality_score)}</span>
        <span class="ov-row-main"><span class="ov-row-title">${esc(item.title)}</span><span class="ov-row-sub">${esc(item.company)}</span></span>
        <span class="ov-next-action">${esc(item.action)}</span>
      </li>`;
    }).join("");
  }

  window.JobAgentOverviewShortlist = { render };
})();
