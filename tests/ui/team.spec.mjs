// «Η ομάδα μου»: set-up, prices, options, trades and their undo (public edition); the game's team (personal).
import { test, expect } from "@playwright/test";
import { open, checkLayout, checkNoOverlap, buildTeam, stored, option, isPhone } from "./helpers.mjs";

const C = "#team .tm-courtcard";                 // the user's court (the best-team card has another)
const court = (page) => page.locator(`${C} .chip[data-fid]`);
const header = (page) => page.locator("#team .tm-top");
const tradeRows = (page) => page.locator("#team li.tm-item.tm-trade");

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
    await expect(page.locator(`${C} .lane h3`, { hasText: "Sixth man" })).toBeVisible();
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

  test("options: each one works (behind «⋯ Επιλογές» on phone and PC)", async ({ page, context }, testInfo) => {
    await context.grantPermissions(["clipboard-read", "clipboard-write"]);
    await savedTeam(page);
    await expect(page.locator("#mBackup")).toHaveCount(0);           // closed until tapped

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

    await page.locator("#mUsed").click();
    await page.locator("#tmUndoOk").click();
    const after = await stored(page);
    for (const k of ["players", "bank", "roles", "captain"]) expect(after[k]).toEqual(before[k]);
    await expect(header(page)).toContainText("Trades 0/4");
  });

  test("✕ as in the game: take players off, empty places, save only when full; cancel leaves the team as it was", async ({ page }) => {
    await savedTeam(page);
    await page.locator("#tmConfirm").click();
    const before = await stored(page);
    const first = page.locator(`${C} .court .chip[data-fid]`).first();
    const outId = Number(await first.getAttribute("data-fid"));
    await first.click();
    await page.locator("#aOut").click();
    await expect(page.locator("#team [data-fill]")).toHaveCount(1);
    await expect(page.locator("#tmSellOk")).toBeDisabled();
    await expect(page.locator("#tmSellOk")).toHaveText("Λείπουν 1");
    expect(await stored(page)).toEqual(before);                         // nothing saved while a place is empty

    await page.locator("#team [data-off]").first().click();             // a second one off
    await expect(page.locator("#team [data-fill]")).toHaveCount(2);
    await page.locator("#tmSellNo").click();                            // cancel: the team as it was
    await expect(court(page)).toHaveCount(11);
    expect(await stored(page)).toEqual(before);

    await page.locator(`${C} .chip[data-fid="${outId}"]`).click();
    await page.locator("#aOut").click();
    await page.locator("#team [data-fill]").click();
    const inId = Number(await page.locator("#tmList [data-n]").first().getAttribute("data-n"));
    await page.locator("#tmList [data-n]").first().click();
    await expect(page.locator("#tmSellOk")).toBeEnabled();
    await page.locator("#tmSellOk").click();
    await expect(court(page)).toHaveCount(11);
    await expect(header(page)).toContainText("Trades 1/4");
    const after = await stored(page);
    expect(after.players.map((x) => x.id)).toContain(inId);
    expect(after.players.map((x) => x.id)).not.toContain(outId);
    expect(after.bank).toBeGreaterThanOrEqual(0);
  });

  test("round under way: no trades proposed (next round's wait for it to end), only swaps and CAP", async ({ page }) => {
    await page.route(/predictions\.json/, async (route) => {
      const res = await route.fetch();
      const p = await res.json();
      for (const x of p.players) if (x.turn === 1) x.actual = 7;       // turn 1 has been played
      p.trade_info = { ...(p.trade_info || {}), round: p.round + 1 };
      await route.fulfill({ response: res, json: p });
    });
    await savedTeam(page);
    await expect(page.locator("#team")).not.toContainText("Trades για το Round");
    await expect(tradeRows(page)).toHaveCount(0);
  });

  test("«Αναίρεση τελευταίας κίνησης»: one step back at a time, down to the round's start", async ({ page }) => {
    await savedTeam(page);
    await page.locator("#tmConfirm").click();
    const start = await stored(page);
    await tradeRows(page).first().locator(".tm-done").click();
    const one = await stored(page);
    await tradeRows(page).first().locator(".tm-done").click();
    await expect(header(page)).toContainText("Trades 2/4");

    await page.locator("#mUndoLast").click();                               // the second trade goes back
    let now = await stored(page);
    for (const k of ["players", "bank", "used"]) expect(now[k]).toEqual(one[k]);
    await expect(header(page)).toContainText("Trades 1/4");
    await page.locator("#mUndoLast").click();                               // the first one
    await page.locator("#mUndoLast").click();                               // the «confirmed» click
    now = await stored(page);
    for (const k of ["players", "bank", "roles", "captain"]) expect(now[k]).toEqual(start[k]);
    await expect(header(page)).toContainText("Trades 0/4");
  });

  test("«Αλλαγή ομάδας» after trades: the count starts again, but undo still brings back the round's team", async ({ page }) => {
    await savedTeam(page);
    await page.locator("#tmConfirm").click();
    const before = await stored(page);
    await tradeRows(page).first().locator(".tm-done").click();
    await tradeRows(page).first().locator(".tm-done").click();
    await expect(header(page)).toContainText("Trades 2/4");

    await option(page, "mEdit");                                   // edit the team, save it as it is
    await expect(page.locator("#team .tm-h")).toHaveText("Αλλαγή ομάδας");
    await page.locator("#tmFinish").click();
    await expect(header(page)).toContainText("Trades 0/4");        // not binding: the count starts again

    await page.locator("#mUsed").click();                                   // …but the undo is still there
    await expect(page.locator("#sheet")).toContainText("Αναίρεση των κινήσεων");
    await page.locator("#tmUndoOk").click();
    const after = await stored(page);
    for (const k of ["players", "bank"]) expect(after[k]).toEqual(before[k]);
  });

  test("trades left can be declared (the game counts more than the app saw): the proposals follow", async ({ page }) => {
    await savedTeam(page);
    await expect(page.locator("#tmLeft")).toHaveValue("4");        // at the «same team?» step
    await page.locator("#tmLeft").selectOption("1");
    await expect(header(page)).toContainText("Trades 3/4");
    await page.locator("#tmConfirm").click();
    expect(await tradeRows(page).count()).toBeLessThanOrEqual(1);   // not 4 again

    await page.locator("#tmTrades").click();                       // and later, from «Trades x/4» in the header
    await page.locator('#sheet [data-left="0"]').click();
    await expect(header(page)).toContainText("Trades 4/4");
    await expect(tradeRows(page)).toHaveCount(0);
    await page.locator("#tmTrades").click();
    await page.locator('#sheet [data-left="4"]').click();
    await expect(header(page)).toContainText("Trades 0/4");
    await expect(tradeRows(page).first()).toBeVisible();
    await checkLayout(page, "trades left");
  });

  test("tapping a proposed trade opens the two players side by side; a trade the credits can't pay yet is locked", async ({ page }) => {
    await savedTeam(page);
    await page.locator("#tmConfirm").click();
    const row = tradeRows(page).first();
    const [out, inn] = await row.locator(".tm-what > b").allInnerTexts();
    await row.locator(".tm-what > b").first().click();
    await expect(page.locator("#sheet table.h2h")).toBeVisible();
    await expect(page.locator("#sheet h2")).toContainText(`${out} vs ${inn}`);
    await page.keyboard.press("Escape");
    // no credits left: a trade that costs more than it frees waits for the others
    await page.evaluate(() => { const t = JSON.parse(localStorage.getItem("myteam_v1")); t.bank = 0; localStorage.setItem("myteam_v1", JSON.stringify(t)); });
    await page.reload();
    for (const b of await page.locator("#team li.tm-trade .tm-done").all()) {
      if (await b.getAttribute("title")) await expect(b).toBeDisabled();   // greyed: the credits don't reach yet
      else await expect(b).toBeEnabled();
    }
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
    await first.locator("[data-keep]").click();
    await expect(page.locator("#team .tm-kept")).toContainText(out);
    await expect(page.locator('#team li.tm-item.tm-trade .tm-what > b:first-child', { hasText: out })).toHaveCount(0);
    await page.locator("#team [data-unkeep]").first().click();
    await expect(page.locator("#team .tm-kept")).toHaveCount(0);
  });

  test("«Όχι τον X, πρότεινε άλλον» drops that player from the trades and re-plans; undo brings him back", async ({ page }) => {
    await savedTeam(page);
    await page.locator("#tmConfirm").click();
    const btn = page.locator("#team [data-avoid]").first();
    const name = (await btn.getAttribute("title")).match(/Όχι τον (.+), πρότεινε/)[1].trim();
    const before = await tradeRows(page).allInnerTexts();
    await btn.click();
    await expect(page.locator("#team .tm-kept")).toContainText(name);
    const after = await tradeRows(page).allInnerTexts();
    expect(after.some((t) => t.includes(`vs ${name}`))).toBeFalsy();
    expect(after).not.toEqual(before);
    await page.locator("#team [data-unavoid]").first().click();
    await expect(page.locator("#team .tm-kept")).toHaveCount(0);
  });

  test("drag a bench player onto a starter swaps them", async ({ page }, testInfo) => {
    test.skip(isPhone(testInfo), "touch drag is covered by the player sheet's «Αλλαγή θέσης»");
    await savedTeam(page);
    // a starter of the bench player's position, so the five keeps its G/F/C whatever the proposal was
    const bench = page.locator(`${C} .lane.bench .chip[data-fid]`).first();
    const pos = (await bench.locator(".ct span").first().innerText()).trim();
    const starter = page.locator(`${C} .court .chip[data-fid]`).filter({ has: page.locator(".ct span", { hasText: new RegExp(`^${pos}$`) }) }).first();
    const [b, s] = [await bench.getAttribute("data-fid"), await starter.getAttribute("data-fid")];
    await bench.dragTo(starter);
    const roles = (await stored(page)).roles;
    expect(roles[b]).toBe("5άδα");
    expect(roles[s]).not.toBe("5άδα");
  });
});

test.describe("player sheet on the team screen", () => {
  test("tapping a player shows the actions and, below them, his analysis and stats", async ({ page }) => {
    await savedTeam(page);
    await court(page).first().click();
    await expect(page.locator("#aRep")).toBeVisible();
    await expect(page.locator("#tmDetails")).toContainText(/Επόμενος αγώνας|Αγώνας/);
    await expect(page.locator("#tmDetails")).toContainText("Επόμενα 3 παιχνίδια");
    await expect(page.locator("#tmDetails")).not.toContainText("Δεν υπάρχουν προγραμματισμένοι αγώνες");
  });

  test("replacement: only players the credits allow, biggest gain first, and the trade applies", async ({ page }) => {
    await savedTeam(page);
    const t = await stored(page);
    const chip = court(page).first();
    const id = Number(await chip.getAttribute("data-fid"));
    await chip.click();
    await page.locator("#aRep").click();
    const max = await page.evaluate(([bank, id]) => bank + P.players.find((p) => p.fantasy_id === id).price, [t.bank, id]);
    const prices = await page.locator("#tmList [data-n]").evaluateAll((els) => els.map((e) => P.players.find((p) => p.fantasy_id === Number(e.dataset.n)).price));
    expect(prices.length).toBeGreaterThan(0);
    for (const p of prices) expect(p).toBeLessThanOrEqual(max + 1e-9);
    await expect(page.locator("#tmList [disabled]")).toHaveCount(0);
    const pick = Number(await page.locator("#tmList [data-n]").first().getAttribute("data-n"));
    await page.locator("#tmList [data-n]").first().click();
    const after = await stored(page);
    expect(after.players.some((x) => x.id === pick)).toBeTruthy();
    expect(after.bank).toBeGreaterThanOrEqual(0);
  });

  test("tapping 🆕 on a chip explains it instead of opening the player", async ({ page }) => {
    await savedTeam(page);
    const few = page.locator(`${C} .chip .few`).first();
    test.skip(!(await few.count()), "no newcomer in this team");
    await few.click();
    await expect(page.locator("#tip")).toContainText("Νέος στη EuroLeague");
    await expect(page.locator("#modal")).not.toHaveClass(/\bon\b/);
  });
});

test.describe("personal edition", () => {
  test("a player not registered with his club is marked 📋 (not 🚑) on the court", async ({ page }) => {
    await open(page, "personal", { tab: "team" });
    const chip = page.locator(`${C} .chip[data-fid="4061"]`);        // Mantzoukas: unregistered in the fixture
    await expect(chip).toContainText("📋");
    await expect(chip).not.toContainText("🚑");
  });

  test("the game's team: tapping a player shows his stats and who fits in his place (an idea, not a trade)", async ({ page }) => {
    await open(page, "personal", { tab: "team" });
    await court(page).first().click();
    await expect(page.locator("#aCap")).toHaveCount(0);            // lineup and CAP go through /lineup
    await expect(page.locator("#tmDetails")).toContainText(/Επόμενος αγώνας|Αγώνας/);
    await page.locator("#aRep").click();
    await expect(page.locator("#sheet h2")).toContainText("Στη θέση του");
    const n = await page.locator("#tmList [data-n]").count();
    expect(n).toBeGreaterThan(0);
    const before = await page.locator(`${C} .chip[data-fid]`).evaluateAll((els) => els.map((e) => e.dataset.fid));
    await page.locator("#tmList [data-n]").first().click();
    await expect(page.locator("#tmtoast")).toContainText("Στο παιχνίδι");
    expect(await page.locator(`${C} .chip[data-fid]`).evaluateAll((els) => els.map((e) => e.dataset.fid))).toEqual(before);
  });

  test("«Όχι τον X» on the game's team re-plans without him", async ({ page }) => {
    await open(page, "personal", { tab: "team" });
    const btn = page.locator("#team [data-avoid]").first();
    const name = (await btn.getAttribute("title")).match(/Όχι τον (.+), πρότεινε/)[1].trim();
    await btn.click();
    await expect(page.locator("#team .tm-kept")).toContainText(name);
    expect((await page.locator("#team .tm-list").innerText()).includes(`vs ${name}`)).toBeFalsy();
  });

  test("«Κράτα τον» re-plans and the expected points with the plan follow", async ({ page }) => {
    await open(page, "personal", { tab: "team" });
    const planned = () => header(page).locator(".tm-planned").innerText();
    const before = await planned();
    const trades = await page.locator("#team .tm-list").innerText();
    await page.locator("#team [data-keep]").first().click();
    await expect(page.locator("#team .tm-kept")).toBeVisible();
    expect(await page.locator("#team .tm-list").innerText()).not.toEqual(trades);
    expect(await planned()).not.toEqual(before);
    await page.locator("#team [data-unkeep]").first().click();
    await expect(header(page).locator(".tm-planned")).toHaveText(before);
  });

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

test("phones: the court comes before the to-do list and the whole squad fits in one screen; PC: HC/6th left, bench right", async ({ page }, testInfo) => {
  await open(page, "personal", { tab: "team" });
  const card = page.locator("#team .tm-courtcard");
  const todo = page.locator("#team .tm-colL .card").first();
  const [c, d] = [await card.boundingBox(), await todo.boundingBox()];
  if (isPhone(testInfo)) {
    expect(c.y, "το γήπεδο πριν από τις προτάσεις").toBeLessThan(d.y);
    const room = await page.evaluate(() => innerHeight - document.querySelector("#bnav").getBoundingClientRect().height);
    expect(c.height, "όλη η ομάδα σε μία οθόνη").toBeLessThanOrEqual(room);
  } else {
    const floor = await page.locator("#team .tm-courtcard .tm-floor").boundingBox();
    for (const lane of ["six", "coach"]) expect((await page.locator(`${C} .tm-floor .lane.${lane}`).boundingBox()).x + 5).toBeLessThan(floor.x);
    expect((await page.locator(`${C} .tm-floor .lane.bench`).boundingBox()).x).toBeGreaterThan(floor.x + floor.width - 5);
  }
  await checkLayout(page, "court first");
  await checkNoOverlap(page, "#team .tm-courtcard .chip", "γήπεδο");
  // the team's summary scrolls away with the page (it isn't the page's sticky header)
  expect(await page.locator("#team .tm-top").evaluate((el) => getComputedStyle(el).position)).not.toBe("sticky");
});

test("a change doesn't throw you back to the top of the page", async ({ page }, testInfo) => {
  await open(page, "public", { tab: "team" });
  await buildTeam(page);
  await page.locator("#tmFinish").click();
  await expect(page.locator("#tmtoast")).not.toHaveClass(/\bon\b/, { timeout: 8000 });   // it would cover the chip
  await page.locator("#team .tm-courtcard").scrollIntoViewIfNeeded();
  await page.mouse.wheel(0, 150);
  await page.waitForTimeout(300);
  const chip = page.locator("#team .tm-courtcard .court .chip:not(.cap)").last();   // mid-screen: at an edge Playwright scrolls by itself
  await chip.scrollIntoViewIfNeeded();
  const y = await page.evaluate(() => scrollY);
  expect(y).toBeGreaterThan(100);
  await chip.click();
  await page.locator("#aCap").click();
  await expect(page.locator("#modal")).not.toHaveClass(/\bon\b/);
  await page.waitForTimeout(200);
  expect(Math.abs((await page.evaluate(() => scrollY)) - y)).toBeLessThan(5);
});

test("phones: a line above the court says how many steps are left and takes you to them; not on a PC", async ({ page }, testInfo) => {
  await open(page, "personal", { tab: "team" });
  const line = page.locator("#tmSteps");
  if (!isPhone(testInfo)) { await expect(line).toBeHidden(); return; }
  const n = (await page.locator("#tmTodo h2 small").innerText()).trim();     // «6 βήματα»
  await expect(line).toContainText(n);
  const [l, c] = [await line.boundingBox(), await page.locator(C).boundingBox()];
  expect(l.y).toBeLessThan(c.y);
  await line.click();
  await expect.poll(() => page.locator("#tmTodo").evaluate((el) => Math.round(el.getBoundingClientRect().top))).toBeLessThan(40);
  await checkLayout(page, "steps line");
});
