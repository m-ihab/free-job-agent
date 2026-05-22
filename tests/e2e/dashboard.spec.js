// Smoke e2e test: the dashboard renders all tabs, the AI status badge appears,
// and the autopilot status endpoint responds. Run with `npm run test:e2e`.
const { test, expect } = require("@playwright/test");

test("dashboard loads and tabs are navigable", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("h1")).toContainText("Paris Data Career Copilot");

  const tabs = ["search", "jobs", "autopilot", "insights", "add", "profile"];
  for (const name of tabs) {
    await page.click(`button.tab[data-tab="${name}"]`);
    await expect(page.locator(`#tab-${name}`)).toBeVisible();
  }

  await page.click('button.tab[data-tab="autopilot"]');
  await expect(page.locator("#autopilotMetrics")).toBeVisible();

  await page.click('button.tab[data-tab="insights"]');
  await expect(page.locator("#insightsMetrics")).toBeVisible();
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
