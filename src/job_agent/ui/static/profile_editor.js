/* My Profile tab — edit the local candidate facts (candidate_profile.json)
   that drive scoring, packet generation, and screening answers. The full
   profile object round-trips through the form, so fields the form doesn't
   surface are preserved verbatim. Uses app.js globals. */
(function () {
  const $ = (id) => document.getElementById(id);
  const esc = (value) => window.escapeHtml(String(value ?? ""));

  let profile = null;   // the live object being edited
  let loaded = false;

  // ── tiny form builders ──────────────────────────────────────────────────────

  function textField(id, label, value, placeholder = "", hint = "") {
    return `<label>${esc(label)}
      <input id="pf_${id}" value="${esc(value ?? "")}" placeholder="${esc(placeholder)}" autocomplete="off" />
      ${hint ? `<span class="muted" style="font-size:0.75rem">${esc(hint)}</span>` : ""}
    </label>`;
  }

  function numberField(id, label, value, hint = "") {
    return `<label>${esc(label)}
      <input id="pf_${id}" type="number" value="${value ?? ""}" />
      ${hint ? `<span class="muted" style="font-size:0.75rem">${esc(hint)}</span>` : ""}
    </label>`;
  }

  function checkField(id, label, value, hint = "") {
    return `<label class="check-row" ${hint ? `title="${esc(hint)}"` : ""}>
      <input id="pf_${id}" type="checkbox" ${value ? "checked" : ""} /> ${esc(label)}
    </label>`;
  }

  function chipEditor(id, label, values, hint) {
    const chips = (values || []).map((value, index) => `
      <span class="chip">${esc(value)}<button type="button" class="chip-x" data-chip-remove="${id}" data-index="${index}" aria-label="Remove ${esc(value)}">&times;</button></span>`).join("");
    return `<div class="pf-chips-block">
      <label style="margin-bottom:0.25rem">${esc(label)}</label>
      <div class="chips" data-chip-list="${id}">${chips}</div>
      <div class="action-row" style="margin-top:0.35rem">
        <input data-chip-input="${id}" placeholder="Type and press Enter to add" style="max-width:20rem" />
      </div>
      ${hint ? `<span class="muted" style="font-size:0.75rem">${esc(hint)}</span>` : ""}
    </div>`;
  }

  // ── render ──────────────────────────────────────────────────────────────────

  function render() {
    const form = $("profileFactsForm");
    if (!form || !profile) return;
    const contact = profile.contact || {};
    form.innerHTML = `
      <div class="split">
        <section class="panel">
          <h3>Contact</h3>
          <div class="control-grid compact">
            ${textField("name", "Full name", contact.name)}
            ${textField("email", "Email", contact.email)}
            ${textField("phone", "Phone", contact.phone)}
            ${textField("location", "Location", contact.location, "Paris, France")}
            ${textField("linkedin_url", "LinkedIn URL", contact.linkedin_url)}
            ${textField("github_url", "GitHub URL", contact.github_url)}
            ${textField("portfolio_url", "Portfolio URL", contact.portfolio_url)}
            ${textField("availability", "Availability", contact.availability, "e.g. from 2026-09, 6 months")}
          </div>
        </section>
        <section class="panel">
          <h3>Targeting</h3>
          ${chipEditor("target_roles", "Target roles", profile.target_roles, "Used for title matching in the fit score.")}
          ${chipEditor("target_locations", "Target locations", profile.target_locations, "Used for location matching.")}
          <div class="control-grid compact" style="margin-top:0.5rem">
            ${checkField("remote_ok", "Remote OK", profile.remote_ok)}
            ${checkField("hybrid_ok", "Hybrid OK", profile.hybrid_ok)}
            ${checkField("onsite_ok", "On-site OK", profile.onsite_ok)}
            ${checkField("relocation_ok", "Relocation OK", profile.relocation_ok)}
            ${numberField("min_fit_score", "Min fit score (apply threshold)", profile.min_fit_score)}
          </div>
        </section>
      </div>
      <div class="split">
        <section class="panel">
          <h3>Skills</h3>
          ${chipEditor("skills", "Skills", (profile.skills || []).map((s) => s.name), "Drives the 38% skill-match component. Removing a chip removes the skill fact.")}
        </section>
        <section class="panel">
          <h3>Languages &amp; salary</h3>
          ${chipEditor("languages", "Languages you speak", profile.languages, "French here is what lifts the FRENCH_REQUIRED cap — only add languages you actually speak.")}
          <div class="control-grid compact" style="margin-top:0.5rem">
            ${numberField("salary_min", "Salary min (EUR/yr)", profile.salary_min, "Leave empty for no preference.")}
            ${numberField("salary_max", "Salary max (EUR/yr)", profile.salary_max)}
          </div>
        </section>
      </div>
      <section class="panel">
        <div class="panel-header-row">
          <h3>Work authorization &amp; contract facts</h3>
          <span class="badge warn">Facts only — never guess</span>
        </div>
        <p class="muted" style="margin-top:0.2rem">These drive work-authorization routing, sponsorship caps, and locked screening answers. Enter only what is factually true for you; blank is always safer than a guess.</p>
        <div class="control-grid compact">
          ${textField("work_auth_status", "Work authorization status", profile.work_auth_status, "", "Free text, e.g. 'student visa with titre de séjour'")}
          ${textField("visa_expiry", "Visa / permit expiry", profile.visa_expiry, "YYYY-MM-DD")}
          ${checkField("can_do_stage", "Can do a stage (internship)", profile.can_do_stage)}
          ${checkField("convention_de_stage_available", "Convention de stage available", profile.convention_de_stage_available)}
          ${checkField("needs_sponsorship_for_cdi", "Needs sponsorship for CDI", profile.needs_sponsorship_for_cdi)}
        </div>
      </section>`;
    bindChips();
  }

  // ── chip editing (mutates the live profile object) ──────────────────────────

  function chipValues(id) {
    if (id === "skills") return (profile.skills || []).map((s) => s.name);
    return profile[id] || [];
  }

  function addChip(id, value) {
    const clean = value.trim();
    if (!clean) return;
    if (id === "skills") {
      profile.skills = profile.skills || [];
      if (!profile.skills.some((s) => s.name.toLowerCase() === clean.toLowerCase())) {
        profile.skills.push({ name: clean, category: "general" });
      }
    } else {
      profile[id] = profile[id] || [];
      if (!profile[id].some((v) => String(v).toLowerCase() === clean.toLowerCase())) {
        profile[id].push(clean);
      }
    }
    render();
    const input = document.querySelector(`[data-chip-input="${id}"]`);
    if (input) input.focus();
  }

  function removeChip(id, index) {
    if (id === "skills") profile.skills.splice(index, 1);
    else profile[id].splice(index, 1);
    render();
  }

  function bindChips() {
    document.querySelectorAll("[data-chip-input]").forEach((input) => {
      input.addEventListener("keydown", (event) => {
        if (event.key !== "Enter") return;
        event.preventDefault();
        addChip(input.dataset.chipInput, input.value);
      });
    });
  }

  // ── load / save ─────────────────────────────────────────────────────────────

  function readFormIntoProfile() {
    const contact = profile.contact || (profile.contact = {});
    const text = (id) => ($(`pf_${id}`) ? $(`pf_${id}`).value.trim() : "");
    const num = (id) => {
      const raw = $(`pf_${id}`) ? $(`pf_${id}`).value.trim() : "";
      return raw === "" ? null : Number(raw);
    };
    const bool = (id) => Boolean($(`pf_${id}`)?.checked);
    contact.name = text("name");
    contact.email = text("email");
    contact.phone = text("phone") || null;
    contact.location = text("location") || null;
    contact.linkedin_url = text("linkedin_url") || null;
    contact.github_url = text("github_url") || null;
    contact.portfolio_url = text("portfolio_url") || null;
    contact.availability = text("availability") || null;
    profile.remote_ok = bool("remote_ok");
    profile.hybrid_ok = bool("hybrid_ok");
    profile.onsite_ok = bool("onsite_ok");
    profile.relocation_ok = bool("relocation_ok");
    profile.min_fit_score = num("min_fit_score") ?? profile.min_fit_score;
    profile.salary_min = num("salary_min");
    profile.salary_max = num("salary_max");
    profile.work_auth_status = text("work_auth_status");
    profile.visa_expiry = text("visa_expiry") || null;
    profile.can_do_stage = bool("can_do_stage");
    profile.convention_de_stage_available = bool("convention_de_stage_available");
    profile.needs_sponsorship_for_cdi = bool("needs_sponsorship_for_cdi");
  }

  async function load() {
    try {
      const payload = await window.api("/api/profile-facts");
      profile = payload.profile;
      loaded = true;
      render();
    } catch (error) {
      window.setNotice("profileFactsNotice", error.message, true);
    }
  }

  async function save() {
    if (!profile) return;
    const button = $("profileFactsSaveBtn");
    readFormIntoProfile();
    window.setBusy(button, true);
    window.setNotice("profileFactsNotice", "");
    try {
      const result = await window.api("/api/profile-facts", { profile });
      window.toast(result.evidence_rebuilt
        ? "Profile saved — evidence store rebuilt."
        : "Profile saved (evidence rebuild skipped — check logs).");
      window.setNotice("profileFactsNotice", `Saved. Backup: ${result.backup}`);
      // Scoring/readiness badges depend on these facts.
      window.loadState();
    } catch (error) {
      window.setNotice("profileFactsNotice", error.message, true);
    } finally {
      window.setBusy(button, false);
    }
  }

  function bind() {
    if (!$("profileFactsForm")) return;
    $("profileFactsSaveBtn").addEventListener("click", save);
    $("profileFactsReloadBtn").addEventListener("click", load);
    $("profileFactsForm").addEventListener("click", (event) => {
      const remove = event.target.closest("[data-chip-remove]");
      if (remove) {
        readFormIntoProfile();
        removeChip(remove.dataset.chipRemove, Number(remove.dataset.index));
      }
    });
    const original = window.activateTab;
    window.activateTab = function patchedActivateTabProfile(name) {
      original(name);
      if (name === "myprofile" && !loaded) load();
    };
  }

  bind();
  window.JobAgentProfileEditor = { load };
})();
