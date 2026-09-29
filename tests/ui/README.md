# UI tests (Playwright)

The dashboard in a real browser, both editions (`/personal/`, `/public/` = HoopsLab), on a PC screen
(1280×900), an iPhone-sized one (390×844, touch) and two Android phones (Pixel 7, 412px; Galaxy S9+, 320px —
the narrowest still around). Chrome on Android is Chromium like the tests, so those two are close to the real
thing; the iPhone runs are Chromium with the iPhone's screen, not Safari. They run in CI (`Tests` → `ui`) on main and on every change that can reach the dashboard
(`web/`, `tests/ui/`, `elf/publish.py`; the `changes` job decides, otherwise `ui` is skipped);
the report with a screenshot of every tab is the `ui-report` artifact.

```bash
cd tests/ui
npm ci
npx playwright install chromium        # once
npx playwright test                    # all
npx playwright test team.spec.mjs --project=iphone
```

- `fixtures/`: a frozen copy of `data/public` and the clock set just after it was generated, so the
  round, deadline and proposals are the same on every run. Refresh it when the data format changes:
  `for f in clubs model_params news players predictions report report_public tracking; do cp data/public/$f.json tests/ui/fixtures/; done`
- `serve.py` builds both editions from the fixtures (the public one through `elf.publish`).
- `helpers.mjs`: opening an edition, navigating like a user, the layout checks (no sideways scroll,
  nothing off-screen, cards not overlapping).
