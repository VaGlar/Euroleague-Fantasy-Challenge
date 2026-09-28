// Shared steps for the UI tests. The data are frozen (fixtures/), the clock is set just after
// they were generated, so the round, deadline and proposals are the same on every run.
import { expect } from "@playwright/test";
import fs from "node:fs";

const PRED = JSON.parse(fs.readFileSync(new URL("./fixtures/predictions.json", import.meta.url)));
export const NOW = new Date(Date.parse(PRED.generated) + 20 * 60 * 1000);
export const ROUND = PRED.round;
export const isPhone = (testInfo) => testInfo.project.name !== "pc";
export const isAndroid = (testInfo) => testInfo.project.name.startsWith("android");

// Opens an edition ("public" | "personal") with a clean slate; returns the list of JS errors.
export async function open(page, edition, { tab = "today", team = null, guide = false } = {}) {
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => { if (m.type() === "error" && !/favicon|Failed to load resource/.test(m.text())) errors.push(m.text()); });
  await page.clock.setFixedTime(NOW);
  await page.addInitScript(([tab, team, guide]) => {
    if (sessionStorage.getItem("ui-init")) return;          // only on the first load: reloads keep what the test did
    sessionStorage.setItem("ui-init", "1");
    localStorage.clear();
    if (!guide) localStorage.setItem("a2hs", JSON.stringify({ at: Date.now(), never: true }));   // no install guide
    localStorage.setItem("tab", tab);
    if (team) localStorage.setItem("myteam_v1", JSON.stringify(team));
  }, [tab, team, guide]);
  await page.goto(`/${edition}/index.html`);
  await expect(page.locator("#round")).toHaveText(`Round ${ROUND}`);
  return errors;
}

// Goes to a tab the way a user would: top bar on a PC, bottom bar / «Περισσότερα» on a phone.
export async function goTab(page, testInfo, t) {
  if (!isPhone(testInfo)) { await page.locator(`#tabs button[data-t="${t}"]`).click(); }
  else if (await page.locator(`#bnav button[data-t="${t}"]`).count()) { await page.locator(`#bnav button[data-t="${t}"]`).click(); }
  else {
    await page.locator('#bnav button[data-t="more"]').click();
    await page.locator(`#sheet [data-go="${t}"]`).click();
  }
  await expect(page.locator(`section#${t}`)).toHaveClass(/\bon\b/);
}

// Nothing sticks out sideways (no horizontal page scroll) and nothing is hidden under the bottom bar.
export async function checkLayout(page, where) {
  const bad = await page.evaluate(() => {
    const out = [];
    const W = document.documentElement.clientWidth;
    if (document.documentElement.scrollWidth > W + 1) out.push(`η σελίδα κυλάει οριζόντια (${document.documentElement.scrollWidth} > ${W})`);
    const scrolls = (el) => { for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
      if (getComputedStyle(p).overflowX !== "visible") return true; } return false; };
    for (const el of document.querySelectorAll("main section.on *, header *")) {
      const r = el.getBoundingClientRect();
      if (!r.width || getComputedStyle(el).position === "fixed") continue;
      if ((r.right > W + 1 || r.left < -1) && !scrolls(el)) { out.push(`βγαίνει εκτός οθόνης: <${el.tagName.toLowerCase()} class="${el.className}"> ${el.textContent.trim().slice(0, 40)}`); if (out.length > 4) break; }
    }
    return out;
  });
  expect(bad, `διάταξη: ${where}`).toEqual([]);
}

// Cards of the same row don't overlap each other (the court's chips, the player cards).
export async function checkNoOverlap(page, selector, where) {
  const hits = await page.evaluate((sel) => {
    const els = [...document.querySelectorAll(sel)].filter((e) => e.getBoundingClientRect().width);
    const out = [];
    for (let i = 0; i < els.length; i++) for (let j = i + 1; j < els.length; j++) {
      const a = els[i].getBoundingClientRect(), b = els[j].getBoundingClientRect();
      const x = Math.min(a.right, b.right) - Math.max(a.left, b.left), y = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
      if (x > 2 && y > 2) out.push(`${els[i].textContent.trim().slice(0, 20)} ⟂ ${els[j].textContent.trim().slice(0, 20)}`);
    }
    return out;
  }, selector);
  expect(hits, `επικαλύψεις: ${where}`).toEqual([]);
}

// The public edition's team, built through the UI: the (i+offset)-th player of each empty slot's list.
export async function buildTeam(page, offset = 20) {
  for (let i = 0; i < 11; i++) {
    await page.locator("#team .tm-slot").first().click();
    const picks = page.locator("#tmList .tm-pick");
    await expect(picks.first()).toBeVisible();
    await picks.nth(Math.min((await picks.count()) - 1, offset + i)).click();
  }
  await expect(page.locator("#team .tm-setchip")).toHaveCount(11);
}

export const stored = (page) => page.evaluate(() => JSON.parse(localStorage.getItem("myteam_v1") || "null"));

// The team's options: the toolbar on a PC, «⋯ Επιλογές» on a phone.
export async function option(page, id) {
  if (await page.locator("#tmMore").count()) {
    await page.locator("#tmMore").click();
    await expect(page.locator("#tmMenu .tm-menu")).toBeVisible();
  }
  await page.locator(`#${id}`).click();
}
