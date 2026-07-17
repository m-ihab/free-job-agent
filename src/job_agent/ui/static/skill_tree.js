// Evidence-grounded SVG skill progression map. All labels and actions come from /api/skill-tree.
(function () {
  const $ = (id) => document.getElementById(id);
  const SVG_NS = $("skillTreeSvg").namespaceURI;
  const api = (...args) => window.api(...args);
  const escapeHtml = (value) => window.escapeHtml(value);
  const setNotice = (...args) => window.setNotice(...args);
  const treeLayout = window.JobAgentSkillTreeLayout;
  const state = { payload: null, selectedId: null, loading: false };
  let baseView = { x: 0, y: 0, width: 1, height: 1 };
  let view = { ...baseView };
  let skillById = new Map(), skillPositions = new Map();

  function applyView() {
    $("skillTreeSvg").setAttribute("viewBox", `${view.x} ${view.y} ${view.width} ${view.height}`);
  }

  function resetView() {
    view = { ...baseView };
    applyView();
  }

  function zoomView(factor, point) {
    const svg = $("skillTreeSvg"), rect = svg.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    const rx = (point.x - rect.left) / rect.width, ry = (point.y - rect.top) / rect.height;
    const worldX = view.x + rx * view.width, worldY = view.y + ry * view.height;
    const width = Math.max(baseView.width / 4, Math.min(baseView.width * 2, view.width / factor));
    const height = width * (baseView.height / baseView.width);
    view = { x: worldX - rx * width, y: worldY - ry * height, width, height };
    applyView();
  }

  function screenToWorld(point) {
    const svg = $("skillTreeSvg"), rect = svg.getBoundingClientRect();
    if (!rect.width || !rect.height) return null;
    const matrix = svg.getScreenCTM?.();
    if (matrix && svg.createSVGPoint) {
      const cursor = svg.createSVGPoint();
      cursor.x = point.x; cursor.y = point.y;
      const world = cursor.matrixTransform(matrix.inverse());
      return { x: world.x, y: world.y };
    }
    return {
      x: view.x + ((point.x - rect.left) / rect.width) * view.width,
      y: view.y + ((point.y - rect.top) / rect.height) * view.height,
    };
  }

  function hitSkill(point) {
    const world = screenToWorld(point);
    if (!world) return null;
    return [...skillPositions].find(([, position]) => Math.abs(world.x - position.x) <= 86 && Math.abs(world.y - position.y) <= 39)?.[0] || null;
  }

  function bindTreeInteractions() {
    const svg = $("skillTreeSvg");
    window.JobAgentGraphGestures.bindSurface(svg, {
      onDrag(dx, dy) {
        const rect = svg.getBoundingClientRect();
        view.x -= (dx / rect.width) * view.width; view.y -= (dy / rect.height) * view.height;
        applyView();
      },
      onWheel(delta, point) { zoomView(Math.exp(-delta * 0.001), point); },
      onPinch(scale, point) { zoomView(scale, point); },
      onTap(point) { const id = hitSkill(point); if (id) selectSkill(id, skillById); },
      onDoubleActivate: resetView,
    });
  }

  function roleMeters(roles) {
    $("skillTreeRoles").innerHTML = roles.length ? roles.map((row) => {
      const readiness = Math.max(0, Math.min(100, Number(row.readiness || 0)));
      return `<article class="skill-role-card"><div><strong>${escapeHtml(row.role)}</strong><span>${readiness}% evidence-backed readiness</span></div><div class="skill-role-meter" role="meter" aria-label="${escapeHtml(row.role)} readiness" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${readiness}"><i style="width:${readiness}%"></i></div><small>${(row.skillIds || []).length} mapped required skill(s)</small></article>`;
    }).join("") : "";
  }

  function svgNode(name, attributes = {}) {
    const node = document.createElementNS(SVG_NS, name);
    Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, String(value)));
    return node;
  }

  function drawTree(skills) {
    const svg = $("skillTreeSvg");
    svg.replaceChildren();
    if (!skills.length) {
      svg.classList.add("hidden");
      $("skillTreeEmpty").classList.remove("hidden");
      return;
    }
    svg.classList.remove("hidden");
    $("skillTreeEmpty").classList.add("hidden");
    const { byId, positions } = treeLayout.layoutSkills(skills);
    skillById = byId; skillPositions = positions;
    const bounds = treeLayout.contentBounds(positions), fitView = treeLayout.fitView;
    baseView = fitView(bounds);
    resetView();
    skills.forEach((skill) => (skill.parents || []).forEach((parentId) => {
      const from = positions.get(parentId);
      const to = positions.get(skill.id);
      if (!from || !to) return;
      const path = svgNode("path", { class: "skill-edge", d: `M ${from.x} ${from.y + 31} C ${from.x} ${from.y + 90}, ${to.x} ${to.y - 90}, ${to.x} ${to.y - 31}` });
      svg.appendChild(path);
    }));
    skills.forEach((skill) => {
      const point = positions.get(skill.id);
      const group = svgNode("g", { class: `skill-node ${skill.state}`, transform: `translate(${point.x - 78} ${point.y - 31})`, "aria-label": `${skill.label}, ${skill.state}` });
      group.setAttribute("tabindex", "0");
      group.setAttribute("role", "button");
      group.appendChild(svgNode("rect", { class: "skill-node-hit", x: -8, y: -8, width: 172, height: 78, rx: 22 }));
      group.appendChild(svgNode("rect", { class: "skill-node-card", width: 156, height: 62, rx: 16 }));
      const label = svgNode("text", { x: 78, "text-anchor": "middle" });
      const lines = treeLayout.wrapLabel(skill.label);
      lines.forEach((line, index) => {
        const part = svgNode("tspan", { x: 78, y: lines.length === 1 ? 27 : 19 + index * 14 });
        part.textContent = line; label.appendChild(part);
      });
      group.appendChild(label);
      const status = svgNode("text", { class: "skill-node-state", x: 78, y: 46, "text-anchor": "middle" });
      status.textContent = skill.state === "locked" ? `\u{1F512} ${skill.unlock.jobsBlocked} gap job(s)` : skill.state === "claimed" ? "â—‹ add evidence" : `âœ¦ ${skill.evidenceCount} proof item(s)`;
      group.appendChild(status);
      const select = () => selectSkill(skill.id, byId);
      group.addEventListener("click", select);
      group.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") { event.preventDefault(); select(); }
      });
      svg.appendChild(group);
    });
  }

  function listOrEmpty(items, render, empty) {
    return items.length ? `<ul>${items.map(render).join("")}</ul>` : `<p class="muted">${empty}</p>`;
  }

  function selectSkill(id, byId = new Map((state.payload?.skills || []).map((row) => [row.id, row]))) {
    const skill = byId.get(id);
    if (!skill) return;
    state.selectedId = id;
    const lift = skill.scoreLift === undefined ? "" : `<p><strong>Simulated cluster lift:</strong> +${Number(skill.scoreLift).toFixed(2)} points. Hypothetical re-score, not a promise.</p>`;
    const certs = skill.unlock.certs || [];
    const projects = skill.unlock.projects || [];
    $("skillTreeDetails").innerHTML = `<span class="brain-type ${skill.state}">${escapeHtml(skill.state)}</span><h3>${escapeHtml(skill.label)}</h3><div class="skill-proof-grid"><div><span>Evidence entries</span><strong>${skill.evidenceCount}</strong></div><div><span>Profile/CV claims</span><strong>${skill.claimCount || 0}</strong></div></div><h4>Why it matters</h4><p><strong>${skill.jobsRequiring}</strong> tracked job(s) require it; <strong>${skill.unlock.jobsBlocked}</strong> low-score job(s) expose it as a gap.</p>${lift}<h4>How to unlock</h4>${listOrEmpty(certs, (row) => `<li><strong>${escapeHtml(row.name)}</strong><span>${escapeHtml(row.issuer)} Â· ${escapeHtml(row.cost)} Â· ${Number(row.estHours)}h estimate</span></li>`, "No certification from the current cert plan matches this gap.")}${listOrEmpty(projects, (row) => `<li><strong>${escapeHtml(row.name)}</strong><span>${escapeHtml(row.hardPart)}<br>${escapeHtml(row.deliverable)} Â· ${Number(row.timeBudgetHours)}h plan</span></li>`, "No project action from the current project plan matches this gap.")}<button class="primary-soft" data-evidence-flow>Open evidence flow</button>`;
  }

  async function load(force = false) {
    if (state.loading || (state.payload && !force)) return;
    state.loading = true;
    setNotice("skillTreeNotice", "");
    try {
      state.payload = await api("/api/skill-tree");
      roleMeters(state.payload.roles || []);
      drawTree(state.payload.skills || []);
      if (state.selectedId) selectSkill(state.selectedId);
    } catch (error) {
      if (error instanceof TypeError) {
        window.renderConnectionLost("skillTreeNotice", () => load(true));
        drawTree([]);
        return;
      }
      setNotice("skillTreeNotice", `Skill Tree could not load: ${error.message}`, true);
      drawTree([]);
    } finally {
      state.loading = false;
    }
  }

  bindTreeInteractions();
  $("skillTreeRefreshBtn").addEventListener("click", () => load(true));
  $("skillTreeDetails").addEventListener("click", (event) => {
    if (!event.target.closest("[data-evidence-flow]")) return;
    window.activateTab("studio");
    document.getElementById("studioDefensibilityBtn")?.scrollIntoView({ block: "center" });
  });
  window.JobAgentSkillTree = { load };
})();
