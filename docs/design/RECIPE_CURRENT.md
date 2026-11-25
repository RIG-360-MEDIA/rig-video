# CURRENT PRODUCTION RECIPE: read this first (locked 2026-10-06)

> This is the authoritative recipe for the single-anchor 60 s news video. It **supersedes** the step/LoRA/speed
> settings in `H3_MAIN_VERSION_LOCKED.md`. That document stays the reference for prompt format, the Picture-reference
> rule, colour-lock and graphics. Approved by the user on 2026-10-06: "no visible cuts, overall good, we keep this
> method."

## The recipe in one table

| Part | Setting |
|---|---|
| Install | ComfyUI **v0.38.1** test install `~/anchor-studio/repos/ComfyUI-v038` (input/ symlinked to production), started with `--disable-comfy-compiler`. Chain pack **0.5.11** (`ComfyUI-MiniMaxH3-Context-Loop-0511`, copied from production). The newer 0.7.x pack drops `MiniMaxH3ChainPolicy`; do not use it with this graph. |
| Model | `minimax_h3_ref2va_pruned_int8_convrot`, `comfy kitchen attention`, 1280×736, 24 fps |
| **Seed** (1 shot, 328 frames) | **20 steps**, `res_multistep` / `simple`, sigma shift 12/3. FirstBlockCache **H3 Fast 0.10**, plus `H3SparseAttentionOverride` (tau 1.0, window 0.40–1.0, dense blocks 0-2/47-49). Anchor voice on the **seed only**, via the flat key `ref_audios.ref_audio_0`. |
| **Chain** (3 shots × 328 frames, 39-frame overlap) | **8 steps**, `lcm` / `beta`, sigma shift 12/3, LoRA **`MiniMax-H3-Ref2VA-Acc-8Step_pruned_comfy.safetensors` at strength 1.0** (Kijai, `Kijai/MiniMax-H3-experimental`, in `models/loras`), sparse attention override as on the seed. Continuation `audio_feathered_av`, context 39, `generated_audio`, `prepend_original=True`, **no `ref_audio` on the chain**. |
| Post | colour-lock (per-shot HSV) → wall composite (story photos, auto-located wall) → `lt_remotion` lower third, ticker, location tag, logo → DNL outro. Final duration 61.6 s. |

## Measured time (trijya-7, RTX 4090 at its locked 250 W cap)

| Stage | Time |
|---|---|
| Seed: sampling 10:25, plus about 1 min load/encode/decode (warm) | **~10.7 min** (about 13.4 min if it is the first job after ComfyUI starts) |
| Chain: 3 shots × (8 steps × ~57 s + ~45 s overhead) | **~24 min** (24.8 min measured, including ComfyUI start) |
| **Complete video, seed rendered fresh every time** | **~35 min warm; ~38 min for the first video of a session** (was ~61 min) |
| Post (CPU, runs in parallel with the next render) | ~10 min on the Mac; adds nothing to GPU time |

## Quality evidence (same seed, 2026-10-06, `output/full/naza_v2_t8kf` vs `naza_v2_v7`)
- **Voice match to the locked voice, per shot:** 0.93 / 0.86 / 0.80 / 0.75 for this recipe, against
  0.93 / 0.85 / 0.80 / 0.76 for the old 20-step recipe. The same chain-inherent drift; no added loss.
- **Speech accuracy (word error):** 0.8% here, 1.6% before.
- **Face sharpness:** 331 here, 320 before.
- **Colour drift after colour-lock:** under 1% in both.
- **Seams:** 2.11 / 1.93 / 1.82, against 1.36 / 1.34 / 1.60 before. The user saw no cuts.
- **Shot-1 continuity** (first new frame against the seed's last frame): 36.8 dB, against 38.2 dB for the old recipe.

## Why this works, and what NOT to do (all measured)
- **Origin:** the chain pack's own chain workflow is lcm + beta + **8 steps + an accelerator LoRA**. The old
  production chain had kept lcm/beta but run 20 steps with the turbo LoRA at strength 0, so every chain shot cost
  17 min.
- **FirstBlockCache cannot skip chain steps with lcm.** lcm re-noises every step (cached 0/20). It still works on
  the seed (res_multistep): 7/20 steps cached.
- **Do not switch the chain sampler** (res_multistep, euler, any beta/simple combination, `guide` mode). Every one
  was tested, and every one ignores the previous shot and invents a new framing (10 dB continuity). Only lcm keeps
  continuity with this pack and graph.
- **Do not use the official `minimax_h3_fl2v_turbo_8step_v1.0` LoRA.** It is built for the FL2V model and causes a
  close-up jump-cut at each join. The old `ref2v_turbo_4step_v0.1` was rejected for quality earlier.
- **Do not reuse the chain FBC node expecting a gain.** It is harmless but skips nothing under lcm.
- **Rejected by the user:** 16-step seed. Lossy quants (w4a8, w6a8, nvfp4, ClipProj 4B text encoder) are excluded
  by the zero-quality-loss rule. SageAttention 1/2 were slower than kitchen int8.

## Next speed step (not yet done)
- The LoRA currently costs about 11 s per step, because it is applied on the fly every step (57 s against 46 s).
  Merging it into the weights once should bring the chain to about 20 min and the full video to about 30 min. It
  must be re-checked with the same-seed A/B before adoption.

## Where it is encoded
- **Builder:** `pipeline/build_main.py`, variant `t8k` (seed = v7 settings, chain = the recipe above).
- **Daily system:** `ANCHOR_VARIANT=t8k` (`deploy/anchor-daily.service`).
- **Job/test scripts on trijya:** `~/anchor-studio/t8kf_run.sh`. Logs: `~/anchor-studio/full_run.log`.

## To be addressed: realism / new studio (paused by the user 2026-10-06 01:35 IST)
**Goal:** remove the "AI look" of the current tall-room renders.

**Issues found in `naza_v2_t8kf`:**
- Orange skin: LAB a 20 / b 22, saturation 165.
- Waxy skin and weak eyes and teeth. The face is only about 100 px tall in the wide shot.
- A sunset "postcard" set with glossy surfaces and glowing lights.
- The wall composite looks flat.
- The pose is very static.

**Decided:** move to chest-up framing in a neutral daylight studio, with the LED wall on the right with a clear gap
from the anchor.

**Tried so far:**
- **Text-only seeds** (`pipeline/templates/seed_newsroom_v2_prompt.txt`, Emre's identity frame as `<Picture 1>`):
  - Identity holds (0.91 vs registry Emre).
  - Much more realistic skin and lighting (a 17 / b 16, face 26% of frame height).
  - Composition is not controllable by text. Seed 42 hard-cut to a new angle at about 8 s, and seed 7 centred the
    anchor with no separate wall. **Rejected as a method:** composition must come from a plate.
- **H3 empty-studio plates** (`pipeline/jobs/plate_nr3_s{11,23,31}.json`, 124 frames each, about 3 min each):
  - Realistic and stable, with no cuts.
  - Layout is wrong: the chair is small and at the far left (backrest about 60% down the frame), and the screen runs
    off the right edge.

**User suggestion for the next run (2026-10-06):** keep these plates' look, and simply **reduce the screen size a
bit** so the whole screen sits inside the frame. Ask for "a slightly smaller screen, its right edge fully visible
inside the frame with some wall beside it". Variant 31 is the reference look.

**Plate round 2 (2026-10-10, 21:37–21:47 IST, `pipeline/jobs/plate_nr4_*.json`, frames in `output/plates_nr4/`):**
- Prompt change: the screen becomes "a medium-sized panel… all four edges and corners fully inside the frame, plain wall
  visible to its right"; B and C also ask for the chair "close to the camera, backrest about a quarter of the frame wide".
- A (seed 31, screen only), B (seed 31, screen + chair), C (seed 23, screen + chair). 124 frames each: 4.6 / 2.5 / 2.5 min.
- **Result:** the screen now sits fully inside the frame with its right bezel and a strip of wall visible in all three,
  and every clip holds a steady frame from start to end. The variant-31 look is kept in A and B. The chair barely grew
  (backrest top about 63% down in B instead of about 65%); text alone does not move the camera closer.
- Recommended plate: **B** (`plate_nr4_s31b`).

**Next steps when resumed:**
1. Fix the plate layout, either by rephrasing with relative geometry ("chair close to camera filling the lower-left
   third; screen a smaller panel fully inside the frame") or by an image edit/reframe of the best plate frame.
2. Seed = plate as `<Picture 1>` + identity as `<Picture 2>` + "one continuous static shot, no cuts", with 2–3
   candidate seeds.
3. Add a post grade: skin-tone correction (prototype moves a/b from 20/22 to 12/15), about −10% saturation, and fine
   grain.

The current production recipe above is unaffected and remains in use.
