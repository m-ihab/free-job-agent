/* Canvas force layout plus hand-rolled yaw/pitch projection. No WebGL dependency. */
(function () {
  "use strict";

  function create(canvas, options = {}) {
    const ctx = canvas.getContext("2d");
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
    let nodes = [], edges = [], byId = new Map(), frame = 0, alpha = 0;
    let mode = "2d", yaw = 18, pitch = -12, zoom = 1, visible = false, selected = "";
    let drag = null;

    function sizeCanvas() {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const width = Math.max(320, canvas.clientWidth);
      const height = Math.max(360, canvas.clientHeight);
      if (canvas.width !== width * dpr || canvas.height !== height * dpr) {
        canvas.width = width * dpr; canvas.height = height * dpr;
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      }
      return { width, height };
    }

    function place(rawNodes) {
      const golden = Math.PI * (3 - Math.sqrt(5));
      return rawNodes.map((node, index) => {
        const sphereZ = 1 - (2 * (index + 0.5)) / Math.max(1, rawNodes.length);
        const radius = Math.sqrt(Math.max(0, 1 - sphereZ * sphereZ));
        const angle = index * golden + (node.meta.stable_seed % 997) / 997;
        return { ...node, x: Math.cos(angle) * radius * 230, y: Math.sin(angle) * radius * 230,
          z: sphereZ * 230, vx: 0, vy: 0, sx: 0, sy: 0, sr: 0, depth: 0 };
      });
    }

    function simulate() {
      const repulsion = 1300, spring = 0.012, centering = 0.004;
      for (let i = 0; i < nodes.length; i += 1) {
        for (let j = i + 1; j < nodes.length; j += 1) {
          const a = nodes[i], b = nodes[j];
          let dx = b.x - a.x, dy = b.y - a.y;
          const d2 = Math.max(64, dx * dx + dy * dy), force = (repulsion * alpha) / d2;
          const d = Math.sqrt(d2); dx /= d; dy /= d;
          a.vx -= dx * force; a.vy -= dy * force; b.vx += dx * force; b.vy += dy * force;
        }
      }
      edges.forEach((edge) => {
        const a = byId.get(edge.source), b = byId.get(edge.target);
        if (!a || !b) return;
        const dx = b.x - a.x, dy = b.y - a.y, distance = Math.max(1, Math.hypot(dx, dy));
        const pull = (distance - 95) * spring * alpha;
        a.vx += (dx / distance) * pull; a.vy += (dy / distance) * pull;
        b.vx -= (dx / distance) * pull; b.vy -= (dy / distance) * pull;
      });
      nodes.forEach((node) => {
        node.vx = (node.vx - node.x * centering * alpha) * 0.84;
        node.vy = (node.vy - node.y * centering * alpha) * 0.84;
        node.x += node.vx; node.y += node.vy;
      });
      alpha *= 0.985;
    }

    function project(node, width, height) {
      if (mode === "2d") return { x: width / 2 + node.x * zoom, y: height / 2 + node.y * zoom, p: 1, z: 0 };
      const yr = yaw * Math.PI / 180, pr = pitch * Math.PI / 180;
      const x1 = node.x * Math.cos(yr) + node.z * Math.sin(yr);
      const z1 = -node.x * Math.sin(yr) + node.z * Math.cos(yr);
      const y1 = node.y * Math.cos(pr) - z1 * Math.sin(pr);
      const z2 = node.y * Math.sin(pr) + z1 * Math.cos(pr);
      const perspective = Math.max(0.45, Math.min(1.7, 520 / (520 + z2)));
      return { x: width / 2 + x1 * zoom * perspective, y: height / 2 + y1 * zoom * perspective,
        p: perspective, z: z2 };
    }

    function palette() {
      const css = getComputedStyle(document.documentElement);
      return { skill: css.getPropertyValue("--brain-skill").trim(), job: css.getPropertyValue("--brain-job").trim(),
        company: css.getPropertyValue("--brain-company").trim(), evidence: css.getPropertyValue("--brain-evidence").trim(),
        edge: css.getPropertyValue("--line-strong").trim(), text: css.getPropertyValue("--ink").trim() };
    }

    function draw() {
      const { width, height } = sizeCanvas(), colors = palette();
      ctx.clearRect(0, 0, width, height);
      nodes.forEach((node) => {
        const p = project(node, width, height); node.sx = p.x; node.sy = p.y; node.depth = p.z;
        node.sr = (node.type === "job" ? 7 : node.type === "skill" ? 6 : 5) * Math.sqrt(p.p);
      });
      ctx.lineWidth = 1;
      edges.forEach((edge) => {
        const a = byId.get(edge.source), b = byId.get(edge.target); if (!a || !b) return;
        ctx.strokeStyle = colors.edge; ctx.globalAlpha = 0.38;
        ctx.beginPath(); ctx.moveTo(a.sx, a.sy); ctx.lineTo(b.sx, b.sy); ctx.stroke();
      });
      [...nodes].sort((a, b) => b.depth - a.depth).forEach((node) => {
        const active = node.id === selected;
        ctx.globalAlpha = mode === "3d" ? Math.max(0.42, Math.min(1, 1.25 - (node.depth + 230) / 700)) : 1;
        ctx.fillStyle = colors[node.type]; ctx.shadowColor = colors[node.type]; ctx.shadowBlur = active ? 18 : 7;
        ctx.beginPath(); ctx.arc(node.sx, node.sy, node.sr + (active ? 3 : 0), 0, Math.PI * 2); ctx.fill();
        if (active || node.meta.degree >= 3) {
          ctx.shadowBlur = 0; ctx.fillStyle = colors.text; ctx.font = "12px Inter, Segoe UI, sans-serif";
          ctx.fillText(node.label, node.sx + node.sr + 5, node.sy + 4);
        }
      });
      ctx.globalAlpha = 1; ctx.shadowBlur = 0;
    }

    function animate() {
      frame = 0;
      if (!visible) return;
      if (!reduced.matches && alpha > 0.015) simulate();
      draw();
      if (!reduced.matches && alpha > 0.015) frame = requestAnimationFrame(animate);
    }

    function wake(amount = 0.3) {
      alpha = Math.max(alpha, amount);
      if (!frame && visible) frame = requestAnimationFrame(animate);
      else if (reduced.matches) draw();
    }

    function hit(x, y) {
      return [...nodes].reverse().find((node) => Math.hypot(node.sx - x, node.sy - y) <= node.sr + 7);
    }

    canvas.addEventListener("pointerdown", (event) => {
      drag = { x: event.clientX, y: event.clientY, yaw, pitch, moved: false };
      canvas.setPointerCapture(event.pointerId);
    });
    canvas.addEventListener("pointermove", (event) => {
      if (!drag || mode !== "3d") return;
      const dx = event.clientX - drag.x, dy = event.clientY - drag.y;
      drag.moved = drag.moved || Math.abs(dx) + Math.abs(dy) > 4;
      yaw = drag.yaw + dx * 0.45; pitch = Math.max(-80, Math.min(80, drag.pitch + dy * 0.35));
      options.onOrbit?.({ yaw, pitch, zoom }); draw();
    });
    canvas.addEventListener("pointerup", (event) => {
      const rect = canvas.getBoundingClientRect(), node = hit(event.clientX - rect.left, event.clientY - rect.top);
      if (node && !drag?.moved) options.onSelect?.(node.id);
      drag = null;
    });
    new window.ResizeObserver(() => draw()).observe(canvas);

    return {
      setData(data) { nodes = place(data.nodes || []); edges = data.edges || []; byId = new Map(nodes.map((n) => [n.id, n])); selected = ""; wake(1); },
      setMode(value) { mode = value; draw(); },
      setOrbit(next) { yaw = Number(next.yaw); pitch = Number(next.pitch); zoom = Number(next.zoom); draw(); },
      setVisible(value) { visible = value; if (!visible && frame) { window.cancelAnimationFrame(frame); frame = 0; } else if (visible) wake(); },
      select(id) { selected = id; draw(); },
      snapshot() { return { nodeCount: nodes.length, mode, yaw, pitch, zoom }; },
    };
  }

  window.JobAgentBrainGraph = { create };
})();
