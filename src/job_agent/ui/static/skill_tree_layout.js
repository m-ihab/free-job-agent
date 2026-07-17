/* Deterministic skill-tree layout, fitted bounds, and compact label wrapping. */
(function () {
  "use strict";

  function skillDepth(skill, byId, trail = new Set()) {
    if (trail.has(skill.id)) return 0;
    const parents = (skill.parents || []).map((id) => byId.get(id)).filter(Boolean);
    if (!parents.length) return 0;
    const nextTrail = new Set(trail);
    nextTrail.add(skill.id);
    return 1 + Math.max(...parents.map((parent) => skillDepth(parent, byId, nextTrail)));
  }

  function layoutSkills(skills) {
    const byId = new Map(skills.map((skill) => [skill.id, skill]));
    const tiers = new Map();
    skills.forEach((skill) => {
      const depth = skillDepth(skill, byId);
      if (!tiers.has(depth)) tiers.set(depth, []);
      tiers.get(depth).push(skill);
    });
    const width = 760, perRow = 4;
    const positions = new Map();
    let visualRow = 0;
    [...tiers.entries()].sort(([a], [b]) => a - b).forEach(([, rows]) => {
      rows.sort((a, b) => a.label.localeCompare(b.label));
      for (let start = 0; start < rows.length; start += perRow) {
        const line = rows.slice(start, start + perRow), gap = width / (line.length + 1);
        line.forEach((skill, index) => positions.set(skill.id, { x: gap * (index + 1), y: 95 + visualRow * 120 }));
        visualRow += 1;
      }
    });
    return { byId, positions };
  }

  function contentBounds(positions) {
    const points = [...positions.values()];
    const left = Math.min(...points.map((point) => point.x - 86));
    const right = Math.max(...points.map((point) => point.x + 86));
    const top = Math.min(...points.map((point) => point.y - 39));
    const bottom = Math.max(...points.map((point) => point.y + 39));
    return { x: left, y: top, width: right - left, height: bottom - top };
  }

  function fitView(bounds) {
    const padding = Math.max(bounds.width, bounds.height) * 0.08;
    return { x: bounds.x - padding, y: bounds.y - padding, width: bounds.width + padding * 2, height: bounds.height + padding * 2 };
  }

  function wrapLabel(label) {
    const words = label.split(/\s+/), lines = [];
    words.forEach((word) => {
      const current = lines.at(-1);
      if (!current || (current.length + word.length + 1 > 18 && lines.length < 2)) lines.push(word);
      else lines[lines.length - 1] = `${current} ${word}`;
    });
    return lines.slice(0, 2);
  }

  window.JobAgentSkillTreeLayout = { contentBounds, fitView, layoutSkills, wrapLabel };
})();
