/* Force-layout collision and collision-aware canvas labels for the Brain graph. */
(function () {
  "use strict";

  function radiusFor(node, perspective = 1) {
    return (node.type === "job" ? 7 : node.type === "skill" ? 6 : 5) * Math.sqrt(perspective);
  }

  function collide(nodes) {
    for (let i = 0; i < nodes.length; i += 1) {
      for (let j = i + 1; j < nodes.length; j += 1) {
        const a = nodes[i], b = nodes[j];
        let dx = b.x - a.x, dy = b.y - a.y;
        if (Math.abs(dx) + Math.abs(dy) < 0.01) { dx = 1; dy = 0; }
        const distance = Math.hypot(dx, dy);
        const minDistance = radiusFor(a) + radiusFor(b) + 6;
        if (distance >= minDistance) continue;
        dx /= distance; dy /= distance;
        const overlap = minDistance - distance;
        const aShare = a.pinned ? 0 : b.pinned ? 1 : 0.5;
        const bShare = b.pinned ? 0 : a.pinned ? 1 : 0.5;
        a.x -= dx * overlap * aShare; a.y -= dy * overlap * aShare;
        b.x += dx * overlap * bShare; b.y += dy * overlap * bShare;
      }
    }
  }

  function simulate(nodes, edges, byId, alpha) {
    const repulsion = 1550, spring = 0.012, centering = 0.004;
    for (let i = 0; i < nodes.length; i += 1) {
      for (let j = i + 1; j < nodes.length; j += 1) {
        const a = nodes[i], b = nodes[j];
        let dx = b.x - a.x, dy = b.y - a.y;
        const d2 = Math.max(64, dx * dx + dy * dy), force = (repulsion * alpha) / d2;
        const distance = Math.sqrt(d2); dx /= distance; dy /= distance;
        if (!a.pinned) { a.vx -= dx * force; a.vy -= dy * force; }
        if (!b.pinned) { b.vx += dx * force; b.vy += dy * force; }
      }
    }
    edges.forEach((edge) => {
      const a = byId.get(edge.source), b = byId.get(edge.target);
      if (!a || !b) return;
      const dx = b.x - a.x, dy = b.y - a.y, distance = Math.max(1, Math.hypot(dx, dy));
      const pull = (distance - 95) * spring * alpha;
      if (!a.pinned) { a.vx += (dx / distance) * pull; a.vy += (dy / distance) * pull; }
      if (!b.pinned) { b.vx -= (dx / distance) * pull; b.vy -= (dy / distance) * pull; }
    });
    nodes.forEach((node) => {
      if (node.pinned) { node.vx = 0; node.vy = 0; return; }
      node.vx = (node.vx - node.x * centering * alpha) * 0.84;
      node.vy = (node.vy - node.y * centering * alpha) * 0.84;
      node.x += node.vx; node.y += node.vy;
    });
    collide(nodes);
  }

  function rectsIntersect(a, b) {
    return a.x < b.x + b.width && a.x + a.width > b.x && a.y < b.y + b.height && a.y + a.height > b.y;
  }

  function labelDegreeThreshold(zoom) {
    if (zoom >= 1.45) return 1;
    if (zoom >= 1.05) return 2;
    return 3;
  }

  function drawLabels(ctx, nodes, selected, zoom, color) {
    const labelRects = [];
    const ordered = [...nodes].sort((a, b) => Number(b.id === selected) - Number(a.id === selected) || b.meta.degree - a.meta.degree);
    ctx.globalAlpha = 1; ctx.shadowBlur = 0; ctx.fillStyle = color; ctx.font = "12px Inter, Segoe UI, sans-serif";
    ordered.forEach((node) => {
      const active = node.id === selected;
      if (!active && node.meta.degree < labelDegreeThreshold(zoom)) return;
      const width = Math.ceil(ctx.measureText(node.label).width);
      const rect = { x: node.sx + node.sr + 5, y: node.sy - 8, width, height: 16 };
      if (!active && labelRects.some((drawn) => rectsIntersect(rect, drawn))) return;
      ctx.fillText(node.label, rect.x, node.sy + 4);
      labelRects.push(rect);
    });
  }

  window.JobAgentBrainLayout = { collide, drawLabels, radiusFor, simulate };
})();
