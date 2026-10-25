import { defineConfig, devices } from "@playwright/test";

// Runs against a real API seeded with `python -m app.seed` (see the CI e2e job).
export default defineConfig({
  testDir: "e2e",
  fullyParallel: false, // the review test changes shared demo data
  retries: process.env.CI ? 1 : 0,
  use: { baseURL: "http://localhost:3000", trace: "retain-on-failure" },
  projects: [
    // Signs in once: the API rate-limits logins per account (5 at once, then 1 a minute).
    { name: "setup", testMatch: /auth\.setup\.ts/ },
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"], storageState: "test-results/.auth.json" },
      dependencies: ["setup"],
    },
  ],
  webServer: {
    command: "npm run start",
    url: "http://localhost:3000/login",
    reuseExistingServer: !process.env.CI,
    env: { API_URL: process.env.API_URL ?? "http://localhost:8000", DEMO_LOGIN: "1" },
  },
});
