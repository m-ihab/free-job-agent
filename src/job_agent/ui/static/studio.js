// CV Studio — editor core (R3 split from app.js).
// Classic script loaded with defer AFTER app.js; reads shared app.js
// globals at call time (pipeline.js idiom): function declarations via
// window.*, top-level consts (state) as bare script-scope identifiers.
// Exposes window.JobAgentStudio for activateTab and studio_tools.js.
(function () {
  const api = (...args) => window.api(...args);
  const toast = (...args) => window.toast(...args);
  const setNotice = (...args) => window.setNotice(...args);
  const setBusy = (...args) => window.setBusy(...args);
  const escapeHtml = (value) => window.escapeHtml(value);

// ===== CV Studio =====
async function loadStudio() {
  try {
    const data = await api("/api/cv-studio");
    state.studio = data;
    const textarea = document.getElementById("studioTextarea");
    if (textarea && !textarea.dataset.dirty) textarea.value = data.text || "";
    renderStudioSections(data.sections || [], data.section_display || {});
    const langSel = document.getElementById("studioLanguage");
    if (langSel && data.language) langSel.value = data.language;
    const status = document.getElementById("studioStatus");
    if (status) {
      status.textContent = data.origin === "draft" ? "Editing draft (unsaved promotion to main.tex)" : "Loaded main.tex";
    }
    studioSyncGutter();
  } catch (error) {
    setNotice("studioNotice", error.message, true);
  }
}

function studioSyncGutter() {
  const textarea = document.getElementById("studioTextarea");
  const gutter = document.getElementById("studioGutter");
  if (!textarea || !gutter) return;
  const lines = (textarea.value.match(/\n/g) || []).length + 1;
  const current = gutter.childElementCount ? gutter.dataset.lines : "";
  if (String(lines) !== current) {
    let out = "";
    for (let i = 1; i <= lines; i++) out += i + "\n";
    gutter.textContent = out;
    gutter.dataset.lines = String(lines);
  }
  gutter.scrollTop = textarea.scrollTop;
}

function renderStudioSections(titles, display) {
  const list = document.getElementById("studioSections");
  if (!list) return;
  display = display || {};
  if (!titles.length) {
    list.innerHTML = "<li class='muted'>No \\section{...} blocks found yet.</li>";
    return;
  }
  list.innerHTML = titles
    .map((title) => `<li draggable="true" data-section="${escapeHtml(title)}">${escapeHtml(display[title] || title)}</li>`)
    .join("");
  attachSectionDnd(list);
}

function attachSectionDnd(list) {
  let dragEl = null;
  list.querySelectorAll("li").forEach((li) => {
    li.addEventListener("dragstart", () => { dragEl = li; li.classList.add("dragging"); });
    li.addEventListener("dragend", () => { if (dragEl) dragEl.classList.remove("dragging"); dragEl = null; list.querySelectorAll("li").forEach((x) => x.classList.remove("drop-target")); });
    li.addEventListener("dragover", (e) => { e.preventDefault(); list.querySelectorAll("li").forEach((x) => x.classList.remove("drop-target")); li.classList.add("drop-target"); });
    li.addEventListener("drop", (e) => {
      e.preventDefault();
      if (dragEl && dragEl !== li) {
        const rect = li.getBoundingClientRect();
        const before = (e.clientY - rect.top) < rect.height / 2;
        list.insertBefore(dragEl, before ? li : li.nextSibling);
      }
    });
  });
}

async function studioSetLanguage(lang) {
  const textarea = document.getElementById("studioTextarea");
  try {
    const result = await api("/api/cv-studio/language", { language: lang });
    if (!result.ok) {
      setNotice("studioNotice", result.reason === "no_language_toggle"
        ? "This template has no \\cvlang toggle, so the language can't be switched automatically."
        : "Could not switch language.", true);
      return;
    }
    if (textarea) { textarea.value = result.text || textarea.value; delete textarea.dataset.dirty; }
    await studioCompile();
    toast(`CV language set to ${result.language === "fr" ? "Français" : "English"}.`);
  } catch (error) {
    setNotice("studioNotice", error.message, true);
  }
}

async function studioSwapEduExp() {
  const button = document.getElementById("studioSwapEduExpBtn");
  const textarea = document.getElementById("studioTextarea");
  setBusy(button, true);
  setNotice("studioNotice", "");
  try {
    const result = await api("/api/cv-studio/swap-sections", { a: "Education", b: "Professional Experience" });
    if (!result.ok) {
      setNotice("studioNotice", result.reason === "section_not_found"
        ? "Couldn't find both Education and Professional Experience sections to swap."
        : "Swap failed.", true);
      return;
    }
    if (textarea) { textarea.value = result.text || textarea.value; delete textarea.dataset.dirty; }
    renderStudioSections(result.sections || [], result.section_display || {});
    await studioCompile();
    toast("Swapped Education and Professional Experience.");
  } catch (error) {
    setNotice("studioNotice", error.message, true);
  } finally {
    setBusy(button, false);
  }
}

function studioRefreshPreview() {
  const iframe = document.getElementById("studioPreview");
  // Fit the WHOLE page into the frame (page-fit, not page-width) so the full
  // CV is visible without scrolling; the taller preview panel (see app.css)
  // keeps it readable, and "Open full PDF" covers close inspection.
  if (iframe) iframe.src = `/api/cv-studio/preview-pdf?t=${Date.now()}#zoom=page-fit`;
}

async function studioCompile() {
  const button = document.getElementById("studioCompileBtn");
  const textarea = document.getElementById("studioTextarea");
  setBusy(button, true);
  setNotice("studioNotice", "");
  try {
    const text = textarea ? textarea.value : "";
    const result = await api("/api/cv-studio/compile", { text });
    if (!result.ok) {
      const reason = result.reason || "compile_failed";
      const log = (result.log || "").slice(-2000);
      const logHtml = log
        ? `<details style="margin-top:0.5rem"><summary style="cursor:pointer;font-size:0.8rem">LaTeX error log ▸</summary><pre style="font-size:0.75rem;max-height:280px;overflow:auto;white-space:pre-wrap;margin-top:0.4rem">${escapeHtml(log)}</pre></details>`
        : "";
      const noticeEl = document.getElementById("studioNotice");
      if (noticeEl) {
        noticeEl.className = "notice error";
        noticeEl.innerHTML = `Compile failed (${escapeHtml(reason)}).${logHtml}`;
      }
      return;
    }
    studioRefreshPreview();
    toast("Preview rebuilt.");
  } catch (error) {
    setNotice("studioNotice", error.message, true);
  } finally {
    setBusy(button, false);
  }
}

async function studioSaveDraft() {
  const button = document.getElementById("studioSaveBtn");
  const textarea = document.getElementById("studioTextarea");
  setBusy(button, true);
  try {
    await api("/api/cv-studio/save", { text: textarea ? textarea.value : "" });
    if (textarea) textarea.dataset.dirty = "";
    toast("Draft saved locally.");
    await loadStudio();
  } catch (error) {
    setNotice("studioNotice", error.message, true);
  } finally {
    setBusy(button, false);
  }
}

async function studioReset() {
  if (!window.confirm("Discard the working draft and reload main.tex?")) return;
  const button = document.getElementById("studioResetBtn");
  setBusy(button, true);
  try {
    await api("/api/cv-studio/reset", {});
    const textarea = document.getElementById("studioTextarea");
    if (textarea) delete textarea.dataset.dirty;
    await loadStudio();
    toast("Draft discarded.");
  } catch (error) {
    setNotice("studioNotice", `Discard failed: ${error.message}`, true);
  } finally {
    setBusy(button, false);
  }
}

async function studioPromote() {
  if (!window.confirm("Overwrite profiles/main.tex with the current draft? A snapshot of the current version is kept.")) return;
  const button = document.getElementById("studioPromoteBtn");
  setBusy(button, true);
  try {
    const result = await api("/api/cv-studio/promote", {});
    if (result.ok) {
      toast("Saved draft to main.tex.");
      const versions = document.getElementById("studioVersions");
      if (versions && !versions.classList.contains("hidden")) {
        await studioLoadVersions();
      }
    } else {
      setNotice("studioNotice", result.log || `Could not save: ${result.reason}`, true);
    }
  } catch (error) {
    setNotice("studioNotice", `Save as main.tex failed: ${error.message}`, true);
  } finally {
    setBusy(button, false);
  }
}

async function studioToggleVersions() {
  const panel = document.getElementById("studioVersions");
  if (!panel) return;
  const willShow = panel.classList.contains("hidden");
  panel.classList.toggle("hidden");
  if (willShow) await studioLoadVersions();
}

async function studioLoadVersions() {
  const list = document.getElementById("studioVersionList");
  if (!list) return;
  list.innerHTML = "<li class='muted'>Loading…</li>";
  try {
    const result = await api("/api/cv-studio/versions", {});
    const versions = (result && result.versions) || [];
    if (!versions.length) {
      list.innerHTML = "<li class='muted'>No saved versions yet.</li>";
      return;
    }
    list.innerHTML = versions.map((v) => {
      const kb = Math.max(1, Math.round((v.size || 0) / 1024));
      const label = String(v.name).replace(/^main\.|\.tex$/g, "");
      return `<li class="version-row">
        <span class="version-name">${escapeHtml(label)}</span>
        <span class="version-size muted">${kb} KB</span>
        <button data-restore="${escapeHtml(v.name)}">Restore</button>
      </li>`;
    }).join("");
    list.querySelectorAll("button[data-restore]").forEach((btn) => {
      btn.addEventListener("click", () => studioRestoreVersion(btn.dataset.restore));
    });
  } catch (error) {
    list.innerHTML = `<li class="muted">${escapeHtml(error.message)}</li>`;
  }
}

async function studioRestoreVersion(name) {
  if (!window.confirm(`Restore main.tex from ${name}? The current version is snapshotted first.`)) return;
  const result = await api("/api/cv-studio/restore-version", { name });
  if (result.ok) {
    toast("Restored main.tex from history.");
    await loadStudio();
    await studioLoadVersions();
  } else {
    setNotice("studioNotice", `Could not restore: ${result.reason}`, true);
  }
}

async function studioSuggest() {
  const button = document.getElementById("studioSuggestBtn");
  const textarea = document.getElementById("studioTextarea");
  const target = document.getElementById("studioSuggestionList");
  setBusy(button, true);
  if (target) target.innerHTML = "<div class='muted'>Thinking locally…</div>";
  try {
    const result = await api("/api/cv-studio/suggest", { text: textarea ? textarea.value : "" });
    if (!result.available) {
      if (target) target.innerHTML = "<div class='muted'>Start Ollama (Autopilot tab) to unlock AI suggestions.</div>";
      return;
    }
    const items = result.suggestions || [];
    if (!items.length) {
      if (target) target.innerHTML = "<div class='muted'>No suggestions — your CV already looks tight.</div>";
      return;
    }
    state.studioSuggestions = items;
    if (target) target.innerHTML = items.map((s, idx) => `
      <div class="studio-suggestion" data-suggest-idx="${idx}">
        <div class="suggest-head">
          <strong>${escapeHtml(s.title)}</strong>
          <span class="row-tag">${escapeHtml(s.priority || "")} · ${escapeHtml(s.section || "")}</span>
        </div>
        <p class="muted" style="margin:0 0 0.3rem">${escapeHtml(s.rationale || "")}</p>
        ${s.before ? `<code class="suggest-before" title="Current text in your CV">${escapeHtml(s.before)}</code>` : ""}
        ${s.after ? `<label class="suggest-edit-label">Edit before applying${/\[[A-Za-z0-9_\- ]+\]/.test(s.after) ? ' <span class="row-tag warn">has placeholders</span>' : ""}</label>` : ""}
        ${s.after ? `<textarea class="suggest-after-edit" data-suggest-after-edit="${idx}" rows="3">${escapeHtml(s.after)}</textarea>` : ""}
        ${s.before && s.after ? `<div class="action-row" style="margin-top:0.4rem">
          <button data-suggest-apply-idx="${idx}" class="primary-soft">Apply</button>
          <button data-suggest-reset-idx="${idx}">Reset edit</button>
          <button data-suggest-dismiss-idx="${idx}">Dismiss</button>
        </div>` : ""}
      </div>
    `).join("");
  } catch (error) {
    if (target) target.innerHTML = `<div class='notice error'>${escapeHtml(error.message)}</div>`;
  } finally {
    setBusy(button, false);
  }
}

function studioApplySuggestion(before, after) {
  const textarea = document.getElementById("studioTextarea");
  if (!textarea || !before) return;
  if (!textarea.value.includes(before)) {
    toast("Suggestion's 'before' text isn't an exact match — apply manually.");
    return;
  }
  textarea.value = textarea.value.replace(before, after);
  textarea.dataset.dirty = "1";
  toast("Suggestion applied. Click Compile preview to render.");
}

// ===== Studio v2: assets, photo, icon pack, single-page, GitHub import =====

  // ---- event bindings (moved from bindEvents) ----
  // CV Studio
  const studioCompileBtn = document.getElementById("studioCompileBtn");
  if (studioCompileBtn) studioCompileBtn.addEventListener("click", studioCompile);
  const studioSaveBtn = document.getElementById("studioSaveBtn");
  if (studioSaveBtn) studioSaveBtn.addEventListener("click", studioSaveDraft);
  const studioResetBtn = document.getElementById("studioResetBtn");
  if (studioResetBtn) studioResetBtn.addEventListener("click", studioReset);
  const studioPromoteBtn = document.getElementById("studioPromoteBtn");
  if (studioPromoteBtn) studioPromoteBtn.addEventListener("click", studioPromote);
  const studioSuggestBtn = document.getElementById("studioSuggestBtn");
  if (studioSuggestBtn) studioSuggestBtn.addEventListener("click", studioSuggest);
  const studioReloadBtn = document.getElementById("studioReloadBtn");
  if (studioReloadBtn) studioReloadBtn.addEventListener("click", async () => {
    const ta = document.getElementById("studioTextarea");
    if (ta) delete ta.dataset.dirty;
    await loadStudio();
  });
  const studioVersionsBtn = document.getElementById("studioVersionsBtn");
  if (studioVersionsBtn) studioVersionsBtn.addEventListener("click", studioToggleVersions);
  const studioSwapBtn = document.getElementById("studioSwapEduExpBtn");
  if (studioSwapBtn) studioSwapBtn.addEventListener("click", studioSwapEduExp);
  const studioLangSel = document.getElementById("studioLanguage");
  if (studioLangSel) studioLangSel.addEventListener("change", (event) => studioSetLanguage(event.target.value));
  const studioTextarea = document.getElementById("studioTextarea");
  if (studioTextarea) {
    studioTextarea.addEventListener("input", () => { studioTextarea.dataset.dirty = "1"; studioSyncGutter(); });
    studioTextarea.addEventListener("scroll", studioSyncGutter);
  }

  // Studio suggestion apply / reset / dismiss (delegated)
  document.body.addEventListener("click", (event) => {
    const apply = event.target.closest("[data-suggest-apply-idx]");
    if (apply) {
      const idx = Number(apply.dataset.suggestApplyIdx);
      const suggestion = (state.studioSuggestions || [])[idx];
      if (!suggestion) return;
      const editEl = document.querySelector(`[data-suggest-after-edit="${idx}"]`);
      const after = editEl ? editEl.value : suggestion.after;
      if (/\[[A-Za-z0-9_\- ]+\]/.test(after)) {
        if (!window.confirm("Your text still contains placeholders like [X]. Apply anyway?")) return;
      }
      studioApplySuggestion(suggestion.before, after);
      const card = apply.closest("[data-suggest-idx]");
      if (card) card.style.opacity = "0.55";
      return;
    }
    const reset = event.target.closest("[data-suggest-reset-idx]");
    if (reset) {
      const idx = Number(reset.dataset.suggestResetIdx);
      const suggestion = (state.studioSuggestions || [])[idx];
      const editEl = document.querySelector(`[data-suggest-after-edit="${idx}"]`);
      if (suggestion && editEl) editEl.value = suggestion.after;
      return;
    }
    const dismiss = event.target.closest("[data-suggest-dismiss-idx]");
    if (dismiss) {
      const card = dismiss.closest("[data-suggest-idx]");
      if (card) card.remove();
      return;
    }
    // Backward-compat: the old data-suggest-apply attribute may still exist.
    const legacy = event.target.closest("[data-suggest-apply]");
    if (legacy) {
      const [before, after] = legacy.dataset.suggestApply.split("|||");
      studioApplySuggestion(before, after);
    }
  });


  window.JobAgentStudio = {
    load: loadStudio,
    compile: studioCompile,
    renderSections: renderStudioSections,
  };
})();
