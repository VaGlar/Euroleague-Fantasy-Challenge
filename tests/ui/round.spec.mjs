// «Round» (PR 65): one page for the round, in place of «Σήμερα», «Νέα» and «Report».
// Expected values: the order the owner agreed (PR 65), the fixtures (what each edition is served),
// and the game's rule that the coach is never captain.
import { test, expect } from "@playwright/test";
import fs from "node:fs";
import { open, isPhone } from "./helpers.mjs";

const fix = (f) => JSON.parse(fs.readFileSync(new URL(`./fixtures/${f}`, import.meta.url)));
const PRED = fix("predictions.json");
const REPORT = fix("report.json");

// each card of the page, in the order agreed: countdown, my team, AI summary, captain, injuries,
// price tiers, price changes, articles, then (personal edition only) the report in text
const ORDER = ["countdown", "my team", "AI summary", "captain", "injuries", "price tiers", "price changes", "articles", "report"];

// the page's cards top to bottom as the page has them, each named, with where it is drawn
// (the classifier runs in the page: no `new Function`, which a CSP would refuse)
async function cards(page) {
  return page.locator("#today .td-grid").evaluate((g) => [...g.children].map((el) => {
    const h2 = (el.matches("details") ? el.querySelector("summary h2") : el.querySelector(":scope > h2"))?.textContent || "";
    const name = el.querySelector(".td-hero") ? "countdown"
      : el.classList.contains("td-ai") ? "AI summary"
      : el.classList.contains("td-col") ? "captain"
      : el.classList.contains("td-avail") ? "injuries"
      : el.classList.contains("td-best") ? "price tiers"
      : h2.startsWith("Price changes") ? "price changes"
      : el.matches("details") && h2.startsWith("Άρθρα") ? "articles"
      : el.matches("details") && h2.startsWith("Report σε κείμενο") ? "report"
      : el.querySelector(".td-team") || /Η ομάδα (μου|δεν διαβάστηκε)/.test(el.textContent) ? "my team"
      : "?";
    const r = el.getBoundingClientRect();
    return { name, top: Math.round(r.top), left: Math.round(r.left) };
  }));
}

for (const edition of ["public", "personal"]) {
  test(`Round (${edition}): the cards come in the agreed order, on screen as in the page`, async ({ page }, testInfo) => {
    await open(page, edition);
    const cs = (await cards(page)).filter((c) => c.name !== "?");     // «Κατάσταση», «Αρχή σεζόν»: notes, not cards of the order
    const names = cs.map((c) => c.name);
    const want = ORDER.filter((n) => edition === "personal" || n !== "report");
    expect(names).toEqual(want);                                       // all there, once each, in this order
    // what you see follows the page: no card drawn above one that comes before it (the old phone-only
    // CSS `order` rules are gone); on a phone one column, so every card is lower than the one before
    for (let i = 1; i < cs.length; i++) {
      if (isPhone(testInfo)) expect(cs[i].top, `${cs[i].name} under ${cs[i - 1].name}`).toBeGreaterThan(cs[i - 1].top);
      else expect(cs[i].top, `${cs[i].name} not above ${cs[i - 1].name}`).toBeGreaterThanOrEqual(cs[i - 1].top);
    }
    if (isPhone(testInfo)) expect(new Set(cs.map((c) => c.left)).size).toBe(1);
  });
}

test("Round (personal): the report in text is the last card, folded, and opens to the report's messages", async ({ page }) => {
  expect(REPORT.messages.length).toBeGreaterThan(0);
  await open(page, "personal");
  const fold = page.locator("#today .td-grid > details", { hasText: "Report σε κείμενο" });
  await expect(fold).toHaveCount(1);
  expect(await page.locator("#today .td-grid > *").last().evaluate((el) => el.textContent.includes("Report σε κείμενο"))).toBeTruthy();
  await expect(fold.locator(".msg").first()).toBeHidden();
  await fold.locator("summary").click();
  await expect(fold).toHaveAttribute("open", "");
  await expect(fold.locator(".msg")).toHaveCount(REPORT.messages.length);
  // the Telegram text as written: its bold stays bold, its line breaks stay
  const head = REPORT.messages[0].text.match(/<b>([^<]+)<\/b>/)[1];
  await expect(fold.locator(".msg").first().locator("b").first()).toHaveText(head);
  expect(await fold.locator(".msg br").count()).toBeGreaterThan(0);
});

test("Round (public): no report in text, although the public edition is served one", async ({ page }) => {
  await open(page, "public");
  const served = await page.evaluate(async () => (await (await fetch("data/report.json")).json()).messages?.length || 0);
  expect(served).toBeGreaterThan(0);                                   // so the check below means something
  await expect(page.locator("#today")).not.toContainText("Report σε κείμενο");
  await expect(page.locator("#today")).not.toContainText("όπως στο Telegram");
});

for (const edition of ["public", "personal"]) {
  for (const tab of ["news", "report"]) {
    test(`Round (${edition}): a saved last tab «${tab}» opens «Round» and is saved as «Round»`, async ({ page }) => {
      await open(page, edition, { tab });
      await expect(page.locator("section#today")).toHaveClass(/\bon\b/);
      await expect(page.locator("main > section.on")).toHaveCount(1);
      expect(await page.evaluate(() => localStorage.getItem("tab"))).toBe("today");
    });
  }
}

for (const edition of ["public", "personal"]) {
  test(`${edition}: every tab button, «Περισσότερα» entry and in-page link leads to a page that exists`, async ({ page }, testInfo) => {
    await open(page, edition);
    if (isPhone(testInfo)) await page.locator('#bnav button[data-t="more"]').click();
    const targets = await page.evaluate(() => [...document.querySelectorAll("[data-t], [data-go], [data-tab]")]
      .map((el) => el.dataset.t || el.dataset.go || el.dataset.tab));
    expect(targets.length).toBeGreaterThan(5);
    for (const t of targets) {
      expect(["news", "report"], `link to the gone tab «${t}»`).not.toContain(t);
      if (t !== "more") expect(await page.locator(`main > section#${t}`).count(), `section for «${t}»`).toBe(1);
    }
  });
}

test("Round: «Για Captain» is the 5 best healthy court players by xFPT; the coach is the best coach, never in the five", async ({ page }) => {
  const xs = PRED.players.filter((r) => r.x_now != null);
  const healthy = (r) => r.avail_game == null || r.avail_game >= 1;
  const five = xs.filter((r) => r.position !== "Head Coach" && healthy(r)).sort((a, b) => b.x_now - a.x_now).slice(0, 5);
  const coach = xs.filter((r) => r.position === "Head Coach").sort((a, b) => b.x_now - a.x_now)[0];
  await open(page, "public");
  const cap = page.locator("#today .td-col .card").first();
  const ids = await cap.locator(":scope > ul.td-list > li, :scope > details.td-more li").evaluateAll((ls) => ls.map((l) => l.dataset.pid));
  expect(ids).toEqual(five.map((r) => r.person_id));
  await expect(cap.locator(".cap-turn li")).toHaveCount(1);
  await expect(cap.locator(".cap-turn li")).toHaveAttribute("data-pid", coach.person_id);
  // each turn shown is the one he plays (fixtures: before the round, nobody has played yet)
  for (const r of five) await expect(cap.locator(`li[data-pid="${r.person_id}"]`)).toContainText(`Turn ${r.turn}`);
});

// Known bug (owner, 11/11): within a round the captain can move only to a player who hasn't played yet,
// so «Για Captain» must leave out who has played. Today the list keeps him, with «Turn n».
// Pinned with test.fail(): it turns red when the bug is fixed; then drop the test.fail line.
test("Round: «Για Captain» leaves out a player who has already played this round", async ({ page }) => {
  test.fail(true, "KNOWN BUG: «Για Captain» keeps players who already played (report 2026-11-11, §2.2)");
  const healthy = (r) => r.avail_game == null || r.avail_game >= 1;
  const best = PRED.players.filter((r) => r.x_now != null && r.position !== "Head Coach" && healthy(r))
    .sort((a, b) => b.x_now - a.x_now)[0];
  await page.route(/\/predictions\.json(\?|$)/, async (route) => {
    const r = await route.fetch(), j = await r.json();
    for (const p of j.players) if (p.person_id === best.person_id) p.actual = 30;      // his game is over
    await route.fulfill({ response: r, json: j });
  });
  await open(page, "public");
  const cap = page.locator("#today .td-col .card").first();
  await expect(cap.locator("li[data-pid]").first()).toBeVisible();
  await expect(cap.locator(`li[data-pid="${best.person_id}"]`)).toHaveCount(0);
});
