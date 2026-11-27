import { defineConfig } from "@playwright/test";

// The API + built site start from serve.py (a throwaway data folder). One browser, one worker: the journeys change
// stories (Remake, Discard), so they run in order against the same seeded data.
export default defineConfig({
  testDir: ".",
  timeout: 30_000,
  retries: 0,
  workers: 1,
  reporter: [["list"]],
  use: { baseURL: "http://127.0.0.1:8799", trace: "retain-on-failure" },
  webServer: {
    command: `${process.env.PYTHON ?? "python"} serve.py`,
    url: "http://127.0.0.1:8799/api/health",
    timeout: 60_000,
    reuseExistingServer: false,
    stdout: "pipe",
  },
});
