# free-job-agent — Codebase Health Report

_Generated 2026-06-17 against HEAD `0fcae40`. Scope: `src/job_agent/` (~19,200 LOC Python,
79 modules) + `src/job_agent/ui/static/app.js` (3,567 LOC) + tests (`tests/`, 42 unit files +
Playwright e2e). Method: direct exploration + parallel python-reviewer, typescript-reviewer,
python-security-auditor, and python-test-coverage-auditor passes._

## 1. Architecture Overview

A local-first, single-user job-search/application copilot for France/Paris data-AI roles.
Python 3.11+, two entry points (`job-agent` CLI and `job-agent-web` dashboard), SQLite storage,
Pydantic schemas, optional local Ollama LLM. No cloud services for job data by design.

**Layered pipeline** (`src/job_agent/`):

| Layer | Modules | Role |
|-------|---------|------|
| Entry | `cli/main.py` (1617), `ui/server.py` (1297, stdlib `http.server`), `ui/static/app.js` (3567) | CLI dispatch + local dashboard on `127.0.0.1:8765` |
| Intake | `intake/` (`free_apis.py` 1482, `france_market.py`, `france_travail_*`, `rss.py`, `url.py`, `file.py`, `markitdown_intake.py`) | Ingest jobs from paste/file/URL/RSS/free APIs/France market |
| Normalize/Score | `normalizer.py`, `scorer.py`, `filters.py`, `skill_extractor.py`, `search_quality.py` | Extract tech/salary/seniority; deterministic 0–100 fit scoring; noise filtering |
| Generate | `generator/` (cv, qa, cover-letter, followup, linkedin, interview-prep), `cv_studio.py` (988), `coach.py` (699), `portfolio_builder.py` (924) | Tailored CV/cover/QA, portfolio site, interview coaching |
| Render | `renderer/` (`latex_render.py` 898, `pdf_render.py`, `html_render.py`, `assistant_render.py`, `markdown_render.py`) | Markdown/HTML/PDF/LaTeX outputs |
| Apply | `auto_apply.py` (1046, Playwright), `apply_bridge.py`, `autopilot.py` (515) | Browser-assisted apply with human-in-the-loop gate |
| AI | `ai_agent.py` (661), `agent_core.py`, `ollama_manage.py` | Optional local LLM routing/caching |
| Persistence/Util | `db/database.py` (563, SQLite), `config.py`, `secrets.py`, `validators.py`, `utils/` | Storage, env/secret loading, boundary validation |

**Data flow:** intake → normalize → score/filter → DB → (CLI/dashboard) → generate packet →
render → apply-assist. Pydantic schemas (`schemas/job.py`, `candidate.py`, `packet.py`) define boundaries.

**Health snapshot:** functional architecture with sensible feature decomposition, but the entry
and intake layers have become monoliths (10 modules exceed the project's own 200-line cap; 54
functions exceed the 50-line cap). Test coverage (45%) and observability (almost no logging) are
the weakest structural areas; security is mostly sound for loopback-only use but has
SSRF/CSRF gaps that escalate sharply if ever bound to `0.0.0.0`.

## 2. Code Quality (python-reviewer + typescript-reviewer)

### Python — CRITICAL
- **3.12-only f-string syntax violates declared `>=3.11` support.** `portfolio_builder.py:404`
  and `renderer/latex_render.py:729` use backslash-escaped quotes/regex inside f-string
  expressions (PEP 701, valid only on 3.12+). `pyproject.toml` declares `>=3.11`; these are hard
  `SyntaxError`s on 3.11. The dev `.venv` runs 3.12.13, masking it locally.

### Python — HIGH
- **Silent exception handling everywhere:** 123 `except Exception: pass`/`continue`/fallback
  blocks across 54 files (worst: `db/database.py`, `auto_apply.py`, `cv_studio.py`, `ui/server.py`).
  Only ~5 of ~80 modules import `logging` at all — failures leave no diagnostic trail.
- **`do_POST` monolith:** `ui/server.py:686-1165` — 480 lines, cyclomatic complexity 108, a
  92-branch `if path == ...` chain wrapped in one catch-all that discards every route's traceback.
- **Module/function bloat past the project's own limits:** 26/79 modules > 200 lines; 54 functions
  > 50 lines. Worst functions: `do_POST` (480), `build_parser` (276, `cli/main.py:1295`),
  `generate_packet_for_job` (249, `pipeline.py:240`), `_run_cycle` (196, `autopilot.py:240`),
  `do_GET` (165), `_render_html` (162, `portfolio_builder.py`).
- **Missing type hints on 59/695 signatures** (CLAUDE.md requires them on every function) —
  concentrated in `cli/main.py`'s ~20 `_handle_*(args)` handlers.

### Python — MEDIUM
- Too-many-params (PLR0913): `free_apis.py:1354` (16 params), `:1418` (14), `ai_agent.py:596` (8).
- Correctness risks: `field` loop var shadows `dataclasses.field` (`auto_apply.py:492`);
  missing `raise … from` (`auto_apply.py:899`, `free_apis.py:963`, `latex_render.py:877`);
  `zip()` without `strict=` (`latex_render.py:646,668`); late-binding loop closures
  (`free_apis.py:968`, `rss.py:32`); duplicate `"communication"` in a set (`coach.py:120`).
- DRY: duplicated GitHub-handle-resolution block (`ui/server.py:799-805` & `979-985`).
- Dead/unused: 22 unused imports (F401), unused locals (`autopilot.py:243` `tracker`,
  `followup_email.py:30` `candidate_first`); 35 vacuous f-strings (mostly `headhunter.py`).
- Magic numbers in `scorer.py` (fuzzy thresholds 85/90/70, score bands) not named constants.

### JavaScript (`app.js`, 3567 LOC) — HIGH
- **Dead duplicate function definitions:** `openStudioAsset`, `saveStudioAsset`, `applyIconPack`,
  `importGithubProject` each defined twice (lines 1542-1673 then 1791-1931); the first set is
  silently shadowed dead code. `no-redeclare` is not enabled, so lint can't catch it.
- **Swallowed errors on live-automation paths:** empty `catch {}` around auto-apply
  confirm/skip/cancel (`app.js:3520,3528,3535,3542`) — failures give the user no feedback while a
  real Playwright session is running.
- **3567-line untyped no-build-step file** (~9× the project's 400-line target) with a thin ESLint
  config as its only safety net — real long-term maintainability risk.

### JavaScript — MEDIUM
- `eslint.config.mjs` globals list omits `AbortController`/`setInterval`/`clearInterval` → 5
  false-positive `no-undef` errors that erode lint trust.
- `bindEvents()` ~430 lines with inline business logic; ~12 near-identical
  `setBusy/try/toast/finally` handlers (`app.js:721-1026`) beg for a `withBusy()` helper.

**Positive:** XSS defense in JS is solid — `escapeHtml()` used consistently before `innerHTML`,
and LLM/chat output uses `textContent`. No `eval`/`dangerouslySetInnerHTML`.

## 3. Security (python-security-auditor)

Threat model: loopback-only, single-user. Severity reflects that, with escalation notes.

### CRITICAL
- **Live secrets at rest in a cloud-synced folder.** `.env.local` holds **real, active** France
  Travail OAuth `CLIENT_ID`/`CLIENT_SECRET` and an `APPRENTISSAGE_API_TOKEN` JWT (embeds your
  email, valid to ~2027). **Good:** verified _not_ tracked in git and never committed
  (`git check-ignore` ✓, absent from history). **Bad:** the repo lives under
  `C:\Users\mihab\OneDrive\…`, so the secrets are being synced to OneDrive — contradicting the
  "keep all data local" constraint. **Rotate both now** and move `.env.local` out of OneDrive sync.

### HIGH
- **SSRF:** `intake/url.py:22` and `intake/rss.py:24,49` fetch arbitrary user URLs with no scheme
  allowlist / no private-IP block / no redirect vetting, reachable via `POST /api/add-url`. Bounded
  by loopback today; **becomes critical if `JOB_AGENT_UI_HOST=0.0.0.0`** (supported).
- **Dashboard has no auth / no CSRF / mutating ops on GET.** All `/api/*` routes are
  unauthenticated; no Origin/CSRF check; `_read_json` never validates `Content-Type`; some
  state-changing/streaming actions are on GET. A malicious local page could drive auto-apply or
  delete jobs cross-origin.

### MEDIUM
- `/file` and static serving resolve symlinks before the `relative_to(root)` containment check
  (`ui/server.py:153-167,1242-1251,626-632`) — a symlink planted in a served root could escape.
- Unbounded `int/float` parse of `limit`/`min_score` on `/api/auto-apply/preview`
  (`ui/server.py:563`) — minor local DoS; route through existing `_safe_int`.
- Broad exception swallowing around credential/token paths (`config.py:35`, `secrets.py:35`,
  France Travail token cache) can mask auth failures.

### Verified SAFE (no action)
SQL injection (parameterized throughout `db/database.py`); command injection (only
`latex_render.py` & `ollama_manage.py`, both `shell=False` list-args); server-side XSS (escaped in
`html_render.py`/`assistant_render.py`); unsafe deser (no pickle/yaml.load/eval); TLS (no
`verify=False`); secret logging (none).

### Not yet covered
- Dependency CVEs — run `pip-audit`/`bandit` (recommend adding to CI).
- A focused re-audit of `auto_apply.py`'s human-review gate (the "never auto-submit" constraint).

## 4. Test Coverage (python-test-coverage-auditor)

- **Measured line coverage: 45%** (357 unit tests pass; was 38% before a temp-dir fix) — well
  below the **80% mandated in CLAUDE.md**. e2e (Playwright, 30 tests) can't run headless here, so
  `ui/server.py` is effectively ~0% in CI.
- **Environment fault:** a corrupted/locked `%TEMP%\pytest-of-mihab` dir throws 98
  `PermissionError`s on a normal `pytest` run; `--basetemp=.pytest_tmp/bt` is the workaround. Your
  local runs have likely been silently erroring/under-reporting.

**Zero-coverage critical modules:** `autopilot.py` (0%), `ui/server.py` (0% unit / 9% e2e),
`ollama_manage.py` (0%), `maintenance.py` (0%), `analytics.py` (0%), `market_intelligence.py` (20%),
`enrichment*.py` (12-18%).

**Under-tested high-value logic:** `ai_agent.py` (20%), `coach.py` (21%), `cv_studio.py` (22%),
`profile_audit.py` (19%), `auto_apply.py` (27% — error/human-gate paths thin),
`intake/free_apis.py` (42%), `cli/main.py` (47%), `db/database.py` (54%), **`validators.py` (43%)**,
`skill_extractor.py` (37%).

**Healthy (the quality bar to hold):** scorer 90%, normalizer 86%, filters 89%, generators 88-97%,
schemas 92-100%, france_market 92%, config 92%. Tests that exist are genuinely behavioral.

## 5. Top 10 Prioritized Improvements

| # | Priority | Improvement | Evidence |
|---|----------|-------------|----------|
| 1 | CRITICAL (security) | **Rotate** the France Travail secret + Apprentissage JWT and move `.env.local` out of the OneDrive-synced path | `.env.local` cloud-synced; JWT valid to 2027 |
| 2 | CRITICAL (correctness) | Fix the two 3.12-only f-strings so the code runs on the declared Python 3.11 | `portfolio_builder.py:404`, `latex_render.py:729` |
| 3 | HIGH (security) | Add SSRF guard (scheme allowlist + private-IP block + redirect vetting) to URL/RSS intake | `intake/url.py:22`, `intake/rss.py:24,49` |
| 4 | HIGH (security) | Add Origin/CSRF defense + JSON `Content-Type` check to the dashboard; move mutating ops off GET; keep `127.0.0.1` default and warn on `0.0.0.0` | `ui/server.py` `/api/*`, `_read_json:137` |
| 5 | HIGH (testing) | Lift coverage toward 80%, P0 first: `validators.py`, `auto_apply.py` human-review gate, `db/database.py`; fix the temp-dir issue blocking local runs | 45% vs 80% mandate |
| 6 | HIGH (quality) | Introduce `logging` project-wide; stop swallowing 123 broad excepts silently | 54 files, ~5 import logging |
| 7 | HIGH (quality) | Decompose `do_POST` into a route table + per-route handlers; split the 10 oversized modules | `ui/server.py:686` (480 ln, cx 108) |
| 8 | HIGH (quality) | Add the 59 missing type hints, esp. `cli/main.py` `_handle_*(args)` | CLAUDE.md type-hint rule |
| 9 | HIGH (JS) | Delete the 4 dead duplicate `app.js` functions; enable `no-redeclare` + fix `globals` in ESLint; surface auto-apply `catch {}` errors | `app.js:1542-1673`, `eslint.config.mjs` |
| 10 | MEDIUM | Harden `/file` symlink escape, clamp GET params, dedupe the GitHub-handle block, fix bugbear correctness risks (`field` shadow, `raise…from`, `zip(strict=)`); add `pip-audit`+`bandit` to CI | §2/§3 MEDIUM items |
