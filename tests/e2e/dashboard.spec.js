// Smoke e2e test: the dashboard renders all tabs, the AI status badge appears,
// and the autopilot status endpoint responds. Run with `npm run test:e2e`.
const { test, expect } = require("@playwright/test");

test("dashboard loads and tabs are navigable", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("h1")).toContainText("Career Copilot");

  const tabs = ["search", "jobs", "autopilot", "studio", "portfolio", "coach", "insights", "add", "profile"];
  for (const name of tabs) {
    await page.click(`button.tab[data-tab="${name}"]`);
    await expect(page.locator(`#tab-${name}`)).toBeVisible();
  }

  await page.click('button.tab[data-tab="autopilot"]');
  await expect(page.locator("#autopilotMetrics")).toBeVisible();

  await page.click('button.tab[data-tab="insights"]');
  await expect(page.locator("#insightsMetrics")).toBeVisible();
});

test("portfolio builder previews and exports local static site", async ({ page, request }) => {
  await page.goto("/");
  await page.click('button.tab[data-tab="portfolio"]');
  await expect(page.locator("#portfolioPreview")).toBeVisible();
  await expect(page.locator("#portfolioHtmlEditor")).toHaveValue(/<!doctype html>/i);
  await expect(page.locator("#portfolioPath")).toContainText(".job_agent");

  const preview = await request.get("/api/portfolio/preview");
  expect(preview.ok()).toBeTruthy();
  expect(await preview.text()).toContain("<!doctype html>");
});

test("cv studio keeps assets separate from the LaTeX draft", async ({ page }) => {
  await page.goto("/");
  await page.click('button.tab[data-tab="studio"]');
  await expect(page.locator("#studioTextarea")).toHaveValue(/\\begin\{document\}/);

  await page.click('[data-asset="master_cv.json"]');
  await expect(page.locator("#studioAssetTextarea")).toHaveValue(/"contact"/);
  await expect(page.locator("#studioTextarea")).not.toHaveValue(/"contact"/);

  await page.click("#studioCompileBtn");
  await expect(page.locator("#studioNotice")).toBeHidden();
  await expect(page.locator("#studioPreview")).toHaveAttribute("src", /preview-pdf/);
});

test("ai status endpoint responds", async ({ request }) => {
  const response = await request.get("/api/ai-status");
  expect(response.ok()).toBeTruthy();
  const body = await response.json();
  expect(body).toHaveProperty("reachable");
  expect(body).toHaveProperty("base_url");
});

test("autopilot status endpoint responds", async ({ request }) => {
  const response = await request.get("/api/autopilot");
  expect(response.ok()).toBeTruthy();
  const body = await response.json();
  expect(body).toHaveProperty("running");
  expect(body).toHaveProperty("config");
});

test("failed API fetch shows the shared server-restart banner and Retry", async ({ page }) => {
  await page.goto("/");
  await page.evaluate(() => {
    window.fetch = () => Promise.reject(new TypeError("Failed to fetch"));
  });

  await page.click('button.tab[data-tab="insights"]');
  await page.click("#insightsRefreshBtn");

  const banner = page.locator("#insightsMetrics [data-connection-lost]");
  await expect(banner).toContainText(
    "Dashboard server not reachable — restart it (launch.ps1) and refresh"
  );
  await expect(banner.getByRole("button", { name: "Retry" })).toBeVisible();
  await expect(banner).not.toContainText("Failed to fetch");
});
