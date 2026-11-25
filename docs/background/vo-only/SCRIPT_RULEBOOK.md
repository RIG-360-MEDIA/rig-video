# VO-only script rulebook (draft for review)

**Drafted by persona:** a senior digital video producer with 15 years on international news-agency video desks and social
news teams.
- Knows what footage exists for each kind of event, and how soon after it happens.
- Trained as a broadcast writer, so writes to pictures.
- Has worked with automated footage search, so knows a line only gets a picture if the search can find one.

**What this is:** the questions a VO-only script must answer correctly in production. Like the converter's golden set,
it is criteria, not a test set. It comes from 17 real DNL stories across 15 domains, each written by hand, searched with
our own footage search, and judged picture by picture:
- research_notes/vo_script_study: `SCRIPTS_v1.md`, `SCRIPTS_v2.md`, `FINDINGS.md`
- contact sheets in `search_v*/<story>/sheet.jpg`

**The one idea behind every rule:** in VO-only there is no anchor to cut back to. Every second of narration plays over
a found clip. A line with no matching picture plays over a random or repeated clip, or over footage of a different
event. **A script line is only usable if our search can find a picture for it.** Good writing that can't be shown is a
defect here, not a style choice.

Each item has an **answer** and **how we check it**. Numbers are starting values from the study.

---

## A. What the writer outputs

**1. What does a VO-only script look like?**
A list of **beats**. A beat is 1–3 spoken sentences (about 6–12 s) that one kind of picture can carry. Each beat has:
- `text`: what the voice says
- `picture`: `event` (filmed at this event) or `archive` (this person, place or thing, from any date)
- `shows`: a short description of what should be on screen, in camera terms ("rescuers in the river, stretchers")
- `search`: the footage search phrase

The script also has a headline. No lower third or ticker: those are a later layer.
*Check:* schema; 2–12 beats; every field non-empty.

**2. Why beats, not the anchor format's sections?**
Each beat becomes one footage search. The footage backend matches moments against one segment at a time, so a beat that
mixes ideas matches nothing. In the study, "26 injured to hospital + the highway carries pilgrims + an investigation"
got 0 clips, while single-idea beats beside it got the event.
*Check:* code flags a beat with more than 3 sentences or more than 35 words.

**3. How long is a beat?**
About 6–12 s spoken (15–32 words at the anchor's pace). Shorter beats leave too little room for a clip to play.
Longer beats outlast the clips found and loop them.
*Check:* words per beat against the anchor's measured words per second.

## B. Which stories, and how long

**4. Which stories can be VO-only?**
Stories whose main beats can be **filmed**: something happened at a place, or to people, on camera. That covers
disasters, accidents, weather, war, strikes, unrest, crashes, rescues, court rulings with a hearing, elections with
victory speeches, summits, sport, and launches and listings with an event.
Stories made only of **claims, numbers or decisions with no event** don't fit: intelligence reports, policy papers,
data releases, rumours, "experts say" pieces. They should be flagged before writing (item 6), not padded with generic
shots.
**Weak domains (v2):** elections and health stories are told on TV through studios and graphics. Peltola's win
found CNN's results board and Alaska scenery. The measles beats found a studio interview, an RFK Jr. talk show and
stock photos. For these, only the beats with a filmed moment (a victory speech, a clinic, an official at a podium)
are `event`, and readiness (item 6) usually caps them at 30 s.
*Check:* the picture-readiness check (item 6) on every story.

**5. Who decides the length: the user's slot or the source?**
The source. A script never pads.
- In the study, 11 of 17 scripts had to be cut, on average to about 60% of the asked length.
- A fact-dense article of 300 words or less holds 30–45 s.
- Feature-style articles (most DNL long-reads) hold about 1 s per 7–10 source words. Most of their words are framing,
  not facts.

When the asked length can't be filled from facts with pictures, the writer returns a shorter script and says so ("the
source supports about 35 s").
*Check:* the writer reports `supported_seconds`. Code flags a script whose beats repeat a fact or carry no new fact.

**6. Picture-readiness: how do we know before writing?**
Count the beats whose picture the search can find: an `event` picture, or `archive` of a **named** person, place or
thing, and not a generic shot (logo, document, skyline, "war footage").
- Fewer than 2 such beats, or fewer than two thirds of the beats: VO-only is not offered for the story.

Revised after v2: archive-led stories work. Fiona, Bond and Dhoni had little or nothing filmed, but archive of the
named subject gave some of the best picks. What fails is claims-only news told with generic pictures: the
intelligence plot's generic beats matched January 6 riot footage and a 3D animation.
*Check:* code counts findable beats (writer `vo_notes`, READINESS); the site warns or offers anchor formats instead.

## C. Order and structure

**7. What comes first?**
The strongest **event picture** with the core fact: what happened, where, and how bad. On a phone the first 2–3 s
decide whether the viewer stays, and the voice must match the picture from the first frame. A summary or context line
never opens.

**Exception, announcements with nothing filmed:** a retirement, a casting, a statement or a filing has no event to film.
Beat 1 is then `archive` of the named person or thing, with the news in the words. In v2, Bond's event beat found
nothing while the Pattinson archive was excellent, and Dhoni's retirement beat was rejected while his trophy lift
matched. An announcement that **was** filmed (a press conference, a bell ringing, a signing) stays `event`: Anthropic's
Nasdaq bell found its picture.
*Check:* beat 1 is `event`, or `archive` naming the story's main subject when the article reports no filmed event.

**8. What comes last?**
Where things stand: the search continues, the investigation, the next step, the official reaction. The closing beat
needs a picture too, such as the site, rescuers or the official who spoke. No sign-off, no moral, no "remains to be
seen".
*Check:* code flags closing stock phrases (list in writer checks).

**8a. What never gets a beat?**
Things nobody films: advice ("motorists should carry blankets"), appointments ("he has been named mentor"), plans,
readings and records ("minus 7.7 degrees at Tulloch Bridge"). In the study each of these found nothing or a
YouTuber talking. If the fact matters, it rides as a clause on a beat with a picture; otherwise it is left out.
*Check:* human review; the prompt names the kinds.

**9. Where do numbers go?**
On the beat whose picture shows what they count: the death toll on the crash beat, the damage bill on the looting beat.
A number never gets its own beat. In the study, a toll-only beat found no footage, while the crash beat beside it did.
*Check:* code flags a beat whose sentences are only numbers and attribution.

**10. How much background?**
At most one background beat, and only when archive of it exists and the story needs it to make sense ("Dhoni joined
Chennai in 2008", "the bridge opened in 2018"). Comparisons with other events ("far below the 2023 riots") cost an
archive beat each. In the study, 1 of 2 such beats found its archive. Keep one only when it changes how the viewer reads
the news.
*Check:* at most 1 background beat per 30 s.

## D. The picture for each beat

**11. `event` or `archive`?**
- `event`: the line is about what happened, and the picture should come from this event (the scene, the damage, the
  speech, the ruling).
- `archive`: the line is about who or what is involved, and the picture can come from any date (the actor's earlier
  films, the player's trophies, the aircraft type, the painting).

The search uses this. Without it, the backend asks every beat for raw footage of this event and rejects all archive. In
v1, every archive beat failed for this reason (Dhoni, Pattinson), though matching videos were found.
*Check:* every beat has `picture`. Archive beats must name a specific person, place or thing.

**12. What may archive show?**
Only the specific subject the line names: this person, this aircraft type, this building, this painting, this earlier
event when it is named. Never a "generic" picture of a related topic ("Capitol security", "a hospital").
- Generic topic searches match other events' coverage (in the study, January 6 riot footage under an Iran-plot line).
- The viewer reads any footage as being this event.

*Check:* code flags `archive` beats whose `shows` has no proper noun.

**13. When is the event's date not the news date?**
When the news is a follow-up to an older event: a damage bill after riots, a verdict on a 2017 crackdown, an anniversary,
a report on a past disaster. `event` beats are then searched from the **pictured event's** date.
- The writer must say which date that is, taken from the article.
- If the article doesn't give it, the beat becomes archive of the named event.

In the study, the riot-cost story got good footage only when searched from the riot date.
*Check:* the writer returns `pictured_date` when it differs from the news date.

**14. What does `shows` say?**
Concrete things a camera captures: people, places, objects, actions ("cars burning, riot police", "the auctioneer and
the painting"). No adjectives about mood, no abstract nouns ("tension", "tragedy", "uncertainty").
*Check:* code flags `shows` built only of abstract words (list).

**15. Quotes: when can a quote be used?**
Only when footage of that person speaking at this event, or a recent statement on camera, is likely: leaders, spokespeople,
officials at press conferences, the player or actor.
- A quote from a press release, or from a person who wasn't filmed, becomes reported speech in a beat whose picture is
  the event: "The zoo says its care team did everything possible."
- Quote at most once per 30 s, and keep it short (one sentence).

*Check:* quote count; a quoted speaker must be named in that beat's `shows`.

## E. Facts

**16. What can a line state?**
Only facts the article states. Feature framing ("a stark reminder", "a city under siege", "sent shockwaves"), analysis,
"what it means", predictions and the article's own speculation are left out. VO-only has no anchor to carry
interpretation, and no picture can show it.
*Check:* the fact check on every sentence (writer checks): names, numbers and places must appear in the article.

**17. What if the article contradicts itself?**
- Use only facts that agree with the deck and headline.
- When figures conflict (17 or 19 dead, a state toll larger than the national toll), state the attributed one ("initial
  reports say") or the consistent set, never a flat figure.
- Drop any fact that can't be settled.

In the study, 4 of 17 bodies had conflicting dates or numbers.
*Check:* code compares numbers in the script with the deck. A mismatch is a note for review.

**18. Dates: do we say them?**
No calendar dates, and no "today", "yesterday", "on Tuesday". The video is watched days later, and DNL bodies often carry
wrong dates (4 of 17 in the study). Years are allowed only for background that needs them ("in 2017", "opened in
2018"). Tense says whether something is new: "has crashed", "has won".
*Check:* code bans weekday names, months with a day number, and "today / yesterday / tonight / this morning".

**19. Attribution: when?**
- Always for tolls that may still change.
- Always for claims: intelligence, accusations, unconfirmed reports.
- Always for estimates: damage bills, forecasts.
- Always for anything one side says about the other in a conflict.

Put it at the end of the sentence ("…, police say"), so the fact comes first.
*Check:* code flags toll and claim words ("killed", "plot", "accused", "estimated") with no attribution in the sentence.

**20. How many numbers?**
At most one number per sentence, and about 3–4 per 30 s. Round as the article allows ("about 64 billion"). More numbers
turn the voice into a spreadsheet over unrelated pictures.
*Check:* number count per sentence and per 30 s.

## F. Words for the ear and for the search

**21. How should lines be phrased?**
The way news reports phrase the same facts: plain, active voice, present perfect for news, the names and places as
reporters say them.
- The footage search matches our line against the **spoken words** of other reports, so a line phrased like a report
  finds its picture.
- Example: "a fallen tree blocked the railway to Holyhead" matched a report that said exactly that.

*Check:* reading-level check; no passive "it has been reported that".

**22. Names and places?**
Use the spelling the reports use (check the headline and the most-cited form). Name the place in beat 1. Drop
abbreviations that can't be spoken and that viewers don't know ("CNAAP"). Give a person's role on first mention when the
article gives it.
*Check:* code flags all-caps tokens of 4+ letters that aren't in a known list (NATO, NASA…).

**23. The search phrase?**
2–5 words: the subject + the event noun + the place when it helps ("An-12 crash Kemerovo", "France riots shops
looted", "MS Dhoni lifts IPL trophy"). It must name what makes **this** event unique. A phrase for the setting or a
kind of scene finds any event: Gemma's "Sotheby's auction room" and "voters casting ballots" found graphics, cartoons
or nothing, while "Van Gogh Sotheby's record auction" found the auction floor.
- No adjectives, no dates (the date filter is added by code), no full sentences.
- In English, unless the event is local and its reports use another language. The search finds Hindi, Russian and
  Ukrainian reports from English phrases.

Long phrases returned 0 videos in the study.
*Check:* 2–5 words; no date words; at least one proper noun.

## G. Editorial lines

**24. What is never said over pictures?**
- Graphic injury detail.
- Sexual-violence detail. The fact may be stated in general terms ("widespread abuses") only when it is central, and
  never as its own beat.
- Victims' names unless the article gives them and they are public.
- Speculation about causes ("whether mechanical failure or driver error").

*Check:* word lists; human review on first runs.

**25. Other people's films, TV shows and music?**
Entertainment stories pull clips from films and trailers. **Open question for the user:** allowed (news use), or limited
to premieres, interviews and set photos?
*Check:* decided per policy.

**26. Is a story's own analysis ever allowed?**
One short clause of context, riding on a picture beat, when the article states it as fact ("the bridge is a key supply
route, Ukraine says"). Never "this raises questions", "it remains to be seen", "a stark reminder".
*Check:* stock-phrase list.

## H. What the pipeline must do for these scripts to work

These came out of the study. They are not writer rules, but VO-only fails without them.

**27. A per-beat brief.** The footage search must get each beat's `picture`, `shows` and date rule. Today the site sends
one brief per part: "footage filmed at this event". Measured: v1 vs v2 (FINDINGS.md).

**28. The pictured event's date** goes into the dated search (item 13).

**29. A presenter / graphic / animation filter.** The search picks moments from what is **said**, never what is shown,
so many picks are not usable pictures:
- studio presenters and reporters standing in front of the scene (Bond, measles, the bus reports, Bessent on Axios)
- TV graphics: election boards (CNN's Alaska results), quote cards, Hindi TV packages framed in graphics
- animation: a 3D-rendered White House tour, an animated Apple explainer, whiteboard cartoons
- AI-generated slideshows: stills rendered by AI with a voice-over ("UK Snow Melts" flooded streets)

The 9:16 converter keeps all of these. VO-only needs the clip checker's presenter, graphic and map labels (plus an
animation label), or a cheaper version, before a pick is used.

**30. The picture-readiness check** (item 6) before the user picks VO-only.

**30a. The footage search's own model.** Since 2026-11-20 the search reads transcripts with the local Qwen3-VL 8B on
trijya-8, not Groq: about 2 s a video, no daily cap. A VO-only story makes one search per beat (about 4 videos read
each), so it costs about 25–60 model calls, roughly 2–3 min per story including downloads. On Groq the same work
hit the daily token cap after about 10 stories (the v2 rate-limit failures).

## I. How it's judged

**31. Is a script good?**
Every beat has a found clip that shows its `shows`, with no wrong-event footage, no presenter or graphic, and no fact
outside the article. Measured by running the search and judging the contact sheet: beats with a fitting clip ÷ beats.
*Target:* ≥ 80% of beats with a fitting clip on stories that pass item 6, and 0 wrong-event clips.

**32. How is the writer tuned?**
Gemma is tuned with the prompt and code checks, not by retraining. Its scripts for the same stories go through the same
search-and-judge loop and are compared against the hand-written ones. A fresh set of stories is used for the final check
(no tuning on the test stories).
