// Interactive metrics dashboard. Chart.js is vendored and loaded before this file.
(function () {
  const $ = (id) => document.getElementById(id);
  const api = (...args) => window.api(...args);
  const esc = (value) => window.escapeHtml(String(value ?? ""));
  if (typeof Chart !== "undefined" && window.ChartZoom && !Chart.registry?.plugins?.items?.zoom) Chart.register(window.ChartZoom);
  function css(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }
  function colors() {
    return {
      ink: css("--ink"), muted: css("--muted"), line: css("--line"),
      surface: css("--surface-solid"), accent: css("--accent"),
      accent2: css("--accent-2"), soft: css("--accent-soft"),
      good: css("--good"), warn: css("--warn"), bad: css("--bad"),
    };
  }
  function tooltip(callbacks = {}) {
    const tone = colors();
    return {
      enabled: true,
      backgroundColor: tone.surface,
      titleColor: tone.ink,
      bodyColor: tone.muted,
      borderColor: tone.line,
      borderWidth: 1,
      padding: 11,
      callbacks,
    };
  }
  function axes() {
    const tone = colors();
    return {
      x: { grid: { color: tone.line }, ticks: { color: tone.muted } },
      y: { beginAtZero: true, grid: { color: tone.line }, ticks: { color: tone.muted, precision: 0 } },
    };
  }
  function xAxisZoom() {
    return {
      limits: { x: { min: "original", max: "original", minRange: 1 } },
      pan: { enabled: true, mode: "x", threshold: 5 },
      zoom: { wheel: { enabled: true, speed: 0.08 }, pinch: { enabled: true }, mode: "x" },
    };
  }
  function showCanvas(id, hasData) {
    const canvas = $(id);
    const empty = $(`${id}Empty`);
    if (canvas) canvas.hidden = !hasData;
    if (empty) empty.hidden = hasData;
    return canvas;
  }

  function mount(key, id, hasData, config, interactive = false) {
    const existing = state.charts[key];
    if (existing && typeof existing.destroy === "function") existing.destroy();
    state.charts[key] = null;
    const chartAvailable = typeof Chart !== "undefined";
    const canvas = showCanvas(id, hasData && chartAvailable);
    if (!hasData || !canvas || !chartAvailable) return;
    Chart.defaults.font.family = css("--font-body");
    state.charts[key] = new Chart(canvas, config);
    if (interactive && !canvas.dataset.zoomResetBound) {
      canvas.addEventListener("dblclick", () => state.charts[key]?.resetZoom?.());
      canvas.dataset.zoomResetBound = "true";
    }
  }

  function renderFunnel(rows) {
    const values = rows.map((row) => row.count);
    const tone = colors();
    mount("metricsFunnel", "funnelChart", values.some(Boolean), {
      type: "bar",
      data: {
        labels: rows.map((row) => row.label),
        datasets: [{ data: values, backgroundColor: tone.accent, borderRadius: 8, borderSkipped: false }],
      },
      options: {
        indexAxis: "y", responsive: true, maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: tooltip({
            label: (item) => {
              const previous = item.dataIndex ? values[item.dataIndex - 1] : values[0];
              const rate = previous ? Math.round((Number(item.raw) / previous) * 100) : 0;
              return `${item.raw} jobs · ${rate}% of previous stage`;
            },
          }),
        },
        scales: {
          x: { beginAtZero: true, grid: { color: tone.line }, ticks: { color: tone.muted, precision: 0 } },
          y: { grid: { display: false }, ticks: { color: tone.muted } },
        },
      },
    });
  }

  function renderSources(rows) {
    const tone = colors();
    const palette = [tone.accent, tone.accent2, tone.good, tone.warn, tone.bad, tone.muted];
    mount("metricsSources", "sourcesChart", rows.some((row) => row.count), {
      type: "doughnut",
      data: {
        labels: rows.map((row) => row.source),
        datasets: [{
          data: rows.map((row) => row.count),
          backgroundColor: rows.map((_, index) => palette[index % palette.length]),
          borderColor: tone.surface, borderWidth: 3, hoverOffset: 8,
        }],
      },
      options: {
        responsive: true, maintainAspectRatio: false, cutout: "66%",
        plugins: {
          legend: { position: "bottom", labels: { color: tone.muted, usePointStyle: true, boxWidth: 8 } },
          tooltip: tooltip({
            label: (item) => `${item.label}: ${item.raw} tracked · ${rows[item.dataIndex].conversion_rate}% applied`,
          }),
        },
      },
    });
    $("sourceConversionTable").innerHTML = rows.length ? `
      <div class="source-table-head"><span>Source</span><span>Applied</span><span>Rate</span></div>
      ${rows.map((row) => `<div class="source-table-row"><strong>${esc(row.source)}</strong><span>${row.applications}/${row.count}</span><span>${row.conversion_rate}%</span></div>`).join("")}`
      : '<div class="chart-empty-inline">No source conversion data yet.</div>';
  }

  function renderScores(rows) {
    const tone = colors();
    mount("metricsScores", "scoreChart", rows.some((row) => row.count), {
      type: "bar",
      data: {
        labels: rows.map((row) => row.label),
        datasets: [{
          label: "Jobs", data: rows.map((row) => row.count),
          backgroundColor: [tone.bad, tone.warn, tone.accent2, tone.good],
          borderRadius: 8, borderSkipped: false,
        }],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false }, tooltip: tooltip({ label: (item) => `${item.raw} scored jobs` }), zoom: xAxisZoom() },
        scales: axes(),
      },
    }, true);
  }

  function renderApplications(rows) {
    const tone = colors();
    mount("metricsApplications", "applicationsChart", rows.some((row) => row.count), {
      type: "line",
      data: {
        labels: rows.map((row) => row.date.slice(5)),
        datasets: [{
          label: "Applications", data: rows.map((row) => row.count),
          borderColor: tone.accent, backgroundColor: tone.soft, fill: true,
          borderWidth: 2, tension: 0.32, pointRadius: 2, pointHoverRadius: 6,
        }],
      },
      options: {
        responsive: true, maintainAspectRatio: false, interaction: { intersect: false, mode: "index" },
        plugins: { legend: { display: false }, tooltip: tooltip(), zoom: xAxisZoom() },
        scales: axes(),
      },
    }, true);
  }

  function renderStatus(rows) {
    $("statusSnapshot").innerHTML = rows.length
      ? rows.map((row) => `<div class="status-snapshot-row"><span>${esc(row.status.replaceAll("_", " "))}</span><strong>${row.count}</strong></div>`).join("")
      : '<div class="chart-empty-inline">No tracked statuses yet.</div>';
  }

  function renderInsights(metrics) {
    const kpis = metrics.kpis || {};
    $("insightsMetrics").innerHTML = [
      window.metric("Tracked", kpis.tracked || 0),
      window.metric("Applied", kpis.applied || 0, `${kpis.application_rate || 0}% of tracked`),
      window.metric("Response rate", `${kpis.response_rate || 0}%`, `${kpis.responses || 0} responses`),
      window.metric("Interview rate", `${kpis.interview_rate || 0}%`, `${kpis.interviews || 0} interviews`),
    ].join("");
    renderFunnel(metrics.funnel || []);
    renderSources(metrics.sources || []);
    renderScores(metrics.score_distribution || []);
    renderApplications(metrics.applications_over_time || []);
    renderStatus(metrics.status_now || []);
  }

  async function loadInsights() {
    try {
      const payload = await api("/api/metrics");
      state.insightsCache = payload;
      renderInsights(payload);
    } catch (error) {
      window.toast(`Insights error: ${error.message}`);
    }
  }

  $("insightsRefreshBtn").addEventListener("click", loadInsights);
  window.JobAgentInsights = { load: loadInsights, render: renderInsights };
})();
