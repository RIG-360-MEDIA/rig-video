# Converter v1: fixes 1–3 (2026-11-20 IST, t7)

Code: anchor-studio-dnl `pipeline/tools/vertical/vconv.py` (v1). Review video: RIG-NEWS-AI- `reports/vertical_v1/review_v1.mp4`
(30 clips, 9.5 min). Clips 1–16 are the v0 clips; clips 17–30 are a fresh random draw (seed 20) from other videos, so the fixes
are not tuned to the first 16. Magenta boxes on the left panel = areas blurred in the output.

Result: 136 shots. LOCKED 76, FIT 55, PASS 3, SPLIT 1, TRACK 1. No crashes.

## What changed
1. **Text cut by the crop (Q27, Q29).**
   - OCR runs on 6 frames per shot. Any text line a crop edge would cut through is covered by a soft blur.
   - Channel graphics (ticker, lower third, subtitles, timestamp) get a full-width band. A graphic is text in the top 22%
     or bottom 40% of the frame that is on a pixel-stable overlay or at the same height in most samples.
   - Scene text gets a blur over its own box. Scene text ≥ 6% of the frame height sends the shot to FIT instead.
   - Then a check: OCR on up to 4 output crops (patches applied, 2× up). Any text touching a crop edge gets patched too.
   - Graphics no longer count toward "text-heavy" (fix 6, partly).
2. **Picture-in-picture people (Q16, Q21).**
   - A still person at the same spot in two shots with different surroundings is an inset (interpreter, reporter box).
     Same spot with the same surroundings is the same camera (interview A-B-A) and is left alone.
   - An inset is never a subject, its saliency is ignored, and a crop may never cut through it: the crop moves clear or
     the shot goes to FIT.
   - A still person in a moving scene (poster, screen) is demoted, not removed.
3. **Ranking (Q16, Q22).**
   - Subjects are scored by size + saliency mass + presence + centrality.
   - A subject that is not big (≥ 8% of the frame, a person ≥ 35% of the height, or a face ≥ 4% of the width) only wins
     if its window holds ≥ 80% of the best saliency window's share. Otherwise saliency decides.
   - Every crop must keep ≥ 35% of the shot's saliency, else FIT. Confidence = hit rate × min(1, kept share / 0.6).

## Found and fixed during the run
- **OCR read textures as text** (fire, steel frames, aerials): boxes up to the full crop height, so outputs were fully
  blurred. Fix: score ≥ 0.6, wider than tall, and either ≤ 10% of the image height or ≥ 3× wider than tall (two-line
  lower thirds on a plate stay in).
- **Subtitles at 60–70% of the height were treated as scene text**, so an interview went to FIT. The graphic zone now
  starts at 60%.
- **Split-screen layouts (France 24 reporter box + B-roll):** the crop straddled the inset. Fixed by the inset-safe
  windows above.

## Still open
- Speed: 17–111 s per 20 s of clip (median ~35 s, target ≤ 10 s). OCR is now heavier. Fix 7.
- Blur bands are visible as soft smears at the bottom of many crops (the source's graphics). Accepted under Q30; judge in
  review.
- Fixes 4 (pillarbox per shot) and 5 (blank shots) not done yet.
