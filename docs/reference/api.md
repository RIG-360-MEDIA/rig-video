# Reference: the API, storage, script writer and LLM pool

> `file:line` references point at the code as of 2026-11-25; after later changes, search by the name given next to them.

This chapter is the code-level reference for five files and the two helpers they share:

| File | Lines | What it is |
|---|---|---|
| `server/app.py` | 1027 | FastAPI app: sign-in, every HTTP route, job spawning, the job loop (`monitor`), the daily run, auto-posting |
| `server/store.py` | 308 | Project storage on disk, file locks, t3 GPU switch, render window, accounts and sessions |
| `server/writer.py` | 439 | Script prompts, JSON schemas, code checks, and the one function that talks to the writer model |
| `tests/` | the regression suite | Run by CI on every pull request; see `docs/TESTING.md` |
| `studio-app/pipeline/orchestrator/llm.py` | 119 | The LLM provider pool (fallback path) |
| `studio-app/pipeline/orchestrator/common.py` | 85 | Shared paths and `load_env()` |

It assumes you have read the overview in `docs/HANDOFF.md`. For what the jobs do, see HANDOFF section 4 ("The life of
one story"); for where files live, section 8 ("Data"); for env files, section 11 ("Configuration and secrets"); for
restarts, section 12. References below are `file:line`. Times are IST.

---

## 1. `server/app.py`

### 1.1 Startup and module state

The API runs under uvicorn as `rigvideo-api.service` on t7 (`hosts/t7/systemd/rigvideo-api.service`):
`uvicorn app:app --host 100.72.225.89 --port 8770`, working directory `~/anchor-studio/rigvideo/server`,
`EnvironmentFile=~/.config/rigvideo/api.env`, `STUDIO_DATA=~/anchor-studio/rigvideo-data`, `LLM_PROVIDERS=[t3, groq]`,
`KillMode=process` (a restart of the API does not kill its child jobs), `Restart=always`.

Module-level names (`app.py:19-32`):

| Name | Value | Use |
|---|---|---|
| `HERE` | the `server/` folder | `worker.py` is started from here; also `cwd` of every job |
| `APPDIR` | env `RIGVIDEO_APP`, else `~/anchor-studio/studio-app` | Finds the anchor registry and `pipeline/` |
| `REG` | `APPDIR/anchor_registry` | `registry.json`, faces, voice files |
| `TOOLS_PY` | env `ANCHOR_TOOLS_PY`, else `~/.cache/anchor-tools/bin/python` | Interpreter for every `worker.py` job |
| `DIST` | `HERE.parent / "dist"` | The built website. The SPA route exists only if this folder exists at import time. |
| `LOCK` | `threading.Lock()` | Guards `RUNNING`, `CUTTING` and the start of a job |
| `RUNNING` | `{(project id, job): Popen}` | Jobs this API process started. Empty after an API restart. |
| `COOKIE` | `"rv_session"` | Session cookie name |
| `FORMATS` | `("anchor_vo", "anchor_only", "vo_only")` | Valid story formats |
| `CUT_KEYS` | 16 keys (`id, shot, at, secs, src, kind, fit, shows, sound, poster, clip, fill, swapped, review, repeat, byUser`) | The only cut fields `PUT /api/projects/{pid}` keeps from the site |

On startup (`_start`, `app.py:161`) it creates `PROJECTS` and starts one daemon thread named `monitor`. `/api/health`
reports whether that thread is alive.

### 1.2 Auth: cookies, `user()`, `mine()`

- **Sign-in** (`login`, `app.py:54`): `store.check_password(email, password)`. On failure it sleeps 1 s and returns 401.
  On success it sets cookie `rv_session` = `store.session_token(user id)`: `max_age` 30 days, `httponly`,
  `samesite=lax`, and `secure` only when env `RIGVIDEO_HTTPS=1`.
- **Token** (`store.py:239-253`): `"<uid>.<expiry unix seconds>.<hmac-sha256 hex>"`, signed with `rigvideo-data/session.key`.
  There is no server-side session list. A token is valid while the signature matches, it has not expired, and the user
  id still exists in `users.json`.
- **Sign-out** (`logout`, `app.py:65`) only deletes the cookie in the browser.
- **`user(request)`** (`app.py:37`): FastAPI dependency. Returns the user dict or raises **401 "Sign in first."**
  Every route that declares `u=Depends(user)` needs a valid cookie.
- **`mine(pid, u)`** (`app.py:44`): reads the project. Raises **404 "No such story."** if the id is invalid, the project
  does not exist, or its `_workspace` is not the user's `workspaceId`. Stories of another workspace look missing, not
  forbidden.
- **Roles** (`admin` / `editor`) are stored and returned by `/api/desk`, but no route checks them.

### 1.3 Starting jobs

**`spawn(pid, job, *args)`** (`app.py:73`), under `LOCK`:
1. Returns without doing anything if this job is already running: either `RUNNING[(pid, job)]` has not exited, or the
   project's `_jobs[job].state == "running"` and its `os_pid` is alive. The running job picks up new work itself.
2. `store.job(pid, job, state="running", progress=0.0, note="Starting", error=None)`.
3. Appends `===== <IST stamp> <job> <args>` to `projects/<id>/log.txt`.
4. Starts `TOOLS_PY worker.py <job> <pid> <args...>` with stdout and stderr into `log.txt`, `cwd=server/`,
   `start_new_session=True`, stores the `Popen` in `RUNNING`, then saves `os_pid` into `_jobs[job]`.

**`alive(os_pid)`** (`app.py:88`): true if `/proc/<os_pid>` exists.

Jobs started outside `spawn` and not tracked in `_jobs`:

| Starter | Command | Tracked |
|---|---|---|
| `spawn_cut(pid)` (`app.py:496`) | `worker.py cut <pid>` | In `CUTTING[pid]` only. A second call while one runs does nothing; the running one loops until nothing is left to cut. |
| `spawn_keyword(pid, sid, kid)` (`app.py:700`) | `worker.py keyword <pid> <sid> <kid>` | Not tracked. Several may wait at once on the search lock. Progress lives on the keyword itself in `visuals`. |
| `monitor` selection | `worker.py selection` | `monitor.sel` / `monitor.sel_t` (function attributes). Output to `selection/log.txt`. |

Workers start further jobs themselves with `worker.start_job` (`worker.py:1127`), which follows the same rules as `spawn`
but does not touch `RUNNING`.

**`busy(p, job)`** (`app.py:391`): `_jobs[job].state == "running"`.

### 1.4 The render queue: `queue()`

`queue()` (`app.py:92`) returns every project (all workspaces) whose `render.state` is `queued`, `rendering` or
`assembling`, sorted by `(state == "queued", _queuedAt)`. Running renders sort first, then queued ones oldest first.
`_queuedAt` is set by `POST /render` and swapped by `POST /moveup`.

### 1.5 `resume(p, job, j)` (`app.py:100`)

Called by the monitor for a job marked running whose process is gone. `AUTO_RESUME` = env `RIGVIDEO_AUTO_RESUME`,
default 2 (`app.py:97`).

| Case | Result |
|---|---|
| `job == "post"` | Never resumed (returns False). A repeated post could upload twice. |
| resumes so far `>= AUTO_RESUME` | Not resumed (returns False). For `render` the count is `render.resumes`; for other jobs `_jobs[job].resumes`. |
| `job == "render"` | `_jobs.render` is removed and `render` becomes `{state: "queued", resumes: n+1}`. It waits for the render window like any queued render. |
| `job == "final"` | `spawn(pid, "final", "again")`, then `resumes = n+1`. |
| any other job | `spawn(pid, job)`, then `resumes = n+1`. |

It prints `resume <id> <job> (n/2)` to the API's journal.

### 1.6 The job loop: `monitor()` (`app.py:117`)

An endless loop; each pass is wrapped in `try/except` that prints `monitor: <error>` and carries on; then it sleeps
4 seconds. One pass does, in order:

1. **Forget finished children.** Under `LOCK`, removes from `RUNNING` every `Popen` that has exited.
2. **Reap and auto-post, per project** (`store.all_projects()`, every workspace):
   - For every `_jobs[job]` with `state == "running"`, not in `RUNNING`, and `os_pid` not alive:
     - if `resume()` returns True, go on;
     - else mark the job failed: `error` and `note` = "Interrupted (machine restart?). Try again." Also:
       `render` → `render.state = "failed"`, `heldReason` "Interrupted. Send it to render again.", `stage = "review"`;
       `final` → `final.state = "failed"`, note "Interrupted. Make it again.";
       `post` → every `posts.*` in `posting`/`uploading` becomes `failed` with "Interrupted. Post again."
   - `auto_post(p)`, inside its own `try/except` so one story's error does not stop the loop.
3. **Start the next render.** If `queue()[0]` is `queued` (so nothing is rendering or assembling), no `render` key is in
   `RUNNING`, and `store.in_render_window()`: set `render.state = "rendering"` and `spawn(id, "render")`.
4. **Selection.** If env `RIGVIDEO_NO_SELECTION` is not `1`, and `selection/<today IST>.json` does not exist, and no
   selection process has been started or the last one has exited and was started more than 1800 s ago: start
   `worker.py selection`. So it retries at most every 30 minutes until the file exists.
5. **Daily run.** If env `RIGVIDEO_DAILY_AUTO == "1"` and the IST time `HH:MM` is `>=` `RIGVIDEO_DAILY_AT` (default
   `08:00`, compared as strings): `daily_start()`. It does nothing if today's marker exists or today's selection does not.

### 1.7 `auto_post(p)` (`app.py:908`)

Runs for every project on every monitor pass. It acts only when `stage == "done"`, `public(p).final` is `ready`, not
`stale`, has `builtAt`, and no `post` job is running. `age` = minutes since `final.builtAt`.

| Condition | Action |
|---|---|
| no `posts.youtube` yet and `age < 24 h` | `queue_post(..., "auto", upload_only=True)` with the default title and description: uploads **unlisted** into "Awaiting approval". For `anchor_only` it also stores `autoAt` = `builtAt + AUTO_PUBLISH_MIN`. |
| `posts.youtube.state == "awaiting"`, format `anchor_only`, `age >= AUTO_PUBLISH_MIN` | `queue_post(..., "auto")` with the stored title and description: makes it **public**. |

`AUTO_PUBLISH_MIN` = env `RIGVIDEO_AUTO_PUBLISH_MIN`, default 60 (`app.py:905`). Finals older than a day with no post
record are left alone.

### 1.8 Posting helpers

- **`post_text(p)`** (`app.py:842`): title = headline, cut to 97 characters at a word plus "..." if over 100.
  Description lines: "Video Bulletin", blank, the first part's text; "Read the full story: <url>" only if the source URL
  contains `/long-read/` (the DNL CMS maps the video to its story from this line); "Voiced by <anchor>, an AI-generated
  voice." (VO only) or "Presented by <anchor>, an AI-generated news anchor."; "The script is written from Democracy
  News Live's reporting."
- **`can_post(p, platform)`** (`app.py:882`): returns `""` if postable, else the reason: final not ready or stale;
  already posted; posting/uploading or a `post` job running.
- **`queue_post(pid, platform, title, description, by, upload_only=False, extra=None)`** (`app.py:895`): writes
  `posts[platform]`, keeping `videoId, url, fp, sent, queued, uploadedAt, autoAt` from the old record (so a retry never
  uploads a second copy), sets `state` `uploading` (upload only) or `posting`, `title`, `description`, `by`, `at`, and
  `auto: true` when `by == "auto"`. Then `spawn(pid, "post", platform[, "upload"])`.
- `PLATFORMS = ("youtube",)` (`app.py:839`).

### 1.9 The daily run: `daily_start(only=None)` (`app.py:323`)

- **Automatic** (`only=None`, from the monitor): returns `[]` if `daily/<today>.json` exists or
  `selection/<today>.json` does not. Otherwise it makes every **main** pick (not reserves) that has no project yet in
  the `dnl` workspace, then writes the marker `{"at": stamp, "projects": [ids]}`.
- **By hand** (`only` = list of pick ids, from `POST /api/daily/start`): makes just those picks, reserves included, at
  any time, from the newest selection file. No marker is written.
- **Owner**: the first user with `workspaceId == "dnl"` and `role == "admin"`, else the first `dnl` user. With no `dnl`
  user the `next()` raises and the monitor logs the error.
- **Each project**: `make_project(headline, {kind: "link", url, site: "DNL selection", text: article body}, 60, place,
  "vo_only", "dnl", owner, {_pick, _daily: <date>, _autoApprove: True, formatWhy: {by: "auto", text: "Daily run:
  starts with no anchor; the footage check decides.", at}})`, then `spawn(id, "write")`.
  `_autoApprove` makes the worker approve the script by itself and start voice and search (`worker.step_write`,
  `worker.py:207`).

### 1.10 `make_project(...)` (`app.py:314`)

`store.create()` with: `headline`, `source`, `targetSeconds`, `anchorId = pick_anchor(place)`, `tone "Serious"`,
`stage "script"`, `format`, `versions {anchor_vo: [], anchor_only: [], vo_only: []}`, `_place`,
`lt {kicker, headline, subline: ""}`, `ticker []`, `facts []`, `visuals {}`, `_workspace`, `_by`, plus `extra`.

### 1.11 `pick_anchor(country)` and `REGION` (`app.py:263-276`)

`REGION` maps 2-letter country codes to a region:

| Region | Codes |
|---|---|
| `russia_ukraine` | RU, UA |
| `south_asia` | IN, PK, BD, LK, NP |
| `middle_east` | IL, PS, IR, SA, IQ, SY, LB, YE, EG |
| `turkey` | TR |
| `north_america` | US, CA |
| `latin_america` | BR, MX, AR, CO, VE |
| `east_asia` | CN, JP, KR, TW |
| `southeast_asia` | PH, ID, TH |
| `uk` | GB |
| `oceania` | AU, NZ |
| `africa` | NG, KE, ZA, ET, SD |

Any other code, or none, means `europe`. `pick_anchor` returns the first anchor in `registry.json` with
`status == "ready"` whose `affinity` contains that region, else the first ready anchor.

### 1.12 `selection()` mapping (`app.py:185`)

Reads the **newest** `selection/20*.json` (sorted by name). `made` = that file's modification time in IST. Each entry of
`picks` then `reserves` becomes one desk pick:

| Pick field | From |
|---|---|
| `id` | `event_id[:8]` |
| `reserve` | `true` for entries after the main picks (field absent otherwise) |
| `headline`, `deck` | `headline`, `deck` (or `""`) |
| `type` | `label.category`, default `turmoil_unrest` |
| `place` | `label.country`, else `country`, else `""` |
| `source` | `"<n> sources"` if `sources` is an int, else `""` |
| `url` | `https://democracynewslive.com/long-read/<event_id>` |
| `publishedAt` | `made - age_h hours`, ISO to the minute |

It also returns `bodies = {pick id: body}`, the article text used as the story source.

### 1.13 Views

- **`anchors()`** (`app.py:173`): per registry anchor: `id`, `name` (or the id title-cased), `gender` (`male` if
  `M`, else `female`), `face`/`frame` URLs under `/anchor-media/`, `voiceSample` (only if `voice_file` is set),
  `wordsPerSecond` (from `calibration.json`, else `voice_wps`, else 2.85), `regions` (= `affinity`),
  `offered` (= `status == "ready"`).
- **`job_view(p)`** (`app.py:206`): the first of `write, search, check, voice` present in `_jobs` (voice only when it
  failed), as `{kind, progress, note, failed?, parts?}`. `parts` (per-part search progress) is included unless failed.
- **`view(p)`** (`app.py:216`): `store.public(p)`. While the render is queued, rendering or assembling it adds
  `render.queuePosition` (index in `queue()`), and if queued outside the render window `render.waitNote`
  = "Starts at <window start> IST".

### 1.14 Other helpers

| Function | Line | What it does |
|---|---|---|
| `registry()` | 169 | `registry.json["anchors"]`, read on every call |
| `file_text(name, data)` | 360 | Text of `.txt`/`.md` (UTF-8), `.docx` (zip + XML `w:t` runs per `w:p`), `.pdf` (pypdf). 400 on unreadable files or other types. |
| `uncut(p)` | 481 | True if a placed moment has no `clip` and no `cutFailed` |
| `switch_to(pid, fmt, why, by)` | 534 | `store.switched()` under the project lock; then `spawn(write)` or `spawn(voice)` + `spawn(search)` |
| `named(text, common)` | 639 | Places a text names (see `/api/places`): capitalised runs; 3- then 2-word phrases that are place names win and their words are not tried alone; leftover single words (minus `common`) match a place's main name; biggest population first |
| `save_file(pid, sub, f, allowed)` | 752 | Streams an upload to `media/<sub>/<8 hex>.<ext>` in 1 MB chunks; 400 for a wrong extension, 413 over `MAX_UPLOAD` (500 MB) |
| `probe_seconds(f)` | 770 | ffprobe duration; 400 if unreadable |
| `new_visuals` | 506 | Alias of `store.new_visuals` |

Constants: `IMG = {.jpg .jpeg .png .webp}`, `VID = {.mp4 .mov .m4v .webm}` (`app.py:747`), `PLACES` (GeoNames cache,
loaded on the first `/api/places` call), `ANCHOR_SRC` (`app.py:1006`), `REWRITE` (the rewrite prompt, `app.py:584`).

---

## 2. API reference

"Auth" = needs the `rv_session` cookie (401 "Sign in first." without it). Every `{pid}` route also runs `mine()`, so a
missing story or one from another workspace gives **404 "No such story."** Bodies are JSON unless marked *form*.
Unless stated, the response is the project as `view()` returns it.

### 2.1 Session, health, desk

| Method | Path | Auth | Body | What it does | Response | Errors |
|---|---|---|---|---|---|---|
| POST | `/api/login` (`app.py:54`) | no | `email`, `password` | Checks the password, sets the cookie | `{ok: true}` | 401 "That email and password don't match." (after a 1 s wait) |
| POST | `/api/logout` (`:65`) | no | — | Deletes the cookie | `{ok: true}` | — |
| GET | `/api/health` (`:226`) | no | — | Deploy and boot check | `{ok, version (the VERSION file next to server/, else "dev"), monitor (thread alive)}` | — |
| GET | `/api/desk` (`:234`) | yes | — | Everything the Desk shows | `{user {id,name,email,role,workspaceId}, workspace, picks, hiddenPicks, defaults, formats, anchors, projects (non-archived, as view()), jobs {id: job_view}, queue (render records of this workspace), library (from `_library`, newest first)}` | — |
| PUT | `/api/prefs` (`:250`) | yes | `defaults` (only keys already in defaults; `format` must be valid), `hiddenPicks` (strings cut to 20 chars, last 500 kept) | Saves per-user prefs | the prefs | — |

`picks` on the desk: only when the workspace has `picksFeed`. A pick already made into a story (any user's `_pick`) or
hidden by this user is removed, and the list is cut to the number of main picks, so a reserve fills each gap.

### 2.2 Creating stories

| Method | Path | Auth | Body | What it does | Jobs | Errors |
|---|---|---|---|---|---|---|
| POST | `/api/projects` (`:279`) | yes | `kind` (`pick`/`link`/`text`/`file`), `pickId`, `url`, `text`, `name`, `seconds` (default: prefs length), `format` (default: prefs format) | Makes a project. `pick`: text, url, place and headline from today's selection, `_pick` set. Headline otherwise: file name without extension, else the text's first line (90 chars), else the URL's last segment. `source.site`: "DNL selection" for picks, else the URL's host without `www.` | `write` | 400 length not 20–600 s; 404 pick not in selection or workspace not `dnl`; 400 link not `http(s)://`; 400 text/file under 40 words; 400 unknown source; 400 unknown format |
| POST | `/api/projects/file` (`:382`) | yes | *form*: `file`, `seconds` (60), `format` | Reads up to 20 MB, extracts text (`file_text`), squeezes spaces, keeps 40,000 chars, then the same as `kind: "file"` | `write` | 413 over 20 MB; 400 unreadable or wrong type; plus the `/api/projects` errors |
| POST | `/api/daily/start` (`:352`) | yes | `pickIds` | `daily_start(pickIds)` by hand | `write` per story | 400 "Give the pick ids (DNL workspace)." if no ids or workspace not `dnl` |
| POST | `/api/picks` | yes | `kind` (`link`/`text`), `url` or `text` | Adds an own pick to today's picks (DNL desk). Before the daily run it waits; after 08:00 it starts at once (`start_pick`: VO only, 60 s, auto-approved). Returns `{pick, started}` | `write` if started | 400 not DNL / too short / not a link; 409 same link twice |
| POST | `/api/picks/file` | yes | multipart `file` (pdf/docx/txt/md) | The same from a file | `write` if started | 400, 413 over 20 MB |
| DELETE | `/api/picks/{pick}` | yes | | Removes an own pick for everyone | | 404 not found / other workspace; 409 already a story |
| POST | `/api/library/{item}/duplicate` (`:981`) | yes | — | `item` = `lib-<pid>`. Copies the public fields except `id, render, videoId, createdAt, updatedAt, edit`; parts keep only `id, kind, text, picture, search, cls` (no voices); headline + " (copy)", `stage "script"`, empty `visuals`; keeps `_search`, `_vo`, `_place` | none | 404 |

### 2.3 Editing a story

| Method | Path | Auth | Body | What it does | Jobs | Errors |
|---|---|---|---|---|---|---|
| PUT | `/api/projects/{pid}` (`:395`) | yes | any of `headline, targetSeconds, tone, format, facts, ticker, lt, stage, anchorId, versions, visuals, edit` | The site's save; see 2.3.1 | `write`, `voice`, `cut` as needed | 409 "The script is still being written."; 400 unknown format; 400 "No such anchor." |
| POST | `/api/projects/{pid}/approve` (`:509`) | yes | — | `store.approved` | `voice` + `search` | 409 "Wait until the script is written." (writing, or no parts in this format) |
| POST | `/api/projects/{pid}/switch` (`:521`) | yes | `format` (`vo_only` or `anchor_vo`, not the current one) | `switch_to(..., "Switched by <name>", "editor")` | `write`, or `voice` + `search` | 400 "Choose the other type."; 409 while `stage` is `render`/`done` or writing |
| POST | `/api/projects/{pid}/retry` (`:545`) | yes | `job`, `sid` (check only) | See 2.3.2 | the job | 409, 404 (see below) |
| POST | `/api/projects/{pid}/revoice` (`:569`) | yes | `sid`, `note` (300 chars) | The part's voice → `state "redoing"`, `note` | `voice` | 404 "No such part." |
| POST | `/api/projects/{pid}/rewrite` (`:594`) | yes | `scope` (`all` or a part id), `chips` (list), `note` | AI rewrite proposals, see 2.3.3 | none (runs inside the API) | 503 "The script model is not answering right now." |

#### 2.3.1 What `PUT /api/projects/{pid}` merges (`merge`, `app.py:406`)

All under the project lock, in one `store.update`:
- Copies `headline, targetSeconds, tone, format, facts, ticker, lt` as given.
- `stage` changes only between `script`, `visuals` and `review`, and only if the story is in one of those.
- `anchorId` must exist in the registry. A changed anchor resets every voiced part to `making` with no takes.
- `versions[fmt]` (valid formats only) replaces the part list. Per part: `id` (24 chars), `kind` (`vo` or `anchor`),
  `text`; `picture`, `search`, `cls` from the body or the old part (300 chars). Voice:
  - the old voice is kept; a new part added after approval in the current format gets `{state: "making"}`;
  - the site may change only `voice.pick`, and only to an existing take id;
  - changed text or kind resets the voice to `making` (takes kept unless the anchor changed);
  - every part left `making` or `redoing` is queued for re-voicing.
- After approval, every part of the current format gets a `visuals` entry if missing.
- `visuals[sid]`: `placed` is replaced. `keywords`, `uploads` and `maps` can only **lose** items (adding goes through
  their own routes). Removed keyword ids are recorded in `_removedKeywords[sid]`, and `found` videos of removed keywords
  are dropped.
- `edit.beats[*].cuts` (VO only, only while `edit.state == "ready"`): replaces a beat's cuts. Each cut must be a dict
  with a dict `src`; only `CUT_KEYS` are kept; `sound` is whitespace-squeezed and cut to 80 characters.
- If the story is at `script`, the current format has no parts, and nothing is writing: a `write` is started (the
  editor switched to a format not written yet).

After saving: `spawn(write)` if needed; `spawn(voice)` if any part needs voicing and the stage is past `script`;
`spawn_cut(pid)` if `uncut(p)`.

#### 2.3.2 `POST /retry` cases (`app.py:545`)

| `job` | Allowed when | Does |
|---|---|---|
| `check` | format `vo_only`, stage not `script`, no check running. `sid` optional, must be a beat id. | Sets `edit.state = "checking"`, `progress 0` (creates `edit` if missing), clears `_jobs.check`, `spawn(check[, sid])` |
| `write` | stage `script`, the format has no parts, not writing | `spawn(write)` |
| anything else | `_jobs[job].state == "failed"` | Clears the job, `spawn(job)` |

Errors: 409 "The clips can be checked once the script is approved, and not while a check runs."; 404 "No such beat.";
409 "Nothing to retry."

#### 2.3.3 `POST /rewrite` (`app.py:594`)

- Imports `orchestrator.common`, `orchestrator.llm` and `writer`, then `common.load_env()`.
- Sections = the current format's parts where `scope` is `all` or the part's id.
- Request text = `chips` joined with ", " plus ". <note>"; empty means "tighten it".
- Lengths: `writer.plan(targetSeconds, 328/24 - 0.7, anchor wps)`; anchor parts get `a_words`, VO parts `v_words`
  as `target`.
- Up to 2 rounds. Each round, under `store.gpu("writer")`, calls `writer.ask(REWRITE, ...)` with the source (14,000
  chars), the story's facts, the request, and the remaining sections as JSON `{id, kind, text, words, target}`. The
  schema forces `{"sections": [{"id": <one of the asked ids>, "text"}]}`, `max_tokens` 4000. Sections that came back
  unchanged are asked again in round 2.
- `REWRITE` (`app.py:584`) tells the model: only facts from the source, the facts list (which wins over the source) and
  the request; keep each section's job; stay within 10% of `words` unless the request is about length; when asked
  shorter or longer, end within 10% of `target` if that is the asked direction, else change the length by about a
  quarter; every given section must change.
- **Response:** `{part id: new text}` for changed sections only. The site keeps or rejects each. Nothing is saved.
- **Errors:** `llm.LLMUnavailable`, or `gpu.sh` failing or timing out, give 503 if nothing came back yet (else the
  proposals so far are returned). `writer.Busy` is not caught here, so a busy t3 returns HTTP 500.

### 2.4 Visuals (anchor formats)

| Method | Path | Auth | Body | What it does | Jobs | Response / errors |
|---|---|---|---|---|---|---|
| GET | `/api/places` (`:666`) | yes | query `q` or `text` | Loads `rigvideo-data/geo/cities15000.txt` (GeoNames) once. `text`: up to 4 places the text names (`named(text, writer.COMMON)`). `q` (2+ chars): up to 6 places whose name or alternate name starts with `q`, main-name matches first, then by population | none | `[{name, lat, lon, iso}]`; `[]` if `q` under 2 chars |
| POST | `/api/projects/{pid}/keywords` (`:685`) | yes | `sid`, `text` (120 chars) | Adds keyword `k<6 hex>` with `reason "Added by you"`, `state "queued"` | `worker.py keyword` | view; 400 "Type a keyword." (no text or unknown part); 409 duplicate keyword (case-insensitive) |
| POST | `/api/projects/{pid}/keywords/{kid}/research` (`:707`) | yes | `sid` | Keyword back to `queued`, "Searching again" | `worker.py keyword` | view; 404 "No such keyword." |
| POST | `/api/projects/{pid}/moments` (`:719`) | yes | `videoId`, `start`, `end` | Turns a range marked on a found video into a moment. `end` is capped at the video's duration. Reuses a moment within 0.15 s at both ends, else appends `{label "Your clip", score 0, custom: true}` | none | `{moment: index, project: view}`; 400 missing/invalid start or end; 404 "No such video."; 400 range not inside the video |
| POST | `/api/projects/{pid}/uploads` (`:778`) | yes | *form*: `sid`, `file` | Saves to `media/uploads/`, appends `{id "up<6 hex>", src "/files/<pid>/media/uploads/...", kind video\|image, name, seconds (videos)}` | none | the item; 404 "No such part."; 400 wrong type or unreadable video; 413 over 500 MB |
| POST | `/api/projects/{pid}/maps` (`:792`) | yes | *form*: `sid`, `title`, `file` (picture) | Saves to `media/maps/`, appends `{id "map<6 hex>", src, title}` | none | the item; 404; 400; 413 |

### 2.5 Render, final video, posting, queue

| Method | Path | Auth | Body | What it does | Jobs | Errors |
|---|---|---|---|---|---|---|
| POST | `/api/projects/{pid}/render` (`:805`) | yes | `outro` (default on) | Puts the story in the queue: `stage "render"`, `_queuedAt`, `extras.outro`, `render {projectId, state "queued", queuePosition 0, percent 0, etaIso null}`. The monitor starts it. | `render` (later, by the monitor) | 409 "Wait until every part has its voice."; 409 "Wait until the edit is checked." (VO only) |
| POST | `/api/projects/{pid}/final` (`:824`) | yes | — | Makes the VO final again; `final.state "building"` | `final again` | 409 nothing to make (`final_fp` is None); 409 being made; 409 outside the render window |
| GET | `/api/projects/{pid}/post` (`:858`) | yes | — | Default post text | — | `{platforms, title, description}` |
| POST | `/api/projects/{pid}/post` (`:865`) | yes | `platform`, `title` (100 chars), `description` (5000 chars) | Publishes (`queue_post(..., by = email or id)`) | `post youtube` | 400 "That account is not connected yet."; 400 "Give it a title."; 409 `can_post` reason |
| POST | `/api/post-all` (`:926`) | yes | `ids` | Each story: same checks as one Post; title/description from `posts.youtube` if set, else `post_text` | `post youtube` per story | Never fails as a whole: `{posted: [ids], skipped: {id: reason}}` ("Not found." for a missing story) |
| POST | `/api/projects/{pid}/cancel` (`:948`) | yes | — | Removes a **queued** render; `stage "review"` | none | 409 "Only a waiting render can be cancelled." |
| POST | `/api/projects/{pid}/moveup` (`:960`) | yes | — | Swaps `_queuedAt` with the queued story ahead | none | `{ok: true}` (no error if already first or not queued) |
| POST | `/api/projects/{pid}/archive` (`:972`) | yes | — | `_archived = true` (hidden from the desk) | none | `{ok: true}`; 409 while any job runs, or (a rendered story) while its YouTube video is public, being made public or uploading |
| POST | `/api/projects/{pid}/remake` | yes | `{now?: bool}` | A rendered story (`stage done`) is opened again: `stage review`; `render`, `final`, `_library`, `videoId` removed; `posts.youtube` moved to `_oldPosts` (the YouTube upload is left as it is). `now`: then queued for render as it is, with its old outro choice | as `view()` | 409 when not rendered, or its YouTube video is public / being posted / uploading |

### 2.6 Files and the website

| Method | Path | Auth | What it does | Errors |
|---|---|---|---|---|
| GET | `/files/{pid}/{rel}` (`:996`) | yes + `mine` | Serves a file inside the story folder | 404 if the path leaves the folder, is not a file, or starts with `footage/`, `render/` or `voice/` (unless it contains `/takes/`, so voice takes are served) |
| GET | `/anchor-media/{aid}/{name}` (`:1010`) | yes | `name` is `face.jpg` (registry `identity_face`, 320 px wide), `frame.jpg` (`identity_ref`, 960 px) or `voice.mp3` (`voice_file`, first 12 s, 96 kb/s). Made once with ffmpeg into `rigvideo-data/anchors/<aid>_<name>`, then served with `Cache-Control: max-age=86400` | 404 unknown anchor, name, or no source file |
| GET | `/{path}` (`:1023`) | **no** | SPA fallback, registered last and only if `dist/` exists: the file under `dist/` if `path` points to one, else `dist/index.html` (client-side routes). It also answers any unmatched GET, including unknown `/api/...` paths. | — |

---

## 3. `server/store.py`

Stdlib only. Imported by both the API and the workers.

### 3.1 Constants and paths

| Name | Line | Value |
|---|---|---|
| `HOME` | 22 | `Path.home()` |
| `DATA` | 23 | env `STUDIO_DATA`, else `~/anchor-studio/rigvideo-data` |
| `PROJECTS` | 24 | `DATA/projects` |
| `IST` | 25 | UTC+5:30 |
| `WORKSPACES` | 26 | `{"dnl": {id "dnl", name "DNL", kind "dnl", picksFeed: True}}` (the only workspace, in code) |
| `T3` | 92 | `ssh -o BatchMode=yes -o ConnectTimeout=20 -i <key> <host>`; key = env `ANCHOR_VOICE_KEY` else `~/.ssh/to_trijya3`; host = env `ANCHOR_VOICE_HOST` else `trijya-3@100.99.155.88` |

### 3.2 Time and ids

| Function | Line | What it does |
|---|---|---|
| `now()` | 29 | Current time in IST |
| `stamp()` | 33 | `now()` as ISO, to the second |
| `pdir(pid)` | 37 | `PROJECTS/<pid>`. Raises `KeyError` unless `pid` matches `[a-z0-9-]{3,60}` (blocks path tricks) |
| `slug(text)` | 112 | Lower case, non-alphanumerics to `-`, first 5 words, 40 chars, else `story` |

### 3.3 Locks

All locks are `fcntl.flock` on files in `DATA` (or the project folder), so they work across processes.

| Lock | Kind | Held by |
|---|---|---|
| `projects/<id>/.lock` | exclusive | `read()` and `update()` (and so `job()`) |
| `search.lock` | **shared** | `worker.step_search` (`worker.py:1006`), `step_keyword` (`:1053`), `step_cut` (`:1080`), `step_check` (`:1363`), `step_final` (`:1460`). Any number at once. |
| `search.lock` | **exclusive** | `worker.gpu_run` (`worker.py:1605`), the anchor render's GPU run. It waits for every shared holder to finish, and keeps new ones out while it runs. |
| `voice.lock` | exclusive | `worker.step_voice` (`worker.py:431`): one voice job at a time |
| `t3gpu.lock` | shared (writer) / exclusive (voice) | `store.gpu()` |
| `writer.lock` | exclusive | `writer.ask()`: one writer request at a time from t7 |

`_lock(path, shared=False)` (`store.py:44`) is the context manager used for all of them except `t3gpu.lock` and
`writer.lock`, which open their own files.

### 3.4 Project storage

| Function | Line | What it does |
|---|---|---|
| `_write(f, data)` | 54 | JSON (indent 1, UTF-8) to `<f>.tmp`, then `os.replace`: a crash never leaves half a file |
| `read(pid)` | 60 | Reads `project.json` under the project lock. `KeyError` if missing. |
| `update(pid, f)` | 68 | Under the project lock: load, `f(p)` mutates in place, set `updatedAt`, write, return the saved project. If `f` raises, nothing is written. |
| `job(pid, kind, **fields)` | 79 | Merges `fields` into `_jobs[kind]`. `state=None` removes the job. |
| `create(p)` | 117 | Id = `<slug(headline)>-<4 hex>`, makes the folder (fails if it exists), sets `createdAt`/`updatedAt`, writes |
| `all_projects(workspace=None)` | 127 | Every `project.json` (optionally one workspace), newest `createdAt` first. Reads **without** the lock and skips a file that fails to parse (mid-write). |
| `new_visuals()` | 139 | `{keywords, found, photos, uploads, maps, placed}`, all empty lists |

### 3.5 t3 GPU switch: `gpu(use)` (`store.py:97`)

A context manager. `use` is `"writer"` or `"voice"`.
1. Takes `DATA/t3gpu.lock`: **shared** for `writer` (several scripts side by side), **exclusive** for `voice` (waits
   for every running script).
2. Runs `ssh … "~/rigvideo/llm/gpu.sh <use>"` on t3 (`check=True`, timeout 900 s). That script loads the asked model
   and unloads the other.
3. Yields; releases the lock on exit.

It runs `gpu.sh` on every entry. A `CalledProcessError` or `TimeoutExpired` propagates to the caller. Callers:
`worker.step_write` (`worker.py:213`), `app.rewrite` (`app.py:613`) and the voice step.

### 3.6 Story state helpers

| Function | Line | What it does |
|---|---|---|
| `approved(q)` | 143 | Mutates: `stage = "visuals"`; VO only: `edit = {state "waiting", flow "", beats []}`; every part of the current format without a ready voice gets `{state "making", takes [], pick null}`; every part gets a `visuals` entry. The caller starts `voice` + `search`. |
| `switched(q, fmt, why, by)` | 155 | Mutates: `format`, `formatWhy {by, text, at}`, drops `render`. If that format has no parts: `stage "script"`, `_autoApprove True`, returns `"write"`. Else runs `approved(q)` and returns `"approved"`. |
| `text_share(p)` | 167 | VO only. Returns `(share of cuts whose kind is "post_or_document", [beat ids that are short])`. A beat is short if it has no cuts or its cuts sum to less than its length minus 0.25 s. The worker's `decide_type` keeps VO only when the share is at most 35% and no beat is short. |
| `in_render_window(t=None)` | 176 | Env `RIGVIDEO_RENDER_WINDOW` (default `00:00-07:00`, IST). Start inclusive, end exclusive. A window that wraps midnight (start after end) also works. |
| `final_fp(p)` | 183 | VO only. `None` unless the format is `vo_only`, `edit.state == "ready"` with beats, and every beat's voice is ready. Otherwise the first 12 hex of SHA-1 over: per beat `[sectionId, secs, [[youtubeId, start, secs, kind, (sound)] per cut]]` plus every part's `voice.pick`. A changed value means the final video is out of date. |
| `public(p)` | 198 | The project without keys starting `_`. If there is `_library` but no `final` (an older anchor video), builds `final` from it. Adds `final.stale = (final.fp != final_fp(p))`. |

### 3.7 Users, sessions, prefs

| Function | Line | What it does |
|---|---|---|
| `users()` | 212 | `DATA/users.json`, or `[]` |
| `_hash(password, salt)` | 219 | scrypt, `n=2**14, r=8, p=1`, hex |
| `check_password(email, password)` | 223 | Email trimmed and lower-cased; constant-time compare of hashes; returns the user or `None` |
| `_secret()` | 230 | `DATA/session.key`; made on first use (32 random bytes, hex, mode 600). Replacing it signs everyone out. |
| `session_token(uid)` | 239 | `uid.exp.sig`, `exp` = now + 30 days |
| `session_user(token)` | 245 | Checks signature and expiry; returns the user if the id still exists |
| `prefs(uid)` | 256 | `DATA/prefs/<uid>.json`, else defaults `{defaults: {format "anchor_vo", length 60, captions "file", aiLabel true, outro true}, hiddenPicks []}` |
| `save_prefs(uid, data)` | 263 | Writes the prefs file |
| `adduser(email, name, role, workspace, password)` | 268 | Removes any account with that email, then adds one with a **new** id `u<8 hex>`, a new salt and hash. Writes `users.json` with mode 600. Because the id is new, a password reset ends that user's old sessions, and their old prefs file is no longer used. Role and workspace are not validated. |

Command line (`store.py:279`):
- `python store.py adduser <email> <name> <role> <workspace>` reads the password from one line of stdin, prints `ok`.
- `python store.py` with no arguments runs the self-test (section 6).

---

## 4. `server/writer.py`

The script writer. It holds the prompts, the JSON schemas, the code checks, and `ask()`. It has no state of its own.
`worker._write` and `worker._write_vo` (`worker.py:228`, `:298`) drive it; `app.rewrite` uses `plan()` and `ask()`;
`app.places` uses `COMMON`. It imports `orchestrator.llm`, so `studio-app/pipeline` must be on `sys.path`.

### 4.1 Anchor formats: `plan`, `system`, `schema`

**`plan(seconds, shot, wps)`** (`writer.py:14`) returns `(apps, vos, a_words, v_words)`:
- `apps` (anchor parts) = `round((seconds + shot) / (2 * shot))`, clamped to 1–10;
- `vos` = `apps - 1`;
- `a_words` = `round(shot * wps)`: one anchor part fills one shot;
- `v_words` = `round(max(seconds - apps*shot, shot*vos) / max(vos, 1) * wps)`.

Example (the self-test): 60 s, shot `328/24 - 0.7` ≈ 12.97 s, 2.85 words/s gives 3 anchor parts and 2 VO parts, about
37 words each.

**`system(seconds, apps, vos, a_words, v_words)`** (`:23`), the anchor system prompt:
- **Format:** the fixed order ANCHOR → VO → … → ANCHOR. Anchor 1 = the most important new fact. VO = facts footage can
  show, as narration, never describing pictures. Middle anchors = numbers, statements, reactions with attribution.
  Last anchor = where things stand and the next step; no sign-off.
- **Length:** anchor `a_words` (−3/+2), VO `v_words` (±4).
- **Facts:** only what the article states; drop its commentary and dramatic phrasing; keep attributions; "at least"
  when the article says it; no repeats.
- **Style:** for the ear; present perfect; digits; no lists, parentheses, questions, opinion, first person or graphic
  detail.
- **Also return:** `headline` (≤ 90 chars), 4–6 `facts` with labels, `lt` (kicker ≤ 14 caps, headline ≤ 48 caps,
  subline ≤ 70), 5–7 `ticker` lines (≤ 90), and a footage `search` phrase per VO part (empty for anchor parts).

**`schema(n)`** (`:59`): required `headline`, `facts` (4–6 of `{label ∈ What/Where/When/Who/Numbers/Source, value}`),
`sections` (exactly `n` of `{kind ∈ anchor/vo, text, search}`), `lt {kicker, headline, subline}`, `ticker` (5–7
strings).

### 4.2 `ask()` and busy detection

| Name | Line | Value |
|---|---|---|
| `SAMPLING` | 11 | `temperature 1.0, top_p 0.95, top_k 64` (Gemma 4's recommended settings) |
| `Busy` | 72 | `RuntimeError` subclass; its message is shown to the user as is |
| `BUSY` | 76 | "The script writer's GPU is busy with other work right now. Try again in a few minutes." |
| `FIRST_TOKEN_S` | 77 | 45: socket timeout, which covers the wait for the first token |
| `MIN_TPS` | 77 | 6 streamed pieces per second |
| `CHECK_AFTER_S` | 77 | 15: the speed is judged only after this many seconds of streaming |

**`ask(system_prompt, user, json_schema, max_tokens, log=print)`** (`writer.py:80`) takes the exclusive
`DATA/writer.lock` (`DATA` = env `STUDIO_DATA`, else `~/anchor-studio/rigvideo-data`), then calls `_ask`. So every
process on t7 sends one writer request at a time. Without this, a daily run of 10 stories queued behind each other on t3
and the later requests looked like a busy GPU.

**`_ask(...)`** (`writer.py:94`):
1. Reads the pool from env `LLM_PROVIDERS`. `main` = its first entry (in production, `t3` at
   `http://100.99.155.88:8780/v1`, key `RIGVIDEO_WRITER_KEY`, model `writer`).
2. If `main` exists and its key variable is set: POST `<base_url>/chat/completions` with `model`, `max_tokens`,
   `json_schema` (llama-server enforces it), `stream: true`, `SAMPLING`, and the system and user messages.
   - Reads the SSE stream (`data: ` lines, skipping `[DONE]`) and joins the `delta.content` pieces.
   - Once streaming has run more than `CHECK_AFTER_S` and the rate is under `MIN_TPS` pieces/s: logs
     "`<n>` tok/s, GPU busy" and raises **`Busy`**.
   - A `TimeoutError` (no data within 45 s, at the start or between pieces): logs it and raises **`Busy`**.
   - Otherwise it parses the joined text as JSON and returns it.
   - Any other error (`OSError` such as connection refused or HTTP errors, `ValueError` such as bad JSON, `KeyError`,
     `IndexError`, `TypeError`): logs "failed (…); using the fallback pool" and goes to step 3.
3. **Fallback**: sets `LLM_PROVIDERS` to the pool without `main` (so t3 is not asked again), calls
   `llm.chat_json(system_prompt + "\nReturn strict JSON only.", user, temperature=0.7, max_tokens, log)`, then restores
   `LLM_PROVIDERS`. The fallback has no schema enforcement, only `response_format: json_object`.
4. If there is no pool or `main`'s key is not set, it goes straight to `llm.chat_json` with the whole pool. If
   `LLM_PROVIDERS` is not set at all, that is `llm.DEFAULT_POOL`.

So a slow or silent t3 is reported as busy and never falls back; only a down or broken t3 does.

How callers treat `Busy`: `worker.step_write` retries a story with `_autoApprove` (daily run, type switch) up to 10
times, 3 minutes apart; an editor's own story gets one try and the message (`worker.py:207-225`).

### 4.3 Anchor-format checks

| Name | Line | What it is |
|---|---|---|
| `ONES` | 136 | "zero" … "twenty" |
| `COMMON` | 137 | Capitalised words that are not names (articles, pronouns, question words, titles, "Police", "United States", …) |
| `in_text(word, art)` | 143 | True if the word, or the word minus its last 1–3 letters (stem at least 4 letters, so "Iranian" matches "Iran"), is in the lower-cased article |
| `order_ok(sections, apps, vos)` | 149 | Kinds are exactly `[anchor, vo] * vos + [anchor]` |
| `fact_notes(where, text, art, art_nums, names=True)` | 153 | Every number in `text` must be in the article's numbers (commas removed), or be 0–20 written as a word in the article. With `names`, every capitalised run not at a sentence start, minus `COMMON` words, must pass `in_text`. Returns notes like "ANCHOR 1: the number 12 is not in the article". |
| `notes(sc, article, a_words, v_words)` | 167 | Runs `fact_notes` on every section and ticker line (names checked), and on the headline and lower third (numbers only, since they are Title Case). Adds a length note when a section is outside the prompt's range widened by 4 words each side (anchor `a_words-7 … a_words+6`, VO `v_words-8 … v_words+8`); the note quotes the prompt's range. Duplicates removed. |

`worker._write` (`worker.py:228`): up to 3 tries. A wrong order or count is written again from scratch. Notes
containing "not in the article" are sent back once per try with the previous JSON. The try with the fewest such notes
is kept; any notes left are saved in `_checks`.

### 4.4 VO only: constants, prompt, schema

| Name | Line | Value |
|---|---|---|
| `VO_WPS` | 188 | 2.6 spoken words a second, breaths included |
| `VO_CPS` | 191 | 17.7 characters a second (more stable than words; measured 17.0–18.6 over 3 voices and 7 scripts) |
| `vo_words(seconds)` | 195 | `round(seconds * 2.6)` |
| `vo_seconds(texts)` | 199 | Sum over lines of `len(text) / 17.7 + 0.35` (the breath after each take, `worker.VO_GAP`) |

**`vo_system(seconds)`** (`writer.py:204`). Target `words = vo_words(seconds)`, range 92%–105%, about
`max(2, round(words/21))` beats of about 21 words, at most `max(1, seconds // 40)` background beats. The prompt:
- **The one rule:** a line is usable only if real news footage can show it; facts no camera filmed ride on a beat that
  can carry them, or are left out.
- **Beats:** `picture` is `event` (filmed at this event; a person speaking about this event counts) or `archive` (one
  specific named person, place or thing). No generic pictures (logos, documents, maps, skylines, weapons in general…).
  `shows` = 3–10 words in camera terms. `search` = 2–5 words a news video **title** would contain: the event or named
  subject plus country or well-known city; no dates, years or adjectives. `text` = 1–3 sentences, 18–32 words, one
  idea.
- **Order:** beat 1 = the core fact over the strongest event picture (archive only if nothing was filmed); numbers on
  the beat that shows what they count; limited background; last beat = where things stand.
- **Facts:** only the article's; on contradictions follow the headline and deck or attribute; at most one number per
  sentence and two per beat; no calendar dates or weekdays; at most one direct quote, only from someone likely filmed
  saying it; no graphic detail or unpublished victim names.
- **Style:** for the ear, active voice, present perfect, no abbreviations, no describing pictures.
- **Length:** fill the target from the article's showable facts; never pad; if the article truly has less, write less
  and set `supported_seconds`.
- **Also return:** `headline`, `event_search` (2–5 words naming the whole event), `supported_seconds`, `pictured_date`
  (almost always empty; a `YYYY-MM-DD` only when the news is a later count of an earlier event), `event_filmed`.

**`vo_schema()`** (`:290`): required `headline, event_search, event_filmed (bool), supported_seconds (int),
pictured_date, beats` (2–20 of `{picture ∈ event/archive, shows, search, text}`, `picture` first so the model writes to
it).

**`vo_user(title, deck, body, news_date)`** (`:312`): `"News date: <date>\n\nARTICLE\nHeadline: …\nDeck: …\n\n<body>"`.

**`vo_pictured_date(sc, article, news_date)`** (`:300`): keeps the writer's `pictured_date` only if it parses, is at
least 3 days before the news date, and its month name appears in the article. Otherwise `""` (the search uses the news
date).

### 4.5 VO only: `vo_notes(sc, article, seconds)` (`writer.py:332`)

Regex sets: `DATE_WORDS` (today, yesterday, weekdays, "November 15" / "15 November" …), `STOCK` (stock phrases such as
"stark reminder", "we see", "footage shows"), `GENERIC` (generic picture words), `SPOKEN_CAPS` (NATO, NASA, FIFA … allowed
all-caps words), `ABSTRACT` (mood words), `SAYS` (said, told, announced …). The bracketed numbers are items of the VO
script rulebook.

| Check | Note |
|---|---|
| Beat 1 not `event` | "(info) Beat 1 is archive…" [7] |
| `event_search` not 2–5 words, or has a year or date word | [23] |
| Beat over 35 words or over 3 sentences | [2,3] |
| Beat under 10 words / 10–14 words | too short / add detail [3] |
| Numbers and names not in the article | via `fact_notes` |
| More than one number in a sentence | [20] |
| A date or day word in the text | [18] |
| A `STOCK` phrase | [16,26] |
| Beat `search` not 2–5 words, or a year or date word | [23] |
| Archive beat with nothing capitalised in `shows` + `search` | [12] |
| Archive beat whose text reports someone's words and names a person shown | should be `event` [12] |
| `shows` matches `GENERIC` | [12] |
| `shows` names a person the line does not mention | "(info) … check the line is about them" [11] |
| An all-caps word of 4+ letters not in `SPOKEN_CAPS` | abbreviation [22] |
| `shows` made only of `ABSTRACT` words | not filmable [14] |
| Direct quotes (pairs of `"`) over `max(1, seconds // 30)` | [15] |
| `vo_seconds` of all beats over 110% of `seconds` | "cut to about N words" [5] |
| `vo_seconds` under 90% of `seconds` | "write about N words, about M beats" [5] |
| `pictured_date` set but not `YYYY-MM-DD` | [13] |
| "Findable" beats (`shows` not generic, and event or named) under 2 or under 2/3 of beats | "READINESS: … VO-only should not be offered" [6] |

`N` in the length notes is the word count at this script's own pace: `round(total words * seconds / spoken seconds)`.
Notes starting `(info)` or `READINESS` are for a person only; `worker._write_vo` (`worker.py:298`) sends the rest back
for a rewrite (up to 3 tries) and keeps the try closest to the target length (within 10%), then with the fewest notes.

### 4.6 Self-test

`python3 writer.py` (`writer.py:405`) asserts `plan`, `order_ok`, `notes` (an unknown day name and number are caught;
"1,144", a stemmed place name and "Seven" for 7 are accepted), `vo_notes` (each rule above with a known bad script) and
`vo_pictured_date`. It prints `ok …` and `ok vo …`. It is not run by CI.

---

## 5. `orchestrator/llm.py` and `orchestrator/common.py`

### 5.1 The provider pool (`llm.py`)

Every LLM call in RIG-Video that is not the writer's main path goes through `chat_json`: the writer's fallback
(`writer.py:128`), story selection (`select_stories.py`) and story pictures (`assets.py`).

**`DEFAULT_POOL`** (`llm.py:14`), used only when env `LLM_PROVIDERS` is not set: `cerebras` (`gpt-oss-120b`,
`CEREBRAS_API_KEY`), `groq` (`openai/gpt-oss-120b`, `GROQ_API_KEY`, `max_budget` 5000), `local` (Ollama at
`127.0.0.1:11434`, `qwen3.8:27b`, built-in key `local`), `rig` (LiteLLM gateway `100.83.67.1:4000`, `rig-quality`,
`RIG_GATEWAY_KEY`, timeout 90).

**`LLM_PROVIDERS` in production** (`rigvideo-api.service`; workers inherit it):

| Order | name | base_url | key env | model | extra |
|---|---|---|---|---|---|
| 1 | `t3` | `http://100.99.155.88:8780/v1` | `RIGVIDEO_WRITER_KEY` (from `~/.config/rigvideo/api.env`) | `writer` | `timeout` 900 |
| 2 | `groq` | `https://api.groq.com/openai/v1` | `GROQ_API_KEY` (from `~/.config/anchor-studio/*.env` via `load_env`) | `openai/gpt-oss-120b` | `max_budget` 7800 |

Provider entry fields: `name`, `base_url`, `key_env`, `model`, optional `key` (a fixed key), `timeout` (default 180 s),
`max_budget`.

| Name | Line | What it does |
|---|---|---|
| `SHORT_WAIT_S` | 28 | 30 s: a rate limit that clears within this is waited out rather than falling to slower providers |
| `LLMUnavailable` | 31 | Raised when every provider fails |
| `pool()` | 35 | One entry per key. A `key_env` may hold several comma-separated keys. Each entry gets `name#i`, `key`, and `tier` = its provider's position. Providers with no key are left out. |
| `available()` | 42 | True if any provider's `key_env` is set (a built-in key alone does not count) |
| `_extract_json(text)` | 47 | Strips a ``` fence, parses from the first `{` to the last `}` |
| `_turn` | 55 | Round-robin start among the first-tier keys |

**`chat_json(system, user, temperature=0.2, max_tokens=4000, log=print)`** (`llm.py:58`):
1. No keys: raise `LLMUnavailable("no LLM provider key configured")` at once.
2. `first` = keys of the lowest tier. Each pass tries `first` round-robin from `_turn`, then all other keys.
3. Per key: POST `/chat/completions` with `response_format: {"type": "json_object"}`, header
   `User-Agent: anchor-studio/1.0`, timeout `timeout` or 180 s. If the reply is not valid JSON (empty or cut off), it
   doubles `max_tokens` up to `max(max_tokens, max_budget or 16000)` and asks again (the bigger budget also defeats the
   gateway's request cache). Success advances `_turn` and returns.
4. HTTP errors record the provider's message. A 429 from a first-tier key with "try again in …s" records the wait.
5. If every first-tier key is rate-limited with the shortest wait ≤ 30 s (and fewer than 6 such waits so far), it stops
   before the fallbacks, sleeps that wait + 1 s, and runs the pass again without counting it.
6. Otherwise a failed pass counts. It logs "LLM: every key failed on pass N" and sleeps `15 * N` s. After 3 failed passes
   it raises `LLMUnavailable` with the last 6 errors.

### 5.2 `common.py`

Shared paths for the pipeline tools. In this chapter's files only `load_env()` is used (by `worker.py:58`,
`worker.py:1509` and `app.rewrite`).

| Name | Line | Value |
|---|---|---|
| `APP` | 7 | `studio-app/` (two levels above the file) |
| `PIPE` | 8 | `studio-app/pipeline` |
| `HOME`, `STUDIO` | 9-10 | `~`, `~/anchor-studio` |
| `COMFY`, `COMFY_IN` | 11-12 | `~/anchor-studio/repos/ComfyUI-v038` and its `input/` |
| `DAILY`, `OUTPUT` | 13-14 | `~/anchor-studio/daily`, `~/anchor-studio/output/daily` |
| `TOOLS_PY` | 15 | env `ANCHOR_TOOLS_PY`, else `~/.cache/anchor-tools/bin/python` |
| `IST` | 16 | UTC+5:30 |
| `OFF_SWITCH` | 17 | `~/anchor-studio/ANCHOR_OFF` |
| `SELECT_AT`, `GPU_AT`, `RENDER_START`, `HARD_STOP` | 21-22 | `17:30`; env `ANCHOR_GPU_AT` / `17:55`; env `ANCHOR_RENDER_START` / `18:00`; env `ANCHOR_HARD_STOP` / `23:00` |
| `REST_BETWEEN_VIDEOS_S` | 23 | 0 |
| `now()`, `today_at(hhmm, day)` | 26, 30 | IST clock; `"24:45"` means 00:45 the next day |
| `Run` | 47 | A day's run folder with a checkpointed `state.json` |

Other modules import some of these: `orchestrator/post.py` (`APP, PIPE, TOOLS_PY`), `comfy.py` (`COMFY, COMFY_IN,
STUDIO`), `assets.py` (`APP`), `tools/new_anchors/runlib.py` (`COMFY_IN, REST_BETWEEN_VIDEOS_S, STUDIO, now`),
`tools/sourcetrack/assemble_hybrid.py` (`TOOLS_PY`). `SELECT_AT`, `GPU_AT`, `RENDER_START`, `HARD_STOP`, `OFF_SWITCH`,
`DAILY`, `OUTPUT`, `today_at` and `Run` are not used by any file in this repository; RIG-Video's own schedule is the
env settings in HANDOFF section 11.

**`load_env()`** (`common.py:37`): reads every `~/.config/anchor-studio/*.env` in name order. Each `KEY=VALUE` line
(blank lines and `#` comments skipped, surrounding quotes removed) goes into `os.environ` with `setdefault`, so a value
already in the environment (for example from the systemd unit) wins. Nothing is logged. It does **not** read
`~/.config/rigvideo/api.env`; systemd loads that one into the API, and the workers inherit it.

---

## 6. Tests

The tests moved to the regression suite in `tests/` (about 250 tests and about 10 browser journeys). CI runs it on
every pull request on GitHub's runners. What each file covers, how to run it and how to add a test: **`docs/TESTING.md`**.
