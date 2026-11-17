// The English page's AI texts (PR 69): summary_en and note_en from the same call; the page shows them in
// English, escapes them like the Greek, and with an older digest (no English) shows the Greek summary
// and no notes. A first visit follows the browser's language (here an English browser).
// Expected values: the PR 69 description and README; the escaping rule is the Greek summary's (esc()).
import { test, expect } from "@playwright/test";
import fs from "node:fs";
import { open } from "./helpers.mjs";

test.use({ locale: "en-GB" });

const NEWS = JSON.parse(fs.readFileSync(new URL("./fixtures/news.json", import.meta.url)));
const EXPERT = NEWS.digest.expert[0];
const EN = "• Mathias Lessort is the pick of the week. <img src=x onerror=\"window.__xss=1\">";

async function withDigest(page, digest) {
  await page.route(/\/news\.json(\?|$)/, async (route) => {
    const r = await route.fetch(), j = await r.json();
    await route.fulfill({ response: r, json: { ...j, digest: { ...j.digest, ...digest } } });
  });
}

test("an English browser opens in English", async ({ page }) => {
  await open(page, "public");
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  await expect(page.locator("#langBtn")).toHaveText("ΕΛ");
});

test("English: the summary and the experts' notes are the English ones, the summary as text", async ({ page }) => {
  const experts = NEWS.digest.expert.map((e, i) => (i === 0 ? { ...e, note_en: "Top pick, high floor" } : e));
  await withDigest(page, { summary_en: EN, expert: experts });
  await open(page, "public");
  const ai = page.locator("#today .td-ai .msg");
  await expect(ai).toContainText("Mathias Lessort is the pick of the week.");
  await expect(ai).not.toContainText(NEWS.digest.summary_el.slice(0, 30));
  // markup in the AI text stays text: no element, no script run
  await expect(ai).toContainText("<img src=x");
  await expect(ai.locator("img")).toHaveCount(0);
  expect(await page.evaluate(() => window.__xss)).toBeUndefined();
  // the experts' fold: the English note where there is one, no Greek note anywhere
  const fold = page.locator("#today details.td-fold-x").first();
  await expect(fold).toContainText("Top pick, high floor");
  await expect(fold).not.toContainText(EXPERT.note);
  const notes = await fold.locator(".nt").allTextContents();
  expect(notes.filter((t) => /[Ͱ-Ͽ]/.test(t))).toEqual([]);
});

test("English with an older digest: the Greek summary is shown, and no notes", async ({ page }) => {
  await open(page, "public");                                       // the fixture's digest has no English
  await expect(page.locator("#today .td-ai .msg")).toContainText(NEWS.digest.summary_el.slice(0, 30));
  await expect(page.locator("#today details.td-fold-x .nt")).toHaveCount(0);
  const avail = await page.locator("#today .td-avail .m").allTextContents();
  expect(avail.filter((t) => /[Ͱ-Ͽ]/.test(t))).toEqual([]);         // no Greek injury note either
});
