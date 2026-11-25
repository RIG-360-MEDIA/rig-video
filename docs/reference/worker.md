# Reference: `server/worker.py` (the machine jobs)

> `file:line` references point at the code as of 2026-11-25; after later changes, search by the name given next to them.

> Part of the RIG-Video handoff. Read [`docs/HANDOFF.md`](../HANDOFF.md) first. This chapter assumes its sections
> **4. The life of one story**, **5. How an anchor video is rendered**, **6. How a voice-over (VO only) video is made**
> and **8. Data: where everything is stored**, and does not repeat them. It describes what `worker.py` does, line by
> line where it matters. All line numbers are `server/worker.py` unless another file is named. Times are IST.

---

## Contents

1. [What the worker is](#1-what-the-worker-is)
2. [How a job runs](#2-how-a-job-runs)
3. [Constants and environment variables](#3-constants-and-environment-variables)
4. [Locks](#4-locks)
5. [Job: write](#5-job-write)
6. [Job: voice](#6-job-voice)
7. [Job: search](#7-job-search)
8. [Job: keyword](#8-job-keyword)
9. [Job: cut](#9-job-cut)
10. [Job: check](#10-job-check)
11. [Type decision (inside check)](#11-type-decision-inside-check)
12. [Job: final](#12-job-final)
13. [Job: render](#13-job-render)
14. [Job: post](#14-job-post)
15. [Job: selection](#15-job-selection)
16. [Shared helpers](#16-shared-helpers)
17. [What each job writes](#17-what-each-job-writes)
18. [Failure modes and how they surface](#18-failure-modes-and-how-they-surface)
19. [Self-test](#19-self-test)

---

## 1. What the worker is

`worker.py` is one Python file that holds every heavy job for a story. The API (`server/app.py`) never does heavy work
itself; it starts `worker.py <job> <story id>` as a separate process and polls `project.json` for progress.

- **Interpreter:** the tools venv, `TOOLS_PY` (`~/.cache/anchor-tools/bin/python`), on t7.
- **Imports at start (lines 23–60):** `store` (project storage and locks), `orchestrator.common` (then
  `common.load_env()`, which copies every `~/.config/anchor-studio/*.env` line into `os.environ` without overwriting
  what is already set), `orchestrator.llm`, and `writer`. `studio-app/pipeline` is put on `sys.path`, so the
  orchestrator modules are imported from the installed `studio-app`.
- **PATH (line 34):** the shared ffmpeg build (`~/anchor-studio/repos/ffmpeg-shared/current/bin`) is put first, then
  `~/.local/bin`. Every `ffmpeg`/`ffprobe` the worker runs is the shared build.
- **Output:** stdout and stderr go to the story's `log.txt` (the API opens it in append mode and writes a header
  line `===== <IST timestamp> <job> <args>` before each job).

---

## 2. How a job runs

### 2.1 Command line

| Command | Started by | What it does |
|---|---|---|
| `worker.py write <id>` | `app.spawn` (new story, Write, Try again, format switch); `start_job` from `decide_type` | Script (section 5) |
| `worker.py voice <id>` | `app.spawn` (approve, revoice, save with changed text); `start_job` from `step_write`, `decide_type` | Voice takes (section 6) |
| `worker.py search <id>` | `app.spawn` (approve); `start_job` from `step_write`, `decide_type` | Footage search (section 7) |
| `worker.py keyword <id> <section id> <keyword id>` | `app.spawn_keyword` | One keyword (section 8) |
| `worker.py cut <id>` | `app.spawn_cut` (a save that placed an uncut moment) | Cut placed moments (section 9) |
| `worker.py check <id> [<section id> ...]` | `app.spawn` (Check again); `start_job` from `step_search`, `recheck_changed` | Clip checker (section 10) |
| `worker.py final <id> [again]` | `app.spawn` (Make it again, always with `again`); auto-resume (with `again`) | VO final 9:16 video (section 12) |
| `worker.py render <id>` | the job loop's render queue (`app.monitor`) | Render (section 13) |
| `worker.py post <id> youtube [upload]` | `app.queue_post` (Post, Post all, auto upload, auto post) | YouTube (section 14) |
| `worker.py selection` | the job loop, at most every 30 min until today's file exists | Daily picks (section 15) |
| `worker.py selftest` | `deploy/check.sh` (CI) | Asserts (section 19) |

### 2.2 `main()` (lines 1837–1874)

1. `selection` runs `step_selection()` directly and returns. It has **no** try/except and no job record.
2. `PID = argv[2]`.
3. `cut` runs `step_cut()` directly and returns. It also has **no** try/except and no job record ("quiet helper job";
   the clips simply appear when cut).
4. Every other job runs inside one `try`. The job's record name (`kind`) is the step name, except `keyword`, which
   records under `search`.
5. **Success:** `store.job(PID, kind, state=None)` removes `_jobs[kind]` from `project.json`. A job with no entry is
   "not running, not failed" to the site.
6. **Failure:** any exception:
   - the full traceback is printed to `log.txt` (`traceback.print_exc()`);
   - a message for the editor is chosen (table below) and written to `_jobs[kind]` as `state: "failed"`, `error` and
     `note` (cut to 400 characters);
   - then extra fields per job:

| Job | Extra failure fields |
|---|---|
| `render` | `render.state = "failed"`, `render.heldReason = msg` (300 chars); `render_state` also sets `stage = "review"` |
| `check` (VO only) | `edit.state = "failed"`, `edit.note = msg` |
| `final` | `final.state = "failed"`, `final.note = msg` |
| `post` | `posts.<platform>.state = "failed"`, `.error = msg` |
| `search` / `keyword` | every keyword in every part still `queued` or `searching` is set to `error`, so it stops spinning and "Search again" works on it |

   - The process exits with status 1.

### 2.3 What the editor sees: `Say` and `PLAIN`

| Exception | Message shown |
|---|---|
| `Say` (line 70) | its own text. `Say` is the worker's way to write an error for the editor. |
| `writer.Busy` | its own text (the writer's GPU on t3 is contended) |
| `llm.LLMUnavailable` | "The script writer is busy right now. Try again in a few minutes." |
| anything else | `PLAIN[kind]` (lines 74–80), else "Something went wrong. Try again." |

`PLAIN` per job:

| kind | Message |
|---|---|
| write | The script could not be written just now. Press Try again. |
| voice | The voices could not be made just now. Try again in a few minutes. |
| search | The footage search stopped with an error. Search the keyword again. |
| render | The render stopped with an error. Send it to render again. |
| check | The clip check stopped with an error. Press Check again. |
| final | The final video could not be made. Press Make it again. |
| post | Posting stopped with an error. Press Post again. |

The real cause is always in `log.txt` as the traceback; the site only gets the plain sentence.

### 2.4 Logging

- `log(msg)` (line 66) prints `[HH:MM:SS] msg`. The time comes from `store.now()`, which is **IST** (unlike the
  machines' system logs, which are UTC).
- `run(cmd, cwd, on_line)` (line 83) logs `RUN <command>` (first 300 chars), streams every output line into the log,
  keeps the last 15 lines, and passes each line to `on_line` (used for `PROGRESS` parsing). On a non-zero exit it raises
  `RuntimeError("<script>.py failed: <last 4 lines>")`, where `<script>` is the first `.py` argument, or the command
  name.
- `ff(*args)` (line 99) runs `ffmpeg -v error -y …` with `check=True`; its errors are not streamed, only raised.

### 2.5 Progress lines

`store.job(pid, kind, progress=…, note=…)` merges fields into `_jobs[kind]`. The site shows `note` and `progress`.
The footage search also writes per-part lines into `_jobs.search.parts[<section id>]` through `part()` (line 916);
`part(pid, sid)` with no text removes that part's line.

### 2.6 Jobs started by jobs: `start_job` (lines 1127–1138)

Same as the API's `spawn()`, without the API's in-memory process table:
- If `_jobs[job]` is `running` and its `os_pid` exists in `/proc`, it does nothing (the running one picks up the work).
- Otherwise it sets `_jobs[job] = {state: running, progress: 0, note: "Starting", error: None}`, appends the
  `=====` header to `log.txt`, starts `TOOLS_PY worker.py <job> <id> <args>` in a new session (so it outlives the
  parent), and records `os_pid`.

The API's job loop reaps both kinds the same way (HANDOFF section 12).

---

## 3. Constants and environment variables

### 3.1 Paths and hosts

| Name | Line | Value / env | Meaning |
|---|---|---|---|
| `HOME` | 26 | `store.HOME` (`Path.home()`) | |
| `STUDIO` | 27 | `~/anchor-studio` | |
| `APPDIR` | 28 | env `RIGVIDEO_APP`, default `~/anchor-studio/studio-app` | The pipeline code |
| `PIPE`, `REG` | 29 | `APPDIR/pipeline`, `APPDIR/anchor_registry` | |
| `ST_TOOLS`, `FOOT_TOOLS` | 30 | `pipeline/tools/sourcetrack`, `pipeline/tools/footage` | |
| `TOOLS_PY` | 31 | env `ANCHOR_TOOLS_PY`, default `~/.cache/anchor-tools/bin/python` | Python for the worker and render tools |
| `SV` | 32 | `~/anchor-studio/repos/social_verifier` | The footage backend checkout (`footage/` in the repo) |
| `YTDLP` | 36 | `~/anchor-studio/repos/social_verifier/ytdlp_node.sh` | yt-dlp wrapper (Node 22 + WARP), HANDOFF section 4 step 3 |
| `VHOST` | 43 | env `ANCHOR_VOICE_HOST`, default `trijya-3@100.99.155.88` | Voice box (t3) |
| `VKEY` | 44 | env `ANCHOR_VOICE_KEY`, default `~/.ssh/to_trijya3` | ssh key to t3 (also used by `store.gpu`) |
| `VROOT` | 45 | env `ANCHOR_VOICE_ROOT`, default `/home/trijya-3/anchor-studio` | Root on t3 |
| `VPY` | 46 | `VROOT/repos/chatterbox/.venv/bin/python` | Chatterbox Python on t3 |
| `VSSH` | 47 | `ssh -o BatchMode=yes -o ConnectTimeout=20 -i VKEY VHOST` | |
| `SVB` | 470 | `http://127.0.0.1:8787/api` | Footage backend API |
| `VO_PY` | 1035 | env `VO_PY`, default `~/anchor-studio/vertical/.venv/bin/python` | Python for `vo_pick.py` |
| `VO_PICK` | 1036 | `FOOT_TOOLS/vo/vo_pick.py` | The clip checker |
| `VO_CACHE` | 1037 | env `VO_CACHE`, default `~/vo_check/cache` | 480p copies the checker downloads; `edit_media` cuts previews from them |
| `ASSEMBLE` | 1326 | env `VO_ASSEMBLE`, default `~/anchor-studio/vertical/assemble916.py` | VO final builder; also imported as a module (`_a9`, line 1731) for `download`/`secs_of` |
| `CAL` | 127 | `rigvideo-data/calibration.json` | Learned pace per anchor |

Other env read by the worker: `RIGVIDEO_PUBLISH_PRIVACY` (line 1537, default `public`), and through `store`,
`STUDIO_DATA`. Through `orchestrator.publish`: `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN`,
`YT_PENDING_PLAYLIST_ID`, `YT_BULLETIN_PLAYLIST_ID`. Through `writer`: `LLM_PROVIDERS`.

### 3.2 Footage and download

| Name | Line | Value | Meaning |
|---|---|---|---|
| `MIN_CLIP_S` | 35 | 3.0 | A found moment shorter than this is stretched to 3 s (or the video's end) before cutting |
| `SOURCE_FMT` | 37 | ≤720p, H.264 (`avc1`) + m4a first, then any ≤720p | Whole-video download format for **anchor** stories |
| `SOURCE_FMT_VO` | 39 | same, ≤1080p | Whole-video download format for **VO only** stories (9:16 crops need the height; a crop may be upscaled at most 2×) |
| `SOURCE_MAX_S` | 40 | 1200 | Found videos longer than 20 min are not downloaded whole (moments are still cut on use) |
| `LIVE` | 471 | regex `LIVE`, `live stream`, `24/7` | Titles of live streams; skipped for whole downloads  |
| `STATE` | 472 | backend status → site status | `pending/queued→queued`, `searching/analyzing→searching`, `done`, `error`, `idle` |
| `VF` | 473 | `crop` (90% crop, 640×360) / `blur_fill` (blurred 16:9 with the 9:16 centre over it) | Treatment previews made in `cut()` |
| `FLAG_OF` | 476 | `clean_shots.py` reject reason → site flag | presenter, text (graphic/map), logo (website), vertical (vertical, side bars), presenter (call) |
| `BLOCKED` | 506 | `429`, `Too Many Requests`, `Sign in to confirm`, `not a bot`, `HTTP Error 403`, `blocked` | YouTube refusal patterns |
| `NOT_NAMES` | 663 | word list | Capitalised words that are never names (articles, weekdays, months, titles, institutions) |
| `VO_GAP` | 1038 | 0.35 s | A breath after each beat's voice; part of the beat's picture time |
| `VO_LIMIT` | 1061 | 10 | Videos asked per VO search line (`limit:10`); the backend's default is 5 |
| `MONTHS`, `DAYS` | 777–778 | | Date parsing for `stated_date` |

**Anchor footage is not checked on search.** `after_search` downloads each found video whole and leaves the moments for
the editor, who places them (they are cut by the `cut` job). The clip checker, `vo_pick.py` on t7 (the `check` job), picks
the VO parts' shots afterwards (`anchorEdit`). An older checker on t8 was removed on 2026-11-25.

### 3.3 Render and timing

`FPS, SHOT, CTX, LEAD, KEEP_TAIL, MAX_FIT = 24, 328, 39, 0.25, 0.45, 0.09` (line 62).

| Name | Value | Meaning |
|---|---|---|
| `FPS` | 56 | Frame rate of the anchor render |
| `SHOT` | 328 | Frames in one H3 shot |
| `CTX` | 39 | Frames of context overlap between chained shots |
| `LEAD` | 0.25 s | Silence before the voice in a part (anchor and VO parts in assembly) |
| `KEEP_TAIL` | 0.45 s | Time kept after the voice ends |
| `MAX_FIT` | 0.09 | ±9% stretch limit. Declared here; **not used** in `worker.py` (the time-fit itself is in `make_master.py`). |

`target_for(d0)` (line 346): for `d0` seconds of speech, `n = round(((LEAD + d0 + KEEP_TAIL) * 24 − 39) / (328 − 39))`
shots (at least 1), and the speech length that fills them exactly:
`(328 + (n − 1) × 289) / 24 − 0.25 − 0.45`. One shot holds 12.97 s of speech, two 25.01 s, three 37.05 s.

Other render constants:

| Name | Line | Meaning |
|---|---|---|
| `TONE` | 337 | Story tone → (Chatterbox `exaggeration`, `cfg_weight`): grave (0.6, 0.45), urgent (0.8, 0.35), serious (0.7, 0.4, also the default), measured (0.65, 0.45), brisk (0.75, 0.4) |
| `CONF` | 1554 | Footage filter for anchor assembly: 90% centre crop (drops corner logos), fill 1280×736, 24 fps, yuv420p |
| `BLUR` | 1555 | Same size, for vertical clips: blurred fill with the 9:16 centre over it |
| `PID` | 57 | The current story id (global, set in `main`) |

---

## 4. Locks

All are `fcntl.flock` file locks under `rigvideo-data/` (`store._lock`, `store.gpu`, `writer.ask`). They are released
when the process exits, so a crashed job never leaves a lock behind.

| Lock file | Mode | Taken by | Why |
|---|---|---|---|
| `projects/<id>/.lock` | exclusive, short | every `store.read` / `store.update` | Read-modify-write of `project.json` never overlaps between the API and workers |
| `search.lock` | **shared** | `step_search` (1006), `step_keyword` (1053), `step_cut` (1080), `step_check` (1363), `step_final` (1460) | Many of these can run side by side |
| `search.lock` | **exclusive** | `gpu_run` (1605), the anchor GPU run | The GPU hold stops the footage backend and other GPU users; a render waits until every search, check, cut and final has let go, and they wait for it |
| `voice.lock` | exclusive | `step_voice` (431), whole job | One voice job at a time across all stories |
| `t3gpu.lock` | shared for `writer`, exclusive for `voice` | `store.gpu("writer")` in `step_write` (213) and `step_selection` (1548); `store.gpu("voice")` in `make_takes` (408) | t3's GPU holds one model at a time. Entering runs `~/rigvideo/llm/gpu.sh writer|voice` on t3 over ssh (timeout 900 s), which loads that model and unloads the other |
| `writer.lock` | exclusive | `writer.ask` (writer.py:85) | One request to the writer from t7 at a time |

Notes:
- `step_search` sets its note to "Waiting its turn (a render is using the machine)" **before** asking for
  `search.lock`; `step_check` and `step_final` do the same ("Waiting its turn").
- `gpu_run` sets `render.note = "Waiting for a footage search to finish"` before the exclusive lock, and clears it once held.
- The VO render (`render_vo` → `step_final`) takes `search.lock` **shared**, not exclusive; it does not hold the GPU.

---

## 5. Job: write

Entry `step_write` (line 207) → `_write` (228) → `_write_vo` (298) for VO only.

### 5.1 Retry on a busy t3

- `tries = 10` if `_autoApprove` is set (daily run, type switch), else `1`.
- Each try: `with store.gpu("writer"): _write(store.read(id))`.
- On `writer.Busy`: log, set note "The script writer is busy; trying again in a few minutes", sleep 180 s. After the
  last try, `Busy` is raised and `main` shows its text.
- After a successful write with `_autoApprove`: pop `_autoApprove`, call `store.approved(q)` (stage → `visuals`, voices
  set to `making`, empty `visuals` per part, VO only: `edit = {state: waiting}`), then `start_job(voice)` and
  `start_job(search)`.

### 5.2 Reading the source (`_write`, lines 228–239)

- If `source.text` is empty and `source.url` is set: `fetch_article(url)` (line 193):
  - GET with User-Agent `Mozilla/5.0 (RIG-Video)`, 30 s timeout, first 2 MB.
  - Title from `<title>`, cut at the first ` | ` and a trailing ` — Site name` (2–40 chars).
  - Body = every `<p>` with more than 8 words.
  - Fewer than 80 words → `Say("Could not find the article text on that page. Paste the article text instead.")`.
  - Saves `source.text`; replaces `headline` with the page title only if the headline is still `""`, `"New story"`
    or the URL's slug.
- Source under 40 words → `Say("The source is too short to write from. …")`.

### 5.3 Anchor formats (`anchor_vo`, `anchor_only`)

- `shot = SHOT/FPS − LEAD − KEEP_TAIL` (12.97 s of speech per H3 shot).
- `writer.plan(targetSeconds, shot, pace(anchorId))` → the anchor and VO part counts and word budgets.
- Up to **3 attempts** of `writer.ask(system, user + feedback, writer.schema(...), max_tokens = max(4000, seconds × 40))`.
  The article is cut to 14,000 characters.
  - Sections without text are dropped. Wrong order or count (`writer.order_ok`) → try again from scratch.
  - `writer.notes(...)` lists problems; those containing "not in the article" count as fact errors. The attempt with
    the fewest fact errors is kept. Fact errors are fed back ("These are not in the article: …") for the next try.
  - No valid attempt at all → `Say("The script model did not return the sections in the right order. Try Write again.")`.
- Saved:
  - `versions.anchor_vo` = parts `a1…`/`v1…` (`{id, kind, text}`); `versions.anchor_only` = the same parts, all `kind: anchor`.
  - `facts` (≤ 6, `{label, value}`), `ticker` (≤ 7 lines; the headline if none).
  - `lt` = kicker (upper case, ≤ 14 chars), headline (upper case, ≤ 48), subline (≤ 70).
  - `headline` = the model's headline (≤ 90) unless the source is a link.
  - `_search` = the model's search line per part id; `_checks` = remaining notes.

### 5.4 VO only (`_write_vo`, lines 298–338)

- `writer.vo_system(seconds)`, `writer.vo_user(headline, "", text[:14000], story day)`, schema `writer.vo_schema()`.
- Up to **3 attempts**. Fewer than 2 beats → try again. `writer.vo_notes` lists notes; those starting `(info)` or
  `READINESS` are not "to fix". The kept attempt is the lowest `(round(off), number of notes to fix)`, where `off` is how far
  `writer.vo_seconds(texts)` is outside ±10% of the asked length. Notes are fed back as "Fix these: …".
- No attempt with 2+ beats → `Say("The script model did not return the beats. Try Write again.")`.
- Saved:
  - `versions.vo_only` = beats `b1…`: `{id, kind: "vo", text, picture (≤200, from "shows"), search (≤120), cls: "archive" | "event"}`.
  - `headline` as above.
  - `_vo = {picturedDate (writer.vo_pictured_date), eventFilmed, supportedSeconds, eventSearch (≤80)}`.
  - `_checks`.

---

## 6. Job: voice

Entry `step_voice` (line 428). Holds `voice.lock` for the whole job.

### 6.1 Loop

The job loops until no part is waiting:
1. Re-read the project. `todo` = parts whose `voice.state` is `making` or `redoing` and whose text is not empty.
2. None left → `recheck_changed(p)` (section 10.6) and return.
3. Progress = ready parts / all parts; note "Making the voice (N parts)".
4. **Seeds:** `[11, 23, 41]` for a first voicing; for a redo, three seeds from the clock (`time % 1000 + 1, 2, 3`).
5. **Settings per part:** base = `TONE[tone]`. For a `redoing` part, its `voice.note` goes through `asked()`.
   Parts with the same `(exaggeration, cfg, tempo)` are grouped into one Chatterbox run.
6. `make_takes` per group; then rank and save (6.4).
7. If a part's text changed while it was being voiced, it stays `making` and the next round voices it again.

### 6.2 `asked(note, ex, cfg, text)` (line 374): editor notes → settings

| Note contains | Effect |
|---|---|
| `slower` | tempo 0.9 (stretch the finished take, pitch kept) |
| `faster` | tempo 1.1 |
| `more serious` | exaggeration −0.2 |
| `less flat` | exaggeration +0.2, cfg −0.05 |
| `Name is Say` / `is said` / `is pronounced` / `sounds like` / `=` | every whole-word `Name` in the spoken text becomes `Say` (voice only; the script keeps `Name`) |
| `pause before the last line` | ` ... ` inserted before the last sentence |

Results are clamped: exaggeration 0.3–1.2, cfg 0.2–0.7. Matching is lower-case, except the name rule, which needs a
capitalised name.

### 6.3 `make_takes` (line 393) and the t3 layout

`spoken(text)` (line 176) is applied to every line first: numbers become words ("2026" → "twenty twenty-six",
"1905" → "nineteen oh-five", "2.5" → "two point five", thousands/millions/billions), `%` → "per cent", `&` → "and",
spaced dashes → commas.

| Where | Path |
|---|---|
| t7, config | `projects/<id>/voice/t<unix time>/config.json` |
| t7, takes | `projects/<id>/voice/t<unix time>/takes/` (`takes.json` + wavs) |
| t3, anchor reference audio | `VROOT/studio/refs/<voice file name>` (copied from `anchor_registry/<voice_file>` each run) |
| t3, run folder | `VROOT/studio/<id>/t<unix time>/config.json`, `…/takes/` |
| t3, script | `VROOT/voice_lab/chatterbox_takes.py`, run with `VPY` |

Steps:
1. `config.json` = `{anchor, ckpt_dir: VROOT/models/chatterbox, ref_audio, exaggeration: [ex], cfg_weight: [cfg], seeds, scripts: {part: spoken text}}`.
2. `ssh mkdir -p`, `scp` the reference audio and config.
3. Inside `store.gpu("voice")` (unloads the writer): `cd VROOT/voice_lab && VPY chatterbox_takes.py <config> <takes dir>`.
4. If tempo ≠ 1.0: on t3, every wav is re-encoded in place with `ffmpeg -af rubberband=tempo=<t> -c:a pcm_f32le`
   (`$HOME/.local/bin` ffmpeg on t3, which has Rubber Band). In place, because renders later use the remote file.
5. `scp -r` the takes folder back. Returns `{part: [wav, …]}` and the remote takes folder.

### 6.4 Scoring and saving

`score(kind, wav, text)` (line 420) gives the sort key:
1. word error rate above 0.05 sorts last (`wer`: faster-whisper `small.en`, CPU, int8, loaded once per process;
   `difflib` ratio of normalised words, both sides passed through `spoken()`);
2. for anchor parts only: `|speech seconds / target_for(speech) − 1|` (closest to filling whole shots);
3. the word error rate itself.

`speech_seconds` (line 351) is the time between the first and last sample louder than −45 dBFS.

Saved per part (only parts still in the project with a `voice` field):
- `voice.takes` = the new takes, best first (`{id: "<t…>-<stem>", src: /files/…, seconds}`); for a `redoing` part they
  are **appended** to the old takes.
- `voice.pick` = the best new take.
- `voice.state = "ready"` only if the text did not change meanwhile.
- `_takes[<take id>] = {file: <local wav>, remote: <t3 wav>, text: <script text>}`. The render uses `remote`
  (section 13.1), assembly uses `file`.

### 6.5 Pace learning

Only for a group run with the base settings and tempo 1.0: `learn_pace(anchor, [(spoken words, speech seconds)])`
(line 143). Samples under 2 s are dropped; the last 40 samples are kept; `wps = sum(words) / sum(seconds)`, written to
`calibration.json`. `pace(anchor)` (line 136) reads it back, else the registry's `voice_wps`, else 2.85. The anchor
writer uses it (section 5.3).

---

## 7. Job: search

Entry `step_search` (line 1003). Note "Waiting its turn …", then holds **`search.lock` shared** and a one-thread
executor named `checks`.

### 7.1 Footage backend client

- `sv_up()` (486): GET `/api/health` (3 s); any HTTP error code also counts as "up".
- `sv_client()` (495): if not up, starts `bash studio-app/pipeline/tools/footage/start_backend.sh` in its own session,
  output appended to `rigvideo-data/footage_backend.log`, and waits up to 180 s (60 × 3 s); then
  `Say("The footage search service did not start.")`. Logs in with the backend's own single account (imported from
  `social_verifier/backend/app/core/auth.py`) and returns an `httpx` client with the bearer token, 120 s timeout.
- `start_backend.sh` (not part of the worker): kills any old backend on :8787, exports Groq keys from `llm.env`,
  starts the PO-token server on :4416 if needed, sources `footage.env`, points the backend's LLM at t8:11610 unless
  `FOOTAGE_LLM=groq`, sets `FOOTAGE_VIDEOS_PER_KEYWORD=4`, `FOOTAGE_KEYWORDS_PER_WAVE=3`, and starts uvicorn on
  127.0.0.1:8787.
- `poll(c, project, done, on, every=8, most=3600)` (577): polls `GET /footage/projects/<id>`. While the backend is
  restarting (no `segments` in the answer) it waits. Every answer goes through `blocked_check`, then `on(svp)`, then
  `done(svp)`. An hour with **no progress** (keyword states, videos judged, clip states all unchanged) → `Say("The footage search made no progress for an hour and was stopped.")`. A slow search that keeps moving is waited for.
- `blocked_check` (515): any keyword or clip error matching `BLOCKED` writes `rigvideo-data/youtube_blocked`
  (`<IST stamp> <error>`) and raises `Say("YouTube is refusing our searches right now (rate limit). Try again later; nothing was lost.")`.

### 7.2 Mapping results onto the site (`map_found`, `save_visuals`)

`map_found(svp, old)` (528):
- Keywords → `{id (first 8 chars of the backend id), text, reason, state, progress, _sv}`.
- Videos: only analysed ones with relevance ≥ 10, best first, one per YouTube id, skipping ids in the part's `wrongPlace`.
- Each found video keeps from the old site entry: its `id`, `flags`, `source`, and moments that were cut, checked or
  custom (a new backend moment within 0.5 s of an unchecked old one is replaced by the old one, keeping its clip).
- An uncut moment's poster is YouTube's own `mq1/mq2/mq3.jpg` by position in the video (`posterNear: true`).

`save_visuals(pid, sid, kws, found)` (566) writes `visuals[sid].keywords` (minus those in `_removedKeywords[sid]`) and
`visuals[sid].found` (only videos of kept keywords), and records `_svk[site keyword id] = backend keyword id`.

### 7.3 VO only path: `search_vo` (line 1168)

Then `start_job(check)` and return (the check waits for the voices).

- `when = vo_date(p)` = `_vo.picturedDate`, else the story's day. `after = when − 3 days`.
- `place = _place` (set by the API when the project is made). `ev = _vo.eventSearch`, else `event_query(headline)`.
- `first` = the first beat that is not `archive`.
- `todo` = beats with no `found` videos (never searched, or found nothing).
- Per beat: one backend project (mode `script`, title `<headline[:60]> <beat id>`), reused from `_svp[beat]` on a
  retry. The brief: `"<place>: <headline>. Event of <date>. Wanted on screen: <picture>, filmed at this event. Not
  wanted: maps, graphics, a presenter in a studio, footage of other incidents."` For archive beats: "Archive footage
  from any date is right for this part" and no date. Then `SEGMENT 1 — <beat text>`.
- **Search lines** (`dated`, line 1179): the beat's `search` (else its first 60 chars of text), plus on the first event
  beat the event line. Each gets ` after:<date>` (event beats only) and ` limit:10`.
- **Query syntax** (parsed by the backend, `footage/backend/app/footage/search.py:15-16`): `after:YYYY-MM-DD` is removed
  from the text and used as YouTube's `publishedAfter`; `limit:N` (1–25) sets how many videos the line asks for.
- **No suggested keywords** on the VO path (YouTube quota).
- `add()` (1194): queues lines not already on the project and starts a batch for new lines and lines in `error` (a
  restart cut them off).
- `wait()` (1207): polls every 15 s until those keywords are `done`/`error`, saving visuals as videos arrive.
- **Retry** (1230): an event beat with fewer than 2 videos gets `retry_lines(search, headline + event line + place,
  every found title in the story)`:
  - "rare" words = capitalised words not found in the headline/event/place text;
  - line 1: each rare word replaced by `respell(word, titles)` (difflib closest title word of 4+ letters, cutoff 0.8,
    only when it differs), e.g. "Hmielek" → "Chmielek";
  - line 2: the line without the rare words;
  - only lines that differ from the original and have 2+ words, and only if there was a rare word.
  - Note "Searching again without the rare name"; the new lines are dated and limited like the first.
- A beat whose backend project could not read the script (no segments) is logged and skipped.

### 7.4 Anchor path (`anchor_vo`, `anchor_only`)

- Parts to search: the `vo` parts; for `anchor_only` (no `vo` parts) every part. Parts that already have keywords are
  skipped.
- **Cut-off searches first** (1020): any part with a keyword still `queued`/`searching` is resumed with
  `search_section(…, resume=True)`, which waits for those backend keywords and takes what they found.
- Then per part, in order: note "Searching footage for part i of n", `search_section(c, p, s, checks=checks)`, then
  the pictures (7.6).
- At the end: progress 0.9, note "Cutting the clips", and waits for every
  queued `after_search`. An exception in one of them fails the search job.
- For `anchor_vo` only: `start_job(check)` (the clip checker then picks the VO parts' shots into `anchorEdit`).

`search_section(c, p, s, extra, resume, checks)` (line 712):
- `place = lt.kicker`, `event = event_query(headline)`, `when = event_date(p)` (7.5), `after = when − 3 days`.
- Backend project per part (`_svp[sid]`), brief: `"<place>: <event>. Event of <date>. Wanted on screen: footage filmed
  at this event, or of <place> and the people and forces it names. Not wanted: maps, graphics, studio, footage of other
  incidents."` + `SEGMENT 1 — <text>`. Waits until the backend has read it; no segments → `Say("The footage search could not read part <sid>.")`.
- Our lines: the writer's `_search[sid]` (else `"<place> <event> <year>"`) and `"<event> <year>"`, each with
  ` after:<date>` (no `limit:`). With `extra` (the keyword job) only `extra`, undated.
- Plus the backend's **first 2 suggested keywords** that are `idle`/`pending` and carry no year other than this year
  (not with `extra`).
- Starts one batch, then `finish_section`.

`finish_section` (857): polls every 15 s until the run's keywords end (saving visuals as they come), asks the backend
for its `edit-plan` and waits while it is `building`, saves visuals, then runs `after_search` either now or queued on
the `checks` executor (part line "Waiting to cut the clips").

`after_search`: for each found video that has no `source` yet, is not `LIVE`, and is
0–1200 s long, `download_source` with 3 threads (part line "Downloading the videos: k of n"). A failed download is
logged; that video's moments are still cut on use.

`download_source` (901): `YTDLP -f SOURCE_FMT(_VO) --merge-output-format mp4` into
`media/source/<yt id>.dl.mp4` (15 min timeout), then `ffmpeg -c copy -movflags +faststart` to
`media/source/<yt id>.mp4` (so the browser can seek), and sets `found.source` to its `/files/` URL. Once per story.

### 7.5 Event date (`event_date`, line 815)

Used for anchor searches. Cached in `_eventDate = {date, from}`.
1. `until` = the story's day; or the source page's own published date (`page_date`: JSON-LD/meta/`<time>`) if earlier.
2. Google News RSS is searched for `event_query(headline)` and `"<lt.kicker> <lt.headline>"`.
3. `stated_date` parses the `When` fact ("November 9", "9 Nov 2026", "2026-11-09", a weekday). If it is within 30
   days before `until` and two matching reports fall on that day or the next (`first_reported(…, back=1)`), it is used.
4. Else `first_reported(queries, news, until)`: the earliest day in the 3 days up to `until` that has at least 2
   matching reports on that day or the next. "Matching" (`matches`) = at least 2 of every 5 word stems of a query
   appear in the title.
5. Else `until`. The result and how it was found are logged.

`event_query(headline)` (751): the longest piece between `:`, `|`, `;`, dashes; cut before "amid/as/after/while/following"; first 9 words.

### 7.6 Story pictures (anchor path)

- `story_photos` (688), once per story (a failure is not retried per part): query = `event_query(headline) + kicker`;
  names = `story_names` over all part texts; the source URL if any. Calls
  `orchestrator.assets.story_pictures(query, media/photos/pool, names, urls)`: Tavily news images, photos on the
  source page and Tavily's articles (with captions), SerpAPI Google Images, Wikimedia Commons; kept only when the
  caption or page title names the story; then the wall-photo filters (`fetch`, up to 24).
- `story_names` (676): capitalised words (3+ letters) or acronyms (2+) that do not start a sentence and are not in
  `NOT_NAMES`, plus the kicker in title case.
- `photos_for` (697): per part, the pool sorted by how many of the part's own names the caption has, 6 at most, each
  re-encoded to ≤1920 px wide as `media/photos/<sid>/<sid>_<k>.jpg`. Saved to `visuals[sid].photos`
  (`{id, src, caption ≤140, credit: "", source: host}`).
- Any picture error is logged and the part gets no photos; footage goes on.

### 7.7 `cut()` (line 599): moments → clips (anchor path)

Called by the `cut` job. For `[(found video, moment index)]`:
1. Moments shorter than `MIN_CLIP_S` are lengthened.
2. Videos without a local `media/source/<id>.mp4` are cut by the backend: POST `/clips`, poll until none is
   `queued`/`downloading`.
3. Per moment, into `footage/<sid>/clips/<sid>_<yt>_<i>.mp4`: a frame-accurate re-encode from the local source
   (x264 CRF 18, AAC 160k), or the backend's clip file. Failure → `cutFailed: true` on the moment.
4. Web copy `media/clips/<sid>_<yt>_<i>.mp4` (360p, 25 fps, CRF 28) and a still `.jpg`; failure → `cutFailed`.
5. `clips.json` written, then `clean_shots.py <footage/<sid>> <footage/<sid>/clean>` (SigLIP-2 labels per shot:
   presenter, graphic, map, vertical, call, website; RapidOCR text; side bars). If it fails, the shot check is
   skipped and logged.
6. Rejected reasons become `flags` via `FLAG_OF`. Treatment = `blur_fill` if `vertical`, else `crop`; a preview
   `media/treated/<sid>_<n>_<kind>.mp4` is made with `VF`.
7. `_clipfiles[<clip URL>] = <full-quality clip path>` (assembly uses it).


---

## 8. Job: keyword

`step_keyword(p, sid, kid)` (line 1050). Holds `search.lock` shared. Records under `_jobs.search`.

- Part or keyword gone → return.
- **Search again** (the keyword has a backend project and id in `_svp`/`_svk`): re-run that backend keyword in a new
  batch, poll every 15 s, save visuals, run `after_search` inline, save again.
- **New keyword** (no backend id yet): remove the site's placeholder keyword, then
  `search_section(c, p, s, extra=[text])` — the text as typed (no `after:`), no suggestions, `after_search` inline.

On success `main` removes `_jobs.search` (this happens whether or not a full search job is also listed there).

---

## 9. Job: cut

`step_cut(p)` (line 1076). Holds `search.lock` shared. No job record; errors only go to `log.txt`.

Up to 3 rounds (moments placed while cutting are picked up in the next round):
- For every placed `moment` in every part, find the found video that owns it (own part first, then any part, since
  anchor parts may place other parts' footage). Moments without `clip` and without `cutFailed` are queued **under the
  part whose search found them**.
- Per owning part: `cut(c, pid, sid, <backend project>, moments)`, then copy each moment's new fields and the video's
  flags back into `project.json`.
- Nothing left → return.

---

## 10. Job: check

`step_check(p, only)` (line 1344). `only` = beat ids from the command line ("Check again" on one beat, or
`recheck_changed`).

### 10.1 Which format

- **VO only:** writes `edit`, works in `projects/<id>/check/`.
- **Anchor + VO:** writes `anchorEdit`, works in `projects/<id>/check_anchor/`, and does **not** touch `edit`
  (`edit_state` becomes a no-op for this job). Only the `vo` parts are beats.

### 10.2 Order of work

1. `edit.state = checking`, note "Waiting for the voices"; with `only`, `_jobs.check.parts[beat] = "Checking again"`.
2. Wait up to **30 min** (10 s steps) until every part's voice is `ready`, or the voice job has failed. After 30 min it
   goes on anyway.
3. Note "Waiting its turn (a render or a footage search is using the machine)"; take **`search.lock` shared**.
4. Build the input (`check_input`), write `inputs.json`. No videos at all is logged ("the checker uses its own pictures").
5. Delete `<out>/<id>/edit.json` (a failed run must not reuse the last edit).
6. `run([VO_PY, VO_PICK, <out>/inputs.json, <out>])`. Lines `PROGRESS beat k/n` set progress `0.1 + 0.8 × (k−1)/n`
   and note "Choosing shots for beat k of n".
7. Lock released. No `edit.json` → `Say("The shot check could not finish (the vision model did not answer). Try the check again.")`.
8. `edit_from(...)` → saved as `edit` (VO only, keeping other beats when `only` is set) or `anchorEdit` (anchor + VO,
   built with no old edit).
9. VO only: `decide_type` (section 11).
10. Log: number of cuts, beats, and beats with notes.

### 10.3 `check_input(p, secs)` (line 1261)

One story object:
`{sid: <story id>, headline, date: vo_date, place: _place, beats: [...], videos: [...]}`.

- **beats:** `{id, text, picture, cls, dated: cls == event, secs: beat_secs, words: take_words}`.
  - `beat_secs` (1240): the picked take's seconds + `VO_GAP` when the voice is ready; else `max(3, words / writer.VO_WPS)` (2.6 words/s).
  - `take_words` (1247): faster-whisper word timestamps of the picked local take (`{w, start, end}`), or `[]`.
- **videos:** every found video, pooled by YouTube id, with the beats that found it and their moments (custom moments
  excluded). VO only pools the story's own parts; anchor + VO pools **every** entry in `visuals`, including searches
  the story ran while it was VO only.

### 10.4 `edit_from(p, res, only)` (line 1303)

`vo_pick.py`'s `edit.json` → the site's `StoryEdit` (`web/src/data/types.ts`):
- Per beat: `{sectionId, secs, cuts, candidates, notes (fill), why}`.
- Per cut: `{id: <beat>-<shot>-<k>, shot, at, secs, src, kind, fit, shows, sound?, poster, clip?, fill?, swapped?, review?, repeat?}`.
- `src` (`src_of`, 1296): a video `{kind: video, youtubeId, title, start, end, shotEnd, focus?}` or a picture
  `{kind: picture, url, page, title}`.
- Candidates are kept only if `fit` is exact/subject/topic and `kind` is not presenter, studio, promo, text_card, map
  or chart; each gets a ≤4 s preview.
- With `only`, beats outside `only` keep their old entry (including the editor's changes).
- `at` is recomputed over the whole story at the end.
- Result: `{state: "ready", flow, beats}`.

`edit_media` (1278) makes the previews from `VO_CACHE/<yt>.mp4`: a 360p still at the cut's middle and a 360p clip
`media/edit/<yt>_<start>_<secs>.mp4` (not remade if present). Own pictures become `media/edit/own_<hash>.jpg`.

### 10.5 Writes

`check/inputs.json`, `check/<id>/edit.json` (and the checker's other files there), `media/edit/*`, and `edit` or
`anchorEdit` in `project.json`.

### 10.6 `recheck_changed(p)` (line 1397)

Called at the end of every voice job. VO only, edit ready: beats whose `beat_secs` now differs from the edit's
`secs` by more than 0.5 s are checked again (`start_job(check, *beats)`). The final video's rebuild on a changed pick
follows from `store.final_fp` (section 12).

---

## 11. Type decision (inside check)

`decide_type(p)` (line 1415). Only for daily-run stories (`_daily`) and only once (`formatWhy.decided`).

- `store.text_share(p)` → (share of cuts whose `kind` is `post_or_document`, beats with no cuts or cuts shorter than
  the beat by more than 0.25 s).
- **Keep VO only** if share ≤ 0.35 and no beat is short: `formatWhy.text = "Daily run: N% of the shots are text: no anchor."`, `decided = true`.
- **Else** `store.switched(q, "anchor_vo", why, "auto")`: format → `anchor_vo`, `formatWhy = {by: auto, text, at}`,
  `render` removed. If there is no `anchor_vo` script yet: `stage = script`, `_autoApprove = true`, and
  `start_job(write)`. Otherwise `store.approved(q)` and `start_job(voice)` + `start_job(search)`.

---

## 12. Job: final

`step_final(p, again)` (line 1442). VO only. Also called by `render_vo` (section 13.6).

- `again`: `final.fp` is cleared, and every `final916/v_*.how.json` with `full: false` (a cut that came from the
  480p copy) is deleted, so those cuts are downloaded again.
- Up to **10 rounds**:
  1. `fp = store.final_fp(p)`: a hash of every cut (YouTube id, start, secs, kind, sound) and every picked voice.
     `None` while the edit is not ready or a voice is not ready.
  2. `fp` is `None`, or equals `final.fp` with `final.state == ready` → return (nothing to do).
  3. `final.state = building`, note "Waiting its turn"; take **`search.lock` shared**.
  4. Copy the project as it is now to `final916/project.json`; delete the old `final916/final_916.mp4`.
  5. `run([TOOLS_PY, ASSEMBLE, <project dir>, final916, final916/project.json])`. `PROGRESS k/n` → progress
     `0.05 + 0.85 × (k−1)/n`, note "Framing shot k of n−3"; `STAGE <text>` → that text as note. If the project has a
     `render` block, `render.percent` follows too.
  6. Copy to `media/final_916.mp4`, poster `media/final_916.jpg` (frame at 1 s, 540 px).
  7. Read `final916/build.json` (`cuts`: per cut `beat, shows, prompt, secs, loud, pre, post, how, full, check`).
  8. `final = {state: ready, fp, progress: 1, builtAt, seconds (ffprobe), video: …?v=<fp>, poster: …?v=<fp>, cuts,
     low: cuts with full=false, whole: cuts whose how starts with "whole"}`.
  9. Loop: an edit saved during the build gives a new `fp`, so the next round builds again.

---

## 13. Job: render

`step_render(p)` (line 1819). VO only → `render_vo` (13.6). Anchor formats:

1. `render.state = rendering`, `percent = 1`.
2. `prepare_render` (13.1).
3. `gpu_run` for every anchor part (13.2).
4. `lipsync` per appearance (13.3). Any failure → `render.state = held`,
   `heldReason = "Lips out of step in appearance <a> (<last line>). Check it, then render again."`, `stage = review`. Stop.
5. `render.state = assembling`, `percent = 92`; `step_assemble` (13.4).

### 13.1 `prepare_render` (line 1563): appearance masters on t3

| Where | Path |
|---|---|
| t7 | `projects/<id>/render-in/script.json` = `{scripts: {a1: spoken text of the picked take, …}}` |
| t3 | `VROOT/studio/<id>/script.json` |
| t3 | `VROOT/studio/bin/make_appearances.py`, `make_master.py` (copied every render) |
| t3 | `VROOT/studio/<id>/render/` (deleted and remade every render) |
| t7 | `projects/<id>/render/` (deleted and replaced by a copy of t3's every render) |

Command on t3: `cd VROOT/voice_lab && VPY VROOT/studio/bin/make_appearances.py <remote render> <anchor id> <script.json> a1=<remote take> a2=…`
(with t3's `~/.local/bin` ffmpeg on PATH). The takes used are each part's picked `_takes[...].remote`.

Then per anchor part `d = render/<a>`: `build_st.py d/story.json d d --turbo-seed`, and `d/run.txt = story.run + "_st"`.

### 13.2 `gpu_run` / `_gpu_run` (lines 1595–1627)

- Every `.png/.jpg/.wav/.mp4` input named in the part's workflow JSONs (except `render_*` per-run files) must exist in
  `~/anchor-studio/repos/ComfyUI-v038/input/`. Missing → log the list and
  `Say("This anchor's pictures are missing on the render machine. Tell the studio team.")`.
- `render.note = "Waiting for a footage search to finish"`; take **`search.lock` exclusive**; clear the note.
- `run_multi.py render/ a1 a2 …` (HANDOFF section 5 step 3). Output streamed to the log.
- **Estimate:** `9.8 + 8.0 × (shots − 1)` minutes per appearance (from `shots.json`). Each output line sets
  `percent = min(90, 90 × elapsed / estimate)` and `etaIso = now + max(1, estimate − elapsed) + 3 min`.
- Non-zero exit → `RuntimeError("Render failed: <last 3 lines>")` (the site shows `PLAIN.render`).
- Per part: `render/<a>/<run>.mp4`, else `<run>_seed.mp4`, copied to `render/<a>.mp4`.

### 13.3 `lipsync(rd, a)` (line 1630)

`lipsync_check.py render/<a>.mp4 render/<a>/master_seed.wav`, 10 min timeout. Passes when the reported
`best lag` is within ±2 frames, when no lag is printed, or on timeout ("not measured").

### 13.4 `step_assemble` (line 1737)

Works in `render/assembly/`. Reads `render/appearances.json`.

**What each VO part plays** (`shown`), first non-empty of:
1. the editor's placed items for that part (`placed_items`);
2. the clip checker's cuts for that part from `anchorEdit` (`auto_items`);
3. every placed item in the whole story.

**VO parts:**
- Voice wav `<sid>_voice.wav`: leading silence removed, `LEAD` delay, padded/trimmed to `LEAD + speech + KEEP_TAIL`,
  70 Hz high-pass, `loudnorm I=-16:TP=-1.5:LRA=11`, 48 kHz mono.
- Nothing to show → `Say("Part <sid> has no pictures. Place footage or pictures for it first.")`.
- Pictures: `montage(items, length, <sid>_pics.mp4)`.

**Anchor parts (the wall):**
- Length `need = keep_frames / 24 + 0.5`.
- Source, first non-empty of: the editor's own placed items for that anchor part; `wall_item(wall_shot(...))`;
  every placed item in the story.
- `wall_shot(secs, i, shown)` (1723): the **last** shot of the nearest VO part before it; for the opening anchor, the
  **first** shot of the nearest VO part after it; `None` with no footage.
- `wall_item` (1711): a checker cut is downloaded again from its start for the wall's length; a placed clip plays on to
  its file's end (Ken Burns stills keep their length).
- `montage` to `<sid>_wall.mp4`; the EDL entry is `{wall: [path, 0]}`, or `{}` when there is nothing.

**EDL** `assembly/edl.json`:
`{meta: {anchor_name, lt_headline, location: lt.kicker, kicker: "WORLD NEWS", subline, outro: extras.outro (default true)}, ticker, beats}`.
The rendered `<a>.mp4`, each `render/<a>/` folder and `appearances.json` are copied in. Then
`assemble_story.py assembly "<part ids in order>"`.

**Done:** `media/final.mp4`, `media/poster.jpg` (frame at 3 s, 960 px), duration by ffprobe.
`project.json`: `stage = done`, `videoId = lib-<id>`, `_library = {id, projectId, headline, anchorId, madeAt, seconds, video, poster, origin: studio}`,
`final = {state: ready, video, poster, seconds, builtAt}`, `render = {state: done, percent: 100, etaIso: None, queuePosition: 0, heldReason: None}`.

### 13.5 Montage helpers

- `montage(items, seconds, out)` (1645): items `(path, in, out, filter)` back to back, looped if short, items of
  ≤ 0.05 s dropped; one ffmpeg concat at 24 fps, x264 CRF 16, no sound, exactly `seconds` long.
- `placed_items(p, sid, work)` (1660): placed moments use `_clipfiles[clip]` with `CONF` (or `BLUR` when the editor
  chose the blur treatment); uploaded videos use their file with `CONF`; photos, maps and uploaded stills become
  `assets.ken_burns` push-ins `<sid>_<item>_kb.mp4`. Moments without a clip are skipped.
- `auto_items(p, beat, work)` (1690): picture cuts become Ken Burns of the cut's poster; video cuts are downloaded by
  `assemble916.download` (up to 1080p with spare seconds; the checker's 480p copy if YouTube refuses) to
  `raw_<yt>_<start>_<secs>.mp4`, trimmed with `CONF`.

### 13.6 `render_vo` (line 1801)

`render.state = rendering`, then `step_final(p)`. If `final.state` is not `ready` afterwards →
`Say(final.note or "The final video could not be made.")`. Else `stage = done`, `videoId`, `_library`, and
`render = done` as in 13.4.

---

## 14. Job: post

`step_post(p, platform, upload_only)` (line 1497).

Checks first:
- platform ≠ `youtube` → `Say("Only YouTube is connected so far.")`.
- `store.public(p).final` not `ready` or `stale` → `Say("The final video changed. Wait until it is made again, then post.")`.
- Any of `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN`, `YT_PENDING_PLAYLIST_ID`, `YT_BULLETIN_PLAYLIST_ID`
  missing → `Say("YouTube is not connected on this machine yet. Tell the studio team.")`.

Video: `media/final_916.mp4` for VO only, else `media/final.mp4`. `publish._token()` refreshes the OAuth token.

1. **Upload** (only if `posts.youtube.videoId` is empty): `publish.upload` (resumable, category 25 News & Politics,
   `unlisted`, `containsSyntheticMedia: true`), tags "Democracy News Live", "news", "world news" (+ "Shorts" for VO
   only). Then immediately saves `videoId`, `url` (`/shorts/<id>` or `/watch?v=<id>`), `fp` and `sent = [title, description]`.
   A retry never uploads twice.
2. **Awaiting approval** (only if not `queued`): `publish.add_to_playlist(videoId)` into `YT_PENDING_PLAYLIST_ID`;
   saves `queued = true`, `uploadedAt`.
3. `upload_only` → `state = awaiting`, `error = None`; stop.
4. If the title or description changed since `sent`: `publish.set_text`, then `sent` updated.
5. `publish.approve(videoId, token, RIGVIDEO_PUBLISH_PRIVACY)`: into the Bulletin playlist if not there, privacy set,
   removed from Awaiting approval. Each step is skipped when already done.
6. `state = posted`, `postedAt`, `error = None`.

---

## 15. Job: selection

`step_selection()` (line 1544). Output `rigvideo-data/selection/<IST date>.json`.
Inside `store.gpu("writer")` (loads the writer on t3): `select_stories.select("db", log=log)`, then the result is
written (JSON, `default=str`). Any exception ends the process with a traceback in `selection/log.txt`; no file is
written, so the job loop tries again after 30 min. What `select` does is in HANDOFF section 4, step 0.

---

## 16. Shared helpers

| Function | Line | What |
|---|---|---|
| `media(pid, rel)` | 108 | Absolute path in the project folder, parent dirs made |
| `url(pid, f)` | 115 | `/files/<pid>/<relative path>` (how the site loads it) |
| `registry()` | 119 | `anchor_registry/registry.json` anchors by id |
| `sections(p)`, `find(p, sid)` | 123, 127 | The current format's parts; one part by id |
| `vcp(*a)` | 103 | `scp -q -r` with the t3 key; last argument is the destination |
| `part(pid, sid, text)` | 916 | Per-part status line under `_jobs.search.parts` (only while a search job entry exists) |
| `source_file(pid, yt)` | 897 | `media/source/<yt>.mp4` |
| `take_of(p, s)` | 1559 | `_takes[<picked take id>]` |
| `render_state(pid, **kw)` | 1587 | Merge into `render`; `failed`/`held` also set `stage = review` |
| `edit_state`, `final_state` | 1340, 1438 | Merge into `edit` / `final` (creating them if missing) |

---

## 17. What each job writes

| Job | `project.json` | On disk (under `projects/<id>/` unless noted) |
|---|---|---|
| write | `source.text`, `headline`, `versions.*`, `facts`, `ticker`, `lt`, `_search`, `_checks`, `_vo`; on auto-approve `stage`, `edit`, voice states, `visuals` | — |
| voice | `voice.{takes, pick, state}` per part, `_takes` | `voice/t<time>/…`; t3 `VROOT/studio/<id>/t<time>/`; `rigvideo-data/calibration.json` |
| search | `_svp`, `_svk`, `visuals[*].{keywords, found, photos}`, `_eventDate` (anchor), `_jobs.search.parts` | `media/source/*.mp4`, `media/photos/…`; `rigvideo-data/youtube_blocked`, `footage_backend.log` |
| keyword | same as search, for one part | same |
| cut | moments' `clip`, `poster`, `posterNear`, `flags`, `treat`, `cutFailed`; videos' `flags`; `_clipfiles` | `footage/<sid>/clips/`, `footage/<sid>/clean/`, `media/clips/`, `media/treated/` |
| check | `edit` (VO only) or `anchorEdit` (anchor + VO); via `decide_type`: `formatWhy`, `format`, `stage`, `_autoApprove`, `render` removed | `check/` or `check_anchor/` (`inputs.json`, `<id>/edit.json`), `media/edit/*` |
| final | `final` | `final916/` (`project.json`, `v_*`, `build.json`, `final_916.mp4`), `media/final_916.{mp4,jpg}` |
| render (anchor) | `render`, `stage`, `videoId`, `_library`, `final` | `render-in/script.json`, `render/` (appearances, ComfyUI outputs, `assembly/`), `media/final.mp4`, `media/poster.jpg`; t3 `VROOT/studio/<id>/render/` |
| render (VO) | as final, plus `render`, `stage`, `videoId`, `_library` | as final |
| post | `posts.youtube.{videoId, url, fp, sent, queued, uploadedAt, state, postedAt, error}` | — |
| selection | — | `rigvideo-data/selection/<date>.json` |
| every job | `_jobs[kind]` while running/failed | `log.txt` |

---

## 18. Failure modes and how they surface

| Failure | Where | What the site shows | Where to look |
|---|---|---|---|
| Article page unreadable / under 80 words | `fetch_article` | "Could not find the article text on that page. …" | log |
| Source under 40 words | `_write` | "The source is too short to write from. …" | |
| t3 writer slow/contended | `writer.ask` → `Busy` | Busy text; daily stories retry 10 × 3 min first | log "writer busy" |
| Writer down and pool exhausted | `llm.LLMUnavailable` | "The script writer is busy right now. …" | log |
| Model never returns valid sections/beats | `_write`, `_write_vo` | "…did not return the sections in the right order…" / "…did not return the beats…" | log "write attempt" |
| ssh/scp to t3 fails, Chatterbox crashes, `gpu.sh` fails | `make_takes`, `store.gpu` | `PLAIN.voice` | traceback in log |
| Footage backend won't start | `sv_client` | "The footage search service did not start." | `rigvideo-data/footage_backend.log` |
| YouTube refusing (429, bot check, 403) | `blocked_check` | "YouTube is refusing our searches right now…"; running keywords → error | `rigvideo-data/youtube_blocked` |
| Search makes no progress for 1 hour | `poll` | "The footage search made no progress for an hour and was stopped." | Retry resumes the same footage projects |
| Backend cannot read a part's script | `search_section` | "The footage search could not read part <sid>." (VO path: logged, beat skipped) | |
| A whole-video download fails | `after_search` | nothing; the video stays, its moments are cut on use | log "download … failed" |
| Picture search fails | `step_search` | nothing; the part has no photos | log "pictures for … failed" |
| A clip cannot be cut | `cut` | the moment is marked `cutFailed` | log "clip … unusable" |
| `clean_shots.py` fails | `cut` | no flags; clips still usable | log "shot check skipped" |
| Voices not ready after 30 min | `step_check` | check runs anyway with estimated beat lengths | |
| `vo_pick.py` fails | `run` | `PLAIN.check`; `edit.state = failed` (VO only) | traceback + checker output in log |
| `vo_pick.py` exits 0 but writes no `edit.json` | `step_check` | "The shot check could not finish (the vision model did not answer)…" | |
| `assemble916.py` fails | `step_final` | `PLAIN.final`; `final.state = failed` (in a render: `render.failed` with `PLAIN.render`) | log |
| Nothing to build at render time (edit or voices not ready) | `render_vo` | "The final video could not be made." | |
| Anchor pictures missing in ComfyUI `input/` | `gpu_run` | "This anchor's pictures are missing on the render machine…" | log "missing from ComfyUI input/" |
| `run_multi.py` fails | `_gpu_run` | `PLAIN.render`, `render.failed`, `stage = review` | log "Render failed: …" |
| Lips out of step | `lipsync` | `render.held` with the reason | log |
| A VO part with nothing to show | `step_assemble` | "Part <sid> has no pictures. Place footage or pictures for it first." | |
| Final stale or missing at post time | `step_post` | "The final video changed. Wait until it is made again, then post." | |
| YouTube keys missing | `step_post` | "YouTube is not connected on this machine yet…" | `youtube.env` |
| YouTube API error during post | `publish.*` | `PLAIN.post`; `posts.youtube.failed` (the saved `videoId` prevents a second upload) | log |
| DB or LLM error in selection | `step_selection` | no picks today; retried every 30 min | `selection/log.txt` |
| `cut` job crashes | `main` | nothing (no job record) | log |
| Process killed (restart) | — | handled by the job loop's resume (HANDOFF section 12) | API journal |

---

## 19. Self-test

`TOOLS_PY worker.py selftest` (lines 1877–1894), run by `deploy/check.sh`. Prints `ok` when all pass. It checks:
- `story_names` finds names and drops sentence starts, titles and weekdays;
- `wall_shot` for the opening, middle and last anchor parts, and with no footage;
- `asked` for Slower, "Less flat. Faster", a respelling, and "Pause before the last line";
- `retry_lines` respelling "Hmielek" → "Chmielek", dropping the rare word, and returning nothing when there is no rare word.

`server/test_event_date.py` imports the worker and tests `event_query` and `first_reported`.
