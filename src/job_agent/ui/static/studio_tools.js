// CV Studio — assets, analysis and project tools (R3 split from app.js).
// Loads after studio.js; calls the editor core through window.JobAgentStudio
// (runtime lookups, so load order only matters before first user click).
(function () {
  const api = (...args) => window.api(...args);
  const toast = (...args) => window.toast(...args);
  const setNotice = (...args) => window.setNotice(...args);
  const setBusy = (...args) => window.setBusy(...args);
  const escapeHtml = (value) => window.escapeHtml(value);
  const loadStudio = (...args) => window.JobAgentStudio.load(...args);
  const studioCompile = (...args) => window.JobAgentStudio.compile(...args);
  const renderStudioSections = (...args) => window.JobAgentStudio.renderSections(...args);

async function loadStudioAssets() {
  const node = document.getElementById("studioAssetList");
  if (!node) return;
  try {
    const data = await api("/api/cv-studio/assets");
    state.studioAssets = data.assets || [];
    if (!state.studioAssets.length) {
      node.innerHTML = "<li class='muted'>No assets found in profiles/.</li>";
      return;
    }
    node.innerHTML = state.studioAssets.map((a) => {
      const size = a.kind === "image" ? `${Math.round(a.size / 1024)} KB` : `${a.size} B`;
      return `<li data-asset="${escapeHtml(a.name)}"><span class="coach-title">${escapeHtml(a.name)}</span><span class="row-tag">${escapeHtml(a.kind)} · ${size}</span></li>`;
    }).join("");
    Array.from(node.querySelectorAll("li[data-asset]")).forEach((li) => {
      li.addEventListener("click", () => openStudioAsset(li.dataset.asset));
    });
    const select = document.getElementById("studioIconPack");
    if (select && data.icon_packs) {
      select.innerHTML = data.icon_packs.map((p) => `<option value="${escapeHtml(p.key)}">${escapeHtml(p.label)}</option>`).join("");
    }
  } catch (error) {
    node.innerHTML = `<li class="notice error">${escapeHtml(error.message)}</li>`;
  }
}

async function uploadStudioPhoto() {
  const input = document.getElementById("studioPhotoInput");
  const notice = document.getElementById("studioPhotoNotice");
  if (!input || !input.files || !input.files[0]) {
    if (notice) notice.textContent = "Pick a JPG or PNG first.";
    return;
  }
  const file = input.files[0];
  const reader = new FileReader();
  reader.onload = async () => {
    try {
      const result = await api("/api/cv-studio/replace-photo", {
        name: file.name,
        data: reader.result,
      });
      if (result.ok) {
        toast(`Photo updated (${Math.round(result.bytes / 1024)} KB).`);
        if (notice) notice.textContent = "Recompile to see the new photo.";
        loadStudioAssets();
      } else {
        if (notice) notice.textContent = `Failed: ${result.reason}`;
      }
    } catch (error) {
      if (notice) notice.textContent = error.message;
    }
  };
  reader.readAsDataURL(file);
}

async function removeStudioPhoto() {
  if (!window.confirm("Remove the CV photo and comment out \\photo{...} in main.tex?")) return;
  const result = await api("/api/cv-studio/remove-photo", {});
  toast(result.ok ? "Photo removed (backup kept)." : `Failed: ${result.reason}`);
  loadStudioAssets();
}

async function loadStudioGithubProjects() {
  try {
    const data = await api(`/api/cv-studio/asset?name=master_cv.json`);
    if (!data.ok || data.kind !== "text") return;
    let parsed;
    try {
      parsed = JSON.parse(data.text);
    } catch (error) {
      console.debug("Could not parse master_cv.json for project dropdown", error);
      setNotice("studioNotice", "Could not parse master_cv.json, so the project dropdown was not refreshed.", true);
      return;
    }
    const projects = (parsed.projects || []).map((p) => p.name).filter(Boolean);
    const select = document.getElementById("studioGithubProjectSelect");
    if (!select) return;
    select.innerHTML = '<option value="">— select a project —</option>' + projects.map((name) => `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`).join("");
  } catch (error) {
    console.debug("Could not load Studio project list", error);
    setNotice("studioNotice", `Could not load project list: ${error.message}`, true);
  }
}

async function checkSinglePage() {
  const button = document.getElementById("studioSinglePageBtn");
  const target = document.getElementById("studioSinglePageResult");
  const textarea = document.getElementById("studioTextarea");
  if (!target) return;
  setBusy(button, true);
  target.innerHTML = "Compiling and counting pages…";
  try {
    const result = await api("/api/cv-studio/single-page-check", { text: textarea ? textarea.value : null });
    if (!result.ok) {
      target.innerHTML = `<span class="notice error">${escapeHtml(result.reason)}</span>`;
      return;
    }
    if (result.single_page) {
      target.innerHTML = `<span class="badge good">✓ Fits on 1 page (${result.page_count})</span>`;
      return;
    }
    if (result.single_page === null) {
      target.innerHTML = `<span class="muted">Could not count pages — compile succeeded though.</span>`;
      return;
    }
    target.innerHTML = `<div><span class="badge warn">Overflowing (${result.page_count} pages)</span></div>
      <p class="muted" style="margin:0.5rem 0">Try these conservative trims in order:</p>
      <ol class="coach-list">${(result.trims || []).map((t) => `<li>
        <div><span class="coach-title">${escapeHtml(t.title)}</span><span class="coach-sub">${escapeHtml(t.note)} — search for <code>${escapeHtml(t.where)}</code></span></div>
        <strong></strong>
      </li>`).join("")}</ol>`;
  } catch (error) {
    target.innerHTML = `<span class="notice error">${escapeHtml(error.message)}</span>`;
  } finally {
    setBusy(button, false);
  }
}

async function autoFitStudioDraft() {
  const button = document.getElementById("studioAutoFitBtn");
  const target = document.getElementById("studioSinglePageResult");
  const textarea = document.getElementById("studioTextarea");
  if (!textarea || !target) return;
  setBusy(button, true);
  target.innerHTML = "Trying conservative layout tightening...";
  try {
    const result = await api("/api/cv-studio/auto-fit", { text: textarea.value });
    if (!result.ok) {
      target.innerHTML = `<span class="notice error">${escapeHtml(result.reason || result.log || "Auto-fit failed")}</span>`;
      return;
    }
    if (result.changed) {
      textarea.value = result.text || textarea.value;
      textarea.dataset.dirty = "1";
    }
    const stepList = (result.steps || []).map((step) => `<li>${escapeHtml(step)}</li>`).join("");
    target.innerHTML = `<div><span class="badge ${result.single_page ? "good" : "warn"}">${result.single_page ? "Fits after auto-fit" : "Still needs manual trim"}${result.page_count ? ` (${result.page_count} page${result.page_count === 1 ? "" : "s"})` : ""}</span></div>
      <ol class="coach-list" style="margin-top:0.5rem">${stepList}</ol>`;
    toast(result.changed ? "Auto-fit applied to the draft." : "Draft already fits.");
    await studioCompile();
  } catch (error) {
    target.innerHTML = `<span class="notice error">${escapeHtml(error.message)}</span>`;
  } finally {
    setBusy(button, false);
  }
}

async function analyzeStudioAtsKeywords() {
  const button = document.getElementById("studioAtsBtn");
  const textarea = document.getElementById("studioTextarea");
  const role = document.getElementById("studioAtsRole")?.value || "data_scientist";
  const target = document.getElementById("studioAtsResult");
  if (!textarea || !target) return;
  setBusy(button, true);
  target.innerHTML = "Scanning the current draft...";
  try {
    const result = await api("/api/cv-studio/ats-keywords", { text: textarea.value, role });
    if (!result.ok) {
      target.innerHTML = `<span class="notice error">${escapeHtml(result.reason || "ATS scan failed")}</span>`;
      return;
    }
    const chips = (result.present || []).map((kw) => `<span class="chip good">${escapeHtml(kw)}</span>`).join("");
    const missing = (result.missing || []).map((kw) => `<span class="chip warn">${escapeHtml(kw)}</span>`).join("");
    const suggestions = (result.suggestions || []).map((item) => `<li>
      <div><span class="coach-title">${escapeHtml(item.keyword)}</span><span class="coach-sub">${escapeHtml(item.note)} Suggested place: ${escapeHtml(item.where)}.</span></div>
      <strong>gap</strong>
    </li>`).join("");
    target.innerHTML = `
      <div><span class="badge ${result.coverage >= 70 ? "good" : "warn"}">${result.coverage}% coverage</span></div>
      <p class="muted" style="margin:0.5rem 0 0.25rem">Present</p><div class="chips">${chips || "<span class='muted'>None yet.</span>"}</div>
      <p class="muted" style="margin:0.7rem 0 0.25rem">Missing / optional</p><div class="chips">${missing || "<span class='muted'>No obvious gaps.</span>"}</div>
      <ol class="coach-list" style="margin-top:0.7rem">${suggestions}</ol>`;
  } catch (error) {
    target.innerHTML = `<span class="notice error">${escapeHtml(error.message)}</span>`;
  } finally {
    setBusy(button, false);
  }
}

async function analyzeStudioDefensibility() {
  const button = document.getElementById("studioDefensibilityBtn");
  const textarea = document.getElementById("studioTextarea");
  const target = document.getElementById("studioDefensibilityResult");
  if (!textarea || !target) return;
  setBusy(button, true);
  target.innerHTML = "Checking claims against local evidence...";
  try {
    const result = await api("/api/cv-studio/defensibility", { text: textarea.value });
    if (!result.ok) {
      target.innerHTML = `<span class="notice error">${escapeHtml(result.reason || "Defensibility check failed")}</span>`;
      return;
    }
    const badgeClass = result.score >= 85 ? "good" : (result.score >= 65 ? "warn" : "bad");
    const unbacked = (result.unbacked_lines || []).slice(0, 8).map((row) => `<li>
      <div>
        <span class="coach-title">Line ${escapeHtml(row.line)}: ${escapeHtml(row.text)}</span>
        <span class="coach-sub">${escapeHtml(row.reason || "No strong local evidence match found.")}</span>
      </div>
      <strong>fix</strong>
    </li>`).join("");
    const backed = (result.backed_lines || []).slice(0, 5).map((row) => `<span class="chip good" title="line ${escapeHtml(row.line)}">${escapeHtml(row.text.slice(0, 56))}${row.text.length > 56 ? "..." : ""}</span>`).join("");
    target.innerHTML = `
      <div><span class="badge ${badgeClass}">${escapeHtml(result.score)}% defensible</span>
      <span class="muted">${escapeHtml(result.backed)} backed / ${escapeHtml(result.checked)} checked</span></div>
      <p class="muted" style="margin:0.6rem 0 0.25rem">Backed evidence</p>
      <div class="chips">${backed || "<span class='muted'>No claim-like lines detected yet.</span>"}</div>
      <p class="muted" style="margin:0.8rem 0 0.25rem">Needs evidence or softer wording</p>
      <ol class="coach-list" style="margin-top:0.4rem">${unbacked || "<li><div><span class='coach-title'>Everything checked is supported.</span></div><strong>ok</strong></li>"}</ol>`;
  } catch (error) {
    target.innerHTML = `<span class="notice error">${escapeHtml(error.message)}</span>`;
  } finally {
    setBusy(button, false);
  }
}

async function studioApplyReorder() {
  const list = document.getElementById("studioSections");
  const textarea = document.getElementById("studioTextarea");
  const button = document.getElementById("studioReorderApplyBtn");
  if (!list || !textarea) return;
  const order = Array.from(list.querySelectorAll("li")).map((li) => li.dataset.section).filter(Boolean);
  if (!order.length) {
    toast("No reorderable sections.");
    return;
  }
  setBusy(button, true);
  try {
    const result = await api("/api/cv-studio/reorder", { text: textarea.value, order });
    if (result.ok) {
      textarea.value = result.text;
      textarea.dataset.dirty = "1";
      toast("Reorder applied. Click Compile preview to verify.");
    } else {
      setNotice("studioNotice", result.error || "Section reorder failed.", true);
    }
  } catch (error) {
    setNotice("studioNotice", `Section reorder failed: ${error.message}`, true);
  } finally {
    setBusy(button, false);
  }
}

// CV Studio asset/project overrides. These intentionally appear after the
// first Studio helpers so the browser binds the safer split-editor behavior:
// Compile preview always reads #studioTextarea, while assets use
// #studioAssetTextarea.
async function openStudioAsset(name) {
  if (!name) return;
  state.studioActiveAsset = name;
  state.studioActiveAssetKind = null;
  const status = document.getElementById("studioAssetActive");
  const assetEditor = document.getElementById("studioAssetTextarea");
  const assetPreview = document.getElementById("studioAssetPreview");
  const assetSave = document.getElementById("studioAssetSaveBtn");
  if (status) status.textContent = `Editing ${name}`;
  if (assetEditor) {
    assetEditor.value = "";
    assetEditor.classList.add("hidden");
    delete assetEditor.dataset.dirty;
  }
  if (assetPreview) {
    assetPreview.classList.remove("hidden");
    assetPreview.textContent = "Loading asset...";
  }
  try {
    const data = await api(`/api/cv-studio/asset?name=${encodeURIComponent(name)}`);
    if (!data.ok) {
      toast(`Could not open ${name}: ${data.reason}`);
      return;
    }
    state.studioActiveAssetKind = data.kind;
    if (data.kind === "text") {
      if (assetEditor) {
        assetEditor.value = data.text || "";
        assetEditor.classList.remove("hidden");
        assetEditor.dataset.dirty = "";
      }
      if (assetPreview) {
        const isMainTex = name.toLowerCase() === "main.tex";
        assetPreview.innerHTML = isMainTex
          ? "This is your source CV. Inspect or edit it here; Compile preview still renders the LaTeX draft above."
          : "Text asset loaded below. This side editor is intentionally separate from the CV preview draft.";
      }
      if (assetSave) assetSave.disabled = false;
      toast(`Loaded ${name} in the asset editor.`);
    } else {
      if (assetSave) assetSave.disabled = true;
      const url = data.url || "";
      if (assetPreview) {
        const lower = name.toLowerCase();
        assetPreview.innerHTML = lower.endsWith(".pdf")
          ? `<iframe src="${escapeHtml(url)}" title="${escapeHtml(name)} preview"></iframe>`
          : `<img src="${escapeHtml(url)}" alt="${escapeHtml(name)} preview" />`;
      }
      toast(`${name} is preview-only here.`);
    }
  } catch (error) {
    toast(error.message);
  }
}

async function saveStudioAsset() {
  const name = state.studioActiveAsset;
  if (!name) {
    toast("Open an asset from the list first.");
    return;
  }
  if (state.studioActiveAssetKind !== "text") {
    toast("This asset is not text-editable.");
    return;
  }
  const textarea = document.getElementById("studioAssetTextarea");
  try {
    const result = await api("/api/cv-studio/asset-save", { name, text: textarea ? textarea.value : "" });
    if (result.ok) {
      toast(`Saved ${name}.`);
      if (textarea) delete textarea.dataset.dirty;
      if (name.toLowerCase() === "main.tex") {
        const draft = document.getElementById("studioTextarea");
        if (draft && !draft.dataset.dirty) draft.value = textarea ? textarea.value : "";
        await loadStudio();
      }
    } else {
      toast(`Could not save: ${result.reason}`);
    }
  } catch (error) {
    toast(error.message);
  }
}

async function applyIconPack() {
  const select = document.getElementById("studioIconPack");
  const notice = document.getElementById("studioIconPackNotice");
  if (!select) return;
  try {
    const result = await api("/api/cv-studio/icon-pack", { pack: select.value });
    if (result.ok) {
      if (notice) notice.textContent = `Applied ${result.label}. Compiling preview…`;
      toast("Icon pack updated.");
      const ta = document.getElementById("studioTextarea");
      if (ta && result.text) {
        ta.value = result.text;
        ta.dataset.dirty = "1";
      } else if (ta) {
        delete ta.dataset.dirty;
        await loadStudio();
      }
      await loadStudioAssets();
      // Recompile immediately so the icons actually show up. A failed compile
      // usually means the pack's LaTeX package is missing locally.
      try {
        await studioCompile();
        if (notice) notice.textContent = `Applied ${result.label}. Preview updated.`;
      } catch (compileError) {
        if (notice) notice.textContent =
          `Applied ${result.label}, but the preview failed to compile: ${compileError.message}. ` +
          `If the error mentions a missing package (e.g. fontawesome5), install it via MiKTeX Console → Packages.`;
      }
    } else if (notice) {
      notice.textContent = `Failed: ${result.reason}`;
    }
  } catch (error) {
    if (notice) notice.textContent = error.message;
  }
}

async function applyKeyProjects() {
  const select = document.getElementById("studioKeyProjectsCount");
  const notice = document.getElementById("studioKeyProjectsNotice");
  const button = document.getElementById("studioKeyProjectsApplyBtn");
  if (!select) return;
  setBusy(button, true);
  try {
    const result = await api("/api/cv-studio/key-projects", { count: Number(select.value) });
    if (!result.ok) {
      if (notice) notice.textContent = `Failed: ${result.reason}`;
      return;
    }
    const ta = document.getElementById("studioTextarea");
    if (ta && result.text) {
      ta.value = result.text;
      ta.dataset.dirty = "1";
    }
    if (notice) notice.textContent = `Packed ${result.count} project(s): ${(result.projects || []).join(", ")}. Checking page count…`;
    toast(`Key projects: ${result.count}`);
    await studioCompile();
    // More projects = tighter space; run the one-page guard automatically.
    await checkSinglePage();
  } catch (error) {
    if (notice) notice.textContent = error.message;
  } finally {
    setBusy(button, false);
  }
}

async function importGithubProject() {
  const select = document.getElementById("studioGithubProjectSelect");
  const notice = document.getElementById("studioGithubNotice");
  if (!select || !select.value) {
    if (notice) notice.textContent = "Pick a project first.";
    return;
  }
  try {
    const result = await api("/api/cv-studio/import-github-project", { name: select.value });
    if (result.ok) {
      if (notice) notice.textContent = result.draft_updated
        ? `Promoted "${result.promoted}" and updated the preview draft. Compile to see it.`
        : `Promoted "${result.promoted}" to top of projects. ${result.note || ""}`;
      toast("Project promoted.");
      if (result.text) {
        const ta = document.getElementById("studioTextarea");
        if (ta) {
          ta.value = result.text;
          ta.dataset.dirty = "1";
        }
        renderStudioSections(state.studio?.sections || []);
      }
      await loadStudioGithubProjects();
      if (state.studioActiveAsset === "master_cv.json") await openStudioAsset("master_cv.json");
    } else if (notice) {
      notice.textContent = `Failed: ${result.reason}`;
    }
  } catch (error) {
    if (notice) notice.textContent = error.message;
  }
}

function fillDeepLearningProjectTemplate() {
  const set = (id, value) => {
    const node = document.getElementById(id);
    if (node) node.value = value;
  };
  set("studioProjectName", "DSTI Deep Learning AG News Classifier");
  set("studioProjectUrl", "https://github.com/fractalical/dsti-deep-learning");
  set("studioProjectTech", "Python, Jupyter Notebook, Transformers, DistilBERT, RoBERTa, scikit-learn, NLP, Deep Learning");
  set("studioProjectDescription", "Deep learning group project for AG News topic classification comparing classical baselines with transformer-based models.");
  set("studioProjectBullets", [
    "Owned the model-development and training workflow for transformer-based text classification experiments.",
    "Compared TF-IDF + Logistic Regression baselines against DistilBERT and RoBERTa improvements.",
    "Tracked accuracy, macro-F1, configuration snapshots, predictions, and reproducible run artefacts."
  ].join("\n"));
}

async function saveStudioProject() {
  const notice = document.getElementById("studioGithubNotice");
  const read = (id) => (document.getElementById(id)?.value || "").trim();
  const name = read("studioProjectName");
  if (!name) {
    if (notice) notice.textContent = "Project name is required.";
    return;
  }
  const technologies = read("studioProjectTech").split(",").map((x) => x.trim()).filter(Boolean);
  const bullet_points = read("studioProjectBullets").split(/\r?\n/).map((x) => x.trim()).filter(Boolean);
  try {
    const result = await api("/api/cv-studio/project-save", {
      name,
      url: read("studioProjectUrl"),
      description: read("studioProjectDescription"),
      technologies,
      bullet_points,
      promote: true,
    });
    if (result.ok) {
      if (notice) notice.textContent = `Saved "${result.project?.name || name}" locally and promoted it.`;
      toast("Project saved to local profile.");
      if (result.text) {
        const ta = document.getElementById("studioTextarea");
        if (ta) {
          ta.value = result.text;
          ta.dataset.dirty = "1";
        }
      }
      await loadStudioGithubProjects();
      if (state.studioActiveAsset === "master_cv.json") await openStudioAsset("master_cv.json");
    } else if (notice) {
      notice.textContent = `Failed: ${result.reason}`;
    }
  } catch (error) {
    if (notice) notice.textContent = error.message;
  }
}

// ===== Portfolio Builder =====

  // ---- event bindings (moved from bindEvents) ----
  // Studio v2 hooks
  const studioAssetReloadBtn = document.getElementById("studioAssetReloadBtn");
  if (studioAssetReloadBtn) studioAssetReloadBtn.addEventListener("click", loadStudioAssets);
  const studioAssetSaveBtn = document.getElementById("studioAssetSaveBtn");
  if (studioAssetSaveBtn) studioAssetSaveBtn.addEventListener("click", saveStudioAsset);
  const studioPhotoUploadBtn = document.getElementById("studioPhotoUploadBtn");
  if (studioPhotoUploadBtn) studioPhotoUploadBtn.addEventListener("click", uploadStudioPhoto);
  const studioPhotoRemoveBtn = document.getElementById("studioPhotoRemoveBtn");
  if (studioPhotoRemoveBtn) studioPhotoRemoveBtn.addEventListener("click", removeStudioPhoto);
  const studioIconPackApplyBtn = document.getElementById("studioIconPackApplyBtn");
  if (studioIconPackApplyBtn) studioIconPackApplyBtn.addEventListener("click", applyIconPack);
  const studioGithubImportBtn = document.getElementById("studioGithubImportBtn");
  if (studioGithubImportBtn) studioGithubImportBtn.addEventListener("click", importGithubProject);
  const studioSinglePageBtn = document.getElementById("studioSinglePageBtn");
  if (studioSinglePageBtn) studioSinglePageBtn.addEventListener("click", checkSinglePage);
  const studioAutoFitBtn = document.getElementById("studioAutoFitBtn");
  if (studioAutoFitBtn) studioAutoFitBtn.addEventListener("click", autoFitStudioDraft);
  const studioAtsBtn = document.getElementById("studioAtsBtn");
  if (studioAtsBtn) studioAtsBtn.addEventListener("click", analyzeStudioAtsKeywords);
  const studioDefensibilityBtn = document.getElementById("studioDefensibilityBtn");
  if (studioDefensibilityBtn) studioDefensibilityBtn.addEventListener("click", analyzeStudioDefensibility);
  const studioAssetTextarea = document.getElementById("studioAssetTextarea");
  if (studioAssetTextarea) studioAssetTextarea.addEventListener("input", () => { studioAssetTextarea.dataset.dirty = "1"; });
  const studioProjectAddBtn = document.getElementById("studioProjectAddBtn");
  if (studioProjectAddBtn) studioProjectAddBtn.addEventListener("click", saveStudioProject);
  const studioProjectDeepLearningBtn = document.getElementById("studioProjectDeepLearningBtn");
  if (studioProjectDeepLearningBtn) studioProjectDeepLearningBtn.addEventListener("click", fillDeepLearningProjectTemplate);

  const studioKeyProjectsBtn = document.getElementById("studioKeyProjectsApplyBtn");
  if (studioKeyProjectsBtn) studioKeyProjectsBtn.addEventListener("click", applyKeyProjects);
  const studioReorderApplyBtn = document.getElementById("studioReorderApplyBtn");
  if (studioReorderApplyBtn) studioReorderApplyBtn.addEventListener("click", studioApplyReorder);

  window.JobAgentStudioTools = {
    loadAssets: loadStudioAssets,
    loadGithubProjects: loadStudioGithubProjects,
  };
})();
