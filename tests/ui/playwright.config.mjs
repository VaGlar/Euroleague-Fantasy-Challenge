// UI tests: both editions on a desktop, an iPhone-sized screen and two Android phones.
// Run: cd tests/ui && npm ci && npx playwright test   (browsers: npx playwright install chromium)
import { defineConfig, devices } from "@playwright/test";

const PORT = 8799;
const iphone = { ...devices["iPhone 13"] };
delete iphone.defaultBrowserType;           // Chromium with the iPhone's screen, touch and user agent

export default defineConfig({
  testDir: ".",
  timeout: 45_000,
  fullyParallel: true,
  workers: process.env.CI ? 2 : undefined,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    locale: "el-GR",
    timezoneId: "Europe/Athens",
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    launchOptions: process.env.PW_CHROMIUM ? { executablePath: process.env.PW_CHROMIUM } : {},
  },
  projects: [
    { name: "pc", use: { viewport: { width: 1280, height: 900 } } },
    { name: "iphone", use: iphone },
    { name: "android", use: devices["Pixel 7"] },               // Chrome on Android is Chromium: close to the real thing
    { name: "android-small", use: devices["Galaxy S9+"] },      // 320px wide: the narrowest phones still around
  ],
  webServer: {
    command: `python3 serve.py ${PORT}`,
    url: `http://127.0.0.1:${PORT}/public/index.html`,
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
});
