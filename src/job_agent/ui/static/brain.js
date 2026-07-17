/* Brain tab controller: live graph loading, controls, and factual node details. */
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const esc = (value) => window.escapeHtml(String(value ?? ""));
  let graph = { nodes: [], edges: [], truncated: false, total_nodes: 0, total_edges: 0 };
  let renderer = null, loaded = false, loading = null;

  function node(id) { return graph.nodes.find((item) => item.id === id); }
  function edges(type, id, side) { return graph.edges.filter((edge) => edge.type === type && edge[side] === id); }
  function score(value) { return value === null || value === undefined ? "Not scored" : `${Math.round(value)}/100`; }
  function list(items, empty) {
    return items.length ? `<ul class="brain-detail-list">${items.map((item) => `<li>${item}</li>`).join("")}</ul>` : `<p class="muted">${esc(empty)}</p>`;
  }
  function heading(item) {
    return `<span class="brain-type ${esc(item.type)}">${esc(item.type)}</span><h3>${esc(item.label)}</h3>`;
  }
  function evidenceForSkillIds(skillIds) {
    const ids = new Set(graph.edges.filter((edge) => edge.type === "proves" && skillIds.has(edge.target)).map((edge) => edge.source));
    return [...ids].map(node).filter(Boolean);
  }

  function renderJob(item) {
    const skillIds = new Set(edges("requires", item.id, "source").map((edge) => edge.target));
    const skills = [...skillIds].map(node).filter(Boolean);
    const evidence = evidenceForSkillIds(skillIds);
    return `${heading(item)}
      <div class="brain-score-pair"><div><span>Fit score</span><strong>${score(item.meta.fit_score)}</strong></div>
      <div><span>Search quality</span><strong>${score(item.meta.search_quality_score)}</strong></div></div>
      <h4>Required skills</h4>${list(skills.map((skill) => `<button class="brain-node-link" data-node="${esc(skill.id)}">${esc(skill.label)}</button>`), "No extracted tech stack is stored for this job.")}
      <h4>Evidence backing this fit</h4>${list(evidence.map((proof) => `<button class="brain-node-link" data-node="${esc(proof.id)}">${esc(proof.label)}</button><span class="muted"> · ${esc(proof.meta.kind)}</span>`), "No stored evidence entry matches this job's extracted skills.")}`;
  }

  function renderSkill(item) {
    const jobs = edges("requires", item.id, "target").map((edge) => node(edge.source)).filter(Boolean);
    const proofs = edges("proves", item.id, "target").map((edge) => node(edge.source)).filter(Boolean);
    const claims = proofs.filter((proof) => proof.meta.is_claim);
    return `${heading(item)}
      <div class="brain-score-pair"><div><span>Evidence entries</span><strong>${proofs.length}</strong></div>
      <div><span>Profile/CV claims</span><strong>${claims.length}</strong></div></div>
      <h4>Jobs requiring it</h4>${list(jobs.map((job) => `<button class="brain-node-link" data-node="${esc(job.id)}">${esc(job.label)}</button><span class="muted"> · ${esc(job.meta.company)}</span>`), "No retained job relation.")}
      <h4>Stored proof</h4>${list(proofs.map((proof) => `<button class="brain-node-link" data-node="${esc(proof.id)}">${esc(proof.label)}</button><span class="muted"> · ${esc(proof.meta.source)}</span>`), "This is required by jobs but has no matching local evidence.")}`;
  }

  function renderCompany(item) {
    const jobs = edges("at", item.id, "target").map((edge) => node(edge.source)).filter(Boolean);
    return `${heading(item)}<h4>Tracked jobs</h4>${list(jobs.map((job) => `<button class="brain-node-link" data-node="${esc(job.id)}">${esc(job.label)}</button>`), "No retained job relation.")}`;
  }

  function renderEvidence(item) {
    const skills = edges("proves", item.id, "source").map((edge) => node(edge.target)).filter(Boolean);
    const positionNote = item.meta.position_source === "stable_seed_no_relations"
      ? `<p class="brain-honesty">No computable relations; this node uses a stable fallback position.</p>` : "";
    return `${heading(item)}<dl class="brain-meta"><dt>Kind</dt><dd>${esc(item.meta.kind)}</dd><dt>Source</dt><dd>${esc(item.meta.source)}</dd><dt>Confidence</dt><dd>${Math.round(item.meta.confidence * 100)}%</dd></dl>
      ${item.meta.value ? `<p>${esc(item.meta.value)}</p>` : ""}<h4>Skills supported</h4>
      ${list(skills.map((skill) => `<button class="brain-node-link" data-node="${esc(skill.id)}">${esc(skill.label)}</button>`), "No extracted job skill matches this evidence text.")}${positionNote}`;
  }

  function selectNode(id) {
    const item = node(id); if (!item) return;
    renderer?.select(id);
    const renderers = { job: renderJob, skill: renderSkill, company: renderCompany, evidence: renderEvidence };
    $("brainDetails").innerHTML = renderers[item.type](item);
  }

  function syncOrbit(values) {
    $("brainYaw").value = String(Math.round(values.yaw));
    $("brainPitch").value = String(Math.round(values.pitch));
    $("brainZoom").value = String(Math.round(values.zoom * 100));
  }

  function ensureRenderer() {
    if (!renderer) renderer = window.JobAgentBrainGraph.create($("brainCanvas"), { onSelect: selectNode, onOrbit: syncOrbit });
    return renderer;
  }

  async function load(force = false) {
    if (loaded && !force) { ensureRenderer().setVisible(true); return graph; }
    if (loading) return loading;
    $("brainGraphStats").textContent = "Loading graph…";
    loading = window.api("/api/graph").then((payload) => {
      graph = payload; loaded = true; ensureRenderer().setData(graph);
      const empty = graph.nodes.length === 0;
      $("brainEmpty").hidden = !empty; $("brainCanvas").hidden = empty;
      $("brainGraphStats").textContent = empty ? "0 nodes · fresh local database" : `${graph.nodes.length} nodes · ${graph.edges.length} relations${graph.truncated ? ` · showing top ${graph.nodes.length} of ${graph.total_nodes}` : ""}`;
      return graph;
    }).catch((error) => {
      if (error instanceof TypeError) {
        window.renderConnectionLost("brainGraphStats", () => load(true));
        return graph;
      }
      $("brainGraphStats").textContent = `Graph unavailable: ${error.message}`; throw error;
    }).finally(() => { loading = null; });
    return loading;
  }

  function savedMode() {
    try {
      const saved = localStorage.getItem("job-agent-brain-mode");
      return saved === "2d" || saved === "3d" ? saved : "3d";
    } catch { return "3d"; }
  }

  function setMode(mode, persist = true) {
    $("brainMode2d").setAttribute("aria-pressed", String(mode === "2d"));
    $("brainMode3d").setAttribute("aria-pressed", String(mode === "3d"));
    $("brainGestureHint").textContent = mode === "3d" ? "drag to orbit · scroll to zoom" : "drag to pan · drag a node to pin";
    $("brainYaw").disabled = mode === "2d";
    $("brainPitch").disabled = mode === "2d";
    $("brainControls").dataset.mode = mode;
    ensureRenderer().setMode(mode);
    if (persist) { try { localStorage.setItem("job-agent-brain-mode", mode); } catch { /* private mode */ } }
  }

  async function openJob(jobId) { window.activateTab("brain"); await load(); selectNode(`job:${jobId}`); }
  function state() { return renderer?.snapshot() || { nodeCount: 0, mode: "3d" }; }
  function setActive(active) { ensureRenderer().setVisible(active && !document.hidden); }

  function bind() {
    if (!$("brainCanvas")) return;
    ensureRenderer();
    setMode(savedMode(), false);
    $("brainRefreshBtn").addEventListener("click", () => load(true));
    $("brainMode2d").addEventListener("click", () => setMode("2d"));
    $("brainMode3d").addEventListener("click", () => setMode("3d"));
    ["brainYaw", "brainPitch", "brainZoom"].forEach((id) => $(id).addEventListener("input", () => renderer.setOrbit({ yaw: $("brainYaw").value, pitch: $("brainPitch").value, zoom: Number($("brainZoom").value) / 100 })));
    $("brainDetails").addEventListener("click", (event) => { const link = event.target.closest("[data-node]"); if (link) selectNode(link.dataset.node); });
    document.addEventListener("visibilitychange", () => renderer.setVisible(!document.hidden && $("tab-brain").classList.contains("active")));
  }

  bind();
  window.JobAgentBrain = { load, openJob, selectNode, setActive, state };
})();
