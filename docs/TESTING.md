# Testing and the way a change reaches production

Nothing reaches `main`, and nothing is released, without passing the regression suite. The suite is permanent and
grows with the product: every feature that is confirmed working adds its tests, and every later change must keep them
all passing.

## The path of a change

1. **Branch.** Work on a branch (`fix/...`, `feat/...`). Every push runs the branch's own tests on GitHub
   (checks named `branch: static checks`, `branch: python tests`, `branch: browser tests`). Make them green: that
   proves the change works on its branch.
2. **Pull request into `main`.** The gate runs (`.github/workflows/tests.yml`, event `pull_request_target`):

   | Check | What it runs | Why |
   |---|---|---|
   | `static checks` | secrets scan, Python compiles, shell syntax, site type-check and build | the basics |
   | `python tests` | **main's** pytest suite against the PR's code, plus migrations on a throwaway Postgres | nothing that worked may break |
   | `browser tests` | **main's** browser journeys (Playwright) against the PR's code | the site still works for editors |
   | `PR's own tests` | the PR's version of the tests (new tests for the new feature) | the new feature works |
   | `tests added` | code changed but no test changed → fails (label `no-test-needed` allows it) | the suite grows with the code |

   The workflow file and the tests that judge a PR come from `main`, never from the PR. Editing, skipping or deleting
   a test in a PR does not change its own result.
3. **Merge.** The ruleset on `main` allows merging only when all five checks pass and the branch is up to date with
   `main` (so what was tested is what lands). No direct pushes to `main`, no force pushes, no deleting `main`, for
   anyone.
4. **Release.** Publish a GitHub Release `vX.Y.Z` from `main`. `release.yml` installs it only if that exact commit
   passed `static checks`, `python tests` and `browser tests` on GitHub (the run after the merge), then deploys to
   the machines, checks `/api/health` and rolls back by itself if it fails.

**Changing what an existing test expects** (a deliberate behaviour change asked for by the owner) takes two pull
requests. The first changes only the test (it passes, because the code has not changed yet) and says why in its
description. The second changes the code. Both stay visible in git history.

## Running the tests yourself

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r tests/requirements.txt
PYTHON=.venv/bin/python tests/ci.sh python      # ~250 tests, ~10 s
PYTHON=.venv/bin/python tests/ci.sh browser     # builds the site, ~10 browser journeys, ~1 min
PYTHON=.venv/bin/python tests/ci.sh static
```

The migration tests need a throwaway Postgres: `RIGVIDEO_TEST_PG=postgresql://user@127.0.0.1:5432/db`. Without it they
are skipped on a laptop. In CI they always run. **Never point it at a real database.**

## What the suite covers

| File | Covers |
|---|---|
| `test_routes.py` | Every API route, from the app's own route table. A new route fails the suite until it is listed and tested. Every route needs sign-in except the public ones. No route shows or changes a story from another workspace. |
| `test_auth.py` | Sign-in, 5-wrong-tries lock, Secure cookie on HTTPS, forged or expired sessions, sign-out |
| `test_desk.py` | Picks and reserves, removed picks, workspace isolation, archived stories, private fields, preferences, queue |
| `test_create.py` | New stories from text, link, file (txt, md, docx, pdf) and picks; every refusal |
| `test_story_flow.py` | Script edits, Approve, re-voicing, type switch, retries, keywords, moments, uploads, maps, places, rewrite, render queue, cancel, move up |
| `test_posting.py` | Unlisted upload once, Post, never twice, anchor-only auto-post at 60 min, Post all |
| `test_remake_discard.py` | Remake (to Review or straight to the queue), Discard, both refused while public or uploading |
| `test_files.py` | Story files: only that story's, never outside its folder, private folders hidden |
| `test_daily.py` | The 08:00 daily run: main picks only, once a day, never two stories from one pick |
| `test_resume.py` | Restart recovery: jobs resume, renders requeue, posts never repeat, one render at a time, only in the window |
| `test_store.py` | Safe ids, locking under parallel writers, render window and hold, text-share rule, passwords |
| `test_writer.py` | Script checks: every number and name from the article, VO beat rules, busy GPU detection |
| `test_worker.py` | Numbers read aloud, re-voice notes, search re-spelling, event dates, search pipelining, the daily chain write → approve → voice + search → keep VO or add an anchor |
| `test_selection.py` | Hard news only, 8+ outlets, mix caps, no duplicate stories, short or dead articles skipped |
| `test_youtube_upload.py` | Resumable upload against a fake YouTube |
| `test_migrations.py` | Database migrations: apply, undo exactly, all-or-nothing, edited files refused |
| `e2e/journeys.spec.ts` | In a real browser: sign-in, Desk, every story step, Render page, Remake, Discard, Library |

**Not covered here, by design:** the GPU renders, real voices, real LLM answers and real YouTube. They need the
machines and live accounts. `ops/doctor.py` checks the machines twice a day.

## Writing a test

- Put it in `tests/`, in the file for that part of the product (or a new `test_<part>.py`).
- Use the helpers in `tests/conftest.py`:
  - `ed` / `outsider` give a signed-in browser for the API.
  - `at_stage("review")` makes a story the way the real flow leaves it.
  - `spawned` lists the machine jobs the API asked for.
- Tests run in their own empty data folder. They can never start a real process (they fail if they try) or read
  this machine's keys.
- A test must fail when the behaviour breaks. Before you rely on a new test, break the code on purpose once and watch
  it go red.
- A bug fix comes with the test that would have caught the bug.
