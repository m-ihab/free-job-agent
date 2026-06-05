// E2E tests for new features added in the TDD/feature session:
//   - Les Jeudis + Choose Paris Region boards in search links
//   - Recruiter outreach email (API + UI button + modal)
//   - Chrome apply session button in the Jobs toolbar
//   - Multi-source search API smoke
//   - Add-job flow (text intake)
//   - Scorer v2 API response shape
//   - Jobs tab toolbar completeness
//
// Run: npm run test:e2e
// Headed: npm run test:e2e:headed

const { test, expect } = require("@playwright/test");

// ── Search tab: new boards appear in link builder output ─────────────────────

test.describe("Search tab — French job boards", () => {
  test("search-links API includes Les Jeudis and Choose Paris Region", async ({ request }) => {
    const resp = await request.post("/api/search-links", {
      data: { query: "data scientist stage", location: "Paris", limit: 4, boards: "recommended" },
    });
    expect(resp.ok()).toBeTruthy();
    const body = await resp.json();
    expect(body).toHaveProperty("groups");
    const allLinks = body.groups.flatMap((g) => g.links);
    const boardKeys = allLinks.map((l) => l.board_key);
    expect(boardKeys).toContain("lesjeudis");
    expect(boardKeys).toContain("chooseparisregion");
    expect(boardKeys).toContain("welcome-to-the-jungle");
    expect(boardKeys).toContain("wttj-data");
  });

  test("Les Jeudis URL contains the query string", async ({ request }) => {
    const resp = await request.post("/api/search-links", {
      data: { query: "machine learning", location: "Paris", limit: 2, boards: "recommended" },
    });
    const body = await resp.json();
    const allLinks = body.groups.flatMap((g) => g.links);
    const lj = allLinks.find((l) => l.board_key === "lesjeudis");
    expect(lj).toBeDefined();
    expect(lj.url).toContain("lesjeudis.com");
    expect(lj.url).toContain("machine");
  });

  test("Choose Paris Region URL is HTTPS and contains the query", async ({ request }) => {
    const resp = await request.post("/api/search-links", {
      data: { query: "data engineer", location: "Paris", limit: 2, boards: "recommended" },
    });
    const body = await resp.json();
    const allLinks = body.groups.flatMap((g) => g.links);
    const cpr = allLinks.find((l) => l.board_key === "chooseparisregion");
    expect(cpr).toBeDefined();
    expect(cpr.url.startsWith("https://")).toBeTruthy();
    expect(cpr.url).toContain("chooseparisregion.org");
  });

  test("search links panel renders after clicking Build links", async ({ page }) => {
    await page.goto("/");
    await page.waitForSelector("#tab-search", { state: "visible" });

    // The search results containers exist in the DOM at all times
    await expect(page.locator("#manualResults")).toBeAttached();
    await expect(page.locator("#multiSourceResults")).toBeAttached();
    await expect(page.locator("#apiResults")).toBeAttached();

    // Clicking Build clean links populates #manualResults with board links
    await page.click("#linksBtn");
    await page.waitForResponse((r) => r.url().includes("/api/search-links"));
    // After the response, at least some link text should appear
    const manualText = await page.locator("#manualResults").textContent({ timeout: 10000 });
    expect(manualText.length).toBeGreaterThan(0);
  });
});

// ── Jobs toolbar: Chrome session button is present ───────────────────────────

test.describe("Jobs tab — toolbar buttons", () => {
  test("Chrome apply session button is visible in the Jobs toolbar", async ({ page }) => {
    await page.goto("/");
    await page.click('button.tab[data-tab="jobs"]');
    await expect(page.locator("#tab-jobs")).toBeVisible();
    await expect(page.locator("#chromeSessionBtn")).toBeVisible();
    await expect(page.locator("#chromeSessionBtn")).toHaveText(/Chrome apply session/i);
  });

  test("Generate packets button is in the toolbar", async ({ page }) => {
    await page.goto("/");
    await page.click('button.tab[data-tab="jobs"]');
    await expect(page.locator("#packetSelectedBtn")).toBeVisible();
  });

  test("Deduplicate jobs button is in the toolbar", async ({ page }) => {
    await page.goto("/");
    await page.click('button.tab[data-tab="jobs"]');
    await expect(page.locator("#dedupeJobsBtn")).toBeVisible();
  });
});

// ── Chrome session API: endpoint responds correctly ──────────────────────────

test.describe("Chrome session API", () => {
  test("/api/chrome-session responds with path and count", async ({ request }) => {
    const resp = await request.post("/api/chrome-session", {
      data: { min_score: 65, limit: 10 },
    });
    expect(resp.ok()).toBeTruthy();
    const body = await resp.json();
    expect(body).toHaveProperty("path");
    expect(body).toHaveProperty("count");
    expect(body).toHaveProperty("message");
    expect(typeof body.count).toBe("number");
    expect(body.path).toContain("chrome_apply_session");
  });

  test("/api/chrome-session with zero ready packets returns count 0", async ({ request }) => {
    // Fresh test DB has no ready packets
    const resp = await request.post("/api/chrome-session", {
      data: { min_score: 99, limit: 1 },
    });
    expect(resp.ok()).toBeTruthy();
    const body = await resp.json();
    expect(body.count).toBe(0);
  });

  test("Chrome session button click shows a toast", async ({ page }) => {
    await page.goto("/");
    await page.click('button.tab[data-tab="jobs"]');

    // Intercept the API call to avoid side effects in the real data dir
    await page.route("**/api/chrome-session", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ path: "/tmp/session.md", count: 0, message: "No ready packets found." }),
      });
    });

    await page.click("#chromeSessionBtn");
    // Toast should appear
    await expect(page.locator(".toast, #toast, [role=alert]").first()).toBeVisible({ timeout: 5000 });
  });
});

// ── Outreach email API + UI ───────────────────────────────────────────────────

// Synthetic job used in UI tests — avoids real-DB dependency for DOM assertions.
const MOCK_JOB_ID = "e2e-test-outreach-job-0001";
const MOCK_JOB = {
  id: MOCK_JOB_ID,
  title: "Data Scientist",
  company: "TestCo",
  location: "Paris",
  status: "SCORED",
  remote: false,
  fit_score: 78,
  fit_decision: "apply",
  tech_stack: ["python", "pandas"],
  apply_url: "https://testco.example/apply",
  recruiter_name: "Alice Martin",
  recruiter_email: "alice@testco.example",
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
};

async function mockJobsWithOutreach(page) {
  await page.route("**/api/jobs*", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ jobs: [MOCK_JOB] }),
    });
  });
}

async function mockOutreachEmail(page) {
  await page.route("**/api/generate-outreach", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        email_md: "**Subject:** Re: Data Scientist — Alice\n\n---\n\nDear Alice Martin,\n\nI am excited to apply.\n\nBest regards,\nAlice",
        recruiter_name: "Alice Martin",
        recruiter_email: "alice@testco.example",
      }),
    });
  });
}

test.describe("Outreach email — API tests", () => {
  let jobId;

  test.beforeAll(async ({ request }) => {
    const resp = await request.post("/api/add-text", {
      data: {
        text: "Data Scientist at TestCo\nParis, France\nPython, pandas, scikit-learn required.\nContact: Alice Martin\nalice.martin@testco.example",
        title: "Data Scientist",
        company: "TestCo",
        url: "https://testco.example/jobs/ds",
      },
    });
    if (resp.ok()) {
      const body = await resp.json();
      jobId = body.job?.id;
    }
  });

  test("/api/generate-outreach returns email_md when job exists", async ({ request }) => {
    test.skip(!jobId, "Job creation in beforeAll failed");
    const resp = await request.post("/api/generate-outreach", {
      data: { job_id: jobId },
    });
    expect(resp.ok()).toBeTruthy();
    const body = await resp.json();
    expect(body).toHaveProperty("email_md");
    expect(body.email_md).toContain("Subject");
    expect(body.email_md.length).toBeGreaterThan(50);
  });

  test("/api/generate-outreach returns recruiter fields", async ({ request }) => {
    test.skip(!jobId, "Job creation in beforeAll failed");
    const resp = await request.post("/api/generate-outreach", {
      data: { job_id: jobId },
    });
    const body = await resp.json();
    expect(body).toHaveProperty("recruiter_name");
    expect(body).toHaveProperty("recruiter_email");
  });

  test("/api/generate-outreach returns 400-range for missing job_id", async ({ request }) => {
    const resp = await request.post("/api/generate-outreach", {
      data: {},
    });
    expect(resp.ok()).toBeFalsy();
  });
});

test.describe("Outreach email — UI tests (mocked jobs)", () => {
  async function gotoJobsTab(page) {
    await mockJobsWithOutreach(page);
    // Capture the jobs API call fired during page init
    const jobsReady = page.waitForResponse((r) => r.url().includes("/api/jobs"));
    await page.goto("/");
    await jobsReady;
    // Now click the Jobs tab — activateTab will call renderJobs() with our mock data
    await page.click('button.tab[data-tab="jobs"]');
    await expect(page.locator("#tab-jobs")).toBeVisible();
  }

  test("Outreach button is rendered in a job row", async ({ page }) => {
    await gotoJobsTab(page);
    await expect(page.locator(`[data-action="outreach"][data-job="${MOCK_JOB_ID}"]`)).toBeVisible({ timeout: 10000 });
    await expect(page.locator(`[data-action="outreach"][data-job="${MOCK_JOB_ID}"]`)).toHaveText("Outreach");
  });

  test("Outreach button opens a modal with the email draft", async ({ page }) => {
    await mockOutreachEmail(page);
    await gotoJobsTab(page);
    await expect(page.locator(`[data-action="outreach"][data-job="${MOCK_JOB_ID}"]`)).toBeVisible({ timeout: 10000 });
    await page.locator(`[data-action="outreach"][data-job="${MOCK_JOB_ID}"]`).click();

    await expect(page.locator("#outreachModal")).toBeVisible({ timeout: 10000 });
    await expect(page.locator("#outreachContent")).toContainText("Dear Alice Martin");
    await expect(page.locator("#outreachCopyBtn")).toBeVisible();
    await expect(page.locator("#outreachRecruiterInfo")).toContainText("Alice Martin");
  });

  test("Outreach modal closes on X click", async ({ page }) => {
    await mockOutreachEmail(page);
    await gotoJobsTab(page);
    await expect(page.locator(`[data-action="outreach"][data-job="${MOCK_JOB_ID}"]`)).toBeVisible({ timeout: 10000 });
    await page.locator(`[data-action="outreach"][data-job="${MOCK_JOB_ID}"]`).click();
    await expect(page.locator("#outreachModal")).toBeVisible({ timeout: 10000 });
    await page.locator("#outreachCloseBtn").click();
    await expect(page.locator("#outreachModal")).toBeHidden();
  });
});

// ── Add Job tab: text intake flow ─────────────────────────────────────────────

test.describe("Add Job tab", () => {
  test("Add job tab is reachable and has the text input", async ({ page }) => {
    await page.goto("/");
    await page.click('button.tab[data-tab="add"]');
    await expect(page.locator("#tab-add")).toBeVisible();
    await expect(page.locator("#addTextBtn")).toBeVisible();
    await expect(page.locator("#addUrlBtn")).toBeVisible();
  });

  test("add-text API accepts a job description and returns a job object", async ({ request }) => {
    const resp = await request.post("/api/add-text", {
      data: {
        text: "ML Engineer at MegaCorp\nRemote\nPython, PyTorch, MLOps required.",
        title: "ML Engineer",
        company: "MegaCorp",
        url: "https://megacorp.example/jobs/mle",
      },
    });
    expect(resp.ok()).toBeTruthy();
    const body = await resp.json();
    expect(body).toHaveProperty("job");
    expect(body.job.title).toBe("ML Engineer");
    expect(body.job.company).toBe("MegaCorp");
    expect(body).toHaveProperty("created");
  });
});

// ── Stats / Insights API ──────────────────────────────────────────────────────

test.describe("Stats API", () => {
  test("/api/stats returns funnel and weekly data", async ({ request }) => {
    const resp = await request.get("/api/stats");
    expect(resp.ok()).toBeTruthy();
    const body = await resp.json();
    expect(body).toHaveProperty("funnel");
    expect(body).toHaveProperty("weekly");
    expect(Array.isArray(body.funnel)).toBeTruthy();
    expect(Array.isArray(body.weekly)).toBeTruthy();
  });
});

// ── Multi-source search API smoke ─────────────────────────────────────────────

test.describe("Multi-source search API", () => {
  test("/api/multi-search returns jobs, per_source, and errors keys", async ({ request }) => {
    // Use a low limit to keep the test fast
    const resp = await request.post("/api/multi-search", {
      data: {
        query: "data scientist",
        location: "Paris",
        limit: 2,
        sources: ["arbeitnow"],  // Use a fast source only
        min_relevance: 0,
        france_eu_only: false,
      },
    });
    expect(resp.ok()).toBeTruthy();
    const body = await resp.json();
    expect(body).toHaveProperty("jobs");
    expect(body).toHaveProperty("per_source");
    expect(body).toHaveProperty("errors");
    expect(Array.isArray(body.jobs)).toBeTruthy();
  });
});

// ── Jobs tab: metrics panel ───────────────────────────────────────────────────

test.describe("Jobs tab — metrics", () => {
  test("jobs metrics panel renders", async ({ page }) => {
    await page.goto("/");
    await page.click('button.tab[data-tab="jobs"]');
    await page.waitForLoadState("networkidle");
    await expect(page.locator("#jobsMetrics")).toBeAttached();
  });

  test("jobs list table wrapper is present", async ({ page }) => {
    await page.goto("/");
    await page.click('button.tab[data-tab="jobs"]');
    await expect(page.locator("#jobsTableWrap")).toBeVisible();
  });
});
