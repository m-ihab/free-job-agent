// Portfolio builder (R3 split from app.js). Classic script, defer, after
// app.js — pipeline.js idiom: window.* aliases for app.js function
// declarations, bare `state` for the shared script-scope const.
(function () {
  const api = (...args) => window.api(...args);
  const toast = (...args) => window.toast(...args);
  const setNotice = (...args) => window.setNotice(...args);
  const setBusy = (...args) => window.setBusy(...args);
  const escapeHtml = (value) => window.escapeHtml(value);
  const safeHref = (value) => window.safeHref(value);

function renderPortfolioOptions(data) {
  const cfg = (data && data.config) || {};
  const theme = document.getElementById("portfolioTheme");
  const font = document.getElementById("portfolioFont");
  const layout = document.getElementById("portfolioLayout");
  if (theme && data.themes) {
    const current = cfg.theme || theme.value || "signal";
    theme.innerHTML = data.themes.map((item) => `<option value="${escapeHtml(item.key)}">${escapeHtml(item.label)} · ${escapeHtml(item.preset || "")}</option>`).join("");
    theme.value = data.themes.some((item) => item.key === current) ? current : "signal";
  }
  if (font && data.fonts) {
    const current = cfg.font || font.value || "inter";
    font.innerHTML = data.fonts.map((item) => `<option value="${escapeHtml(item.key)}">${escapeHtml(item.label)}</option>`).join("");
    font.value = data.fonts.some((item) => item.key === current) ? current : "inter";
  }
  if (layout && data.layouts) {
    const current = cfg.layout || layout.value || "split";
    layout.innerHTML = data.layouts.map((item) => `<option value="${escapeHtml(item.key)}">${escapeHtml(item.label)}</option>`).join("");
    layout.value = data.layouts.some((item) => item.key === current) ? current : "split";
  }
  const accent = document.getElementById("portfolioAccent");
  if (accent) accent.value = (cfg.custom_accent && /^#[0-9a-fA-F]{6}$/.test(cfg.custom_accent)) ? cfg.custom_accent : "#2563eb";
  const tagline = document.getElementById("portfolioTagline");
  if (tagline) tagline.value = cfg.tagline || "";
  const siteUrl = document.getElementById("portfolioSiteUrl");
  if (siteUrl) siteUrl.value = cfg.site_url || "";
  const darkToggle = document.getElementById("portfolioDarkToggle");
  if (darkToggle) darkToggle.checked = cfg.enable_dark_toggle !== false;
  const animations = document.getElementById("portfolioAnimations");
  if (animations) animations.checked = cfg.enable_animations !== false;
  renderPortfolioSections(data, cfg);
  renderPortfolioOrder(cfg);
  const path = document.getElementById("portfolioPath");
  if (path) path.textContent = data.path ? `Local folder: ${data.path}` : "";
}

const PORTFOLIO_SECTION_LABELS = {
  skills: "Core stack",
  projects: "Projects",
  experience: "Experience",
  education: "Education",
};

function renderPortfolioOrder(cfg) {
  const list = document.getElementById("portfolioOrder");
  if (!list) return;
  const defaults = ["skills", "projects", "experience", "education"];
  let order = Array.isArray(cfg.section_order) && cfg.section_order.length ? cfg.section_order.slice() : defaults.slice();
  order = order.filter((k) => defaults.includes(k));
  defaults.forEach((k) => { if (!order.includes(k)) order.push(k); });
  state.portfolioOrder = order;
  list.innerHTML = order.map((key, idx) => `
    <li class="section-order-row" data-key="${escapeHtml(key)}">
      <span>${escapeHtml(PORTFOLIO_SECTION_LABELS[key] || key)}</span>
      <span class="order-actions">
        <button type="button" data-move="up" ${idx === 0 ? "disabled" : ""} aria-label="Move up">↑</button>
        <button type="button" data-move="down" ${idx === order.length - 1 ? "disabled" : ""} aria-label="Move down">↓</button>
      </span>
    </li>`).join("");
  list.querySelectorAll("button[data-move]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const row = btn.closest("[data-key]");
      const key = row.dataset.key;
      const i = state.portfolioOrder.indexOf(key);
      const j = btn.dataset.move === "up" ? i - 1 : i + 1;
      if (j < 0 || j >= state.portfolioOrder.length) return;
      [state.portfolioOrder[i], state.portfolioOrder[j]] = [state.portfolioOrder[j], state.portfolioOrder[i]];
      renderPortfolioOrder({ section_order: state.portfolioOrder });
    });
  });
}

function renderPortfolioSections(data, cfg) {
  const wrap = document.getElementById("portfolioSections");
  if (!wrap || !data.optional_sections) return;
  const sectionLabels = {
    open_source: "Open Source",
    speaking: "Speaking",
    awards: "Awards",
    testimonials: "Testimonials",
    blog: "Writing",
  };
  const checks = (cfg.sections || {});
  wrap.innerHTML = `<span class="muted" style="margin-right:0.4rem">Optional sections:</span>` + data.optional_sections.map((key) =>
    `<label class="check-row"><input type="checkbox" data-portfolio-section="${escapeHtml(key)}" ${checks[key] ? "checked" : ""} /> ${escapeHtml(sectionLabels[key] || key)}</label>`
  ).join("");
}

function readPortfolioSections() {
  const checks = {};
  document.querySelectorAll('[data-portfolio-section]').forEach((el) => {
    checks[el.dataset.portfolioSection] = el.checked;
  });
  return checks;
}

function portfolioPayload() {
  return {
    theme: document.getElementById("portfolioTheme")?.value || "signal",
    font: document.getElementById("portfolioFont")?.value || "inter",
    layout: document.getElementById("portfolioLayout")?.value || "split",
    custom_accent: document.getElementById("portfolioAccent")?.value || "",
    tagline: document.getElementById("portfolioTagline")?.value || "",
    site_url: document.getElementById("portfolioSiteUrl")?.value || "",
    sections: readPortfolioSections(),
    section_order: Array.isArray(state.portfolioOrder) ? state.portfolioOrder : null,
    enable_dark_toggle: document.getElementById("portfolioDarkToggle")?.checked !== false,
    enable_animations: document.getElementById("portfolioAnimations")?.checked !== false,
  };
}

function setPortfolioEditors(data) {
  const htmlEditor = document.getElementById("portfolioHtmlEditor");
  const cssEditor = document.getElementById("portfolioCssEditor");
  if (htmlEditor && data.html) htmlEditor.value = data.html;
  if (cssEditor && data.css) cssEditor.value = data.css;
  const iframe = document.getElementById("portfolioPreview");
  if (iframe) iframe.src = `/api/portfolio/preview?t=${Date.now()}`;
}

async function loadPortfolio() {
  try {
    const data = await api("/api/portfolio");
    state.portfolio = data;
    renderPortfolioOptions(data);
    setPortfolioEditors(data);
  } catch (error) {
    setNotice("portfolioNotice", error.message, true);
  }
}

async function generatePortfolio() {
  const button = document.getElementById("portfolioGenerateBtn");
  setBusy(button, true);
  setNotice("portfolioNotice", "");
  try {
    const data = await api("/api/portfolio/generate", portfolioPayload());
    state.portfolio = data;
    // Re-read full state to refresh the controls (themes, layouts, etc.)
    try {
      state.portfolio = await api("/api/portfolio");
    } catch (refreshError) {
      console.debug("Could not refresh portfolio state after generation", refreshError);
      state.portfolio = data;
    }
    setPortfolioEditors(data);
    renderPortfolioOptions(state.portfolio || data);
    toast("Portfolio regenerated locally.");
  } catch (error) {
    setNotice("portfolioNotice", error.message, true);
  } finally {
    setBusy(button, false);
  }
}

async function fetchAiTagline() {
  const button = document.getElementById("portfolioAiTaglineBtn");
  const input = document.getElementById("portfolioTagline");
  if (!input) return;
  setBusy(button, true);
  try {
    const result = await api("/api/portfolio/tagline", {});
    if (result.tagline) {
      input.value = result.tagline;
      toast(result.available ? "AI tagline ready." : "Used deterministic tagline.");
    }
  } catch (error) {
    setNotice("portfolioNotice", error.message, true);
  } finally {
    setBusy(button, false);
  }
}

async function loadGithubReposForPortfolio() {
  const button = document.getElementById("portfolioGithubLoadBtn");
  const panel = document.getElementById("portfolioGithubPanel");
  const list = document.getElementById("portfolioGithubRepos");
  if (!panel || !list) return;
  setBusy(button, true);
  panel.classList.remove("hidden");
  list.innerHTML = "<p class='muted'>Loading…</p>";
  try {
    const data = await api("/api/portfolio/github-repos", {});
    state.portfolioRepos = data.repos || [];
    if (!state.portfolioRepos.length) {
      list.innerHTML = "<p class='muted'>No repos found on GitHub for that handle.</p>";
      return;
    }
    list.innerHTML = state.portfolioRepos.map((repo) => `
      <label class="check-row" style="display:grid;grid-template-columns:auto 1fr auto;gap:0.5rem;border-bottom:1px dashed var(--line);padding:0.4rem 0;align-items:start">
        <input type="checkbox" data-portfolio-repo="${escapeHtml(repo.name)}" />
        <div>
          <strong>${escapeHtml(repo.name)}</strong>
          <span class="coach-sub">${escapeHtml(repo.description || "—")}</span>
          <span class="row-tag">${escapeHtml(repo.language || "")} · ★ ${repo.stars || 0}</span>
        </div>
        <a href="${safeHref(repo.url)}" target="_blank" rel="noreferrer" class="muted">Open</a>
      </label>
    `).join("");
  } catch (error) {
    list.innerHTML = `<p class="notice error">${escapeHtml(error.message)}</p>`;
  } finally {
    setBusy(button, false);
  }
}

async function importSelectedGithubRepos() {
  const list = document.getElementById("portfolioGithubRepos");
  const button = document.getElementById("portfolioGithubImportBtn");
  if (!list) return;
  const names = Array.from(list.querySelectorAll('[data-portfolio-repo]:checked')).map((el) => el.dataset.portfolioRepo);
  if (!names.length) {
    toast("Tick at least one repo first.");
    return;
  }
  setBusy(button, true);
  try {
    const handle = (state.portfolio && state.portfolio.handle) || "";
    const data = await api("/api/portfolio/import-github", { repos: names, handle });
    if (data.ok) {
      toast(`Added ${data.added.length} project(s). Regenerate to see them.`);
      // Auto-regenerate so the user sees the result right away.
      await generatePortfolio();
    } else {
      toast(`Import failed: ${data.reason || "unknown"}`);
    }
  } catch (error) {
    toast(error.message);
  } finally {
    setBusy(button, false);
  }
}

async function savePortfolioEdits() {
  const button = document.getElementById("portfolioSaveBtn");
  const htmlEditor = document.getElementById("portfolioHtmlEditor");
  const cssEditor = document.getElementById("portfolioCssEditor");
  setBusy(button, true);
  try {
    const result = await api("/api/portfolio/save", {
      html: htmlEditor ? htmlEditor.value : "",
      css: cssEditor ? cssEditor.value : "",
    });
    if (result.ok) {
      const iframe = document.getElementById("portfolioPreview");
      if (iframe) iframe.src = `/api/portfolio/preview?t=${Date.now()}`;
      toast("Portfolio edits saved.");
    }
  } catch (error) {
    setNotice("portfolioNotice", error.message, true);
  } finally {
    setBusy(button, false);
  }
}

async function suggestPortfolioDesign() {
  const button = document.getElementById("portfolioSuggestBtn");
  const list = document.getElementById("portfolioSuggestions");
  setBusy(button, true);
  if (list) list.innerHTML = "<li class='muted'>Thinking locally...</li>";
  try {
    const result = await api("/api/portfolio/suggest", {});
    const items = result.suggestions || [];
    if (list) {
      list.innerHTML = items.length
        ? items.map((item) => `<li><div><span class="coach-title">${escapeHtml(item.title || "")}</span><span class="coach-sub">${escapeHtml(item.detail || "")}</span></div><strong>${result.available ? "AI" : "local"}</strong></li>`).join("")
        : "<li class='muted'>No suggestions yet.</li>";
    }
  } catch (error) {
    if (list) list.innerHTML = `<li class="notice error">${escapeHtml(error.message)}</li>`;
  } finally {
    setBusy(button, false);
  }
}

async function buildPublishGuide() {
  const button = document.getElementById("portfolioPublishBtn");
  const target = document.getElementById("portfolioPublishResult");
  setBusy(button, true);
  try {
    const result = await api("/api/portfolio/publish-guide", {});
    if (target) target.innerHTML = result.ok
      ? `Created local checklist: <code>${escapeHtml(result.path)}</code>`
      : `Failed: ${escapeHtml(result.reason || "unknown")}`;
    toast("Publish checklist ready.");
  } catch (error) {
    if (target) target.textContent = error.message;
  } finally {
    setBusy(button, false);
  }
}


  // ---- event bindings (moved from bindEvents) ----
  // Portfolio Builder
  const portfolioGenerateBtn = document.getElementById("portfolioGenerateBtn");
  if (portfolioGenerateBtn) portfolioGenerateBtn.addEventListener("click", generatePortfolio);
  const portfolioSaveBtn = document.getElementById("portfolioSaveBtn");
  if (portfolioSaveBtn) portfolioSaveBtn.addEventListener("click", savePortfolioEdits);
  const portfolioSuggestBtn = document.getElementById("portfolioSuggestBtn");
  if (portfolioSuggestBtn) portfolioSuggestBtn.addEventListener("click", suggestPortfolioDesign);
  const portfolioPublishBtn = document.getElementById("portfolioPublishBtn");
  if (portfolioPublishBtn) portfolioPublishBtn.addEventListener("click", buildPublishGuide);
  const portfolioTheme = document.getElementById("portfolioTheme");
  if (portfolioTheme) portfolioTheme.addEventListener("change", generatePortfolio);
  const portfolioFont = document.getElementById("portfolioFont");
  if (portfolioFont) portfolioFont.addEventListener("change", generatePortfolio);
  const portfolioLayout = document.getElementById("portfolioLayout");
  if (portfolioLayout) portfolioLayout.addEventListener("change", generatePortfolio);
  const portfolioAccent = document.getElementById("portfolioAccent");
  if (portfolioAccent) portfolioAccent.addEventListener("change", generatePortfolio);
  const portfolioDarkToggle = document.getElementById("portfolioDarkToggle");
  if (portfolioDarkToggle) portfolioDarkToggle.addEventListener("change", generatePortfolio);
  const portfolioAnimations = document.getElementById("portfolioAnimations");
  if (portfolioAnimations) portfolioAnimations.addEventListener("change", generatePortfolio);
  document.body.addEventListener("change", (event) => {
    if (event.target && event.target.matches('[data-portfolio-section]')) {
      generatePortfolio();
    }
  });
  const portfolioAiTaglineBtn = document.getElementById("portfolioAiTaglineBtn");
  if (portfolioAiTaglineBtn) portfolioAiTaglineBtn.addEventListener("click", fetchAiTagline);
  const portfolioGithubLoadBtn = document.getElementById("portfolioGithubLoadBtn");
  if (portfolioGithubLoadBtn) portfolioGithubLoadBtn.addEventListener("click", loadGithubReposForPortfolio);
  const portfolioGithubImportBtn = document.getElementById("portfolioGithubImportBtn");
  if (portfolioGithubImportBtn) portfolioGithubImportBtn.addEventListener("click", importSelectedGithubRepos);
  const portfolioGithubCloseBtn = document.getElementById("portfolioGithubCloseBtn");
  if (portfolioGithubCloseBtn) portfolioGithubCloseBtn.addEventListener("click", () => {
    document.getElementById("portfolioGithubPanel")?.classList.add("hidden");
  });


  window.JobAgentPortfolio = {
    load: loadPortfolio,
  };
})();
