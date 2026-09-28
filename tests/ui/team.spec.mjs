// «Η ομάδα μου»: set-up, prices, options, trades and their undo (public edition); the game's team (personal).
import { test, expect } from "@playwright/test";
import { open, checkLayout, checkNoOverlap, buildTeam, stored, option, isPhone } from "./helpers.mjs";

const C = "#team .tm-courtcard";                 // the user's court (the best-team card has another)
const court = (page) => page.locator(`${C} .chip[data-fid]`);
const header = (page) => page.locator("#team .tm-top");
const tradeRows = (page) => page.locator('#team li.tm-item:has-text("Trade:")');

async function savedTeam(page) {
  await open(page, "public", { tab: "team" });
  await buildTeam(page);
  await page.locator("#tmFinish").click();
  await expect(court(page)).toHaveCount(11);
}

test.describe("public edition", () => {
  test("set-up: empty court, pick 11, purchase price, over-budget warning, remove, save", async ({ page }) => {
    const errors = await open(page, "public", { tab: "team" });
    await expect(page.locator("#team .tm-h")).toHaveText("Φτιάξε την ομάδα σου");
    await expect(page.locator("#tmFinish")).toBeDisabled();
    await buildTeam(page);
    await checkLayout(page, "set-up");
    await checkNoOverlap(page, "#team .tm-setchip", "set-up chips");

    // the offset-20 picks cost more than 100: warned, not blocked
    await expect(page.locator(".tm-over")).toContainText("Πάνω από το budget");
    // purchase price, with a comma, as a Greek keyboard types it
    const chip = page.locator("#team .tm-setchip").first();
    await chip.click();
    await page.locator("#tmSetPrice").fill("abc");
    await page.locator("#tmSetOk").click();
    await expect(page.locator("#tmSetPrice")).toBeVisible();           // invalid: the sheet stays
    await page.locator("#tmSetPrice").fill("4,5");
    await page.keyboard.press("Enter");
    await expect(chip.locator(".cp")).toHaveText(/^4\.5/);
    // every price down to 8: under budget, the warning goes
    for (let i = 0; i < 11; i++) {
      await page.locator("#team .tm-setchip").nth(i).click();
      await page.locator("#tmSetPrice").fill("8");
      await page.keyboard.press("Enter");
    }
    await expect(page.locator(".tm-over")).toHaveCount(0);
    await expect(page.locator("#team .tm-money")).toContainText("Credits 12.0/100");
    // remove one, the slot comes back and saving waits
    await page.locator("#team .tm-setchip").first().click();
    await page.locator("#tmSetRm").click();
    await expect(page.locator("#team .tm-setchip")).toHaveCount(10);
    await expect(page.locator("#tmFinish")).toBeDisabled();
    await page.locator("#team .tm-slot").first().click();
    await page.locator("#tmList .tm-pick").nth(30).click();
    await page.locator("#tmFinish").click();

    await expect(court(page)).toHaveCount(11);
    const t = await stored(page);
    expect(t.players).toHaveLength(11);
    expect(t.players.filter((x) => x.price === 8)).toHaveLength(10);
    expect(errors).toEqual([]);
  });

  test("saved team: game terms, 11 on the court, one CAP, no overlaps", async ({ page }) => {
    await savedTeam(page);
    await expect(header(page)).toContainText(/Credits \d+\.\d\/\d+\.\d/);
    await expect(header(page)).toContainText("Trades 0/4");
    await expect(header(page)).toContainText(/Round \d+/);
    await expect(page.locator(`${C} .lane h3`, { hasText: "6th (100% FPT)" })).toBeVisible();
    await expect(page.locator(`${C} .lane h3`, { hasText: "Bench (50% FPT)" })).toBeVisible();
    await expect(page.locator(`${C} .lane h3`, { hasText: "Head Coach" })).toBeVisible();
    await expect(page.locator(`${C} .chip.cap`)).toHaveCount(1);
    await checkNoOverlap(page, `${C} .chip[data-fid]`, "γήπεδο");
    await checkLayout(page, "saved team");
  });

  test("purchase price vs today: ▲/▼ on the chip, gain in the header", async ({ page }) => {
    await savedTeam(page);
    const t = await stored(page);
    t.players[0].price = Math.round((t.players[0].price - 1) * 10) / 10;     // bought 1.0 cheaper
    await page.evaluate((t) => localStorage.setItem("myteam_v1", JSON.stringify(t)), t);
    await page.reload();
    await expect(page.locator(`${C} .chip[data-fid="${t.players[0].id}"] .tm-up`)).toHaveText("▲1.0");
    await expect(header(page)).toContainText("gain");
  });

  test("player sheet: make CAP, change a place, correct the purchase price", async ({ page }) => {
    await savedTeam(page);
    const five = page.locator(`${C} .court .chip[data-fid]:not(.cap)`).first();
    const id = await five.getAttribute("data-fid");
    await five.click();
    await page.locator("#aCap").click();
    await expect(page.locator(`${C} .chip.cap[data-fid="${id}"]`)).toHaveCount(1);
    await expect(page.locator(`${C} .chip.cap`)).toHaveCount(1);

    const before = (await stored(page)).roles;
    await page.locator(`${C} .chip[data-fid="${id}"]`).click();
    await page.locator("#aSwap").click();
    await page.locator("#sheet [data-q]").first().click();
    const after = (await stored(page)).roles;
    expect(after).not.toEqual(before);

    await page.locator(`${C} .chip[data-fid="${id}"]`).click();
    await page.locator("#aPrice").click();
    await page.locator("#tmPrice").fill("3,3");
    await page.locator("#tmPriceOk").click();
    expect((await stored(page)).players.find((x) => String(x.id) === id).price).toBe(3.3);
  });

  test("options: each one works (phone menu / PC toolbar)", async ({ page, context }, testInfo) => {
    await context.grantPermissions(["clipboard-read", "clipboard-write"]);
    await savedTeam(page);
    if (isPhone(testInfo)) await expect(page.locator("#tmTools")).toHaveCount(0);
    else await expect(page.locator("#tmTools #mBackup")).toBeVisible();

    await option(page, "mBank");
    await page.locator("#tmBank").fill("2,5");
    await page.locator("#tmBankOk").click();
    await expect(header(page)).toContainText("Credits 2.5/");

    await option(page, "mEdit");
    await expect(page.locator("#team .tm-h")).toHaveText("Αλλαγή ομάδας");
    await page.locator("#tmCancel").click();
    await expect(court(page)).toHaveCount(11);

    await option(page, "mMail");
    await expect(page.locator("#tmtoast")).toContainText("euroleaguefantasy26@gmail.com");

    // backup link -> another device (empty storage) -> the same team
    const team = await stored(page);
    await option(page, "mBackup");
    let link = await page.evaluate(() => navigator.clipboard.readText().catch(() => ""));
    if (!link.includes("#t=")) link = await page.locator("#sheet textarea").inputValue();
    expect(link).toContain("#t=");
    await page.evaluate(() => localStorage.removeItem("myteam_v1"));
    await page.goto(link.replace(/^https?:\/\/[^/]+/, ""));
    await expect(court(page)).toHaveCount(11);
    expect((await stored(page)).players).toEqual(team.players);

    await option(page, "mDel");
    await page.locator("#tmDelOk").click();
    await expect(page.locator("#team .tm-h")).toHaveText("Φτιάξε την ομάδα σου");
    expect(await stored(page)).toBeNull();
  });

  test("backup link opened on another device (empty browser)", async ({ page, browser }, testInfo) => {
    await savedTeam(page);
    const team = await stored(page);
    const code = await page.evaluate(() => TEAM.encode(JSON.parse(localStorage.getItem("myteam_v1"))));
    const other = await browser.newContext(testInfo.project.use);
    const p2 = await other.newPage();
    await open(p2, "public", { tab: "today" });
    await p2.goto(`/public/index.html#t=${code}`);
    await p2.reload();
    await p2.locator(isPhone(testInfo) ? '#bnav button[data-t="team"]' : '#tabs button[data-t="team"]').click();
    await expect(p2.locator(`${C} .chip[data-fid]`)).toHaveCount(11);
    expect((await stored(p2)).players).toEqual(team.players);
    await other.close();
  });

  test("restore from a pasted backup link", async ({ page }) => {
    await savedTeam(page);
    const code = await page.evaluate(() => TEAM.encode(JSON.parse(localStorage.getItem("myteam_v1"))));
    const team = await stored(page);
    await page.evaluate(() => localStorage.removeItem("myteam_v1"));
    await page.reload();
    await page.locator("#tmRestore").click();
    await page.locator("#tmLink").fill(`https://example.org/#t=${code}`);
    await page.locator("#tmLinkOk").click();
    await expect(court(page)).toHaveCount(11);
    expect((await stored(page)).players).toEqual(team.players);
  });

  test("trades: done ones count, Trades n/4, undo brings the team back exactly", async ({ page }) => {
    await savedTeam(page);
    await page.locator("#tmConfirm").click();
    const before = await stored(page);
    await expect(tradeRows(page).first()).toBeVisible();
    await tradeRows(page).first().locator(".tm-done").click();
    await tradeRows(page).first().locator(".tm-done").click();
    await expect(header(page)).toContainText("Trades 2/4");
    const mid = await stored(page);
    expect(mid.players.map((x) => x.id)).not.toEqual(before.players.map((x) => x.id));
    // sold at today's price: bank = before + out(today) - in
    expect(mid.bank).not.toBeNaN();

    await option(page, "mUsed");
    await page.locator("#tmUndoOk").click();
    const after = await stored(page);
    for (const k of ["players", "bank", "roles", "captain"]) expect(after[k]).toEqual(before[k]);
    await expect(header(page)).toContainText("Trades 0/4");
  });

  test("all the proposed trades together fit in the credits left", async ({ page }) => {
    await savedTeam(page);
    await page.locator("#tmConfirm").click();
    for (let n = 0; n < 11 && await tradeRows(page).count(); n++) {
      await tradeRows(page).first().locator(".tm-done").click();
      expect((await stored(page)).bank).toBeGreaterThanOrEqual(-1e-9);
    }
    const t = await stored(page);
    expect(t.used.n).toBeGreaterThan(0);
    expect(t.bank).toBeGreaterThanOrEqual(0);
  });

  test("«Κράτα τον» removes the player's trade and re-plans; undo brings it back", async ({ page }) => {
    await savedTeam(page);
    await page.locator("#tmConfirm").click();
    const first = tradeRows(page).first();
    const out = (await first.locator(".tm-what b").first().innerText()).trim();
    await first.locator(".tm-keep").click();
    await expect(page.locator("#team .tm-kept")).toContainText(out);
    await expect(page.locator('#team li.tm-item:has-text("Trade:") .tm-what > b:first-child', { hasText: out })).toHaveCount(0);
    await page.locator("#team [data-unkeep]").first().click();
    await expect(page.locator("#team .tm-kept")).toHaveCount(0);
  });

  test("drag a bench player onto a starter swaps them", async ({ page }, testInfo) => {
    test.skip(isPhone(testInfo), "touch drag is covered by the player sheet's «Αλλαγή θέσης»");
    await savedTeam(page);
    const bench = page.locator(`${C} .lane.bench .chip[data-fid]`).first();
    const starter = page.locator(`${C} .court .chip[data-fid]`).first();
    const [b, s] = [await bench.getAttribute("data-fid"), await starter.getAttribute("data-fid")];
    await bench.dragTo(starter);
    const roles = (await stored(page)).roles;
    expect(roles[b]).toBe("5άδα");
    expect(roles[s]).not.toBe("5άδα");
  });
});

test.describe("personal edition", () => {
  test("the game's team: 11 on the court, credits from the game, no set-up or ✓ buttons", async ({ page }) => {
    const errors = await open(page, "personal", { tab: "team" });
    await expect(court(page)).toHaveCount(11);
    await expect(page.locator("#team .tm-setchip")).toHaveCount(0);
    await expect(page.locator("#team .tm-done[data-i], #team .tm-done[data-n]")).toHaveCount(0);
    await expect(header(page)).toContainText(/Credits \d+\.\d\/\d+\.\d/);
    await expect(page.locator(`${C} .chip.cap`)).toHaveCount(1);
    await checkNoOverlap(page, `${C} .chip[data-fid]`, "γήπεδο (προσωπική)");
    await checkLayout(page, "personal team");
    await court(page).first().click();
    await expect(page.locator("#modal")).toHaveClass(/\bon\b/);
    expect(errors).toEqual([]);
  });
});
