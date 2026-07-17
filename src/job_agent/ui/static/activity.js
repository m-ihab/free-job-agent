/* Tracker activity stream from the real cross-job event log. */
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const esc = (value) => window.escapeHtml(String(value ?? ""));
  let activityItems = [];
  let activeSubsystem = "";

  function timestamp(value) {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? String(value || "") : date.toLocaleString();
  }

  function render(items) {
    const node = $("trackerActivity");
    if (!node) return;
    if (!items.length) {
      node.innerHTML = '<li class="empty-state"><strong>No recorded activity</strong><span>Real tracker events will appear here as work happens.</span></li>';
      return;
    }
    node.innerHTML = items.map((item) => `<li class="activity-row">
      <time datetime="${esc(item.created_at)}">${esc(timestamp(item.created_at))}</time>
      <span class="activity-tag ${esc(item.subsystem)}">${esc(item.subsystem)}</span>
      <span>${esc(item.message)}</span>
    </li>`).join("");
  }

  function syncFilters() {
    $("activityFilters")?.querySelectorAll("[data-subsystem]").forEach((button) => {
      const active = button.dataset.subsystem === activeSubsystem;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
  }

  async function load(subsystem = activeSubsystem) {
    activeSubsystem = subsystem;
    syncFilters();
    const query = subsystem ? `?subsystem=${encodeURIComponent(subsystem)}` : "";
    try {
      const payload = await window.api(`/api/activity${query}`);
      activityItems = payload.events || [];
      render(activityItems);
    } catch (error) {
      $("trackerActivity").innerHTML = `<li class="notice error">Activity could not load: ${esc(error.message)}</li>`;
    }
  }

  async function copyExport() {
    if (!activityItems.length) {
      window.toast("No activity to copy.");
      return;
    }
    const text = activityItems.map((item) => `${timestamp(item.created_at)} [${item.subsystem}] ${item.message}`).join("\n");
    await navigator.clipboard.writeText(text);
    window.toast(`Copied ${activityItems.length} activity event(s).`);
  }

  $("activityFilters")?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-subsystem]");
    if (button) load(button.dataset.subsystem || "");
  });
  $("activityCopyBtn")?.addEventListener("click", copyExport);

  window.JobAgentActivity = { load };
})();
