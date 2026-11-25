"""VO-only clip checker: footage search results -> an edit list per story (which shots, where, how long).
Rules: docs/rig-video/vo-only/CHECKER_CRITERIA.md (RIG-NEWS-AI repo). Steps:
  1 gate     every video the story's search found, split into camera shots; repeated pictures dropped (stills stay)
  2 rank     SigLIP-2: each beat's line + wanted picture vs every shot of the story's pool -> top candidates per beat
  3 pick     Qwen3-VL, one call per beat: candidates side by side -> unusable kinds out, 1-3 shots in order
  4 assemble fill each beat's length, cut on phrase breaks, event order; a beat short of footage gets our own pictures
  5 review   Qwen3-VL, one call per story on the finished edit -> misfit cuts swapped for the next candidate
  6 enforce  no cut is the same picture as the one before it; no shot or picture comes back within REUSE_GAP s
usage (trijya-7, ~/anchor-studio/vertical/.venv python): vo_pick.py inputs.json out_dir [--only F1,F2] [--preview]
inputs: vo_inputs.py output, or the site's equivalent: [{sid, headline, date, place, beats: [{id, text, picture, cls,
        dated, secs?, words?}], videos: [{id, title, dur, beats, moments}]}]
        secs = the beat's voice length (else words / 2.6); words = [{w, start, end}] from the voice, for phrase cuts.
out: out_dir/<sid>/edit.json, sheet.jpg (+ preview.mp4) and out_dir/timing.json. A cut is a video shot {video, start, end}
     or one of our own pictures {image, url, page} (shown as a still for `secs`).
"""
import argparse, base64, datetime as dt, json, math, os, pathlib, re, subprocess, sys, time, urllib.request

import cv2
import numpy as np

HOME = pathlib.Path.home()
CACHE = pathlib.Path(os.environ.get("VO_CACHE", HOME / "vo_check/cache"))
YTDLP = os.environ.get("VO_YTDLP", str(HOME / "anchor-studio/repos/social_verifier/ytdlp_node.sh"))
FFMPEG = os.environ.get("VO_FFMPEG", str(HOME / "anchor-studio/repos/ffmpeg-shared/current/bin/ffmpeg"))
VLM = [u for u in os.environ.get("VO_VLM", "http://100.72.225.89:11620/v1,http://100.95.0.11:11610/v1").split(",") if u]
SIGLIP = "google/siglip2-so400m-patch14-384"
MAX_VIDEO_S = 2400          # longer videos are live streams / documentaries: skipped. A 31-min TV news report can be the
                            # best footage of the event (TVP World, Poland missile, 2026-11-22), so 40 min, not 20
MIN_SHOT_S = 1.5
WPS = 2.6                   # voice words per second when the beat has no voice timing yet
CANDS = 10                  # candidates per beat shown to the model
PER_VIDEO = 6               # of which at most this many from one video: 3 starved the one video that had the event (TVP
                            # World, 6-8 right shots, Poland 2026-11-22) and let title cards from others in
CUT = (2.0, 5.0, 8.0)       # shortest, usual longest, absolute longest cut (s)
MIN_CUT = 2.0               # a shot shorter than this (after trimming its edges) is never a cut of its own
REUSE_GAP = 12.0            # a shot (or the same picture) may come back after this many seconds: references reuse after ~30 s
                            # in 3-min pieces; our stories run 20-35 s, so 12 s (not in this beat or the one before)
EARLY_DAYS = 3              # a video uploaded more than this many days before the news can't show the event itself
                            # (it can still show its people, places and things: archive). Told to the model, not filtered.
DROP = ("presenter", "studio", "promo", "text_card", "map", "chart", "animation")
FAKE = re.compile(r"\b(ai[- ]generated|ai[- ]made|re-?enact\w*|animat\w+|cgi|simulat\w+|computer[- ]generated|colori[sz]ed|colouri[sz]ed)\b", re.I)
SAME_SCENE = 0.88           # SigLIP similarity above which two shots are the same picture: one clip re-aired by two channels
                            # measured 0.88-0.97; two angles of one scene 0.86-0.87 (kept: that is coverage, not a repeat)
OWN = os.environ.get("VO_ASSETS", str(HOME / "anchor-studio/studio-app"))   # repo holding pipeline/orchestrator/assets.py
LICENSED = re.compile(r"reutersconnect|gettyimages|apimages|alamy|shutterstock|istockphoto|dreamstime|depositphotos|"
                      r"123rf|stock\.adobe|agefotostock|imago-images|pond5|bridgeman", re.I)   # watermarked previews, sold licences
OWN_MAX = 4.0               # longest hold of one of our own still pictures (s)
NAME_BOOST = 0.04           # rank bonus per name in the beat (person, place, ship) that the video's title carries, max 2

# ---------------------------------------------------------------- 1 gate

def download(vid):
    f = CACHE / f"{vid}.mp4"
    if not f.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        subprocess.run([YTDLP, "-q", "--no-warnings", "--no-playlist", "-f",
                        "bv*[height<=480][vcodec^=avc1]+ba/b[height<=480][vcodec^=avc1]/bv*[height<=480]+ba/b[height<=480]",
                        "--merge-output-format", "mp4", "--write-info-json", "-o", str(f), f"https://www.youtube.com/watch?v={vid}"],
                       check=True, timeout=900)
    return f


def info(vid):
    for j in (CACHE / f"{vid}.mp4.info.json", CACHE / f"{vid}.info.json"):
        if j.exists():
            return json.loads(j.read_text())
    return {}


def shots_of(path, sample_fps=6):
    """Camera shots by colour-histogram cuts (6 frames/s): [{start, end, frames: 3 small BGR frames}]. Cached."""
    cache = path.with_suffix(".shots.json")
    if cache.exists():
        shots = json.loads(cache.read_text())
    else:
        cap = cv2.VideoCapture(str(path)); fps = cap.get(cv2.CAP_PROP_FPS) or 25; step = max(1, round(fps / sample_fps))
        times, hists, i = [], [], 0
        while True:
            ok = cap.grab()
            if not ok:
                break
            if i % step == 0:
                ok, f = cap.retrieve()
                if ok:
                    h = cv2.calcHist([cv2.cvtColor(cv2.resize(f, (160, 90)), cv2.COLOR_BGR2HSV)], [0, 1], None, [32, 32], [0, 180, 0, 256])
                    times.append(i / fps); hists.append(cv2.normalize(h, h).flatten())
            i += 1
        cuts = [0] + [j for j in range(1, len(hists)) if cv2.compareHist(hists[j - 1], hists[j], cv2.HISTCMP_CORREL) < 0.55] + [len(times)]
        shots = [{"start": round(times[a], 2), "end": round(times[b - 1] + step / fps, 2)}
                 for a, b in zip(cuts, cuts[1:]) if b - a >= 2 and times[b - 1] + step / fps - times[a] >= MIN_SHOT_S]
        cache.write_text(json.dumps(shots))
    return shots


def frames_at(path, times):
    if str(path).lower().endswith((".jpg", ".jpeg", ".png", ".webp")):      # one of our own still pictures
        img = cv2.imread(str(path))
        return [img for _ in times]
    cap, out = cv2.VideoCapture(str(path)), []
    for t in times:
        cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, t) * 1000)
        ok, f = cap.read()
        out.append(f if ok else None)
    return out


def peak_time(path, a, b):
    """The moment the picture changes most inside [a, b] (a flash, a blast, a hit): the frame with the strongest LOCAL
    change from the frame before (99.5th percentile of the difference on a 160x90 grid, every frame). A whole-frame
    average missed a small flash over roofs (Chmielek CCTV, 2026-11-22: one patch changed by 86 levels, the mean by 2.5).
    Middle of the shot for a still or a steady picture."""
    mid = (a + b) / 2
    if str(path).lower().endswith((".jpg", ".jpeg", ".png", ".webp")) or b - a < 0.8:
        return mid
    cap = cv2.VideoCapture(str(path)); cap.set(cv2.CAP_PROP_POS_MSEC, (a + 0.05) * 1000)
    prev, best = None, (0.0, mid)
    while True:
        ok, f = cap.read()
        t = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000
        if not ok or t > b - 0.05:
            break
        g = cv2.GaussianBlur(cv2.resize(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY), (160, 90), interpolation=cv2.INTER_AREA), (3, 3), 0).astype(np.float32)
        if prev is not None:
            d = float(np.percentile(np.abs(g - prev), 99.5))
            if d > best[0]:
                best = (d, t)
        prev = g
    return best[1] if best[0] > 20 else mid                     # nothing changes sharply anywhere: the middle


def cut_start(c, use):
    """Where a `use`-second cut starts inside shot c: around the moment the model said shows the subject (c["focus"],
    a third into the cut so it is seen early), else the shot's middle; inside the shot's edges."""
    f = c.get("focus")
    lo = c["start"] + (0.15 if f and f - c["start"] < 0.6 else 0.3)     # a moment right after the cut: trim less
    hi = max(lo, c["end"] - 0.3 - use)
    return min(max(f - use / 3 if f else (c["start"] + c["end"]) / 2 - use / 2, lo), hi)


def phash(img):
    g = cv2.resize(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (32, 32), interpolation=cv2.INTER_AREA)
    if g.std() < 12:
        return None                                       # black / one-colour frame
    d = cv2.dct(np.float32(g))[:8, :8].flatten()
    return int("".join("1" if x > np.median(d) else "0" for x in d), 2)


def same_pic(a, b):
    return a is not None and b is not None and bin(a ^ b).count("1") <= 10


COMMON = set("the a an and but in on at of for to by with from as it its this that these those he she they his her their "
             "officials says said monday tuesday wednesday thursday friday saturday sunday".split())


def names(text):
    """Proper names in a line ('Harry Styles', 'Kursk', 'Betul 8'), lower-case: capitalised runs not at a sentence start."""
    out = []
    for m in re.finditer(r"(?<![.!?]\s)(?<!^)\b([A-Z][\w'-]+(?:\s+(?:[A-Z][\w'-]*|\d+))*)", text):
        n = m.group(1).lower()
        if n not in COMMON and len(n) > 2:
            out.append(n)
    first = re.match(r"([A-Z][\w'-]+(?:\s+[A-Z][\w'-]+)+)", text)      # a multi-word name opening the sentence
    if first:
        out.append(first.group(1).lower())
    return list(dict.fromkeys(out))


def word(x):
    """'text_card (big text...)' -> 'text_card'; None -> ''."""
    m = re.search(r"[a-z_]+", str(x or "").lower())
    return m.group(0) if m else ""


_O = []


def ocr(img):
    """On-screen text of one frame: (the readable text, share of the frame its boxes cover). RapidOCR on CPU, ~0.4 s."""
    if not _O:
        import logging
        from rapidocr import RapidOCR
        _O.append(RapidOCR())
        logging.getLogger("RapidOCR").setLevel(logging.ERROR)
    r = _O[0](img)
    if not r.txts:
        return "", 0.0
    h, w = img.shape[:2]
    keep = [(b, t) for b, t, c in zip(r.boxes, r.txts, r.scores) if c > 0.6 and len(t.strip()) >= 2]
    area = sum(float((b[:, 0].max() - b[:, 0].min()) * (b[:, 1].max() - b[:, 1].min())) for b, _ in keep) / (w * h)
    return " | ".join(t for _, t in keep)[:200], min(1.0, area)


def fake(verdict):
    """The search's own verdict says the video IS AI-made / animated / re-enacted. Not when it says "not ...", and not a
    guess ("likely a studio report or reenactment" dropped The Independent's CCTV of the Poland impact, 2026-11-22: the
    verdict is read from the transcript only; the picker sees the pictures and rejects fakes itself)."""
    for m in FAKE.finditer(verdict[:300]):
        before = verdict[max(0, m.start() - 60):m.start()]
        if not re.search(r"\b(not|no|isn't|non)\b[\w\s-]{0,12}$", before, re.I) and \
                not re.search(r"\b(likely|may|might|maybe|possibly|perhaps|could|appears?|seems?|probably|or)\b", before, re.I):
            return True
    return False


# ---------------------------------------------------------------- 2 rank

_M = []


def siglip():
    if not _M:
        import torch
        from transformers import AutoModel, AutoProcessor
        dev = "cuda" if torch.cuda.is_available() else "cpu"
        m = AutoModel.from_pretrained(SIGLIP, local_files_only=True, dtype=torch.float16 if dev == "cuda" else torch.float32)
        _M.extend([m.to(dev).eval(), AutoProcessor.from_pretrained(SIGLIP, local_files_only=True), dev, torch])
    return _M


def embed_images(imgs):
    from PIL import Image
    m, p, dev, torch = siglip()
    out = []
    for i in range(0, len(imgs), 32):
        x = p(images=[Image.fromarray(cv2.cvtColor(f, cv2.COLOR_BGR2RGB)) for f in imgs[i:i + 32]], return_tensors="pt").to(dev)
        with torch.no_grad():
            e = m.get_image_features(pixel_values=x["pixel_values"].to(m.dtype))
        e = getattr(e, "pooler_output", e)
        out.append(torch.nn.functional.normalize(e.float(), dim=-1).cpu().numpy())
    return np.concatenate(out) if out else np.zeros((0, 1152))


def embed_texts(texts):
    m, p, dev, torch = siglip()
    x = p(text=texts, padding="max_length", max_length=64, truncation=True, return_tensors="pt").to(dev)
    with torch.no_grad():
        e = m.get_text_features(**x)
    e = getattr(e, "pooler_output", e)
    return torch.nn.functional.normalize(e.float(), dim=-1).cpu().numpy()


# ---------------------------------------------------------------- 3 pick / 5 review (the vision model)

def jpg(img):
    return "data:image/jpeg;base64," + base64.b64encode(cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 88])[1].tobytes()).decode()


def vlm(content, max_tokens=1500):
    """OpenAI-style chat call with interleaved text and images; the first server that answers wins (t7, then t8)."""
    body = json.dumps({"model": "vlm", "temperature": 0, "max_tokens": max_tokens, "response_format": {"type": "json_object"},
                       "messages": [{"role": "user", "content": content}]}).encode()
    err = None
    for url in VLM:
        try:
            req = urllib.request.Request(f"{url}/chat/completions", body, {"Content-Type": "application/json"})
            d = json.loads(urllib.request.urlopen(req, timeout=600).read())
            return json.loads(d["choices"][0]["message"]["content"] or "{}")
        except Exception as e:                                 # this server is down or busy: try the next
            err = e
            print("vision server failed:", url, e, flush=True)
    raise RuntimeError(f"no vision server answered: {err}")


PICK = """You are a senior news video editor cutting a voice-over-only news video from footage other channels already
aired. Every second of the voice plays over a picture.

STORY: {head}
THE SCRIPT (one line per beat):
{lines}

NOW CUTTING beat {n}: "{text}"
It lasts {secs:.0f} seconds; it needs {need} shot(s). The writer suggested on screen: {want} (a hint, not a must).
{before}
Below are {k} candidate shots (one frame each, from other channels' videos).

Rules:
- Show the SUBJECT of the line: a named person -> that person; a named place -> that place; an action -> that action
  by the right side; a company -> its buildings, products, people. If the event itself was never filmed, footage of
  the people or place involved is right.
- A line that names or quotes a person: only THAT person (or the event itself) fits. Another person, even one from
  this story (a prime minister for his defence minister's words), is "no" for that line.
- A logo, emblem or flag on its own is "topic" at most.
- Photos, social-media posts, newspaper pages, headline screenshots, documents and news text on screen are all usable
  material, like footage. Read their on-screen text: about THIS story -> "exact" when it shows the line's own subject
  or is the post/report the line quotes, else "subject"; about another case or event -> "no".
- Unusable: a TV presenter or reporter talking to camera, a TV studio, a channel's title card / promo / end screen,
  maps, charts, footage of a different event.
- Footage of a DIFFERENT event is "no": check the video title and the shot's ON-SCREEN TEXT (read for you below each
  shot; scoreboards, captions, banners, subtitles in any language). Other names, places or numbers than this story's
  (a different opponent on the scoreboard, a different ship, a different death toll, another country's crash in a
  caption) mean a different event. Text like "representative visuals", "file" or "archive" means it is NOT this event
  (only archive of the same people/places). AI-made, animated or re-enacted footage is "no".
- "kind" is what the picture IS. Camera footage with a ticker, caption, banner or subtitles over it is still "footage"
  (or "speech"). "post_or_document" is a frame that IS a social post, newspaper page, headline screenshot, document or
  a full-frame news text card. "text_card" is only a channel's own branding: its title card, promo, "subscribe" or end
  screen. A post, headline or news text about this story is "post_or_document", never "text_card".
- A video uploaded well before this story cannot show this event, but it CAN show the same named people, places and
  things (archive): a singer's earlier concert for "the singer will perform", the court building for a ruling. That
  is "subject", and it is the normal choice for a line about something not filmed yet.
- If no shot shows the line's own subject (the moment was never filmed: an investigation, a decision, a call), shots
  of the story's main people, place, vessel or aftermath are the right choice: mark them "subject" and pick them.
- A shot may be shown as 2 frames: its middle and the moment its picture changes most, in time order. Judge it by
  both: a brief moment (a flash, an explosion, a hit, a fall) may be visible in only one frame, and that moment is what
  the shot shows. A place where the event is only heard, not seen, is "subject" at most.
- Prefer moving footage over a still of equal fit. Prefer shots that differ from the previous beat's shots.
- Order the chosen shots as events happen (cause before effect, the strike before the ruins).
- "sound": the scene sound our sound-effects model should make for the shot, max 8 words ("rifle gunfire and shell
  casings", "ship engine and waves against the hull", "tank tracks clanking on a road", "missile launch roar"), ONLY
  when the shot shows an action or a moving thing that makes a distinct sound: firing, explosions, strikes, launches,
  missiles, aircraft, tanks and military vehicles moving, ships sailing, fire burning, damage and rubble being cleared,
  crowds chanting or marching. "" for everything else: still or static scenes (buildings, power lines, substations,
  landscapes, offices), people talking or posing, photos, posts, documents, text, maps.

Answer with JSON only:
{{"shots": [{{"n": <shot number>, "kind": "footage" | "speech" | "photo" | "post_or_document" | "presenter" | "studio" |
             "promo" | "text_card" (a channel's own title / promo / end card) | "map" | "chart" | "animation",
             "shows": "<what is visible, max 10 words>", "at": <the frame (1 or 2) that shows it best>,
             "sound": "<scene sound, max 8 words, or \"\">",
             "fit": "exact" (shows this line's subject/event) | "subject" (the story's people/place, another moment) |
                    "topic" (only the general topic) | "no"}}  ... one entry for EVERY shot],
 "pick": [<shot numbers in screen order, best first unless order matters, up to {most}>],
 "why": "<one sentence>"}}"""

REVIEW = """You are a senior news video editor checking a finished voice-over-only news video before it airs.
STORY: {head}
Below, each cut is one frame with the line spoken over it. Channels routinely use archive footage: an earlier concert
of a named singer, earlier pictures of a named person, place or building. That is RIGHT, even for a future event.
Tickers, captions, banners and subtitles over footage are fine. Social posts, newspaper pages, headline screenshots,
documents and news text cards about this story are RIGHT material too.
Flag a cut only if:
- it shows a different person, place or event than its line is about (not just an earlier occasion of the same one);
  text on screen naming other people, places or numbers counts as evidence;
- it is a TV presenter or reporter talking to camera, a studio, a channel's own promo / subscribe / end screen, a map
  or a chart;
- it is the same picture as the cut right before it.
Answer with JSON only: {{"bad": [{{"cut": <cut number>, "why": "<max 10 words>"}}], "flow": "<one sentence on how the whole
sequence reads>"}}  (an empty "bad" list when every cut is right)"""


# ---------------------------------------------------------------- 4 assemble

def clauses(text, secs, words=None):
    """Phrase breaks inside the beat, as times from its start: commas/full stops, timed by the voice's words when given."""
    toks = text.split()
    if words and len(words) >= len(toks) * 0.8:
        t0 = words[0]["start"]
        return [w["end"] - t0 for w in words[:-1] if re.search(r"[,.;:!?]$", w["w"])]
    out, n = [], 0
    for w in toks[:-1]:
        n += 1
        if re.search(r"[,.;:!?]$", w) or w.lower() in ("and", "but", "while", "after", "as"):
            out.append(secs * n / len(toks))
    return out


def cut_points(secs, k, breaks):
    """k cuts over secs seconds: even split, each cut moved to the nearest phrase break within 1.2 s."""
    pts = []
    for i in range(1, k):
        t = secs * i / k
        near = [b for b in breaks if abs(b - t) <= 1.2 and b - (pts[-1] if pts else 0.0) >= CUT[0] and secs - b >= CUT[0]]
        t = min(near, key=lambda b: abs(b - t)) if near else max(t, (pts[-1] if pts else 0.0) + CUT[0])
        if t <= secs - CUT[0]:                                   # no room for this cut: one cut fewer
            pts.append(t)
    return [0.0] + pts + [secs]


def plan_beat(secs, picks, breaks):
    """Lengths for the chosen shots: as many cuts as the beat needs (one per ~3.5 s, max 3, more if shots are short),
    cut on phrase breaks; a shot shorter than its slot keeps its own length and the others take up the rest."""
    k = max(1, min(len(picks), 3, round(secs / 3.5) or 1, int(secs // CUT[0]) or 1))
    while True:
        pts = cut_points(secs, k, breaks)
        lens = [b - a for a, b in zip(pts, pts[1:])]
        cap = [p["len"] - 0.6 for p in picks[:len(lens)]]
        if all(c >= L for c, L in zip(cap, lens)) or k >= min(len(picks), 4 if secs >= 9 else 3, int(secs // CUT[0]) or 1):
            break
        k += 1
    lens = [min(L, c) for L, c in zip(lens, cap)]
    left = secs - sum(lens)
    for i in sorted(range(len(lens)), key=lambda i: -(cap[i] - lens[i])):
        add = max(0.0, min(left, cap[i] - lens[i])); lens[i] += add; left -= add
    return list(zip(picks[:len(lens)], lens))


def hold_longer(cuts, secs, by_id):
    """Cuts too short for the beat even together: lengthen them inside their shots (longest shot first, at most
    CUT[2] each) and re-time them. Returns the seconds still missing."""
    gap = secs - sum(c["secs"] for c in cuts)
    if gap < 0 and cuts:                                         # too long (a longer shot swapped in): trim the longest cut
        cut = max(cuts, key=lambda c: c["secs"])
        cut["secs"] = round(max(MIN_CUT, cut["secs"] + gap), 2); cut["end"] = round(cut["start"] + cut["secs"], 2)
        gap = secs - sum(c["secs"] for c in cuts)
    for cut in sorted(cuts, key=lambda c: -by_id[c["shot"]]["len"]):
        if gap <= 0.05:
            break
        sh = by_id[cut["shot"]]
        add = max(0.0, min(gap, min(sh["end"] - 0.3, cut["start"] + CUT[2]) - cut["end"]))
        cut["end"] = round(cut["end"] + add, 2); cut["secs"] = round(cut["secs"] + add, 2); gap -= add
    t = cuts[0]["at"] if cuts else 0.0
    for cut in cuts:
        cut["at"] = round(t, 2); t += cut["secs"]
    return max(0.0, gap)


def repeats(cuts, same):
    """Indexes of cuts that break the repeat rules (criteria items 19-20): the same shot or picture as the cut right before
    it, or one that already played less than REUSE_GAP s earlier. cuts: [{shot, at, secs}] in screen order."""
    bad = []
    for i, c in enumerate(cuts):
        for k, p in enumerate(cuts[:i]):
            if (p["shot"] == c["shot"] or same(p["shot"], c["shot"])) and (k == i - 1 or c["at"] - (p["at"] + p["secs"]) < REUSE_GAP):
                bad.append(i)
                break
    return bad


def place(c, sh, use, note):
    """Point cut c at shot sh (its middle `use` seconds), with the model's notes for sh."""
    a = cut_start(dict(sh, focus=note.get("focus")), use)
    for k in ("image", "url", "page"):
        c.pop(k, None)
    c.pop("focus", None)                                         # the swapped-out shot's moment is not this shot's
    if note.get("focus") and sh["start"] <= note["focus"] <= sh["end"]:
        c["focus"] = round(note["focus"], 2)
    c.update(shot=sh["id"], video=sh["video"], start=round(a, 2), end=round(a + use, 2), secs=round(use, 2), shot_end=round(sh["end"], 2),
             kind="photo" if sh.get("own") else note.get("kind"),
             fit=note.get("fit"), shows=note.get("shows"), sound=note.get("sound", ""), title=sh["title"][:80],
             **({"image": sh["path"], "url": sh.get("url"), "page": sh.get("page")} if sh.get("own") else {}))


def own_search(query, out_dir):
    """Our own pictures for a line the clips can't show: the studio's free picture search (Bing + Wikimedia Commons, no
    stock libraries) with its filters for broadcaster logos, text-heavy images, collages and duplicates.
    -> [{path, url, page, title, w, h}]; [] when the search or the studio code is unavailable."""
    try:
        if OWN not in sys.path:
            sys.path.insert(0, OWN)
        from pipeline.orchestrator import assets
        if not _O:
            ocr(np.zeros((32, 32, 3), np.uint8))
        assets._ocr = lambda path: [(b.tolist(), t, c) for b, t, c in zip(*(lambda r: (r.boxes, r.txts, r.scores) if r.txts else ([], [], []))(_O[0](str(path))))]
        got = assets.vo_pictures(query, out_dir, keep=6, log=lambda m: print("  own:", m, flush=True))
        return [g for g in got if not LICENSED.search((g.get("page") or "") + " " + (g.get("url") or ""))][:4]
    except Exception as e:                                       # no studio code / search down: the beat stays short, flagged
        print("own picture search failed:", type(e).__name__, e, flush=True)
        return []


# ---------------------------------------------------------------- story

def run_story(s, out, timing, preview):
    t_all = time.time()
    sd = out / s["sid"]; sd.mkdir(parents=True, exist_ok=True)
    news = dt.date.fromisoformat(s["date"]) if s.get("date") else None
    beats = s["beats"]
    for b in beats:
        b["secs"] = float(b.get("secs") or max(3.0, len(b["text"].split()) / WPS))

    # 1 gate: every shot of every video, middle frame, picture hash; repeats (re-uploads, same frame) dropped
    t0 = time.time(); shots = []

    def fetch(v):                                            # download + shot split, 4 videos at a time
        if (v.get("dur") or 0) > MAX_VIDEO_S or fake(v.get("verdict") or ""):
            return v, None, []                               # too long, or the search found it AI-made / re-enacted
        try:
            p = download(v["id"])
            return v, p, shots_of(p)
        except Exception as e:
            print("download failed, skipped", v["id"], e, flush=True)
            return v, None, []

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(4) as ex:
        fetched = list(ex.map(fetch, s["videos"]))
    timing["download_s"] = timing.get("download_s", 0.0) + time.time() - t0
    for v, p, vshots in fetched:
        if p is None:
            continue
        up = (info(v["id"]).get("upload_date") or "")
        up = dt.date(int(up[:4]), int(up[4:6]), int(up[6:8])) if len(up) == 8 else None
        for sh in vshots:
            a, b = sh["start"], sh["end"]
            fr = frames_at(p, [a + (b - a) * q for q in (0.25, 0.5, 0.75)])
            if any(f is None for f in fr):
                continue
            h = phash(fr[1])
            if h is None:
                continue
            dup = next((x for x in shots if same_pic(x["hash"], h)), None)
            if dup:                                             # the same picture: keep the longer copy
                if b - a > dup["len"]:
                    dup.update(video=v["id"], path=str(p), start=a, end=b, len=b - a, frames=fr, up=up, title=v.get("title", ""))
                continue
            shots.append({"id": len(shots), "video": v["id"], "path": str(p), "start": a, "end": b, "len": b - a,
                          "frames": fr, "hash": h, "up": up, "title": v.get("title", ""),
                          "moment_beats": {m["beat"] for m in v.get("moments") or [] if m["start"] - 1 <= (a + b) / 2 <= m["end"] + 1}})
    timing["gate_s"] += time.time() - t0
    print(s["sid"], "shots", len(shots), "from", len(s["videos"]), "videos", flush=True)
    if not shots:                                                # no usable footage at all: every beat gets our own pictures
        print(s["sid"], "no footage: own pictures only", flush=True)

    # 2 rank: SigLIP similarity of each beat's text (+ wanted picture) to each shot (mean of 3 frames)
    t0 = time.time()
    E = embed_images([f for sh in shots for f in sh["frames"]]).reshape(len(shots), 3, -1).mean(1) if shots else np.zeros((0, 1152))
    E /= np.maximum(np.linalg.norm(E, axis=1, keepdims=True), 1e-9)
    T = embed_texts([b["text"] for b in beats]) + embed_texts([b.get("picture") or b["text"] for b in beats])
    T /= np.linalg.norm(T, axis=1, keepdims=True)
    S = T @ E.T                                                  # beats x shots
    timing["rank_s"] += time.time() - t0

    # 3 pick, beat by beat (each call sees what the previous beat got)
    t0 = time.time()
    lines = "\n".join(f"{i}. {b['text']}" for i, b in enumerate(beats, 1))
    edit, used, pool = [], {}, {}                               # used: shot id -> story time it last ended; pool: fitting shots
    by_id = {sh["id"]: sh for sh in shots}
    # the same picture: across videos, one clip re-aired by two channels (embedding); inside one video the shot cuts
    # already separate the pictures, so only a replay (near-identical frame) counts
    def same(a, b):
        if a == b:
            return False
        x, y = by_id[a], by_id[b]
        if x["video"] != y["video"]:
            return float(E[a] @ E[b]) > SAME_SCENE
        tx, ty = x.get("ocr", ("", 0))[0], y.get("ocr", ("", 0))[0]     # one card shown twice: same words, same look
        return same_pic(x["hash"], y["hash"]) or (len(tx) >= 8 and tx == ty and float(E[a] @ E[b]) > SAME_SCENE)
    recent = lambda k: any(clock - t < REUSE_GAP and (u == k or same(u, k)) for u, t in used.items())
    clock = 0.0

    def see(xs):
        """Full-size middle frame + on-screen text for every shot not looked at yet (4 at a time), and the frames the model
        sees: the middle and, when the picture changes, the moment it changes most (a brief flash or blast shows only there)."""
        todo = [x for x in xs if "mid" not in x]

        def one(x):
            a, b = x["start"], x["end"]
            m = (a + b) / 2
            x["mid"] = frames_at(x["path"], [m])[0]
            x["ocr"] = ocr(x["mid"])
            if x.get("own") or b - a < 1.2:
                x["views"] = [(m, x["mid"])]
                return
            pk = peak_time(x["path"], a, b)                     # 2 frames, not 3: 10 shots x 3 full frames went past
            x["views"] = [(m, x["mid"])]                         # the server's 32k context (33k tokens, 2026-11-22)
            if abs(pk - m) > 0.15 * (b - a):
                f = frames_at(x["path"], [pk])[0]
                if f is not None:
                    x["views"] = sorted(x["views"] + [(pk, f)], key=lambda v: v[0])
        t1 = time.time()
        if todo and not _O:
            one(todo.pop(0))                                     # loads the OCR engine once, before the threads share it
        with ThreadPoolExecutor(4) as ex:
            list(ex.map(one, todo))
        timing["ocr_s"] = timing.get("ocr_s", 0.0) + time.time() - t1

    def own_shots(b, bi):
        """Our own pictures for beat b as shots of the pool (embedded and ranked like footage)."""
        nonlocal E, S
        nm = names(b["text"])
        q = " ".join(nm[:3]) if nm else (b.get("picture") or s.get("headline") or "")
        if nm and s.get("place") and s["place"].lower() not in q.lower():
            q += " " + s["place"]
        q = " ".join(dict.fromkeys(w for w in q.replace(",", " ").split()))      # "president x mongolian president x" -> once
        pics = own_search(q, CACHE / "own" / s["sid"] / str(b["id"]))
        new = []
        for ph in pics:
            img = cv2.imread(ph["path"])
            h = phash(img) if img is not None else None
            if h is None or any(same_pic(x["hash"], h) for x in shots):
                continue
            sh = {"id": len(shots), "video": "own", "path": ph["path"], "start": 0.0, "end": OWN_MAX + 0.6, "len": OWN_MAX + 0.6,
                  "frames": [img] * 3, "hash": h, "up": None, "title": ph.get("title") or q, "moment_beats": set(), "own": True,
                  "url": ph.get("url"), "page": ph.get("page")}
            shots.append(sh); by_id[sh["id"]] = sh; new.append(sh)
        if new:
            e = embed_images([x["frames"][0] for x in new])
            E = np.vstack([E, e]); S = np.hstack([S, T @ e.T])
        print(s["sid"], b["id"], "own pictures", len(new), "for", repr(q), flush=True)
        return new

    for bi, b in enumerate(beats):
        print(f"PROGRESS beat {bi + 1}/{len(beats)}", flush=True)        # the site's progress line (worker.py step_check)
        event = b.get("cls", "event") == "event" and b.get("dated", True)
        early = lambda sh: bool(news and sh["up"] and (news - sh["up"]).days > EARLY_DAYS)
        ok = shots
        nm = names(b["text"])
        boost = lambda sh: NAME_BOOST * min(2, sum(1 for n in nm if n in sh["title"].lower()))
        ranked = sorted(ok, key=lambda sh: -(S[bi, sh["id"]] + boost(sh) + (0.02 if b["id"] in sh["moment_beats"] else 0)
                                                - (0.02 if event and early(sh) else 0)))
        if os.environ.get("VO_RANKDUMP"):                                 # why a shot was / wasn't a candidate
            with open(os.path.join(os.environ["VO_RANKDUMP"], f"rank_{b['id']}.txt"), "w") as f:
                for r, sh in enumerate(ranked[:60], 1):
                    f.write(f"{r:3} {S[bi, sh['id']] + boost(sh):.3f} {sh['video']} {sh['start']:.1f}-{sh['end']:.1f}"
                            f"{' early' if event and early(sh) else ''}{' recent' if recent(sh['id']) else ''} | {sh['title'][:60]}\n")
        cands, per = [], {}
        for sh in ranked:
            if per.get(sh["video"], 0) >= PER_VIDEO or recent(sh["id"]):
                continue
            per[sh["video"]] = per.get(sh["video"], 0) + 1
            cands.append(sh)
            if len(cands) == CANDS:
                break
        need = max(1, min(3, round(b["secs"] / 3.5)))
        prev = edit[-1]["cuts"] if edit else []
        before = ("The previous beat showed: " + "; ".join(c["shows"] for c in prev) + ".") if prev else ""
        def ask(nums, extra="", cs=None):
            """One pick call over candidates `nums` (1-based, numbers kept), each with its title, age and on-screen text."""
            cs = cs or cands
            content = [{"type": "text", "text": PICK.format(head=s.get("headline") or s.get("title", ""), lines=lines, n=bi + 1, text=b["text"],
                                                             secs=b["secs"], need=need, want=b.get("picture") or "the subject of the line",
                                                             before=before, k=len(nums), most=min(len(cands), need + 1)) + extra}]
            for i in nums:
                sh = cs[i - 1]
                age = ""
                if news and sh.get("up"):
                    d = (sh["up"] - news).days
                    age = (f", uploaded {-d // 365} year(s) before this story" if d <= -365 else f", uploaded {-d} days before this story"
                           if d < -EARLY_DAYS else ", uploaded around this story's date")
                src = f'our own picture from "{sh["title"][:90]}"' if sh.get("own") else f'from the video "{sh["title"][:90]}"{age}'
                txt = f' On-screen text: "{sh["ocr"][0]}".' if sh["ocr"][0] else " No on-screen text."
                vs = sh.get("views") or [(0, sh["mid"])]
                content += [{"type": "text", "text": f'Shot {i} ({sh["len"]:.1f} s, {src}).{txt}'
                                                     + (f" {len(vs)} frames of it:" if len(vs) > 1 else "")}]
                content += [{"type": "image_url", "image_url": {"url": jpg(f)}} for _, f in vs]
            try:
                return vlm(content)
            except Exception as e:                               # no labels = no edit worth showing: fail the check (the
                print("pick failed", s["sid"], b["id"], e, flush=True)   # site offers Retry), never a silent photo-only edit
                raise RuntimeError(f"the vision model could not label beat {b['id']}: {e}") from e

        def label(j):
            return {int(x.get("n", 0)): dict(x, kind=word(x.get("kind")), fit=word(x.get("fit")))
                    for x in j.get("shots") or [] if str(x.get("n", "")).isdigit()}

        see(cands)
        j = ask(range(1, len(cands) + 1)) if cands else {}
        notes = label(j)
        miss = [i for i in range(1, len(cands) + 1) if i not in notes]
        if miss and j:                                           # the model skipped some: ask once more for just those
            j2 = ask(miss, f"\n(You already labelled the other shots. Label EVERY one of these {len(miss)}, keeping their numbers.)")
            notes.update({i: x for i, x in label(j2).items() if i in miss})
            j["pick"] = list(j.get("pick") or []) + list(j2.get("pick") or [])
            timing["reasks"] = timing.get("reasks", 0) + 1
        good = lambda i: 1 <= i <= len(cands) and notes.get(i, {}).get("kind") not in DROP and notes.get(i, {}).get("fit") in ("exact", "subject")
        order = [int(i) for i in j.get("pick") or [] if str(i).isdigit()]
        picks = [i for i in dict.fromkeys(order) if good(i)]
        picks += [i for i in range(1, len(cands) + 1) if i not in picks and good(i) and notes[i]["fit"] == "exact"]   # spares
        picks += [i for i in range(1, len(cands) + 1) if i not in picks and good(i)]
        def focus(sh, i):
            vs, k = sh.get("views") or [], notes.get(i, {}).get("at")
            return vs[int(k) - 1][0] if str(k).isdigit() and 1 <= int(k) <= len(vs) else None
        note = lambda sh, i, **kw: dict(sh, shows=notes.get(i, {}).get("shows", ""), sound=str(notes.get(i, {}).get("sound") or "")[:80],
                                        fit=notes.get(i, {}).get("fit", "?"),
                                        kind=notes.get(i, {}).get("kind", "?"), n=i, focus=focus(sh, i), **kw)
        for i in range(1, len(cands) + 1):                       # every fitting shot also serves later beats (story footage)
            if good(i):
                pool.setdefault(cands[i - 1]["id"], note(cands[i - 1], i))
        prev_ids = [c["shot"] for c in prev]
        chosen = []
        for c in [note(cands[i - 1], i) for i in picks]:
            if c["len"] - 0.6 < MIN_CUT or any(same(c["id"], x) for x in [k["id"] for k in chosen] + prev_ids):
                continue                                         # the same picture as a shot already in (or just before)
            chosen.append(c)
        fill = []
        have = sum(min(c["len"] - 0.6, CUT[2]) for c in chosen[:3])
        if have < b["secs"] - 0.3:                               # not enough: the story's own fitting footage from earlier beats
            extra = sorted((x for x in pool.values() if x["len"] - 0.6 >= MIN_CUT and x["id"] not in {c["id"] for c in chosen} and x["id"] not in prev_ids
                            and not recent(x["id"])
                            and not any(same(x["id"], c["id"]) for c in chosen)), key=lambda x: -S[bi, x["id"]])
            for x in extra[:2]:
                chosen.append(dict(x, fill=True)); fill.append("story footage")
                have += min(x["len"] - 0.6, CUT[2])
                if have >= b["secs"] - 0.3:
                    break
        if have < b["secs"] - 0.3:                               # still short: our own pictures (criteria item 16 step 5), automatic
            mine = own_shots(b, bi)
            if mine:
                see(mine)
                jo = ask(range(1, len(mine) + 1), "\n(These are OUR OWN pictures from an image search, for a line the clips could "
                                                  "not cover. Pick only pictures that show this line's subject.)", cs=mine)
                on = label(jo)
                okk = lambda i: 1 <= i <= len(mine) and on.get(i, {}).get("kind") not in DROP and on.get(i, {}).get("fit") in ("exact", "subject")
                ids = {c["id"] for c in chosen} | set(prev_ids)
                for i in [i for i in dict.fromkeys(int(x) for x in jo.get("pick") or [] if str(x).isdigit()) if okk(i)] + \
                         [i for i in range(1, len(mine) + 1) if okk(i)]:
                    x = mine[i - 1]
                    if x["id"] in ids or any(same(x["id"], k) for k in ids):
                        continue
                    chosen.append(dict(x, shows=on[i].get("shows", ""), sound="", fit=on[i]["fit"], kind="photo", n=i, fill=True))
                    fill.append("own picture"); ids.add(x["id"])
                    have += OWN_MAX
                    if have >= b["secs"] - 0.3:
                        break
        if have < b["secs"] - 0.3:                               # still short: this beat's on-topic shots, flagged
            ids = {c["id"] for c in chosen} | set(prev_ids)
            for i in range(1, len(cands) + 1):
                x = cands[i - 1]
                if (notes.get(i, {}).get("fit") == "topic" and notes.get(i, {}).get("kind") not in DROP and x["len"] - 0.6 >= MIN_CUT
                        and x["id"] not in ids and not any(same(x["id"], k) for k in ids) and not recent(x["id"])):
                    chosen.append(note(x, i, fill=True)); fill.append("topic footage"); ids.add(x["id"])
                    have += min(x["len"] - 0.6, CUT[2])
                    if have >= b["secs"] - 0.3:
                        break
        if not chosen:                                           # nothing at all: the best-ranked usable shot, flagged
            fall = [i for i in range(1, len(cands) + 1) if notes.get(i, {}).get("kind") not in DROP
                    and cands[i - 1]["len"] - 0.6 >= MIN_CUT
                    and notes.get(i, {}).get("fit") != "no" and not any(same(cands[i - 1]["id"], u) or cands[i - 1]["id"] == u for u in used)]
            chosen = [note(cands[i - 1], i) for i in fall[:1]]
            fill.append("no fitting shot: best-ranked used")
        # 4 assemble this beat: keep same-video shots in their original order, then cut lengths on phrase breaks
        top = chosen[:3]
        first = {}
        for i, c in enumerate(top):
            first.setdefault(c["video"], i)
        top.sort(key=lambda c: (first[c["video"]], c["start"]))
        breaks = clauses(b["text"], b["secs"], b.get("words"))
        plan = plan_beat(b["secs"], top + chosen[3:], breaks) if top else []
        cuts, t = [], 0.0
        for c, L in plan:
            use = min(L, c["len"] - 0.6)
            a = cut_start(c, use)
            cuts.append({"shot": c["id"], "video": c["video"], "start": round(a, 2), "end": round(a + use, 2), "secs": round(use, 2),
                         **({"focus": round(c["focus"], 2)} if c.get("focus") else {}),
                         "at": round(clock + t, 2), "shot_end": round(c["end"], 2), "kind": "photo" if c.get("own") else c["kind"], "fit": c["fit"], "shows": c["shows"], "sound": c.get("sound", ""), "title": c["title"][:80], **({"fill": True} if c.get("fill") else {}),
                         **({"image": c["path"], "url": c.get("url"), "page": c.get("page")} if c.get("own") else {})})
            t += use
        gap = hold_longer(cuts, b["secs"], by_id)
        if gap > 0.3:
            fill.append(f"{gap:.1f} s short")
        for cut in cuts:
            used[cut["shot"]] = clock + b["secs"]
        edit.append({"beat": b["id"], "text": b["text"], "secs": round(b["secs"], 2), "cuts": cuts, "fill": fill,
                     "why": j.get("why", ""), "candidates": [{"n": i, "shot": c["id"], "video": c["video"], "start": c["start"], "end": c["end"],
                                                              "sim": round(float(S[bi, c["id"]]), 3), "title": c["title"][:80],
                                                              **{k: notes.get(i, {}).get(k) for k in ("kind", "fit", "shows", "sound")},
                                                              **({"image": c["path"], "url": c.get("url"), "page": c.get("page")} if c.get("own") else {})}
                                                             for i, c in enumerate(cands, 1)],
                     "spares": [c["id"] for c in chosen[len(plan):]]})
        clock += b["secs"]
    timing["pick_s"] += time.time() - t0

    # 5 review: the whole edit, one frame per cut with its line; misfits swapped for the beat's next spare
    t0 = time.time()
    flat = [(e, c) for e in edit for c in e["cuts"]]

    def flat_cuts_near(e):
        i = next(k for k, x in enumerate(edit) if x is e)
        return [c for x in edit[max(0, i - 1):i + 2] for c in x["cuts"]]
    content = [{"type": "text", "text": REVIEW.format(head=s.get("headline") or s.get("title", ""))}]
    for i, (e, c) in enumerate(flat, 1):
        f = frames_at(next(x["path"] for x in shots if x["id"] == c["shot"]), [(c["start"] + c["end"]) / 2])[0]
        content += [{"type": "text", "text": f'Cut {i} ({c["secs"]:.1f} s), line: "{e["text"]}"'}, {"type": "image_url", "image_url": {"url": jpg(f)}}]
    try:
        rv = vlm(content, 800)
    except Exception as e:
        print("review failed", s["sid"], e, flush=True); rv = {}
    for bad in rv.get("bad") or []:
        try:
            e, c = flat[int(bad["cut"]) - 1]
        except (KeyError, ValueError, IndexError, TypeError):
            continue
        c["review"] = bad.get("why", "")
        inbeat = {x["shot"] for x in e["cuts"]}
        spare = next((sid for sid in e["spares"] if sid not in inbeat), None)
        near = {x["shot"] for x in flat_cuts_near(e)}               # this beat's and the neighbouring beats' cuts
        if spare is not None and any(same(spare, y) for y in near):
            spare = None                                         # no better shot of its own: keep the cut, flagged
        if spare is None and len(e["cuts"]) > 1:                 # ...unless the beat's other cuts can hold its time
            rest = [dict(x) for x in e["cuts"] if x is not c]
            if hold_longer(rest, e["secs"], by_id) <= 0.3:
                e["cuts"][:] = [x for x in e["cuts"] if x is not c]
                e["fill"].append(f"dropped: {bad.get('why', '')}"[:80])
                continue
        if spare is not None:
            sh = next(x for x in shots if x["id"] == spare)
            if sh["len"] - 0.6 >= MIN_CUT:
                use = min(max(c["secs"], CUT[0]), sh["len"] - 0.6)
                if spare in e["spares"]:
                    e["spares"].remove(spare)
                cand = pool.get(spare) or next((x for x in e["candidates"] if x["video"] == sh["video"] and x["start"] == sh["start"]), {})
                place(c, sh, use, cand); c["swapped"] = True
    for e in edit:                                               # a swapped-in shot may be shorter or longer: re-time the beat
        if any(c.get("swapped") for c in e["cuts"]) or any(f.startswith("dropped") for f in e["fill"]):
            e["fill"] = [f for f in e["fill"] if not f.endswith(" s short")]
            gap = hold_longer(e["cuts"], e["secs"], by_id)
            if gap > 0.3:
                e["fill"].append(f"{gap:.1f} s short")
    timing["review_s"] += time.time() - t0

    # 6 enforce: a swap or a fill may have broken the repeat rules; a breaking cut takes the beat's best spare that keeps
    # them, else it is dropped (its beat's other cuts hold longer), else it stays, flagged
    def retime():
        clock = 0.0
        for e in edit:
            t = clock
            for c in e["cuts"]:
                c["at"] = round(t, 2); t += c["secs"]
            clock += e["secs"]
    retime()
    stuck = set()
    for _ in range(50):
        flat = [c for e in edit for c in e["cuts"]]
        bad = [i for i in repeats(flat, same) if id(flat[i]) not in stuck]
        if not bad:
            break
        c = flat[bad[0]]
        bi, e = next((k, x) for k, x in enumerate(edit) if any(y is c for y in x["cuts"]))
        old = dict(c)
        opts = sorted({*e["spares"], *pool} - {x["shot"] for x in e["cuts"]}, key=lambda k: -S[bi, k])
        for k in opts:
            sh = by_id[k]
            if sh["len"] - 0.6 < MIN_CUT:
                continue
            place(c, sh, min(old["secs"], sh["len"] - 0.6), pool.get(k) or {})
            if bad[0] not in repeats([y for x in edit for y in x["cuts"]], same):
                c["repeat_fixed"] = True
                break
            c.clear(); c.update(old)
        else:
            if len(e["cuts"]) > 1:
                e["cuts"].remove(c); e["fill"].append("repeat dropped")
            else:
                c["repeat"] = True; stuck.add(id(c))
        gap = hold_longer(e["cuts"], e["secs"], by_id)
        e["fill"] = [f for f in e["fill"] if not f.endswith(" s short")] + ([f"{gap:.1f} s short"] if gap > 0.3 else [])
        retime()
    timing["repeat_fixes"] = timing.get("repeat_fixes", 0) + sum(1 for e in edit for c in e["cuts"] if c.get("repeat_fixed")) + \
        sum(e["fill"].count("repeat dropped") for e in edit)

    res = {"sid": s["sid"], "headline": s.get("headline"), "flow": rv.get("flow", ""), "beats": edit,
           "secs": round(sum(e["secs"] for e in edit), 1), "shots_in_pool": len(shots), "videos": len(s["videos"])}
    (sd / "edit.json").write_text(json.dumps(res, indent=1, ensure_ascii=False))
    sheet(res, shots, sd / "sheet.jpg")
    if preview:
        render_preview(res, shots, sd / "preview.mp4")
    timing["stories"][s["sid"]] = round(time.time() - t_all, 1)


def sheet(res, shots, path, w=427, h=240):
    """One tile per cut: its middle frame, beat id, length, what the model saw; the beat's line under the row."""
    rows = []
    for e in res["beats"]:
        tiles = []
        for c in e["cuts"]:
            f = frames_at(next(x["path"] for x in shots if x["id"] == c["shot"]), [(c["start"] + c["end"]) / 2])[0]
            t = cv2.resize(f, (w, h)) if f is not None else np.zeros((h, w, 3), np.uint8)
            cv2.rectangle(t, (0, 0), (w, 22), (0, 0, 0), -1)
            cv2.putText(t, f"{e['beat']} {c['secs']:.1f}s {c.get('fit') or ''}{' SWAP' if c.get('swapped') else ''}"[:60], (5, 16),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
            tiles.append(t)
        tiles = tiles[:4]
        while len(tiles) < 4:
            tiles.append(np.zeros((h, w, 3), np.uint8))
        cap = np.zeros((44, w * 4, 3), np.uint8)
        txt = f"{e['beat']} ({e['secs']:.0f}s) {e['text']}" + (f"  [{'; '.join(e['fill'])}]" if e["fill"] else "")
        for k in range(2):
            cv2.putText(cap, txt[k * 200:(k + 1) * 200], (6, 18 + 20 * k), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        rows.append(np.vstack([np.hstack(tiles), cap]))
    if rows:
        cv2.imwrite(str(path), np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 85])


def render_preview(res, shots, path):
    """Silent 16:9 rough cut with each beat's line burned in: for checking picks by eye, not a deliverable."""
    parts, tmp = [], path.parent / "parts"
    tmp.mkdir(exist_ok=True)
    k = 0
    for e in res["beats"]:
        for c in e["cuts"]:
            src = next(x["path"] for x in shots if x["id"] == c["shot"])
            txt = re.sub(r"[':\\%]", "", e["text"])[:110]
            o = tmp / f"{k:03d}.mp4"; k += 1
            inp = ["-loop", "1", "-t", str(c["secs"]), "-i", src] if c.get("image") else ["-ss", str(c["start"]), "-t", str(c["secs"]), "-i", src]
            subprocess.run([FFMPEG, "-v", "error", "-y", *inp, "-an",
                            "-vf", f"scale=854:480:force_original_aspect_ratio=decrease,pad=854:480:-1:-1,setsar=1,fps=25,"
                                   f"drawtext=text='{e['beat']} {txt}':x=10:y=h-30:fontsize=15:fontcolor=white:box=1:boxcolor=black@0.6",
                            "-c:v", "libx264", "-preset", "veryfast", "-crf", "26", str(o)], check=True)
            parts.append(o)
    lst = tmp / "list.txt"; lst.write_text("".join(f"file '{p.name}'\n" for p in parts))
    subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(path)], check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inputs"); ap.add_argument("out"); ap.add_argument("--only", default=""); ap.add_argument("--preview", action="store_true")
    a = ap.parse_args()
    stories = [s for s in json.load(open(a.inputs)) if not a.only or s["sid"] in a.only.split(",")]
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
    timing = {"gate_s": 0.0, "rank_s": 0.0, "pick_s": 0.0, "review_s": 0.0, "stories": {}}
    for s in stories:
        try:
            run_story(s, out, timing, a.preview)
        except Exception as e:                                   # one bad story never stops the run
            import traceback; traceback.print_exc()
            print("story failed", s["sid"], e, flush=True)
        (out / "timing.json").write_text(json.dumps({k: (round(v, 1) if isinstance(v, float) else v) for k, v in timing.items()}, indent=1))
    print(json.dumps(timing), flush=True)


def selftest():
    c = {"start": 6.17, "end": 10.18}
    assert abs(cut_start(dict(c, focus=6.6), 3.0) - 6.32) < 0.01                  # the flash at 6.6 s stays on the cut
    assert abs(cut_start(c, 3.0) - 6.675) < 0.01                                   # no focus: the middle, as before
    assert cut_start(dict(c, focus=9.9), 3.0) <= 10.18 - 0.3 - 3.0 + 1e-9           # never past the shot's end
    import tempfile
    vid = os.path.join(tempfile.mkdtemp(), "flash.mp4")
    w = cv2.VideoWriter(vid, cv2.VideoWriter_fourcc(*"mp4v"), 25, (320, 180))
    for k in range(100):                                                           # 4 s, a white flash at 2.0-2.2 s
        w.write(np.full((180, 320, 3), 255 if 50 <= k < 55 else 40, np.uint8))
    w.release()
    assert 1.9 <= peak_time(vid, 0.0, 4.0) <= 2.3, peak_time(vid, 0.0, 4.0)
    assert fake("AI-generated news cast, not real footage") and fake("This is a re-enactment of the attack")
    assert not fake("Real footage, not AI-generated.") and not fake("Raw footage of the rescue")
    assert not fake("No visual description; likely a studio report or reenactment") and not fake("may be AI-generated")
    br = clauses("The ship sank, and the crew was saved by helicopters.", 6.0)
    assert len(br) == 2 and 0 < br[0] < br[1] < 6.0
    pts = cut_points(9.0, 3, [2.9, 6.2])
    assert pts[0] == 0 and pts[-1] == 9.0 and pts[1:3] == [2.9, 6.2], pts
    pts = cut_points(7.0, 3, [1.4, 3.5]); assert all(b - a >= 2.0 - 1e-9 for a, b in zip(pts, pts[1:])), pts
    p = plan_beat(8.0, [{"len": 3.0}, {"len": 9.0}, {"len": 9.0}], [])
    assert abs(sum(L for _, L in p) - 8.0) < 1e-6 and all(c["len"] - 0.6 >= L - 1e-6 for c, L in p)
    assert names("Glastonbury has announced the headliners. The lineup includes Harry Styles, Billie Eilish, and Sam Fender.") == \
        ["harry styles", "billie eilish", "sam fender"], names("Glastonbury has announced the headliners. The lineup includes Harry Styles, Billie Eilish, and Sam Fender.")
    assert "miro g" in names("The bulk carrier Miro G has run aground off the coast of Lit-et-Mixe in France.")
    assert "betul 8" in names("Bulgarian rescue teams saved the crew after the cargo ship Betul 8 sank in the Black Sea.")
    cuts = [{"shot": 1, "at": 0, "secs": 3}, {"shot": 2, "at": 3, "secs": 3}, {"shot": 2, "at": 6, "secs": 3},
            {"shot": 1, "at": 9, "secs": 3}, {"shot": 3, "at": 12, "secs": 3}, {"shot": 1, "at": 30, "secs": 3}, {"shot": 4, "at": 33, "secs": 3}]
    assert repeats(cuts, lambda a, b: False) == [2, 3], repeats(cuts, lambda a, b: False)      # in a row; back 6 s after
    assert repeats(cuts, lambda a, b: {a, b} == {3, 4}) == [2, 3]                             # 3 and 4 same picture but 18 s apart
    assert repeats(cuts[:2], lambda a, b: True) == [1]                                       # same picture in a row
    print("selftest ok")


if __name__ == "__main__":
    selftest() if sys.argv[1:] == ["test"] else main()
