/* Feature panels for the new backend APIs: STAR Story Bank editor (Career
   Coach tab) and Discover Boards (Search tab). Uses app.js globals. */
(function () {
  const $ = (id) => document.getElementById(id);
  const esc = (value) => window.escapeHtml(String(value ?? ""));

  // -- Story bank -------------------------------------------------------------

  let stories = [];

  function storyExcerpt(story) {
    return [story.situation, story.action, story.result].filter(Boolean).join(" — ");
  }

  function renderStories() {
    const grid = $("storyGrid");
    if (!grid) return;
    if (!stories.length) {
      grid.innerHTML = `<div class="empty-state" style="grid-column:1/-1">
        <span class="empty-glyph">★</span>
        <strong>No stories yet</strong>
        Click "Seed from CV" to build grounded STAR stories from your master CV, or add one manually.
      </div>`;
      return;
    }
    grid.innerHTML = stories.map((story) => `
      <article class="story-card" data-story="${esc(story.id)}">
        <h4>${esc(story.title)}</h4>
        <div class="story-skills">${(story.skills || []).slice(0, 6).map((skill) => `<span class="row-tag">${esc(skill)}</span>`).join("")}</div>
        <p class="story-excerpt">${esc(storyExcerpt(story)) || "<em>Empty — click Edit to fill the STAR fields.</em>"}</p>
        <div class="story-actions">
          <button class="ghost" data-story-edit="${esc(story.id)}">Edit</button>
          <button class="ghost" data-story-delete="${esc(story.id)}">Delete</button>
        </div>
      </article>`).join("");
  }

  async function loadStories() {
    try {
      const payload = await window.api("/api/stories");
      stories = payload.stories || [];
      renderStories();
    } catch (error) {
      window.setNotice("storyNotice", error.message, true);
    }
  }

  async function syncStories() {
    const button = $("storySyncBtn");
    window.setBusy(button, true);
    try {
      const payload = await window.api("/api/story-sync", {});
      window.toast(payload.added ? `Seeded ${payload.added} new stor${payload.added === 1 ? "y" : "ies"} from your CV.` : "Story bank already up to date.");
      await loadStories();
    } catch (error) {
      window.setNotice("storyNotice", error.message, true);
    } finally {
      window.setBusy(button, false);
    }
  }

  function openStoryModal(story = null) {
    $("storyModalTitle").textContent = story ? "Edit story" : "Add story";
    $("storyId").value = story?.id || "";
    $("storyTitle").value = story?.title || "";
    $("storySkills").value = (story?.skills || []).join(", ");
    $("storySituation").value = story?.situation || "";
    $("storyTask").value = story?.task || "";
    $("storyAction").value = story?.action || "";
    $("storyResult").value = story?.result || "";
    $("storyReflection").value = story?.reflection || "";
    $("storyModal").classList.remove("hidden");
    $("storyTitle").focus();
  }

  function closeStoryModal() {
    $("storyModal").classList.add("hidden");
  }

  async function saveStory() {
    const button = $("storySaveBtn");
    const payload = {
      id: $("storyId").value || undefined,
      title: $("storyTitle").value.trim(),
      skills: $("storySkills").value.split(",").map((skill) => skill.trim()).filter(Boolean),
      situation: $("storySituation").value,
      task: $("storyTask").value,
      action: $("storyAction").value,
      result: $("storyResult").value,
      reflection: $("storyReflection").value,
    };
    if (!payload.title) {
      window.toast("A story needs a title.");
      return;
    }
    window.setBusy(button, true);
    try {
      await window.api("/api/story-save", payload);
      closeStoryModal();
      window.toast("Story saved.");
      await loadStories();
    } catch (error) {
      window.setNotice("storyNotice", error.message, true);
    } finally {
      window.setBusy(button, false);
    }
  }

  async function deleteStory(storyId) {
    try {
      await window.api("/api/story-delete", { id: storyId });
      window.toast("Story deleted.");
      await loadStories();
    } catch (error) {
      window.setNotice("storyNotice", error.message, true);
    }
  }

  function bindStories() {
    if (!$("storyBankPanel")) return;
    $("storyAddBtn").addEventListener("click", () => openStoryModal());
    $("storySyncBtn").addEventListener("click", syncStories);
    $("storyModalClose").addEventListener("click", closeStoryModal);
    $("storyCancelBtn").addEventListener("click", closeStoryModal);
    $("storySaveBtn").addEventListener("click", saveStory);
    $("storyGrid").addEventListener("click", (event) => {
      const edit = event.target.closest("[data-story-edit]");
      if (edit) {
        openStoryModal(stories.find((story) => story.id === edit.dataset.storyEdit));
        return;
      }
      const remove = event.target.closest("[data-story-delete]");
      if (remove) deleteStory(remove.dataset.storyDelete);
    });
    // Load lazily when the coach tab first activates (and once now if active).
    const original = window.activateTab;
    window.activateTab = function patchedActivateTabStories(name) {
      original(name);
      if (name === "coach") loadStories();
    };
  }

  // -- Discover boards ---------------------------------------------------------

  const FRENCH_PACK = [
    "Doctolib", "BlaBlaCar", "Back Market", "Qonto", "Alan",
    "PayFit", "Dataiku", "Hugging Face", "Mirakl", "Contentsquare",
  ];

  function boardRow(board) {
    return `<div class="board-hit">
      <strong>${esc(board.company)}</strong>
      <span class="muted">${esc(board.slug)}</span>
      <span class="board-source">${esc(board.source)}</span>
    </div>`;
  }

  async function discoverBoards() {
    const button = $("discoverBoardsBtn");
    const companies = $("discoverCompaniesInput").value.split(/\n|,/).map((name) => name.trim()).filter(Boolean);
    if (!companies.length) {
      window.setNotice("discoverNotice", "Add at least one company (or click the French tech pack).", true);
      return;
    }
    window.setBusy(button, true);
    window.setNotice("discoverNotice", `Probing free ATS APIs for ${Math.min(10, companies.length)} compan${companies.length === 1 ? "y" : "ies"}… this can take a minute.`);
    try {
      const payload = await window.api("/api/discover-boards", { companies }, "POST", 300000);
      window.setNotice("discoverNotice", `Checked ${payload.companies_checked} — found ${payload.boards_found} board(s).`);
      $("discoverResults").innerHTML = (payload.boards || []).map(boardRow).join("")
        || `<div class="empty-state"><span class="empty-glyph">◇</span><strong>No boards found</strong>Misses are cached for a week; try other companies.</div>`;
    } catch (error) {
      window.setNotice("discoverNotice", error.message, true);
    } finally {
      window.setBusy(button, false);
    }
  }

  async function showRegistry() {
    try {
      const payload = await window.api("/api/company-boards");
      const boards = payload.boards || [];
      $("discoverResults").innerHTML = boards.length
        ? `<p class="muted" style="margin:0 0 0.4rem">${boards.length} saved board(s):</p>` + boards.map(boardRow).join("")
        : `<div class="empty-state"><span class="empty-glyph">◇</span><strong>No saved boards yet</strong>Run a discovery to build your local registry.</div>`;
    } catch (error) {
      window.setNotice("discoverNotice", error.message, true);
    }
  }

  function bindDiscover() {
    if (!$("discoverBoardsPanel")) return;
    $("discoverBoardsBtn").addEventListener("click", discoverBoards);
    $("discoverPackBtn").addEventListener("click", () => {
      $("discoverCompaniesInput").value = FRENCH_PACK.join("\n");
    });
    $("discoverRegistryBtn").addEventListener("click", showRegistry);
  }

  bindStories();
  bindDiscover();
  window.JobAgentFeatures = { loadStories, syncStories };
})();
