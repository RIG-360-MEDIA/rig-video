# RIG-Video footage: strategy before more code

Draft 1, 2026-11-16. This is a plan to agree on before building. No code changes until the decisions in section 7 are made.

## 1. What went wrong: patching instead of designing

We fixed one failure at a time on live stories: wrong country, then news reports, then the year, then upload dates. Each fix exposed the next gap. That happened because we never wrote down three things:

- **What counts as a correct shot.** The rules have only ever existed as code.
- **What must never appear on screen.** We had no hard list.
- **How we measure the system.** We had no test set, so every "fix" was checked on one story by eye.

## 2. Failure modes seen so far

These come from evidence in our runs: Bahrain, Hormuz, Ceuta, Japan, Aliağa, Brooklyn.

| # | Stage | Failure | Example |
|---|---|---|---|
| F1 | Search | No plain event query, and the headline was cut mid-word | "…Amid Escalat 2026" |
| F2 | Search | The keyword model drifts to generic or side topics | "June ceasefire memorandum Iran 2026" |
| F3 | Search | The brief we send the search backend says "news report. Events of {day}", so its relevance model judges videos as *title-card/map material* | v1 verdicts: "provides map footage needed for a title card" |
| F4 | Search | Nothing limits uploads to the event's dates, so old videos crowd out new ones | Feb 28 Era Tower video for a Nov 13 event |
| F5 | Event identity | Same place, different incident, accepted | NDTV Era Tower (Feb) passed as CONFIRMED raw |
| F6 | Event identity | The 3-day rule checks the *video's* upload date, but a same-day report splices in file footage | TOI Nov 13 report → "AP \| FILE" smoke shot |
| F7 | Facts | A shot contradicts the story: it shows damage when the story says no damage, or a strike when the story says interception | smoke over Manama; thermal boat strike |
| F8 | Place | A country is overturned on weak cues, such as uniforms or a flag in a raw clip | fixed 11-14, needs a regression test |
| F9 | Treatment | A frame that is mostly graphic or phone-format leaves too little picture after cropping | The Future Wire "BREAKING NEWS" vertical |
| F10 | Treatment | Burned-in subtitles, logos and tickers have to be cropped, and sometimes cropping can't remove them | Times Now subtitles |
| F11 | Supply | Footage of the event does not exist, as with an interception at sea at night | Bahrain: no interception video anywhere |
| F12 | Infrastructure | YouTube rate-limits captions (429) on the shared IP, and a stalled download held a search for 15 min | today 13:42–13:58 |
| F13 | Infrastructure | A full Windows C: drive on t8 stops WSL, and with it the checker | today 02:31 |
| F14 | Infrastructure | A tenant using the GPU on t3 or t7 | writer 11-14 |
| F15 | Model limits | The 8B vision model calls "same event" from titles that differ only by date | earlier Bahrain incidents |

The root cause behind F5–F7, F11 and F15: **one model opinion per video decides everything.** "Is this shot right for this story" is really five or six separate questions, and each should be answered from the best evidence for that question.

## 3. The editorial contract (needs your sign-off)

### Never on screen (hard rejects)

1. A different incident shown as this one. That means another attack, strike, fire, crash or protest, at any place or date.
2. Anything that contradicts the story's facts, including its *negative* facts. If the story says "no damage", show no damage. If it says "no casualties", show no casualties.
3. The wrong place or the wrong forces.
4. Studio shots, anchors or presenters of any channel.
5. Text that can't be removed: logos, tickers or subtitles that cropping can't clear without leaving too little picture.
6. Footage marked as file or archive (FILE, ARCHIVE, "representational", an old date stamp), *unless* tier T3 below is allowed.

### Footage tiers, in order of preference

| Tier | What | Allowed when |
|---|---|---|
| T1 | Footage of **this event**, from any source, treatable | always |
| T2 | **Same place, neutral.** Skyline, streets, establishing shots, with no incident content. | always |
| T3 | **Generic illustration of the actors or assets.** A US destroyer launching an interceptor, Iranian drones on display. It must not depict another specific incident. | **your decision (D1)** |
| T4 | Maps, photos, graphics | always (we already have maps/photos) |

## 4. The target system: one question per check

### Step 0: Story fact sheet

Built once per story by the writer LLM and checked against the script. It holds:

- **When:** the event window. The start comes from the story's facts and published date; the window runs from 3 days before to 10 days after.
- **Where:** places and countries.
- **Who:** actors and forces.
- **What happened:** the actions.
- **What explicitly did not happen:** the negative facts, such as no damage or no injuries.
- **What each footage section needs:** the visual need per section.

Every later step reads this sheet. This fixes F3, and makes F7 checkable.

### Step 1: Search, a query portfolio per tier

- **T1 queries.** The plain event query is built from the headline by code, not by the model. On top of that come the model's event variants. All T1 queries use **`publishedAfter` = window start via the YouTube Data API**, which we already have. Optional: Arabic and Farsi variants for local uploads.
- **T2 queries.** Place establishing shots, with no date filter.
- **T3 queries.** Only if D1 allows it.
- **The brief to the search backend becomes the section's visual need**, not "news report. Events of {day}" (fixes F3).
- **Budget per section:** N videos per tier, with a stop as soon as T1 has enough.

### Step 2: Per-shot claims, each with its own evidence

| Claim | Best evidence | Decided by |
|---|---|---|
| Place | picture text, signs, landmarks; metadata | vision model, blind (as now) |
| Time / this event | upload date inside the window; **the same shot found in an older upload** (see below); FILE/ARCHIVE/date-stamp text | code first, model second |
| Content type | studio / anchor / graphic / raw scene | vision model |
| Depicted action vs. facts | the shot's description vs. the fact sheet, including negative facts | text LLM (Gemma or Groq), not the 8B |
| Treatable | usable area after the crop, resolution, text coverage | code (OCR boxes, which we already compute) |

**Re-use detection fixes F6.** We perceptually hash every candidate shot. If the same shot also appears in a video uploaded *before* the event window, it is file footage, whatever the newer video's date. We already download both old and new candidates, so this costs almost nothing. It catches spliced archive footage that no model can see.

### Step 3: Verdict by a written rule table, not one opinion

- A shot's tier is computed from its claims: T1, T2 or T3, or a reject.
- Any hard reject from §3 wins.
- Unknown on a claim that matters means not T1. It can still qualify as T2 if the shot is neutral.
- **Every accepted shot carries its reasons.** These are shown in the site, so you can see *why* it passed.

### Step 4: Placement and honest gaps

- Fill each section from T1, then T2, then T3 (if allowed), then T4.
- **If no T1 exists, the site says so plainly:** "No footage of this event has been published yet; using establishing shots of Manama." The gap is not filled silently.

## 5. How we stop trial and error: a test set

- **Gold set.** Take the roughly 600 shots already judged across six stories, plus 2–3 new stories with known traps. I draft a label for each shot (its tier or its reject reason); you confirm or correct them in a review page.
- **Metrics:**
  - **Primary:** false accepts of anything on the never-list. The target is **zero**.
  - **Secondary:** T1/T2 recall, meaning how much real good footage we keep, plus minutes per story.
- **Every checker or search change runs the gold set before it touches a live story.** A change that adds one false accept is not shipped.
- **Trap cases in the set:**
  - same place, earlier incident;
  - a same-day report that splices in file footage;
  - a "no damage" story next to damage footage;
  - foreign uniforms filmed in the right country;
  - a vertical graphic over a real still;
  - a studio split-screen;
  - map and satellite views;
  - no-footage events.

## 6. Infrastructure edge cases (fix alongside)

| Case | Plan |
|---|---|
| Caption 429 / stalled downloads | 2-min download limit (done today). The caption pause is shared per IP. Whisper only on T1 candidates. |
| t8 C: full → WSL stops | Free or move space on t8's C: drive. KeepWSLAlive must restart WSL. The search reports "checker offline" instead of hanging. |
| Tenant on the GPU | "GPU busy, try again" (as for the writer). Never touch tenant work. |
| A search interrupted mid-way | Resume (exists). Test it in the test set. |
| Time budget | Target ≤ 10 min per story. Report the stage times in the UI. |

## 7. Decisions (user, 2026-11-17)

- **D1:** generic illustration (T3) is **allowed, with no label**, but only as a **last resort**.
- **D2:** the fallback after T1 is **T2 → T4 → T3 / images**.
- **D3:** I draft every label; the user reviews **only the doubtful ones**.
- **D4:** no local-language search.
- **D5:** the free batch is approved, and free X options exist too. **But YouTube only for now:** make YouTube correct first, then add sources one by one.
- **D6:** lower-thirds and tickers are often written about the *impact* or wider story, not about the event, so **their text gets low weight** in judging place and event. A provenance tag such as "FILE" / "ARCHIVE" is a different thing and still counts.
- **D7:** **no sensitive-content filter.** R11 is removed. If the story reports deaths or injuries, that footage is news and stays.
- **D8:** **production scale, not 1-minute stories.** Sections can be long, so shot length and source mix follow the section's length and the footage supply (§10, "Shot length and source mix").
## 8. Order of work once agreed

1. Build the gold set from the existing runs, with a review page for your corrections. This needs no GPU.
2. Fact sheet and brief fix (F3), plus the query portfolio with `publishedAfter` (F1, F2, F4).
3. Claim checks: re-use hashing, FILE text, the facts check, treatability (F5–F10).
4. The rule-table verdict, reasons shown in the UI, honest gaps (F11).
5. Run the gold set, fix until there are zero false accepts, then re-run Bahrain live.

## 9. The gold set in detail

**What it is.** A fixed collection of candidate shots, each with the *right answer* written down by a person. It is our answer key. Every version of the search and checker is run against it, and we count where its answers differ from the key. Without it, "better" means "looked better on one story".

### One item = one shot

| Field | Example |
|---|---|
| story, section, section text | Bahrain drones, v1, "The drones were launched toward…" |
| video id, channel, upload date, title | VGb6IStYn8Y, The Future Wire, 2026-11-13 |
| shot start–end | 18.8–23.3 s |
| frames | 1 frame per second of the shot, plus a playable clip |
| **label: tier** | T1 / T2 / T3 / T4-like (map, photo) / **REJECT** |
| **label: reject reasons** | one or more of R1–R12 (§10) |
| **label: usable seconds** | e.g. "0–4 s usable, 4–6 s ticker appears" |
| **label: treatable** | yes / no, and why (e.g. "subtitles fill the bottom third") |
| note | e.g. "AP FILE tag, earlier strike" |

### What goes in

- **Real runs we already have:**
  - Bahrain: ~340 shots, 2 sections.
  - Hormuz, Ceuta, Japan, Aliağa and Brooklyn.
  - The selftest traps.
  - That is ~600–900 shots in total. Real data, where the real failures happened.
- **Two or three new stories picked for their traps**, so every case in §5 appears at least ~10 times:
  - a "no damage / no casualties" story;
  - a city that is attacked often, so it has many old incidents;
  - a story with no public footage;
  - a story told mostly in vertical or phone video.
- **Kept balanced.** Not 500 easy skyline shots and 5 traps. Every trap category gets enough items that one mistake shows.

### Two halves, so we don't fool ourselves

- **Dev set (~70%).** We look at its failures and tune the rules on it.
- **Test set (~30%).** We never tune on it. A change counts only if it also holds on the test set. Otherwise the rules have just memorised Bahrain.

### Two levels of scoring

1. **Shot level:** our verdict compared with the label.
   - **False accept:** we kept a shot that is a REJECT, or called it T1 when it isn't. Every false accept is counted and listed by reason. **The target is 0** for the never-list.
   - **False reject:** we dropped a good shot. This is a coverage loss, tracked but secondary.
   - **Usable-seconds overlap:** how close our trimmed range is to the labelled range.
2. **Section level:** the end result.
   - **Placed precision:** the share of placed seconds that are correct. The target is 100%.
   - **Coverage:** the share of the voiceover's seconds filled by T1/T2.
   - **Minutes per story.**

### Who labels, and how

- I draft every label: I look at the frames, the clip and the metadata, and write the tier, reasons and usable range.
- You review the drafts in a simple page, one shot per card: frames, a play button, my label, and Accept / Change buttons.
- It shows doubtful ones first: where my label disagrees with the checker, or where I marked low confidence.
- **Your D3 choice:** review all ~800, or only the doubtful ones (my guess is ~150–250). At ~5 seconds a card, all of them is ~1 hour; doubtful only is ~15–20 min.

## 10. How footage is judged

### What happens today (code, 2026-11-16)

1. **Video level.** One vision-model read of the title, description, channel and date gives:
   - where it was filmed;
   - raw footage or report;
   - same event or not.
2. **Shot split.** A cut is detected when the picture changes sharply. The model looks at 6 frames per second, and shots under 1.5 s are dropped.
3. **Each shot is judged from only 2 frames,** taken at 30% and 70% of the shot. The model gives:
   - the kind of shot (scene, studio, graphic…);
   - relevance, 0–4;
   - quality, 0–10;
   - the overlay boxes and the subject box.

   OCR finds the text.
4. **Place.** A blind "where is this" read is combined with the video-level answer to give CONFIRMED / NEARBY / REPORT / UNKNOWN / CONTRADICTED.
5. **Treatment.**
   - A crop that removes logos and tickers, with at most 1.33x zoom.
   - Phone-format video gets a blur fill.
   - Burned-in subtitles are tolerated (your rule, 11-14).
   - A model and OCR re-check the treated frame.
6. **Pick.** Best place first, then relevance × 2 + quality. At most 2 shots per video, and 4 picks per section.

**Gaps:**
- With only 2 frames, a ticker, cut-away or studio shot in the middle of a long shot is never seen.
- Nothing checks time or event at shot level.
- Nothing checks the story's facts.
- A whole shot is either kept or dropped.

### The proposed criteria: a shot is KEPT only if every check passes

| # | Check | Reject when | Evidence |
|---|---|---|---|
| R1 | Content type | studio, presenter, interview, press conference, split screen, screen recording, a graphic covering most of the frame | vision model, 1 frame/s |
| R2 | Place | a different place or country is shown (text, landmark, metadata) | blind place read + metadata (as now) |
| R3 | Forces | the wrong country's troops, ships or aircraft | vision model |
| R4 | Event / time | a different or earlier incident: uploaded before the window, **the same shot found in an older upload**, or "FILE / ARCHIVE / representational" or a date on screen | code: dates, perceptual hash, OCR |
| R5 | Facts | it shows what the story says did **not** happen (damage, casualties, fire), or the opposite action (a strike when the story says interception) | text LLM compares the shot description with the fact sheet |
| R6 | Treatable | after the crop (≤ 1.33x zoom) a logo, ticker or lower-third is still visible, or the subject is cut off | OCR + model re-check (as now) |
| R7 | Picture quality | blurry, shaking, too dark, below ~360p, frozen frame | model score + code (sharpness, motion) |
| R8 | Graphic over a still | most of the frame is text or graphics over a photo | OCR text coverage |
| R9 | Duplicate | the same picture as a shot already picked (another channel's copy) | perceptual hash |
| R10 | Length | the usable run is shorter than ~2 s | code |
| R12 | Irrelevant | relevance 0–1 for the section's visual need | vision model |

**Tier of a kept shot:**
- **T1:** same event (in window, not reused, no FILE tag) and the place agrees.
- **T2:** same place, no incident content.
- **T3:** generic actors or assets, with no specific other incident.

**Selection:**
- Fill the section's voiceover seconds in tier order: T1 → T2 → T4 (maps/graphics) → T3 / photos.
- Within a tier: relevance, then quality.
- **No duplicates:** the same picture never appears twice, including copies from other channels. Everything else is in "Shot length and source mix" below.

### Partial shots: judged second by second, not whole-shot

The new rule: judge every shot at **1 frame per second**, so each second gets its own clean / not-clean mark. Then cut only the clean runs.

- **A 30 s clip with 5 s unusable.** Say a ticker appears at 12–17 s. That leaves two clean runs, 0–12 s and 17–30 s.
  - We keep both as **separate candidate clips**, each trimmed with a ~0.3 s safety margin.
  - We never join them into one clip, because that would make a jump cut.
  - How much of a run to use is decided by the section's needs ("Shot length and source mix" below), not a fixed 3–6 s.
- **A 30 s clip with only 10 s usable.** The 10 s counts if it's one run, or runs that are each at least ~2 s. How much of it is used depends on the section.
  - If the 10 s is scattered as 1 s fragments, it's rejected (R10). Flashes between graphics are unusable.
- **The crop is planned per run, not per frame.** The crop box must clear the overlays across *every* second of the run. So a logo that moves, or a ticker that appears late, can't slip through.
- **A run that changes subject mid-way** (the camera pans from the skyline to a burning building) is split where the content changes, and each piece is judged on its own facts (R5).

### Shot length and source mix (D8)

- **The whole clean run is available.** A shot is used for as long as it carries information: an interception, a rescue or a fire spreading can hold 10–20 s or more. A static view (a skyline, a parked ship) is cut sooner.
- **Section length drives the plan.**
  - The section's voiceover seconds set how much footage is needed.
  - The picker fills those seconds from the tiers in D2 order.
  - When good shots run short, it holds strong shots longer instead of padding with weaker tiers.
- **No fixed cap per video.** A long raw video of the event can supply many shots.
  - Shots that are consecutive in the original keep their order, because that's how the source editor cut them.
  - Mixing sources is a tie-breaker, not a rule.
- **No duplicate pictures,** including the same agency clip re-posted by other channels (perceptual hash).
- **Pacing is a setting per format** (e.g. a short bulletin vs a long explainer), not a hard-coded number.

## 11. Sources beyond YouTube (D5; parked: YouTube first)

There are two separate problems:
- **Downloading.** This is mostly solved. yt-dlp, which we already use, downloads from X, Instagram, TikTok, Facebook, Reddit, Vimeo, Dailymotion, public Telegram posts and more.
- **Finding the right post.** This is the hard part. Each platform's search access differs.

| Source | How we find posts | Cost | Value |
|---|---|---|---|
| YouTube | Data API (in use) | free quota | main source |
| Instagram reels | Google site: search (already in the footage backend) | free quota | phone video from the scene |
| TikTok, Facebook, X posts | Google site: search (same mechanism) | free quota | eyewitness video; **heavy reuse of old clips**, so the re-use check is essential |
| X direct search | X API, pay-per-use since Feb 2026 (~$0.005 per post read, ~$0.50 per 100-post search) | **paid**, needs your go | fastest eyewitness source |
| Reddit | free API (OAuth), news subreddits | free | links to raw clips |
| Telegram | a fixed list of public news channels via their public web preview (t.me/s/…), no account needed; full search would need a Telegram account (your OK) | free | conflict footage often appears here first |
| DVIDS (US military media) | free API key | free | official US Navy and CENTCOM video; T1 for US-military events, best T3 |
| Pexels / Pixabay | free APIs | free | clean T2 city and establishing shots, no logos |
| Wikimedia Commons / Internet Archive | free APIs | free | T2/T3, older |
| Dailymotion / Vimeo | free APIs | free | some news channels post here |
| AP / Reuters / AFP feeds | licensed | **paid** | out |

**How many we can add:** about 10 free ones are practical. X direct search and the agency feeds are paid. Every source goes through the same checks and the gold set; no source is trusted by name.

**Suggested first batch:**
- DVIDS, for US-military stories like Bahrain;
- Pexels/Pixabay, for clean T2 shots;
- a fixed Telegram channel list;
- Reddit;
- TikTok, X and Facebook through the site: search we already have.

## 12. Prior work on GitHub (searched 2026-11-17, newest and most relevant first)

**No open project does the whole job.** Several pick footage for a script, but none checks place, same event and reused footage before placing a clip. The checking layer is the new part.

| Use | Repo / dataset | How it helps us |
|---|---|---|
| Borrow design | broll-god (2026-09) | A plan per shot with must/reject checklists; agents keep or reject from a contact sheet; a manifest with source and licence. Closest to our flow. No place or event check. |
| Borrow design | VFCenter/CSI (ACL 2026 Findings) | Per-shot visual analyst + web-evidence agent + adjudicator. Matches our "one check per question → rule table". |
| Borrow design | AFP-Medialab verification-plugin (InVID/WeVerify, active 2026-11) | Keyframe reverse image search to find the earliest copy online: the practical way to catch old or "file" footage. Free access to the reverse-search engines needs checking. |
| Borrow design | broll-mcp (2026-10) | Per-clip provenance record; exact-length cut. |
| Reuse | meta/ThreatExchange vPDQ (2026-11) | Finds a clip inside a longer video, for our re-use check (R4) and duplicates (R9). |
| Reuse | GeoCLIP (active 2026-10) | Cheap GPS guess per keyframe, a second opinion next to the vision model on place (R2). |
| Reuse | line/lighthouse, TimeLens (CVPR 2026) | Find the moment in a long video that matches the section text, before the slow vision model. |
| Reuse | Meta Perception Encoder | Fast shot↔text ranking, so the vision model judges fewer shots. |
| Test data | FakeVV / Fact-R1 (NeurIPS 2025) | 100k news video-text pairs with swapped mismatches, for testing R5 (facts). |
| Test data | ACM MM Multimedia Verification challenge, MV2026 edition | ~50 real verification cases with location and date answers (registration needed). |
| Evidence | EVID-Bench (2026) | The best frontier model reaches only 43% judging edited or spliced news video from the clip alone, so web or date evidence is needed, not just the pixels. |
| Maybe later | video-subtitle-remover, ProPainter | Remove tickers or logos by inpainting, only where a crop can't. Cropping stays the default (zero quality loss). |
