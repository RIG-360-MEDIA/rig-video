# VO-only 9:16 converter: repo research (2026-11-19)

Goal: turn any found clip (16:9, square, vertical, pillarboxed, letterboxed) into a good 1080×1920 shot without the footage checker,
for any footage type. Code-level reviews: findings_A (auto-vertical-reframe family), findings_B (pyautoflip, ai-video-reframing,
FrameShift, AutoFlip), findings_C (clipper layout engines), findings_D (wider search + licence-safe parts).

## Verdict
No single repo works as it stands. All of them, in some footage situation, crop blindly, crash or drift, and most rely on
AGPL (Ultralytics YOLO) or non-commercial (InsightFace) models. Recommendation: one converter built on the most complete MIT
engine, with the missing pieces taken from other repos as code or as ideas, and every model licence-safe.

Base: **mutonby/openshorts reframe engine (MIT)**. Its per-shot layouts are track, blurred-background fit and split. It
passes vertical input through, renders on the GPU (NVDEC→CUDA→NVENC) and outputs per-frame crop data. Remove YOLOv8
(AGPL fallback) and Gemini (optional picker).

| Stage | Part | Source / licence |
|---|---|---|
| 0 Prepare | constant frame rate; black/uniform bars via ffmpeg cropdetect; blurred side bars via a small custom check; vertical passes through; stills via freezedetect | ffmpeg; ours |
| 1 Shots | TransNetV2 (+ PySceneDetect fallback) | MIT / BSD-3 |
| 2 Signals | faces YuNet; people/objects RF-DETR N/S/M + roboflow/trackers ByteTrack without ReID; saliency PAVEN or UNISAL for shots with no person; text boxes RapidOCR, with persistent same-place text treated as an overlay (reelsaw idea, re-implemented) | MIT / Apache |
| 3 Layout per shot | TRACK (ai-video-reframing director maths / wide2short spring); LOCKED crop per shot (KazKozDev movie mode); FIT on blur (graphics, crowds, wide, stills, low confidence); SPLIT (strict gate: 2 faces, each at least 4.5% of width, at least 20% apart, together at least 50% of the time, shot at least 2.5 s); SWEEP / slow push-in (AutoFlip, wide shots with no subject, stills) | MIT code + ideas |
| 4 Confidence | share of the salient mass inside the chosen window (SmartVidCrop idea) + detection success rate (AutoFlip); low → FIT | ours |
| 5 Output | AutoFlip-style JSON: per-frame crop + per-shot mode/reason/confidence; single-pass NVENC 1080×1920 (darkvertex writer) | MIT |

Licence traps: Ultralytics YOLO/YOLOE (AGPL), InsightFace/SCRFD weights (non-commercial), ViNet-S/HD2S (non-commercial),
DEIMv2 (no commercial use), RF-DETR Atto/Femto/Pico/XL/2XL (Roboflow licence), roboflow/trackers default ReID (MOT17),
BoxMOT (AGPL), Autocrop-vertical and VSOR (no licence). Open: Google patent US8531535B2 (camera-path cropping, listed
active until 2031) needs a counsel check; DeepGaze licence is conflicting between sources.

Next: golden-set criteria (about 50 Q&A, written before building), then a prototype run on real, varied clips (GPU go needed).
