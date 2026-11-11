// The English page: ΕΛ/EN next to the theme switches the language (remembered); in English no Greek is
// left on any tab, sheet or menu, except the AI texts of a digest written before English existed.
import { test, expect } from "@playwright/test";
import { open, goTab, buildTeam, isPhone } from "./helpers.mjs";

// visible Greek text and Greek titles/labels, without the AI summary, the articles' titles, the bot's status
// lines for the owner (personal edition) and the ΕΛ button
const greekLeft = (page) => page.evaluate(() => {
  const out = new Set();
  const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n; (n = w.nextNode());) {
    const el = n.parentElement;
    if (!el || !el.getClientRects().length || el.closest(".msg, .news, .nt, .health, #langBtn, svg, script, style")) continue;
    if (/[Ͱ-Ͽ]/.test(n.nodeValue)) out.add(n.nodeValue.trim().slice(0, 80));
  }
  document.querySelectorAll("[title], [aria-label], [placeholder]").forEach((el) => {
    if (el.id === "langBtn") return;
    for (const a of ["title", "aria-label", "placeholder"]) {
      const v = el.getAttribute(a);
      if (v && /[Ͱ-Ͽ]/.test(v)) out.add(`@${a}: ${v.slice(0, 60)}`);
    }
  });
  return [...out];
});

async function english(page, edition) {
  const errors = await open(page, edition, { tab: "today" });
  await expect(page.locator("#langBtn")).toHaveText("EN");          // a Greek browser starts in Greek
  await page.locator("#langBtn").click();
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  await expect(page.locator("#langBtn")).toHaveText("ΕΛ");
  return errors;
}

for (const edition of ["public", "personal"]) {
  test(`${edition}: in English no Greek is left on the tabs`, async ({ page }, testInfo) => {
    const errors = await english(page, edition);
    for (const t of ["today", "team", "players", "teams", "compare", "model", "about"]) {
      if (edition === "personal" && t === "about") continue;
      await goTab(page, testInfo, t);
      expect(await greekLeft(page), t).toEqual([]);
    }
    expect(errors).toEqual([]);
  });
}

test("the language is remembered and ΕΛ brings Greek back", async ({ page }) => {
  await english(page, "public");
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  await expect(page.locator("#updated")).toContainText("Updated");
  await page.locator("#langBtn").click();
  await expect(page.locator("html")).toHaveAttribute("lang", "el");
  await expect(page.locator("#updated")).toContainText("Ενημερώθηκε");
});

test("English team: set-up, the steps, the options menu and a player's sheet have no Greek", async ({ page }, testInfo) => {
  const errors = await english(page, "public");
  await goTab(page, testInfo, "team");
  expect(await greekLeft(page), "set-up").toEqual([]);
  await buildTeam(page);
  await page.locator("#tmFinish").click();
  await expect(page.locator("#tmTodo")).toContainText("Next step");
  expect(await greekLeft(page), "team").toEqual([]);
  await page.locator("#tmMore").click();
  expect(await greekLeft(page), "menu").toEqual([]);
  await page.locator("#team .tm-top h2").click();
  await page.locator("#team .tm-courtcard .chip[data-fid]").first().click();
  await expect(page.locator("#modal")).toHaveClass(/\bon\b/);
  expect(await greekLeft(page), "player sheet").toEqual([]);
  expect(errors).toEqual([]);
});

test("English players: the filters and a player's card have no Greek", async ({ page }, testInfo) => {
  const errors = await english(page, "public");
  await goTab(page, testInfo, "players");
  await page.locator("#fopen").click();
  expect(await greekLeft(page), "filters").toEqual([]);
  await page.locator("#fclose").click();
  await page.locator(isPhone(testInfo) ? "#plist .pcard" : "#ptable tbody tr").first().click();
  await expect(page.locator("#modal")).toHaveClass(/\bon\b/);
  await expect(page.locator("#sheet")).toContainText("Next 3 games");
  expect(await greekLeft(page), "player card").toEqual([]);
  expect(errors).toEqual([]);
});
