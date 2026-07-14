/* score_explain.js — G2 "Why this score" drawer. Self-contained module.
 *
 * Deliberately makes ZERO changes to app.js (R3 boy-scout rule: the next
 * session that edits app.js must split it first). Instead it:
 *   1. watches the DOM and upgrades every rendered `.score-pill` into an
 *      accessible trigger (role=button, tabindex, aria-haspopup);
 *   2. resolves the job id from the row's existing `[data-job]` buttons;
 *   3. opens an aria-modal drawer with the per-component decomposition
 *      from POST /api/score-explain (job_agent.scorer.explain_score).
 *
 * A11y: focus is moved into the dialog and restored on close; Tab is trapped;
 * Esc closes; the active pill carries aria-expanded; bar visuals are
 * aria-hidden with the same values present as text.
 */
(function () {
  "use strict";

  const TOKEN_HEADER = "X-Job-Agent-Token";
  const csrf = () => document.querySelector('meta[name="csrf-token"]')?.content || "";
  let lastTrigger = null;

  // ---------------------------------------------------------------- styles
  const style = document.createElement("style");
  style.textContent = `
  .score-pill[role="button"]{cursor:pointer}
  .score-pill[role="button"]:hover{outline:1px solid var(--accent,#7aa2ff)}
  .score-pill[role="button"]:focus-visible{outline:2px solid var(--accent,#7aa2ff);outline-offset:2px}
  #se-backdrop{position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:70;backdrop-filter:blur(2px)}
  #se-drawer{position:fixed;top:0;right:0;bottom:0;width:min(430px,94vw);z-index:71;
    background:var(--panel,var(--card,#161a22));color:var(--text,#e8e8ea);
    border-left:1px solid var(--border,#2a2f3a);box-shadow:-18px 0 40px rgba(0,0,0,.45);
    display:flex;flex-direction:column;transform:translateX(102%);transition:transform .22s ease}
  #se-drawer.se-open{transform:none}
  @media (prefers-reduced-motion: reduce){#se-drawer{transition:none}}
  .se-head{display:flex;align-items:flex-start;gap:10px;padding:16px 18px 10px;border-bottom:1px solid var(--border,#2a2f3a)}
  .se-head h2{margin:0;font-size:1.02rem;line-height:1.3;flex:1}
  .se-head small{display:block;color:var(--muted,#9aa1ad);font-weight:400;margin-top:2px}
  .se-close{background:none;border:1px solid var(--border,#2a2f3a);color:inherit;border-radius:8px;
    width:30px;height:30px;font-size:15px;cursor:pointer;flex:none}
  .se-close:focus-visible{outline:2px solid var(--accent,#7aa2ff)}
  .se-body{padding:14px 18px;overflow-y:auto;flex:1}
  .se-total{display:flex;align-items:baseline;gap:10px;margin-bottom:4px}
  .se-total b{font-size:1.9rem}
  .se-total span{color:var(--muted,#9aa1ad);font-size:.85rem}
  .se-row{margin:10px 0}
  .se-row .se-lbl{display:flex;justify-content:space-between;font-size:.82rem;margin-bottom:3px}
  .se-row .se-lbl em{color:var(--muted,#9aa1ad);font-style:normal}
  .se-bar{height:7px;border-radius:5px;background:var(--border,#2a2f3a);overflow:hidden}
  .se-bar i{display:block;height:100%;background:var(--accent,#7aa2ff);border-radius:5px}
  .se-caps{margin:12px 0;padding:9px 12px;border:1px solid #b4832a55;background:#b4832a1a;
    border-radius:8px;font-size:.82rem}
  .se-sec{margin-top:14px;font-size:.82rem}
  .se-sec h3{font-size:.72rem;text-transform:uppercase;letter-spacing:1.2px;color:var(--muted,#9aa1ad);margin:0 0 6px}
  .se-sec ul{margin:0;padding-left:18px}
  .se-sec li{margin:3px 0}
  .se-err{color:#e5534b;padding:14px 18px}
  `;
  document.head.appendChild(style);

  // ------------------------------------------------------------ pill upgrade
  function upgrade(root) {
    root.querySelectorAll?.(".score-pill:not([role])").forEach((pill) => {
      if (!jobIdFor(pill)) return; // pills outside a job row stay inert
      pill.setAttribute("role", "button");
      pill.setAttribute("tabindex", "0");
      pill.setAttribute("aria-haspopup", "dialog");
      pill.setAttribute("aria-expanded", "false");
      pill.title = "Why this score?";
    });
  }
  function jobIdFor(el) {
    const row = el.closest("tr, [data-job-row], .kanban-card");
    return row?.querySelector("[data-job]")?.dataset.job || row?.dataset?.job || null;
  }
  new MutationObserver((muts) => {
    for (const m of muts) for (const n of m.addedNodes) if (n.nodeType === 1) upgrade(n);
  }).observe(document.documentElement, { childList: true, subtree: true });
  upgrade(document);

  document.addEventListener("click", (e) => {
    const pill = e.target.closest?.('.score-pill[role="button"]');
    if (pill) open(pill);
  });
  document.addEventListener("keydown", (e) => {
    if ((e.key === "Enter" || e.key === " ") && e.target.matches?.('.score-pill[role="button"]')) {
      e.preventDefault();
      open(e.target);
    }
  });

  // ---------------------------------------------------------------- drawer
  function close() {
    document.getElementById("se-backdrop")?.remove();
    document.getElementById("se-drawer")?.remove();
    lastTrigger?.setAttribute("aria-expanded", "false");
    lastTrigger?.focus?.();
    lastTrigger = null;
  }

  async function open(pill) {
    const jobId = jobIdFor(pill);
    if (!jobId) return;
    close();
    lastTrigger = pill;
    pill.setAttribute("aria-expanded", "true");

    const backdrop = document.createElement("div");
    backdrop.id = "se-backdrop";
    backdrop.addEventListener("click", close);
    const drawer = document.createElement("aside");
    drawer.id = "se-drawer";
    drawer.setAttribute("role", "dialog");
    drawer.setAttribute("aria-modal", "true");
    drawer.setAttribute("aria-labelledby", "se-title");
    drawer.innerHTML = `
      <div class="se-head">
        <h2 id="se-title">Why this score?<small>loading…</small></h2>
        <button class="se-close" aria-label="Close score explanation">✕</button>
      </div>
      <div class="se-body" id="se-body"><p style="color:var(--muted,#9aa1ad)">Computing decomposition…</p></div>`;
    document.body.append(backdrop, drawer);
    requestAnimationFrame(() => drawer.classList.add("se-open"));

    drawer.querySelector(".se-close").addEventListener("click", close);
    drawer.addEventListener("keydown", (e) => {
      if (e.key === "Escape") return close();
      if (e.key !== "Tab") return;
      const focusables = drawer.querySelectorAll("button, [href], [tabindex]:not([tabindex='-1'])");
      const first = focusables[0], last = focusables[focusables.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    });
    drawer.querySelector(".se-close").focus();

    try {
      const resp = await fetch("/api/score-explain", {
        method: "POST",
        headers: { "Content-Type": "application/json", [TOKEN_HEADER]: csrf() },
        body: JSON.stringify({ job_id: jobId }),
      });
      const data = await resp.json();
      if (!resp.ok || data.error) throw new Error(data.error || `HTTP ${resp.status}`);
      render(drawer, data);
    } catch (err) {
      const body = drawer.querySelector("#se-body");
      if (body) body.innerHTML = `<p class="se-err">Could not explain this score: ${esc(String(err.message || err))}</p>`;
    }
  }

  function esc(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  function render(drawer, data) {
    const ex = data.explain, job = data.job || {};
    drawer.querySelector("#se-title").innerHTML =
      `Why this score?<small>${esc(job.title || "")} · ${esc(job.company || "")}</small>`;
    const rows = (ex.components || []).map((c) => {
      const pct = Math.max(0, Math.min(100, c.score));
      return `<div class="se-row">
        <div class="se-lbl"><span>${esc(c.name)}</span>
          <em>${c.score}/100 · weight ${(c.weight * 100).toFixed(0)}% · +${c.contribution} pts</em></div>
        <div class="se-bar" aria-hidden="true"><i style="width:${pct}%"></i></div>
      </div>`;
    }).join("");
    const caps = (ex.caps_applied || []).length
      ? `<div class="se-caps" role="note">⚠ Score capped: ${ex.caps_applied
          .map((c) => `${esc(c.flag)} → ceiling ${c.ceiling}`).join(" · ")}</div>` : "";
    const missing = (ex.missing_requirements || []).length
      ? `<div class="se-sec"><h3>Missing requirements</h3><ul>${ex.missing_requirements
          .map((m) => `<li>${esc(m)}</li>`).join("")}</ul></div>` : "";
    const notes = (ex.notes || []).length
      ? `<div class="se-sec"><h3>Notes</h3><ul>${ex.notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul></div>` : "";
    const feedbackDelta = Number(ex.feedback_adjustment || 0);
    const feedbackReasons = (ex.feedback_reasons || []).map(esc).join(" · ");
    const feedback = `<div class="se-caps" role="note"><strong>Base score ${ex.base_score}</strong> · Feedback adjustment ${feedbackDelta >= 0 ? "+" : ""}${feedbackDelta}<br>${feedbackReasons}</div>`;
    drawer.querySelector("#se-body").innerHTML = `
      <div class="se-total"><b>${ex.total_score}</b>
        <span>${esc(ex.decision || "")} · confidence ${Math.round((ex.confidence || 0) * 100)}%</span></div>
      ${feedback}${caps}${rows}${missing}${notes}`;
  }
})();
