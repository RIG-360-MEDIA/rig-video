# Reference: the anchor render chain and the shared pipeline code

> `file:line` references point at the code as of 2026-11-25; after later changes, search by the name given next to them.

This chapter documents the code under `studio-app/` that makes **anchor videos** (formats `anchor_vo` and
`anchor_only`), plus the shared pipeline modules that other steps also use: story selection, story pictures, YouTube
publishing, the anchor registry and the voice tool.

It assumes you have read `docs/HANDOFF.md`. The overview of an anchor render is in HANDOFF section 5 ("How an anchor
video is rendered"); the daily selection is section 4, step 0; posting is section 4, steps 8 and 9; anchors are in
section 7; the installs this code needs (ComfyUI, models, Node, ffmpeg) are in section 10. This chapter does not repeat
those; it goes one level deeper, file by file.

All paths are relative to the repository root unless they start with `~` (a home folder on a machine). On t7 the
`studio-app/` folder is `~/anchor-studio/studio-app/`. References look like `file.py:123`. All times are IST; note that
`select_stories.py` writes UTC timestamps.

`server/worker.py` is referred to by function name (for example `worker.step_assemble`), not by line number, because
its line numbers change often. Other files are referred to as `file.py:line`.

---

## Contents

1. [File map](#1-file-map)
2. [The call chain from the worker](#2-the-call-chain-from-the-worker)
3. [Frame and audio maths](#3-frame-and-audio-maths)
4. [File formats in a render folder](#4-file-formats-in-a-render-folder)
5. [Building the ComfyUI jobs: build_main.py and build_st.py](#5-building-the-comfyui-jobs-build_mainpy-and-build_stpy)
6. [The workflow templates](#6-the-workflow-templates)
7. [ComfyUI: client, custom nodes, required input files](#7-comfyui-client-custom-nodes-required-input-files)
8. [The GPU run and the tenant pause/restore protocol](#8-the-gpu-run-and-the-tenant-pauserestore-protocol)
9. [Lip-sync check](#9-lip-sync-check)
10. [Assembly](#10-assembly)
11. [lt_remotion: the TV graphics package](#11-lt_remotion-the-tv-graphics-package)
12. [Anchor registry and adding an anchor](#12-anchor-registry-and-adding-an-anchor)
13. [chatterbox_takes.py: the voice tool](#13-chatterbox_takespy-the-voice-tool)
14. [select_stories.py: the daily selection](#14-select_storiespy-the-daily-selection)
15. [assets.py: story pictures and Ken Burns](#15-assetspy-story-pictures-and-ken-burns)
16. [publish.py and youtube_auth.py: YouTube](#16-publishpy-and-youtube_authpy-youtube)
17. [common.py](#17-commonpy)
18. [Code present but not on a RIG-Video path](#18-code-present-but-not-on-a-rig-video-path)

---

## 1. File map

| File | Role | Called by | Runs on |
|---|---|---|---|
| `server/worker.py` (`step_render`, `prepare_render`, `gpu_run`, `lipsync`, `step_assemble`) | Drives the anchor render end to end | job loop (`worker.py render <id>`) | t7 |
| `studio-app/pipeline/tools/sourcetrack/make_appearances.py` | Time-fits each anchor part's chosen take to whole 328-frame shots; writes per-appearance voice masters, `shots.json`, `story.json` | `prepare_render` over ssh | **t3** (chatterbox venv; its ffmpeg has Rubber Band) |
| `studio-app/pipeline/tools/sourcetrack/make_master.py` | Older per-beat master builder. Only its constants and `trimmed()` are imported by `make_appearances.py` | `make_appearances.py` (import) | t3 |
| `studio-app/pipeline/tools/sourcetrack/build_st.py` | Builds the two ComfyUI jobs per appearance (seed + chain) with the audio locked to the masters | `prepare_render` | t7 (tools venv) |
| `studio-app/pipeline/build_main.py` | The locked recipe builder ("t8k"): prompts, identity pin, seeds, speed nodes. `build_st.py` calls it and then rewires its output | `build_st.py` (import) | t7 |
| `studio-app/pipeline/templates/seed_set7_fbc.json`, `chain_prod_v2_canon.json` | ComfyUI API graphs the builder starts from | `build_main.py` | — |
| `studio-app/pipeline/tools/sourcetrack/run_multi.py` | One ComfyUI session for all appearances; frees the GPU first and restores it after | `gpu_run` | t7 |
| `studio-app/pipeline/tools/new_anchors/runlib.py` | `ensure_gpu()` (free the GPU) and `log()` | `run_multi.py` | t7 |
| `studio-app/pipeline/orchestrator/comfy.py` | ComfyUI start / submit / wait / kill | `run_multi.py`, `runlib.py` | t7 |
| `studio-app/pipeline/orchestrator/gpu.py` | Pause other teams' GPU services and restore them (also a CLI for the restore timer) | `runlib.py`, `run_multi.py`, systemd timer | t7 |
| `studio-app/pipeline/comfy_nodes/` | Our ComfyUI custom nodes + a saved patch to a third-party node | ComfyUI | t7 |
| `studio-app/pipeline/tools/sourcetrack/lipsync_check.py` | Mouth-vs-voice lag measurement | `worker.lipsync` | t7 |
| `studio-app/pipeline/tools/sourcetrack/assemble_story.py` | Joins anchor appearances, VO parts and the outro into `final.mp4` | `step_assemble` | t7 |
| `studio-app/pipeline/tools/sourcetrack/assemble_novo.py`, `assemble_hybrid.py` | Helpers imported by `assemble_story.py` (`graphics`, `frames_of`, `ff`, `CONFORM`, constants) | `assemble_story.py` (import) | t7 |
| `studio-app/pipeline/tools/colorlock.py` | Per-shot brightness/saturation match inside one appearance | `assemble_story.py` | t7 |
| `studio-app/pipeline/tools/wall_comp.py` | Puts footage onto the studio video wall behind the anchor | `assemble_story.py` | t7 |
| `studio-app/pipeline/orchestrator/post.py` | Wall-quad check (`refine_quad`), graphics story builder (`lt_story`), Node and outro paths | `assemble_story.py` (via helpers) | t7 |
| `studio-app/lt_remotion/` | Remotion (React) TV graphics rendered as an alpha overlay and composited with ffmpeg | `assemble_novo.graphics` | t7 (Node) |
| `studio-app/anchor_registry/registry.json` | The anchors | `build_main.py`, `worker.py`, `server/app.py` | — |
| `studio-app/pipeline/tools/voice_lab/chatterbox_takes.py` | Chatterbox TTS takes from a config file | `worker.make_takes` over ssh | **t3** |
| `studio-app/pipeline/orchestrator/select_stories.py` | The daily pick of 10 + 10 hard-news stories from the RIG DB | `worker.step_selection` | t7 (LLM on t3) |
| `studio-app/pipeline/orchestrator/assets.py` | Story picture search + filters; Ken Burns stills | `worker.story_photos`, `worker.placed_items`/`auto_items`, `vo_pick.py` | t7 |
| `studio-app/pipeline/orchestrator/publish.py` | YouTube upload, playlists, text update, approve | `worker.step_post` | t7 |
| `studio-app/pipeline/orchestrator/youtube_auth.py` | One-time OAuth + playlist creation | a person, by hand | any machine with a browser |
| `studio-app/pipeline/orchestrator/common.py` | Paths, IST clock, `load_env()` | most of the above | t7 |

---

## 2. The call chain from the worker

`worker.step_render` is the entry for both anchor formats. VO-only stories branch to
`render_vo` on its first line and never reach the code below.

```mermaid
sequenceDiagram
  participant W as worker.py (t7)
  participant T3 as t3 (ssh)
  participant BS as build_st.py
  participant RM as run_multi.py
  participant C as ComfyUI :8199
  participant AS as assemble_story.py
  W->>T3: copy make_appearances.py + make_master.py, script.json
  W->>T3: make_appearances.py <remote>/render <anchor> script.json a1=<take> a2=<take> ...
  T3-->>W: render/ (appearances.json, a1/ a2/ ... masters, shots.json, story.json)
  loop each anchor part
    W->>BS: build_st.py a1/story.json a1 a1 --turbo-seed
    BS-->>W: render_a1_st_seed.json, render_a1_st_chain.json (+ run.txt)
  end
  W->>W: check ComfyUI input/ has every picture the jobs load
  W->>RM: run_multi.py render/ a1 a2 ...   (holds search.lock exclusive)
  RM->>RM: ensure_gpu: pause tenants, schedule restore timer
  RM->>C: start, then per part: seed job, chain job (if >1 shot)
  RM->>C: kill; gpu.restore
  W->>W: lipsync_check.py per part (lag > 2 frames -> render "held")
  W->>W: step_assemble: pictures, walls, voices, edl.json
  W->>AS: assemble_story.py render/assembly "a1 v1 a2 v2 ..."
  AS-->>W: final.mp4 -> media/final.mp4 + poster.jpg
```

### Step by step

| # | Code | What happens | Inputs | Outputs |
|---|---|---|---|---|
| 1 | `step_render` | Sets `render.state = rendering`, runs steps 2 to 7, and sets `render.state = assembling` (92 %) before step 7. | `project.json` | — |
| 2 | `prepare_render` | Writes `media/render-in/script.json` (`{"scripts": {partId: spoken text}}`; `spoken()` writes numbers out as words). Copies it and the two scripts to t3, then runs `make_appearances.py` there with each anchor part's **picked take** (its path on t3, `take["remote"]`). Copies the whole remote `render/` folder back to `projects/<id>/render/` (an old one is deleted first). | picked takes on t3 | `render/appearances.json`, `render/<part>/…` |
| 3 | `prepare_render` | For each anchor part runs `build_st.py <part>/story.json <part> <part> --turbo-seed` and writes `<part>/run.txt` = `story["run"] + "_st"` (for example `render_a1_st`). | `story.json`, `shots.json` | `<run>_seed.json`, `<run>_chain.json` |
| 4 | `gpu_run` | Reads every job graph and lists the string inputs ending `.png/.jpg/.wav/.mp4` that do **not** start with `render_` (per-run files are copied later). If any is missing from `~/anchor-studio/repos/ComfyUI-v038/input/`, it fails with "This anchor's pictures are missing on the render machine". Then it waits for `search.lock` **exclusively** (no footage search or clip check runs beside a render) and runs `run_multi.py`. | job graphs | — |
| 5 | `_gpu_run` | Streams `run_multi.py` output into the story log. Progress = elapsed / estimate, capped at 90 %. Estimate = `9.8 + 8.0 × (shots − 1)` minutes per part. On exit 0 copies `<part>/<run>.mp4` (or `<run>_seed.mp4` for a one-shot part) to `render/<part>.mp4`. | — | `render/a1.mp4` … |
| 6 | `lipsync` | Runs `lipsync_check.py render/<part>.mp4 <part>/master_seed.wav`. Any part with \|lag\| > 2 frames sets `render.state = held` with `heldReason`, and the render stops there. | renders | — |
| 7 | `step_assemble` | Builds per-part pictures, walls and voices, writes `render/assembly/edl.json`, runs `assemble_story.py`, copies `final.mp4` to `media/final.mp4`, makes `media/poster.jpg` (frame at 3 s, 960 wide), sets `stage = done`, `final.state = ready`, `render.state = done`. | everything above | `media/final.mp4` |

Any exception in a step marks the job failed and sets `render.state = failed` with the message as `heldReason`
(`worker.main`).

---

## 3. Frame and audio maths

### Constants

| Name | Value | Where | Meaning |
|---|---|---|---|
| FPS | 24 | `make_master.py:15`, `worker.py` | Every anchor video is 24 fps. |
| SHOT | 328 frames (13.67 s) | `make_appearances.py:16`, `build_main.py:21` | Length of every raw H3 shot. |
| CTX | 39 frames | `make_master.py:15` | Context overlap: each continuation shot re-uses the last 39 frames of the previous one, so it adds **289 new frames**. |
| VALID | `L % 17 == 5` (5, 22, …, 328, …) | `build_main.py:20`, `make_master.py:16` | Lengths H3 accepts. 328 = 5 + 17 × 19. |
| SR | 24000 Hz | `make_master.py:15` | Master wav sample rate (assembly resamples to 48000). |
| LEAD | 0.25 s | `make_appearances.py:16` | Silence before the first word of an appearance. |
| KEEP_TAIL | 0.45 s | `make_appearances.py:16` | Silence kept after the last word. |
| MAX_FIT | 0.09 | `make_appearances.py:17` | Largest tempo change (±9 %) allowed to fill whole shots. |

### Shot count and time-fit (`make_appearances.py:46-62`)

For each appearance, with `d0` = the take's speech length after silence trimming (`make_master.trimmed`: below
−45 dBFS removed, 30 ms kept each side):

1. `n = max(1, round(((0.25 + d0 + 0.45) × 24 − 39) / 289))` shots.
2. `frames = 328 + (n − 1) × 289`; `target = frames / 24 − 0.25 − 0.45` seconds of speech.
3. If `|d0 / target − 1| ≤ 0.09`: the take is time-stretched to exactly `target` (ffmpeg `rubberband`, pitch kept), and
   `keep_frames = frames`. The speech ends exactly 0.45 s before the last frame.
4. Otherwise the take is **not** stretched: `n = ceil(...)` of the same formula, `frames` is recomputed, and
   `keep_frames = min(frames, ceil((0.25 + d0 + 0.45) × 24))`. The render is longer than the line; assembly cuts it at
   `keep_frames`, so the silent end is never shown.

| Shots | Frames | Seconds | Speech target | Stretch window (±9 %) |
|---|---|---|---|---|
| 1 | 328 | 13.67 | 12.97 s | 11.80–14.13 s |
| 2 | 617 | 25.71 | 25.01 s | 22.76–27.26 s |
| 3 | 906 | 37.75 | 37.05 s | 33.72–40.38 s |
| 4 | 1195 | 49.79 | 49.09 s | 44.67–53.51 s |

Example outside the window: a 16 s take rounds to 1 shot (ratio 1.23, too far), so it gets 2 shots (617 frames),
unstretched, with `keep_frames = 401`.

The voice side uses the same rule when picking takes: `worker.target_for` and `worker.score`
prefer the take whose length is closest to filling whole shots, after word accuracy.

### Loudness of the masters (`make_appearances.py:63-79`)

All appearances are concatenated into `all_raw.wav`, finished **once** together (`highpass=f=70`,
`loudnorm=I=-16:TP=-1.5:LRA=11`) into `all_finished.wav`, and cut back per appearance. So every appearance gets the same
gain. Each is then split at frame 328: `master_seed.wav` (first 328 frames of audio) and `master_chain.wav` (the rest;
one frame of silence for a one-shot appearance).

---

## 4. File formats in a render folder

Everything lives in `~/anchor-studio/rigvideo-data/projects/<id>/render/` on t7 (it is built in
`~/anchor-studio/studio/<id>/render/` on t3 and copied back).

| File | Written by | Shape |
|---|---|---|
| `../media/render-in/script.json` (t3: `studio/<id>/script.json`) | `prepare_render` | `{"scripts": {"a1": "spoken text", "a2": "..."}}` |
| `all_raw.wav`, `all_finished.wav` | `make_appearances` | All appearances end to end, before and after the loudness finish |
| `appearances.json` | `make_appearances` | List, one per anchor part: `{"id": "a1", "take": "<wav name>", "speech_s": 12.97, "shots": 1, "tempo": 1.034, "frames": 328, "keep_frames": 328}`. `tempo` = d0 / target. |
| `<part>/master_seed.wav` | `make_appearances` | Mono 24 kHz, exactly 328 frames of audio (13.667 s) |
| `<part>/master_chain.wav` | `make_appearances` | The remaining `(n−1) × 289` frames of audio, or one frame of silence |
| `<part>/shots.json` | `make_appearances` | `{"fps": 24, "context": 39, "sr": 24000, "total_frames": F, "shots": [{"raw_frames": 328, "delivered_frames": 328}, {"raw_frames": 328, "delivered_frames": 289}, ...]}` |
| `<part>/story.json` | `make_appearances` | `{"run": "render_<part>", "anchor": "<registry id>", "beats": ["text spoken in shot 1", "text in shot 2", ...]}`. Each sentence goes to the shot where its middle falls, estimating time by character count (`split_sentences`, `make_appearances.py:32`). |
| `<part>/run.txt` | `prepare_render` | `render_<part>_st` |
| `<part>/render_<part>_st_seed.json`, `..._chain.json` | `build_st.py` | ComfyUI API graphs (section 5) |
| `<part>/render_<part>_st_seed.mp4`, `render_<part>_st.mp4` | `run_multi.py` | Copies of ComfyUI's `output/h3_chains/<run>/final/*.mp4` |
| `<part>.mp4` | `_gpu_run` | The appearance's finished render (chain output, or the seed for one shot). 1280×736. |
| `paused.json` / `paused.restored.json` | `gpu.pause` / `gpu.restore` | What was stopped (section 8) |
| `times.json` | `run_multi.py` | Minutes per job: `{"a1_seed": 9.6, "a1_chain": 7.9, ...}` |
| `assembly/` | `step_assemble` | Work folder: `<vo>_voice.wav`, `<vo>_pics.mp4`, `<anchor>_wall.mp4`, `raw_*.mp4` downloads, `*_kb.mp4` stills, copies of every `<part>.mp4` and `<part>/`, `appearances.json`, `edl.json`, `segments/`, `segments_audio.txt`, `segments.json`, `final.mp4` |

### `edl.json` (written by `step_assemble`)

```json
{"meta": {"anchor_name": "Maren Ashcroft", "lt_headline": "<p.lt.headline>", "location": "<p.lt.kicker>",
          "kicker": "WORLD NEWS", "subline": "<p.lt.subline>", "outro": true},
 "ticker": ["<p.ticker items>"],
 "beats": {"a1": {"wall": ["<assembly/a1_wall.mp4>", 0]},
           "v1": {"pictures": "<assembly/v1_pics.mp4>", "voice": "<assembly/v1_voice.wav>"},
           "a2": {}}}
```

- `location` is filled from the project's `lt.kicker` (the place); the red kicker chip always says `WORLD NEWS`.
- `outro` is `project.extras.outro`, default `true`.
- An anchor part with no footage anywhere in the story gets `{}` (no wall composite; H3's own wall stays).
- `assemble_story.py` also accepts `"nX": {"shots": [[clip, in_s, out_s], ...]}` (footage with its own sound) and
  `meta.no_name_tag`; `step_assemble` never writes either.

`segments.json` (written by `assemble_story.py`) = `[["a1", frames], ["v1", frames], ..., ["outro", frames]]`.

---

## 5. Building the ComfyUI jobs: build_main.py and build_st.py

### The recipe (`build_main.py:102-114`)

| Variant | Seed | Chain | Notes in code |
|---|---|---|---|
| `safe` | FBC "H3 Safe — 0.08 / max 2", 20 steps | same FBC, 20 steps | 13.1 min sampling per shot. CLI default. |
| `v4` | FBC "H3 Fast — 0.10 / max 2" | same | 12.1 min |
| `v7` | FBC Fast + sparse attention (0.40–1.0, tau 1.0) | same | 9.6 min |
| **`t8k`** | v7 | v7 + LoRA `MiniMax-H3-Ref2VA-Acc-8Step_pruned_comfy.safetensors` at 1.0, **8 steps** (lcm / beta) | The production recipe. `build_st.py` always uses it. |

Speed nodes (`_speed`, `build_main.py:183`): node `9700` = `H3SparseAttentionOverride` (our custom node; tau 1.0,
window 0.40–1.0, dense blocks `0-2, 47-49`, min_tokens 12288, extra_tokens 256, `sink_conditioning:
exact_kv_and_rows`), then node `9300` = `ApplyMiniMaxH3FirstBlockCache` (start 0.10, end 0.95, max 2 consecutive
hits). The sampler reads `9300`.

### Seeds (`build_main.py:24-52`)

Seeds change what H3 does (a close-up cut, a camera pan), so they are fixed and vetted.

| Name | Value |
|---|---|
| `SEED_SHOTS` (seed shot, row k) | 42, 2042, 3042, 4042, 5042 |
| `CHAIN_SEEDS` (row k) | [52000, 52103, 54206], [53000, 53103, 53206], [54103, 52000, 52103] |
| `BAD_SEEDS` (never used) | 1042, 52206, 54000 |
| `PROVEN_CHAIN_SEEDS` (fill for long chains) | 52000, 52103 |

`seeds(off, n)`: row `k = noise_offset // 1000`. Rows past the table use `42 + 1000k` and fresh chain seeds
`52000 + 103·i + 1000k (+7 steps)` skipping bad ones. RIG-Video never sets `noise_offset`, so every appearance uses
seed **42** for its first shot and **52000, 52103, 54206, 52000, 52103 …** for shots 2, 3, 4, ….

### Prompt text and identity pin

- `anchor_entry(id)` reads the registry row; `pr()` fills he/she/his/her/him from `pronoun` and `noun` from `gender`.
- **Identity pin** (`build_main.py:207-215`): the seed template's legacy anchor description ("He is a real male
  television news anchor (S1) … below the knot.") is replaced by `identity_block(a)`: "<Picture 2> is the identity
  reference … keep exactly that person's face …" + the registry `descriptor`. Node `138` becomes
  `LoadImage anchor_face_<id>.png` (or `anchor_id_<id>.png` when the entry has no `identity_face`) and is wired as
  `ref_images.ref_image_1`. Picture 1 is the studio plate `plate_set7.png`.
- **Chain shot prompt** `cont(line, a)` (`build_main.py:166`): a 6-section Ref2VA prompt ("subject_definitions",
  "summary", "retention_analysis", "detailed_description", "overall_soundscape", "non_diegetic_music") that keeps the
  same anchor, set (`SET`), crowd motion (`MOTION`), delivery (`DELIVERY`), room tone (`SOUND`) and underscore (`MUSIC`),
  with the shot's text as `<d>[English]…</d>`.
- `spoken()` and `snap()` (`build_main.py:55-94`) size shots by spoken words and the anchor's `words_per_shot`. In the
  source_track path `build_st.py` overwrites every length with the master's `raw_frames` (328), so they only affect the
  "LOCK OK" printout.

### Locks (assertions, `build_main.py:227-262`)

The build fails if: the seed template does not have exactly one `<d>` line and one legacy description; the voice is
not on the flat key `ref_audios.ref_audio_0`; the seed does not run FBC; the chain differs from the canon in anything
except `1950.video`, `1700.plan_json/run_name`, `1706.filename`, `121/123.model` (plus the LoRA and `default_steps`
for t8k) and the added speed nodes; the chain has any `ref_audio`; `1951.prepend_original` is not true; or the anchor
time + `OUTRO_S` is under 60 s. `build_st.py` sets `bm.OUTRO_S = 60` in its own process so that last check always
passes (`build_st.py:45`).

### build_st.py: the source_track lock

`build_st.build(story, master_dir, out_dir, turbo_seed)` (`build_st.py:38`) calls `build_main.build(..., "t8k")` into a
temp folder, then rewires both graphs. The lock is `LOCK = {final_audio: "source", lock_source_audio: True,
source_reference: "off", generated_continuity: "off"}` on node `1954` (MiniMaxH3ChainPolicy). Each scene's window
of the master is VAE-encoded into H3's audio latent with a zero denoise mask, so H3 generates the video **against our
voice** (lip sync) instead of inventing a voice. The audio comes in through `1951a LoadAudio` →
`1955 MiniMaxH3SourceTimeline`, wired into `1930` (Plan Studio) and `1701` (Loop Start).

| | Seed job `<run>_seed.json` | Chain job `<run>.json` → `<run>_chain.json` |
|---|---|---|
| Graph | A copy of the **chain** graph run as one scene: nodes `1950/1951` (imported video) removed, `1701.external_context` removed, `1949.asset_1` removed | The t8k chain graph |
| Pictures | `137` plate = Picture 1, `138` face = Picture 2, wired into `110` (ReferenceToVideo) | none new (continues from the seed video) |
| Prompt | The seed's identity prompt with the `<Audio 1> is the voice reference…` sentence removed (asserted) | `cont()` per shot |
| Shots | one: `{"id": "seed", "length": 328, "steps": S, "seed": 42}` | one per further shot, `length = raw_frames` (328), seeds from the table |
| Steps | **production passes `--turbo-seed`**: 8 steps, lcm/beta, Acc-8Step LoRA, SigmaShift kept. Without it: 20 steps res_multistep/simple, LoRA and SigmaShift removed. | 8, lcm/beta, Acc-8Step LoRA |
| Context | `video_blend_frames = 0`, `retain_overlap_frames = 0`, `incoming_transition = cut` | 39-frame context; incoming transition stays `soft_av` |
| Audio | `<run>_master_seed.wav` | `<run>_master_chain.wav`; the pack fills the 39-frame overlap from the seed video's own (locked) audio |
| Video input | — | `1950.video = <run>_seed.mp4` |
| Output name | `1706.filename = <run>_seed` → `output/h3_chains/<run>_seed/final/*.mp4` | `<run>` → `output/h3_chains/<run>/final/*.mp4` |

`build_st.py` prints `seed 328 + chain [328, …] = F frames = master S s`; the two must match.

---

## 6. The workflow templates

Both are ComfyUI API-format graphs (`{node id: {class_type, inputs}}`). Summary by role:

### `templates/seed_set7_fbc.json` (single-shot seed)

| Role | Nodes |
|---|---|
| Model loaders | `127` UNET `minimax_h3_ref2va_pruned_int8_convrot`, `128` CLIP `qwen3vl_32b_minimax_h3_int8_convrot` (type minimax), `119` video VAE fp16, `120` audio VAE fp32 |
| Attention / speed | `9100` ModelAttentionBackend ("comfy kitchen attention") → `9300` FirstBlockCache (template has Safe 0.08; the builder sets the variant) |
| References | `137` LoadImage `plate_set7.png` (Picture 1), `138` (a text primitive in the template; the builder makes it LoadImage of the face), `250` LoadAudio voice (template `mirac.wav`) |
| Generation | `115` ResolutionSelector (16:9, 0.9 MP, multiple of 32), `136` MiniMaxH3ReferenceToVideo (prompt, length 328), `129` RandomNoise (42), `123` KSamplerSelect res_multistep, `124` BasicScheduler simple 20 steps, `126` BasicGuider, `125` SamplerCustomAdvanced |
| Output | `122` VAEDecode, `121` VAEDecodeAudio, `130` CreateVideo 24 fps, `92` SaveVideo `video/<run>_seed` |

In production the seed template is only a **source** for `build_st.py` (its prompt, plate/face nodes, noise seed and
`ref_image_size`); the graph that runs is the chain graph (section 5).

### `templates/chain_prod_v2_canon.json` (multi-shot chain, "anchor_60s_prod_v2")

| Role | Nodes |
|---|---|
| Loaders | `1` UNET, `2` CLIP, `3` video VAE, `4` audio VAE (same files as the seed) |
| Model path | `1941` attention backend → `1635` LoraLoaderModelOnly (canon: turbo 4-step LoRA at 0.0; t8k: Acc-8Step at 1.0) → `5` MiniMaxH3SigmaShift (audio 3.0, video 12.0) → [`9700` sparse → `9300` FBC, added by the builder] |
| Chain plan | `1700` MiniMaxH3ChainPlan (plan_json with the shots, 1280×736, context 39, audio context 39, `audio_feathered_av`, blend 39, segment CRF 20), `1954` ChainPolicy, `1942` RichScenePromptEditor, `1930` PlanStudio, `1949` RunManager |
| Continuity inputs | `1945` LoadImage `anchor_ref_v12.png` → `1947` TaggedPictureReference ("anchor"), `1950` VHS_LoadVideo (the seed mp4, 1280×736, 24 fps), `1951` ChainExternalVideo (`prepend_original: true`) |
| Loop | `1701` LoopStart → `1702` ChainCurrent → `110` ReferenceToVideo → `1703` ChainContext → `120` noise, `121` guider, `122` lcm, `123` beta scheduler, `124` sampler → `130/131` decode → `132` LoopTrim (retains 39 overlap frames) → `1704` SegmentSave, `1931` ChainReview (disabled) → `1705` LoopEnd |
| Output | `1706` ChainAssemble (audio from plan, 256 kbps) → `output/h3_chains/<run>/final/` |

---

## 7. ComfyUI: client, custom nodes, required input files

### `orchestrator/comfy.py`

| Function | Behaviour |
|---|---|
| `start(log, timeout_s=600)` (`:36`) | If nothing answers `GET /system_stats`, starts `~/anchor-studio/repos/ComfyUI-v038/.venv/bin/python main.py --listen 0.0.0.0 --port 8199 --disable-comfy-compiler` plus `$COMFY_ARGS`, logging to `~/anchor-studio/comfy_daily.log`. Polls every 5 s; raises after 600 s. |
| `submit(job_file, tries=4)` (`:73`) | POSTs `{"prompt": graph}` to `/prompt` (120 s timeout). On a timeout/reset it waits 20 s × attempt and checks `/queue` for an identical graph already accepted, so a job is never queued twice. Raises on `node_errors`. Returns the prompt id. |
| `wait(prompt_id, deadline_ts, log, label)` (`:99`) | Polls `/history/<id>` every 15 s. Returns `(ok, seconds, error)`. Past the deadline it calls `/interrupt` and returns "hard deadline reached". It only declares "ComfyUI died" when the HTTP check fails **and** no `main.py --listen` process exists (a model load can make it stop answering for a while). |
| `kill(log)` (`:52`) | `pkill -9 -f "[m]ain.py --listen"`. This kills **any** ComfyUI on the machine. |
| `newest(pattern)` (`:127`) | Newest file under `ComfyUI-v038/output/` matching a glob. |

### Custom nodes (`studio-app/pipeline/comfy_nodes/`)

These must sit in `ComfyUI-v038/custom_nodes/`. `deploy/deploy.sh` copies `studio-app/` to t7 but does **not** copy
them into ComfyUI; HANDOFF section 10 lists them as installed.

| Node | File | What it does |
|---|---|---|
| `H3SparseAttentionOverride` | `h3_sparse_override/__init__.py` | Sparse attention (`comfy_kitchen.sol_attn`) installed **only** as `optimized_attention_override`, so it can stack with FirstBlockCache (ComfyUI's own BlockSparseAttention also replaces DiT blocks, which collides with FBC). Falls back to dense attention outside the sigma window, below `min_tokens`, on `dense_blocks`, or with a mask. Text/reference/audio rows stay exact via `sink_conditioning`. Used by t8k (node `9700`). |

### Files that must already be in `ComfyUI-v038/input/`

Checked by `gpu_run` before every render (names starting `render_` are excluded because `run_multi.py` copies them):

| File | Loaded by | Source |
|---|---|---|
| `plate_set7.png` | seed job node `137` | the studio plate |
| `anchor_face_<anchor id>.png` | seed job node `138` | the registry `identity_face` cut-out, copied by hand |
| `anchor_ref_v12.png` | node `1945` in both jobs (chain template) | fixed file of the canon chain |

Per-run files `run_multi.py` copies in: `<run>_master_seed.wav`, `<run>_master_chain.wav`, `<run>_seed.mp4`.

---

## 8. The GPU run and the tenant pause/restore protocol

### `run_multi.py <render dir> <part>[:seed|:chain|:both] ...`

1. `ensure_gpu(base.name, base/"paused.json")` (below).
2. `comfy.start()` once.
3. Per part: copy both masters into ComfyUI `input/` as `<run>_master_*.wav`; submit the seed job (deadline **45 min**),
   copy its `final/*.mp4` to `<part>/<run>_seed.mp4` and to `input/<run>_seed.mp4`; if the part has more than one shot,
   submit the chain job (deadline **60 min × number of shots**) and copy its output to `<part>/<run>.mp4`. Any failure
   raises `SystemExit("<part> <kind> failed: <error>")`.
4. `finally`: write `times.json`, `comfy.kill()`, `gpu.restore(paused.json)`. This runs even after a failure.

### `runlib.ensure_gpu(what, paused)` (`runlib.py:23`)

| Check, in order | Result |
|---|---|
| `~/anchor-studio/NEW_ANCHORS_HOLD` exists | exits 0 without rendering (the worker then fails because no video exists) |
| `anchor-daily.service` (the old DNL daily pipeline) is active | exits 1 |
| No systemd (a cloud container) | waits up to 15 min for a free GPU; never pauses anything |
| `gpu.tenants_active()` is non-empty, **or** the GPU is not free within 60 s | `gpu.pause(paused, now + 5 h)` |
| then | waits up to 15 min for a free GPU, else `SystemExit` |

"Free" (`gpu.is_free`) = memory used < **4000 MiB** and utilisation < **10 %** (`nvidia-smi`; the WSL path
`/usr/lib/wsl/lib/nvidia-smi` is used when present).

### `orchestrator/gpu.py`

| Name | Value | Meaning |
|---|---|---|
| `SERVICES` (`:21`) | `ollama-robin.service`, `pt-worker-box-gpu.service`, `collect-ollama.service`, `vo-vision.service` | `systemctl --user` units stopped and started again |
| `TRANSIENT` (`:23`) | `collect-vision-llm.service` → `systemd-run --user --unit=collect-vision-llm --slice=app.slice /usr/bin/bash -c "exec bash ~/collect-vision/serve_vision.sh >> ~/collect-vision/vision-llm.log 2>&1"` | A transient unit disappears when stopped, so restore relaunches it with this exact line |
| `LEAVE_ALONE` (`:25`) | `embed_server.py`, `embed_launch.sh` | GPU processes never touched (small, self-respawning) |

**`pause(record_file, restore_at_utc)`** (`gpu.py:71`):
1. Loads an existing record if one is there (an unrestored record is never dropped) and saves it.
2. **Before stopping anything**, schedules the independent restore: `systemd-run --user
   --unit=anchor-gpu-restore-<epoch> --on-calendar="<UTC time>" --timer-property=AccuracySec=1s <python> gpu.py restore
   <record_file>`. `runlib` passes now + 5 hours.
3. Stops every active unit in `SERVICES` + `TRANSIENT`, saving the record after each stop.
4. Waits 5 s, then for every process still on the GPU that is not in one of those units, not in `LEAVE_ALONE`, and not
   ComfyUI (`main.py --listen`): records its command line, working directory and full environment (one entry per
   command line), sends SIGTERM, waits up to 30 s, then SIGKILL.

**`paused.json`**: `{"services": ["ollama-robin.service", ...], "procs": [{"pid": 1234, "cmdline": [...], "cwd": "...",
"env": {...}}]}`.

**`restore(record_file)`** (`gpu.py:116`): idempotent; does nothing if the file is gone. Starts each recorded unit that
is not active (transient ones with their `systemd-run` line), relaunches each recorded process unless an identical
command line is already running (detached, same cwd and env), then renames the file to `paused.restored.json`. It runs
twice in a normal render (from `run_multi.py`'s `finally`, then from the timer, which finds nothing to do).

CLI: `python gpu.py restore <file>` (what the timer runs) and `python gpu.py status` (memory, utilisation, free or busy,
which tenants are up).

---

## 9. Lip-sync check

`lipsync_check.py video.mp4 [master.wav] [start_s end_s]` (`lipsync_check.py`):

1. **Audio lock** (printed only): cross-correlates the video's audio (16 kHz mono) with the master and prints the peak
   and its offset in ms.
2. **Lip sync**: finds the face with OpenCV's Haar cascade on 25 frames spread over the file, takes the median box, and
   uses a mouth box (middle half of the face width, from 68 % to 93 % of its height). Per frame, "mouth openness" =
   minus the 10th-percentile grey level in the mouth box. Per frame, loudness = RMS of the matching audio in dB. Both are
   differenced (so slow lighting drift does not count) and z-scored; the correlation is computed at lags −12…+12
   frames. Output line: `LIPSYNC frames a-b: best lag +N frames (+ = mouth after sound), corr …`.

**Threshold** (`worker.lipsync`): the render passes if the best lag is within **±2 frames**, or if no
lag line is printed. A check that takes over 600 s counts as a pass ("not measured"). The check runs on each part's own
render, never on the finished video (the docstring warns that footage faces confuse the mouth box).

---

## 10. Assembly

### `step_assemble`: what each part plays

**VO parts**:
- Pictures, first non-empty of: the editor's placed items for that part (`placed_items`); the clip checker's cuts
  (`p.anchorEdit.beats[sectionId].cuts`, `auto_items`); anything placed anywhere in the story. None at all fails with
  "Part vN has no pictures".
- `placed_items`: a placed moment uses its cut clip (`p._clipfiles`), with `BLUR` (blurred fill for a vertical
  clip) when the editor chose the treated version, else `CONF`; an uploaded video plays as is; a photo, upload image or
  map becomes a Ken Burns clip of its placed length (`assets.ken_burns`).
- `auto_items`: a checker video cut is downloaded at source quality by `vertical/assemble916.download` (up to
  1080p; the 480p checker copy if YouTube refuses); a picture cut becomes a Ken Burns clip.
- `CONF` = crop the centre 90 % (removes corner logos), fill 1280×736, 24 fps.
- `montage()` joins the items back to back, looping if short, to exactly the needed length, with no sound.
- Voice: the part's picked take, leading silence removed, 0.25 s lead added, padded to `0.25 + speech + 0.45` s,
  `highpass=70`, `loudnorm I=-16 TP=-1.5 LRA=11`, 48 kHz mono.

**Anchor parts (the wall)**:
- The editor's own placed items for that anchor part win.
- Otherwise `wall_shot()`: the **last shot shown in the footage before** this anchor part; for the opening
  part, the **first shot of the footage after** it. `wall_item()` downloads a checker cut again from its start for the
  wall's length (`keep_frames / 24 + 0.5` s); a placed clip plays on to its file's end.
- Otherwise everything placed in the story; otherwise no wall.

### `assemble_story.py <work_dir> "<order>"`

Per entry of the order (`assemble_story.py:81-104`):

| Kind | Video | Audio |
|---|---|---|
| Anchor (`id` in `appearances.json`) | If more than one shot: `colorlock.py` with boundaries `328, 617, 906, …` (`328 + k·289`). Cut to `keep_frames` (CRF 14). `post.refine_quad` checks the wall position; if it passes **and** the EDL has a wall, the wall clip is conformed (`CONFORM`, 90 % crop) and composited with `wall_comp.py … broll`. Then `assemble_novo.graphics()` burns in the TV graphics. | The finished masters themselves (`master_seed.wav` + `master_chain.wav`), cut sample-exactly to `keep_frames`; not the render's AAC |
| VO (`"voice"` in the EDL) | Pictures cut to the voice's frame count, sound removed | The voice wav, padded/trimmed to the video's frames |
| Footage with own sound (`"shots"`) | Clips joined, 24 fps | Their own sound, `loudnorm -16`, 0.15 s fade in, 0.6 s fade out |
| Outro (when `meta.outro`) | `studio-app/DNL Outro.mp4`, scaled to 1280×736 without the 90 % crop | its own sound |

**Join** (`:105-112`): video with the ffmpeg `concat` **filter** (exact frame counts); audio from the per-segment PCM
wavs through the concat demuxer, so AAC padding never shifts lip sync. One pass: `loudnorm=I=-14:TP=-1:LRA=11`, 48 kHz,
AAC 256 kbps, H.264 CRF 16, `+faststart`. Segments already made are reused on a re-run.

All ffmpeg calls use `~/anchor-studio/repos/ffmpeg-shared/current/bin/ffmpeg` (`assemble_hybrid.py:20`), which is
also put first on `PATH` for `colorlock.py` and `wall_comp.py`.

### Graphics per anchor part (`assemble_novo.graphics`, `assemble_novo.py:20`)

Starts from `post.lt_story(meta, ticker)` (`post.py:66`): `anchorName`, `anchorTitle: "News Anchor"`, `headline`,
`location`, `logo: studio-app/lt_remotion/assets/logo.png`, `lowerThird: {kicker, subline, holdSeconds 6,
repeatEverySeconds 20}`, `ticker: {tag "LIVE", speedPxPerSecond 90, items}`, `nameTag: {holdSeconds 4.5}`. Then:
- removes `outro` (added once at the end instead);
- sets the lower third to hold 8 s, no repeat;
- on every appearance **after the first**: name tag zeroed (in/hold/out 0) and the lower third starts at 0.6 s.

It writes the story JSON next to the segment and runs `node lt_remotion/apply_broadcast_package.mjs <in> <story> <out>`
with Node from `ANCHOR_NODE` or the first `~/.nvm/versions/node/v*/bin/node`, and `LD_LIBRARY_PATH` including
`~/.local/chrome-libs/root/usr/lib/x86_64-linux-gnu` when present (NSS libraries unpacked in user space for Remotion's
headless Chrome).

### `colorlock.py in.mp4 out.mp4 b1,b2,...`

Reads the middle frame of each part between boundaries, computes mean HSV value (brightness) and saturation, and
multiplies every frame of part k by part 1's mean / part k's mean (constant per part). Part 1 is untouched. Re-encodes
H.264 CRF 16, copies audio, and prints a verify line per part.

### Wall position check: `post.refine_quad(video)` (`post.py:38`)

- One studio set is defined: `SETS["set7"]` with plate `studio-app/bg_options/option_C_tall_room_set/plate_1280x736.png`,
  wall corners `[[717,232],[1270,182],[1272,512],[717,500]]` (TL, TR, BR, BL) and `min_align 0.6`.
- Takes frame 12 of the video, draws a 24-px band along the quad, and computes the normalised correlation of the
  grey plate vs the frame in that band for every shift of ±20 px in steps of 2.
- Below 0.6 it returns `None` and the wall composite is skipped (H3's own wall stays). Otherwise it returns the shifted
  quad as `"x,y x,y x,y x,y"`.

### `wall_comp.py seed.mp4 content.mp4 start_s out.mp4 "<quad>" [broll|clean]`

Per frame: segments the anchor with `rembg` (`u2net_human_seg`), so the anchor stays in front; warps the content
(resized to 960 wide) onto the quad; mixes it with a soft-edged wall mask minus the person mask. `broll` (what assembly
uses): blur sigma 1.6, saturation × 0.6, colour matched 50 % to H3's own lit wall (statistics from the first frame).
`clean`: blur 0.6, full colour, 25 % match. Content shorter than the video holds its last frame. CPU only; the file
notes about 2 min per 13 s shot.

---

## 11. lt_remotion: the TV graphics package

A Remotion 4 project (`package.json`: `@remotion/cli`, `@remotion/renderer`, `remotion` ^4.0.518; `react`, `react-dom`
^19.2.8; `"type": "module"`). `node_modules` is not in git: run `npm ci` in `studio-app/lt_remotion` (lockfile
present). It needs Node, `npx`, `ffmpeg` and `ffprobe` on `PATH`, and a headless Chrome that Remotion runs. It uses no
GPU (README).

### Scripts

| Script | Usage | Steps |
|---|---|---|
| `apply_broadcast_package.mjs` | `node apply_broadcast_package.mjs <in.mp4> <story.json> <out.mp4>` | 1. `ffprobe` width, height, fps, duration. 2. If `story.logo` is a path (or `{src}`), inline it as a `data:` URI (looked up next to the story file, then CWD). 3. `npx remotion render src/index.jsx BroadcastPackage overlay.mov --props props.json --codec=prores --prores-profile=4444 --image-format=png --pixel-format=yuva444p10le` (`LT_CONCURRENCY` adds `--concurrency`). 4. `ffmpeg overlay=0:0:shortest=1`, H.264 CRF 18, audio copied. 5. If `story.outro` is set and found: scale/pad the outro to the video's size and fps and concat it (AAC 192k). Temp files go to `$TMPDIR/bcast-*` and are deleted. |

The ProRes 4444 + PNG + `yuva444p10le` flags are needed for a real alpha channel; the README explains how to verify it.

### The input story JSON

`story.example.json` shows the shape. Everything except `headline`, `anchorName` and `ticker.items` has a default.

| Field | Default | Meaning |
|---|---|---|
| `anchorName`, `anchorTitle` | "ANCHOR NAME", "ANCHOR" | Name tag text |
| `headline` | — | Lower-third headline |
| `location` | none | String, or `{text, startSeconds (0.5)}`. No location bug without it. |
| `logo` | none | Path/URL string, or `{src, heightPx (60), startSeconds (0.5)}` |
| `lowerThird` | `{kicker "BREAKING NEWS", holdSeconds 8, subline "", repeatEverySeconds 0, startSeconds, startDelayAfterNameTagSeconds 0.3}` | Single lower third; starts after the name tag clears unless `startSeconds` is given |
| `lowerThirds` | none | Optional list `[{start, headline, kicker?, subline?, hold (7)}]`; when present it replaces the single lower third |
| `ticker` | `{tag "LIVE", items [], startSeconds 0.4, speedPxPerSecond 90}` | Crawl |
| `nameTag` | `{inSeconds 0.35, holdSeconds 4.5, outSeconds 0.35}` | Name tag timing |
| `outro` | none | Path to a video appended by the script (RIG-Video removes it per segment) |
| `video` | added by the script | `{width, height, fps, durationSeconds}` from ffprobe |

### Components (`src/`)

| File | What it draws |
|---|---|
| `index.jsx` | `registerRoot(RemotionRoot)` |
| `Root.jsx` | One composition, `BroadcastPackage` (defaults 1280×736, 24 fps). `calculateMetadata` takes duration, fps and size from `story.video` / `video`, so the overlay always matches the input. |
| `BroadcastPackage.jsx` | Layers in order: Ticker, LowerThird(s), NameTag, LocationBug, Logo. Computes start times (name tag at 0; lower third at in + hold + out + 0.3 s unless set). |
| `NameTag.jsx` | Lower-left (left 64, bottom 96): a 72×4 red bar, then a dark gradient panel with a red left border; name 28 px bold white, title 17 px uppercase grey. Slides in 40 px with ease-out cubic, holds, eases out. |
| `LowerThird.jsx` | Lower-left, up to 1120 px wide: red kicker chip (20 px uppercase), then a dark panel with red left border, Georgia serif headline 34 px, optional uppercase subline 21 px. Staggered reveal (bar 0 s, kicker +0.06 s, headline +0.12 s), in 0.45 s, out 0.4 s. With `repeatEverySeconds` longer than one show, it re-enters every cycle. |
| `Ticker.jsx` | A 46-px dark strip at the bottom: red tag box (108 px, e.g. "LIVE") and the items joined by " • ", scrolling left at `speedPxPerSecond`, looping seamlessly (content drawn twice; width estimated at 15.5 px per character). Fades in once and stays to the last frame. |
| `LocationBug.jsx` | Top-left (48, 48): red tab with a white map-pin icon, dark panel with the location uppercase 22 px. Fades/slides in, stays to the end. |
| `Logo.jsx` | Top-right (40 px margin), image `heightPx` tall, plain fade-in, stays to the end. |


---

## 12. Anchor registry and adding an anchor

### `anchor_registry/registry.json`

`{"_note": "...", "anchors": [ ... ]}`. 11 entries: 10 `ready`, `rohit` `onboarding`.

| Field | Example | Read by | Meaning |
|---|---|---|---|
| `id` | `maren_ashcroft` | everything | Key; also in `anchor_face_<id>.png` |
| `name` | `Maren Ashcroft` | `worker` (EDL name tag), `app.anchors` | Display name |
| `gender` | `M` / `F` | `build_main` (`noun`), `app.anchors` | Gender |
| `pronoun` | `he` / `she` | `build_main.pr` | Pronouns in prompts |
| `voice_file` | `voices/maren_ashcroft__newsanchor_ref.wav` | `worker.make_takes` (Chatterbox reference, copied to t3), `app` (`voice.mp3` sample) | The cloned-voice reference. `voices/` is not in git. |
| `identity_ref` | `frames/maren_ashcroft.png` | `app` (`frame.jpg` on the site) | Full studio frame |
| `identity_face` | `frames/maren_ashcroft_face.png` | `build_main.id_input_name` (decides `anchor_face_<id>.png`), `app` (`face.jpg`) | Head-and-shoulders cut-out on grey: the identity pin |
| `descriptor` | "He has short dark hair …" | `build_main.identity_block` | Hair and wardrobe in words |
| `affinity` | `["europe", "russia_ukraine", "global"]` | `app.pick_anchor`, `app.anchors` | Regions the anchor covers |
| `status` | `ready` / `onboarding` | `app.pick_anchor` (only `ready`), `app.anchors` (`offered`) | Whether the anchor is cast |
| `words_per_shot` | 33 (39 for Eleanor, Yuna) | `build_main.snap` | Words that fill one shot (printout only in the source_track path) |
| `voice_wps` | 3.023 (optional) | `worker.pace`, `app.anchors` | Words per second before `calibration.json` has a learned value; default 2.85 |
| `voice_sha256`, `identity_sha256`, `identity_face_sha256`, `identity_video`, `set_plate`, `voice_file_previous`, `voice_note`, `identity_note` | — | **no code** | Records only |

Casting: `app.pick_anchor(country)` (`server/app.py:272`) maps the story's country with `REGION` (`app.py:263`: RU/UA →
`russia_ukraine`; IN/PK/BD/LK/NP → `south_asia`; IL/PS/IR/SA/IQ/SY/LB/YE/EG → `middle_east`; TR → `turkey`; US/CA →
`north_america`; BR/MX/AR/CO/VE → `latin_america`; CN/JP/KR/TW → `east_asia`; PH/ID/TH → `southeast_asia`; GB → `uk`;
AU/NZ → `oceania`; NG/KE/ZA/ET/SD → `africa`; anything else → `europe`) and returns the first `ready` anchor in file
order whose `affinity` contains that region, else the first `ready` anchor.

### Adding an anchor (what the code needs)

1. **Face cut-out** → `studio-app/anchor_registry/frames/<id>_face.png` (head and shoulders on plain grey) and a full
   frame → `frames/<id>.png`. Both go through git and `deploy.sh`.
2. **Voice reference** wav → t7 `~/anchor-studio/studio-app/anchor_registry/voices/<id>__<source>.wav` (copy by hand;
   not in git). `make_takes` copies it to t3 `~/anchor-studio/studio/refs/` on every voice job.
3. **ComfyUI input**: copy the face cut-out to t7 `~/anchor-studio/repos/ComfyUI-v038/input/anchor_face_<id>.png` by
   hand. Without it every render of that anchor fails at the `gpu_run` check. (If the entry had no `identity_face`, the
   builder would look for `anchor_id_<id>.png` instead.)
4. **Registry entry** with at least `id`, `name`, `gender`, `pronoun`, `voice_file`, `identity_ref`, `identity_face`,
   `descriptor`, `affinity` (values from `REGION` above, or `global`), `status`, `words_per_shot`. Start with
   `"status": "onboarding"` (shown on the Anchors page, not cast); set `"ready"` to cast it.
5. Ship through a release (HANDOFF section 13).
6. The site caches derived media in `rigvideo-data/anchors/<id>_face.jpg`, `_frame.jpg`, `_voice.mp3` and never
   rebuilds them (`app.py:1010`). If you replace a face, frame or voice for an existing id, delete those three files.

---

## 13. chatterbox_takes.py: the voice tool

Installed on t3 as `~/anchor-studio/voice_lab/chatterbox_takes.py` by `deploy.sh`. Run by `worker.make_takes`
inside `store.gpu("voice")`:
`cd ~/anchor-studio/voice_lab && ~/anchor-studio/repos/chatterbox/.venv/bin/python chatterbox_takes.py <config.json> <out_dir>`.
Its docstring still says "trijya-8" and "TEST ONLY"; it is the live tool (HANDOFF section 9).

### Config (`config.json`)

```json
{"anchor": "maren_ashcroft",
 "ckpt_dir": "/home/trijya-3/anchor-studio/models/chatterbox",
 "ref_audio": "/home/trijya-3/anchor-studio/studio/refs/maren_ashcroft__newsanchor_ref.wav",
 "exaggeration": [0.7], "cfg_weight": [0.4],
 "seeds": [1, 2, 3],
 "scripts": {"a1": "Text to speak ...", "v1": "..."}}
```

- `exaggeration` × `cfg_weight` × `scripts` × `seeds` are all combined; the worker passes one value each for
  exaggeration and cfg_weight. Defaults come from `worker.TONE`: grave (0.6, 0.45), urgent (0.8, 0.35),
  serious (0.7, 0.4, the fallback), measured (0.65, 0.45), brisk (0.75, 0.4).
- The worker writes `scripts` through `spoken()`, so numbers are already words.

### Behaviour

- Loads `ChatterboxTTS.from_local(ckpt_dir, "cuda")`.
- A script longer than 40 words is split at sentence ends into groups of at most 40 words; each group is generated
  with the same reference, settings and seed (`torch.manual_seed(seed)` before each) and joined with 0.30 s silence.
- Output: `<out>/<anchor>_ex<ex>_cfg<cw>_<label>_s<seed>.wav` per take and `<out>/takes.json` =
  `{"config": {...}, "takes": [{"take", "anchor", "exaggeration", "cfg_weight", "script_label", "script", "seed",
  "secs_audio", "secs"}]}`. It prints `TAKES DONE` at the end.
- When the editor asks for a tempo change, the worker runs `ffmpeg rubberband=tempo=<x>` over the takes on t3
  afterwards.

---

## 14. select_stories.py: the daily selection

Run by `worker.step_selection` as `select("db")` while holding `store.gpu("writer")` (so the t3
writer model is loaded for the LLM calls). The result goes to `rigvideo-data/selection/<IST date>.json`. When run
directly: `python -m orchestrator.select_stories [--source api|db] [--out selection.json]` (`db` when
`ANALYTICS_DB_URL` is set).

### Source

`db` (production): Postgres on the RIG Hetzner box via `ANALYTICS_DB_URL` (`db.env`). `_connect()` (`:160`) sets
`default_transaction_read_only = on` and `statement_timeout = 120s`. `api` (dry run): DNL's public
`/api/worldwide?scope=world` and `/long-read/<id>` pages; momentum, tier-1 and follow-up terms are 0 there.

`POOL_SQL` (`select_stories.py:126`), in plain words:
- From `analytics.story_generated_v8` joined to `analytics.story_clusters_v8`: not suppressed, not redirected, not in
  `analytics.story_dedup`, last seen within **7 days**, body present, not a parse failure, body not starting with `{` and
  not containing a section printed as a Python dict/list, status `PUBLISHABLE…`, strategy not `stub`, body ≥ **800**
  characters, updated at least 15 minutes ago. Newest 1500.
- Per story, from `story_cluster_members_v8` + `articles`: member article ids, articles in the last 3 h
  (`recent3h`) and in the 3 h before that (`prior3h`), share of tier-1 sources, up to 8 thumbnails (best tier first),
  and distinct `source_id:source_country` pairs.
- Top 3 `primary_entities` by weight, and the generated image URL.

A second query marks **follow-ups**: stories with a member article event (`article_events.is_future`) due in the
next 12 hours.

### Pipeline (`select()`, `:489`)

| Step | Code | Rule |
|---|---|---|
| 1. Group fragments | `group_events` (`:232`) | Leader clustering (largest `sources` first): a fragment joins a group only if it matches the group's **lead**: shares a member article; or same dominant entity and title Jaccard ≥ 0.3; or within 72 h and ≥ 2 shared top-3 entities; or within 72 h and Jaccard ≥ 0.5; or (only when an LLM is available) within 72 h with ≥ 2 shared title words, one of them rare (used by ≤ max(3, 3 % of candidates)). |
| 2. Summarise | `summarise` (`:334`) | Lead = among fragments with ≥ 3 sources, the most recent; else the one with most sources. `sources` = distinct outlet ids over all fragments. Also `recent3h`, `prior3h`, max tier-1 share, follow-up, `age_h` (since newest), `span_h` (newest − first seen), images. |
| 3. Confirm merges (LLM) | `confirm_groups` (`:266`) | For the top **50** events by score: the LLM splits each multi-fragment group into same-event sets (short ids like `3.1`, ≤ 30 fragments per call). A malformed answer keeps the rule grouping. If the LLM fails, everything is regrouped with the strict rules only. |
| 4. Classify (LLM) | `classify` (`:301`) | Top **80** events, 10 per call, with the `RUBRIC` prompt (`:40`): keep only `war_conflict`, `death_disaster`, `democracy`, `turmoil_unrest`, `terrorism_security`, `corruption_crackdown`; reject sports, entertainment, business, tech, soft stories, private tragedies, freak accidents, roundups, cyber pranks, political rhetoric. The LLM also returns the event's country (ISO alpha-2). |
| 4b. No-LLM fallback | `classify` | Keep only if topic ≠ SPORTS, no `SOFT_RX` word, no `PRIVATE_RX` phrase, and a `FALLBACK_RX` word (kill, attack, flood, quake, crash, hostage, wildfire, …). Category `rule`. |
| 4c. Hard veto | `classify` | Topic SPORTS or a category outside the list → `keep = false`. A valid LLM country different from DNL's replaces it (original kept as `label.dnl_country`). |
| 5. Re-score | `score` (`:349`) | See formula below. |
| 6. Merge sagas | `merge_sagas` (`:406`) | Among kept events only: two are the same story if their headlines share ≥ 2 words one of which is rare (≤ max(2, 5 % of events)), or their deck+body share ≥ 3 rare names (capitalised words never written in lower case anywhere in the pool, used by ≤ max(3, 6 %) of events). The highest-scoring event leads; coverage is pooled and re-scored. |
| 7. Pick | `pick` (`:427`) | Two passes, best score first. See below. |

### Score (`score`, `:349`)

```
base  = ln(1+sources) + 0.8·ln(1+foreign) + 0.6·ln(1+recent3h) − 0.3·ln(1+prior3h) + 0.4·tier1_share + 0.5·followup
fresh = 0.03 + 0.97 · 2^(−age_h / 12)                  (half-life 12 hours)
stability = 0.5 if span_h < 3 and more than one fragment, else 1.0
type  = TYPE_WEIGHT[category] (1.0 when unclassified or keyword rule)
score = base · fresh · stability · type
```

`foreign` = distinct outlets whose country is neither the event's country nor `XX`. `TYPE_WEIGHT` (`:34`):
war_conflict 1.3, terrorism_security 1.25, death_disaster 1.2, turmoil_unrest 1.0, democracy 0.9,
corruption_crackdown 0.8.

### Pick rules and caps

| Setting | Value |
|---|---|
| `N_PICKS`, `N_RESERVES` | 10, 10 (the module docstring still says 5) |
| `MIN_OUTLETS` | pick ≥ 8 distinct outlets; reserve ≥ 3 |
| `PICK_CAPS` (per country, per type, political types in total) | (3, 4, 4) |
| `RESERVE_CAPS` | (3, 3, 4), counted among the reserves |
| Political types | turmoil_unrest, democracy, corruption_crackdown |
| `MIN_BODY` | 800 characters |

For each candidate in score order: skip if already taken, under the outlet floor, or breaking the caps; skip if it is
the same story or saga as anything already picked (`saga_index`); skip if `site_live(lead id)` is `False` (DNL's
`/long-read/<id>` answers 404 or 410: killed, held, merged or aged out; network errors count as unknown and do not
skip); skip if the body is under 800 characters. After both passes, on a thin day, reserves that fit the pick caps move
up until there are 10 picks. `exclude` (ids already made) is supported but the worker does not pass it.

### LLM

`orchestrator/llm.chat_json` / `llm.available`. The provider pool in production is `LLM_PROVIDERS` in the API's
systemd unit (HANDOFF section 11): the t3 writer first, Groq after.

### Output (`selection/<date>.json`)

```json
{"generated_at": "<UTC ISO>", "source": "db", "llm": true,
 "picks":    [<pub>, ...],
 "reserves": [<pub>, ...],
 "candidates": [{"event_id", "headline", "score", "parts", "keep", "category", "country", "sources", "why", "fragments"}]}
```

`<pub>` (`_pub`, `:477`): `event_id` (lead story id), `headline`, `deck`, `body`, `topic`, `country`, `score`,
`score_parts` (`base`, `foreign_outlets`, `fresh`, `stability`, `type`), `label` (`keep`, `category`, `country`,
`reason`, maybe `dnl_country`), `sources`, `foreign_outlets`, `age_h`, `fragments` (`[{id, title, sources,
articles}]`), `supporting` (up to 6 other fragments' decks), `images` (up to 24 unique URLs). `candidates` lists all of
the top 80 after the saga merge, best first. The site reads `picks` + `reserves` (`server/app.py:185`).

---

## 15. assets.py: story pictures and Ken Burns

### Shared filters: `fetch(urls, out_dir, keep=5, max_text=0.04, min_ar=0.9)` (`assets.py:172`)

Downloads each URL and drops it when:

| Check | Rule |
|---|---|
| Shape / flatness | aspect ratio outside `min_ar`…2.4, or mean RGB std-dev < 25 (banners, logos, flat graphics) |
| Split-screen | a sharp vertical seam in the middle 40 % (≥ 45 % of rows jump > 30 grey levels), or two near-identical halves (dHash distance ≤ 12) |
| Duplicate | dHash within 10 bits of a kept image |
| Text | RapidOCR boxes (confidence > 0.6, ≥ 3 characters) cover more than `max_text` (4 %) of the image |
| Broadcaster logo | OCR text in a corner (x < 0.3 or > 0.7, y < 0.22 or > 0.78), without "/", matching a broadcaster/newspaper word in `BROADCASTERS` |
| Not a photo | SigLIP-2 (`google/siglip2-so400m-patch14-384`, local cache only) rates collage/map/chart/graphic/logo above "photo", or vertical/padded-portrait > 0.5 with empty sides (`_side_detail` < 0.2) |

Images ≥ 800 px wide are kept first; if fewer than 2 pass, smaller ones fill up. Files are saved as
`photo_<dhash>.jpg`. If RapidOCR or SigLIP-2 is not installed, those checks are skipped (with one warning for OCR).

### `story_pictures(query, out_dir, names, urls=(), keep=24)` (`:698`): the anchor stories' picture pool

Called once per story by `worker.story_photos`. The query is the headline's event words plus the
place; `names` are the capitalised names in the script (`worker.story_names`); `urls` is the story's source link.

| Source | What it gives |
|---|---|
| Tavily news search (`_tavily`, 7 days, 8 results, with image descriptions) | Images with Tavily's own description; article URLs |
| Article pages (the story link + the first 6 Tavily articles, `page_photos`) | `og:image` with its alt text, JSON-LD `ImageObject` captions, `<figure>` + `<figcaption>`; up to 4 per page |
| SerpAPI Google Images (`_serpapi_images`, past week) | Images ≥ 900 px wide, up to 25, with page title |
| Wikimedia Commons search (`_commons_images`) | Bitmaps, 1920 px thumbnails |

**Caption gate**: a candidate is kept only if its URL is http, is not junk (`JUNK_URL`: svg, logo, icon, avatar,
banner, ads, …), is not from a stock library (`STOCK`: Pexels, Unsplash, Pixabay, Shutterstock, iStock, Freepik, Adobe Stock, Dreamstime, Alamy, 123RF, Depositphotos), and
its caption/page title names one of `names` (accent-folded match). Then the `fetch` filters run on up to `2 × keep`
URLs. Returns `[{"path", "url", "page", "title", "w", "h"}]`.

**Free-tier keys** (`_take`, `:392`): `SERPAPI_KEY` and `TAVILY_API_KEY` may each hold several comma-separated keys.
Each key is used until 95 % of its free monthly allowance (`FREE`: SerpAPI 250, Tavily 1000), counted locally in
`~/.config/anchor-studio/search_usage.json`. When all are used up, that source returns nothing.

### `vo_pictures(query, out_dir, keep=6, names=None)` (`:674`)

Used by `vo_pick.py` (the clip checker) when a beat is short of footage. Bing Images (large, wide; no key) + Commons;
same junk/stock filters; when `names` is given, the page title must name one of them; then `fetch`.

### `pick(story, out_dir)` (`:462`): the older single wall photo

Kept from the old DNL daily pipeline. Not called by RIG-Video (section 18). It asks the LLM for entities, language,
an ideal-photo sentence and news queries; links names to Wikidata; harvests captioned photos from the DB's member
articles and Bing News RSS (plus SerpAPI/Tavily when `WALL_KEYED_PRIMARY=1`, the default); gates out stock, file-photo
words (`FILE_WORDS`, many languages), dates older than 10 days before the story, and duplicates; lets the LLM choose
like a picture editor (`EDITOR` prompt); ranks up to 4 survivors by SigLIP-2 similarity to the ideal sentence; falls
back to the subject's Commons image, then `[]` (logo card).

### `ken_burns(photos, seconds, out, title=None)` (`:596`)

Makes a slow push-in video (1920×1080, 24 fps, H.264 CRF 18) at least `seconds + 1` long:
- each photo gets an equal share; consecutive photos cross-fade over 0.8 s;
- zoom 1.00 → 1.08 over the photo's time, computed on a 9.2× upscaled frame so the motion is sub-pixel smooth;
- a photo narrower than 1.3:1 (portrait, poster) is fitted over a blurred copy of itself;
- no photos → the DNL logo (`lt_remotion/assets/logo.png`) centred on navy `#0b1626`;
- with `title`, a 4 s title card (`title_card`: white bold headline, up to 3 lines, under a red bar on navy) cross-fades
  into the photos.

The worker always calls it with one photo and no title, then scales the result to 1280×736 in `montage`.
`python -m orchestrator.assets` runs a self-check (logo card and title card render with the right length).

---

## 16. publish.py and youtube_auth.py: YouTube

### One-time setup: `youtube_auth.py`

Run on a machine with a browser (the docstring says the Mac), with `studio-app/pipeline` as the working directory:

| Command | What it does |
|---|---|
| `python -m orchestrator.youtube_auth <client_secret.json>` | Google's installed-app OAuth flow with PKCE and a loopback redirect on a random local port. Scopes: `youtube.upload` and `youtube`. Sign in as the DNL channel owner/manager and choose the DNL channel. Saves `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN` to `~/.config/anchor-studio/youtube.env` (mode 600) and prints which channel the token belongs to. If Google returns no refresh token, remove the app's access at myaccount.google.com/permissions and retry. |
| `python -m orchestrator.youtube_auth --playlists` | Creates (or re-uses by title) **Awaiting approval** (private) → `YT_PENDING_PLAYLIST_ID`, and **Video Bulletin** (public) → `YT_BULLETIN_PLAYLIST_ID`, saved to the same file. |
| `python -m orchestrator.youtube_auth --test <short.mp4>` | Private test upload; prints the URL and status. |

Then copy `youtube.env` to t7 `~/.config/anchor-studio/` (deploy does not). `common.load_env()` reads it.

### `publish.py` functions used by the worker

`worker.step_post` requires `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN`,
`YT_PENDING_PLAYLIST_ID` and `YT_BULLETIN_PLAYLIST_ID`, else it fails with "YouTube is not connected on this machine
yet".

| Function | What it does |
|---|---|
| `_token()` (`:44`) | Refresh-token grant at `oauth2.googleapis.com/token` → access token |
| `upload(path, title, description, tags, token, privacy=None)` (`:50`) | Resumable upload. Category 25 (News & Politics), language `en`, privacy `unlisted` by default, embeddable, not made for kids, **`containsSyntheticMedia: true`**. The whole file is sent in one PUT (900 s timeout). Logs if YouTube set a different privacy than asked. Returns the video resource. |
| `add_to_playlist(video_id, token, playlist=None)` (`:71`) | Adds to `YT_PENDING_PLAYLIST_ID` by default |
| `set_text(video_id, title, description, token)` (`:95`) | Reads the current snippet, keeps tags/category/languages, writes the new title and description (videos.update needs the whole snippet) |
| `approve(video_id, token, privacy="public")` (`:102`) | Same as DNL's CMS Approve: add to Video Bulletin (if not there), set privacy (keeping `embeddable`, `license`, `publicStatsViewable`, `selfDeclaredMadeForKids`, and `containsSyntheticMedia: true`), remove from Awaiting approval. Each step is skipped when already done, so a retry is safe. |

How the worker uses them: if `posts.youtube.videoId` is empty → `upload` (tags `Democracy News Live, news, world news`,
plus `Shorts` for VO-only) and save the id at once; if not yet `queued` → `add_to_playlist`; for an upload-only job stop
there (`state: awaiting`); for Post → `set_text` if the title/description changed since upload, then `approve` with
`RIGVIDEO_PUBLISH_PRIVACY` (default `public`), `state: posted`.

`python orchestrator/publish.py` runs a self-check of `youtube_text`.

---

## 17. common.py

| Name | Value |
|---|---|
| `APP` | `studio-app/` (parent of `pipeline/`) |
| `PIPE` | `studio-app/pipeline` |
| `STUDIO` | `~/anchor-studio` |
| `COMFY`, `COMFY_IN` | `~/anchor-studio/repos/ComfyUI-v038`, its `input/` |
| `TOOLS_PY` | `$ANCHOR_TOOLS_PY` or `~/.cache/anchor-tools/bin/python` |
| `IST`, `now()` | UTC+5:30 clock (used for `runlib.log` timestamps) |
| `load_env()` | Reads every `~/.config/anchor-studio/*.env` (`KEY=VALUE`, `#` comments, quotes stripped) into `os.environ` without overwriting variables already set. Called by `worker.py` at import and again in `step_post`. |

---

## 18. Code present but not on a RIG-Video path

Unused code was removed on 2026-11-25 (old daily-pipeline helpers, the older wall-photo picker, the old upload step,
the captions overlay, the profiler node, an experimental patch). What remains off the RIG-Video path is only the
command-line entry of files whose functions are imported:

| Code | Note |
|---|---|
| `make_master.py`, `assemble_hybrid.py`, `assemble_novo.py` as scripts | Only their imports are used |
| `build_main.py` as a script (`build_main.py story.json out/ [variant]`) | Production goes through `build_st.py` |
