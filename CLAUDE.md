# CLAUDE.md — who does what in this repo

Two Claude sessions work on this repo, each on its own branch. The owner (VaGlar) merges.
How the project works is in `README.md`; this file is only about roles and rules.

## Roles

| Role | Branch | Owns (writes) | Does not touch |
|------|--------|---------------|----------------|
| **Developer** | `claude/vibrant-cannon-u7rds6` | product code: `elf/`, `web/`, `worker/`, `functions/`, `sources.yaml`, `preferences.yaml`, `README.md` | `tests/` beyond the tests of its own change |
| **Tester** | `claude/festive-babbage-gota28` | `tests/`, `.github/workflows/tests.yml`, `.coveragerc`, `docs/test-reports/` | product code: bugs go in a report or the PR, the developer fixes them (unless the owner asks the tester to) |
| **Owner** | — | merges, GitHub settings (rulesets, secrets, variables), Cloudflare, Patreon | — |

**Shared, owner's approval needed:** `.github/workflows/update.yml`, `lineup.yml`, `deploy-bot.yml`,
any secret or repo variable, rulesets and branch protection. Propose the change in the PR and say what
it affects. Don't merge it on your own.

## Rules for both

- **`main` is live.** The update bot pushes data straight to `main` several times a day. A ruleset,
  required check or protection that blocks those pushes stops the updates. Check this before
  suggesting any GitHub setting.
- **Sync with `main` before each new change.** `main` moves on its own with every data commit.
- **The repo is public.** Read «Public repo and private data» in the README before adding an output file:
  - every new `data/public` file goes into `PUBLIC_FILES` or `PRIVATE_ONLY` in `elf/publish.py`;
  - nothing personal goes in logs, test output or fixtures;
  - `tests/test_public_repo.py` enforces this.
- **Actions minutes count.** Tests run on PRs only, never twice. Batch pushes to an open PR. Don't
  re-run CI to "see if it passes".
- **Security headers** for the sites are in `web/_headers`. Pages Functions don't get them: a Function
  sets its own headers.
- No commit messages, comments or files that name a model.

## Developer

- New behavior comes with its tests (`python -m pytest --cov`; the coverage floor is in `.coveragerc`).
- Open the PR early (as a draft) to get CI. Read the tester's report in `docs/test-reports/` and the PR
  comments before merging.

## Tester

- Work as an independent tester:
  - read the developer's PRs and diff, and find what isn't tested;
  - add tests in `tests/` and report the rest.
- Never skip, xfail or weaken a test, and never lower `fail_under`, to get green. A known bug is pinned
  with a strict xfail that names it.
- Expected values come from the game's rules, the README or the owner, not from what the code returns now.
  When there is no source, label the test as characterization.
- **Reports:**
  - `docs/test-reports/YYYY-MM-DD-<branch>.md`, in Greek;
  - command outputs go in a `…-appendix/` folder next to the report, without local paths or secrets.
- Mutation testing (mutmut) runs locally only, on `optimize.py`, `lineup_cmd.py`, `publish.py`, `validate.py`.
  Never in CI: it takes too long.

## Handing over

- The PR description and the tester's report are the record between sessions. Don't rely on the
  other session's chat.
- A finding for the other role goes in the report, with file:line and a proposed fix or test.
