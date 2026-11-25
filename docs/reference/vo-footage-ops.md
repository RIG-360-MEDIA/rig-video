# Reference: VO-only pipeline, footage search, machines and operations

> `file:line` references point at the code as of 2026-11-25; after later changes, search by the name given next to them.

> Part of the RIG-Video handoff. Read `docs/HANDOFF.md` first; this chapter assumes its sections 2, 4, 6, 10, 11
> and 13 and does not repeat them. Everything here is taken from the code at the time of writing. File references are
> `path:line`. Times are IST; the machines log in UTC.

Contents

- A. [The clip checker (`vo_pick.py`)](#a-the-clip-checker-vo_pickpy)
- B. [The 9:16 final video (`vertical/`)](#b-the-916-final-video-vertical)
- C. [The footage search backend (`footage/`)](#c-the-footage-search-backend-footage)
- D. [Machine files (`hosts/`)](#d-machine-files-hosts)
- E. [Deploy, CI and doctor](#e-deploy-ci-and-doctor)

---

## A. The clip checker (`vo_pick.py`)

File: `studio-app/pipeline/tools/footage/vo/vo_pick.py` (936 lines). Installed on t7 at
`~/anchor-studio/studio-app/pipeline/tools/footage/vo/vo_pick.py`.

### A.1 How it is run

| What | Value |
|---|---|
| Caller | `worker.step_check` (`server/worker.py:1344`) for VO only (edit → `p["edit"]`) and for anchor + VO (VO parts only → `p["anchorEdit"]`, work dir `check_anchor/`) |
| Interpreter | `VO_PY` = `~/anchor-studio/vertical/.venv/bin/python` (`server/worker.py:1120`): torch, SigLIP-2, RapidOCR |
| Command | `vo_pick.py <inputs.json> <out_dir> [--only F1,F2] [--preview]` (`vo_pick.py:884-898`). `--only` filters by story id (`sid`), not beat. `--preview` also writes a rough 16:9 cut. |
| Self-test | `vo_pick.py test` (`vo_pick.py:901-936`): cut placement, flash detection, fake-verdict rule, phrase breaks, cut points, `plan_beat`, name finding, repeat rule. |
| Machine lock | The worker holds `rigvideo-data/search.lock` **shared** for the whole run (`server/worker.py:1363`), so it never runs beside a render (which takes it exclusive). |
| Progress | Prints `PROGRESS beat k/n` per beat (`vo_pick.py:583`); the worker turns it into the site's progress line (`server/worker.py:1372-1377`). |
| Failure | One story failing never stops the others (`vo_pick.py:892-896`). The worker deletes the old `edit.json` first, so a failed run cannot reuse the last one (`server/worker.py:1379`), and then raises "The shot check could not finish". |

Environment variables (all optional):

| Variable | Default | Line |
|---|---|---|
| `VO_CACHE` | `~/vo_check/cache` | 22 |
| `VO_YTDLP` | `~/anchor-studio/repos/social_verifier/ytdlp_node.sh` | 23 |
| `VO_FFMPEG` | `~/anchor-studio/repos/ffmpeg-shared/current/bin/ffmpeg` | 24 |
| `VO_VLM` | `http://100.72.225.89:11620/v1,http://100.95.0.11:11610/v1` | 25 |
| `VO_ASSETS` | `~/anchor-studio/studio-app` (where `pipeline/orchestrator/assets.py` lives) | 44 |
| `VO_RANKDUMP` | unset. When set to a folder, writes `rank_<beat>.txt` with the top 60 ranked shots per beat and why. | 591-595 |

### A.2 Input schema (`inputs.json`)

Built by `worker.check_input` (`server/worker.py:1261-1281`). A list of stories; the worker always sends one.

```
[{ "sid": "<story id>", "headline": "...", "date": "YYYY-MM-DD",   # the pictured event date (worker.vo_date)
   "place": "<place or ''>",
   "beats": [{ "id": "b1", "text": "line spoken", "picture": "what should show",
               "cls": "event" | "archive", "dated": true,           # dated = cls == "event"
               "secs": 6.41,                                         # picked take length + 0.35 s (VO_GAP), else words/2.6
               "words": [{"w": "Strikes", "start": 0.12, "end": 0.48}, ...] }],   # faster-whisper small.en on the CPU
   "videos": [{ "id": "<youtube id>", "title": "...", "channel": "...", "dur": 312,
                "relevance": 72, "verdict": "<footage backend's verdict>",
                "beats": ["b1", "b3"],                               # which beats' searches found it
                "moments": [{"start": 12.0, "end": 40.0, "beat": "b1"}] }] }]
```

If `secs` is missing, `vo_pick` uses `max(3, words / 2.6)` (`vo_pick.py:458-459`, `WPS`).
For anchor + VO the pool is every video any search of the story ever found, VO-only beats' searches included
(`server/worker.py:1262-1265`).

### A.3 Output

In `<out_dir>/<sid>/`:

| File | Content |
|---|---|
| `edit.json` | The edit (below). |
| `sheet.jpg` | Contact sheet: one 427×240 tile per cut (beat, length, fit, `SWAP`), 4 per row, the beat's line and notes under each row (`vo_pick.py:840-861`). |
| `preview.mp4` | Only with `--preview`: silent 854×480, 25 fps, each beat's line burned in (`vo_pick.py:864-881`). |

`<out_dir>/timing.json`: `download_s`, `gate_s` (includes the download time), `rank_s`, `ocr_s`, `pick_s`,
`review_s`, `reasks`, `repeat_fixes`, and seconds per story.

`edit.json` shape (`vo_pick.py:831-833`, cut fields `vo_pick.py:723-726`):

```
{ "sid", "headline", "flow": "<review's one-sentence read of the sequence>", "secs", "shots_in_pool", "videos",
  "beats": [{ "beat": "b1", "text", "secs",
              "cuts": [{ "shot": <pool id>, "video": "<yt id>" | "own", "start", "end", "secs", "at",   # at = story time
                         "focus"?: <source time of the key moment>, "shot_end", "kind", "fit", "shows",
                         "sound": "<foley prompt or ''>", "title",
                         "fill"?: true, "swapped"?: true, "review"?: "<why flagged>",
                         "repeat_fixed"?: true, "repeat"?: true,
                         "image"?, "url"?, "page"? }],            # own pictures only
              "fill": ["story footage", "own picture", "topic footage", "2.1 s short", "dropped: ...", "repeat dropped", ...],
              "why": "<pick call's one sentence>",
              "candidates": [{ "n", "shot", "video", "start", "end", "sim", "title", "kind", "fit", "shows", "sound", ... }],
              "spares": [<shot ids chosen but not used>] }] }
```

The worker converts it into the site's `StoryEdit` with `edit_from` (`server/worker.py:1303-1336`): each cut gets
`src` (`{kind: video, youtubeId, start, end, shotEnd, focus?}` or `{kind: picture, url, page, title}`), a poster and a
360p preview clip cut from the 480p cache (`edit_media`, `server/worker.py:1278-1299`). Candidates the model judged
`no` or an unusable kind are not offered to editors.

### A.4 Constants

| Name | Value | Meaning (line) |
|---|---|---|
| `SIGLIP` | `google/siglip2-so400m-patch14-384` | Ranking model, local HF cache only (26, 216) |
| `MAX_VIDEO_S` | 2400 | Longer videos are skipped (27) |
| `MIN_SHOT_S` | 1.5 | Shortest camera shot kept (29) |
| `WPS` | 2.6 | Words per second when a beat has no voice yet (30) |
| `CANDS` | 10 | Candidate shots shown to the model per beat (31) |
| `PER_VIDEO` | 6 | Most candidates from one video (32) |
| `CUT` | (2.0, 5.0, 8.0) | Shortest, usual longest, absolute longest cut, s (34) |
| `MIN_CUT` | 2.0 | A shot shorter than this after trimming 0.6 s is never a cut (35) |
| `REUSE_GAP` | 12.0 | A shot or the same picture may return only this many seconds after it last ended (36) |
| `EARLY_DAYS` | 3 | A video uploaded more than this before the story date cannot show the event (38) |
| `DROP` | presenter, studio, promo, text_card, map, chart, animation | Kinds never used (40) |
| `FAKE` | regex: AI-generated, re-enact…, animat…, CGI, simulat…, computer-generated, colorized | Read from the search verdict (41) |
| `SAME_SCENE` | 0.88 | SigLIP cosine above which two shots are the same picture (42) |
| `LICENSED` | regex of stock and agency sites | Own pictures from these are dropped (45) |
| `OWN_MAX` | 4.0 | Longest hold of one own still, s (47) |
| `NAME_BOOST` | 0.04 | Rank bonus per beat name found in the video title, at most 2 (48) |

### A.5 Step 1: gate (shots and repeats)

1. **Skip** a video longer than 2400 s, or one whose search verdict says it *is* AI-made, animated or re-enacted
   (`fake`, `vo_pick.py:194-203`). The rule ignores negated ("not AI-generated") and hedged ("likely", "may",
   "or" …) mentions within 60 characters before the word.
2. **Download** at most 480p, H.264 preferred, with the info JSON, through `ytdlp_node.sh`, 4 videos at a time,
   900 s timeout each (`download`, `vo_pick.py:52-60`; pool `vo_pick.py:474-476`). A failed download is skipped.
3. **Split into shots** (`shots_of`, `vo_pick.py:70-92`): every frame at ~6 fps, HSV 32×32 histogram of a
   160×90 copy; a cut where histogram correlation with the previous sample is below 0.55. A shot needs at least 2
   samples and 1.5 s. Cached as `<cache>/<id>.shots.json`.
4. **Per shot**: 3 frames at 25/50/75 %; a 64-bit DCT hash of the middle frame (`phash`, skipped when the frame is
   one colour, std < 12). Two shots whose hashes differ in ≤10 bits are the same picture: only the longer copy is kept
   (`vo_pick.py:491-495`).
5. **Upload date** from the info JSON (`up`), and `moment_beats`: the beats whose search moments cover the shot's
   middle ±1 s (`vo_pick.py:498`).

If no shot survives, every beat is filled with own pictures (step 4).

### A.6 Step 2: rank (SigLIP-2)

`vo_pick.py:504-511`. Image embedding = mean of the 3 frames' embeddings, normalised (fp16 on CUDA). Text embedding =
`embed(line) + embed(picture or line)`, normalised. `S = T · Eᵀ` (beats × shots).

Per beat the rank key is (`vo_pick.py:589-590`):

```
S[beat, shot] + 0.04 × min(2, beat names in the video title)
              + 0.02 if a search moment of this beat covers the shot
              − 0.02 if it is an event beat and the video was uploaded > 3 days before the story date
```

Names come from `names()` (`vo_pick.py:156-166`): capitalised runs not at a sentence start, plus a multi-word name
opening the sentence, minus a small common-word list.

Candidates: walk the ranking, skip shots used less than `REUSE_GAP` ago (`recent`, `vo_pick.py:528`), at most 6 per
video, stop at 10 (`vo_pick.py:596-603`).

"Same picture" (`same`, `vo_pick.py:520-527`): across videos, cosine > 0.88; inside one video, the same hash, or the
same on-screen text (≥ 8 characters) with cosine > 0.88.

### A.7 Step 3: pick (Qwen3-VL), one call per beat

**What the model sees** (`see`, `vo_pick.py:531-555`; `ask`, `vo_pick.py:607-630`), 4 shots prepared in parallel:

- the full-size middle frame;
- a second frame at the **peak** moment when it is more than 15 % of the shot away from the middle. `peak_time`
  (`vo_pick.py:107-128`) reads every frame, 160×90 grey, and takes the frame with the largest 99.5th-percentile change
  from the previous frame; below 20 levels it uses the middle. Own pictures and shots under 1.2 s get one frame.
- the on-screen text, read by RapidOCR on the CPU (boxes with score > 0.6 and ≥ 2 characters, 200 characters max)
  (`ocr`, `vo_pick.py:178-191`);
- the video title and its age relative to the story date ("uploaded N days / years before this story",
  "around this story's date").

**The prompt** (`PICK`, `vo_pick.py:265-323`) sets the model as a senior news editor and gives it the headline, every
beat's line, the beat being cut, its length, the number of shots needed (`need = clamp(round(secs / 3.5), 1, 3)`) and
the writer's wanted picture as a hint. Its rules, in short:

- show the line's subject; a named or quoted person allows only that person or the event;
- a logo or flag alone is `topic` at most;
- posts, documents, newspaper pages and news text on screen are usable (`post_or_document`), judged by their text;
- presenters, studios, channel cards, maps, charts and other events are unusable; on-screen text naming other places,
  numbers or opponents, or "file"/"archive"/"representative visuals", means another event;
- old uploads may still show the same people and places (archive = `subject`);
- prefer moving footage, vary from the previous beat (whose `shows` are given), order shots as events happen;
- `sound`: up to 8 words of scene sound only for shots with action that makes a distinct sound, `""` for static
  scenes, people talking, photos, documents, text, maps.

The answer is JSON: per shot `kind`, `shows`, `at` (which frame), `sound`, `fit` (`exact` | `subject` | `topic` |
`no`), plus `pick` (up to `need + 1` shots) and `why`.

**Call** (`vlm`, `vo_pick.py:249-262`): OpenAI-style `/chat/completions`, `model: "vlm"`, temperature 0,
`max_tokens` 1500, `response_format: json_object`, 600 s timeout. The servers in `VO_VLM` are tried in order: t7 `:11620`
first, t8 `:11610` if t7's raises any error. (t8's server alias is `qwen3-vl-q4`; see D.3.) If no server answers, the
beat raises and the whole check fails (`vo_pick.py:628-630`), so editors never get a silent pictures-only edit.

If the model left some shots unlabelled, one more call asks for just those (`vo_pick.py:639-644`).

**Choice** (`vo_pick.py:645-664`):

- usable = kind not in `DROP` and fit `exact` or `subject`;
- order = the model's `pick` order, then other `exact` shots, then other usable ones;
- every usable candidate also enters the story's **pool** for later beats;
- a shot is skipped if its length − 0.6 s < 2 s, or it is the same picture as one already chosen or one in the previous beat.

`focus` = the time of the frame the model named in `at` (`vo_pick.py:650-652`). Cuts are placed around it.

**Filling a short beat** (`vo_pick.py:665-710`). `have` = sum of `min(len − 0.6, 8)` over the first 3 chosen shots.
While `have < secs − 0.3`, in this order:

| Order | Source | Note added to `fill` |
|---|---|---|
| 1 | Up to 2 shots from the story pool (earlier beats' usable shots), best by `S`, not recent, not in the previous beat | `story footage` |
| 2 | **Own pictures** (below) | `own picture` |
| 3 | This beat's `topic`-fit candidates | `topic footage` |
| 4 | Nothing chosen at all: the best-ranked candidate that is not `no`, not an unusable kind, not already used | `no fitting shot: best-ranked used` |

**Own pictures** (`own_shots`, `vo_pick.py:557-580`; `own_search`, `vo_pick.py:433-448`):

- Query: the first 3 names in the line (plus the story's place if missing), else the wanted picture, else the headline; repeated words removed.
- Search: `pipeline.orchestrator.assets.vo_pictures(query, out_dir, keep=6)` from the studio code (Bing images + Wikimedia
  Commons with the wall-photo filters). `vo_pick` replaces that module's OCR hook with its own RapidOCR instance.
  `names` is not passed.
- Pictures from `LICENSED` sites are dropped; at most 4 are kept. They are cached in `<cache>/own/<sid>/<beat>/`.
- A picture identical to a pool shot (hash) is skipped. Each becomes a pool shot of length 4.6 s, embedded and ranked like footage.
- A separate pick call over just these pictures follows, with an extra note that they are our own pictures. Kept ones get kind `photo`,
  no sound, and count as 4 s each.
- If the search or the studio code fails, the beat stays short and says so.

### A.8 Step 4: assemble the beat

`vo_pick.py:711-740`.

1. The first 3 chosen shots are sorted so shots from the same video keep their original order (by the video's first
   appearance, then start time).
2. **Phrase breaks** (`clauses`, `vo_pick.py:343-354`): with voice words (at least 80 % of the line's word count),
   the end time of every word ending in `, . ; : ! ?`; otherwise an even spread at punctuation and at "and", "but",
   "while", "after", "as".
3. **Cut count and lengths** (`plan_beat`, `vo_pick.py:369-384`):
   `k = max(1, min(shots, 3, round(secs / 3.5), secs // 2))`. If a shot is too short for its slot, `k` grows, up to 4
   cuts for a beat of 9 s or more, else 3, and never more than `secs // 2`. Each length is capped at the shot's length − 0.6 s; leftover time goes to the shots with most room.
4. **Cut points** (`cut_points`, `vo_pick.py:357-366`): an even split, each point moved to the nearest phrase break
   within 1.2 s, keeping every piece ≥ 2 s; a point with no room is dropped.
5. **Where in the shot** (`cut_start`, `vo_pick.py:131-137`): with a `focus`, the cut starts a third of its length before the focus moment.
   Without one, the cut is centred. It stays inside the shot: the start trims 0.15 s (when the moment is right after the shot cut) or
   0.3 s, and the end keeps 0.3 s spare.
6. **Fill the exact length** (`hold_longer`, `vo_pick.py:387-404`): if the cuts are short together, the cuts with the longest shots grow,
   each to at most 8 s. If they are too long, the longest cut is trimmed (not below 2 s). The cuts are then re-timed. A gap over 0.3 s adds
   `"<gap> s short"`.

### A.9 Step 5: review (one call per story)

`vo_pick.py:743-789`. One frame (the middle) per cut with its line, prompt `REVIEW` (`vo_pick.py:325-338`): flag a cut
only if it shows a different person, place or event; is a presenter, studio, channel card, map or chart; or repeats
the cut before. Archive of the same people or places, tickers and posts are explicitly fine. `max_tokens` 800. If the
call fails, the edit is kept unreviewed.

For each flagged cut (marked `review`):

- the beat's next spare that is not already in the beat and not the same picture as any cut in this or the neighbouring beats replaces it (`place`, `swapped`);
- with no such spare, if the beat has other cuts that can hold its time, the cut is dropped (`dropped: <why>`);
- otherwise it stays, flagged.

Beats that changed are re-timed.

### A.10 Step 6: enforce (repeats)

`vo_pick.py:791-829`. `repeats()` (`vo_pick.py:407-416`) marks a cut that is the same shot or same picture as the cut right
before it, or that returns less than 12 s after an earlier use ended. Up to 50 rounds, each fixing the first bad cut:

1. try the beat's spares and the story pool, best by `S`, each long enough; keep the first that removes the repeat (`repeat_fixed`);
2. else drop the cut if the beat has more than one (`repeat dropped`);
3. else mark it `repeat` and leave it.

### A.11 Caching

| Cache | Key | Kept |
|---|---|---|
| 480p video + `.info.json` | `<VO_CACHE>/<id>.mp4` | Forever (also the fallback for the final video, B.2) |
| Shot list | `<VO_CACHE>/<id>.shots.json` | Forever |
| Own pictures | `<VO_CACHE>/own/<sid>/<beat>/` | Forever |
| SigLIP and OCR models | in-process (`_M`, `_O`) | One run |

Model answers are not cached; every check asks again.

---

## B. The 9:16 final video (`vertical/`)

Installed on t7 at `~/anchor-studio/vertical/`. Not in git there: `models/` (YuNet ONNX, UNISAL weights),
`fonts/` and the `.venv` (packages: `hosts/t7/requirements/vertical.txt`).

### B.1 How it is run

`worker.step_final` (`server/worker.py:1442-1494`) copies `project.json` into `projects/<id>/final916/project.json` and
runs, under the shared `search.lock`:

```
TOOLS_PY assemble916.py <project dir> <project dir>/final916 <final916/project.json>
```

`assemble916.py` itself runs in `TOOLS_PY` (it needs numpy, soundfile and faster-whisper). It calls `vconv.py` and
`cropcheck.py` with the vertical venv (`PY`, `assemble916.py:19`). It prints `PROGRESS k/n` (n = cuts + 3) and
`STAGE <text>`, which the worker shows as "Framing shot k of n" and the stage name.

The worker then copies `final916/final_916.mp4` to `media/final_916.mp4`, makes a 540-wide poster at 1 s, and records
`final.cuts`, `final.low` (cuts that came from the 480p copy) and `final.whole` (cuts made whole-frame), read from
`build.json`. `step_final(again=True)` deletes the `.how.json` of every low-quality cut so they are downloaded again.

### B.2 `assemble916.py` (150 lines): per cut

Input: the project's `edit.beats[].cuts[]` (site shape), `versions.vo_only` (lines and their picked take) and
`_takes`.

**Video cuts** (`assemble916.py:83-108`):

1. **Download** (`download`, `assemble916.py:29-50`) through `ytdlp_node.sh`:
   format `bv*[height<=1080][vcodec^=avc1]/bv*[height<=1080]/b[height<=1080]` (video only); the section
   `[start − 4 s, start + secs + 4 s]` (`MARGIN` = 4.0), `--force-keyframes-at-cuts`, 30 s socket timeout, 600 s limit, 2 tries.
   A "not a bot" refusal stops retrying. Saved as `raw_<id>_<start>_<secs>.mp4` with a sidecar `raw_….json`
   `{"a": <source time of its first frame>}`; older raws without a sidecar are taken as having 2 s spare.
   If it fails, the checker's `~/vo_check/cache/<id>.mp4` (480p, whole video) is used and the cut is marked
   `full: false`. If that is missing too, the build fails.
2. **Cut exactly**: `ffmpeg -ss <start − a> -t <secs>`, no audio, libx264 CRF 14, preset medium → `src_<key>.mp4`.
3. **Reframe**:
   - `kind == post_or_document` → `vconv.py --fit` ("whole frame: text shot");
   - otherwise `vconv.py`, then `cropcheck.py src out "<shows>" [<focus − start>] --line "<beat line>"`. If the check
     is not `ok` (or gave no answer), `vconv.py --fit` again ("whole frame: crop check failed").
   The result and the check go into `v_<key>_<kind>.how.json` (`how`, `check`, `full`).
4. Fields for sound: `before` / `after` = spare seconds in the raw around the cut, `loud` and `prompt` from
   `sound916` (B.5).

**Own pictures** (`src.kind != "video"`, `assemble916.py:72-82`): the image (from the cut's `poster` path inside
the project) is looped for the cut length at 25 fps, CRF 14, then `vconv.py --fit`. `loud = -1` (no sound).

**Rebuild reuse**: files are named by video, start, length and kind (`key`). An existing `v_*.mp4` with its
`.how.json` is reused, unless the old one was low quality and this time the download worked (`assemble916.py:90`). So a
rebuild after an edit only makes the changed cuts.

**Voice per beat** (`assemble916.py:112-116`): the picked take →
`silenceremove` (leading silence under −45 dB) → `apad` → `atrim` to the beat's `secs` → `highpass 70 Hz` →
`loudnorm I=-16:TP=-1.5:LRA=11` → 48 kHz stereo `voice_<beat>.wav`.

**After all cuts** (`assemble916.py:118-147`):

1. `sound916.place(cuts)` sets `pre`/`post` (lead-in and sound-ups). A cut with `pre` or `post` is cut again from its
   raw over the longer range and reframed again with the same layout choice (`--fit` if it was whole), as
   `vx_<key>_<pre>_<post>_<kind>.mp4`.
2. `STAGE Making the sound`: `sound916.foley` on every cut with `loud ≥ 0`.
3. `STAGE Mixing and captions`: `sound916.mix` → `mix.wav` and the loudnorm filter; `plan.json` (cut beat, length,
   `pre`; voices); `gfx916.ass` → `gfx.ass`.
4. `STAGE Finishing the video`: **the final encode** (`assemble916.py:139-143`):
   ```
   ffmpeg -f concat -i v.txt -i mix.wav
          -filter_complex "[0:v]ass=gfx.ass:fontsdir=<FONTS>[v];[1:a]<two-pass loudnorm>,aresample=48000[a]"
          -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p -c:a aac -b:a 192k -shortest -movflags +faststart
          final_916.mp4
   ```
5. `build.json` (`assemble916.py:144-146`):

| Key | Content |
|---|---|
| `cuts[]` | `beat`, `shows`, `prompt`, `secs`, `loud`, `pre`, `post`, `how` ("converter", "whole frame: text shot", "whole frame: crop check failed", "whole frame: own picture"), `full` (false = 480p copy), `check` (`{ok, missing, at}`) |
| `soundUps` | indices of the cuts lengthened into a sound-up |
| `foley` | number of cuts that got a foley sound |

Other files left in `final916/`: `raw_*`, `src_*`, `v_*` (+ `.json` sidecar, `.how.json`), `xsrc_*`, `vx_*`, `voice_*.wav`,
`fx_*.wav`, `foley_run/`, `mix.wav`, `plan.json`, `gfx.ass`, `v.txt`, `project.json`.

### B.3 `vconv.py` (836 lines): landscape to 1080×1920

`vconv.py in.mp4 out.mp4 [--preview preview.mp4] [--fit]`; `vconv.py --selftest`. Output: 1080×1920, 24 fps,
H.264 (NVENC), no audio, plus a JSON sidecar `out.json`.

**Models** (`Models`, `vconv.py:125-218`), all loaded once per process:

| Model | Use | Settings |
|---|---|---|
| TransNetV2 (`transnetv2_pytorch`) | Shot cuts | 48×27 frames, cut where p > 0.5 rises (`vconv.py:155-162`) |
| RF-DETR Small (`rfdetr`) | People and objects (COCO) | threshold 0.45 |
| YuNet (`models/face_detection_yunet_2023mar.onnx`) | Faces | score 0.7 |
| UNISAL (`models/unisal`, pretrained run) | Saliency | DHF1K head, 384×224 input |
| RapidOCR (`rapidocr`, detection only) | Text boxes | score ≥ 0.6; on GPU when CUDA and `VCONV_OCR_GPU=1` (default) |

The code comment at `vconv.py:140` says onnxruntime-gpu must stay a CUDA 12 build and the CUDA 13 cuDNN extras must
never be installed (they overwrite torch's cuDNN). `hosts/t7/requirements/vertical.txt` pins `onnxruntime-gpu==1.32.0`;
the comment names 1.23.2.

**Constants** (`vconv.py:34-50`):

| Name | Value | Meaning |
|---|---|---|
| `FPS, OW, OH` | 24, 1080, 1920 | Output |
| `AW` | 640 | Analysis width |
| `MAX_UP` | 2.0 | Crops may be upscaled at most 2×; a source under 960 px tall is FIT throughout |
| `SAMPLE` | 6 | Analyse every 6th frame (4/s) |
| `SPEED` | 0.15 | Max crop speed, frame widths per second |
| `LOCK_TRAVEL` | 0.15 | Subject travel under this share of width → LOCKED |
| `CONF_MIN` | 0.5 | Below → FIT |
| `TEXT_HEAVY` | 0.08 | Scene-text area share → FIT |
| `TRIM_MAX` | 0.15 | FIT may trim up to 15 % per edge to drop an edge logo/ticker |
| `TEXT_SAMPLES`, `VERIFY_FRAMES` | 6, 4 | OCR samples per shot; OCR checks of output crops per shot |
| `BIG_TEXT` | 0.06 | Scene text this tall that a crop would cut → FIT |
| `TEXT_MAX_H` | 0.10 | Taller "text" is texture |
| `STATIC` | 0.006 | Box movement under this share of width = still |
| `SAL_KEEP` | 0.35 | A crop must keep this share of the saliency |
| `RENDER_THREADS` | `$VCONV_THREADS` or 16 | Parallel frame composition |

Other env: `VCONV_FFMPEG` (default the shared ffmpeg build, else `ffmpeg` on PATH).

**Flow** (`convert`, `vconv.py:723-792`):

1. `probe`: size, rotation (90° swaps width/height), duration.
2. **Black bars**: `cropdetect` at 2 fps (limit 24, round 2, reset 0); ignored if the box is under 30 % of either side
   (`vconv.py:91-101`). Skipped with `--fit`, so bands with captions stay.
3. Decode at 640 px wide after `bwdif` deinterlace, `fps=24`, crop.
4. **Blurred sides** (`vconv.py:104-120`): a vertical video inside a landscape frame with blurred copies on the
   sides is found by column sharpness, and only the sharp middle is kept. Skipped with `--fit`.
5. **PASS** if the picture is already 9:16 or narrower (aspect ≤ 9/16 × 1.05).
6. Otherwise: overlays (`find_overlays`: edge-rich regions unchanged across ≥ 24 sampled frames, area > 0.15 %,
   width < 90 %), the FIT trim for edge overlays (`fit_trim`), and shot cuts.
7. Per shot `analyse` then `decide`. Any model error makes that shot FIT (`vconv.py:762-773`).
8. A shot under 0.5 s next to a FIT/SWEEP/PASS shot becomes FIT.
9. `--fit`: one FIT shot over the whole clip, no trim (unless PASS).
10. `render`: frames decoded at full crop resolution, composed in parallel, encoded with
    `h264_nvenc -preset p6 -rc vbr -cq 18 -profile high`, BT.709, `+faststart` (`vconv.py:632-685`).

**`analyse`** (`vconv.py:356-385`) per shot: grey frames for motion, OCR text boxes on 6 samples, `text_share`
(scene text only; graphics are banded, not counted). It returns early if the shot is text-heavy or a still of 2 s or
more. Otherwise it runs detection, faces and saliency on every 6th frame, and links boxes into tracks by IoU > 0.2
(`tracks`). Kept tracks are present in ≥ 40 % of samples. A still person in a moving scene is demoted (×0.2).
`mark_pip` (`vconv.py:388-404`) marks a still person at the same spot in two shots with different surroundings as a
picture-in-picture inset: never the subject, and blurred if a crop cuts it.

**`decide`** (`vconv.py:407-577`), first match wins:

| Condition | Layout |
|---|---|
| scene text > 8 % of the frame | FIT |
| still (mean motion < 1) and ≥ 2 s | **SWEEP**: FIT with a push-in from 1.00× to 1.06× over the shot |
| every crop position cuts through an inset | FIT |
| top two people both present in ≥ 50 % of samples and their joint span ≤ 0.95 × crop width | one crop on both (then as below) |
| exactly 2 people, each wider than 4.5 % of width, ≥ 20 % of width apart, shot ≥ 2.5 s | **SPLIT**: two 1080×960 crops stacked |
| ≥ 3 people, the top one scoring less than twice the second | FIT |
| main subject (person first, else object > 2 % area) is small and its window holds < 80 % of the best saliency window | the subject is dropped; saliency decides |
| no subject, best window holds < 60 % of saliency | FIT |
| no subject, saliency concentrated | **LOCKED** at the best window |
| subject found in < 50 % of samples | FIT |
| subject travel ≤ 15 % of width | **LOCKED** at its median (moved clear of scene text and insets if within 30 % of the crop) |
| subject moves more | **TRACK**: per-frame path, 3 % dead zone, Gaussian smoothing (σ = 8 frames), speed ≤ 0.15 widths/s both ways |
| crop keeps < 35 % of saliency, or confidence `hit × min(1, keep / 0.6)` < 0.5 | FIT |
| `text_guard` finds large scene text (≥ 6 % of height) cut by the crop | FIT |

Subject aim (`aim`): the face centre if a face is inside the person box, else the box centre. Subject score: presence ×
(area + 0.5 × saliency mass) × centrality.

**`text_guard`** (`vconv.py:313-353`): text cut by a crop edge is blurred, never shown half-cut.

- Graphics (`is_graphic`: on a small stable overlay, or in the top 22 % / bottom 40 % at a steady height) get a full-width blur band.
- Scene text and insets get a blur over their own box.
- Then OCR runs on up to 4 output crops at 2× size; any text still touching a crop edge gets a patch too (`patches_by_check`).
- `blur_patch` (`vconv.py:290-306`) shrinks the area so a text line is about 4 px tall, blurs it, and feathers the patch outward.

**FIT** (`fit_frame`, `vconv.py:612-629`): the whole frame (after the edge trim) scaled to fit the width, over a copy
of itself scaled to fill, blurred (1/8 size, σ 6) and darkened to 70 %. PASS uses the same function without trim.

**Sidecar** (`vconv.py:743-791`): `input`, `source` [w, h], `duration`, `bars`, `blurred_sides`, `frames`,
`shots[]` (`start`, `end` in frames, `mode`, `reason`, `confidence`, `x` as [first, last], `patches`,
`patches_by_check`, `pair` for SPLIT), `overlays`, `fit_trim`, `seconds`, `timing` per stage.
`--preview` writes a 1920×1080 review video: the source with the crop (orange) and patches (magenta) on the left, the
output on the right, the mode and reason on top.

### B.4 `cropcheck.py` (85 lines)

`cropcheck.py src.mp4 out916.mp4 "<shows>" [key s] [--line "<line>"]` → prints `{"ok", "missing", "at"}`.

- One moment only: the key moment (the checker's `focus`, relative to the cut), else the middle, clamped to the clip
  (`cropcheck.py:64`).
- Picture A = the source frame (max 1280 wide), picture B = the vertical frame (1080 wide).
- Prompt (`ASK`, `cropcheck.py:21-29`): judge only the picture, ignore all text; did B lose the person, place or
  moment the shot was chosen for; small but visible is fine.
- Same server list and order as the checker (`VO_VLM`), `max_tokens` 200, 300 s timeout.
- Any failure (frames unreadable, no server, a non-`true` answer) returns `ok: false`, so the safe whole-frame version is used.

### B.5 `sound916.py` (173 lines): scene sound and the mix

Rules (docstring `sound916.py:1-11`): only shots that show something making a sound get **foley**. There is nothing from
the source clips and no music.

**Which cuts** (`loud`, `sound916.py:31-40`): −1 = no foley, else 1 to 3.

- With a `sound` field (every edit since 2026-11-24): an empty `sound` gives −1. Otherwise the level comes from the first `LOUD` regex that matches the prompt, else 1.
- Without a `sound` field (older edits): −1 for `post_or_document`, `speech` or speaking scenes. Otherwise the level comes from `shows`, and only level ≥ 2 gets sound.

| Level | Regex (`LOUD`, `sound916.py:19-21`) | Foley under the voice (`UNDER`) |
|---|---|---|
| 3 | explosion, blast, missile, rocket, launch, strike, bomb, shell, gunfire, firing, artillery, drone attack | −12 dB |
| 2 | fire, burn, siren, ambulance, police car, helicopter, jet, aircraft, crowd, protest, rally, riot, clash, concert, tank, armour | −12 dB |
| 1 | traffic, street, port, ship, train, storm, rain, flood, wave, engine, crane | −24 dB |

`prompt` = the cut's `sound`, else `shows`.

**Lead-in and sound-ups** (`place`, `sound916.py:47-76`). Constants `LEAD = 1.5`, `UP = 3.0`, `MAX_UPS = 2`,
`SPACING = 20.0` s.

- **Lead-in**: if the first cut has sound, it starts up to 1.5 s early (as much spare footage as there is). The first
  voice starts after it.
- **Sound-ups**: at beat boundaries next to a cut of level ≥ 2, loudest first, then earliest, at most 2. Not within the first
  20 s, not within 20 s of another sound-up, and not twice on the same cut.
  - The loud cut is lengthened by up to 3 s from its spare footage. The neighbour across the boundary adds the rest, but only if it has a sound of its own (level ≥ 1).
  - Together they must give at least 1.5 s.
  - The next voice starts later by the lengthening, so the voice pauses and the scene sound comes up.
- `EXTRA_S` (6.8 s, `sound916.py:24`) is the most picture time this adds. Nothing else in the repo reads it.

**Foley** (`foley`, `sound916.py:79-105`): HunyuanVideo-Foley XL in `~/foley/HunyuanVideo-Foley` with its own `.venv`.

- One CSV row per clip (`index, video, prompt`). The clip is the final (lengthened) vertical cut.
- Command: `infer.py --model_path ~/foley/weights/HunyuanVideo-Foley --model_size xl --csv_path … --output_dir … --neg_prompt "speech, talking, human voice, narration, music, singing"`.
- If the GPU has less than 20 000 MiB free (`nvidia-smi`), it runs with `--enable_offload` straight away. Otherwise it runs whole, and on failure again with `--enable_offload`.
- Results are cached as `fx_<clip stem>_<sha1(prompt)[:8]>.wav`, so a changed prompt makes a new sound.

**Mix** (`mix`, `sound916.py:108-156`), 48 kHz mono:

1. Each beat's voice starts at its first cut's start plus that cut's `pre`.
2. Each foley track is fitted to its cut, normalised to −24 dBFS RMS, with 40 ms fades.
3. Voice activity: 50 ms frames over −40 dBFS; gaps under 0.8 s count as speech.
4. Foley level relative to the voice's median level: the cut's `UNDER` value while the voice speaks, −3 dB (`UP_DB`)
   when it does not (lead-in, sound-ups, pauses), with 0.25 s ramps.
5. The sum is clipped to ±1 and written to `mix.wav`.
6. First loudnorm pass measures it. The returned filter is the second pass:
   `loudnorm=I=-14:TP=-1.5:LRA=11:…:linear=true`, applied in the final encode.

### B.6 `gfx916.py` (164 lines): captions, title card, quote cards

Rendered as ASS subtitles at 1080×1920 and burned in by ffmpeg's `ass` filter with `fontsdir=~/anchor-studio/vertical/fonts`.
The fonts used are Plus Jakarta Sans ExtraBold and Bold (and Arial for the boxes). There are no credits.

**Caption timing** (`ass`, `gfx916.py:104-129`):

- Beat start = the story time of its first cut + that cut's `pre` (from `plan.json`).
- Words: faster-whisper `small` on the CPU (int8), English, word timestamps, run on the beat's `voice_<beat>.wav`.
- `script_words` (`gfx916.py:31-57`) keeps the **script's** spelling. It aligns the script words to the heard words with `difflib`; matched words take whisper's times, the rest are spread evenly between their matched neighbours.
- `groups` (`gfx916.py:79-87`): a caption closes at 4 words, at 24 characters, or after punctuation once it has 2 words.
- A caption ends when the next one starts (if that is less than 0.6 s later), else 0.25 s after its last word.

**Styles** (`gfx916.py:140-147`):

| Style | Font, size | Place | Use |
|---|---|---|---|
| `Cap` | Plus Jakarta Sans ExtraBold 66, white, 3.5 outline, 2 shadow | bottom centre, 500 px up, 80 px side margins | Captions |
| `Title` | ExtraBold 82, white | top-left at (80, 335), wrap 20 characters | Headline, 0 to 3.5 s (`TITLE_S`), fade 150/300 ms |
| `Rule` | solid DNL red `#E31B23` | 90×10 bar | Above the title (80, 300) and the quote (80, 620) |
| `Quote` / `Who` | Bold 60 / ExtraBold 44 | (80, 660), wrap 26 characters | Quote card |
| `Box` | black at alpha `0x70` | full frame | Darkens the picture behind a quote |

**Quote cards** (`quote_of`, `gfx916.py:90-101`): a beat whose text has a quotation of 25 or more characters, and a
speaker found by name before the quote ("X said/says/argued/stated/added/warned/told/wrote/noted") or after it
("…," said X). The card covers the whole beat, fading 200 ms in and out. An unnamed speaker ("a spokesperson said") gives no card.

Self-tests: `python gfx916.py` and `python sound916.py` (both print `ok`).

---

## C. The footage search backend (`footage/`)

Vendored copy of "Live Cutter" (`footage/UPSTREAM.md`): upstream `Daksh288948921904/social_verifier`, branch
`dnl-trijya-whisper` at 5504871. Only `backend/` is kept. The one local change: `app/core/auth.py` reads its password from
`$FOOTAGE_AUTH_PASSWORD` or `~/.config/anchor-studio/footage-auth`.

Installed on t7 at `~/anchor-studio/repos/social_verifier/` (`backend/` and `ytdlp_node.sh`). Python:
`~/anchor-studio/repos/social_verifier/.venv` (packages: `hosts/t7/requirements/footage.txt`, which includes yt-dlp
2026.10.21, `bgutil-ytdlp-pot-provider`, `curl-cffi`, `faster-whisper`, `groq`, `openai`).

### C.1 Starting it (`start_backend.sh`)

`studio-app/pipeline/tools/footage/start_backend.sh` (48 lines). The worker runs it when `GET /api/health` does not answer
(`sv_client`, `server/worker.py:495-509`; a 401 or 404 also counts as up). The worker waits up to 180 s, writes the script's output to
`rigvideo-data/footage_backend.log`, and otherwise fails with "The footage search service did not start". `deploy.sh`
also runs it after a release that changed `footage/`, if the backend was running.

What it does, in order:

1. `DATA = $FOOTAGE_DATA_DIR` or `~/anchor-studio/footage/data`; kills an earlier `uvicorn app.main:app … --port 8787`.
2. Exports up to 7 Groq keys from `~/.config/anchor-studio/llm.env` (`GROQ_API_KEY` comma list → `GROQ_API_KEY`,
   `GROQ_API_KEY_2…7`), into the process environment only.
3. Starts the **PO-token server** (bgutil) if `localhost:4416/ping` does not answer:
   `~/.nvm/versions/node/v20.20.2/bin/node build/main.js --port 4416 --host 127.0.0.1` in
   `~/anchor-studio/repos/bgutil-ytdlp-pot-provider/server`, detached, log `$DATA/pot_server.log`.
4. `LD_LIBRARY_PATH` += the venv's `nvidia/cublas` and `nvidia/cudnn` (for whisper on the GPU); `PATH` starts with the
   shared ffmpeg build; `DATA_DIR=$DATA`; `YTDLP_BIN=…/ytdlp_node.sh`.
5. Sources `~/.config/anchor-studio/footage.env` if present (its Groq keys then replace the `llm.env` ones; also
   `YOUTUBE_API_KEY`, `GOOGLE_CSE_*`) and unsets `OPENAI_API_KEY`.
6. `FOOTAGE_LLM=local` (default): `LLM_BASE_URL=${FOOTAGE_LLM_URL:-http://100.95.0.11:11610/v1}`,
   `LLM_MODEL=${FOOTAGE_LLM_MODEL:-qwen3-vl-q4}`. `FOOTAGE_LLM=groq` leaves them unset (Groq only).
7. `FOOTAGE_VIDEOS_PER_KEYWORD=4`, `FOOTAGE_KEYWORDS_PER_WAVE=3` unless already set.
8. `cd backend; nohup uvicorn app.main:app --host 127.0.0.1 --port 8787 > $DATA/backend.log`; waits up to 30 s for
   `/api/health`, exit 1 if it never answers.

It is **not** a systemd unit and does not start at boot. The PO-token server keeps running after the backend stops.

### C.2 Configuration it reads

`app/core/config.py` (pydantic settings; environment variables, plus `backend/.env` if one exists in the working
directory). The ones that matter to RIG-Video:

| Variable | Default | Used for |
|---|---|---|
| `GROQ_API_KEY`, `GROQ_API_KEY_2…7` | — | Groq fallback, rotated per call |
| `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY` | —, —, `local` | Local OpenAI-compatible LLM first (`app/core/groq_pool.py:40-59`) |
| `YOUTUBE_API_KEY` | — | YouTube Data API search |
| `FOOTAGE_VIDEOS_PER_KEYWORD` | 5 (4 from `start_backend.sh`) | Videos per keyword, unless the keyword has `limit:N` |
| `FOOTAGE_KEYWORDS_PER_WAVE` | 3 | Keywords searched side by side |
| `DATA_DIR` | `backend/../data` (`~/anchor-studio/footage/data` from the script) | SQLite DB and clip files |
| `YTDLP_BIN` | `yt-dlp` (`ytdlp_node.sh` from the script) | Every yt-dlp call |
| `SEGMENTATION_MODEL` | `openai/gpt-oss-120b` | Model name sent; replaced by `LLM_MODEL` on the local server |
| `YTDLP_YOUTUBE_COOKIES_FILE` | empty | Not set on t7 |
| `FOOTAGE_CAPTION_MIN_INTERVAL_S` | 3 | Seconds between caption downloads |
| `FOOTAGE_CAPTION_COOLDOWN_S` | 1800 | Caption pause after a 429 |
| `FOOTAGE_WHISPER_MODEL` | `small` (empty = off) | Speech-to-text fallback |
| `FOOTAGE_WHISPER_MAX_SECONDS` | 0 (whole video) | Cap on transcribed audio |
| `FOOTAGE_WHISPER_DEVICE` | `auto` | `auto` / `cuda` / `cpu` |
| `FOOTAGE_INVIDIOUS` | `auto` | Invidious caption fallback servers; empty = off |
| `FOOTAGE_AUTH_USERNAME`, `FOOTAGE_AUTH_PASSWORD` | `rig360media`, file | The single account |

At startup (`app/main.py:60-110`) it creates the database schema, marks interrupted jobs as failed
(`recover_interrupted`, `app/footage/runner.py:224-252`), checks that `ffmpeg`, `ffprobe` and `yt-dlp` are on PATH, and
logs warnings for missing keys. httpx request logging is turned down because URLs carry API keys (`app/main.py:19`).

### C.3 Auth

One account (`app/core/auth.py`): user `rig360media` (or `$FOOTAGE_AUTH_USERNAME`), password from
`$FOOTAGE_AUTH_PASSWORD` or `~/.config/anchor-studio/footage-auth`. An empty password makes every login fail.
`POST /api/auth/login` returns one shared random session token, regenerated at each process start, also set as cookie
`lc_session`. Every `/api/*` path except `/api/auth/login` and `/api/health` needs `Authorization: Bearer <token>` or that cookie
(`app/main.py:23-37`). The worker imports `AUTH_USERNAME`/`AUTH_PASSWORD` from the installed backend code and logs in
for each run (`server/worker.py:506-509`). The server listens on 127.0.0.1 only.

### C.4 Data and logs

| Path (t7) | What |
|---|---|
| `~/anchor-studio/footage/data/live_cutter.db` | SQLite: `footage_projects`, `footage_segments`, `footage_keywords`, `footage_batches`, `footage_videos`, `footage_clips`, `footage_plans`, `footage_transcripts` (plus the unused tabs' tables) |
| `~/anchor-studio/footage/data/footage_clips/<project>/<clip>.mp4` | Downloaded moments (anchor formats) |
| `~/anchor-studio/footage/data/backend.log` | uvicorn + app log |
| `~/anchor-studio/footage/data/pot_server.log` | PO-token server log |
| `~/anchor-studio/rigvideo-data/footage_backend.log` | `start_backend.sh` output when the worker starts it |
| `~/anchor-studio/rigvideo-data/youtube_blocked` | Last YouTube refusal the worker saw (`blocked_check`, `server/worker.py:515-521`) |

Transcripts are cached per video in `footage_transcripts`, forever, including "no captions". A fetch that failed
(no metadata, or a caption track that would not download) is not cached, so it is tried again later.

### C.5 Endpoints RIG-Video calls

All under `http://127.0.0.1:8787/api` (`SVB`, `server/worker.py:476`).

| Call | When |
|---|---|
| `GET /health` | Is it up? |
| `POST /auth/login` `{username, password}` → `{token}` | Each worker run |
| `POST /footage/projects` `{mode: "script", title, script}` | One project per VO beat or anchor VO part; id kept in `project.json` `_svp[<part>]` |
| `GET /footage/projects/{id}` | Polled (8 to 30 s); returns segments → keywords → videos (with `relevance`, `verdict`, `moments`), `edit_plan`, `clips` |
| `POST /footage/projects/{id}/segments/{seg}/keywords` `{text}` | Our search lines |
| `POST /footage/projects/{id}/batches` `{keyword_ids}` | Run those keywords (refused with 409 while the script is still being split) |
| `POST /footage/projects/{id}/edit-plan` | Anchor formats only (`finish_section`, `server/worker.py:862`); the worker waits for it to finish but does not read the plan |
| `POST /footage/projects/{id}/clips` `{clips: [{video_id, video_title, segment_position, label, start, end}]}` | Anchor formats: download moments (≤ 600 s each, 2 at a time, 720p) |
| `GET /footage/clips/{id}/file` | Fetch a downloaded moment |

The VO-only path never downloads through the backend: the checker and `assemble916` download themselves with
`ytdlp_node.sh`. The other routers (`/api/sessions`, `/api/verify`, `/api/search`, `/api/search-results`, clips/reels,
editor, WebSocket) are upstream features for live streams, reel fact-checking and multi-source search. RIG-Video
does not call them.

### C.6 What happens per request

**1. A project is created with a script** (`api/footage.py:63-73`). The script must be at least 40 characters. A
background task runs `parse_script` (`app/footage/script_parse.py`): the script is numbered line by line and the LLM
(temperature 0.3, JSON) returns segments by first line number, each with a title, summary, `visual_needs`, and 3 to 6
**suggested keywords** that end with the current year and favour raw footage ("raw footage", "AP", "Reuters"…) over
explainers. The text of each segment is sliced from the original script, not taken from the LLM. A bare JSON list answer is
accepted (`script_parse.py:89-90`). The project then becomes `ready` (or `error`).

RIG-Video's script is always one segment: a short brief ("place: headline. Event of DATE. Wanted on screen: …. Not
wanted: maps, graphics, a presenter in a studio, footage of other incidents.") then `SEGMENT 1 — <line>`
(`server/worker.py:1184-1188`). A one-segment script keeps a small local model from mis-splitting.

**2. Keywords.** Each keyword is a YouTube query. Two options are read out of the text (`app/footage/search.py:15-34`):

| Option | Effect |
|---|---|
| `after:YYYY-MM-DD` | Data API `publishedAfter=<date>T00:00:00Z`. In the yt-dlp fallback: YouTube's results-page upload-date filter, the smallest of this week / month / year that contains the date (`_SP`). |
| `limit:N` | Videos for this keyword, 1 to 25, instead of `FOOTAGE_VIDEOS_PER_KEYWORD` |

Which keywords RIG-Video runs:

| Format | Lines (`server/worker.py`) |
|---|---|
| VO only (`search_vo`, 1168-1240) | Per beat: the writer's `search` line (else the first 60 characters of the text) + ` after:<event date − 3 d>` (event beats only) + ` limit:10` (`VO_LIMIT`). The first event beat also runs the story's event line. **No suggested keywords** (YouTube quota). If an event beat finds fewer than 2 videos, `retry_lines` respells its rare capitalised names to the closest spelling in found video titles (`difflib`, cutoff 0.8) and also tries the line without them. |
| Anchor formats (`search_section`, 712-748) | `<place> <event> <year>` (or the part's own search line) and `<event> <year>`, each with ` after:<event date − 3 d>`, plus the first 2 suggested keywords that carry no other year. |

**3. A batch** (`app/footage/runner.py:69-130`) queues the keywords. A worker per project takes 3 keywords at a time (a "wave").
Re-running a keyword replaces its earlier videos.

**4. Per keyword** (`_process_keyword`, `runner.py:138-203`):

1. **Search** (`search_videos`): the YouTube Data API `search` (`part=snippet, type=video`), 15 s timeout. On any error, or
   with no key: `yt-dlp --flat-playlist -J` (`ytsearchN:` or the filtered results page).
2. The found videos are stored at once with relevance pending (−1).
3. For each video in turn: **transcript**, then **moments**.
4. One video failing gets relevance 0 and the error as its verdict; a search failing marks the keyword `error`.

**5. Transcript** (`app/footage/transcript.py`), first that works:

1. `yt-dlp -J --skip-download` for duration, channel, chapters and caption tracks. yt-dlp's default clients are used: forcing
   the web client gave empty captions (`transcript.py:273-274`).
2. **Captions**, one English track in this order: YouTube's own speech recognition (`en-orig`, `en-*-orig`), human
   captions, then YouTube's machine translation. The `srv1` format is used. Downloads are one at a time, at least 3 s apart, with a
   Chrome-like TLS fingerprint (`curl_cffi`) when installed. A 429 pauses all caption downloads for 30 minutes
   (`_download_caption`, `transcript.py:242-266`). The PO-token provider plugin in the venv adds YouTube's token to caption URLs
   (`start_backend.sh` comment and `transcript.py:23-26`).
3. **Invidious** (when the caption download failed): up to 3 healthy public servers from `api.invidious.io` (list
   refreshed every 6 h; a failing server rests 30 min), English, auto track first, WebVTT.
4. **Whisper** (no lines yet): `yt-dlp` best audio (2 min download limit) → ffmpeg to 16 kHz → faster-whisper `small`
   (GPU `int8_float16` if it loads, else CPU `int8`), `task="translate"` (to English), VAD on, beam 1, one at a time.
   Cues are merged into lines of about 15 s.

**6. Moments and relevance** (`match_video`, `app/footage/matcher.py:128-177`): one LLM call per video (temperature 0.2,
JSON) with today's date, the segment, the query, the video's title, channel, duration, description (600 characters),
chapters (40) and transcript. A transcript longer than 8000 characters keeps only the lines sharing the most words
with the segment and query (± 1 line), with "…" for gaps. With a local LLM, times are written as plain seconds (`_fmt_ts`): small
models misread "3:30". The answer:

- `relevance` 0 to 100;
- `verdict`: 1 to 2 sentences. It must say plainly when the video is a movie, re-enactment, AI-generated or colourised, and then cap relevance at 40.
- up to 4 `moments`, each `{start, end, label, description, fit, score}`, 10 to 120 s. Times are clamped to the duration.
- Without a transcript, the moments are marked `estimated`.

RIG-Video's `map_found` (`server/worker.py:528-566`) keeps videos with relevance ≥ 10, best first, one entry per
YouTube id, and stores them in `visuals[<part>].found`. The checker's `fake()` reads the same `verdict`.

**7. LLM routing** (`app/core/groq_pool.py`): with `LLM_BASE_URL` set, every call goes to the local server (t8
`:11610`, model `qwen3-vl-q4`, 600 s timeout; Groq-only arguments such as `reasoning_effort` are dropped). Only a
connection error or timeout sends that call to Groq. Groq rotates keys: a rate-limited key moves on to the next, and after all keys
it waits out the stated retry time if that is ≤ 10 minutes.

**8. Edit plan** (anchor formats ask for it): one LLM call per segment splits the script into anchor/clip beats with
moments of score ≥ 40 (`app/footage/edit_plan.py`).

**9. Clips** (anchor formats): `yt-dlp -f "bv*[height<=720]+ba/b[height<=720]/bv*+ba/b" --download-sections
*start-end --force-keyframes-at-cuts`, 600 s limit, 2 at a time (`app/footage/clips.py`). RIG-Video then cuts web
copies and runs `clean_shots.py` (C.8).

A backend restart marks every running keyword, plan, clip and project as `error` ("Interrupted by a server restart").
The worker's resume (`add`, `server/worker.py:1194-1205`) queues `error` keywords again.

### C.7 YouTube access

| Piece | Where | What |
|---|---|---|
| `ytdlp_node.sh` | `footage/ytdlp_node.sh` → t7 `~/anchor-studio/repos/social_verifier/ytdlp_node.sh` | The yt-dlp wrapper for every RIG-Video and backend download. If `curl -x socks5h://127.0.0.1:18091 https://www.youtube.com/generate_204` returns 204 within 4 s, it adds `--proxy socks5h://127.0.0.1:18091`; otherwise it goes direct. It always passes `--js-runtimes node:~/.nvm/versions/node/v22.23.5/bin/node` and runs the venv's yt-dlp. |
| WARP proxy | `warp-proxy.service` (D.1) | Userspace wireproxy SOCKS5 on 127.0.0.1:18091 through Cloudflare WARP. The office IP gets `LOGIN_REQUIRED` from YouTube. |
| Data API | `YOUTUBE_API_KEY` in `footage.env` | Searches (the API is not blocked; 100 quota units per search) |
| PO-token server | bgutil on `127.0.0.1:4416`, Node 20 | Started by `start_backend.sh` |
| Captions / Invidious / whisper | C.6 step 5 | |

### C.8 `clean_shots.py`

**`clean_shots.py`** (137 lines; anchor formats, called by `worker.cut`, `server/worker.py:651`, with `TOOLS_PY`):
`clean_shots.py <run dir> <out dir>` reads `<run dir>/clips.json`.

- Shots: histogram cuts as in A.5. Long shots are split into equal pieces of at most 8 s; each piece must be ≥ 1.5 s.
- Each piece is labelled by **SigLIP-2** zero-shot on 3 frames, against 4 "clean" labels and 6 reject labels
  (presenter, graphic, map, vertical, call, website). The weakest frame's clean share must be ≥ 0.5.
- Other tests: centre text (RapidOCR on the centre 76 %) ≤ 3 %, no side bars (Laplacian variance of the outer 14 % strips < 0.15 × the centre), and not a
  re-upload of a kept shot from another clip of the same part (histogram correlation > 0.97).
- If `~/e2e/no_siglip` exists, the SigLIP check is skipped.
- Writes `shots.json`, `kept.jpg` and `rejected.jpg`.
- The worker maps the reasons to site flags (`FLAG_OF`) and makes a treatment preview: `crop` (90 % centre) or `blur_fill` for vertical clips.

---

## D. Machine files (`hosts/`)

All services are `systemd --user` units. "Boot" means the unit is enabled (`WantedBy=default.target`) and starts with
the user manager, which runs at boot because linger is on (HANDOFF section 12).

### D.1 trijya-7

| Repo file | Installed at | Starts | Port | Boot |
|---|---|---|---|---|
| `hosts/t7/systemd/rigvideo-api.service` | `~/.config/systemd/user/` | `~/anchor-studio/rigvideo-api-venv/bin/uvicorn app:app --host 100.72.225.89 --port 8770` in `~/anchor-studio/rigvideo/server` | 8770 (Tailscale address) | yes |
| `hosts/t7/systemd/vo-vision.service` | same | `~/vo_check/vo_vision_serve.sh` | 11620 | yes |
| `hosts/t7/vo_vision_serve.sh` | `~/vo_check/vo_vision_serve.sh` | (the script the unit runs) | | |
| `hosts/t7/systemd/warp-proxy.service` | same | `/home/trijya-7/warp/wireproxy -c /home/trijya-7/warp/wireproxy.conf` | 127.0.0.1:18091 | yes |
| `hosts/t7/systemd/actions-runner.service` | same | `~/actions-runner/run.sh` | — | yes |
| `hosts/t7/requirements/{api,tools,vertical,footage}.txt` | not installed | exact `pip freeze` of the four venvs | | |

**`rigvideo-api.service`**: `EnvironmentFile=~/.config/rigvideo/api.env`, `STUDIO_DATA=~/anchor-studio/rigvideo-data`,
`PYTHONUNBUFFERED=1`, and `LLM_PROVIDERS` = t3 writer (`http://100.99.155.88:8780/v1`, key `RIGVIDEO_WRITER_KEY`, model
`writer`, 900 s timeout) then Groq (`openai/gpt-oss-120b`, key `GROQ_API_KEY`, `max_budget` 7800). `KillMode=process`
so a restart does not kill the job processes it started. `Restart=always`, 5 s.

**`vo_vision_serve.sh`**: llama.cpp `llama-server` from `~/vo_check/src/build/bin` (built at 0fb8f15 for sm_89),
`Qwen3VL-8B-Instruct-Q8_0.gguf` + `mmproj-Qwen3VL-8B-Instruct-F16.gguf` from `~/vo_check/models`, alias `vlm`,
`--host 100.72.225.89 --port 11620 -ngl 99 -fa on -np 1 -c 32768 -ctk q8_0 -ctv q8_0 --jinja --image-min-tokens 1024
-b 2048 -ub 512 --sleep-idle-seconds 600 --no-webui`. About 12.5 GB VRAM awake; it sleeps after 10 idle minutes and
wakes on the next request (`/health` then answers 503 while loading). `Restart=always`, 5 s.

**`warp-proxy.service`**: the paths are written for the `trijya-7` user. `Restart=always`, 5 s.

**`actions-runner.service`**: the GitHub runner in `~/actions-runner` (labels `self-hosted, rig-video`). `Restart=always`, 10 s.

Requirements files, key pins:

| File | Venv | Key packages |
|---|---|---|
| `api.txt` (14) | `~/anchor-studio/rigvideo-api-venv` | fastapi 0.115.14, uvicorn 0.32.1 |
| `tools.txt` (85) | `~/.cache/anchor-tools` (`TOOLS_PY`) | torch 2.14.1+cpu, transformers 5.19.0, faster-whisper 1.2.1, rapidocr-onnxruntime 1.4.4, soundfile, opencv |
| `vertical.txt` (95) | `~/anchor-studio/vertical/.venv` | torch 2.11.0+cu128, transformers 5.23.0, rfdetr 1.12.1, transnetv2-pytorch 1.0.5, rapidocr 3.10.0, onnxruntime-gpu 1.32.0 |
| `footage.txt` (75) | `~/anchor-studio/repos/social_verifier/.venv` | yt-dlp 2026.10.21, yt-dlp-ejs, bgutil-ytdlp-pot-provider 2.0.2, curl-cffi, faster-whisper 1.2.1, groq, openai, fastapi 0.162.0 |

### D.2 trijya-3

| Repo file | Installed at | What |
|---|---|---|
| `hosts/t3/systemd/rigvideo-writer.service` | `~/.config/systemd/user/` | llama.cpp server for the writer |
| `hosts/t3/gpu.sh` | `~/rigvideo/llm/gpu.sh` | Writer / voice GPU switch |
| `hosts/t3/setup_writer.sh` | not installed; run by hand | Rebuilds the writer toolchain |
| `hosts/t3/setup_voice.sh` | not installed; run by hand | Rebuilds Chatterbox and ffmpeg |
| `hosts/t3/chatterbox-requirements.txt` | not installed | Exact package list of the Chatterbox venv (torch 2.6.0+cu124, chatterbox-tts 0.1.7) |

**`rigvideo-writer.service`**: `~/rigvideo/llm/llama.cpp/build/bin/llama-server -m
models/gemma-4-26B-A4B-it-UD-Q4_K_XL.gguf --alias writer --fit on -fitt 2560 -t 12 -fa on -c 32768 -np 1 -b 2048 -ub
2048 --jinja --reasoning off --host 100.99.155.88 --port 8780 --api-key-file ~/rigvideo/llm/api.key`. Port 8780 on the
Tailscale address. `Restart=always`, 10 s. It has an `[Install]` section, but it is started on demand by `gpu.sh writer` and stopped by
`gpu.sh voice`. `deploy.sh` does not enable it.

**`gpu.sh writer|voice`** (called from t7 over ssh, under t7's lock):

- `writer`: starts the unit if it is not active, then up to 200 tries, 3 s apart, sends a one-token chat request with the API key.
  It exits 0 on the first answer with `choices`. It exits 1 if the unit dies, or "not ready after 10 min".
- `voice`: stops the unit and waits until no `llama-server … --port 8780` process remains.

**`setup_writer.sh`**: everything under `~/rigvideo/llm`, log `setup.log`.

1. micromamba and a `cuda` env (CUDA 12.8.1 nvcc, cuBLAS, cmake, ninja, gcc 13).
2. Downloads, in parallel: `gemma-4-26B-A4B-it-UD-Q4_K_XL.gguf` and `Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf` from Hugging Face.
3. Clones llama.cpp (depth 1) and builds `llama-server`, `llama-bench` and `llama-cli` with CUDA for sm 86 and 89.

**`setup_voice.sh`**:

1. A uv venv (Python 3.12) in `~/anchor-studio/repos/chatterbox`, installed from `~/anchor-studio/chatterbox.txt` with
   `--no-deps` and the cu124 torch index.
2. The Chatterbox weights (`t3_cfg`, `s3gen`, `ve`, `conds.pt`, `tokenizer.json`) into `~/anchor-studio/models/chatterbox`.
3. The BtbN ffmpeg n8.1 GPL shared build into `~/anchor-studio/repos/ffmpeg-shared/current`; it reports its Rubber Band filter count.

### D.3 trijya-8

| Repo file | Installed at | Starts | Port | Boot |
|---|---|---|---|---|
| `hosts/t8/systemd/vision-llm.service` | `~/.config/systemd/user/` | `~/vision/vision_serve.sh` | 11610 | yes |
| `hosts/t8/vision/vision_serve.sh` | `~/vision/vision_serve.sh` | | | |
| `hosts/t8/vision/deploy_recv.sh` | `~/vision/deploy_recv.sh` | forced command of the deploy key | | |

**`vision_serve.sh`**: `~/vision/llamacpp/llama-server` (llama.cpp 0fb8f15 with its CUDA libraries, `LD_LIBRARY_PATH`
= that folder). The weights are Ollama's Qwen3-VL 8B Q4_K_M blob and its mmproj blob (by sha256) in `~/vision/models/blobs`.
Flags: alias `qwen3-vl-q4`, `--host 100.95.0.11 --port 11610 -ngl 99 -fa on -np 4 -c 24576 --jinja -kvu -b 2048 -ub 512
--cache-reuse 256 --image-min-tokens 1024 --sleep-idle-seconds 900 --no-webui`: 4 requests at once on a shared KV
cache, asleep after 15 idle minutes. Used by the footage backend for every text call, and by the checker and crop check
when t7's `:11620` fails. `Restart=always`, 5 s.

**`deploy_recv.sh`**: the only thing the deploy key may run (`command=…,restrict` in `authorized_keys`).

1. It accepts only `SSH_ORIGINAL_COMMAND` = `deploy`.
2. It untars stdin (the repo's `hosts/t8/vision` and `hosts/t8/systemd`), rsyncs `vision/` into `~/vision/` and `systemd/` into `~/.config/systemd/user/`.
3. Then `daemon-reload` and `enable vision-llm`. It restarts `vision-llm` only if `vision_serve.sh` changed or the unit is not active, and prints `t8 ok`.

---

## E. Deploy, CI and doctor

The release flow is in HANDOFF section 13. This section lists each step exactly.

### E.1 `.github/workflows/ci.yml` (`check`)

- Triggers: every `push` and `pull_request`. Concurrency group `check-<ref>`, cancels the older run.
- Runs only for pushes and for PRs whose head repo is this repo; fork PRs never run on the office runner.
- `runs-on: [self-hosted, rig-video]`, 30 min limit. Steps: checkout, `deploy/check.sh`.

### E.2 `deploy/check.sh` (the gate)

Runs in the checkout on t7. Interpreters: `API_PY` (`~/anchor-studio/rigvideo-api-venv/bin/python`), `TOOLS_PY`
(`~/.cache/anchor-tools/bin/python`), `NODE_BIN` (`~/.nvm/versions/node/v22.23.5/bin`); each can be overridden by env.
Every step runs; any failure makes the final result `CHECK FAILED` and exit 1.

| Step | Exactly |
|---|---|
| secrets | `git ls-files` (except `deploy/check.sh` itself) searched for the shapes of real keys: Groq, OpenAI-style, Google API and OAuth tokens, GitHub tokens, Slack tokens, private key blocks, database URLs with a password, AWS keys, Hugging Face tokens (the exact patterns are in `deploy/check.sh`) |
| python compiles | `TOOLS_PY -m py_compile` on every tracked `.py` |
| shell syntax | `bash -n` on every tracked `.sh` |
| server self-tests | with `RIGVIDEO_APP=<checkout>/studio-app`, in `server/`: every `test_*.py` with `API_PY`, `store.py` with `API_PY`, `worker.py selftest` with `TOOLS_PY`. Each must print a last line containing the word `ok`. |
| site | in `web/` with Node 22: `npm ci`, `npm run build` (type-check + Vite build into `web/dist`, which `deploy.sh` needs) |

### E.3 `.github/workflows/release.yml` (`release`)

- Triggers: a published GitHub Release, or *Run workflow* with a `tag` (rollback or re-install).
- Concurrency group `deploy`, never cancelled. 40 min limit, same runner.

1. Checkout the tag (full history).
2. **only releases of main**: `git merge-base --is-ancestor $TAG origin/main`, else fail.
3. **check**: `deploy/check.sh`.
4. **install**: `deploy/deploy.sh $TAG`.
5. **roll back** (only if install failed):
   - read `~/.local/state/rig-video/last-good`; if it is missing or equals the tag, fail with "restore a backup by hand";
   - otherwise make a git worktree of that tag in `$RUNNER_TEMP/rollback`, run `check.sh` and `deploy.sh <last good>` there;
   - mark the run failed ("<tag> failed its health check; <prev> is live again").

### E.4 `deploy/deploy.sh <version>`

Runs on t7. `VER` defaults to `git describe --tags --always --dirty`. File copies use
`rsync -a --itemize-changes`, excluding `__pycache__` and `*.pyc`; only the site copy uses `--delete`.

| # | Step | Detail |
|---|---|---|
| 0 | Preconditions | `web/dist` exists (else "run deploy/check.sh first", exit 2); `~/.config/anchor-studio/footage-auth` is non-empty (exit 2) |
| 1 | Backup | `~/.local/state/rig-video/backups/<UTC time>-before-<VER>.tgz` of the current t7 code: `rigvideo/{server,dist,VERSION}`, `studio-app/pipeline`, `registry.json`, `lt_remotion/src`, `vertical/*.py`, the footage backend `app/`, `start_backend.sh` and `ytdlp_node.sh` paths under `social_verifier/`, `vo_check/vo_vision_serve.sh`, and the three unit files. Missing paths are ignored. Only the newest 20 are kept. |
| 2 | t3 | Over ssh with `~/.ssh/to_trijya3`: `hosts/t3/gpu.sh` → `~/rigvideo/llm/gpu.sh`; `hosts/t3/systemd/` → `~/.config/systemd/user/`; `chatterbox_takes.py` → `~/anchor-studio/voice_lab/`; `systemctl --user daemon-reload`. Nothing is restarted. |
| 3 | t8 | `tar` of `hosts/t8/{vision,systemd}` piped to `ssh -i ~/.ssh/rigvideo_deploy_t8 trijya-8@100.95.0.11 deploy` (D.3) |
| 4 | t7 files | `server/` → `~/anchor-studio/rigvideo/server/`; `web/dist/` → `rigvideo/dist/` (with delete); `studio-app/` → `~/anchor-studio/studio-app/`; `vertical/` → `~/anchor-studio/vertical/`; `footage/backend/` → `repos/social_verifier/backend/` and `footage/ytdlp_node.sh` → `repos/social_verifier/` (their changes are kept as `FOOT`); `hosts/t7/vo_vision_serve.sh` → `~/vo_check/` (changes kept as `VIS`); `hosts/t7/systemd/` → `~/.config/systemd/user/`; `VER` → `rigvideo/VERSION` |
| 5 | Units | `daemon-reload`; `enable warp-proxy vo-vision rigvideo-api actions-runner` (retried without the runner if that fails); start `warp-proxy` if inactive; restart `vo-vision` if its script changed, else start it if inactive |
| 6 | Footage backend | If `FOOT` changed and `:8787/api/health` answers, run `start_backend.sh` again (a failure only logs; the worker starts it when needed) |
| 7 | API | `systemctl --user restart rigvideo-api` (running jobs survive, `KillMode=process`) |
| 8 | Health | Up to 30 tries, 2 s apart: `http://100.72.225.89:8770/api/health` must contain `"version":"<VER>"` and `"monitor":true`. On success: write `VER` to `~/.local/state/rig-video/last-good`, print "release … is live", run `ops/doctor.py` (its failure is only reported), exit 0. Otherwise: print the last 15 journal lines, exit 1. |

Never touched by `deploy.sh`: media, models, venvs, `node_modules`, secrets, `hosts/t3/setup_*.sh`, the requirements
files, the t3 writer's enablement. Files removed from the repo stay on the machines (except in `dist/`).

### E.5 `.github/workflows/doctor.yml` and `ops/doctor.py`

The workflow runs `python3 ops/doctor.py` on the same runner at cron `0 2 * * *` (07:30 IST) and `0 18 * * *`
(23:30 IST), or by hand (*Run workflow*). 5 min limit.

`ops/doctor.py` (69 lines) prints one line per check (`OK`, `FAIL` or `WARN`), then `READY` or `NOT READY: …`, and
exits 1 on any failure:

| Check | Pass when |
|---|---|
| `t7 rigvideo-api`, `warp-proxy`, `vo-vision`, `actions-runner` | `is-enabled` = `enabled` **and** `is-active` = `active` |
| API answers | `GET http://100.72.225.89:8770/api/health` = 200 (prints the version) |
| API job loop alive | its JSON has `monitor` true |
| daily auto-start on | `~/.config/rigvideo/api.env` has `RIGVIDEO_DAILY_AUTO=1` |
| YouTube via WARP | `curl -x socks5h://127.0.0.1:18091 https://www.youtube.com/generate_204` = 204 (8 s) |
| t7 clip-checker model :11620 | `/health` = 200 or 503 (asleep or loading) |
| t8 vision model :11610 | `/health` = 200 or 503 |
| t3 writer + voice box reachable | over ssh (`~/.ssh/to_trijya3`, 10 s connect): `~/rigvideo/llm/gpu.sh` and the Chatterbox venv's python are executable |
| t7 data disk free | more than 40 GB free where `STUDIO_DATA` lives |
| t7 GPU | `nvidia-smi` answers (warning only; prints temperature and memory) |

### E.6 `config/env.example.md`

Names only, no values. It is the list behind HANDOFF section 11. It adds three items that the handoff table does not show:
`RIG_GATEWAY_KEY` in `llm.env`; and `RIGVIDEO_NO_SELECTION=1` for test instances (no daily picks).
