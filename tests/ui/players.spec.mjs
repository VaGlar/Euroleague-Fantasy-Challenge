// «Παίκτες»: search, filters, sort, player popup, compare.
import { test, expect } from "@playwright/test";
import { open, goTab, checkLayout, checkNoOverlap, isPhone } from "./helpers.mjs";

// the rows the user sees: the table on a PC, the cards on a phone
const rows = (page, testInfo) => page.locator(isPhone(testInfo) ? "#plist .pcard" : "#ptable tbody tr");
// the filters live in a panel («Φίλτρα»), on PCs and phones alike; search and sort stay on the page
const filters = async (page) => { await page.locator("#fopen").click(); await expect(page.locator("#fpanel")).toBeVisible(); };
const done = async (page) => { await page.locator("#fapply").click(); await expect(page.locator("#fpanel")).toBeHidden(); };

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

test("filters: search on the page, the rest in the «Φίλτρα» panel; position, price, chips, reset", async ({ page }, testInfo) => {
  await open(page, "public", { tab: "players" });
  await expect(page.locator("#fsearch")).toBeVisible();
  await expect(page.locator("#fpanel")).toBeHidden();
  const all = parseInt(await page.locator("#fcount").innerText());

  await page.locator("#fsearch").fill("vezenkov");
  await expect(rows(page, testInfo)).toHaveCount(1);
  await expect(rows(page, testInfo).first()).toContainText("Vezenkov");
  await page.locator("#fsearch").fill("");

  await filters(page);
  await expect(page.locator(`#fpos input[value="Center"]`)).not.toBeChecked();   // none ticked = all positions
  await page.locator(`#fpos input[value="Center"]`).check();
  await page.locator("#fpmin").fill("10");
  await page.locator("#fpmax").fill("12");
  const prices = await page.evaluate(() => P.players.filter((p) => p.x_now != null && p.position === "Center" && p.price >= 10 && p.price <= 12).length);
  await expect(page.locator("#fapply")).toContainText(String(prices));          // the button counts them live
  await checkLayout(page, "filters panel");
  await done(page);
  await expect(page.locator("#fcount")).toHaveText(new RegExp(`^${prices} `));
  await expect(page.locator("#fopen")).toContainText("(2)");
  await expect(page.locator("#fchips .fchip")).toHaveText([/^C/, /^Price 10–12/]);
  const pos = await page.evaluate(() => [...document.querySelectorAll("#plist .pcard .pm, #ptable tbody tr td:first-child .muted")]
    .filter((e) => e.getBoundingClientRect().width).map((e) => e.textContent));
  expect(pos.length).toBeGreaterThan(0);
  for (const t of pos) expect(t).toMatch(/· C|Center/);

  await page.locator("#fchips .fchip", { hasText: "Price" }).click();           // ✕ on a chip takes that one off
  await expect(page.locator("#fpmin")).toHaveValue("");
  await expect(page.locator("#fchips .fchip")).toHaveCount(1);

  await page.locator("#freset").click();
  await expect(page.locator("#fcount")).toHaveText(new RegExp(`^${all} `));
  await expect(page.locator("#fchips .fchip")).toHaveCount(0);
});

test("sort by POP puts the most owned first", async ({ page }, testInfo) => {
  await open(page, "public", { tab: "players" });
  if (isPhone(testInfo)) await page.locator("#fsort").selectOption("popularity");
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
  await filters(page);
  await page.locator(`#fpos input[value="Head Coach"]`).check();
  await done(page);
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
  // remove them one by one, the last one too
  await page.locator("#compare .h2h button.rm").first().click();
  await page.locator("#cmpClear").click();
  expect(await page.evaluate(() => CMP.length)).toBe(0);
  await expect(page.locator("#cmpClear")).toHaveCount(0);
});

test("club codes as in the game (EFS, BAY, RMB…), not the API's (IST, MUN, MAD…)", async ({ page }, testInfo) => {
  await open(page, "public", { tab: "players" });
  const list = page.locator(isPhone(testInfo) ? "#plist" : "#ptable tbody");
  const text = await list.innerText();
  expect(text).toMatch(/\b(EFS|BAY|RMB|VBC|FBT|PAO|BJK|CZV|PBB|MTA|KBA)\b/);
  expect(text).not.toMatch(/\b(IST|MUN|MAD|PAM|ULK|PAN|BES|RED|PRS|TEL|BAS)\b/);
  const opts = await page.locator("#fteam option").evaluateAll((os) => os.map((o) => o.textContent));   // in the «Φίλτρα» panel
  expect(opts).toContain("EFS");
  expect(opts).not.toContain("IST");
  await filters(page);
  await page.locator("#fteam").selectOption({ label: "EFS" });           // the filter still works on the data's codes
  await done(page);
  await expect(list).toContainText("EFS");
  expect(await list.innerText()).not.toMatch(/\b(BAY|RMB|ZAL|OLY)\b ·/);
});

test("a player back after 3 missed games is marked BACK and it's explained", async ({ page }, testInfo) => {
  await open(page, "public", { tab: "players" });
  await page.locator("#fsearch").fill("carlik");
  const row = rows(page, testInfo).first();
  await expect(row.locator(".tag.t-back")).toHaveText("BACK");
  await row.locator('[data-info="back"]').click();
  await expect(page.locator("#tip")).toContainText("3 τελευταία ματς");
  await expect(page.locator("#modal")).not.toHaveClass(/\bon\b/);      // the mark explains, it doesn't open the player
  await checkLayout(page, "returning");
});

test("watchlist: ☆ adds a player, «★ Watchlist» shows only them with what changed since, kept after a reload", async ({ page }, testInfo) => {
  await open(page, "public", { tab: "players" });
  await page.locator("#fsearch").fill("vezenkov");
  const star = rows(page, testInfo).first().locator(".wstar");
  await expect(star).toHaveText("☆");
  await star.click();
  await expect(star).toHaveText("★");                       // the page has no emoji: ★ / ☆
  await expect(page.locator("#modal")).not.toHaveClass(/\bon\b/);   // the star doesn't open the player
  await page.locator("#fsearch").fill("");
  await page.locator("#fwatch").check();                               // ★ Watchlist: on the page, next to «Φίλτρα»
  await expect(rows(page, testInfo)).toHaveCount(1);
  await expect(rows(page, testInfo).first()).toContainText("Vezenkov");
  await expect(rows(page, testInfo).first().locator(".wsince")).toContainText("χωρίς αλλαγές");   // just added
  await page.reload();
  await expect(page.locator("#fwatch")).toBeChecked();                  // kept after the reload
  await expect(rows(page, testInfo)).toHaveCount(1);
  await rows(page, testInfo).first().locator(".wstar").click();       // out of the list
  await expect(rows(page, testInfo)).toHaveCount(0);
  await expect(page.locator("#fcount")).toContainText("άδεια");
});

test("filters: «Ειδικοί» PICK / CAP / AVOID and the from–to ranges (Value, xFPT)", async ({ page }, testInfo) => {
  await open(page, "public", { tab: "players" });
  const rows = isPhone(testInfo) ? page.locator("#plist .pcard") : page.locator("#ptable tbody tr");
  await filters(page);
  await page.locator("#fxpick").check();
  await done(page);
  const n = await rows.count();
  expect(n).toBeGreaterThan(0);
  for (let i = 0; i < Math.min(n, 10); i++) await expect(rows.nth(i).locator(".t-pick")).toHaveCount(1);
  await filters(page);
  await page.locator("#fxpick").uncheck();
  await page.locator("#fminval").fill("2,5");
  await page.locator("#fmaxx").fill("15");
  await done(page);
  const vals = await page.evaluate(() => P.players.filter((p) => p.x_now != null && p.x_now <= 15 && p.value != null && p.value >= 2.5).length);
  await expect(page.locator("#fcount")).toHaveText(`${vals} ${vals === 1 ? "παίκτης" : "παίκτες"}`);
  await expect(page.locator("#fchips")).toContainText("Value ≥ 2,5");
  await expect(page.locator("#fchips")).toContainText("xFPT ≤ 15");
  await checkLayout(page, "players filters");
});

test("filters: Points/credit is the season's points over today's price", async ({ page }) => {
  await open(page, "public", { tab: "players" });
  await filters(page);
  await page.locator("#fminppc").fill("1");
  await done(page);
  const n = await page.evaluate(() => P.players.filter((p) => p.x_now != null && p.fpt_total != null && p.price > 0 && p.fpt_total / p.price >= 1).length);
  await expect(page.locator("#fcount")).toHaveText(`${n} ${n === 1 ? "παίκτης" : "παίκτες"}`);
  await expect(page.locator("#fchips")).toContainText("Points/credit ≥ 1");
});

test("sort by Points/credit: the best season's points per credit first", async ({ page }, testInfo) => {
  await open(page, "public", { tab: "players" });
  await page.locator("#fsort").selectOption("ppc");
  const best = await page.evaluate(() => Math.max(...P.players.filter((p) => p.x_now != null && p.ppc != null).map((p) => p.ppc)));
  test.skip(!isFinite(best), "no season points in the fixture");
  const first = page.locator(isPhone(testInfo) ? "#plist .pcard" : "#ptable tbody tr").first();
  const pid = await first.getAttribute("data-pid");
  const ppc = await page.evaluate((id) => P.players.find((p) => p.person_id === id).ppc, pid);
  expect(ppc).toBeCloseTo(best, 6);                 // ties may come in any order: the value, not the player
});

test("filters: $▲ keeps the players whose price is expected to rise, shown with the same tag", async ({ page }, testInfo) => {
  await open(page, "public", { tab: "players" });
  await filters(page);
  await page.locator("#fxup").check();
  await done(page);
  const n = await page.evaluate(() => P.players.filter((p) => p.x_now != null && p.price_trend === "up").length);
  await expect(page.locator("#fcount")).toHaveText(`${n} ${n === 1 ? "παίκτης" : "παίκτες"}`);
  await expect(page.locator("#fchips")).toContainText("$▲");
  const rows = page.locator(isPhone(testInfo) ? "#plist .pcard" : "#ptable tbody tr");
  if (n) await expect(rows.first().locator(".tag.t-up")).toHaveText("$▲");
});

// tester, 14/10: Points/credit against values worked by hand from the fixture (fpt_total / price), not by the
// page's own formula; and «Καθαρισμός» leaving ★ Watchlist on (it is on the page, as the search)
test("Points/credit: the best and a from-value, by hand from the fixture", async ({ page }, testInfo) => {
  await open(page, "public", { tab: "players" });
  await page.locator("#fsort").selectOption("ppc");
  const first = page.locator(isPhone(testInfo) ? "#plist .pcard" : "#ptable tbody tr").first();
  await expect(first).toHaveAttribute("data-pid", "014108");          // DIARRA: 84.8 / 6.6 = 12.85, the most
  await filters(page);
  await page.locator("#fminppc").fill("10");                          // MALEDON 10.65, OBRADOVIC 10.68, DIARRA 12.85
  await done(page);
  await expect(page.locator("#fcount")).toHaveText("3 παίκτες");
  await filters(page);
  await page.locator("#fminppc").fill("10,7");                        // a Greek keyboard's comma: only DIARRA
  await done(page);
  await expect(page.locator("#fcount")).toHaveText("1 παίκτης");
});

test("«Καθαρισμός» clears the panel's filters but leaves ★ Watchlist and the search", async ({ page }) => {
  await open(page, "public", { tab: "players" });
  await page.locator("#fsearch").fill("a");
  await page.locator("#fwatch").check();
  await filters(page);
  await page.locator("#fpmin").fill("5");
  await page.locator("#fxup").check();
  await page.locator("#fclear").click();
  await expect(page.locator("#fpmin")).toHaveValue("");
  await expect(page.locator("#fxup")).not.toBeChecked();
  await done(page);
  await expect(page.locator("#fwatch")).toBeChecked();
  await expect(page.locator("#fsearch")).toHaveValue("a");
  await expect(page.locator("#fchips")).toBeEmpty();
});
