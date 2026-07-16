/* Small controls for CLI capabilities that had no direct dashboard surface. */
(function () {
  const $ = (id) => document.getElementById(id);
  const esc = (value) => window.escapeHtml(String(value ?? ""));

  async function importProfile() {
    const input = $("profileImportFile");
    const file = input?.files?.[0];
    if (!file) { window.toast("Choose a JSON Resume or LinkedIn export ZIP first."); return; }
    if (file.size > 10 * 1024 * 1024) { window.toast("Profile import must be 10 MB or smaller."); return; }
    const button = $("profileImportBtn");
    button.disabled = true;
    try {
      const bytes = new Uint8Array(await file.arrayBuffer());
      let binary = "";
      for (let offset = 0; offset < bytes.length; offset += 0x8000) {
        binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000));
      }
      const result = await window.api("/api/profile-import", {
        filename: file.name, content_base64: btoa(binary),
      });
      window.toast(`Imported ${result.stored} new evidence item(s) from ${result.parsed} parsed.`);
      if (window.JobAgentProfileEditor) window.JobAgentProfileEditor.load();
    } catch (error) {
      window.toast(`Profile import failed: ${error.message}`);
    } finally {
      button.disabled = false;
    }
  }

  async function showFranceTargets() {
    const node = $("franceTargetsResults");
    node.innerHTML = '<div class="empty-state"><strong>Loading company targets…</strong></div>';
    try {
      const payload = await window.api("/api/france-targets?limit=40");
      node.innerHTML = (payload.targets || []).map((target) => `
        <article class="result-card">
          <div><strong>${esc(target.company)}</strong><div class="muted">${esc(target.sector)}</div></div>
          <a class="button-link" href="${window.safeHref(target.url)}" target="_blank" rel="noreferrer">Careers ↗</a>
        </article>`).join("") || '<div class="empty-state">No targets available.</div>';
    } catch (error) {
      node.innerHTML = `<div class="notice">Could not load targets: ${esc(error.message)}</div>`;
    }
  }

  $("profileImportBtn")?.addEventListener("click", importProfile);
  $("franceTargetsBtn")?.addEventListener("click", showFranceTargets);
  window.JobAgentFeatureSurfaces = { importProfile, showFranceTargets };
})();
