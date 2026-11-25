# Golden set: VO-only 9:16 converter (draft for review)

**Drafted by persona:** a senior vertical-news video editor who has also built automatic reframing systems. Ten years cutting
news for broadcast and for Shorts/Reels/TikTok, plus a computer-vision engineer's view of shot detection, detection and
tracking, saliency, OCR and GPU video pipelines. The editor's eye decides what "good" looks like; the engineer's eye makes
every answer measurable.

**What this is:** the questions the converter must answer correctly in production, written before it is built. Nothing
here names a footage type to tune for. Every rule must hold for any clip the search returns. Testing runs real, varied
clips against these answers. There is no fixed clip test set.

**System under test:** clip in → 1080×1920 shot out. Five models: TransNetV2 (cuts), RF-DETR (people and objects), YuNet
(faces), PAVEN/UNISAL (saliency), PP-OCR detection via RapidOCR (text boxes). Plus ffmpeg checks and our own layout,
camera and confidence logic. Layouts: TRACK (follow a subject), LOCKED (one fixed crop per shot), FIT (whole frame over
a blurred copy of itself), SPLIT (two stacked crops), SWEEP (slow pan or push-in).

Each item has an **answer** and **how we check it**. Items marked **[DECIDED]** were open questions, settled on 2026-11-19
for long-run production with as little user intervention as possible. The numbers are starting values, calibrated on
real, varied clips; they are never tuned to particular clips.

---

## A. Output contract

**1. What exactly does the converter output?**
A 1080×1920 H.264 (High profile) MP4, square pixels, BT.709, no audio track (VO and foley are added later), with the same
frame rate and frame count as the normalised input. Plus a JSON sidecar: per-shot mode, reason, confidence and crop
window, and a per-frame crop path.
*Check:* ffprobe on every output; JSON schema validation; frame count = input frame count.

**2. Does the output keep the clip's exact timing?**
Yes. Same duration to ±1 frame, same cut positions to ±1 frame. VO timing, foley and the clip joins all depend on it.
*Check:* output duration and cut times match the input's.

**3. What frame rate is delivered?** [DECIDED]
Constant 24 fps, converted once at the input stage: the same rate the final video assembly already uses (`worker.py`
render steps run at fps=24; only the site's small preview clips are 25). One rate means
the clip joins, the VO and foley timing and the encode never deal with mixed or variable rates. Mixed rates are a classic
source of drift and stutter, and fixing them later would need a person.
*Check:* constant frame rate in every output; no duplicated or dropped frames beyond what the conversion requires.

**4. What quality is the encode held to?**
Visually lossless relative to the cropped source: CRF ≤ 18 (or the NVENC equivalent), one encode only. No intermediate
lossy files.
*Check:* VMAF of the output against the same crop rendered losslessly ≥ 95.

**5. What happens to clips that are already 9:16 (or narrower)?**
They pass through: scaled to 1080×1920 with no crop, or FIT if they are narrower than 9:16. Never cropped, never zoomed.
*Check:* input aspect ≤ 9:16 → mode PASS or FIT, with the crop window = full frame.

## B. Input handling

**6. Which inputs must be accepted without failing?**
Any container or codec ffmpeg can decode, any aspect ratio (landscape, square, portrait), constant or variable frame
rate, interlaced, rotated (rotation metadata applied), 8/10-bit, any length the search produces.
*Check:* corrupt or undecodable input fails cleanly with a reason; every decodable input gives an output.

**7. How are black bars inside the frame handled (letterbox / pillarbox)?**
Detected first (ffmpeg cropdetect, checked across the whole shot, not one frame) and removed before anything else, so
bars never appear in the output and never steer the crop.
*Check:* no output frame has a uniform band ≥ 2% of width or height that the source picture doesn't have.

**8. How are blurred side bars (a vertical phone clip placed in a 16:9 frame) handled?**
Detected (sharpness and mirrored-content check on the side regions) and removed. The sharp centre is treated as a vertical
clip and passes through or goes to FIT.
*Check:* the blurred copy is never chosen as the subject; output shows only the sharp picture.

**9. What is the lowest source resolution allowed to be cropped?** [DECIDED]
A crop may be upscaled at most 2.0×. Above that the shot uses FIT, which keeps the full width and is sharper. A 1080p
source gives a 608 px wide crop (1.78×, fine). A 720p source gives 405 px (2.67×), so FIT. Anything lower is always FIT.
**Found 2026-11-19:** the clip cutter downloads **at most 720p** (`social_verifier backend/app/footage/clips.py:45`,
`bv*[height<=720]`). With that, the converter could never crop, only FIT.
**Decision:** for VO-only stories the cutter fetches the best available height up to 1080p, falling back to lower when
the source has nothing better. No AI upscaling: an extra model and invented detail, which is risky for news.
*Check:* logged upscale factor ≤ the limit in every TRACK/LOCKED/SWEEP shot.

**10. What happens with interlaced or very noisy sources?**
Deinterlace at input (bwdif). No extra denoise or sharpen beyond a light sharpen after upscaling. The converter never
"restores" footage.
*Check:* no combing artefacts in output frames from interlaced sources.

## C. Shots and cuts (TransNetV2)

**11. Is every decision made per shot?**
Yes. Layout, subject and camera path are decided per shot. Nothing carries across a cut except a soft preference to
keep the same subject when it appears in the next shot.
*Check:* the crop path has no motion that spans a cut.

**12. What happens at a hard cut?**
The crop jumps on the cut frame itself: no easing into the new shot, and no frame of the old crop on the new shot.
*Check:* the crop changes within ±0 frames of a detected cut.

**13. What happens at dissolves, fades and wipes?**
Treated as a transition zone. The crop holds steady (or interpolates between the two shots' crops) through the
transition and never pans during it.
*Check:* no crop movement inside a detected transition.

**14. How short can a shot be and still get its own decision?**
Shots under 0.5 s inherit the neighbouring shot's mode and crop when the content allows. Otherwise they use FIT. No
flicker from tiny shots.
*Check:* no layout change lasting < 0.5 s.

**15. What if cut detection misses a cut?**
The shot's tracking breaks (the subject disappears or the scene changes completely). The converter must notice the scene
change from frame similarity and split the shot anyway.
*Check:* sudden full-frame changes with no detected cut are logged and handled as cuts.

## D. Subjects: people and objects (RF-DETR, YuNet)

**16. Who or what is the subject of a shot?**
The most important visible thing, ranked by: faces and people (larger and more central first), then large moving
objects, then saliency. One primary subject per shot; a second one only for SPLIT or a two-shot that fits.
*Check:* human review: the subject chosen is the one an editor would choose in ≥ 90% of shots.

**17. How is a person framed?**
The head and upper body are fully in frame. Eyes about a third of the way down the frame. Nobody is cut at the eyes,
mouth, chin or forehead. Looking room is on the side the person faces.
*Check:* face box fully inside the crop in 100% of frames where the subject's face is detected.

**18. What happens with two people who fit in one 9:16 crop?**
Frame both (a two-shot), balanced.
*Check:* both face boxes inside the crop.

**19. What happens with two people who don't fit?**
SPLIT only if all of these hold: both faces are ≥ 4.5% of frame width, they are ≥ 20% apart, both are on screen ≥ 50%
of the shot, and the shot is ≥ 2.5 s. Otherwise FIT.
*Check:* no SPLIT that violates the gate; no crop that shows the empty gap between two people.

**20. What happens with three or more people, or a crowd?**
If one person clearly dominates (much larger or central), frame them. Otherwise LOCKED on the densest area if it carries
the meaning, or FIT. Never zoom onto one random face in a crowd.
*Check:* human review of crowd shots: no random-face zooms.

**21. What about faces that aren't real people (posters, photos on a wall, TV screens, statues)?**
Faces that don't move for the whole shot while the scene moves are demoted. They can still be the subject if nothing
else is.
*Check:* static faces in a moving scene are never chosen over a moving person.

**22. How are non-human subjects handled (vehicles, buildings, aircraft, ships, wreckage, animals)?**
RF-DETR objects within its classes; anything outside its classes falls through to saliency (section E). The largest,
most central or moving object wins.
*Check:* human review: the object chosen is the one an editor would choose.

**23. What happens when the subject leaves the frame mid-shot?**
The crop eases to the next subject or to the saliency centre over ~1 s. It never follows an empty spot.
*Check:* no frame where the crop points at a region with no subject and no saliency for > 1 s.

## E. Shots without a clear subject (saliency: PAVEN/UNISAL)

**24. What happens when no person or object is detected?**
Saliency decides. If ≥ 60% (proposed) of the shot's salient mass fits in one 9:16 window: LOCKED there. If the salient
area is wide: SWEEP slowly across it when the shot is long enough, else FIT.
*Check:* every subject-less shot has a logged reason for its mode.

**25. What happens with wide landscapes, aerials and skylines?**
These are the classic cases where the meaning is the width. FIT or a slow SWEEP. Never a tight static crop of a random
patch of sky or ground.
*Check:* human review: the output conveys what the wide shot showed.

**26. What happens with smoke, fire, water and other things without a clear edge?**
Saliency (not detection) leads. The crop goes on the strongest motion or contrast region, held steady. No chasing of
flickering flames.
*Check:* crop motion stays under the speed limit (item 31) even when saliency flickers.

## F. Text, graphics and overlays (PP-OCR detection)

**27. Can the crop cut through on-screen text?**
No. A text line is either fully inside the crop or fully outside it. Partly cut words never appear.
*Check:* no text box crossing the crop edge in any output frame.

**28. What happens with text-heavy frames (maps, infographics, slides, title cards, documents, screen recordings)?**
FIT. Text must stay readable at phone size.
*Check:* the OCR text share of the frame ≥ threshold (e.g. 8%) → FIT.

**29. What about channel logos, tickers, lower thirds and burned-in captions?**
Text that stays in the same place across the shot (or across shots) is an overlay. The crop prefers windows that leave
it out. FIT keeps overlays visible, as the source has them.
*Check:* in TRACK/LOCKED, overlays are outside the crop in ≥ 90% of shots where that's possible without losing the subject.

**30. Should another channel's logo or watermark ever appear in our output?** [DECIDED]
No, wherever it can be avoided without hiding the story. This matches today's clip treatment (the smallest crop that
removes overlays).
- TRACK/LOCKED: windows that leave persistent logos and tickers out are preferred.
- FIT: first the smallest trim of the frame edge that removes persistent corner logos and tickers, as long as the trim
  removes ≤ 15% of width or height. Otherwise the logo area alone is covered by a soft blur patch.
- Burned-in captions (spoken words) may stay, as with today's treatment.
Logos are found as regions that stay the same across the shot (pixel stability), not only as OCR text, so picture logos
are caught too. Every trim or patch is listed in the JSON.

## G. Camera movement

**31. How fast may the crop move?**
At most 15% of frame width per second on average. Acceleration eased: no jerk, no snapping (except at cuts).
*Check:* the per-frame crop path is within the speed and acceleration limits.

**32. When should the crop not move at all?**
When the subject moves less than ~15% of the frame width over the shot: LOCKED (one crop for the whole shot). Most news
shots should be LOCKED. A steady frame looks professional; a busy one looks automated.
*Check:* share of LOCKED shots is logged; no movement under 2% of width (no jitter).

**33. Is the crop ever allowed to jitter?**
Never. Detector noise must not reach the crop: dead zone plus smoothing.
*Check:* no frame-to-frame crop change that reverses direction within 0.5 s.

**34. Should the converter zoom in and out?** [DECIDED]
No dynamic zoom inside a shot: it reads as automated. One fixed zoom per shot, chosen so the subject is well framed,
within the upscale limit (item 9). The only motion besides panning is SWEEP's slow push-in on stills.

**35. How is shaky handheld footage handled?**
Not stabilised by the converter (that's a separate, optional step). The crop must not add its own shake, so it follows
the smoothed subject, not the raw one.

## H. Stills and near-still shots

**36. How is a still image (a photo shown in the video, a frozen frame) handled?**
Detected by ffmpeg freezedetect. Then a slow push-in or pan across the subject (SWEEP), or FIT when the image is wide or
text-heavy. Never a dead static crop of a photo for many seconds.
*Check:* stills > 2 s always get SWEEP or FIT.

**37. What about near-still shots (a building, a podium, a static camera with little action)?**
LOCKED on the subject. That's correct for news; no artificial motion needed.

## I. Fallbacks, confidence and failure

**38. What is the confidence score and what does it mean?**
Per shot, 0–1, combining: the share of salient mass inside the chosen window, the detection success rate (frames with
the subject found ÷ all frames), and the upscale factor. Below 0.5 (proposed), the shot is forced to FIT.
*Check:* every shot has a score; human review agrees the low-scored shots are the bad crops.

**39. What is the universal fallback?**
FIT (the whole frame centred over a blurred, darkened copy of itself). It never loses information, so it is always
acceptable. Any error in any model for a shot → FIT for that shot, with the reason logged.
*Check:* a model crash or timeout never fails the clip.

**40. Can the converter ever fail a clip outright?**
Only for an input it cannot decode. Everything else produces an output (in the worst case, all FIT).
*Check:* in production, failures ≤ undecodable inputs.

**41. How does FIT look?**
The picture is scaled to 1080 wide and centred. The background is the same frame scaled to fill, Gaussian-blurred (strong),
darkened ~30%. There is no black.
*Check:* no black bars in any FIT output.

**42. Does a human ever have to fix a crop?** [DECIDED]
No. There is no manual step in the flow. Safety comes from the confidence fallback (item 38), not from review. The JSON
sidecar keeps a per-shot override possible later, but it is only built if production numbers show it is needed
(item 52's < 5% target is missed).

## J. Speed and resources

**43. How long may conversion take?**
On the 4090 (t7): ≤ 0.5× the clip's duration (a 10 s clip in ≤ 5 s), including decode and encode. A full 60 s VO-only
video's clips in ≤ 1 minute in total.
*Check:* timing per clip in the JSON; p95 under the limit.

**44. How much GPU memory may it use, and where does it run?** [DECIDED]
t7 (the 4090), with a hard budget of ≤ 4 GB VRAM for all five models together. In VO-only mode there are no anchor
renders, so the 4090 is mostly free, but an anchor render from another story can still be running. The converter starts
a clip only when free VRAM ≥ budget + 1 GB headroom, and otherwise waits. It never pushes a render out. t8's card is
nearly full while the clip checker runs (≈ 11.8 of 12 GB), and t3's runs the writer and the voice.

**45. Can it run several clips in parallel?**
Yes. Clips are independent; models load once and serve a queue of clips. No per-clip model reload.

**46. Can it start before all clips are found?**
Yes. Each clip converts as soon as it is cut, so conversion overlaps with the search.

## K. Licensing and safety

**47. Which licences are allowed?**
Code and weights MIT, Apache-2.0 or BSD only. No AGPL/GPL, no non-commercial weights (Ultralytics YOLO, InsightFace/SCRFD,
ViNet-S, DEIMv2, BoxMOT and Roboflow-licensed RF-DETR sizes are excluded). Every model file is pinned by checksum.
*Check:* licence list in the repo; build fails on an unpinned model.

**48. The Google camera-path patent (US8531535B2)?** [DECIDED]
Not a blocker for building. Our path logic is written and documented as our own (per-shot hold / ease / smooth with a
speed limit), and no code is copied from AutoFlip. A counsel check of the claims is required before public launch. That
is the one item here that needs a person outside engineering.

## L. Joined video (VO-only mode)

**49. Do neighbouring clips have to look consistent after conversion?**
Yes. No jarring switch between a tight crop and FIT on every clip. Prefer the same mode across neighbouring shots when
the content allows, and never alternate FIT/crop faster than every 2 s.
*Check:* human review of the joined video; logged mode changes per minute.

**50. Is anything placed over the converted video by the converter?**
No. Captions, lower thirds, ticker and branding are a later layer. The converter delivers clean picture, and its JSON
tells that layer where the safe areas are (e.g. not over the subject's face, not over kept source text).

**51. Where are the platform safe zones?**
The subject and any kept text stay inside the central safe area (top ~14% and bottom ~20% are covered by app UI on
Shorts/Reels/TikTok).
*Check:* the subject's face box is inside the safe area in TRACK/LOCKED shots.

## M. How it's judged

**52. Who decides if an output is good?**
An editor's review of real, varied clips with a fixed checklist from this document: subject kept, no cut text, no jitter,
no bars, cut-aligned, readable graphics, consistent joined video. Plus the automatic checks listed above on every
production clip. The share of shots needing human correction is tracked over time; target < 5%.

**53. What is never acceptable (zero tolerance)?**
A cut-off face of the main subject, black bars, text cut mid-word, a crop moving across a cut, jitter, a crash that loses
a clip, an output whose length doesn't match the input.
