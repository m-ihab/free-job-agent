// Insights charts (R3 split from app.js). Classic script, defer, after
// app.js — pipeline.js idiom. Chart.js is loaded as a vendor script;
// state.charts / state.insightsCache stay on the shared app.js state.
(function () {
  function $(id) { return document.getElementById(id); }
  const api = (...args) => window.api(...args);
  const toast = (...args) => window.toast(...args);
  const metric = (...args) => window.metric(...args);
  const escapeHtml = (value) => window.escapeHtml(value);

async function loadInsights() {
  try {
    const payload = await api("/api/stats");
    state.insightsCache = payload;
    renderInsights(payload);
  } catch (error) {
    toast(`Insights error: ${error.message}`);
  }
}

function readVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#888";
}

function destroyChart(key) {
  const existing = state.charts[key];
  if (existing && typeof existing.destroy === "function") existing.destroy();
  state.charts[key] = null;
}

function renderFunnelChart(funnel) {
  if (typeof Chart === "undefined") return;
  destroyChart("funnel");
  const ctx = document.getElementById("funnelChart");
  if (!ctx) return;
  const labels = funnel.map((row) => row.label);
  const values = funnel.map((row) => row.count);
  state.charts.funnel = new Chart(ctx, {
    type: "bar",
    data: {
      labels,
      datasets: [{
        label: "Jobs",
        data: values,
        backgroundColor: labels.map((_, i) => `rgba(${i % 2 ? "28,63,114" : "11,139,127"}, 0.85)`),
        borderRadius: 6,
        borderSkipped: false,
      }],
    },
    options: {
      indexAxis: "y",
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { beginAtZero: true, grid: { color: readVar("--line") }, ticks: { color: readVar("--muted") } },
        y: { grid: { display: false }, ticks: { color: readVar("--ink") } },
      },
    },
  });
}

function renderWeeklyChart(weeks) {
  if (typeof Chart === "undefined") return;
  destroyChart("weekly");
  const ctx = document.getElementById("weeklyChart");
  if (!ctx) return;
  const labels = weeks.map((row) => row.week.replace(/^\d{4}-/, ""));
  const added = weeks.map((row) => row.added);
  const applied = weeks.map((row) => row.applied);
  state.charts.weekly = new Chart(ctx, {
    type: "bar",
    data: {
      labels,
      datasets: [
        { label: "Added", data: added, backgroundColor: "rgba(28,63,114,0.75)", borderRadius: 4 },
        { label: "Applied", data: applied, backgroundColor: "rgba(11,139,127,0.85)", borderRadius: 4 },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { labels: { color: readVar("--muted") } } },
      scales: {
        x: { grid: { display: false }, ticks: { color: readVar("--muted") } },
        y: { beginAtZero: true, grid: { color: readVar("--line") }, ticks: { color: readVar("--muted") } },
      },
    },
  });
}

function renderPipelineChart(funnel) {
  if (typeof Chart === "undefined") return;
  destroyChart("pipeline");
  const ctx = document.getElementById("pipelineChart");
  if (!ctx) return;
  if (!funnel || !funnel.length) return;
  const labels = funnel.map((row) => row.label);
  const values = funnel.map((row) => row.count);
  const conversions = values.map((value, idx) => {
    if (idx === 0 || !values[idx - 1]) return "100%";
    return `${Math.round((value / values[idx - 1]) * 100)}%`;
  });
  state.charts.pipeline = new Chart(ctx, {
    type: "bar",
    data: {
      labels,
      datasets: [{
        label: "Jobs",
        data: values,
        backgroundColor: labels.map((_, i) => {
          const ratio = i / Math.max(1, labels.length - 1);
          return `rgba(${Math.round(11 + (28 - 11) * ratio)}, ${Math.round(139 - (139 - 63) * ratio)}, ${Math.round(127 - (127 - 114) * ratio)}, 0.85)`;
        }),
        borderRadius: 8,
        borderSkipped: false,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (item) => `${item.raw} jobs · ${conversions[item.dataIndex]} of previous`,
          },
        },
      },
      scales: {
        x: { grid: { display: false }, ticks: { color: readVar("--muted") } },
        y: { beginAtZero: true, grid: { color: readVar("--line") }, ticks: { color: readVar("--muted") } },
      },
    },
  });
}

function renderScoreChart(buckets) {
  if (typeof Chart === "undefined") return;
  destroyChart("score");
  const ctx = document.getElementById("scoreChart");
  if (!ctx) return;
  const labels = Object.keys(buckets);
  const values = Object.values(buckets);
  state.charts.score = new Chart(ctx, {
    type: "doughnut",
    data: {
      labels,
      datasets: [{
        data: values,
        backgroundColor: [
          "rgba(192,57,43,0.85)",
          "rgba(244,184,96,0.85)",
          "rgba(11,139,127,0.85)",
          "rgba(28,63,114,0.85)",
        ],
        borderColor: readVar("--surface"),
        borderWidth: 2,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { position: "bottom", labels: { color: readVar("--muted") } } },
    },
  });
}

function renderInsights(stats) {
  const total = stats.total || 0;
  const submitted = stats.submitted_count || 0;
  const interviews = stats.interview_count || 0;
  $("insightsMetrics").innerHTML = [
    metric("Total tracked", total),
    metric("Submitted", submitted),
    metric("Interviews+", interviews),
    metric("Response rate", `${stats.response_rate ?? 0}%`, `avg score ${stats.avg_score ?? "—"}`),
  ].join("");

  renderFunnelChart(stats.funnel || []);
  renderWeeklyChart(stats.weekly || []);
  renderScoreChart(stats.score_buckets || {});
  renderPipelineChart(stats.funnel || []);

  $("topCompaniesView").innerHTML = (stats.top_companies || [])
    .map((row) => `<li><span>${escapeHtml(row.name)}</span><strong>${row.count}</strong></li>`)
    .join("") || "<li class='muted'>No data yet.</li>";
  $("topSourcesView").innerHTML = (stats.top_sources || [])
    .map((row) => `<li><span>${escapeHtml(row.name)}</span><strong>${row.count}</strong></li>`)
    .join("") || "<li class='muted'>No data yet.</li>";
  $("topLocationsView").innerHTML = (stats.top_locations || [])
    .map((row) => `<li><span>${escapeHtml(row.name)}</span><strong>${row.count}</strong></li>`)
    .join("") || "<li class='muted'>No data yet.</li>";
}


  // ---- event bindings (moved from bindEvents) ----
  $("insightsRefreshBtn").addEventListener("click", loadInsights);

  window.JobAgentInsights = {
    load: loadInsights,
    render: renderInsights,
  };
})();
