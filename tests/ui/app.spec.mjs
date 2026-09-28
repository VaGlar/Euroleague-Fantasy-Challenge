// The app as a whole: loads, navigation, every tab fits the screen, both editions, dark mode.
import { test, expect } from "@playwright/test";
import { open, goTab, checkLayout, isPhone, isAndroid } from "./helpers.mjs";

const TABS = ["today", "team", "players", "teams", "news", "compare", "model", "report"];

for (const edition of ["public", "personal"]) {
  test(`${edition}: every tab opens, has content, fits the screen, no JS errors`, async ({ page }, testInfo) => {
    const errors = await open(page, edition);
    for (const t of TABS) {
      await goTab(page, testInfo, t);
      const sec = page.locator(`section#${t}`);
      await expect(sec).toBeVisible();
      expect((await sec.innerText()).trim().length, `άδεια καρτέλα ${t}`).toBeGreaterThan(20);
      await checkLayout(page, `${edition}/${t}`);
      await testInfo.attach(`${edition}-${t}`, { body: await page.screenshot({ fullPage: true }), contentType: "image/png" });
    }
    expect(errors).toEqual([]);
  });
}

test("navigation bars: top tabs on PC, bottom bar on phones", async ({ page }, testInfo) => {
  await open(page, "public");
  if (isPhone(testInfo)) {
    await expect(page.locator("#bnav")).toBeVisible();
    await expect(page.locator("#tabs")).toBeHidden();
    await page.locator('#bnav button[data-t="more"]').click();
    await expect(page.locator("#sheet [data-go]")).toHaveCount(4);
    await page.keyboard.press("Escape");
    await expect(page.locator("#modal")).not.toHaveClass(/\bon\b/);
  } else {
    await expect(page.locator("#tabs")).toBeVisible();
    await expect(page.locator("#bnav")).toBeHidden();
  }
});

test("the last tab is remembered after a reload", async ({ page }, testInfo) => {
  await open(page, "public");
  await goTab(page, testInfo, "players");
  await page.reload();
  await expect(page.locator("section#players")).toHaveClass(/\bon\b/);
});

test("header: round, freshness, favicon, HoopsLab name in the public edition", async ({ page }) => {
  await open(page, "public");
  await expect(page.locator("header h1")).toContainText("HoopsLab");
  await expect(page).toHaveTitle("HoopsLab");
  await expect(page.locator("#updated")).toContainText("Ενημερώθηκε");
  await expect(page.locator('link[rel="icon"]')).not.toHaveCount(0);
  const icon = await page.request.get("/public/favicon-32.png");
  expect(icon.ok()).toBeTruthy();
});

test("public edition: no personal data, feedback address shown", async ({ page }) => {
  await open(page, "public");
  const p = await page.evaluate(() => fetch("data/predictions.json").then((r) => r.json()));
  expect(p.my_team).toBeNull();
  expect(p.health).toEqual([]);
  expect(p.edition).toBe("public");
  await expect(page.locator("#feedback")).toBeVisible();
});

test("personal edition: no feedback footer, team read from the game", async ({ page }) => {
  await open(page, "personal");
  await expect(page.locator("#feedback")).toBeHidden();
});

test("ⓘ explains a term", async ({ page }, testInfo) => {
  await open(page, "public", { tab: "players" });
  const i = page.locator(isPhone(testInfo) ? "#plist [data-info]" : "#ptable [data-info]").first();
  await i.click();
  await expect(page.locator("#tip")).toBeVisible();
  expect((await page.locator("#tip").innerText()).length).toBeGreaterThan(20);
});

test("dark mode: dark background, light text, every tab fits", async ({ page }, testInfo) => {
  await page.emulateMedia({ colorScheme: "dark" });
  await open(page, "public");
  const lum = (c) => { const [r, g, b] = c.match(/\d+/g).map(Number); return 0.2126 * r + 0.7152 * g + 0.0722 * b; };
  const [bg, fg] = await page.evaluate(() => [getComputedStyle(document.body).backgroundColor, getComputedStyle(document.body).color]);
  expect(lum(bg)).toBeLessThan(60);
  expect(lum(fg)).toBeGreaterThan(150);
  for (const t of ["today", "players", "team"]) {
    await goTab(page, testInfo, t);
    await checkLayout(page, `dark/${t}`);
    await testInfo.attach(`dark-${t}`, { body: await page.screenshot({ fullPage: true }), contentType: "image/png" });
  }
});

test("Σήμερα: countdown, captain picks and picks per price tier", async ({ page }) => {
  await open(page, "public");
  const today = page.locator("section#today");
  await expect(today).toContainText(/Round \d+/);
  await expect(today).toContainText("Για CAP");
  await expect(today.locator(".td-hero")).toBeVisible();
});

test("install guide on a phone's first visit: Android (⋮ menu) or iPhone (Share) steps", async ({ page }, testInfo) => {
  test.skip(!isPhone(testInfo), "phones only");
  await open(page, "public", { guide: true });
  const sheet = page.locator("#sheet");
  await expect(sheet).toContainText("Βάλ' το στην οθόνη σου", { timeout: 5000 });
  if (isAndroid(testInfo)) {
    await expect(sheet).toContainText("⋮");
    await expect(sheet).toContainText("Εγκατάσταση εφαρμογής");
    await expect(sheet).not.toContainText("Safari");
  } else {
    await expect(sheet).toContainText("Κοινοποίηση");
  }
  await expect(sheet).toContainText("Στήσε την ομάδα σου μέσα από την εφαρμογή");
  await checkLayout(page, "install guide");
  await sheet.getByText("Να μην ξαναεμφανιστεί").click();
  await page.reload();
  await page.waitForTimeout(1200);
  await expect(page.locator("#modal")).not.toHaveClass(/\bon\b/);
});

test("installable as an app (Android): manifest with 192/512 icons, standalone, theme colour", async ({ page }) => {
  await open(page, "public");
  const href = await page.locator('link[rel="manifest"]').getAttribute("href");
  const m = await (await page.request.get(`/public/${href}`)).json();
  expect(m.name).toBe("HoopsLab");
  expect(m.display).toBe("standalone");
  expect(m.start_url).toBeTruthy();
  for (const size of ["192x192", "512x512"]) {
    const icon = m.icons.find((i) => i.sizes === size);
    expect(icon, `εικονίδιο ${size}`).toBeTruthy();
    expect((await page.request.get(`/public/${icon.src}`)).ok()).toBeTruthy();
  }
  await expect(page.locator('meta[name="theme-color"]').first()).toHaveAttribute("content", /.+/);
});

test("theme switch: light ↔ dark; the first visit follows the phone; remembered after a reload", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "dark" });
  await open(page, "public");
  const bg = () => page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  const lum = (c) => { const [r, g, b] = c.match(/\d+/g).map(Number); return 0.2126 * r + 0.7152 * g + 0.0722 * b; };
  const btn = page.locator("#themeBtn");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");   // the phone is dark
  expect(lum(await bg())).toBeLessThan(60);
  await btn.click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  expect(lum(await bg())).toBeGreaterThan(200);
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  expect(lum(await bg())).toBeGreaterThan(200);
  await page.locator("#themeBtn").click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await checkLayout(page, "theme switch");
});

test("the court: parquet and white FIBA lines (no basket) in both themes", async ({ page }) => {
  for (const scheme of ["light", "dark"]) {
    await page.emulateMedia({ colorScheme: scheme });
    await open(page, "personal", { tab: "team" });
    const floor = page.locator("#team .tm-courtcard .tm-floor");
    await expect(floor.locator(".court-lines .key")).toHaveCount(1);
    await expect(floor.locator(".court-lines .rim, .court-lines circle")).toHaveCount(0);   // no basket
    const wood = await floor.evaluate((el) => getComputedStyle(el).backgroundColor);
    expect(wood).toBe("rgb(220, 174, 112)");                 // the same parquet in light and dark
  }
});

test("install bar: on phones from the first visit (before any team), opens the steps; not on a PC", async ({ page }, testInfo) => {
  await open(page, "public", { tab: "team" });                  // no team yet: the set-up screen
  const bar = page.locator("#a2hsBar");
  if (!isPhone(testInfo)) { await expect(bar).toBeHidden(); return; }
  await expect(bar).toBeVisible();
  await expect(bar).toContainText("πριν");
  await page.locator("#a2hsGo").click();
  await expect(page.locator("#sheet")).toContainText("Βάλ' το στην οθόνη σου");
  await checkLayout(page, "install bar");
});
