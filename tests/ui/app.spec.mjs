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
    await expect(page.locator("#sheet [data-go]")).toHaveCount(5);          // news, compare, model, report, «Σχετικά»
    await expect(page.locator('#sheet [data-go="about"]')).toHaveCount(1);
    await page.keyboard.press("Escape");
    await expect(page.locator("#modal")).not.toHaveClass(/\bon\b/);
    await open(page, "personal");                                         // no «Σχετικά» in the personal edition
    await page.locator('#bnav button[data-t="more"]').click();
    await expect(page.locator("#sheet [data-go]")).toHaveCount(4);
    await expect(page.locator('#sheet [data-go="about"]')).toHaveCount(0);
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

test("header: round, freshness, favicon, Coach Dime name in the public edition", async ({ page }) => {
  await open(page, "public");
  await expect(page.locator("header h1")).toContainText("Coach Dime");
  await expect(page).toHaveTitle("Coach Dime");
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

test("Σήμερα: no «Invalid time value» when the browser writes en-CA dates as M/D/Y", async ({ page }) => {
  // some browser versions format en-CA as 10/16/2026, not 2026-10-16: the page must not depend on it
  // (format is a getter on the prototype: wrap the constructor and give en-CA instances their own format)
  await page.addInitScript(() => {
    const DTF = Intl.DateTimeFormat;
    function MDY(locales, options) {
      const f = new DTF(locales, options);
      if (String(locales).startsWith("en-CA")) {
        const fmt = f.format;
        Object.defineProperty(f, "format", { value: (d) => fmt(d).replace(/^(\d{4})-(\d{2})-(\d{2})$/, "$2/$3/$1") });
      }
      return f;
    }
    MDY.prototype = DTF.prototype;
    MDY.supportedLocalesOf = DTF.supportedLocalesOf;
    Intl.DateTimeFormat = MDY;
  });
  const errors = await open(page, "public");
  await expect(page.locator("#updated")).toContainText(/επόμενη ενημέρωση \S+ \d{2}:\d{2}/);
  await expect(page.locator("section#today .td-hero")).toBeVisible();
  expect(errors).toEqual([]);
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
  expect(m.name).toBe("Coach Dime");
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

test("players new to the EuroLeague with few games are marked «νέος · N ματς», explained, and flagged in trades", async ({ page }, testInfo) => {
  await open(page, "public", { tab: "players" });
  const pill = page.locator(isPhone(testInfo) ? "#plist .tag.t-new.few" : "#ptable .tag.t-new.few").first();
  await expect(pill).toHaveText("NEW");                                   // a tag, as PICK; the games in its title
  await expect(pill).toHaveAttribute("title", "νέος · 1 ματς");
  await pill.click();
  await expect(page.locator("#tip")).toContainText("αβέβαιη");
  await goTab(page, testInfo, "today");
  await expect(page.locator("#today .note-early")).toContainText("Αρχή σεζόν");
});

test("Μοντέλο: the autopilot card (points vs the average manager; the owner's own points only in the personal edition)", async ({ page }, testInfo) => {
  for (const edition of ["personal", "public"]) {
    await open(page, edition, { tab: "model" });
    const card = page.locator("#model .card").first();
    await expect(card).toContainText("Autopilot");
    await expect(card).toContainText("164.5");
    await expect(card).toContainText("+18.4");                      // 151.2 raw vs 132.8 average manager
    await expect(card).toContainText("Για το Round");
    await expect(card.locator(".court")).toHaveCount(1);             // the round's team on the court
    await expect(card.locator(".court .chip")).toHaveCount(5);
    await expect(card).toContainText("Πριν το T2: μπήκαν");          // the T1 -> T2 changes
    await expect(card).toContainText("Κινήσεις του autopilot");      // every round's trades
    await expect(card.locator(".ap-mv")).toHaveCount(2);
    await expect(card).toContainText("#45.123");                    // its rank in the game's standings
    await expect(card.locator("th", { hasText: "xFPT" })).toHaveCount(1);   // what the model expected, per round
    await expect(card).toContainText("top 13% από 336.908");
    if (edition === "personal") {
      await expect(card).toContainText("138.8");
      await expect(card).toContainText("εσύ #98.803");
    } else {
      await expect(card).not.toContainText("Εσύ");
      await expect(card).not.toContainText("εσύ #");
    }
    await expect(card.locator(".court .chip.chg")).toHaveCount(0);   // no marks for the changes between turns
    await checkLayout(page, `autopilot ${edition}`);
  }
});

test("Μοντέλο: accuracy in boxes with ⓘ, the backtest folded", async ({ page }) => {
  await open(page, "public", { tab: "model" });
  const acc = page.locator("#model .card", { hasText: "πρόβλεψη vs πραγματικότητα" });
  for (const k of ["μέσο σφάλμα", "Spearman", "top-20", "προβλέψεις"]) await expect(acc.locator(".kpi", { hasText: k })).toHaveCount(1);
  await acc.locator('.kpi [data-info="acc_n"]').click();
  await expect(page.locator("#tip")).toContainText("πριν το τζάμπολ");
  const adv = page.locator("#model details", { hasText: "Για προχωρημένους" });
  await expect(adv).toHaveCount(1);
  await expect(adv).not.toHaveAttribute("open", "");
  await adv.locator("summary").click();
  await expect(adv).toContainText("Points ομάδας ανά Round");          // squad points, not error tables
  await expect(adv.locator("tr", { hasText: "Μοντέλο" })).toContainText("149.9");
});

test("Άμυνες: no footnote, ⓘ on the title, a column sorts both ways", async ({ page }) => {
  await open(page, "public", { tab: "teams" });
  await page.locator('#teams .seg button[data-tv="defense"]').click();
  const card = page.locator("#teams .card", { hasText: "PIR που δίνει η άμυνα" });
  await expect(card.locator("p.muted")).toHaveCount(0);
  await expect(card.locator('h2 [data-info="defense"]')).toHaveCount(1);
  const first = () => page.locator("#dtable tbody tr").first().getAttribute("data-team");
  const th = () => page.locator('#dtable th[data-dk="Guard"]');
  await th().click();
  await expect(th()).toContainText("↓");
  const most = await first();
  await th().click();
  await expect(th()).toContainText("↑");
  expect(await first()).not.toEqual(most);
});

test("«Σχετικά»: what it is, privacy, contact — in the public edition only", async ({ page }, testInfo) => {
  await open(page, "public", { tab: "today" });
  await goTab(page, testInfo, "about");
  const about = page.locator("section#about");
  await expect(about).toContainText("Δεν έχει σχέση με την EuroLeague ούτε με το Dunkest");
  await expect(about).toContainText("Απόρρητο");
  await expect(about.locator('a[href^="mailto:"]')).toHaveCount(1);
  await checkLayout(page, "about");
  await open(page, "personal", { tab: "today" });
  await expect(page.locator('#tabs button[data-t="about"]')).toBeHidden();
});

test("«Ανάφερε πρόβλημα»: an email with the tab, round and data time written; the page's errors are reported", async ({ page }, testInfo) => {
  const sent = [];
  await page.route("**/api/errors", async (route) => { sent.push(route.request().postDataJSON()); await route.fulfill({ status: 204 }); });
  await open(page, "public", { tab: "today" });
  await expect(page.locator('#feedback button:has-text("Ανάφερε πρόβλημα")')).toBeVisible();
  await page.evaluate(() => window.dispatchEvent(new ErrorEvent("error", { message: "Uncaught Error: ui-test boom", filename: location.origin + "/public/team.js?v=1", lineno: 42 })));
  await expect.poll(() => sent.length).toBe(1);
  expect(sent[0]).toMatchObject({ msg: expect.stringContaining("ui-test boom"), src: "team.js", line: 42, tab: "today", edition: "public" });
  const mail = decodeURIComponent(await page.evaluate(() => problemMail()));
  expect(mail).toContain("mailto:");
  expect(mail).toContain("Tab: today");
  expect(mail).toMatch(/Round: \d+/);
  expect(mail).toContain("ui-test boom");
  await page.evaluate(() => window.dispatchEvent(new ErrorEvent("error", { message: "Uncaught Error: ui-test boom", filename: location.origin + "/public/team.js?v=1", lineno: 42 })));   // the same error: sent once
  await page.waitForTimeout(300);
  expect(sent.length).toBe(1);
});
