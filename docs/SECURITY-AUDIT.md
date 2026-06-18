# Security Audit — free-job-agent

_Audit date: 2026-06-18 · Method: `python-security-auditor` · Severity ranking: `triaging-security-incident` (P1–P4)_

## Scope & assumptions

- Audited Python source under `src/job_agent/`, the bundled `src/requests.py`
  fallback HTTP shim, dependency manifests (`requirements.txt`, `pyproject.toml`),
  and `.gitignore` / `.env.local.example`.
- The product is **local-first**: the dashboard binds `127.0.0.1:8765` by
  default and the threat model assumes a single trusted local user. Several
  findings are conditional on that assumption being weakened (non-loopback bind,
  or a malicious website open in the user's browser while the dashboard runs).
- Network dependency scanning was **not** executed; CVE confirmation requires
  running `pip-audit` (see verification).
- Severity uses the triaging P1–P4 matrix (P1 Critical … P4 Low) and NIST
  incident categories. This is a code audit, so "exploit path" replaces "alert".

---

## Findings (ordered by severity)

### F1 — No CSRF / Origin / Host validation on state-changing dashboard endpoints — **P2 High**
- **Category:** Web Application Attack (CSRF) / Improper Access Control
- **Location:** `src/job_agent/ui/server.py` — `do_POST` (lines 686–1161),
  `_read_json` (137–142), `main`/`run_server` (1270–1293).
- **Exploit path:** `do_POST` dispatches on path only. There is no CSRF token,
  no `Origin`/`Referer` check, no `Host`-header allow-list, and Content-Type is
  not enforced (`_read_json` just reads `Content-Length` and `json.loads`).
  A cross-site `fetch()` with `Content-Type: text/plain` is a CORS "simple
  request" (no preflight), so **any website the user visits while the dashboard
  is running can POST** to e.g. `/api/auto-apply/start`, `/api/add-url`,
  `/api/delete-job`, `/api/autopilot/start`. The 127.0.0.1 bind is the only
  control, and it is bypassable via DNS rebinding, or removed entirely when the
  user sets `JOB_AGENT_UI_HOST=0.0.0.0` / `--host`. Because these endpoints can
  drive a real browser and submit job applications (F3) and fetch arbitrary URLs
  (F2), the blast radius is high.
- **Remediation:** Reject POSTs whose `Origin`/`Referer` is not the local app;
  validate the `Host` header against an allow-list (`127.0.0.1:<port>`,
  `localhost:<port>`) to defeat DNS rebinding; require a same-origin custom
  header or per-session CSRF token minted in `index.html`. Refuse to bind a
  non-loopback host without an explicit opt-in flag and a printed warning.

### F2 — SSRF via `/api/add-url`; `file://` reachable through the fallback HTTP shim — **P2 High**
- **Category:** Web Application Attack (SSRF)
- **Location:** `src/job_agent/ui/server.py` `do_POST` `/api/add-url` (699–707) →
  `add_url_job` → `src/job_agent/intake/url.py` `ingest_url` (22–33);
  fallback client `src/requests.py` `_request`/`get` (79–122).
- **Exploit path:** `ingest_url` does `requests.get(url, …)` on a
  caller-supplied URL with **no scheme or host allow-listing** and default
  redirect following, so it can reach internal services, `localhost`, or cloud
  metadata (`169.254.169.254`). Chained with F1 (no CSRF), a remote page can
  trigger internal fetches. Worse: when the third-party `requests` package is
  absent, the bundled `src/requests.py` shim calls `urllib.request.urlopen`,
  which **honors `file://` (and `ftp://`)** — a `file:///C:/…` URL becomes a
  local file read. The response text is stored as the job's `raw_text`,
  creating an exfiltration sink.
- **Remediation:** Allow only `http`/`https`; resolve the host and block
  private/loopback/link-local/reserved IP ranges before connecting (re-check
  after each redirect, or disable redirects); cap response size. In
  `src/requests.py`, explicitly reject non-`http(s)` schemes in `_request`.

### F3 — `FULL_AUTO` auto-submits applications; `USE_REAL_CHROME_PROFILE` exposes live sessions — **P3 Medium**
- **Category:** Improper Usage / Safety-constraint risk
- **Location:** `src/job_agent/auto_apply.py` — `ApplyMode.FULL_AUTO` flow
  (283–311), `_select_browser_profile` (811–837), `_find_chrome_profile`
  (874–885), `_launch_browser_context` (840–871).
- **Exploit path:** `CLAUDE.md` states "Never auto-submit applications without
  human review." `FULL_AUTO` fills and clicks submit after only a 10-second
  cancel window (no affirmative human confirmation), which weakens that
  guarantee — especially if started via F1. Separately,
  `JOB_AGENT_AUTO_APPLY_USE_REAL_CHROME_PROFILE=1` drives the user's **real**
  Chrome profile, exposing all logged-in cookies/sessions to the automation and
  to any page it navigates to (`page.goto(apply_url)` with an untrusted listing
  URL).
- **Remediation:** Require explicit per-run confirmation for `FULL_AUTO` (or
  gate it behind a setting), and ensure it is never reachable via an
  unauthenticated POST once F1 is fixed. Document the real-profile risk and keep
  the dedicated profile the default (it already is).

### F4 — Dependency hygiene: floor-only pins, no lockfile, no vulnerability scan in CI — **P3 Medium**
- **Category:** Supply-chain / Vulnerability Management
- **Location:** `requirements.txt` (all entries `>=`), `pyproject.toml`
  dependencies (10–29).
- **Exploit path:** Every dependency is unbounded (`requests>=2.31`,
  `pillow>=10.0`, `jinja2>=3.1`, `beautifulsoup4>=4.12`, `reportlab>=4.0`,
  `feedparser>=6.0`, `openpyxl>=3.1`, `playwright>=1.40`). No lockfile and no
  `pip-audit`/`safety` gate means builds are non-reproducible and a vulnerable
  or malicious future release can be pulled silently. `pillow` and `jinja2` in
  particular have a history of CVEs; concrete exposure depends on the installed
  versions. `pydantic>=1.10` straddles v1/v2 (code imports `pydantic.v1`),
  which is fragile.
- **Remediation:** Generate and commit a lockfile (`pip-compile`/`uv lock`);
  add `pip-audit` to CI; add upper bounds or pin majors; pin `pydantic` to a
  single major. If `jinja2` renders any non-author-controlled template, confirm
  autoescape is on.

### F5 — Internal exception messages returned to HTTP clients — **P4 Low**
- **Category:** Information Disclosure
- **Location:** `src/job_agent/ui/server.py` `do_POST` catch-all
  (1164–1165: `return self._send_error_json(str(exc), 500)`); similar `str(exc)`
  surfacing in `_enrich_batch` (249–250) and `_api_search` paths.
- **Exploit path:** Raw exception strings (which may include filesystem paths or
  internal state) are returned to the caller. Low impact on a single-user
  localhost app, but elevated if F1/non-loopback bind exposes the surface.
- **Remediation:** Return a generic error to the client; log details
  server-side via `logging`.

### F6 — Broad `except Exception: pass` swallowing across modules — **P4 Low**
- **Category:** Reliability / defensive-coding (security-adjacent)
- **Location:** e.g. `auto_apply.py` (217–218, 369–373, 533–534, 591–594),
  `ui/server.py` AI-cache saves (921–922, 936–939), `config`/profile loads.
- **Note:** Not directly exploitable, but silent failures can mask security-
  relevant errors (e.g. a failed status update after submit). Narrow the catches
  and log at `warning`/`debug`.

### Positive findings (no action required)
- **Secrets handling is sound.** `.env.local` is gitignored (`git check-ignore`
  confirms) and **not tracked** (`git ls-files` shows only `.env.local.example`,
  which contains empty placeholders). No hardcoded secrets in source. `secrets.py`
  loads env files into `os.environ` without logging values, and respects
  pre-existing env (no clobber unless `override=True`).
- **Path traversal is handled** on file-serving routes: `_file_response_path`
  (153–167), `_send_static` (1242–1251), and the portfolio asset route (626–632)
  all use `resolve()` + `relative_to()` / `parents` containment checks.
- **Numeric input is clamped** via `_safe_int` (145–150).
- **LaTeX injection is mitigated:** untrusted text is escaped via `_escape_latex`/
  `_inline_latex` before insertion, and `compile_latex_to_pdf` (849–898) does
  **not** pass `-shell-escape` and enforces a 120s timeout. No `subprocess`
  `shell=True`, no `eval`/`exec`/`pickle`/`yaml.load`, no `verify=False` found.

---

## Severity summary

| ID | Finding | Severity | Category |
|----|---------|----------|----------|
| F1 | No CSRF/Origin/Host validation on dashboard | P2 High | CSRF / Access Control |
| F2 | SSRF via add-url; `file://` via fallback shim | P2 High | SSRF |
| F3 | FULL_AUTO submit + real-Chrome-profile exposure | P3 Medium | Improper Usage |
| F4 | Unpinned deps, no lockfile, no pip-audit | P3 Medium | Supply Chain |
| F5 | Exception messages leaked to client | P4 Low | Info Disclosure |
| F6 | Broad exception swallowing | P4 Low | Reliability |

Recommended remediation order: **F1 → F2** (they compound), then **F4**, **F3**,
then **F5/F6**.

---

## Verification commands (for the remediation phase)

```bash
pip install pip-audit
pip-audit -r requirements.txt          # concrete CVEs for installed deps
ruff check . ; mypy src/               # static checks
pytest -q                              # existing suite (307 tests per repo)
# Manual SSRF probe (after fix): POST /api/add-url with file:///… and an
# internal IP should be rejected.
# Manual CSRF probe (after fix): cross-origin fetch to /api/* should 403.
```

---

## Remaining risks / unknowns

- **Concrete dependency CVEs** are unconfirmed without running `pip-audit`
  against the actually-installed versions (F4).
- **GitHub-handle handling** (`portfolio_builder.fetch_github_repos`,
  `profile_enrich.enrich_from_github`) builds `api.github.com` URLs from a
  user-supplied handle; handle sanitization was not fully traced — worth a
  follow-up to confirm a handle cannot inject path/query segments.
- Whether `jinja2` ever renders non-author-controlled templates (SSTI surface)
  was not exhaustively traced.
