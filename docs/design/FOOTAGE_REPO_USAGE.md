# Footage repo (social_verifier / "Live Cutter"): tested on a real article, and how to use it in our system (2026-10-25)

Repo: github.com/Daksh288948921904/social_verifier (our org's own; licence is not a concern — user, 2026-10-25).
Tested at commit 5d2de99 on story `2c1cc925` (Russia: 616 drones, 23-24 Oct 2026) with our 5-beat script, driven
through its own backend API exactly as its **Footage** tab does (create project → segments/keywords → batches →
edit plan → clip downloads). Supersedes the import-the-modules approach (`pipeline/tools/footage/find_clips.py`).

## What it is
A FastAPI + React newsroom app with four tabs: Sessions (cut a live stream into story clips), Verifier (fact-check
reels), **Search** (one keyword across YouTube / web / Instagram Reels; needs `YOUTUBE_API_KEY`, `GOOGLE_CSE_*`) and
**Footage** (script → footage per segment). For us the Footage tab is the useful part; its API:
`POST /api/footage/projects {mode:"script", script}` → `GET …/projects/{id}` (segments + suggested keywords) →
`POST …/segments/{sid}/keywords {text}` (add our own) → `POST …/batches {keyword_ids}` → poll → `POST …/edit-plan` →
`POST …/clips {clips:[{video_id, start, end, …}]}` → files in `DATA_DIR/footage_clips/<project>/`.

## Three runs, what happened
| Run | Where | Input | Videos | With captions | Clips |
|---|---|---|---|---|---|
| 1 | trijya-7 | plain script | 25 | **0** (YouTube 429 on every caption) | 0 (ffmpeg crash) |
| 2 | Mac | plain script | 25 | 16 | 3/3 downloaded |
| 3 | Mac | **dateline + `SEGMENT n —` markers + our dated keywords** | 114 (104 unique) | **5** (429 after ~25 videos) | 18/18 downloaded |

**Findings:**
1. **Where to run it.** On trijya-7 YouTube refuses the repo's caption fetch (429 every time) and the static ffmpeg
   segfaults on network input, so clip downloads fail. On the Mac (Homebrew ffmpeg/yt-dlp/deno, as its README
   expects) everything works.
2. **Captions are the bottleneck.** Captions drive its timestamps. YouTube rate-limits caption downloads per network
   address: run 2's 25 videos mostly worked; in run 3 it refused 105 of 114 after the first ~25, and then even plain
   yt-dlp subtitle downloads were refused. Without captions it guesses ("≈ estimated") — often the whole video
   (0-219 s). Video downloads were never refused.
3. **Give it a dateline and segment markers.** A plain script gave one segment for 5 beats and keywords with the wrong
   year ("2024"). With a first line "MOSCOW, 24 October 2026 - …" and `SEGMENT n —` before each beat it made one
   segment per beat (plus one for the dateline) and every keyword said 2026.
4. **It finds the right story.** Run 3's top picks per beat were on-topic: the BBC report of the Moscow attack,
   Sobyanin's statement, "6 nights dark: how drones shut down Moscow's airports", red departure boards, airport fires.
   Kanal13's "630 drones toward Moscow, 163 neutralised" is this very night.
5. **But its clips are TV packages, not clean pictures.** Of 18 downloaded clips almost all are other channels'
   reports: their anchors, BREAKING NEWS panels, tickers, QR codes, logos, vertical phone video with side bars, a
   DW talk show. Clean seconds exist inside them (departure board, Moscow skyline, Kremlin, airport fire footage) but
   the repo cannot tell them apart: it never looks at the pictures. One "Moscow airport" pick showed an Indian (IndiGo)
   plane.
6. **No dates without a YouTube API key.** The yt-dlp search fallback returns no upload date, so old footage cannot be
   filtered (an AP 1994 Sheremetyevo fire came back in run 1). With `YOUTUBE_API_KEY` it gets `published_at`.
7. **Edit plan works as a draft.** Per segment it chose a clip or anchor beat with a director's note ("VO over red
   departure boards and staff directing passengers to safe zones"), estimated at 2.5 words/s.
8. **Cost.** Each video is one LLM call (~3-5k tokens); run 3 (114 videos) rotated through all 5 Groq keys 185 times.

## How to use it in our system (Footage step of `STORY_VIDEO_SYSTEM_DESIGN.md`)
1. **Run its backend on the Mac** (or any machine YouTube does not block), started by our app; Groq keys passed in at
   launch from `llm.env` (not written to disk). Drive the API as above. Do not import its modules.
2. **Input** = our script with a dateline and one `SEGMENT n —` per beat. Run its suggested keywords **plus one dated
   keyword of ours per segment** (from the article: place + event + date).
3. **Keep the volume under YouTube's caption limit**: `FOOTAGE_VIDEOS_PER_KEYWORD=3`, 2-3 keywords per segment
   (≈ 30-45 videos per story). For more, either give it a logged-in YouTube cookies file
   (`YTDLP_YOUTUBE_COOKIES_FILE`, its documented fix) or add our own timestamp step: download each candidate's audio
   and transcribe it with Whisper (exact times, any language; video downloads are not throttled).
4. **Ask for `YOUTUBE_API_KEY` (and `GOOGLE_CSE_*` for the Search tab)** from whoever runs the app for the org, so
   upload dates come back and old footage can be dropped.
5. **After download, our shot-level cleaning** (the repo's output is the input to this): split each clip into shots;
   drop shots with another channel's anchor/presenter, studio, BREAKING/ticker panels, QR codes, logos in corners,
   burned-in text, vertical/pillarboxed video; describe each kept shot with a vision model and match it to its beat;
   keep only clean seconds (typically 2-6 s per shot).
6. **Use its edit plan as the first draft** of our EDIT step, then re-time it from the voice master.
7. **The user reviews** the kept shots in the app's Footage step (as designed) before the script is finalised.

## Files
Test drivers and results (scratch, not in the repo): `sv_drive.py`, `sv_drive2.py`, `sv_run2/`, `sv_run3/` (project
JSON with every video, verdict, moment and the edit plan; contact sheets of the 18 clips).
