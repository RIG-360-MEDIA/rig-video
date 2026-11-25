"""Script writer for RIG-Video: the prompt and schema from the 2026-11-14 fair re-run (Gemma 4 26B on trijya-3), plus
plain code checks. Nothing here comes from the old anchor-daily writer/QC (user rule).

Main path: the writer on trijya-3 (first entry of LLM_PROVIDERS) with the JSON schema enforced by llama-server and
Gemma's recommended sampling. A contended GPU is reported as busy (no fallback); only a down t3 falls back to the rest of the pool."""
import json
import os
import re
import urllib.request

SAMPLING = {"temperature": 1.0, "top_p": 0.95, "top_k": 64}          # Gemma 4 recommended


def plan(seconds, shot, wps):
    """(anchor sections, VO sections, words per anchor, words per VO) for a target length."""
    apps = max(1, min(10, round((seconds + shot) / (2 * shot))))
    vos = apps - 1
    a_words = round(shot * wps)
    v_words = round(max(seconds - apps * shot, shot * vos) / max(vos, 1) * wps)
    return apps, vos, a_words, v_words


def system(seconds, apps, vos, a_words, v_words):
    order = " -> ".join(["ANCHOR", "VO"] * vos + ["ANCHOR"])
    return f"""You are the script writer for a serious international TV news channel. You turn one article into a
{seconds}-second news package read by an anchor.

FORMAT. The package alternates between the anchor on camera (ANCHOR) and the anchor's voice over real footage of the
event (VO), in exactly this order: {order}.
- ANCHOR 1: the single most important new fact, stated plainly - what happened, where, how bad.
- VO sections: the concrete facts that footage of the event can show - the place, the damage, the response, the people
  involved. Write them as narration, never as a description of pictures ("we see", "footage shows", "pictured").
- Middle ANCHOR sections: the key numbers, official statements and reactions, each with its attribution.
- LAST ANCHOR: where things stand now and the next step the article reports. No sign-off, no "back to you".
- Each ANCHOR section is about {a_words} words ({a_words - 3} to {a_words + 2}); each VO about {v_words} words
  ({v_words - 4} to {v_words + 4}). These lengths are timed to the video - keep to them.

FACTS. Use only facts the article states. The article is written in a colourful feature style: its commentary,
interpretations and dramatic phrasing ("a city under siege", "a stark reminder", "sent shockwaves") are NOT facts -
leave them out. Never add a fact, number, name, place, date or quote that is not in the article. Keep attributions
("police say", "according to the Air Force"). Say "at least" when the article does. Do not repeat a fact in two
sections.

STYLE. Written for the ear: short, clear, complete sentences an anchor can read in one breath; active voice; present
perfect for news ("has struck"). Numbers in digits as the article gives them. No lists, no parentheses, no
abbreviations a newsreader would not say aloud, no questions, no opinion, no first person. No graphic detail of
injuries or bodies.

ALSO RETURN
- headline: plain factual headline, at most 90 characters.
- facts: 4 to 6 short fact lines, each with a label (What, Where, When, Who, Numbers, Source).
- lt: the on-screen lower third - kicker (the place, ALL CAPS, at most 14 characters), headline (ALL CAPS, at most 48
  characters), subline (one line of detail, at most 70 characters).
- ticker: 5 to 7 short factual lines for the news ticker, at most 90 characters each, each a different fact.
- each VO section's "search": a short phrase to find real news footage of this kind of event at this place, e.g.
  "Kyiv drone strike apartment building fire". For ANCHOR sections leave "search" empty."""


def schema(n):
    return {"type": "object", "required": ["headline", "facts", "sections", "lt", "ticker"], "properties": {
        "headline": {"type": "string"},
        "facts": {"type": "array", "minItems": 4, "maxItems": 6, "items": {"type": "object", "required": ["label", "value"],
                  "properties": {"label": {"enum": ["What", "Where", "When", "Who", "Numbers", "Source"]}, "value": {"type": "string"}}}},
        "sections": {"type": "array", "minItems": n, "maxItems": n, "items": {"type": "object",
                     "required": ["kind", "text", "search"], "properties": {"kind": {"enum": ["anchor", "vo"]},
                     "text": {"type": "string"}, "search": {"type": "string"}}}},
        "lt": {"type": "object", "required": ["kicker", "headline", "subline"], "properties": {
               "kicker": {"type": "string"}, "headline": {"type": "string"}, "subline": {"type": "string"}}},
        "ticker": {"type": "array", "minItems": 5, "maxItems": 7, "items": {"type": "string"}}}}


class Busy(RuntimeError):
    """t3's GPU is shared with other people's work; when it is busy the writer crawls. Said to the user as is."""


BUSY = "The script writer's GPU is busy with other work right now. Try again in a few minutes."
FIRST_TOKEN_S, MIN_TPS, CHECK_AFTER_S = 45, 6, 15   # uncontended: first token in seconds, ~20 tok/s; contended (2026-11-14): 136 s, 0.9 tok/s


def ask(system_prompt, user, json_schema, max_tokens, log=print):
    """One request to the writer at a time from this machine (a file lock): t3 serves one script at a time, so a request
    sent beside another waited past FIRST_TOKEN_S and was taken for a busy GPU (the daily run starts ~10 stories at once).
    ponytail: one queue for every caller; per-story priority if editors' own scripts must jump the daily ones."""
    import fcntl, pathlib
    lock = pathlib.Path(os.environ.get("STUDIO_DATA") or pathlib.Path.home() / "anchor-studio" / "rigvideo-data") / "writer.lock"
    with open(lock, "a+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            return _ask(system_prompt, user, json_schema, max_tokens, log)
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _ask(system_prompt, user, json_schema, max_tokens, log=print):
    """The writer on trijya-3 first (schema enforced), streamed so a contended GPU is caught in under a minute: then
    Busy, no fallback (the user is told to try later). Only if t3 is down or broken, the rest of the pool (orchestrator.llm)."""
    import time
    from orchestrator import llm
    pool = json.loads(os.environ.get("LLM_PROVIDERS") or "[]")
    main = pool[0] if pool else None
    if main and os.environ.get(main["key_env"]):
        body = {"model": main["model"], "max_tokens": max_tokens, "json_schema": json_schema, "stream": True, **SAMPLING,
                "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user}]}
        req = urllib.request.Request(main["base_url"].rstrip("/") + "/chat/completions", json.dumps(body).encode(),
                                     {"Content-Type": "application/json", "Authorization": "Bearer " + os.environ[main["key_env"]]})
        try:
            with urllib.request.urlopen(req, timeout=FIRST_TOKEN_S) as r:   # the socket timeout covers the wait for the first token
                out, n, t0 = [], 0, None
                for line in r:
                    if not line.startswith(b"data: ") or line.strip() == b"data: [DONE]":
                        continue
                    piece = (json.loads(line[6:])["choices"][0].get("delta") or {}).get("content") or ""
                    out.append(piece)
                    n += 1
                    t0 = t0 or time.time()
                    took = time.time() - t0
                    if took > CHECK_AFTER_S and n / took < MIN_TPS:
                        log(f"writer on {main['name']}: {n / took:.1f} tok/s, GPU busy")
                        raise Busy(BUSY)
            return json.loads("".join(out))
        except TimeoutError:
            log(f"writer on {main['name']}: no first token in {FIRST_TOKEN_S} s, GPU busy")
            raise Busy(BUSY)
        except (OSError, ValueError, KeyError, IndexError, TypeError) as e:
            log(f"writer on {main['name']} failed ({type(e).__name__}: {str(e)[:120]}); using the fallback pool")
        os.environ["LLM_PROVIDERS"] = json.dumps(pool[1:])          # the fallback must not ask t3 again
        try:
            return llm.chat_json(system_prompt + "\nReturn strict JSON only.", user, temperature=0.7, max_tokens=max_tokens, log=log)
        finally:
            os.environ["LLM_PROVIDERS"] = json.dumps(pool)
    return llm.chat_json(system_prompt + "\nReturn strict JSON only.", user, temperature=0.7, max_tokens=max_tokens, log=log)


# ------------------------------------------------------------------ code checks

ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty".split()
COMMON = set("""A An The This That These Those It Its He She They We I In On At Of For From By With As After Before
During Since Until While When Where Who What Why How And But Or So Yet If Then There Here Officials Authorities Police
Investigators Meanwhile However Both Each Some Many Most All One Two Three Four Five Six Seven Eight Nine Ten At No
Security Emergency Local Former President Prime Minister Mayor Senator Rescue Firefighters United States""".split())


def in_text(word, art):
    """word, or its stem for demonyms (Armenian -> Armenia, Iranian -> Iran), appears in the article."""
    w = word.lower()
    return w in art or any(len(x) >= 4 and x in art for x in (w[:-1], w[:-2], w[:-3]))


def order_ok(sections, apps, vos):
    return [s.get("kind") for s in sections] == (["anchor", "vo"] * vos + ["anchor"])


def fact_notes(where, text, art, art_nums, names=True):
    """Numbers and names in text that the article (lower-cased: art; its numbers: art_nums) does not contain."""
    out = []
    for n in re.findall(r"\d[\d,]*(?:\.\d+)?", text):
        v = n.replace(",", "")
        if v not in art_nums and not (v.isdigit() and int(v) <= 20 and re.search(rf"\b{ONES[int(v)]}\b", art)):
            out.append(f"{where}: the number {n} is not in the article")
    for name in re.findall(r"(?<![.!?]\s)(?<!^)\b([A-Z][a-z]{2,}(?:\s[A-Z][a-z]+)*)", text) if names else []:
        words = [w for w in name.split() if w not in COMMON]
        if words and not all(in_text(w, art) for w in words):
            out.append(f"{where}: '{name}' is not in the article")
    return out


def notes(sc, article, a_words, v_words):
    """Things a person should look at; not fixed automatically. Numbers and names must appear in the article,
    section lengths should be near the timed target."""
    art = article.lower()
    art_nums = {x.replace(",", "") for x in re.findall(r"\d[\d,]*(?:\.\d+)?", article)}
    out = []
    lines = [(f"{s['kind'].upper()} {i + 1}", s["text"]) for i, s in enumerate(sc.get("sections") or [])]
    lines += [("Ticker", t) for t in sc.get("ticker") or []]
    heads = [("Headline", sc.get("headline") or ""), ("Lower third", " / ".join((sc.get("lt") or {}).values()))]
    for where, text in lines + heads:
        out += fact_notes(where, text, art, art_nums, names=(where, text) not in heads)   # headlines are Title Case
    for i, s in enumerate(sc.get("sections") or []):
        n, (lo, hi) = len(s["text"].split()), ((a_words - 3, a_words + 2) if s["kind"] == "anchor" else (v_words - 4, v_words + 4))
        if not lo - 4 <= n <= hi + 4:
            out.append(f"{s['kind'].upper()} {i + 1}: {n} words, the timing wants {lo} to {hi}")
    return list(dict.fromkeys(out))


# ------------------------------------------------------------------ VO-only (no anchor on screen; footage all the way)
# Rules: docs/design/vo-only/SCRIPT_RULEBOOK.md (item numbers in the comments below).

VO_WPS = 2.6        # spoken words a second with breaths between beats (hand scripts, 2026-11-20 study)


VO_CPS = 17.7       # characters of a line spoken a second, take length: steadier than words (long names, numbers);
                    # 2026-11-23: 17.0-18.6 over 3 voices and 7 scripts, words/s 2.52-2.86. Same for every voice.


def vo_words(seconds):
    return round(seconds * VO_WPS)


def vo_seconds(texts):
    """How long the lines play: each take at VO_CPS plus the breath after it (worker.VO_GAP)."""
    return sum(len(t.strip()) / VO_CPS + 0.35 for t in texts)


def vo_system(seconds):
    words = vo_words(seconds)
    words_lo, words_hi = round(words * 0.92), round(words * 1.05)
    nbeats, bg = max(2, round(words / 21)), max(1, seconds // 40)    # ~21 words (7 s) a beat, what the model holds; context grows
    return f"""You write the narration for a VO-only news video: there is no anchor on screen, the whole video is real
news footage of the event with your voice over it. You turn one article into a script of BEATS. Each beat is one
kind of picture, and the narration that plays over it.

THE ONE RULE. A line is only usable if real news footage can show it. Every beat must be something a camera filmed:
the place, the damage, the rescue, the people named, the moment itself. A fact no camera can show goes into a beat
whose picture can carry it (the death toll on the crash beat), or it is left out. Advice, appointments, plans,
readings and records ("motorists should carry blankets", "he has been named mentor", "temperatures reached minus 7")
are not filmed: give them no beat of their own.

BEATS
- picture "event": footage filmed at this event - the scene, the damage, the rescue, the people there, the speech,
  the hearing, the ceremony, the meeting. A general view of the city, a building's outside, a logo or a sign is NOT an
  event picture.
- picture "archive": footage of one specific named person, place or thing, from any date - the actor's earlier films,
  the player lifting a trophy, the aircraft type, the painting, a named earlier event. A person speaking about or
  reacting to THIS event (a statement, a press conference, a resignation address) is "event", not archive.
- The picture is of what the line is about. A person is on screen only in a beat that is about that person or quotes
  them; a statistic never gets someone's face.
- No generic pictures - the viewer takes every picture for this event, and generic shots are always another event:
  no logos, signs, documents, screens, computer code, stock tickers, charts, maps, skylines, "war footage", weapons
  in general, vials or hospitals in general. A fact that needs one is carried by an event beat, or left out.
- shows: what is on screen, in camera terms, 3 to 10 words - people, places, objects, actions. No moods, no abstract
  words like "tension" or "tragedy".
- search: 2 to 5 words that a news video's TITLE about this would contain. YouTube matches titles, not what is inside
  a video, and the editor finds the shot inside the video: so name the event or the named subject, never the shot -
  "Kursk drone attack", not "Kursk street vehicle fire"; "MiG-29 crash Serbia", not "Serbian military crash scene";
  "Khurelsukh resigns", not "Khurelsukh Ukhnaa address". Event beats: the event noun plus the country or a well-known
  city ("An-12 crash Kemerovo", "France riots shops looted"). Archive beats: the named person, place or thing ("MS
  Dhoni lifts IPL trophy", "Van Gogh Sotheby's auction"). Never only the setting, a building or a kind of scene
  ("auction room", "Ministry of Defense Belgrade", "voters casting ballots"): those find any event. No dates, no
  years, no adjectives.
- text: 1 to 3 short sentences, 18 to 32 words (about 21), ONE idea, written to that picture: the fact and the detail
  the article gives with it (who, where, how many, what it means for the people there).

ORDER
- Beat 1: the core fact - what happened, where, how bad - over the strongest event picture. Announcements that were
  filmed (a press conference, a bell ringing, a ceremony, a hearing, a summit meeting) are event pictures. Only if
  nothing at all was filmed (a casting, a retirement, a written statement), beat 1 is archive of the main person or
  thing, with the news in the words.
- Numbers ride on the beat whose picture shows what they count. Never a beat of only numbers.
- At most {bg} background beat{"s" if bg > 1 else ""} (what led to this, who these people are), only what the story needs to make sense.
- Last beat: where things stand now - the search, the investigation, the next step, the official reaction - over a
  picture. No sign-off, no moral, no "it remains to be seen".

FACTS
- Only facts the article states. Leave out its framing, commentary, analysis, predictions and speculation ("a stark
  reminder", "sent shockwaves", "raises questions").
- If the article contradicts itself, use what agrees with its headline and deck; otherwise attribute the figure
  ("initial reports say") or drop it.
- Attribute tolls that may change, claims, accusations and estimates, at the end of the sentence ("..., police say").
- At most ONE number in each sentence ("8 people have been killed. 26 more were hurt." - never both in one
  sentence), in digits as the article gives it. Say "at least" when the article does. At most 2 numbers in a beat.
- No calendar dates, no weekdays, no "today", "yesterday", "this week". A year only for background ("in 2017").
- A direct quote only from someone likely filmed saying it (an official at a press conference, the player, the actor):
  at most one, one sentence. Otherwise use reported speech.
- Never: graphic injury detail, victims' names the article does not make public, causes the article does not state.

STYLE. For the ear, the way TV news reports say it: plain words, active voice, present perfect for the news ("has
crashed", "has won"). Names and places spelled as the article spells them; name the place in beat 1. No
abbreviations a newsreader would not say aloud, no lists, no parentheses, no questions, no first person. Never
describe the pictures ("we see", "footage shows").

LENGTH. About {words} words in all ({words_lo} to {words_hi}), for {seconds} seconds: about {nbeats} beats of about 21 words. The video is timed to it. Fill it
from the article: more of its showable facts - who said what, where it happened, who is affected, what happens next -
each on a picture that can carry it, with one more beat where needed. Never pad, never repeat a fact, never invent.
Only when the article truly has no more facts write less, and set supported_seconds to what it honestly fills.

ALSO RETURN
- headline: a plain factual headline, at most 90 characters.
- event_search: 2 to 5 words, how most news video titles name this whole event: what happened plus the country or a
  well-known city, in common English spelling ("Russian missile lands Poland", "Serbian MiG-29 crash", "Kursk drone
  attack", "Miro G aground France"). No village or street names, no dates.
- supported_seconds: how many seconds the article's showable facts fill, at most {seconds}.
- pictured_date: almost always an empty string. Only when the news itself is a later count of an earlier event, so
  the event pictures must come from that earlier event (a damage bill weeks after riots): the date of that earlier
  event as YYYY-MM-DD, written in the article. A crash, a strike, a ruling, a summit, an announcement: empty.
- event_filmed: true if the article reports at least one moment that cameras could film at this event (a crash, a
  strike, a protest, a speech, a hearing, a ceremony); false if the news is only claims, figures, documents or
  statements. Be honest: a city view or a building outside does not count."""


def vo_schema():
    beat = {"type": "object", "required": ["picture", "shows", "search", "text"], "properties": {   # picture first: write to it
        "picture": {"enum": ["event", "archive"]}, "shows": {"type": "string"}, "search": {"type": "string"},
        "text": {"type": "string"}}}
    return {"type": "object", "required": ["headline", "event_search", "event_filmed", "supported_seconds", "pictured_date", "beats"], "properties": {
        "headline": {"type": "string"}, "event_search": {"type": "string"}, "event_filmed": {"type": "boolean"}, "supported_seconds": {"type": "integer"},
        "pictured_date": {"type": "string"},
        "beats": {"type": "array", "minItems": 2, "maxItems": 20, "items": beat}}}


def vo_pictured_date(sc, article, news_date):
    """The writer's pictured_date only if it is a real earlier event the article names: at least 3 days before the news
    and its month written in the article. Anything else searches from the news date [13]."""
    import datetime as dt
    pd = sc.get("pictured_date") or ""
    try:
        d, n = dt.date.fromisoformat(pd), dt.date.fromisoformat(news_date)
    except ValueError:
        return ""
    return pd if (n - d).days >= 3 and d.strftime("%B").lower() in article.lower() else ""


def vo_user(title, deck, body, news_date):
    return f"News date: {news_date}\n\nARTICLE\nHeadline: {title}\nDeck: {deck}\n\n{body}"


DATE_WORDS = re.compile(r"\b(today|yesterday|tonight|tomorrow|this (?:morning|afternoon|evening|week)|last night|"
                        r"monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b|\b(?:january|february|march|april|may|june|"
                        r"july|august|september|october|november|december) \d{1,2}\b|\b\d{1,2} (?:january|february|march|april|"
                        r"may|june|july|august|september|october|november|december)\b", re.I)
STOCK = ("remains to be seen", "stark reminder", "raises questions", "sent shockwaves", "only time will tell", "we see",
         "footage shows", "pictured", "in a world", "it is worth noting")
GENERIC = re.compile(r"\b(logos?|signs?|signage|documents?|papers?|screens?|computer|code|tickers?|charts?|graphs?|maps?|"
                     r"skyline|various|generic|stock footage|war footage|missiles|weapons|vials?|syringes?|diagrams?|illustrations?|"
                     r"animations?|graphics?|office building|building exterior|exterior|cracked earth)\b", re.I)
SPOKEN_CAPS = {"NATO", "NASA", "FIFA", "UNICEF", "OPEC", "ASEAN", "APEC", "IPL", "BRICS", "UNESCO", "SWAT", "AIDS", "COVID"}
ABSTRACT = set("tension tensions tragedy uncertainty fear grief chaos anger hope concern concerns crisis impact".split())


SAYS = re.compile(r"\b(has |have )?(called|said|says|told|announced|warned|described|condemned|vowed|confirmed)\b", re.I)


def vo_notes(sc, article, seconds):
    """VO-only checks (rulebook items in brackets). Notes for a person, like notes(). Notes starting "(info)" or
    "READINESS" are for the person only; the rest are worth one rewrite."""
    art = article.lower()
    art_nums = {x.replace(",", "") for x in re.findall(r"\d[\d,]*(?:\.\d+)?", article)}
    beats, out = sc.get("beats") or [], []
    if beats and beats[0].get("picture") != "event":
        out.append("(info) Beat 1 is archive: fine only when the article reports nothing filmed [7]")
    ev = str(sc.get("event_search") or "")
    if not 2 <= len(ev.split()) <= 5 or re.search(r"\b(19|20)\d\d\b", ev) or DATE_WORDS.search(ev):
        out.append(f"event_search '{ev}' should be 2-5 words with no date [23]")
    total, findable = 0, 0
    for i, b in enumerate(beats, 1):
        t, w = b.get("text", ""), f"Beat {i}"
        n = len(t.split()); total += n
        sents = [x for x in re.split(r"(?<=[.!?])\s+", t.strip()) if x]
        if n > 35 or len(sents) > 3:
            out.append(f"{w}: {n} words in {len(sents)} sentences, a beat is 1-3 sentences and at most 32 words [2,3]")
        if n < 10:
            out.append(f"{w}: {n} words, too short to hold a clip [3]")
        elif n < 15:
            out.append(f"{w}: {n} words, a beat is 18 to 32 words: add the detail the article gives with this fact [3]")
        out += fact_notes(w, t, art, art_nums)
        for x in sents:
            if len(re.findall(r"\d[\d,.]*", x)) > 1:
                out.append(f"{w}: more than one number in a sentence [20]")
        if DATE_WORDS.search(t):
            out.append(f"{w}: says a date or day ('{DATE_WORDS.search(t).group(0)}') [18]")
        for x in STOCK:
            if x in t.lower():
                out.append(f"{w}: stock phrase '{x}' [16,26]")
        q = b.get("search", "")
        if not 2 <= len(q.split()) <= 5 or re.search(r"\b(19|20)\d\d\b", q) or DATE_WORDS.search(q):
            out.append(f"{w}: search '{q}' should be 2-5 words with no date [23]")
        named = bool(re.search(r"\b[A-Z0-9][\w-]*", (b.get("shows", "") + " " + q)))
        if b.get("picture") == "archive" and not named:
            out.append(f"{w}: archive with no named person, place or thing [12]")
        speaker = [x for x in re.findall(r"\b[A-Z][\w.-]{3,}", b.get("shows", "")) if x not in COMMON]   # a named person on screen
        if b.get("picture") == "archive" and SAYS.search(t) and any(x in t for x in speaker):
            out.append(f"{w}: a person's words about this event - picture \"event\" (filmed saying it), not archive [12]")
        findable += not GENERIC.search(b.get("shows", "")) and (b.get("picture") == "event" or named)
        generic = bool(GENERIC.search(b.get("shows", "")))
        if generic:
            out.append(f"{w}: shows '{b.get('shows')}' is a generic picture, it will be another event [12]")
        for name in re.findall(r"\b([A-Z][a-z]+(?:\s[A-Z][a-z.]+)+)", b.get("shows", "")):     # a named person on screen
            if not any(x in t for x in name.split() if len(x) > 3 and x not in COMMON):
                out.append(f"(info) {w}: shows {name}; check the line is about them [11]")
        for ab in re.findall(r"\b[A-Z]{4,}\b", t):
            if ab not in SPOKEN_CAPS:
                out.append(f"{w}: '{ab}' is an abbreviation a viewer may not know [22]")
        sw = set(re.findall(r"[a-z]+", b.get("shows", "").lower()))
        if sw and sw <= ABSTRACT | {"and", "the", "a", "of", "in"}:
            out.append(f"{w}: shows '{b.get('shows')}' is not something a camera films [14]")
    quotes = sum(b.get("text", "").count('"') // 2 for b in beats)
    if quotes > max(1, seconds // 30):
        out.append(f"{quotes} direct quotes; at most one per 30 s [15]")
    spoken = vo_seconds([b.get("text", "") for b in beats])
    want = round(total * seconds / spoken) if spoken else vo_words(seconds)   # words at this script's own pace
    if spoken > seconds * 1.1:                                      # spoken, it runs past the length asked for
        out.append(f"{total} words play about {round(spoken)} s, the video is {seconds} s: cut to about {want} words, "
                   f"keeping the strongest facts [5]")
    if beats and spoken < seconds * 0.9:                            # spoken, it runs short of the length asked for
        out.append(f"{total} words play about {round(spoken)} s, the video is {seconds} s: write about {want} words, "
                   f"about {max(2, round(want / 21))} beats of about 21 words, using more of the article's showable facts "
                   f"and their details [5]")
    pd = sc.get("pictured_date") or ""
    if pd and not re.fullmatch(r"\d{4}-\d\d-\d\d", pd):
        out.append(f"pictured_date '{pd}' is not YYYY-MM-DD [13]")
    if findable < 2 or findable < len(beats) * 2 / 3:
        out.append(f"READINESS: only {findable} of {len(beats)} beats have a picture the search can find: VO-only should not be offered [6]")
    return list(dict.fromkeys(out))


if __name__ == "__main__":                                          # self-check: python3 writer.py
    assert plan(60, 328 / 24 - 0.7, 2.85)[:2] == (3, 2)
    assert order_ok([{"kind": k} for k in ("anchor", "vo", "anchor")], 2, 1)
    assert not order_ok([{"kind": k} for k in ("vo", "anchor", "anchor")], 2, 1)
    art = "Seven people died on November 11 in Zvenigovsky district. Police say 1,144 incidents."
    sc = {"sections": [{"kind": "anchor", "text": "Seven people have died in Zvenigovsky. Police say 1,144 incidents on Tuesday."}],
          "headline": "7 dead", "lt": {"kicker": "MARI EL"}, "ticker": ["12 hurt"]}
    got = notes(sc, art, 12, 30)
    assert any("Tuesday" in x for x in got) and any("12" in x for x in got), got
    assert not any("1,144" in x or "Zvenigovsky" in x or "'7'" in x for x in got), got
    print("ok", got)
    vo = {"supported_seconds": 30, "pictured_date": "", "beats": [
        {"picture": "archive", "shows": "tension", "search": "Kerch bridge attack on Tuesday 2026", "text": "Tension remains on Tuesday. 12 boats, 40 drones."},
        {"picture": "event", "shows": "smoke over the Kerch bridge", "search": "Kerch bridge strike", "text": "Ukraine says its forces have struck the Kerch bridge, which links Russia to occupied Crimea, police say."}]}
    got = vo_notes(vo, "Ukraine struck the Kerch bridge linking Russia to occupied Crimea with drones, police said.", 30)
    for want in ("Beat 1 is archive", "the number 12", "more than one number", "'Tuesday'", "search 'Kerch", "too short",
                 "not something a camera"):
        assert any(want in x for x in got), (want, got)
    assert any(x.startswith("event_search ''") for x in got), got
    g = vo_notes({"beats": [{"picture": "archive", "shows": "Kosiniak-Kamysz at a podium", "search": "Kosiniak-Kamysz Poland",
                             "text": "Deputy Prime Minister Wladyslaw Kosiniak-Kamysz has called the strike a provocation."}]}, "", 30)
    assert any("not archive" in x for x in g), g
    assert not any(x.startswith("Beat 2") for x in got), got
    assert vo_pictured_date({"pictured_date": "2025-10-17"}, "riots on 17 October", "2025-11-19") == "2025-10-17"
    assert vo_pictured_date({"pictured_date": "2026-11-15"}, "on November 15", "2026-11-17") == ""
    assert vo_pictured_date({"pictured_date": "2023-06-21"}, "the zoo said", "2026-11-17") == ""
    g = vo_notes({"supported_seconds": 30, "event_filmed": False, "beats": [{"picture": "archive", "shows": "Tedros Ghebreyesus speaking",
                  "search": "WHO measles", "text": "Vaccination rates have fallen to 92 percent, says the CNAAP."}]}, "vaccination 92 percent CNAAP", 30)
    assert any("check the line is about them" in x for x in g) and any("CNAAP" in x for x in g), g
    beat = {"picture": "event", "shows": "smoke over the Kerch bridge", "search": "Kerch bridge strike"}
    line = lambda n: " ".join(["words"] * n)                     # 6 characters a word
    assert any("play about 20 s" in x for x in vo_notes({"beats": [{**beat, "text": line(58)}]}, "", 30)), vo_notes({"beats": [{**beat, "text": line(58)}]}, "", 30)
    assert not any(" s, the video is" in x for x in vo_notes({"beats": [{**beat, "text": line(88)}]}, "", 30))
    assert any("cut to about" in x for x in vo_notes({"supported_seconds": 26, "beats": [{**beat, "text": line(110)}]}, "", 30))
    print("ok vo", len(got))
