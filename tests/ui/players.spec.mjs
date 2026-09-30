// «Παίκτες»: search, filters, sort, player popup, compare.
import { test, expect } from "@playwright/test";
import { open, goTab, checkLayout, checkNoOverlap, isPhone } from "./helpers.mjs";

// the rows the user sees: the table on a PC, the cards on a phone
const rows = (page, testInfo) => page.locator(isPhone(testInfo) ? "#plist .pcard" : "#ptable tbody tr");

test("table on PC, cards on phones; cards don't overlap", async ({ page }, testInfo) => {
  await open(page, "public", { tab: "players" });
  if (isPhone(testInfo)) {
    await expect(page.locator("#plist .pcard").first()).toBeVisible();
    await expect(page.locator("#ptable")).toBeHidden();
    await checkNoOverlap(page, "#plist .pcard", "κάρτες παικτών");
  } else {
    await expect(page.locator("#ptable tbody tr").first()).toBeVisible();
    await expect(page.locator("#ptable thead")).toContainText("xFPT");
    await expect(page.locator("#ptable thead")).toContainText("POP");
  }
  await checkLayout(page, "players");
});

test("filters: visible on PC, behind «Φίλτρα» on phones; search, position, price, reset", async ({ page }, testInfo) => {
  await open(page, "public", { tab: "players" });
  if (isPhone(testInfo)) {
    await expect(page.locator("#fsearch")).toBeHidden();
    await page.locator("#fsum").click();
  }
  await expect(page.locator("#fsearch")).toBeVisible();
  const all = parseInt(await page.locator("#fcount").innerText());

  await page.locator("#fsearch").fill("vezenkov");
  await expect(rows(page, testInfo)).toHaveCount(1);
  await expect(rows(page, testInfo).first()).toContainText("Vezenkov");
  await page.locator("#fsearch").fill("");

  await page.locator(`#fpos input[value="Center"]`).check();
  await expect(page.locator("#fcount")).not.toHaveText(new RegExp(`^${all} `));
  const pos = await page.evaluate(() => [...document.querySelectorAll("#plist .pcard .pm, #ptable tbody tr td:first-child .muted")]
    .filter((e) => e.getBoundingClientRect().width).map((e) => e.textContent));
  expect(pos.length).toBeGreaterThan(0);
  for (const t of pos) expect(t).toMatch(/· C|Center/);

  await page.locator("#fpmin").fill("10");
  await page.locator("#fpmax").fill("12");
  const prices = await page.evaluate(() => P.players.filter((p) => p.position === "Center" && p.price >= 10 && p.price <= 12).length);
  await expect(page.locator("#fcount")).toHaveText(new RegExp(`^${prices} `));

  await page.locator("#freset").click();
  await expect(page.locator("#fcount")).toHaveText(new RegExp(`^${all} `));
});

test("sort by POP puts the most owned first", async ({ page }, testInfo) => {
  await open(page, "public", { tab: "players" });
  if (isPhone(testInfo)) { await page.locator("#fsum").click(); await page.locator("#fsort").selectOption("popularity"); }
  else await page.locator('#ptable th[data-k="popularity"]').click();      // PC: the table's headers sort
  const pops = isPhone(testInfo)
    ? await page.locator("#plist .pcard").evaluateAll((els) => els.slice(0, 6).map((e) => parseFloat((e.textContent.match(/POP ([\d.]+)/) || [])[1])))
    : await page.evaluate(() => {        // the POP column of the table
        const col = [...document.querySelectorAll("#ptable th")].findIndex((th) => th.dataset.k === "popularity");
        return [...document.querySelectorAll("#ptable tbody tr")].slice(0, 6).map((tr) => parseFloat(tr.children[col].textContent));
      });
  expect(pops.every((x) => !isNaN(x))).toBeTruthy();
  for (let i = 1; i < pops.length; i++) expect(pops[i]).toBeLessThanOrEqual(pops[i - 1]);
});

test("player popup: xFPT, POP, price chart section; closes with × and Escape", async ({ page }, testInfo) => {
  await open(page, "public", { tab: "players" });
  await rows(page, testInfo).first().click();
  const sheet = page.locator("#sheet");
  await expect(page.locator("#modal")).toHaveClass(/\bon\b/);
  await expect(sheet).toContainText("xFPT");
  await expect(sheet).toContainText("POP");
  await expect(sheet.locator("h3", { hasText: "Επόμενα 3 παιχνίδια" })).toBeVisible();
  await expect(sheet).not.toContainText("Δεν υπάρχουν προγραμματισμένοι αγώνες");
  await checkLayout(page, "popup");
  await sheet.locator("button.x").first().click();
  await expect(page.locator("#modal")).not.toHaveClass(/\bon\b/);
  await rows(page, testInfo).nth(1).click();
  await expect(page.locator("#modal")).toHaveClass(/\bon\b/);
  await page.keyboard.press("Escape");
  await expect(page.locator("#modal")).not.toHaveClass(/\bon\b/);
});

test("a head coach's popup has upcoming games too", async ({ page }, testInfo) => {
  await open(page, "public", { tab: "players" });
  if (isPhone(testInfo)) await page.locator("#fsum").click();
  await page.locator(`#fpos input[value="Head Coach"]`).check();
  await rows(page, testInfo).first().click();
  await expect(page.locator("#sheet h3", { hasText: "Επόμενα 3 παιχνίδια" })).toBeVisible();
  await expect(page.locator("#sheet")).not.toContainText("Δεν υπάρχουν προγραμματισμένοι αγώνες");
});

test("compare: pick two players, see them side by side", async ({ page }, testInfo) => {
  await open(page, "public", { tab: "players" });
  const boxes = page.locator(isPhone(testInfo) ? "#plist input[type=checkbox]" : "#ptable input[type=checkbox]");
  await boxes.nth(0).check();
  await boxes.nth(1).check();
  await expect(page.locator("#cmpbar")).toBeVisible();
  await goTab(page, testInfo, "compare");
  const names = await page.evaluate(() => CMP.length);
  expect(names).toBe(2);
  await checkLayout(page, "compare");
});

test("club codes as in the game (EFS, BAY, RMB…), not the API's (IST, MUN, MAD…)", async ({ page }, testInfo) => {
  await open(page, "public", { tab: "players" });
  const list = page.locator(isPhone(testInfo) ? "#plist" : "#ptable tbody");
  const text = await list.innerText();
  expect(text).toMatch(/\b(EFS|BAY|RMB|VBC|FBT|PAO|BJK|CZV|PBB|MTA|KBA)\b/);
  expect(text).not.toMatch(/\b(IST|MUN|MAD|PAM|ULK|PAN|BES|RED|PRS|TEL|BAS)\b/);
  const opts = await page.locator("#fteam option").evaluateAll((os) => os.map((o) => o.textContent));   // hidden on phones until «Φίλτρα»
  expect(opts).toContain("EFS");
  expect(opts).not.toContain("IST");
  if (isPhone(testInfo)) await page.locator("#fsum").click();
  await page.locator("#fteam").selectOption({ label: "EFS" });           // the filter still works on the data's codes
  await expect(list).toContainText("EFS");
  expect(await list.innerText()).not.toMatch(/\b(BAY|RMB|ZAL|OLY)\b ·/);
});

test("a player back after 3 missed games is marked «↩ επιστρέφει» and it's explained", async ({ page }, testInfo) => {
  await open(page, "public", { tab: "players" });
  if (isPhone(testInfo)) await page.locator("#fsum").click();
  await page.locator("#fsearch").fill("carlik");
  const row = rows(page, testInfo).first();
  await expect(row).toContainText("↩ επιστρέφει");
  if (isPhone(testInfo)) await page.locator("#fsum").click();          // close the filters again
  await row.locator('[data-info="back"]').click();
  await expect(page.locator("#tip")).toContainText("3 τελευταία ματς");
  await expect(page.locator("#modal")).not.toHaveClass(/\bon\b/);      // the mark explains, it doesn't open the player
  await checkLayout(page, "returning");
});
