# Findings D: wider search + licence-safe components (research agent, 2026-11-19). [V]=primary page read, [S]=secondary, [U]=unverified
A) New whole tools: none handles the full news mix; nearly all are face/speaker clippers.
- BayesCrop (WACV 2027, arXiv 2611.09100, UT Austin LIVE + YouTube): multi-crop reframing 112 FPS; repo steven413d/BayesCrop placeholder [V].
- LIVE-YT-VideoCropping (arXiv 2604.24947): dataset of 1,800 user videos with per-frame portrait crop boxes from 90 people; models "coming soon"; licence unstated [V]. Possible answer key for evaluation.
- VSOR: no LICENSE = all rights reserved [V]. RAVA: no code [V].
- Small permissive repos for ideas: arkevo/Frametage-Encoder-Autoframer (Apache: person+face+PP-OCRv3 title-card detection, per-shot reset, centred when nobody) [V]; MakersMCP/reframekit (MIT, no ML: motion/detail scores, per-shot move-vs-hold planner, dissolve detection, pad when too wide) [V]; GrepCut/OpenClipper (MIT, AutoFlip path-solver port, but SCRFD) [V].
- Avoid: ColinGPT9/clips-studio AGPL; ialakey/shorts-factory custom licence; obi19999/smart-video-reframe suspicious zip download.
- Successors: KazKozDev 3 forks 0-1*; fralapo continues in clippyme (YOLOv8 AGPL); pyautoflip active but InsightFace; HF Spaces nothing substantial.
B) Components:
- Cuts: TransNetV2 (MIT, weights in repo) [V]; PySceneDetect 0.7.3 BSD-3 [V].
- Detection: RF-DETR N/S/M/L + seg (Apache; Seg-L 47.1 AP @ 8.8 ms T4) [V]; D-FINE, DEIM v1 Apache [V].
- Tracking: roboflow/trackers Apache (ByteTrack/OC-SORT/BoT-SORT) without default ReID [V]; SAM 2.1 Apache, 39-91 FPS A100 [V].
- Faces: YuNet MIT (2026 dynamic-shape) [V]; MediaPipe BlazeFace Apache [S]. Pose: RTMPose/rtmlib [U].
- Saliency: PAVEN (MIT, 2025, ViNet-based, 13 eye-tracking sets) [V]; UNISAL Apache, archived [V]; ViNet 2020 MIT code [V].
- Open-vocab: LLMDet Apache [S]; Grounding DINO Apache [V]; OWLv2 Apache [V]; Florence-2 MIT (+OCR boxes) [V].
- OCR boxes: RapidOCR Apache [V]. Bars: ffmpeg cropdetect black/uniform only [S]; blurred side bars need custom check. Stills: ffmpeg freezedetect.
- Camera path: AutoFlip solvers, reframekit planner, L1 optimal path. Google patent US8531535B2 (camera-path cropping) listed active to 2031-08-25 [V]: needs counsel check.
Traps: DEIMv2 no commercial use [V]; RF-DETR Atto/Femto/Pico/XL/2XL/NAS Roboflow licence (enterprise for self-host) [V]; roboflow/trackers default ReID trained on MOT17 (non-commercial) [V]; BoxMOT AGPL [V]; SCRFD non-commercial [S]; YOLO-World GPL, YOLOE AGPL [S]; SAM 3 Meta licence (commercial OK, bans military/weapons) [V]; DeepGaze, SalFoM no licence found [V] (agent A found MIT LICENSE in the DeepGaze MR repo: conflict, recheck); HD2S non-commercial [S]; D-FINE Objects365 checkpoints dataset terms [V].
Commercial quality bars: AWS Elemental Inference smart crop, Amagi NewsPulse, Opus Clip API.
