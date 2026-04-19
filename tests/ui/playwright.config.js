const { defineConfig } = require("@playwright/test");

module.exports = defineConfig({
  testDir: ".",
  testMatch: "**/*.spec.js",
  timeout: 30_000,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: process.env.TEST_BASE_URL ?? "http://localhost:8000",
    headless: true,
    screenshot: "only-on-failure",
    video: "off",
  },
});
