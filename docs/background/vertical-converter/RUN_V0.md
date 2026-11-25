# Converter prototype v0: first run on real clips (2026-11-19, t7)

Code: anchor-studio-dnl `pipeline/tools/vertical/vconv.py` (+ `run_all.py`); on t7 `~/anchor-studio/vertical` (own venv).
Clips: 16 real search-matched moments from 15 stories, picked at random (seed 19), up to 20 s each, fetched at up to 1080p.
Review video: RIG-NEWS-AI- `reports/vertical_v0/review_v0.mp4`. Left: source with the crop box. Right: the 9:16 output.
Top: layout, confidence, reason.

Result: 57 shots. PASS 2, LOCKED 28, TRACK 1, FIT 26. No crashes after one fix (FIT background rounding).
Time: 18–37 s per 20 s of clip (target ≤ 10 s).

## What works
- Already-vertical clips pass through untouched (2/2).
- Close-ups of a speaking person (interview) give a good LOCKED crop.
- A big single object (the wrecked car) gives a good LOCKED crop.
- A vertical phone clip inside a 16:9 graphic was cropped onto its sharp middle.
- 720p-only sources go to FIT, as decided (4 clips; those videos have no 1080p).

## Golden-set failures found (to fix in v1)
1. **Text cut mid-word (Q27, zero tolerance).** Most cropped news shots: tickers, lower thirds, burned-in captions, CCTV
   timestamps. The crop is full height, so any band spanning the frame is always cut. Fix: in crop modes, cover each
   text band the window cuts through with a soft blur patch, or fall back to FIT when the band carries the story.
2. **Wrong subject: picture-in-picture people (Q16, Q21).** A sign-language interpreter in a corner inset was picked as
   "main person" in 6 shots (Turkish clip), so the explosion was cropped away. Fix: a person or face that sits in the
   same place across different shots is an overlay and is never a subject.
3. **Wrong subject: small person beats the event (Q16, Q22).** A small soldier was chosen over the wrecked car, and a
   person at the frame edge over the smoke plume. Fix: rank by size and saliency together; a person wins only when
   large or clearly the focus.
4. **Pillarbox detection runs once per clip, not per shot (Q8).** Phone clips inside a 16:9 frame mid-clip aren't
   detected.
5. **Blank or near-black shots** were LOCKED on nothing. They should be FIT or PASS.
6. **Text-heavy threshold (8%) is too eager:** a normal lower third pushes many shots to FIT. Tie it to fix 1.
7. **Speed** is 2–4× over target. Model calls run per shot, unbatched, and the render goes through Python.
