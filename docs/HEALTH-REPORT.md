# free-job-agent — Codebase Health Report

> 2026-06-23 review note:
> This report is a triage snapshot, not the current product policy source.
> The old "never auto-submit" language is stale. `FULL_AUTO` is now an owner-approved
> unattended mode when the user turns Full Auto ON for a run. Re-audit should verify:
>
> - Full Auto OFF / `FILL_AND_CONFIRM` never submits without user confirmation.
> - Full Auto ON / `FULL_AUTO` submits without per-job human interaction.
> - `FULL_AUTO` fails closed to `NEEDS_MANUAL` on CAPTCHA, login walls, anti-bot,
>   rate limits, unknown required fields, unknown factual answers, unsupported flows,
>   upload failure, unclear submit state, and detection failure.
> - Auto-apply attempts are locally audited.
> - Real Chrome profile use remains advanced opt-in and clearly warned.
>
> Keep the security/code-quality findings, but update any remediation that assumes
> Full Auto should be removed or forced into per-job confirmation.

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
| Apply | `auto_apply.py` (1046, Playwright), `apply_bridge.py`, `autopilot.py` (515) | Browser apply layer with mode toggle: Full Auto OFF = Fill & Confirm; Full Auto ON = automatic submit for eligible supported applications. |
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
- A focused re-audit of the `auto_apply/` mode toggle:
  - Full Auto OFF / `FILL_AND_CONFIRM` must wait for user submit.
  - Full Auto ON / `FULL_AUTO` must submit without per-job human interaction.
  - Full Auto must write local audit events and fail closed to `NEEDS_MANUAL` on uncertain or human-presence cases.

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
`profile_audit.py` (19%), `auto_apply.py` (27% — error/apply-mode paths thin),
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
| 5 | HIGH (testing) | Lift coverage toward 80%, P0 first: `validators.py`, `auto_apply.py` mode toggle + fail-closed handoff, `db/database.py`; fix the temp-dir issue blocking local runs | 45% vs 80% mandate |
| 6 | HIGH (quality) | Introduce `logging` project-wide; stop swallowing 123 broad excepts silently | 54 files, ~5 import logging |
| 7 | HIGH (quality) | Decompose `do_POST` into a route table + per-route handlers; split the 10 oversized modules | `ui/server.py:686` (480 ln, cx 108) |
| 8 | HIGH (quality) | Add the 59 missing type hints, esp. `cli/main.py` `_handle_*(args)` | CLAUDE.md type-hint rule |
| 9 | HIGH (JS) | Delete the 4 dead duplicate `app.js` functions; enable `no-redeclare` + fix `globals` in ESLint; surface auto-apply `catch {}` errors | `app.js:1542-1673`, `eslint.config.mjs` |
| 10 | MEDIUM | Harden `/file` symlink escape, clamp GET params, dedupe the GitHub-handle block, fix bugbear correctness risks (`field` shadow, `raise…from`, `zip(strict=)`); add `pip-audit`+`bandit` to CI | §2/§3 MEDIUM items |

---
---

# Health Report — Refresh 2026-06-27

_Generated 2026-06-27 against HEAD `71ee64b`. Scope: `src/job_agent/` (**175 modules / ~23,647 LOC Python**,
up from 79 modules / ~19,200 LOC at the 2026-06-17 snapshot) + `src/job_agent/ui/static/app.js`
(**3,988 LOC**) + tests (`tests/`, **95 files** + Playwright e2e). Method: graphify/GitNexus orientation +
four parallel passes — `python-reviewer`, `typescript-reviewer` (dashboard JS), `python-security-auditor`,
and `python-test-coverage-auditor`._

> This section is **added, not a replacement** — the 2026-06-17 report above is preserved for history.
> **Several of its findings are now resolved** (see "Deltas since 2026-06-17" below).

## 0. What changed since the last report (deltas)

| 2026-06-17 finding | Status on 2026-06-27 |
|---|---|
| CSRF / Origin / Host gaps on dashboard | ✅ **FIXED** — `ui/security.py:54` `check_request` enforces per-process token + same-origin + Host allowlist on every GET/POST |
| SSRF in URL/RSS intake | ✅ **FIXED (dashboard paths)** — `utils/net.py:90-192` scheme allowlist, private/loopback/link-local block, per-redirect re-validation, IP pinning, body cap |
| Exception leakage from `do_POST` | ✅ **FIXED** — generic 500 + `logging` (`server.py:154`) |
| Dependency hygiene (unpinned) | ✅ **FIXED** — upper-bounded deps, `requirements.lock`, CI `bandit` + `pip-audit` |
| Test coverage 45% | ✅ **IMPROVED to 83%** aggregate (but unevenly — see §4) |
| 10 oversized modules / monolith splits | ✅ **All 10 planned splits DONE** (see §1) — but **34 modules still exceed the 200-line cap** |
| `do_POST` monolith | ✅ Split into `ui/routes/*` handlers |
| Rotate FT secret / `.env.local` in OneDrive | ⚠️ **Operational — verify owner did this**; code no longer logs secrets and only `.env.local.example` is tracked |
| 3.12-only f-strings on declared 3.11 | ↪️ Not re-confirmed this pass (venv is 3.12.13, still masks it) — re-verify on a real 3.11 interpreter |

## 1. Refactor-Split Progress Audit

**The 10 originally-planned monolith splits are ALL COMPLETE** (verified on disk + git log + small facades):

| Original monolith | Facade now | Children extracted |
|---|---|---|
| `db/database.py` | 60 L | `database_schema/_jobs/_packets/_meta` (mixin pattern) |
| `auto_apply/session.py` | 143 L | `session_types/_runner/_actions/_control` |
| `ai_agent.py` | 194 L | `ai_agent_fit/_classify/_letters/_search` |
| `cv_studio.py` | 96 L | `draft/sections/suggest/fit/ats/core/assets/projects` |
| `coach.py` | 137 L | `skills/catalog/market/suggestions/interview` |
| `autopilot.py` | 196 L | `config/cycle/packets/queries/sources` |
| `auto_apply/driver.py` | — | `driver_fields/_fill/_browser` |
| `renderer/latex_render.py` | 317 L | `latex_assets/_compile/_helpers` |
| `intake/france_market.py` | — | `france_market_boards/_queries` |
| `portfolio_render.py` | — | `portfolio_core/_css/_html/_seo` |

**NOT done — the 7 "newly surfaced" optional splits** (tracked in `SESSION-HISTORY.md`, all still over the 200-line cap):
`pipeline.py` (501), `renderer/latex_helpers.py` (494), `portfolio_builder.py` (464), `ui/route_helpers.py` (446),
`intake/sources/base.py` (441), `profile_enrich.py` (402), `cv_studio_assets.py` (242).

**Additionally, ~27 other modules exceed 200 lines** that were never in any split plan — e.g. `cli/main.py` (384),
`intake/sources/registry.py` (339), `ui/server.py` (335), `profile_audit.py` (333), `polish.py` (323). **34 modules
total** violate the cap, 6 of them above 400 lines. And the dashboard **`app.js` is 3,988 lines** (grew from 3,567)
— ~5× the 800-line hard cap and ~20× the 200-line target; it is the single largest unsplit unit in the project.

**Verdict:** the deliberate split campaign succeeded (10/10), but the cap is not being held repo-wide — a second
split batch (the 7 surfaced + `app.js` by feature area) is the outstanding work.

## 2. Architecture Overview

Local-first, single-user job-search/application copilot for France/Paris data-AI roles. Python 3.11+, two entry
points (`job-agent` CLI via `cli/main.py`; dashboard via stdlib `http.server` on `127.0.0.1:8765`), SQLite, Pydantic
schemas, optional local Ollama. **Data flow:** intake (`intake/` — paste/file/URL/RSS/free APIs/France Travail/ATS
feeds) → normalize/fingerprint (`normalizer.py`, `fingerprint.py`) → hard filters + deterministic 0–100 scoring
(`filters.py`, `scorer.py`, `skill_extractor.py`) → SQLite (`db/` mixins) → packet generation (`generator/`,
`cv_studio*`, `pipeline.py`) → render (`renderer/` md/html/pdf/latex) → apply (`auto_apply/` Playwright,
`apply_bridge.py`, `autopilot*`). The post-refactor structure is markedly healthier: feature decomposition is clean,
the DB/auto-apply/AI/cv-studio cores are now small facades over focused children, and the security boundary
(`ui/security.py`, `utils/net.py`) is well-factored. Remaining structural weak points: a handful of orchestration
monoliths (`pipeline.py`, `route_helpers.py`), the JS monolith, and pervasive silent exception-swallowing.

## 3. Code Quality (`python-reviewer` + dashboard-JS `typescript-reviewer`)

> Note: there is **no first-party TypeScript**; the JS pass covered `app.js` + `eslint.config.mjs` + `playwright.config.js`.

**Python — CRITICAL**
- **Swallowed exceptions in FULL_AUTO form-filling** — `auto_apply/driver_fields.py:53,63,101,123` and the submit
  click at `driver_fill.py:183` use `except Exception: pass/continue`. A form can be submitted blank/partial with
  zero signal — directly undercuts the "answers must be grounded / fail-closed" contract. Add `logger.warning(..., exc_info=True)`.
- **`extra = "allow"` on all three core schemas** — `schemas/job.py:75`, `candidate.py:25`, `packet.py:79` accept
  arbitrary unknown fields instead of raising. Combined with **22 in-place mutations** (e.g. `pipeline.py:276,289`,
  `enrichment.py:65-79`, `db/database_jobs.py:18`) the schemas act as mutable bags, not validated boundaries. Move to
  `extra="forbid"` (`ConfigDict`) and use copy-and-save instead of mutation.

**Python — HIGH**
- AI futures swallowed without logging in the core packet loop — `pipeline.py:308,312,316` silently produce
  AI-less packets when Ollama fails. Log each.
- **34 modules > 200-line cap** (6 > 400) and **7 functions ≫ 50-line cap** — worst: `cli/main.py:38 build_parser()`
  (294 L, all sequential `add_parser` calls), `pipeline.py:239 generate_packet_for_job()` (255 L).
- **73 `# type: ignore`** suppressions, ~15 masking one real `Optional[Path]` issue: `Database(config.db_path)`
  where `db_path: Optional[Path]`. Add one assert / `resolved_db_path` property → removes 15 suppressions + a real None-deref risk.
- `portfolio_render_core.py:120-121` — dataclass fields typed `dict`/`list` but defaulting `None` behind `type: ignore`; use `| None`.
- **37 swallowed exceptions across 28 files** — incl. `autopilot_queries.py:60` (degraded queries) and `coach.py:127`
  (silent empty plan) which affect user-visible output.
- Level-9 nesting in `generator/outreach_llm.py:104` — needs guard clauses + helper extraction.

**Python — MEDIUM:** 52 `print()` calls (esp. `ui/server.py:294-309` in a server thread → use `logging`);
117 signatures missing arg type hints (route handlers `(h)` in `ui/routes/get_core.py`); duplicated
`_search_free_api_jobs()` shim in `france.py`/`search.py`; f-string SQL column construction is currently safe but
fragile (`db/database_jobs.py:56`) — guard with a `COLUMNS` constant; finish the Pydantic v1→v2 migration.

**Dashboard JS — CRITICAL**
- **`javascript:` URI passthrough into `href`** — `app.js:262,379,2425`. `escapeHtml()` does not validate URL
  protocol, so a scraped `apply_url` of `javascript:…` executes on click. Add a `safeHref()` allowlist (`http:`/`https:`)
  before interpolation — one helper closes all three sinks.

**Dashboard JS — HIGH:** unhandled promise rejections in `enrichBatch`/`studioReset`/`studioPromote`/`studioApplyReorder`
(`app.js:1095,1723,1731,2024` — no error UI, button stuck disabled); interval leak in `pullFastModel` (`app.js:2951`);
`app.js` at 3,988 lines; ESLint config too thin (`eslint.config.mjs:29-33` — add `no-console`, `eqeqeq`,
`eslint-plugin-security`). **MEDIUM/LOW:** numeric server fields into `innerHTML` un-guarded (`app.js:1934,2004`),
`escapeHtml` misses `'`, no debounce on `generatePortfolio`, 3 stray `console.*`, zero JSDoc types.

## 4. Security (`python-security-auditor`)

**Headline: no CRITICAL or HIGH issues. The 2026-06-17 HIGH findings (CSRF, SSRF, exception leakage, deps) are
fixed and correctly wired into the live request paths.** The auto-apply fail-closed contract is implemented:
`auto_apply/detect.py:61 _detect_human_wall` fails **closed** (unreadable page ⇒ treated as wall, EN+FR login
signatures); `session_runner.py` checks before fill (`:146`), before submit (`:174`), and **post-submit** (`:190`),
handing off to `NEEDS_MANUAL` (`session_actions.py:93`). Detection-only, no circumvention. SQL is parameterized
throughout; secrets read from env and never logged.

**Remaining (all LOW, defense-in-depth):**
- **N1** — `intake/discover.py:15` does a raw `requests.get(user_url)` bypassing `utils.net.safe_get`. CLI-only
  (not reachable from dashboard, so not CSRF-chainable), but would follow redirects to internal IPs with real `requests`. Route through `safe_get`.
- **N2** — GitHub handle only `strip()`-sanitized in `profile_enrich.py:64` and `portfolio_builder.py:364` (host is
  fixed to `api.github.com`, so request-shaping only, not SSRF). Apply the dashboard's `_GITHUB_HANDLE_RE`.
- **N3/N4** — FT access token cached plaintext on disk (~18-min TTL, `client_secret` never written); `languages_url`
  fetched raw from the (trusted) GitHub API response. Note-only.

_Unknowns: no live `pip-audit` CVE run this pass (CI gating exists); Jinja2 SSTI surface not exhaustively traced
(prior audit found renderer escapes untrusted text)._

## 5. Test Coverage (`python-test-coverage-auditor`)

**Measured 83% line coverage** (11,608 stmts, 1,994 missed; 1,430 passed, 0 skipped/xfail) — meets the 80% floor in
aggregate, **but coverage is dangerously uneven: the safest code (schemas/scorer/normalizer/DB mixins) is well
covered while the highest-risk behavioral code is the least covered.**

| Module | Cover | Why it matters |
|---|---:|---|
| `auto_apply/driver_fill.py` | **21%** | Actually fills/submits forms — submission logic essentially untested |
| `auto_apply/session_control.py` | **29%** | Enforces FULL_AUTO gates (max submissions, score threshold, allowed sources/ATS, skip rules) |
| `ai_agent_letters.py` | **28%** | LLM letter generation — "never invent facts" constraint unguarded by tests |
| `auto_apply/session_runner.py` | **42%** | Per-job loop + NEEDS_MANUAL handoff continuation |
| `auto_apply/session_actions.py` / `driver_fields.py` | 46% / 53% | Attempt events, state saving; field mapping (wrong-fill risk) |
| `autopilot_cycle.py` / `cv_studio_suggest.py` | 45% / 33% | No dedicated test file |
| `ui/server.py` / `ui/routes/post_generate.py` | 65% / 59% | Security-adjacent; branch-heavy |

**Gaps:** the auto-apply package — the most safety-critical code in the repo (real submission + legal "never invent /
fail-closed" invariants) — is the least tested; existing `test_auto_apply*.py` don't drive the fill/submit/control
internals. No e2e exercise of the FULL_AUTO flow (eligible job → fill → submit/handoff). Intake adapters are thin on
error/empty-response branches (`ashby` 68%, `lever` 78%, `francetravail` 75%).

**Flaky:** `tests/test_ui_security.py::test_post_without_token_returns_403` fails non-deterministically with
`ConnectionAbortedError [WinError 10053]` (real-socket timing on the in-thread live-server fixture) — makes CI
green/red non-deterministic on Windows. _Caveat: this is line, not branch, coverage (`--cov-branch` would show the
auto-apply modules even lower)._

## 6. Top 10 Prioritized Improvements (2026-06-27)

| # | Priority | Improvement | Evidence |
|---|----------|-------------|----------|
| 1 | CRITICAL (safety) | Stop swallowing form-fill/submit exceptions in FULL_AUTO — log every failure; never let a blank/partial form submit silently | `auto_apply/driver_fields.py:53,63,101,123`, `driver_fill.py:183` |
| 2 | CRITICAL (JS security) | Add `safeHref()` protocol allowlist before any server-sourced URL goes into `href` (blocks `javascript:` XSS from scraped `apply_url`) | `app.js:262,379,2425` |
| 3 | CRITICAL (correctness) | Set `extra="forbid"` on the 3 core schemas and replace the 22 in-place mutations with copy-and-save | `schemas/job.py:75`, `candidate.py:25`, `packet.py:79` |
| 4 | HIGH (testing) | Add control-gate + fail-closed unit tests for the auto-apply core (currently 21–46%) — the project's least-tested, highest-risk code | `session_control.py` 29%, `driver_fill.py` 21%, `session_runner.py` 42% |
| 5 | HIGH (observability) | Add logging to the 37 silent `except Exception: pass` blocks (start with `pipeline.py:308-319` AI futures, `autopilot_queries.py:60`, `coach.py:127`) | 37 across 28 files |
| 6 | HIGH (quality) | Finish the split campaign: the 7 surfaced modules + the 27 other >200-line modules; split `app.js` by feature area | §1; 34 modules over cap |
| 7 | HIGH (types) | Fix the `Optional[Path]` root cause (`assert`/`resolved_db_path`) to delete ~15 `# type: ignore`; add the 117 missing arg hints | `pipeline.py:48`, `ui/routes/get_core.py:40+` |
| 8 | HIGH (JS) | Wrap the 4 unhandled `await api()` calls in try/catch + error UI; fix the `pullFastModel` interval leak; tighten ESLint | `app.js:1095,1723,1731,2024,2951`, `eslint.config.mjs` |
| 9 | MEDIUM (CI reliability) | Stabilize the WinError-10053 flake in `test_ui_security.py` (wait-for-ready / WSGI-style call) so CI signal is deterministic | `tests/test_ui_security.py` live-server fixture |
| 10 | MEDIUM (security hardening) | Route `discover.py` through `safe_get` (N1); apply `_GITHUB_HANDLE_RE` in the 2 CLI/import GitHub paths (N2); replace `ui/server.py` thread `print()`s with `logging` | `intake/discover.py:15`, `profile_enrich.py:64`, `portfolio_builder.py:364`, `ui/server.py:294-309` |
