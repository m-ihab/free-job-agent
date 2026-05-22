// Playwright config — boots the local dashboard, runs smoke tests against it.
// Optional: skip if you do not run `npm install`. The Python pipeline does
// not depend on this file.
const { defineConfig, devices } = require("@playwright/test");

module.exports = defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false,
  retries: 0,
  timeout: 60_000,
  use: {
    baseURL: "http://127.0.0.1:8765",
    headless: true,
    viewport: { width: 1280, height: 800 },
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
  ],
  webServer: {
    command: "python -m job_agent.cli.main ui --no-open",
    url: "http://127.0.0.1:8765",
    reuseExistingServer: true,
    timeout: 30_000,
  },
});
