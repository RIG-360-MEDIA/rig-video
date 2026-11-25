# VO-only clip checker: rulebook and criteria (draft for review)

**Drafted by persona:** a senior news video editor with 20 years of experience.
- Desks: wire agency, broadcast and digital explainer.
- Has cut voice-over packages in every domain: war, disaster, crime, politics, business, tech, science, health, sport,
  entertainment.
- Usually works from footage other people shot: agency feeds, other channels' packages, handouts and social video.

**What this is:** the questions the checker must answer the way a good editor would. It is criteria, not a clip test
set. It comes from three reference videos the user chose, each watched shot by shot against its narration:
- Times Now, IRGC strike on a Bahrain radar (war)
- CNBC-TV18, Madison Huang at Nvidia: full-screen voice-over, the closest to our format
- BBC News, Nvidia board on Jensen Huang: anchor plus library pictures

**The one idea:** the checker is an editor, not a filter.
- The footage search already finds plenty of material: about 50 camera shots per beat.
- The checker decides which few of those shots play, in what order, and for how long. Each beat's length must be
  covered with pictures of its main point, and the whole story must flow from beat to beat.
- Checking each shot on its own is only the first gate.

Each item has an **answer** and **how we check it**. Numbers are starting values.

---

## A. Material: what we may use

**1. What may go on screen?**
Anything a news channel already shows in its own clips:
- camera footage
- interviews and speeches
- photos, including the slow-zoom stills other channels use for people with no video
- screenshots of social posts and newspaper headlines
- handout and CCTV video, drone and phone video
- film and trailer clips (entertainment stories)

We use what others already show instead of sourcing it ourselves. We source our own images only when the clips have
nothing for a line.
*Check:* a shot is never rejected just for being a still or a screenshot.

**2. What never goes on screen?**
- Another channel's presenter or reporter talking to camera, and its studio set.
- Its branded parts: title cards, promos, end cards, "subscribe" screens.
- Maps and charts, which carry the other channel's lines and design (see [[ndc-maps-no-lines]]).
- Footage of a different event dressed as this one.

*Check:* kind = `presenter`, `studio`, `promo`/`title card`, `map`, `chart` → out.

**3. Is a still or screenshot as good as footage?**
No. Moving footage of the subject wins when it exists. A still is right when:
- it is the only picture of a named person or document, or
- the line is about the post or headline itself ("he wrote on X", "according to the New York Times").

*Check:* when ranking, moving footage beats a still of equal fit. A still that is the post the line quotes is a top
fit.

**4. Are logos, tickers and burned-in captions a problem?**
Corner logos and tickers are cropped by the 9:16 converter. Burned-in captions and subtitles may stay. A banner that
covers the subject is a defect.
*Check:* the converter handles overlays. No shot is rejected for how much text it carries: posts, headlines and news
text are material (item 1). The checker reads the on-screen text (OCR) to tell this story from another one.

**5. How old may footage be?**
- An event line ("the strike hit the bridge today") wants footage of this event. A video uploaded more than about 3
  days before the event cannot show it.
- An archive line (a person, place, company or thing) takes footage from any date.

*Check:* event beats drop videos uploaded before event −3 days.

---

## B. One beat: what fits

**6. What should the picture show?**
The subject of the sentence, in this order:
1. **A named person → that person.** Madison → Madison; Ian Buck → Ian Buck, even a portrait photo.
2. **A named place → that place.** Strait of Hormuz → tankers in the strait; "the company" → its HQ, logo and products.
3. **An action → the same action, by the right side.** An Iranian strike → Iranian launches, not US ones. "US forces
   ready" → US carriers.
4. **A thing → that thing.** "Investments in robotics" → robots at the company's booth.

*Check:* the pick prompt names the beat's subject. A shot of the wrong person or the wrong side fails even if it is the
right topic.

**7. The event itself was never filmed (a phone call, a board decision, an argument in an office). What then?**
Show footage of the people or place involved, in public settings (arrivals, stages, buildings). This is what every
channel does; all three references do it.
*Check:* for a "not filmable" beat, a shot of the right subject is a full fit.

**8. The line is abstract (politics, demands, outlook, "what this means").**
Stay on the story's own footage: its main people, its place, its aftermath. Don't cut to an unrelated literal picture.
*Check:* abstract beats rank story-subject shots highest. Generic stock-like pictures (handshakes, money, keyboards)
rank low.

**9. Does the mood have to match?**
No. The subject comes first. In the CNBC reference, Madison smiles over "yelled at colleagues". Never pick a picture
that contradicts the line's fact (a calm, intact bridge for "destroyed bridge").
*Check:* a mood mismatch is no defect; a factual contradiction is.

**10. What is the best possible shot for an event beat?**
The moment itself: the strike, the collapse, the rescue. Then its direct aftermath: the bridge in ruins, the rescued
crew. Both are top fits. Before/after pairs ("the strike, then the bridge in shambles") are ideal.
*Check:* the pick may combine an action shot and an aftermath shot for one beat, in that order.

**11. Footage of a similar but different event (another strike, another flood)?**
Never shown as this event. For an archive beat ("the region is prone to floods") it is allowed only when the line makes
clear it is a past event.
*Check:* the date window (item 5) plus the pick prompt's "same event" test for event beats.

---

## C. One beat: how many shots and how long

**12. How long is a shot on screen?**
- 2–5 s for action and fast stories (war, disaster, crime, explainers): the CNBC reference averages 3.3 s.
- 4–8 s for slow or library pictures (business, science, culture).
- Never under 1.5 s.
- Rarely over 8 s, unless the shot is the single strongest picture and keeps changing (a long collapse).

*Check:* the assembler cuts shots longer than the beat needs. It never stretches a shot or slows it down.

**13. How many shots per beat?**
1–3 for a 6–12 s beat. Change picture when the sentence's subject changes ("Madison… her father…" → Madison, then
Jensen).
*Check:* about 1 shot per clause, 2–3 s minimum each.

**14. Where do cuts go?**
On phrase breaks in the voice-over: commas, full stops, a new subject. About 3 in 4 of the reference's cuts land on a
phrase break.
*Check:* the assembler snaps cuts to the voice's phrase boundaries (word timings) when it has them. Otherwise it splits
by clause word counts at 2.6 words/s.

**15. Which part of a long shot?**
The part that shows the subject clearly. Skip the first and last 0.3 s, which carry cut fades and wobbles. For an event,
the part where the action happens.
*Check:* the assembler takes the middle of the shot unless the pick names a better moment.

**16. Not enough good shots to fill the beat?**
Fill in this order:
1. A second, different shot of the same subject.
2. Hold the best shot longer, up to about 8 s.
3. Reuse a strong shot from earlier in the story (item 20).
4. A general picture of the story's main subject.
5. Our own sourced image.

Never fill with a near-miss of the wrong subject.
*Check:* the edit list marks each fill step it used. A beat that reached step 4 or 5 is flagged for review.

---

## D. The whole story: flow

**17. What makes a sequence flow?**
- The picture follows the subject of each line.
- The story's main people and place keep coming back, so the viewer always knows whose story it is.
- Changes of location are fine. The flow comes from the subject, not from the location.

*Check:* across the story, at least half the shots show the story's main subject (person, place or company).

**18. Order inside an event?**
Chronological: cause before effect, the strike before the ruins, arrival before the speech. Two shots from the same
video keep their original order.
*Check:* the assembler sorts a beat's shots from one video by their time in that video.

**19. Can neighbouring shots look alike?**
Two shots in a row must not be the same picture: the same frame from a re-upload, or a near-identical angle. Two
angles of the same scene are good coverage.
*Check:* a near-duplicate test between neighbouring shots (picture hash plus embedding similarity).

**20. Can a shot be reused?**
Yes, as the references do (2–3 times in a 3-minute piece), but not within about 30 s of its last use. Never the same
shot twice in one beat.
*Check:* the assembler blocks reuse closer than 30 s.

**21. Should one source dominate?**
No share cap (user, 2026-11-22). The best footage plays, however much of it comes from one video or one channel. A
cap would force weaker videos in and leave good footage out. Variety comes from items 19 and 20: no repeated picture
in neighbouring shots, and no reuse too soon.
*Check:* none in the assembler; the pick ranks by fit only.

**22. How does the story open and close?**
- Open on the strongest picture of the main event or subject.
- Close on the main subject or the aftermath, not on a side person.

*Check:* the first beat's first shot is that beat's top pick; the last beat ends on main-subject footage.

---

## E. Speed and machines

**23. How long may the checker take?**
Target: under 3 minutes per story, after downloads. Model calls should be about one per beat plus one for the whole
story, not one per shot.
*Check:* `timing.json` per run.

**24. Where does it run?**
trijya-7 (user, 2026-11-21: the vision model may move to t7 for speed), on the 4090, idle most of the time. The model
server sleeps when idle, which frees the GPU for renders. trijya-8's copy is the fallback.

---

## F. How the checker works (design these criteria drive)

1. **Gate (no model):** split videos into camera shots of at least 1.5 s; drop repeated pictures. Stills stay.
2. **Pre-rank (SigLIP-2 embeddings):**
   - Score each beat's text and wanted picture against every shot in the story's pool. The pool is every video any beat
     found, checked whole; the search's moments are a bonus, not a limit.
   - Keep the top ~10 per beat, at most 3 from one video.
3. **Pick (Qwen3-VL, one call per beat):**
   - The model sees the beat, its neighbours and the candidates side by side, each at its own size.
   - It marks unusable kinds and chooses 1–3 shots that show the beat's main point, in order.
   - Comparing candidates side by side replaces the old 0–3 score per shot, which scored 79 % of shots "3".
4. **Assemble (code):** fill each beat's length, cut on phrase breaks, keep event order, keep neighbouring shots
   different, apply the reuse limit.
5. **Review (Qwen3-VL, one call per story):** a contact sheet of the finished edit (one frame per cut, its line under
   it). Flag shots that don't fit, then swap them for the next candidate.

**Output:** an edit list per story: for each beat, `[{video, start, end, kind, why}]` with durations that sum to the
beat's length. It also writes a contact sheet for review by eye.

---

## Answers from the user (2026-11-22)

- Dates on screen are allowed in RIG-Video (the no-dates rule was NDC only).
- **Q1:** the pace in item 12 is right.
- **Q2:** no share cap per video or channel (see item 21).
- **Q3:** our own sourced images come in automatically (item 16 step 5).
