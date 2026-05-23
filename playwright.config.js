// Playwright config — boots the local dashboard, runs smoke tests against it.
// Optional: skip if you do not run `npm install`. The Python pipeline does
// not depend on this file.
const path = require("path");
const { defineConfig, devices } = require("@playwright/test");

const python = process.platform === "win32"
  ? ".venv\\Scripts\\python.exe"
  : ".venv/bin/python";

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
    command: `${python} -m job_agent.ui.server --no-open`,
    env: { ...process.env, PYTHONPATH: path.join(__dirname, "src") },
    url: "http://127.0.0.1:8765",
    reuseExistingServer: true,
    timeout: 30_000,
  },
});
