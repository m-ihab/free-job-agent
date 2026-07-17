/* Canvas force layout plus hand-rolled yaw/pitch projection. No WebGL dependency. */
(function () {
  "use strict";

  function create(canvas, options = {}) {
    const ctx = canvas.getContext("2d");
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
    let nodes = [], edges = [], byId = new Map(), frame = 0, alpha = 0, lastFrame = 0;
    let mode = "3d", yaw = 18, pitch = -12, zoom = 1, visible = false, selected = "";
    let panX = 0, panY = 0, lastDragAt = 0, draggedNode = null;
    const orbitVelocity = { yaw: 0, pitch: 0 };
    const layout = window.JobAgentBrainLayout;

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
          z: sphereZ * 230, vx: 0, vy: 0, sx: 0, sy: 0, sr: 0, depth: 0, pinned: false };
      });
    }

    function simulate() {
      layout.simulate(nodes, edges, byId, alpha);
      alpha *= 0.985;
    }

    function project(node, width, height) {
      if (mode === "2d") return { x: width / 2 + panX + node.x * zoom, y: height / 2 + panY + node.y * zoom, p: 1, z: 0 };
      const yr = yaw * Math.PI / 180, pr = pitch * Math.PI / 180;
      const x1 = node.x * Math.cos(yr) + node.z * Math.sin(yr);
      const z1 = -node.x * Math.sin(yr) + node.z * Math.cos(yr);
      const y1 = node.y * Math.cos(pr) - z1 * Math.sin(pr);
      const z2 = node.y * Math.sin(pr) + z1 * Math.cos(pr);
      const perspective = Math.max(0.45, Math.min(1.7, 520 / (520 + z2)));
      return { x: width / 2 + panX + x1 * zoom * perspective, y: height / 2 + panY + y1 * zoom * perspective,
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
        node.sr = layout.radiusFor(node, p.p);
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
      });
      layout.drawLabels(ctx, nodes, selected, zoom, colors.text);
      ctx.globalAlpha = 1; ctx.shadowBlur = 0;
    }

    function stepInertia(delta) {
      if (reduced.matches || mode !== "3d" || Math.abs(orbitVelocity.yaw) + Math.abs(orbitVelocity.pitch) < 0.002) return false;
      yaw += orbitVelocity.yaw * delta;
      pitch = Math.max(-80, Math.min(80, pitch + orbitVelocity.pitch * delta));
      const damping = Math.pow(0.9, delta / 16);
      orbitVelocity.yaw *= damping; orbitVelocity.pitch *= damping;
      options.onOrbit?.({ yaw, pitch, zoom });
      return true;
    }

    function animate(timestamp) {
      frame = 0;
      if (!visible) return;
      const delta = lastFrame ? Math.min(32, timestamp - lastFrame) : 16;
      lastFrame = timestamp;
      const forceActive = !reduced.matches && alpha > 0.015;
      if (forceActive) simulate();
      const inertiaActive = stepInertia(delta);
      draw();
      if (forceActive || inertiaActive) frame = requestAnimationFrame(animate);
    }

    function wake(amount = 0.3) {
      alpha = Math.max(alpha, amount);
      if (!frame && visible) { lastFrame = 0; frame = requestAnimationFrame(animate); }
      else if (reduced.matches) draw();
    }

    function hit(x, y) {
      return [...nodes].reverse().find((node) => Math.hypot(node.sx - x, node.sy - y) <= Math.max(node.sr, 12));
    }

    function canvasPoint(point) {
      const rect = canvas.getBoundingClientRect();
      return { x: point.x - rect.left, y: point.y - rect.top };
    }

    function zoomAt(factor, point) {
      const next = Math.max(0.45, Math.min(1.8, zoom * factor));
      const ratio = next / zoom, rect = canvas.getBoundingClientRect();
      const x = point.x - rect.left - rect.width / 2, y = point.y - rect.top - rect.height / 2;
      panX = x - (x - panX) * ratio; panY = y - (y - panY) * ratio; zoom = next;
      options.onOrbit?.({ yaw, pitch, zoom }); draw();
    }

    function resetView() {
      yaw = 18; pitch = -12; zoom = 1; panX = 0; panY = 0;
      orbitVelocity.yaw = 0; orbitVelocity.pitch = 0;
      options.onOrbit?.({ yaw, pitch, zoom }); draw();
    }

    window.JobAgentGraphGestures.bindSurface(canvas, {
      onDragStart(point) {
        orbitVelocity.yaw = 0; orbitVelocity.pitch = 0; lastDragAt = window.performance.now();
        draggedNode = mode === "2d" ? hit(canvasPoint(point).x, canvasPoint(point).y) : null;
        if (draggedNode) { draggedNode.pinned = true; draggedNode.vx = 0; draggedNode.vy = 0; }
      },
      onDrag(dx, dy) {
        if (mode === "2d") {
          if (draggedNode) { draggedNode.x += dx / zoom; draggedNode.y += dy / zoom; }
          else { panX += dx; panY += dy; }
          draw(); return;
        }
        const now = window.performance.now(), delta = Math.max(8, now - lastDragAt);
        const yawDelta = dx * 0.45, pitchDelta = dy * 0.35;
        yaw += yawDelta; pitch = Math.max(-80, Math.min(80, pitch + pitchDelta));
        orbitVelocity.yaw = yawDelta / delta; orbitVelocity.pitch = pitchDelta / delta; lastDragAt = now;
        options.onOrbit?.({ yaw, pitch, zoom }); draw();
      },
      onDragEnd({ moved }) { draggedNode = null; if (moved && mode === "3d" && !reduced.matches) wake(0); },
      onWheel(delta, point) { zoomAt(Math.exp(-delta * 0.001), point); },
      onPinch(scale, point) { zoomAt(scale, point); },
      onTap(point) { const local = canvasPoint(point), node = hit(local.x, local.y); if (node) options.onSelect?.(node.id); },
      onDoubleActivate(point) {
        const local = canvasPoint(point), node = mode === "2d" ? hit(local.x, local.y) : null;
        if (node?.pinned) { node.pinned = false; wake(0.5); return; }
        resetView();
      },
      onKey(event) {
        const turns = { ArrowLeft: [-6, 0], ArrowRight: [6, 0], ArrowUp: [0, -5], ArrowDown: [0, 5] };
        if (turns[event.key]) {
          event.preventDefault(); yaw += turns[event.key][0]; pitch = Math.max(-80, Math.min(80, pitch + turns[event.key][1]));
          options.onOrbit?.({ yaw, pitch, zoom }); draw();
        } else if (["+", "=", "-", "_"].includes(event.key)) {
          event.preventDefault(); const rect = canvas.getBoundingClientRect();
          zoomAt(event.key === "+" || event.key === "=" ? 1.12 : 1 / 1.12, { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 });
        }
      },
    });
    new window.ResizeObserver(() => draw()).observe(canvas);

    return {
      setData(data) { nodes = place(data.nodes || []); edges = data.edges || []; byId = new Map(nodes.map((n) => [n.id, n])); selected = ""; layout.collide(nodes); wake(1); },
      setMode(value) { mode = value; draw(); },
      setOrbit(next) { yaw = Number(next.yaw); pitch = Number(next.pitch); zoom = Number(next.zoom); draw(); },
      setVisible(value) { visible = value; if (!visible && frame) { window.cancelAnimationFrame(frame); frame = 0; lastFrame = 0; } else if (visible) wake(); },
      select(id) { selected = id; draw(); },
      snapshot() { return { nodeCount: nodes.length, mode, yaw, pitch, zoom }; },
    };
  }

  window.JobAgentBrainGraph = { create };
})();
