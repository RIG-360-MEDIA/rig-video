"""One machine job for one story (tools venv on trijya-7, started by app.py):
  worker.py write|voice|search|render <project_id>
  worker.py check <project_id> [<section_id> ...]     (VO only: the clip checker; section ids = check only those beats)
  worker.py keyword <project_id> <section_id> <keyword_id>
  worker.py selection
Progress and results go into the project's project.json (store.py), so the site sees them on its next poll; stdout is
the project's log.txt. The pipeline code (script checks, LLM pool, pictures, footage, render and assembly tools) is
~/anchor-studio/studio-app, imported read-only."""
import datetime as dt
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import store  # noqa: E402

HOME = store.HOME
STUDIO = HOME / "anchor-studio"
APPDIR = pathlib.Path(os.environ.get("RIGVIDEO_APP", STUDIO / "studio-app"))
PIPE, REG = APPDIR / "pipeline", APPDIR / "anchor_registry"
ST_TOOLS, FOOT_TOOLS = PIPE / "tools" / "sourcetrack", PIPE / "tools" / "footage"
TOOLS_PY = os.environ.get("ANCHOR_TOOLS_PY", str(HOME / ".cache" / "anchor-tools" / "bin" / "python"))
SV = STUDIO / "repos" / "social_verifier"
os.environ["PATH"] = f"{STUDIO / 'repos' / 'ffmpeg-shared' / 'current' / 'bin'}:{HOME / '.local' / 'bin'}:" + os.environ.get("PATH", "")

# clip checker (trijya-8 4070): visual_pick.py looks at every shot of the found videos and checks where it was filmed
V8HOST = os.environ.get("VISION_HOST", "trijya-8@100.95.0.11")
V8SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20", "-i", os.environ.get("VISION_KEY", str(HOME / ".ssh" / "to_trijya8")), V8HOST]
VISION_VIDEOS = 6                                                  # top found videos per section the checker looks at
MIN_CLIP_S = 3.0     # shortest clip cut from a found moment
YTDLP = HOME / "anchor-studio" / "repos" / "social_verifier" / "ytdlp_node.sh"   # the footage repo's yt-dlp (PO tokens, node)
SOURCE_FMT = "bv*[height<=720][vcodec^=avc1]+ba[ext=m4a]/b[height<=720][vcodec^=avc1]/bv*[height<=720]+ba/b[height<=720]"
# VO-only (9:16) crops from the frame, so it needs the height: up to 1080p (golden set Q9: a crop may be upscaled at most 2x)
SOURCE_FMT_VO = "bv*[height<=1080][vcodec^=avc1]+ba[ext=m4a]/b[height<=1080][vcodec^=avc1]/bv*[height<=1080]+ba/b[height<=1080]"
SOURCE_MAX_S = 1200  # longer found videos are not downloaded whole (their moments are still cut on use)
CHECKER = False      # the clip checker is off until it is rebuilt (user, 2026-11-19): every found moment is cut and shown instead

# voice box (trijya-3): Chatterbox + an ffmpeg with Rubber Band
VHOST = os.environ.get("ANCHOR_VOICE_HOST", "trijya-3@100.99.155.88")
VKEY = os.environ.get("ANCHOR_VOICE_KEY", str(HOME / ".ssh" / "to_trijya3"))
VROOT = os.environ.get("ANCHOR_VOICE_ROOT", "/home/trijya-3/anchor-studio")
VPY = f"{VROOT}/repos/chatterbox/.venv/bin/python"
VSSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20", "-i", VKEY, VHOST]

sys.path.insert(0, str(PIPE))
from orchestrator import common  # noqa: E402

common.load_env()
from orchestrator import llm  # noqa: E402
import writer  # noqa: E402

FPS, SHOT, CTX, LEAD, KEEP_TAIL, MAX_FIT = 24, 328, 39, 0.25, 0.45, 0.09
PID = ""


def log(msg):
    print(f"[{store.now():%H:%M:%S}] {msg}", flush=True)


class Say(RuntimeError):
    """An error written for the person using the site; anything else is logged and shown as a plain message."""


PLAIN = {"write": "The script could not be written just now. Press Try again.",
         "voice": "The voices could not be made just now. Try again in a few minutes.",
         "search": "The footage search stopped with an error. Search the keyword again.",
         "render": "The render stopped with an error. Send it to render again.",
         "check": "The clip check stopped with an error. Press Check again.",
         "final": "The final video could not be made. Press Make it again.",
         "post": "Posting stopped with an error. Press Post again."}


def run(cmd, cwd=None, on_line=None):
    """Run a command, streaming its output into the log; raise with its last lines on failure."""
    log("RUN " + " ".join(map(str, cmd))[:300])
    p = subprocess.Popen(list(map(str, cmd)), cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    tail = []
    for line in p.stdout:
        print(line, end="", flush=True)
        tail = (tail + [line.rstrip()])[-15:]
        if on_line:
            on_line(line.strip())
    if p.wait() != 0:
        what = next((pathlib.Path(w).name for w in map(str, cmd) if w.endswith(".py")), pathlib.Path(str(cmd[0])).name)
        raise RuntimeError(f"{what} failed: " + " | ".join(tail[-4:]))
    return tail


def ff(*a):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *map(str, a)], check=True)


def vcp(*a):
    """scp to/from the voice box (last argument = destination)."""
    run(["scp", "-q", "-r", "-o", "BatchMode=yes", "-i", VKEY, *a])


def media(pid, rel):
    """Absolute path of a project file (dirs made); the site loads it as /files/<pid>/<rel>."""
    f = store.pdir(pid) / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    return f


def url(pid, f):
    return f"/files/{pid}/{pathlib.Path(f).relative_to(store.pdir(pid))}"


def registry():
    return {a["id"]: a for a in json.load(open(REG / "registry.json"))["anchors"]}


def sections(p):
    return p["versions"][p["format"]]


def find(p, sid):
    return next((s for s in sections(p) if s["id"] == sid), None)


# ------------------------------------------------------------------ pace (words a second per anchor voice)

CAL = store.DATA / "calibration.json"


def pace(anchor):
    try:
        return json.loads(CAL.read_text())[anchor]["wps"]
    except (OSError, KeyError, json.JSONDecodeError):
        return registry().get(anchor, {}).get("voice_wps", 2.85)


def learn_pace(anchor, samples):
    """samples: [(words, speech seconds)]; running average over the last 40."""
    try:
        cal = json.loads(CAL.read_text())
    except (OSError, json.JSONDecodeError):
        cal = {}
    hist = ((cal.get(anchor) or {}).get("samples") or []) + [[w, round(s, 2)] for w, s in samples if s > 2]
    hist = hist[-40:]
    if hist:
        cal[anchor] = {"wps": round(sum(w for w, _ in hist) / sum(s for _, s in hist), 3), "samples": hist}
        CAL.write_text(json.dumps(cal, indent=1))


# ------------------------------------------------------------------ numbers spoken for the voice

ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()


def words_of(n):
    if n < 20:
        return ONES[n]
    if n < 100:
        return TENS[n // 10] + ("" if n % 10 == 0 else "-" + ONES[n % 10])
    if n < 1000:
        return ONES[n // 100] + " hundred" + ("" if n % 100 == 0 else " and " + words_of(n % 100))
    for size, name in ((10 ** 9, "billion"), (10 ** 6, "million"), (1000, "thousand")):
        if n >= size:
            rest = n % size
            return words_of(n // size) + " " + name + ("" if not rest else (" and " if rest < 100 else " ") + words_of(rest))
    return str(n)


def spoken(text):
    def num(m):
        s = m.group(0).replace(",", "")
        if "." in s:
            a, b = s.split(".", 1)
            return words_of(int(a)) + " point " + " ".join(ONES[int(c)] for c in b)
        n = int(s)
        if 1900 <= n <= 2099 and len(s) == 4:
            return words_of(n // 100) + (" hundred" if n % 100 == 0 else " " + (("oh-" + ONES[n % 100]) if n % 100 < 10 else words_of(n % 100)))
        return words_of(n)
    t = text.replace("%", " per cent").replace("&", " and ")
    t = re.sub(r"\s[-–—]\s", ", ", t)
    return re.sub(r"\s+", " ", re.sub(r"\d[\d,]*(?:\.\d+)?", num, t)).strip()


# ------------------------------------------------------------------ write: source -> both versions, facts, LT, ticker

def fetch_article(u):
    import html
    import urllib.request
    req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0 (RIG-Video)"})
    raw = urllib.request.urlopen(req, timeout=30).read(2_000_000).decode("utf-8", "replace")
    title = html.unescape(re.sub(r"<[^>]+>", "", (re.search(r"<title[^>]*>(.*?)</title>", raw, re.S | re.I) or [None, ""])[1])).strip()
    paras = [html.unescape(re.sub(r"<[^>]+>", "", x)).strip() for x in re.findall(r"<p[^>]*>(.*?)</p>", raw, re.S | re.I)]
    body = "\n\n".join(x for x in paras if len(x.split()) > 8)
    if len(body.split()) < 80:
        raise Say("Could not find the article text on that page. Paste the article text instead.")
    title = re.sub(r"\s+[|—–]\s+[^|—–]{2,40}$", "", title.split(" | ")[0])   # "… — Democracy News Live"; ponytail: also cuts a real "— Day 3" tail
    return title[:140], body


def step_write(p):
    """An editor's story fails fast when t3 is busy (they are told to try later); a story written by itself (daily run,
    type switch) has nobody to press Try again, so it waits and tries again for up to ~30 min (other teams share t3)."""
    tries = 10 if p.get("_autoApprove") else 1
    for k in range(tries):
        try:
            with store.gpu("writer"):
                _write(store.read(p["id"]))
            break
        except writer.Busy:
            if k == tries - 1:
                raise
            log(f"writer busy: trying again in 3 min ({k + 1}/{tries - 1})")
            store.job(p["id"], "write", note="The script writer is busy; trying again in a few minutes")
            time.sleep(180)
    if store.read(p["id"]).get("_autoApprove"):                     # daily run / type switch: approve it by itself
        store.update(p["id"], lambda q: (q.pop("_autoApprove", None), store.approved(q)))
        start_job(p["id"], "voice")
        start_job(p["id"], "search")


def _write(p):
    pid = p["id"]
    src = p["source"]
    if not src.get("text") and src.get("url"):
        store.job(pid, "write", progress=0.05, note="Reading the source")
        title, body = fetch_article(src["url"])
        slug = src["url"].rstrip("/").rsplit("/", 1)[-1].replace("-", " ")[:90]    # the site's stand-in until the page is read
        p = store.update(pid, lambda q: (q["source"].update(text=body),
                                         q.update(headline=title if title and q["headline"] in ("", "New story", slug) else q["headline"])))
    text = p["source"]["text"]
    if len(text.split()) < 40:
        raise Say("The source is too short to write from. Paste the full article or a link to it.")
    if p["format"] == "vo_only":
        return _write_vo(p, text)
    article = f"{p['headline']}\n\n{text[:14000]}"
    shot = SHOT / FPS - LEAD - KEEP_TAIL
    apps, vos, a_words, v_words = writer.plan(p["targetSeconds"], shot, pace(p["anchorId"]))
    system = writer.system(p["targetSeconds"], apps, vos, a_words, v_words)
    user = f"HEADLINE: {p['headline']}\n\nARTICLE:\n{text[:14000]}"
    best, feedback = None, ""
    for attempt in range(1, 4):
        store.job(pid, "write", progress=0.15 + 0.25 * (attempt - 1), note="Writing the script" if attempt == 1 else "Rewriting what the checks found")
        sc = writer.ask(system, user + feedback, writer.schema(apps + vos), max_tokens=max(4000, p["targetSeconds"] * 40), log=log)
        secs = [dict(kind=str(x.get("kind")), text=str(x.get("text") or "").strip(), search=str(x.get("search") or "").strip())
                for x in sc.get("sections") or [] if isinstance(x, dict) and str(x.get("text") or "").strip()]
        sc["sections"] = secs
        if not writer.order_ok(secs, apps, vos):                   # wrong order/count: write it again from scratch
            log(f"write attempt {attempt}: sections {[x['kind'] for x in secs]}")
            continue
        checks = writer.notes(sc, article, a_words, v_words)
        facts_bad = [c for c in checks if "not in the article" in c]
        if best is None or len(facts_bad) < best[1]:
            best = (sc, len(facts_bad), checks)
        if not facts_bad:
            break
        log(f"write attempt {attempt}: {facts_bad[:4]}")
        feedback = ("\n\nYOUR PREVIOUS SCRIPT:\n" + json.dumps(sc, ensure_ascii=False) + "\nThese are not in the article: "
                    + "; ".join(facts_bad) + ". Remove them or replace them with what the article says. Keep everything else "
                    "and return the full JSON again.")
    if best is None:
        raise Say("The script model did not return the sections in the right order. Try Write again.")
    sc, _, problems = best
    secs = sc["sections"]
    lt = sc.get("lt") if isinstance(sc.get("lt"), dict) else {}
    ticker = [str(t).strip() for t in sc.get("ticker") or [] if str(t).strip()]
    kinds = [("anchor" if x.get("kind") == "anchor" else "vo") for x in secs]
    na = nv = 0
    vo = []
    for x, k in zip(secs, kinds):
        na, nv = na + (k == "anchor"), nv + (k == "vo")
        vo.append({"id": f"a{na}" if k == "anchor" else f"v{nv}", "kind": k, "text": x["text"]})
    search = {s["id"]: str(x.get("search") or "").strip() for s, x in zip(vo, secs)}
    facts = [{"label": str(f.get("label") or "Fact"), "value": str(f.get("value") or "")}
             for f in sc.get("facts") or [] if isinstance(f, dict) and f.get("value")][:6]
    ticker = ticker[:7] or [p["headline"]]
    if problems:
        log(f"written with notes left: {problems[:6]}")

    def save(q):
        q["versions"].update({"anchor_vo": vo, "anchor_only": [dict(s, kind="anchor") for s in vo]})
        q["facts"], q["ticker"] = facts, ticker
        q["lt"] = {"kicker": str(lt.get("kicker") or "").upper()[:14], "headline": str(lt.get("headline") or q["headline"]).upper()[:48],
                   "subline": str(lt.get("subline") or "")[:70]}
        if sc.get("headline") and q["source"]["kind"] != "link":
            q["headline"] = str(sc["headline"])[:90]
        q["_search"] = search
        q["_checks"] = problems
    store.update(pid, save)


def _write_vo(p, text):
    """VO only: the article -> beats (writer.vo_*: picture, what it shows, its footage search, the line). The checks'
    notes (writer.vo_notes) get one rewrite each, up to three tries; the try with the fewest notes is kept."""
    pid, secs, day = p["id"], p["targetSeconds"], p["createdAt"][:10]
    article = f"{p['headline']}\n\n{text[:14000]}"
    system, user = writer.vo_system(secs), writer.vo_user(p["headline"], "", text[:14000], day)
    best, feedback = None, ""
    for attempt in range(1, 4):
        store.job(pid, "write", progress=0.15 + 0.25 * (attempt - 1), note="Writing the beats" if attempt == 1 else "Rewriting what the checks found")
        sc = writer.ask(system, user + feedback, writer.vo_schema(), max_tokens=max(4000, secs * 40), log=log)
        sc["beats"] = [b for b in sc.get("beats") or [] if isinstance(b, dict) and str(b.get("text") or "").strip()]
        if len(sc["beats"]) < 2:
            log(f"write attempt {attempt}: {len(sc['beats'])} beats")
            continue
        checks = writer.vo_notes(sc, article, secs)
        fix = [c for c in checks if not c.startswith(("(info)", "READINESS"))]
        off = max(0.0, abs(secs - writer.vo_seconds([str(b["text"]) for b in sc["beats"]])) - secs * 0.1)
        if best is None or (round(off), len(fix)) < best[1]:         # the asked length first (within 10%), then fewest notes
            best = (sc, (round(off), len(fix)), checks)
        if not fix:
            break
        log(f"write attempt {attempt}: {fix[:4]}")
        feedback = ("\n\nYOUR PREVIOUS SCRIPT:\n" + json.dumps(sc, ensure_ascii=False) + "\nFix these: " + "; ".join(fix)
                    + ". Keep everything else and return the full JSON again.")
    if best is None:
        raise Say("The script model did not return the beats. Try Write again.")
    sc, _, checks = best
    beats = [{"id": f"b{i}", "kind": "vo", "text": str(b["text"]).strip(), "picture": str(b.get("shows") or "").strip()[:200],
              "search": str(b.get("search") or "").strip()[:120], "cls": "archive" if b.get("picture") == "archive" else "event"}
             for i, b in enumerate(sc["beats"], 1)]
    if checks:
        log(f"written with notes left: {checks[:6]}")

    def save(q):
        q["versions"]["vo_only"] = beats
        if sc.get("headline") and q["source"]["kind"] != "link":
            q["headline"] = str(sc["headline"])[:90]
        q["_vo"] = {"picturedDate": writer.vo_pictured_date(sc, article, day), "eventFilmed": bool(sc.get("event_filmed", True)),
                    "supportedSeconds": sc.get("supported_seconds"), "eventSearch": str(sc.get("event_search") or "").strip()[:80]}
        q["_checks"] = checks
    store.update(pid, save)


# ------------------------------------------------------------------ voice: Chatterbox on the voice box, best take per section

TONE = {"grave": (0.6, 0.45), "urgent": (0.8, 0.35), "serious": (0.7, 0.4), "measured": (0.65, 0.45), "brisk": (0.75, 0.4)}


def target_for(d0):
    n = max(1, round(((LEAD + d0 + KEEP_TAIL) * FPS - CTX) / (SHOT - CTX)))
    return n, (SHOT + (n - 1) * (SHOT - CTX)) / FPS - LEAD - KEEP_TAIL


def speech_seconds(path):
    import numpy as np
    import soundfile as sf
    x, sr = sf.read(str(path), dtype="float32")
    x = x if x.ndim == 1 else x.mean(1)
    loud = np.flatnonzero(np.abs(x) > 10 ** (-45 / 20))
    return (loud[-1] - loud[0]) / sr if len(loud) else 0.0


_WHISPER = None


def wer(path, text):
    global _WHISPER
    import difflib
    if _WHISPER is None:
        from faster_whisper import WhisperModel
        _WHISPER = WhisperModel("small.en", device="cpu", compute_type="int8")
    said = " ".join(s.text for s in _WHISPER.transcribe(str(path))[0])
    norm = lambda s: re.sub(r"[^a-z0-9' ]", " ", spoken(s).lower().replace("-", " ")).split()
    return 1 - difflib.SequenceMatcher(None, norm(text), norm(said)).ratio()


def asked(note, ex, cfg, text):
    """A "what should change" note -> (exaggeration, cfg_weight, text to speak, tempo). Slower/Faster stretch the finished
    take (Rubber Band, pitch kept): Chatterbox's cfg_weight barely moved the pace. A higher exaggeration reads less flat.
    "X is Y" respells a name for the voice only (the script keeps X)."""
    n = (note or "").lower()
    tempo = 0.9 if "slower" in n else 1.1 if "faster" in n else 1.0
    if "more serious" in n:
        ex -= 0.2
    if "less flat" in n:
        ex, cfg = ex + 0.2, cfg - 0.05
    for name, say in re.findall(r"([A-Z][\w'-]+(?: [A-Z][\w'-]+)*) (?:is said|is pronounced|sounds like|is|=) [\"“']?([A-Za-z][A-Za-z' -]*[A-Za-z])", note or ""):
        text = re.sub(rf"\b{re.escape(name)}\b", say, text)
    if "pause before the last line" in n:
        parts = re.split(r"(?<=[.!?])\s+", text.strip())
        if len(parts) > 1:
            text = " ".join(parts[:-1]) + " ... " + parts[-1]
    return round(min(1.2, max(0.3, ex)), 2), round(min(0.7, max(0.2, cfg)), 2), text, tempo


def make_takes(p, texts, seeds, ex=None, cfg=None, tempo=1.0):
    """Chatterbox takes on the voice box: {section id: [local wav, ...]}, plus the remote folder."""
    a = registry()[p["anchorId"]]
    tag = f"t{int(time.time())}"
    remote = f"{VROOT}/studio/{p['id']}/{tag}"
    ref = f"{VROOT}/studio/refs/{pathlib.Path(a['voice_file']).name}"
    if ex is None:
        ex, cfg = TONE.get(str(p.get("tone") or "serious").lower(), (0.7, 0.4))
    conf = {"anchor": p["anchorId"], "ckpt_dir": f"{VROOT}/models/chatterbox", "ref_audio": ref, "exaggeration": [ex],
            "cfg_weight": [cfg], "seeds": seeds, "scripts": {k: spoken(t) for k, t in texts.items()}}
    local = media(p["id"], f"voice/{tag}/config.json")
    local.write_text(json.dumps(conf, indent=1, ensure_ascii=False))
    run(VSSH + [f"mkdir -p {remote} {VROOT}/studio/refs"])
    vcp(REG / a["voice_file"], f"{VHOST}:{ref}")
    vcp(local, f"{VHOST}:{remote}/config.json")
    with store.gpu("voice"):                                        # the script model is unloaded meanwhile
        run(VSSH + [f"cd {VROOT}/voice_lab && {VPY} chatterbox_takes.py {remote}/config.json {remote}/takes"])
    if tempo != 1.0:                                                # in place on the voice box: renders use the remote file
        run(VSSH + [f"cd {remote}/takes && for w in *.wav; do PATH=$HOME/.local/bin:$PATH ffmpeg -v error -y -i \"$w\" "
                    f"-af rubberband=tempo={tempo} -c:a pcm_f32le \"_$w\" && mv \"_$w\" \"$w\"; done"])
    vcp(f"{VHOST}:{remote}/takes", local.parent)
    out = {}
    for t in json.load(open(local.parent / "takes" / "takes.json"))["takes"]:
        out.setdefault(t["script_label"], []).append(local.parent / "takes" / t["take"])
    return out, f"{remote}/takes"


def score(kind, wav, text):
    """Sort key of a take: every word right first, then (anchor sections) closest to filling whole shots."""
    d0 = speech_seconds(wav)
    e = wer(wav, text)
    n, target = target_for(d0)
    return (round(e, 2) > 0.05, abs(d0 / target - 1) if kind == "anchor" else 0, e), d0


def step_voice(p):
    """Every section whose voice is making/redoing gets takes; loops until none is left (text edited meanwhile)."""
    pid = p["id"]
    with store._lock(store.DATA / "voice.lock"):                   # one voice job at a time on the voice box
        while True:
            p = store.read(pid)
            todo = {s["id"]: s for s in sections(p) if (s.get("voice") or {}).get("state") in ("making", "redoing") and s["text"].strip()}
            if not todo:
                return recheck_changed(p)
            redo = any(s["voice"]["state"] == "redoing" for s in todo.values())
            done = sum(1 for s in sections(p) if (s.get("voice") or {}).get("state") == "ready")
            store.job(pid, "voice", progress=done / max(1, len(sections(p))), note=f"Making the voice ({len(todo)} part{'s' * (len(todo) > 1)})")
            seeds = [int(time.time()) % 1000 + k for k in (1, 2, 3)] if redo else [11, 23, 41]
            texts = {k: s["text"] for k, s in todo.items()}
            base = TONE.get(str(p.get("tone") or "serious").lower(), (0.7, 0.4))
            groups = {}                                             # parts with the same voice settings go in one run
            for k, s in todo.items():
                note = s["voice"].get("note") if s["voice"]["state"] == "redoing" else ""
                ex, cfg, say, tempo = asked(note, *base, s["text"])
                groups.setdefault((ex, cfg, tempo), {})[k] = say
            made = {}
            for (ex, cfg, tempo), says in groups.items():
                takes, remote = make_takes(p, says, seeds, ex, cfg, tempo)
                if (ex, cfg, tempo) == (*base, 1.0):
                    learn_pace(p["anchorId"], [(len(spoken(says[k]).split()), speech_seconds(w)) for k, ws in takes.items() for w in ws])
                for k, wavs in takes.items():
                    ranked = sorted((score(todo[k]["kind"], w, says[k]) + (w,) for w in wavs), key=lambda x: x[0])
                    made[k] = [{"id": f"{w.parent.parent.name}-{w.stem}", "src": url(pid, w), "seconds": round(d0, 2),
                                "_file": str(w), "_remote": f"{remote}/{w.name}"} for _, d0, w in ranked]

            def save(q):
                files = q.setdefault("_takes", {})
                for s in sections(q):
                    new = made.get(s["id"])
                    if not new or not s.get("voice"):
                        continue
                    for t in new:
                        files[t["id"]] = {"file": t.pop("_file"), "remote": t.pop("_remote"), "text": texts[s["id"]]}
                    v = s["voice"]
                    v["takes"] = (v.get("takes") or []) + new if v["state"] == "redoing" else new
                    v["pick"] = new[0]["id"]
                    if s["text"] == texts[s["id"]]:                 # edited while voicing: stays "making" for the next round
                        v["state"] = "ready"
            store.update(pid, save)


# ------------------------------------------------------------------ footage search: the footage repo's API, one project per section

SVB = "http://127.0.0.1:8787/api"
LIVE = re.compile(r"\bLIVE\b|\blive ?stream|\b24/7\b", re.I)
STATE = {"idle": "idle", "pending": "queued", "queued": "queued", "searching": "searching", "analyzing": "searching", "done": "done", "error": "error"}
VF = {"crop": "crop=iw*0.9:ih*0.9,scale=640:360",
      "blur_fill": "split[a][b];[a]scale=640:360:force_original_aspect_ratio=increase,crop=640:360,boxblur=20:2,eq=brightness=-0.12[bg];"
                   "[b]crop=ih*9/16:ih,scale=-2:360[fg];[bg][fg]overlay=(W-w)/2:0"}
FLAG_OF = {"label:presenter": "presenter", "label:graphic": "text", "label:map": "text", "label:website": "logo",
           "label:vertical": "vertical", "side bars": "vertical", "label:call": "presenter"}


def sv_up():
    import urllib.request
    try:
        urllib.request.urlopen(f"{SVB}/health", timeout=3)
        return True
    except Exception as e:                                          # 401/404 still means it is up
        return hasattr(e, "code")


def sv_client():
    import httpx
    if not sv_up():
        subprocess.Popen(["bash", str(FOOT_TOOLS / "start_backend.sh")], stdout=open(store.DATA / "footage_backend.log", "a"),
                         stderr=subprocess.STDOUT, start_new_session=True)
        for _ in range(60):
            time.sleep(3)
            if sv_up():
                break
        else:
            raise Say("The footage search service did not start.")
    sys.path.insert(0, str(SV / "backend"))
    from app.core.auth import AUTH_PASSWORD, AUTH_USERNAME     # the footage backend's own single account
    tok = httpx.post(f"{SVB}/auth/login", json={"username": AUTH_USERNAME, "password": AUTH_PASSWORD}, timeout=30).json()["token"]
    return httpx.Client(headers={"Authorization": f"Bearer {tok}"}, timeout=120)


BLOCKED = re.compile(r"429|Too Many Requests|Sign in to confirm|not a bot|HTTP Error 403|blocked", re.I)


def blocked_check(c, svp):
    """YouTube refusing us shows up as keyword/clip errors: stop early and say so (the site shows it; nothing is retried)."""
    errs = [k.get("error_message") or "" for s in svp["segments"] for k in s["keywords"]] + [x.get("error_message") or "" for x in svp["clips"]]
    bad = [e for e in errs if BLOCKED.search(e)]
    if bad:
        (store.DATA / "youtube_blocked").write_text(f"{store.stamp()} {bad[0][:300]}")
        raise Say("YouTube is refusing our searches right now (rate limit). Try again later; nothing was lost.")


def keywords_of(svp):
    return [k for s in svp["segments"] for k in s["keywords"]]


def map_found(svp, old):
    """The footage project's keywords and videos -> Keyword[] and FoundVideo[] (best first, one entry per YouTube video).
    Cut clips, flags and treatments already on the site (old) are kept."""
    have = {f["youtubeId"]: f for f in old.get("found", [])}
    kws, found, seen = [], [], set()
    for k in keywords_of(svp):
        n = len([v for v in k["videos"] if v["analyzed"]])
        kws.append({"id": k["id"][:8], "text": k["text"], "reason": k.get("rationale") or "", "state": STATE.get(k["status"], "queued"),
                    "progress": k.get("progress") or (f"{n} videos" if k["status"] == "done" else ""),
                    "_sv": k["id"]})
    vids = sorted(((v, k) for k in keywords_of(svp) for v in k["videos"] if v["analyzed"] and (v["relevance"] or 0) >= 10),
                  key=lambda x: -x[0]["relevance"])
    for v, k in vids:
        if v["video_id"] in seen or v["video_id"] in old.get("wrongPlace", []):
            continue
        seen.add(v["video_id"])
        prev = have.get(v["video_id"], {})
        moments = v["moments"]
        for i, m in enumerate(moments):
            pm = next((x for x in prev.get("moments", []) if not x.get("checked") and abs(x["start"] - m["start"]) < 0.5), None)
            if pm:
                moments[i] = pm
        moments += [x for x in prev.get("moments", []) if x.get("checked") or x.get("custom")]   # checker's shots and the user's own ranges,
                                                                    # after the repo's (placed refs keep their index)
        found.append({"id": prev.get("id") or v["id"][:10], "keywordId": k["id"][:8], "youtubeId": v["video_id"], "title": v["title"],
                      "channel": v["channel"], "publishedAt": v["published_at"], "duration": v["duration_seconds"] or 0,
                      "thumb": v.get("thumbnail_url") or f"https://i.ytimg.com/vi/{v['video_id']}/mqdefault.jpg",
                      "relevance": v["relevance"], "verdict": v["verdict"] or "", "hasCaptions": bool(v["has_transcript"]),
                      "moments": moments, "flags": prev.get("flags", []), **({"source": prev["source"]} if prev.get("source") else {})})
    for f in found:                                                 # uncut moments: YouTube's own frame nearest the moment
        for m in f["moments"]:
            if not m.get("poster"):
                frac = m["start"] / max(f["duration"], 1)
                m["poster"] = f"https://i.ytimg.com/vi/{f['youtubeId']}/mq{1 if frac < 0.375 else 2 if frac < 0.625 else 3}.jpg"
                m["posterNear"] = True
    return kws, found


def save_visuals(pid, sid, kws, found):
    def f(q):
        v = q["visuals"].setdefault(sid, {"keywords": [], "found": [], "photos": [], "uploads": [], "maps": [], "placed": []})
        gone = set(q.get("_removedKeywords", {}).get(sid, []))     # keywords the user removed stay removed
        v["keywords"] = [{k: x for k, x in kw.items() if k != "_sv"} for kw in kws if kw["id"] not in gone]
        live = {kw["id"] for kw in v["keywords"]}
        v["found"] = [x for x in found if x["keywordId"] in live]
        q.setdefault("_svk", {}).update({kw["id"]: kw["_sv"] for kw in kws})
    store.update(pid, f)


def poll(c, svp_id, done, on=None, every=8, most=3600):
    t0 = time.time()
    while True:
        try:
            svp = c.get(f"{SVB}/footage/projects/{svp_id}").json()
        except Exception:                                           # the footage backend restarting: wait for it
            svp = {}
        if "segments" not in svp:
            if time.time() - t0 > most:
                raise Say("The footage search took over an hour and was stopped.")
            time.sleep(every)
            continue
        blocked_check(c, svp)
        if on:
            on(svp)
        if done(svp):
            return svp
        if time.time() - t0 > most:
            raise Say("The footage search took over an hour and was stopped.")
        time.sleep(every)


def cut(c, pid, sid, svp, picked):
    """[(found video, moment index)] -> each moment downloaded and cut (web copy, poster, shot check, treatment preview).
    The moment dicts are updated in place; a moment that could not be cut gets cutFailed."""
    if not picked:
        return
    seg = svp["segments"][0]
    tag = lambda f, i: f"{f['youtubeId']}_{i}"                       # file names stay unique across later cuts
    for f, i in picked:                                             # the search can give a 0.3 s moment: too short to use
        m = f["moments"][i]
        m["end"] = max(m["end"], min(m["start"] + MIN_CLIP_S, f.get("duration") or m["start"] + MIN_CLIP_S))
    local = lambda f: source_file(pid, f["youtubeId"]).exists()
    want = [{"video_id": f["youtubeId"], "video_title": f["title"], "segment_position": seg["position"],
             "label": f"{sid}_{tag(f, i)}", "start": f["moments"][i]["start"], "end": f["moments"][i]["end"]} for f, i in picked if not local(f)]
    files = {}
    if want:
        c.post(f"{SVB}/footage/projects/{svp['id']}/clips", json={"clips": want})
        svp = poll(c, svp["id"], lambda x: not any(cl["status"] in ("queued", "downloading") for cl in x["clips"]))
        files = {(cl["video_id"], round(cl["start_seconds"], 1)): cl for cl in svp["clips"] if cl["status"] == "done"}
    run_dir = store.pdir(pid) / "footage" / sid
    (run_dir / "clips").mkdir(parents=True, exist_ok=True)
    clips = []
    for f, i in picked:
        n = tag(f, i)
        m = f["moments"][i]
        full = run_dir / "clips" / f"{sid}_{n}.mp4"
        if local(f):                                                # exact cut from the whole video (re-encoded: frame-accurate)
            try:
                ff("-ss", m["start"], "-to", m["end"], "-i", source_file(pid, f["youtubeId"]), "-c:v", "libx264", "-preset", "veryfast",
                   "-crf", 18, "-c:a", "aac", "-b:a", "160k", full)
            except Exception as e:
                log(f"clip {n} unusable: {e}")
                m["cutFailed"] = True
                continue
        else:
            cl = files.get((f["youtubeId"], round(m["start"], 1)))
            if not cl:
                m["cutFailed"] = True
                continue
            full.write_bytes(c.get(f"{SVB}/footage/clips/{cl['id']}/file").content)
        web, still = media(pid, f"media/clips/{sid}_{n}.mp4"), media(pid, f"media/clips/{sid}_{n}.jpg")
        try:                                                        # one bad clip must not stop the others
            ff("-i", full, "-vf", "scale=-2:360,fps=25", "-c:v", "libx264", "-preset", "veryfast", "-crf", 28, "-c:a", "aac", "-b:a", "64k",
               "-movflags", "+faststart", web)
            ff("-ss", round(min(1.0, (m["end"] - m["start"]) / 2), 2), "-i", web, "-frames:v", 1, "-vf", "scale=480:-2", "-q:v", 5, still)
        except Exception as e:
            log(f"clip {n} unusable: {e}")
            m["cutFailed"] = True
            continue
        m.update(clip=url(pid, web), poster=url(pid, still), posterNear=False)
        clips.append({"beat": sid, "n": n, "video_id": f["youtubeId"], "title": f["title"], "file": str(full), "_f": f, "_m": m})
    (run_dir / "clips.json").write_text(json.dumps([{k: v for k, v in x.items() if not k.startswith("_")} for x in clips], indent=1))
    try:
        run([TOOLS_PY, FOOT_TOOLS / "clean_shots.py", run_dir, run_dir / "clean"])
        shots = json.load(open(run_dir / "clean" / "shots.json"))
    except (RuntimeError, OSError) as e:
        log(f"shot check skipped: {e}")
        shots = []
    for x in clips:
        why = {r.split()[0] if r.startswith("text") else r for s in shots if s["clip"] == x["file"] and not s["keep"]
               for r in s["verdict"].split("; ")}
        flags = sorted({FLAG_OF.get(r, "text" if r == "text" else "") for r in why} - {""})
        kind = "blur_fill" if "vertical" in flags else "crop"
        prev = media(pid, f"media/treated/{x['beat']}_{x['n']}_{kind}.mp4")
        ff("-i", store.pdir(pid) / x["_m"]["clip"].split(f"/files/{pid}/", 1)[1], "-vf", VF[kind], "-c:v", "libx264", "-preset", "veryfast",
           "-crf", 26, "-an", "-movflags", "+faststart", prev)
        x["_m"].update(flags=flags, treat={"kind": kind, "preview": url(pid, prev)})
        x["_f"]["flags"] = sorted(set(x["_f"]["flags"]) | set(flags))
    store.update(pid, lambda q: q.setdefault("_clipfiles", {}).update({x["_m"]["clip"]: x["file"] for x in clips}))


NOT_NAMES = set("""The This That These Those There Their They He She It Its His Her We Our A An In On At For From By With As
But And Or If When While After Before During Since Until According Meanwhile However Also Monday Tuesday Wednesday Thursday
Friday Saturday Sunday January February March April May June July August September October November December High
Representative Council Union Fund Commission President Minister Prime Government State National Forces Army Police
Officials Office Department Ministry Party Court Agency""".split())


def story_names(p, text):
    """The people, places and organisations a text names: capitalised words that do not start a sentence (headlines are
    Title Case, so the script's sentences are used), plus the story's place."""
    out = []
    for sent in re.split(r"(?<=[.!?])\s+", text):
        for w in re.findall(r"[A-Za-z][A-Za-z'’-]+", sent)[1:]:
            w = re.sub(r"['’]s$", "", w)
            if (w[0].isupper() and len(w) >= 3 or w.isupper() and len(w) >= 2) and w not in NOT_NAMES:
                out.append(w)
    return list(dict.fromkeys(out + [x for x in [(p.get("lt") or {}).get("kicker", "").title()] if len(x) >= 3]))


def story_photos(pid, p):
    """The story's picture pool, searched once per story (assets.story_pictures): captions that name the story only."""
    from orchestrator import assets
    names = story_names(p, " ".join(x["text"] for x in sections(p)))
    q = " ".join([event_query(p["headline"]), (p.get("lt") or {}).get("kicker", "").title()]).strip()
    link = (p.get("source") or {}).get("url")
    return assets.story_pictures(q, media(pid, "media/photos/pool/x").parent, names, urls=[link] if link else [], log=log)


def photos_for(pid, sid, pool, mine):
    """A part's pictures: the pool ranked by how many of the part's own names the caption has, 6 at most."""
    def score(ph):
        t = ph["title"].lower()
        return -sum(n.lower() in t for n in mine)
    d = media(pid, f"media/photos/{sid}/x").parent
    out = []
    for k, ph in enumerate(sorted(pool, key=score)[:6]):
        f = d / f"{sid}_{k}.jpg"
        ff("-i", ph["path"], "-vf", "scale='min(1920,iw)':-2", "-q:v", 3, f)
        out.append({"id": f"ph-{sid}-{k}", "src": url(pid, f), "caption": (ph.get("title") or "")[:140], "credit": "",
                    "source": urllib.parse.urlsplit(ph.get("page") or ph["url"]).netloc})
    return out


def search_section(c, p, s, extra=None, resume=False, checks=None):
    """One section: its own footage project, our dated keyword + its suggestions, videos as they are scored, then clips.
    resume: an earlier search was cut off; wait for the keywords still running on the footage machine and take what they found."""
    pid, sid = p["id"], s["id"]
    day = str(store.now().date())
    place = p["lt"].get("kicker") or ""
    event = event_query(p["headline"])
    when = event_date(p)
    after = (when - dt.timedelta(days=3)).isoformat()   # the event window opens
    sv = (p.get("_svp") or {}).get(sid)
    if not sv:   # the brief the footage search plans from: real pictures of this event or its place, not a "news report"
        body = (f"{place}: {event}. Event of {when}. Wanted on screen: footage filmed at this event, or of "
                f"{place or 'its place'} and the people and forces it names. Not wanted: maps, graphics, studio, "
                f"footage of other incidents.\n\nSEGMENT 1 — {s['text']}\n")
        sv = c.post(f"{SVB}/footage/projects", json={"mode": "script", "title": f"{p['headline'][:60]} {sid}", "script": body}).json()["id"]
        store.update(pid, lambda q: q.setdefault("_svp", {}).update({sid: sv}))
    svp = poll(c, sv, lambda x: x["status"] != "analyzing")
    if not svp["segments"]:
        raise Say(f"The footage search could not read part {sid}.")
    seg = svp["segments"][0]
    if resume:
        run_ids = [k["id"] for k in keywords_of(svp) if k["status"] in ("queued", "searching", "analyzing")]
        return finish_section(c, pid, sid, sv, run_ids, checks)
    # the event as news titles say it, uploaded from the event window on (after: = YouTube publishedAfter, footage backend)
    mine = extra or list(dict.fromkeys([(p.get("_search") or {}).get(sid) or f"{place} {event} {day[:4]}",
                                        f"{event} {day[:4]}"]))
    mine = mine if extra else [f"{k} after:{after}" for k in mine]
    for kw in mine:
        c.post(f"{SVB}/footage/projects/{sv}/segments/{seg['id']}/keywords", json={"text": kw})
    svp = c.get(f"{SVB}/footage/projects/{sv}").json()
    kws = keywords_of(svp)
    ours = [k for k in kws if k["text"] in mine]
    year = day[:4]
    sug = [k for k in kws if k not in ours and k["status"] in ("idle", "pending") and (not re.search(r"\b(19|20)\d\d\b", k["text"]) or year in k["text"])]
    run_ids = [k["id"] for k in (ours if extra else sug[:2] + ours)]
    c.post(f"{SVB}/footage/projects/{sv}/batches", json={"keyword_ids": run_ids})
    return finish_section(c, pid, sid, sv, run_ids, checks)


def event_query(headline):
    """The headline cut to the event itself: 'US Shoots Down Iranian Drones Targeting Bahrain Amid Escalating ...' ->
    'US Shoots Down Iranian Drones Targeting Bahrain'. YouTube finds the channels' reports of the event with it."""
    h = max(re.split(r"\s*[:|;—–]\s*| - ", headline), key=len)        # 'Label: the event' -> the event
    h = re.split(r"\s+(?:amid|as|after|while|following)\s+", h, maxsplit=1, flags=re.I)[0]
    return " ".join(h.split()[:9])


def stems(t):
    return {w[:5] for w in re.findall(r"[a-z]{3,}", t.lower())} - {"the", "and", "for", "with", "from", "says", "said"}


def matches(queries, title):
    """A report title about the same event: 2 of 5 words of any of the queries (at least 2)."""
    return any(len(w & stems(title)) >= max(2, -(-len(w) * 2 // 5)) for w in map(stems, queries) if w)


def first_reported(queries, reports, until, back=3):
    """The day the event was first reported: the earliest day in the `back` days up to `until` that at least two reports
    matching a query share (that day or the next). reports: [(date, title)]. A stray report never sets it, later
    follow-ups don't move it, and a daily-recurring event (strikes on a city) can't drag it back to an older incident
    (back stays short). None when nothing agrees."""
    days = sorted(d for d, t in reports if until - dt.timedelta(days=back) <= d <= until and matches(queries, t))
    return next((d for d in days if sum(d <= x <= d + dt.timedelta(days=1) for x in days) >= 2), None)


MONTHS = {m: i + 1 for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"))}
DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def stated_date(text, made):
    """The event day the article states (the writer's When fact): 'November 9', '9 Nov 2026', '2026-11-09', 'on a Thursday'.
    A missing year is the latest one not after the story; a weekday the latest one up to it. None if it names no day."""
    t = text.lower()
    m = re.search(r"\b(\d{4})-(\d\d)-(\d\d)\b", t)
    if m:
        y, mo, d = map(int, m.groups())
    else:
        m = (re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b(?:,?\s+(\d{4}))?", t)
             or re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?(?:,?\s+(\d{4}))?", t))
        if m:
            a, b, y = m.groups()
            mo, d = (MONTHS[a], int(b)) if a.isalpha() else (MONTHS[b], int(a))
            y = int(y) if y else made.year - (dt.date(made.year, mo, min(d, 28)) > made)
        elif w := next((i for i, n in enumerate(DAYS) if n in t), None):
            return made - dt.timedelta(days=(made.weekday() - w) % 7)
        else:
            return None
    try:
        return dt.date(y, mo, d)
    except ValueError:
        return None


def page_date(url):
    """The source page's own published date (JSON-LD / meta / <time>), or None."""
    import urllib.request
    raw = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (RIG-Video)"}),
                                 timeout=20).read(2_000_000).decode("utf-8", "replace")
    m = re.search(r"(?:datePublished|article:published_time|pubdate|dateCreated)[\"']?\s*(?:content=|:)\s*[\"'](\d{4}-\d\d-\d\d)", raw) \
        or re.search(r"<time[^>]+datetime=[\"'](\d{4}-\d\d-\d\d)", raw)
    return dt.date.fromisoformat(m[1]) if m else None


def event_date(p):
    """When the event happened, as the news has it, not the day the story was made here:
    1. the day the article states (the writer's When fact) if other outlets reported the event then (two matching
       reports that day or the next, up to 30 days back): a follow-up ('the final toll') keeps its event's day, and a
       wrong date in the article (DNL's Nepal crash said October 2024) finds no reports and is not used;
    2. else the day other outlets first reported it in the 3 days up to the story (or the source page's own date).
    News from Google News, searched with the headline and with the lower third. Saved with the project; the story's day
    when nothing tells."""
    p = store.read(p["id"])
    if p.get("_eventDate"):
        return dt.date.fromisoformat(p["_eventDate"]["date"])
    import email.utils
    import html
    import urllib.request
    made = dt.date.fromisoformat(p["createdAt"][:10])
    queries = [event_query(p["headline"]), f"{p['lt'].get('kicker') or ''} {p['lt'].get('headline') or ''}".strip()]
    until, how = made, "story date"
    try:
        if (p["source"].get("url") or "").startswith("http") and (d := page_date(p["source"]["url"])) and d <= made:
            until, how = d, "source page date"
    except Exception as e:
        log(f"event date: source page unread ({e})")
    news = []
    for q in dict.fromkeys(x for x in queries if x):
        try:
            u = "https://news.google.com/rss/search?" + urllib.parse.urlencode({"q": q, "hl": "en-US", "gl": "US", "ceid": "US:en"})
            x = urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0 (RIG-Video)"}), timeout=20).read().decode()
            news += [(email.utils.parsedate_to_datetime(d).date(), html.unescape(t))
                     for t, d in re.findall(r"<item><title>(.*?)</title>.*?<pubDate>(.*?)</pubDate>", x, re.S)]
        except Exception as e:
            log(f"event date: news search failed ({e})")
    when = " ".join(f["value"] for f in p.get("facts") or [] if f.get("label") == "When")
    said = stated_date(when, until)
    if said and until - dt.timedelta(days=30) <= said <= until and first_reported(queries, news, said + dt.timedelta(days=1), back=1) in (said, said + dt.timedelta(days=1)):
        until, how = said, f"the article's date, confirmed by news reports ({len(news)} checked)"
    elif d := first_reported(queries, news, until):
        until, how = d, f"first news reports ({len(news)} checked)"
    store.update(p["id"], lambda q: q.update(_eventDate={"date": until.isoformat(), "from": how}))
    log(f"event date {until} from {how} (story made {made}; stated: {when[:60] or 'none'})")
    return until


def finish_section(c, pid, sid, sv, run_ids, checks=None):
    """checks: an executor; the clip check is queued there (the next part's search runs meanwhile), else it runs now."""
    old = lambda: store.read(pid)["visuals"].get(sid, {})
    svp = poll(c, sv, lambda x: all(k["status"] in ("done", "error") for k in keywords_of(x) if k["id"] in run_ids),
               on=lambda x: save_visuals(pid, sid, *map_found(x, old())), every=15)
    c.post(f"{SVB}/footage/projects/{sv}/edit-plan")
    svp = poll(c, sv, lambda x: (x["edit_plan"] or {}).get("status") != "building")
    kws, found = map_found(svp, old())
    save_visuals(pid, sid, kws, found)

    def check():
        save_visuals(pid, sid, kws, after_search(c, pid, sid, svp, found))
    if checks is None:
        return check()
    part(pid, sid, "Waiting to cut the clips")
    return checks.submit(check)


def after_search(c, pid, sid, svp, found):
    """A part's found videos -> playable: the clip checker when it is on, else every found moment is cut."""
    if CHECKER:
        return vision_check(c, pid, sid, svp, found)
    todo = [f for f in found if not f.get("source") and not LIVE.search(f["title"]) and 0 < (f["duration"] or 0) <= SOURCE_MAX_S]
    done = [0]

    def one(f):
        try:
            download_source(pid, f)
        except Exception as e:                                       # that video's moments are still cut on use
            log(f"download {f['youtubeId']} failed: {e}")
        done[0] += 1
        part(pid, sid, f"Downloading the videos: {done[0]} of {len(todo)}")
    part(pid, sid, f"Downloading the videos: 0 of {len(todo)}")
    with ThreadPoolExecutor(3) as ex:
        list(ex.map(one, todo))
    part(pid, sid)
    log(f"downloaded {sid}: {sum(1 for f in todo if f.get('source'))} of {len(todo)} videos")
    return found


def source_file(pid, yt):
    return store.pdir(pid) / "media" / "source" / f"{yt}.mp4"


def download_source(pid, f):
    """The whole found video (<=720p, <=1080p for VO-only), once per story: the site plays it and clips are cut from it."""
    out = source_file(pid, f["youtubeId"])
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_name(f"{f['youtubeId']}.dl.mp4")
        fmt = SOURCE_FMT_VO if store.read(pid).get("format") == "vo_only" else SOURCE_FMT
        subprocess.run([str(YTDLP), "-q", "--no-warnings", "--no-playlist", "-f", fmt, "--merge-output-format", "mp4",
                        "--force-overwrites", "-o", str(tmp), f"https://www.youtube.com/watch?v={f['youtubeId']}"],
                       check=True, timeout=900, capture_output=True)
        ff("-i", tmp, "-c", "copy", "-movflags", "+faststart", out)  # index first: the browser can seek right away
        tmp.unlink(missing_ok=True)
    f["source"] = url(pid, out)


def part(pid, sid, text=None):
    """What the footage search is doing on one part, shown on that part (None: nothing, the part shows its fill)."""
    def f(p):
        j = (p.get("_jobs") or {}).get("search")
        if j is not None:
            ps = j.setdefault("parts", {})
            ps.update({sid: text}) if text else ps.pop(sid, None)
    store.update(pid, f)


CHECK_NOTE = {"videos": "Checking where each video was filmed", "facts": "Checking the shots against the story facts",
              "place": "Checking where the shots were filmed"}


def check_note(what):
    """visual_pick.py's PROGRESS text -> the part's status line."""
    m = re.fullmatch(r"shots (\d+)/(\d+)", what)
    return f"Checking clips: {m[1]} of {m[2]} shots" if m else CHECK_NOTE.get(what, "Checking clips")


def story_facts(p):
    """The writer's fact lines ("Numbers: no injuries or damage reported"): the checker rejects pictures they rule out."""
    return [f"{f['label']}: {f['value']}" for f in p.get("facts") or [] if f.get("value")]


def vision_check(c, pid, sid, svp, found):
    """The clip checker on t8 looks at the shots the search matched in the top found videos: what they show, how relevant and clean, and
    whether it was filmed at the story's place (metadata + a blind look, see visual_pick.py). Its picks become moments and
    are cut; videos filmed somewhere else leave the list. Videos already cut are not checked again.
    If the checker cannot run, nothing is cut automatically (an unchecked clip could show the wrong place): the found
    videos stay for the editor to place by hand."""
    todo = [f for f in found if not LIVE.search(f["title"]) and not any(m.get("clip") for m in f["moments"])
            and (f["duration"] or 0) <= 1200 and any(not m.get("checked") for m in f["moments"])][:VISION_VIDEOS]
    if not todo:
        part(pid, sid)
        return found
    p = store.read(pid)
    s = find(p, sid)
    job = [{"story": pid, "sid": sid, "text": f"{p['headline']}. {s['text'] if s else ''}".strip(),
            "date": event_date(p).strftime("%Y%m%d"), "facts": story_facts(p),
            "videos": [{"id": f["youtubeId"], "title": f["title"], "dur": f["duration"] or 0,
                        "moments": [[m["start"], m["end"]] for m in f["moments"] if not m.get("checked")]} for f in todo]}]
    part(pid, sid, "Checking clips")
    pr = subprocess.Popen(V8SSH + [re.sub(r"[^A-Za-z0-9_-]", "", f"{pid}_{sid}")], stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out, err = [], []
    reader = threading.Thread(target=lambda: out.append(pr.stdout.read()), daemon=True)
    reader.start()
    kill = threading.Timer(3 * 3600, pr.kill)
    kill.start()
    pr.stdin.write(json.dumps(job))
    pr.stdin.close()
    for line in pr.stderr:                                          # PROGRESS lines as the checker goes
        m = re.match(r"PROGRESS \S+ (.+)", line.strip())
        if m:
            part(pid, sid, check_note(m[1]))
        else:
            err.append(line)
    pr.wait()
    kill.cancel()
    reader.join()
    if pr.returncode:
        part(pid, sid)
        log(f"clip check for {sid} failed, nothing cut: {''.join(err).strip()[-400:]}")
        return found
    res = json.loads(out[0])
    wrong = set(res.get("wrong_videos") or [])
    store.update(pid, lambda q: q["visuals"].setdefault(sid, {}).setdefault("wrongPlace", []).extend(sorted(wrong)))
    found = [f for f in found if f["youtubeId"] not in wrong]
    by = {f["youtubeId"]: f for f in found}
    picked = []
    for x in res.get("picked") or []:
        f = by.get(x["video"])
        if not f:
            continue
        loc = x.get("location") or {}
        f["moments"].append({"start": x["start"], "end": x["end"], "label": "Checked shot", "fit": loc.get("verdict", ""),
                             "description": f"{x.get('shows', '')}. Place {loc.get('verdict', '?').lower()}: {loc.get('why', '')}",
                             "score": round(x.get("relevance", 0) * 25), "estimated": False, "checked": True})
        picked.append((f, len(f["moments"]) - 1))
    log(f"clip check {sid}: {len(picked)} shots picked, wrong place {sorted(wrong)}")
    part(pid, sid, "Cutting the checked clips")
    cut(c, pid, sid, svp, picked)
    part(pid, sid)
    return found


def step_search(p):
    pid = p["id"]
    store.job(pid, "search", note="Waiting its turn (a render is using the machine)")
    with store._lock(store.DATA / "search.lock", shared=True), ThreadPoolExecutor(1) as checks:   # searches run side by side,
        c = sv_client()                                             # only a render waits for them; clip checks queue on t8
        p = store.read(pid)                                         # while the next part searches
        if p["format"] == "vo_only":
            search_vo(c, p)
            start_job(pid, "check")                                 # the checker waits for the voices, then edits
            return
        secs = sections(p)
        todo = [s for s in secs if s["kind"] == "vo"] or secs     # anchor sections only when the story has no VO
        cut_off = [s for s in secs if any(k["state"] in ("queued", "searching") for k in (p["visuals"].get(s["id"]) or {}).get("keywords", []))]
        todo = [s for s in todo if not (p["visuals"].get(s["id"]) or {}).get("keywords")]
        for s in todo:
            part(pid, s["id"], "Waiting to search")
        pending = []
        for s in cut_off:                                           # an earlier search was interrupted: pick up what it started
            store.job(pid, "search", note="Picking up the footage search")
            part(pid, s["id"], "Picking up the search")
            pending.append(search_section(c, store.read(pid), s, resume=True, checks=checks))
        pool = None                                                 # the story's pictures, searched once
        for i, s in enumerate(todo):
            store.job(pid, "search", progress=i / len(todo), note=f"Searching footage for part {i + 1} of {len(todo)}")
            p = store.read(pid)
            if not find(p, s["id"]):
                part(pid, s["id"])
                continue
            part(pid, s["id"], "Searching YouTube")
            pending.append(search_section(c, p, s, checks=checks))
            try:
                if pool is None:
                    pool = []                                       # a failed search is not tried again for every part
                    pool = story_photos(pid, p)
                ph = photos_for(pid, s["id"], pool, story_names(p, s["text"]))
            except Exception as e:                                  # pictures are extra; footage is what matters
                log(f"pictures for {s['id']} failed: {e}")
                ph = []
            store.update(pid, lambda x: x["visuals"][s["id"]].update(photos=ph))
        store.job(pid, "search", progress=0.9, note="Checking the clips" if CHECKER else "Cutting the clips")
        for fu in pending:                                          # a failed check fails the search job, as before
            if fu is not None:
                fu.result()
    if p["format"] == "anchor_vo":
        start_job(pid, "check")                                     # the clip checker picks the VO parts' shots (after the voices)


def step_keyword(p, sid, kid):
    """One keyword the user added (or asked to search again) on one section."""
    pid = p["id"]
    with store._lock(store.DATA / "search.lock", shared=True):
        c = sv_client()
        p = store.read(pid)
        s = find(p, sid)
        kw = next((k for k in p["visuals"][sid]["keywords"] if k["id"] == kid), None)
        if not s or not kw:
            return
        sv = (p.get("_svp") or {}).get(sid)
        svk = (p.get("_svk") or {}).get(kid)
        if sv and svk:                                              # search again: re-run that keyword
            c.post(f"{SVB}/footage/projects/{sv}/batches", json={"keyword_ids": [svk]})
            old = lambda: store.read(pid)["visuals"].get(sid, {})
            svp = poll(c, sv, lambda x: all(k["status"] in ("done", "error") for k in keywords_of(x) if k["id"] == svk),
                       on=lambda x: save_visuals(pid, sid, *map_found(x, old())), every=15)
            kws, found = map_found(svp, old())
            save_visuals(pid, sid, kws, found)
            found = after_search(c, pid, sid, svp, found)
            save_visuals(pid, sid, kws, found)
        else:
            store.update(pid, lambda q: q["visuals"][sid].update(keywords=[k for k in q["visuals"][sid]["keywords"] if k["id"] != kid]))
            search_section(c, store.read(pid), s, extra=[kw["text"]])


def step_cut(p):
    """Moments the user placed that were never cut get cut now (the site says "the clip is cut when you use it").
    Anchor parts pick from other parts' footage, so a moment is cut in the part whose search found it."""
    pid = p["id"]
    with store._lock(store.DATA / "search.lock", shared=True):
        c = sv_client()
        for _ in range(3):                                          # moments placed while cutting are picked up next round
            p = store.read(pid)
            secs = [s["id"] for s in sections(p)]
            todo = {}
            for sid in secs:
                for x in p["visuals"].get(sid, {}).get("placed", []):
                    r = x["ref"]
                    if r["kind"] != "moment":
                        continue
                    own = next(((o, f) for o in [sid, *secs] for f in p["visuals"].get(o, {}).get("found", []) if f["id"] == r["videoId"]), None)
                    if own and r["moment"] < len(own[1]["moments"]):
                        m = own[1]["moments"][r["moment"]]
                        if not m.get("clip") and not m.get("cutFailed"):
                            todo.setdefault(own[0], {})[(own[1]["id"], r["moment"])] = (own[1], r["moment"])
            if not todo:
                return
            for sid, picked in todo.items():
                sv = (p.get("_svp") or {}).get(sid)
                if not sv:
                    continue
                cut(c, pid, sid, c.get(f"{SVB}/footage/projects/{sv}").json(), list(picked.values()))
                done = {k: (f["moments"][i], f["flags"]) for k, (f, i) in picked.items()}

                def put(q):
                    for f in q["visuals"][sid]["found"]:
                        for i, m in enumerate(f["moments"]):
                            if (f["id"], i) in done:
                                m.update(done[(f["id"], i)][0])
                                f["flags"] = done[(f["id"], i)][1]
                store.update(pid, put)
                p = store.read(pid)


# ------------------------------------------------------------------ VO only: a footage search per beat, then the clip checker
# The checker (vo_pick.py, RIG-NEWS-AI- docs/rig-video/vo-only/CHECKER_CRITERIA.md) runs here on t7: its vision model is
# vo-vision.service (:11620), its Python the converter's venv (torch, SigLIP-2, RapidOCR). It looks at every video the
# story's beats found (480p copies in VO_CACHE) and returns the edit: which shots play under each beat, in order, how long.

VO_PY = os.environ.get("VO_PY", str(STUDIO / "vertical" / ".venv" / "bin" / "python"))
VO_PICK = FOOT_TOOLS / "vo" / "vo_pick.py"
VO_CACHE = pathlib.Path(os.environ.get("VO_CACHE", HOME / "vo_check" / "cache"))
VO_GAP = 0.35        # seconds after each beat's voice before the next beat (a breath); part of the beat's picture time
CUT_KEYS = ("id", "shot", "at", "secs", "src", "kind", "fit", "shows", "sound", "poster", "clip", "fill", "swapped", "review", "repeat", "byUser")


def start_job(pid, job, *args):
    """A job started by another job (the API's spawn() for the site's own requests); skipped while one is running."""
    j = (store.read(pid).get("_jobs") or {}).get(job) or {}
    if j.get("state") == "running" and j.get("os_pid") and os.path.exists(f"/proc/{j['os_pid']}"):
        return
    store.job(pid, job, state="running", progress=0.0, note="Starting", error=None)
    logf = open(store.pdir(pid) / "log.txt", "a")
    logf.write(f"\n===== {store.stamp()} {job} {' '.join(args)}\n")
    logf.flush()
    pr = subprocess.Popen([TOOLS_PY, str(HERE / "worker.py"), job, pid, *args], stdout=logf, stderr=subprocess.STDOUT, cwd=HERE,
                          start_new_session=True)
    store.job(pid, job, os_pid=pr.pid)


def vo_date(p):
    """The day the beats' event footage is from: the writer's pictured date (a later count of an earlier event), else
    the story's day."""
    return dt.date.fromisoformat((p.get("_vo") or {}).get("picturedDate") or p["createdAt"][:10])


VO_LIMIT = 10      # videos per VO search line; the footage backend's default is 5, and a search costs the same quota either way


def respell(word, titles):
    """'Hmielek' -> 'Chmielek' when a found video title spells the name so: the article's own spelling can be wrong."""
    import difflib
    words = {w.lower(): w for t in titles for w in re.findall(r"[^\W\d_]{4,}", t)}
    m = difflib.get_close_matches(word.lower(), list(words), n=1, cutoff=0.8)
    return words[m[0]] if m and m[0] != word.lower() else None


def retry_lines(q, known, titles):
    """Lines to try when an event beat's search found (almost) nothing. Its names that the headline and event line don't
    carry (a village, maybe misspelled: "missile impact Hmielek Poland" found 0, 2026-11-22) are respelled the way a
    found title spells them; and the line without them."""
    rare = [w for w in q.split() if w[:1].isupper() and w.lower() not in known.lower()]
    fixed = " ".join(respell(w, titles) or w if w in rare else w for w in q.split())
    bare = " ".join(w for w in q.split() if w not in rare)
    return [x for x in dict.fromkeys([fixed, bare]) if rare and x != q and len(x.split()) >= 2]


def search_vo(c, p):
    """Each beat searches its own line (the writer's `search`), the first event beat also the whole event as news titles
    name it (the writer's event line); uploads from the event window on for event beats, any date for archive beats,
    VO_LIMIT videos a line; no suggested keywords (YouTube quota). Every video found is pooled for the checker. Beats
    that already found videos are kept."""
    pid = p["id"]
    when, place = vo_date(p), p.get("_place") or ""
    after = (when - dt.timedelta(days=3)).isoformat()
    ev = (p.get("_vo") or {}).get("eventSearch") or event_query(p["headline"])
    first = next((s["id"] for s in sections(p) if s.get("cls") != "archive"), None)
    todo = [s for s in sections(p) if not (p["visuals"].get(s["id"]) or {}).get("found")]   # not searched, or found nothing
    dated = lambda q, s: q + ("" if s.get("cls") == "archive" else f" after:{after}") + f" limit:{VO_LIMIT}"
    jobs = {}
    for s in todo:
        part(pid, s["id"], "Searching YouTube")
        want = s.get("picture") or "the subject of the line"
        body = (f"{place + ': ' if place else ''}{p['headline']}. Event of {when}. Wanted on screen: {want}, filmed at this event. "
                f"Not wanted: maps, graphics, a presenter in a studio, footage of other incidents." if s.get("cls") != "archive" else
                f"{place + ': ' if place else ''}{p['headline']}. Wanted on screen: {want}. Archive footage from any date is right "
                f"for this part. Not wanted: maps, graphics, a presenter in a studio.") + f"\n\nSEGMENT 1 — {s['text']}\n"
        sv = (p.get("_svp") or {}).get(s["id"])                     # a retried search resumes the beat's footage project
        if not sv:
            sv = c.post(f"{SVB}/footage/projects", json={"mode": "script", "title": f"{p['headline'][:60]} {s['id']}", "script": body}).json()["id"]
            store.update(pid, lambda q, sid=s["id"], sv=sv: q.setdefault("_svp", {}).update({sid: sv}))
        jobs[s["id"]] = sv

    def add(sv, lines):
        """Queue search lines on a beat's footage project; their keyword ids."""
        x = c.get(f"{SVB}/footage/projects/{sv}").json()
        had = {k["text"] for k in keywords_of(x)}                   # already queued (a resumed search): not again
        for kw in lines:
            if kw not in had:
                c.post(f"{SVB}/footage/projects/{sv}/segments/{x['segments'][0]['id']}/keywords", json={"text": kw})
        ks = [k for k in keywords_of(c.get(f"{SVB}/footage/projects/{sv}").json()) if k["text"] in lines]
        new = [k["id"] for k in ks if k["text"] not in had or k["status"] == "error"]   # and lines a restart interrupted
        if new:
            c.post(f"{SVB}/footage/projects/{sv}/batches", json={"keyword_ids": new})
        return [k["id"] for k in ks]

    def wait(s, sv, kids):
        old = lambda: store.read(pid)["visuals"].get(s["id"], {})
        svp = poll(c, sv, lambda x: all(k["status"] in ("done", "error") for k in keywords_of(x) if k["id"] in kids),
                   on=lambda x: save_visuals(pid, s["id"], *map_found(x, old())), every=15)
        save_visuals(pid, s["id"], *map_found(svp, old()))
        return map_found(svp, old())[1]

    for i, s in enumerate(todo):
        sv = jobs[s["id"]]
        store.job(pid, "search", progress=0.1 + 0.8 * i / len(todo), note=f"Searching footage for beat {i + 1} of {len(todo)}")
        svp = poll(c, sv, lambda x: x["status"] != "analyzing")
        if not svp["segments"]:
            log(f"footage search could not read beat {s['id']}")
            part(pid, s["id"])
            jobs[s["id"]] = None
            continue
        lines = list(dict.fromkeys([dated(s.get("search") or s["text"][:60], s)] + ([dated(ev, s)] if s["id"] == first else [])))
        jobs[s["id"]] = (sv, add(sv, lines))
    for s in todo:
        if not jobs[s["id"]]:
            continue
        sv, kids = jobs[s["id"]]
        found = wait(s, sv, kids)
        if len(found) < 2 and s.get("cls") != "archive":
            titles = [f["title"] for x in store.read(pid)["visuals"].values() for f in (x or {}).get("found", [])]
            more = [dated(q, s) for q in retry_lines(s.get("search") or "", f"{p['headline']} {ev} {place}", titles)]
            if more:
                part(pid, s["id"], "Searching again without the rare name")
                log(f"beat {s['id']}: {len(found)} videos, searching again: {more}")
                wait(s, sv, add(sv, more))
        part(pid, s["id"])


def beat_secs(p, s):
    """A beat's picture time: its picked voice take plus a breath; words / 2.6 before the voice exists."""
    v = s.get("voice") or {}
    t = next((t for t in v.get("takes") or [] if t["id"] == v.get("pick")), None)
    return round(t["seconds"] + VO_GAP, 2) if t and v.get("state") == "ready" else round(max(3.0, len(s["text"].split()) / writer.VO_WPS), 2)


def take_words(p, s):
    """The picked take's words with times ({w, start, end}), for cuts on the voice's phrase breaks; [] if none."""
    global _WHISPER
    v = s.get("voice") or {}
    t = (p.get("_takes") or {}).get(v.get("pick") or "")
    if not t or v.get("state") != "ready" or not os.path.exists(t["file"]):
        return []
    if _WHISPER is None:
        from faster_whisper import WhisperModel
        _WHISPER = WhisperModel("small.en", device="cpu", compute_type="int8")
    segs = _WHISPER.transcribe(t["file"], word_timestamps=True)[0]
    return [{"w": w.word.strip(), "start": round(w.start, 2), "end": round(w.end, 2)} for sg in segs for w in sg.words or []]


def check_input(p, secs=None):
    """vo_pick.py input: the story, its beats (picture time, voice words) and every video any beat found, pooled.
    `secs` (anchor + footage): only these parts are beats, and the pool is every search the story ever ran (its VO-only
    beats' too: the anchor format's own searches cover two parts and are thin)."""
    vids = {}
    for sid, v in ([(s["id"], p["visuals"].get(s["id"]) or {}) for s in sections(p)] if secs is None else list(p["visuals"].items())):
        for f in v.get("found", []):
            d = vids.setdefault(f["youtubeId"], {"id": f["youtubeId"], "title": f["title"], "channel": f.get("channel"), "dur": f.get("duration"),
                                                 "relevance": f.get("relevance"), "verdict": f.get("verdict") or "", "beats": [], "moments": []})
            d["beats"].append(sid)
            d["moments"] += [{"start": m["start"], "end": m["end"], "beat": sid} for m in f["moments"] if not m.get("custom")]
    beats = [{"id": s["id"], "text": s["text"], "picture": s.get("picture") or "", "cls": s.get("cls") or "event",
              "dated": (s.get("cls") or "event") == "event", "secs": beat_secs(p, s), "words": take_words(p, s)} for s in secs or sections(p)]
    return [{"sid": p["id"], "headline": p["headline"], "date": vo_date(p).isoformat(), "place": p.get("_place") or "",
             "beats": beats, "videos": list(vids.values())}]


def edit_media(pid, vid, start, secs, image=None):
    """(poster URL, clip URL or None) for a shot: a still and a short 360p clip from the checker's copy of the video;
    for one of our own pictures, the picture itself."""
    if image:
        f = media(pid, f"media/edit/own_{abs(hash(image)) % 10 ** 10}.jpg")
        if not f.exists():
            ff("-i", image, "-vf", "scale='min(1280,iw)':-2", "-q:v", 3, f)
        return url(pid, f), None
    src = VO_CACHE / f"{vid}.mp4"
    name = f"{vid}_{start:.2f}_{secs:.2f}"
    poster, clip = media(pid, f"media/edit/{name}.jpg"), media(pid, f"media/edit/{name}.mp4")
    if not clip.exists():
        ff("-ss", f"{start + secs / 2:.2f}", "-i", src, "-frames:v", 1, "-vf", "scale=-2:360", "-q:v", 4, poster)
        ff("-ss", f"{start:.2f}", "-t", f"{secs:.2f}", "-i", src, "-an", "-vf", "scale=-2:360,fps=25", "-c:v", "libx264", "-preset", "veryfast",
           "-crf", 28, "-movflags", "+faststart", clip)
    return url(pid, poster), url(pid, clip)


def src_of(x, titles):
    if x.get("image"):
        return {"kind": "picture", "url": x.get("url") or "", "page": x.get("page") or "", "title": (x.get("title") or "")[:120]}
    return {"kind": "video", "youtubeId": x["video"], "title": titles.get(x["video"]) or x.get("title") or "", "start": x["start"],
            "end": x["end"], "shotEnd": x.get("shot_end", x["end"]), **({"focus": x["focus"]} if x.get("focus") else {})}


def edit_from(p, res, only=()):
    """vo_pick.py's edit.json -> the site's StoryEdit (web/src/data/types.ts). With `only`, the other beats keep the
    edit they had (the person's changes too)."""
    pid = p["id"]
    old = {b["sectionId"]: b for b in (p.get("edit") or {}).get("beats", [])}
    titles = {f["youtubeId"]: f["title"] for v in p["visuals"].values() for f in v.get("found", [])}
    beats = []
    for e in res.get("beats") or []:
        sid = e["beat"]
        if only and sid not in only and sid in old:
            beats.append(old[sid])
            continue
        cuts = []
        for k, c in enumerate(e["cuts"]):
            poster, clip = edit_media(pid, c["video"], c["start"], c["secs"], c.get("image"))
            cuts.append({"id": f"{sid}-{c['shot']}-{k}", "shot": c["shot"], "at": c["at"], "secs": c["secs"], "src": src_of(c, titles),
                         "kind": c.get("kind") or "footage", "fit": c.get("fit") or "subject", "shows": c.get("shows") or "",
                         **({"sound": c["sound"] or ""} if "sound" in c else {}), "poster": poster, **({"clip": clip} if clip else {}),
                         **{k2: c[k2] for k2 in ("fill", "swapped", "review", "repeat") if c.get(k2)}})
        cands = []
        for x in e.get("candidates") or []:
            if x.get("fit") not in ("exact", "subject", "topic") or x.get("kind") in ("presenter", "studio", "promo", "text_card", "map", "chart"):
                continue
            poster, clip = edit_media(pid, x["video"], x["start"], min(4.0, x["end"] - x["start"]), x.get("image"))
            cands.append({"shot": x.get("shot", x["n"]), "src": src_of(x, titles), "kind": x.get("kind") or "footage", "fit": x["fit"],
                          "shows": x.get("shows") or "", **({"sound": x["sound"] or ""} if "sound" in x else {}),
                          "poster": poster, **({"clip": clip} if clip else {})})
        beats.append({"sectionId": sid, "secs": e["secs"], "cuts": cuts, "candidates": cands, "notes": e.get("fill") or [], "why": e.get("why") or ""})
    t = 0.0
    for b in beats:                                                 # story times again (kept beats may sit between new ones)
        k = t
        for c in b["cuts"]:
            c["at"] = round(k, 2); k += c["secs"]
        t += b["secs"]
    return {"state": "ready", "flow": res.get("flow") or "", "beats": beats}


def edit_state(pid, **kw):
    store.update(pid, lambda q: q.setdefault("edit", {"state": "waiting", "flow": "", "beats": []}).update(kw))


def step_check(p, only=()):
    """The clip checker for a VO-only story, after its voices (their lengths and words time the cuts). `only`: check just
    these beats again; the others keep their edit. Never with a render on the GPU (search.lock, as the footage search).
    Anchor + footage (user 2026-11-25): the same checker picks the shots of its VO parts -> p["anchorEdit"] (the VO-only
    edit stays as it was); the assembly plays them where an editor placed nothing, and the anchor walls follow from them."""
    pid = p["id"]
    anchor = p["format"] == "anchor_vo"
    edit_state = (lambda pid, **kw: None) if anchor else globals()["edit_state"]
    edit_state(pid, state="checking", progress=0.0, note="Waiting for the voices")
    store.job(pid, "check", progress=0.02, note="Waiting for the voices", **({"parts": {s: "Checking again" for s in only}} if only else {}))
    t0 = time.time()
    while time.time() - t0 < 1800:
        p = store.read(pid)
        if all((s.get("voice") or {}).get("state") == "ready" for s in sections(p)) or \
                ((p.get("_jobs") or {}).get("voice") or {}).get("state") == "failed":
            break
        time.sleep(10)
    store.job(pid, "check", note="Waiting its turn (a render or a footage search is using the machine)")
    edit_state(pid, note="Waiting its turn")
    with store._lock(store.DATA / "search.lock", shared=True):
        p = store.read(pid)
        out = store.pdir(pid) / ("check_anchor" if anchor else "check")
        out.mkdir(exist_ok=True)
        inp = check_input(p, [s for s in sections(p) if s["kind"] == "vo"] if anchor else None)
        if not inp[0]["videos"]:
            log("check: no footage found for any beat; the checker uses its own pictures")
        (out / "inputs.json").write_text(json.dumps(inp, indent=1, ensure_ascii=False))
        n = len(inp[0]["beats"])

        def progress(line):
            m = re.match(r"PROGRESS beat (\d+)/(\d+)", line)
            if m:
                f = 0.1 + 0.8 * (int(m[1]) - 1) / max(1, int(m[2]))
                store.job(pid, "check", progress=f, note=f"Choosing shots for beat {m[1]} of {m[2]}")
                edit_state(pid, progress=f, note=f"Beat {m[1]} of {m[2]}")
        store.job(pid, "check", progress=0.05, note=f"Looking at every shot the search found ({len(inp[0]['videos'])} videos)")
        (out / pid / "edit.json").unlink(missing_ok=True)         # a failed check must not reuse the last run's edit
        run([VO_PY, VO_PICK, out / "inputs.json", out], on_line=progress)
    if not (out / pid / "edit.json").exists():
        raise Say("The shot check could not finish (the vision model did not answer). Try the check again.")
    res = json.loads((out / pid / "edit.json").read_text())
    store.job(pid, "check", progress=0.95, note="Making the previews")
    if anchor:
        edit = edit_from({**store.read(pid), "edit": None}, res)
        store.update(pid, lambda q: q.update(anchorEdit=edit))
    else:
        edit = edit_from(store.read(pid), res, tuple(only))
        store.update(pid, lambda q: q.update(edit=edit))
        decide_type(store.read(pid))
    log(f"check: {sum(len(b['cuts']) for b in edit['beats'])} cuts over {n} beats; notes "
        f"{[(b['sectionId'], b['notes']) for b in edit['beats'] if b['notes']]}")


def recheck_changed(p):
    """VO only, after the voices: a beat whose new voice is more than half a second longer or shorter than its edit is
    checked again (its cuts no longer fit); otherwise the final video is made again if a picked voice changed."""
    e = p.get("edit") or {}
    if p["format"] != "vo_only" or e.get("state") != "ready":
        return
    by = {b["sectionId"]: b for b in e.get("beats") or []}
    changed = [s["id"] for s in sections(p) if s["id"] in by and abs(beat_secs(p, s) - by[s["id"]]["secs"]) > 0.5]
    if changed:
        log(f"voice length changed for {changed}: checking those beats again")
        start_job(p["id"], "check", *changed)


# ------------------------------------------------------------------ VO only: the final 9:16 video (the Review page's video)

ASSEMBLE = pathlib.Path(os.environ.get("VO_ASSEMBLE", STUDIO / "vertical" / "assemble916.py"))


def decide_type(p):
    """Daily run, once, after the first check: VO only stays when text shots are <= 35% of the cuts and no beat runs
    short; otherwise the story gets an anchor (anchor + footage), the reason recorded for the editors."""
    if not p.get("_daily") or (p.get("formatWhy") or {}).get("decided"):
        return
    share, short = store.text_share(p)
    keep = share <= 0.35 and not short
    why = (f"Daily run: {round(share * 100)}% of the shots are text" + (f", {len(short)} beat(s) short of pictures" if short else "")
           + (": no anchor." if keep else ": given an anchor."))
    if keep:
        store.update(p["id"], lambda q: q["formatWhy"].update(text=why, decided=True, at=store.stamp()))
        return
    out = {}
    store.update(p["id"], lambda q: out.update(job=store.switched(q, "anchor_vo", why, "auto")))
    store.update(p["id"], lambda q: q["formatWhy"].update(decided=True))
    log(f"daily: {why}")
    if out["job"] == "write":
        start_job(p["id"], "write")
    else:
        start_job(p["id"], "voice")
        start_job(p["id"], "search")


def final_state(pid, **kw):
    store.update(pid, lambda q: q.setdefault("final", {"state": "building"}).update(kw))


def step_final(p, again=False):
    """assemble916.py on a copy of the project as it is now: every cut framed 9:16 at source resolution, joined under the
    beat voices. An edit saved meanwhile makes it go round again with that edit. `again`: shots that came from the 480p
    copy are downloaded again (YouTube may let them through now)."""
    pid = p["id"]
    work = store.pdir(pid) / "final916"
    if again:
        final_state(pid, fp=None)
        for h in work.glob("v_*.how.json"):
            if not json.loads(h.read_text()).get("full", True):
                h.unlink()
    for _ in range(10):
        p = store.read(pid)
        fp = store.final_fp(p)
        if not fp or fp == (p.get("final") or {}).get("fp") and p["final"].get("state") == "ready":
            return
        final_state(pid, state="building", progress=0.02, note="Waiting its turn", error=None)
        store.job(pid, "final", progress=0.02, note="Waiting its turn")
        with store._lock(store.DATA / "search.lock", shared=True):  # never beside a render (as the checker)
            work.mkdir(exist_ok=True)
            (work / "project.json").write_text(json.dumps(p, ensure_ascii=False))

            at = {"f": 0.05}

            def progress(line):
                m = re.match(r"PROGRESS (\d+)/(\d+)", line)
                st = re.match(r"STAGE (.+)", line)
                if m:
                    at["f"] = round(0.05 + 0.85 * (int(m[1]) - 1) / max(1, int(m[2])), 3)
                    note = f"Framing shot {m[1]} of {int(m[2]) - 3}"
                elif st:
                    note = st[1]
                else:
                    return
                final_state(pid, progress=at["f"], note=note)
                if store.read(pid).get("render"):
                    render_state(pid, percent=round(at["f"] * 100))
                store.job(pid, "final", progress=at["f"], note=note)
            (work / "final_916.mp4").unlink(missing_ok=True)
            run([TOOLS_PY, ASSEMBLE, store.pdir(pid), work, work / "project.json"], on_line=progress)
        final_state(pid, progress=0.95, note="Finishing")
        video, poster = media(pid, "media/final_916.mp4"), media(pid, "media/final_916.jpg")
        shutil.copy2(work / "final_916.mp4", video)
        ff("-ss", 1, "-i", video, "-frames:v", 1, "-vf", "scale=540:-2", "-q:v", 3, poster)
        cuts = json.loads((work / "build.json").read_text())["cuts"]
        secs = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", video],
                                    capture_output=True, text=True).stdout or 0)
        final_state(pid, state="ready", fp=fp, progress=1, note=None, builtAt=store.stamp(), seconds=round(secs, 2),
                    video=f"{url(pid, video)}?v={fp}", poster=f"{url(pid, poster)}?v={fp}", cuts=len(cuts),
                    low=sum(not c.get("full", True) for c in cuts), whole=sum(c["how"].startswith("whole") for c in cuts))
        log(f"final: {len(cuts)} cuts, {secs:.1f} s, fp {fp}")


# ------------------------------------------------------------------ VO only: posting the final video

def step_post(p, platform, upload_only=False):
    """YouTube, the DNL channel. Upload (by itself when the render is done): unlisted, into "Awaiting approval" - the
    same queue the CMS shows. Post (the site's Post / Post all, or anchor-only by itself an hour after its render):
    the CMS's Approve from here - into "Video Bulletin", public, out of "Awaiting approval". The video id is saved right
    after the upload, so a retry never uploads it twice."""
    pid = p["id"]
    if platform != "youtube":
        raise Say("Only YouTube is connected so far.")
    f = store.public(p).get("final") or {}
    if f.get("state") != "ready" or f.get("stale"):
        raise Say("The final video changed. Wait until it is made again, then post.")
    video = store.pdir(pid) / "media" / ("final_916.mp4" if p["format"] == "vo_only" else "final.mp4")
    common.load_env()
    from orchestrator import publish
    missing = [k for k in publish.NEEDS + ("YT_BULLETIN_PLAYLIST_ID",) if not os.environ.get(k)]
    if missing:
        raise Say("YouTube is not connected on this machine yet. Tell the studio team.")
    yt = p["posts"]["youtube"]
    token = publish._token()
    if not yt.get("videoId"):
        store.job(pid, "post", progress=0.2, note="Uploading to YouTube")
        short = p["format"] == "vo_only"                            # 9:16 = a Short; anchor videos are 16:9
        v = publish.upload(video, yt["title"], yt["description"],
                           ["Democracy News Live", "news", "world news"] + (["Shorts"] if short else []), token, log=log)
        link = f"https://www.youtube.com/shorts/{v['id']}" if short else f"https://www.youtube.com/watch?v={v['id']}"
        store.update(pid, lambda q: q["posts"]["youtube"].update(videoId=v["id"], url=link, fp=f.get("fp") or f.get("builtAt"),
                                                                 sent=[yt["title"], yt["description"]]))
    yt = store.read(pid)["posts"]["youtube"]
    if not yt.get("queued"):
        store.job(pid, "post", progress=0.6, note="Adding it to Awaiting approval")
        publish.add_to_playlist(yt["videoId"], token)
        store.update(pid, lambda q: q["posts"]["youtube"].update(queued=True, uploadedAt=store.stamp()))
    if upload_only:
        store.update(pid, lambda q: q["posts"]["youtube"].update(state="awaiting", error=None))
        log(f"post: youtube {yt['videoId']} uploaded (unlisted, awaiting approval)")
        return
    if yt.get("sent") != [yt["title"], yt["description"]]:          # edited in the Post dialog after the upload
        publish.set_text(yt["videoId"], yt["title"], yt["description"], token)
        store.update(pid, lambda q: q["posts"]["youtube"].update(sent=[yt["title"], yt["description"]]))
    store.job(pid, "post", progress=0.8, note="Making it public")
    publish.approve(yt["videoId"], token, os.environ.get("RIGVIDEO_PUBLISH_PRIVACY", "public"))
    store.update(pid, lambda q: q["posts"]["youtube"].update(state="posted", postedAt=store.stamp(), error=None))
    log(f"post: youtube {yt['videoId']} published")


# ------------------------------------------------------------------ DNL selection (DNL workspace only)

def step_selection():
    from orchestrator import select_stories as ss
    out = store.DATA / "selection" / f"{store.now():%Y-%m-%d}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    with store.gpu("writer"):
        res = ss.select("db", log=log)
    out.write_text(json.dumps(res, indent=1, ensure_ascii=False, default=str))


# ------------------------------------------------------------------ render: appearances -> source_track -> GPU -> assembly

def render_dir(p):
    return store.pdir(p["id"]) / "render"


def take_of(p, s):
    return p["_takes"][s["voice"]["pick"]]


def prepare_render(p):
    """Appearance masters (make_appearances on the voice box: its ffmpeg has Rubber Band) + a source_track job each."""
    anchors = [s for s in sections(p) if s["kind"] == "anchor"]
    rd = render_dir(p)
    remote = f"{VROOT}/studio/{p['id']}/render"
    sj = media(p["id"], "render-in/script.json")
    sj.write_text(json.dumps({"scripts": {s["id"]: spoken(take_of(p, s)["text"]) for s in anchors}}, indent=1, ensure_ascii=False))
    run(VSSH + [f"mkdir -p {remote} {VROOT}/studio/bin"])
    vcp(sj, f"{VHOST}:{remote}/../script.json")
    vcp(ST_TOOLS / "make_appearances.py", ST_TOOLS / "make_master.py", f"{VHOST}:{VROOT}/studio/bin/")
    args = " ".join(f"{s['id']}={take_of(p, s)['remote']}" for s in anchors)
    run(VSSH + [f"rm -rf {remote} && cd {VROOT}/voice_lab && PATH=$HOME/.local/bin:$PATH {VPY} {VROOT}/studio/bin/make_appearances.py "
                f"{remote} {p['anchorId']} {VROOT}/studio/{p['id']}/script.json {args}"])
    if rd.exists():
        shutil.rmtree(rd)
    vcp(f"{VHOST}:{remote}", rd)
    for s in anchors:
        d = rd / s["id"]
        story = json.load(open(d / "story.json"))
        run([TOOLS_PY, ST_TOOLS / "build_st.py", d / "story.json", d, d, "--turbo-seed"])
        (d / "run.txt").write_text(story["run"] + "_st")
    return rd


def render_state(pid, **kw):
    def f(q):
        q["render"].update(kw)
        if kw.get("state") in ("failed", "held"):
            q["stage"] = "review"                  # unlocked, so it can be checked and sent again
    store.update(pid, f)


def gpu_run(p, rd, todo):
    """run_multi.py: one ComfyUI session for every appearance (it pauses the GPU tenants and restores them)."""
    comfy_in = STUDIO / "repos" / "ComfyUI-v038" / "input"          # fixed pictures the workflows load (per-run files are copied later)
    need = {v for a in todo for f in (rd / a).glob("*.json") for n in (lambda g: g.get("prompt", g) if isinstance(g, dict) else {})(json.load(open(f))).values()
            if isinstance(n, dict) for v in (n.get("inputs") or {}).values()
            if isinstance(v, str) and not v.startswith("render_") and v.lower().endswith((".png", ".jpg", ".wav", ".mp4"))}
    if gone := sorted(x for x in need if not (comfy_in / x).exists()):
        log(f"missing from ComfyUI input/: {gone}")
        raise Say("This anchor's pictures are missing on the render machine. Tell the studio team.")
    render_state(p["id"], note="Waiting for a footage search to finish")
    with store._lock(store.DATA / "search.lock"):                  # the GPU hold stops the footage backend: never both at once
        render_state(p["id"], note=None)
        _gpu_run(p, rd, todo)


def _gpu_run(p, rd, todo):
    est = sum(9.8 + 8.0 * (len(json.load(open(rd / a / "shots.json"))["shots"]) - 1) for a in todo)
    t0 = time.time()
    proc = subprocess.Popen([TOOLS_PY, ST_TOOLS / "run_multi.py", rd] + todo, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    tail = []
    for line in proc.stdout:
        print(line, end="", flush=True)
        tail = (tail + [line.rstrip()])[-12:]
        mins = (time.time() - t0) / 60
        render_state(p["id"], percent=round(min(90, 90 * mins / est)),
                     etaIso=(store.now() + __import__("datetime").timedelta(minutes=max(1, est - mins) + 3)).isoformat(timespec="seconds"))
    if proc.wait() != 0:
        raise RuntimeError("Render failed: " + " | ".join(tail[-3:]))
    for a in todo:
        d = rd / a
        name = (d / "run.txt").read_text().strip()
        vid = d / f"{name}.mp4" if (d / f"{name}.mp4").exists() else d / f"{name}_seed.mp4"
        shutil.copy2(vid, rd / f"{a}.mp4")


def lipsync(rd, a):
    try:
        out = subprocess.run([TOOLS_PY, ST_TOOLS / "lipsync_check.py", rd / f"{a}.mp4", rd / a / "master_seed.wav"],
                             capture_output=True, text=True, timeout=600).stdout
    except subprocess.TimeoutExpired:
        return True, "not measured"
    lag = re.search(r"best lag\s+([+-]?\d+) frames", out)
    return lag is None or abs(int(lag.group(1))) <= 2, (out.strip().splitlines() or [""])[-1][:160]


CONF = "crop=iw*0.9:ih*0.9,scale=1280:736:force_original_aspect_ratio=increase,crop=1280:736,setsar=1,fps=24,format=yuv420p"
BLUR = ("split[a][b];[a]scale=1280:736:force_original_aspect_ratio=increase,crop=1280:736,boxblur=20:2,eq=brightness=-0.12[bg];"
        "[b]crop=ih*9/16:ih,scale=-2:736[fg];[bg][fg]overlay=(W-w)/2:0,setsar=1,fps=24,format=yuv420p")


def montage(items, seconds, out):
    """[(path, in, out, vf)] back to back (looped if short) -> exactly `seconds` of conformed video, no sound."""
    items = [x for x in items if x[2] - x[1] > 0.05]                 # an empty item would loop forever
    ins, fc, t, k = [], [], 0.0, 0
    while t < seconds and items:
        path, s, e, vf = items[k % len(items)]
        d = min(e - s, seconds - t + 0.05)
        ins += ["-ss", f"{s:.3f}", "-t", f"{d:.3f}", "-i", path]
        fc.append(f"[{k}:v]{vf},setpts=PTS-STARTPTS[v{k}]")
        t, k = t + d, k + 1
    fc.append("".join(f"[v{i}]" for i in range(k)) + f"concat=n={k}:v=1:a=0[vc];[vc]setpts=N/(24*TB)[v]")
    ff(*ins, "-filter_complex", ";".join(fc), "-map", "[v]", "-t", f"{seconds:.3f}", "-r", 24, "-c:v", "libx264", "-crf", 16, "-pix_fmt", "yuv420p", out)
    return str(out)


def placed_items(p, sid, work):
    """A section's placed visuals in play order -> montage items (stills become slow push-ins of their seconds)."""
    from orchestrator import assets
    v = p["visuals"].get(sid) or {}
    every = [v] + list(p["visuals"].values())                       # own part first; anchor parts pick from the whole story
    pool = {k: {x["id"]: x for w in reversed(every) for x in w.get(k, [])} for k in ("photos", "uploads", "maps")}
    files = lambda src: store.pdir(p["id"]) / src.split(f"/files/{p['id']}/", 1)[1]
    out = []
    for x in v.get("placed", []):
        r, d = x["ref"], max(0.5, x["out"] - x["in"])
        if r["kind"] == "moment":
            f = next((y for w in every for y in w.get("found", []) if y["id"] == r["videoId"]), None)
            m = f and f["moments"][r["moment"]]
            if not m or not m.get("clip"):
                continue
            treat = (m.get("treat") or {}).get("kind") if x.get("useTreated") else None
            out.append((p["_clipfiles"][m["clip"]], x["in"], x["out"], BLUR if treat == "blur_fill" else CONF))
            continue
        it = pool[{"photo": "photos", "upload": "uploads", "map": "maps"}[r["kind"]]].get(r["id"])
        if not it:
            continue
        if r["kind"] == "upload" and it["kind"] == "video":
            out.append((str(files(it["src"])), x["in"], x["out"], CONF))
        else:
            kb = work / f"{sid}_{x['id']}_kb.mp4"
            assets.ken_burns([{"path": str(files(it["src"]))}], d, str(kb), log=log)
            out.append((str(kb), 0.0, d, "scale=1280:736,setsar=1,fps=24,format=yuv420p"))
    return out


def auto_items(p, beat, work):
    """Anchor + footage: the clip checker's cuts of one VO part (anchorEdit) -> [(montage item, cut)]. Video cuts are
    downloaded at source resolution (assemble916.download: up to 1080p, the checker's 480p copy if YouTube refuses);
    our own pictures become slow push-ins."""
    from orchestrator import assets
    a9 = _a9()
    out = []
    for c in (beat or {}).get("cuts", []):
        if c["src"]["kind"] != "video":
            img = store.pdir(p["id"]) / c["poster"].split(f"/files/{p['id']}/", 1)[1].split("?")[0]
            kb = work / f"auto_{img.stem}_{c['secs']:.2f}_kb.mp4"
            if not kb.exists():
                assets.ken_burns([{"path": str(img)}], c["secs"], str(kb), log=log)
            out.append(((str(kb), 0.0, c["secs"], "scale=1280:736,setsar=1,fps=24,format=yuv420p"), c))
            continue
        y, st = c["src"]["youtubeId"], c["src"]["start"]
        f, a, _ = a9.download(c, work / f"raw_{y}_{st:.2f}_{c['secs']:.2f}.mp4")
        out.append(((str(f), st - a, st - a + c["secs"], CONF), c))
    return out


def wall_item(entry, need, work):
    """A shot (montage item, its checker cut or None) -> that shot playing on for `need` s, for an anchor's wall: a
    checker cut is downloaded again from its start for the wall's length; a placed clip plays on to its file's end."""
    (path, s, e, vf), c = entry
    a9 = _a9()
    if c and c["src"]["kind"] == "video":
        y, st = c["src"]["youtubeId"], c["src"]["start"]
        f, a, _ = a9.download({**c, "secs": need}, work / f"raw_{y}_{st:.2f}_{need:.2f}.mp4")
        return (str(f), st - a, min(a9.secs_of(f), st - a + need), CONF)
    return (path, s, max(e, min(a9.secs_of(path), s + need)) if not path.endswith("_kb.mp4") else e, vf)


def wall_shot(secs, i, shown):
    """The shot an anchor part's wall plays (user 2026-11-25): the last one shown in the footage before it, else (the
    opening anchor) the first one of the footage after it; None when the story has no footage. shown: {VO part: [shots]}."""
    before = [x for x in secs[:i] if x["kind"] == "vo" and shown.get(x["id"])]
    after = [x for x in secs[i + 1:] if x["kind"] == "vo" and shown.get(x["id"])]
    return shown[before[-1]["id"]][-1] if before else shown[after[0]["id"]][0] if after else None


def _a9():
    sys.path.insert(0, str(ASSEMBLE.parent))
    import assemble916
    return assemble916


def step_assemble(p):
    rd = render_dir(p)
    work = rd / "assembly"
    work.mkdir(exist_ok=True)
    apps = {a["id"]: a for a in json.load(open(rd / "appearances.json"))}
    secs = sections(p)
    every = [it for s in secs for it in placed_items(p, s["id"], work)]
    auto = {b["sectionId"]: b for b in (p.get("anchorEdit") or {}).get("beats", [])}
    # what each VO part plays: the editor's placed pictures, else the clip checker's picks, else anything placed in the story
    shown = {s["id"]: ([(it, None) for it in placed_items(p, s["id"], work)] or auto_items(p, auto.get(s["id"]), work)
                       or [(it, None) for it in every]) for s in secs if s["kind"] == "vo"}
    beats, order = {}, []
    for i, s in enumerate(secs):
        order.append(s["id"])
        own = placed_items(p, s["id"], work)
        if s["kind"] == "vo":
            t = take_of(p, s)
            d = speech_seconds(t["file"])
            n = LEAD + d + KEEP_TAIL
            wav = work / f"{s['id']}_voice.wav"
            ff("-i", t["file"], "-af", f"silenceremove=start_periods=1:start_threshold=-45dB,adelay={int(LEAD * 1000)},apad,atrim=end={n:.3f},"
               "highpass=f=70,loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000", "-ac", 1, wav)
            if not shown[s["id"]]:
                raise Say(f"Part {s['id']} has no pictures. Place footage or pictures for it first.")
            beats[s["id"]] = {"pictures": montage([it for it, _ in shown[s["id"]]], n, work / f"{s['id']}_pics.mp4"), "voice": str(wav)}
        else:
            need = apps[s["id"]]["keep_frames"] / FPS + 0.5
            # the wall (user 2026-11-25): the last shot the viewer saw in the footage before this anchor, playing on; the
            # opening anchor (no footage before it) shows the first shot of the footage after it. The editor's own wins.
            last = wall_shot(secs, i, shown)
            src = own or ([wall_item(last, need, work)] if last else every)
            if src:
                wall = work / f"{s['id']}_wall.mp4"
                montage(src, need, wall)
                beats[s["id"]] = {"wall": [str(wall), 0]}
            else:
                beats[s["id"]] = {}
    reg = registry()
    edl = {"meta": {"anchor_name": reg[p["anchorId"]]["name"], "lt_headline": p["lt"]["headline"], "location": p["lt"]["kicker"],
                    "kicker": "WORLD NEWS", "subline": p["lt"]["subline"],
                    "outro": (p.get("extras") or {}).get("outro", True)}, "ticker": p["ticker"], "beats": beats}
    for a in apps:
        shutil.copy2(rd / f"{a}.mp4", work / f"{a}.mp4")
        if not (work / a).exists():
            shutil.copytree(rd / a, work / a)
    shutil.copy2(rd / "appearances.json", work / "appearances.json")
    (work / "edl.json").write_text(json.dumps(edl, indent=1, ensure_ascii=False))
    run([TOOLS_PY, ST_TOOLS / "assemble_story.py", work, " ".join(order)])
    final = media(p["id"], "media/final.mp4")
    shutil.copy2(work / "final.mp4", final)
    poster = media(p["id"], "media/poster.jpg")
    ff("-ss", 3, "-i", final, "-frames:v", 1, "-vf", "scale=960:-2", "-q:v", 3, poster)
    secs_total = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", final],
                                      capture_output=True, text=True).stdout or 0)
    item = {"id": f"lib-{p['id']}", "projectId": p["id"], "headline": p["headline"], "anchorId": p["anchorId"], "madeAt": store.stamp(),
            "seconds": round(secs_total), "video": url(p["id"], final), "poster": url(p["id"], poster), "origin": "studio"}

    def done(q):
        q["stage"], q["videoId"], q["_library"] = "done", item["id"], item
        q["final"] = {"state": "ready", "video": item["video"], "poster": item["poster"], "seconds": item["seconds"], "builtAt": store.stamp()}
        q["render"].update(state="done", percent=100, etaIso=None, queuePosition=0, heldReason=None)
    store.update(p["id"], done)


def render_vo(p):
    """VO only: the night render makes the final 9:16 video (step_final), then the story is done (final page, library)."""
    pid = p["id"]
    render_state(pid, state="rendering", percent=1, heldReason=None)
    step_final(p)
    q = store.read(pid)
    f = q.get("final") or {}
    if f.get("state") != "ready":
        raise Say(f.get("note") or "The final video could not be made.")
    item = {"id": f"lib-{pid}", "projectId": pid, "headline": q["headline"], "anchorId": q["anchorId"], "madeAt": store.stamp(),
            "seconds": round(f.get("seconds") or 0), "video": f["video"], "poster": f["poster"], "origin": "studio"}

    def done(x):
        x["stage"], x["videoId"], x["_library"] = "done", item["id"], item
        x["render"].update(state="done", percent=100, etaIso=None, queuePosition=0, heldReason=None)
    store.update(pid, done)


def step_render(p):
    pid = p["id"]
    if p["format"] == "vo_only":
        return render_vo(p)
    render_state(pid, state="rendering", percent=1, heldReason=None)
    rd = prepare_render(p)
    apps = [s["id"] for s in sections(p) if s["kind"] == "anchor"]
    gpu_run(p, rd, apps)
    bad = [(a, why) for a in apps for ok, why in [lipsync(rd, a)] if not ok]
    if bad:
        render_state(pid, state="held", heldReason=f"Lips out of step in appearance {bad[0][0]} ({bad[0][1]}). Check it, then render again.")
        return
    render_state(pid, state="assembling", percent=92)
    step_assemble(store.read(pid))


# ------------------------------------------------------------------ main

def main():
    global PID
    step = sys.argv[1]
    if step == "selection":
        return step_selection()
    PID = sys.argv[2]
    if step == "cut":                                               # quiet helper job: the clips show up when cut
        return step_cut(store.read(PID))
    kind = "search" if step == "keyword" else step
    try:
        p = store.read(PID)
        if step == "keyword":
            step_keyword(p, sys.argv[3], sys.argv[4])
        elif step == "check":
            step_check(p, sys.argv[3:])
        elif step == "final":
            step_final(p, again=sys.argv[3:4] == ["again"])
        elif step == "post":
            step_post(p, sys.argv[3], sys.argv[4:5] == ["upload"])
        else:
            {"write": step_write, "voice": step_voice, "search": step_search, "render": step_render}[step](p)
        store.job(PID, kind, state=None)
    except Exception as e:                                          # the site shows the reason
        traceback.print_exc()
        msg = str(e) if isinstance(e, (Say, writer.Busy)) else ("The script writer is busy right now. Try again in a few minutes."
                                                 if isinstance(e, llm.LLMUnavailable) else PLAIN.get(kind, "Something went wrong. Try again."))
        store.job(PID, kind, state="failed", error=msg[:400], note=msg[:400])
        if step == "render":
            render_state(PID, state="failed", heldReason=msg[:300])
        if step == "check" and store.read(PID)["format"] == "vo_only":
            edit_state(PID, state="failed", note=msg[:300])
        if step == "final":
            final_state(PID, state="failed", note=msg[:300])
        if step == "post":
            store.update(PID, lambda q: q.setdefault("posts", {}).setdefault(sys.argv[3], {}).update(state="failed", error=msg[:300]))
        if kind == "search":                                        # keywords it was running stop spinning; "Search again" works on them
            store.update(PID, lambda q: [k.update(state="error") for v in q["visuals"].values() for k in v["keywords"] if k["state"] in ("queued", "searching")])
        sys.exit(1)


if __name__ == "__main__" and sys.argv[1:2] == ["selftest"]:                  # python3 worker.py selftest
    nm = story_names({"lt": {"kicker": "EUROPE"}}, "The European Union has approved aid for Ukraine. High Representative "
                     "Kaja Kallas said Russia's attacks continue. This package follows a NATO meeting on Monday.")
    assert {"European", "Ukraine", "Kaja", "Kallas", "Russia", "NATO", "Europe"} <= set(nm) and not {"High", "This", "Monday", "The"} & set(nm), nm
    ss = [{"id": k, "kind": "anchor" if k[0] == "a" else "vo"} for k in ("a1", "v1", "a2", "v2", "a3")]
    sh = {"v1": ["v1s1", "v1s2"], "v2": ["v2s1"]}
    assert [wall_shot(ss, i, sh) for i in (0, 2, 4)] == ["v1s1", "v1s2", "v2s1"]     # opening: first after; then last before
    assert wall_shot(ss, 4, {"v1": ["x"], "v2": []}) == "x" and wall_shot(ss, 0, {}) is None
    assert asked("Slower", 0.7, 0.4, "x") == (0.7, 0.4, "x", 0.9)
    assert asked("Less flat. Faster", 0.7, 0.4, "x") == (0.9, 0.35, "x", 1.1)
    assert asked("Fix a name. Lipetsk is LEE-petsk", 0.7, 0.4, "Drones hit Lipetsk today.")[2] == "Drones hit LEE-petsk today."
    assert asked("Pause before the last line", 0.7, 0.4, "One. Two. Three.")[2] == "One. Two. ... Three."
    t = ["WATCH: An explosion is heard in Chmielek as Russian missiles land in Poland"]
    assert retry_lines("missile impact Hmielek Poland", "Russian missile lands in Poland", t) == \
        ["missile impact Chmielek Poland", "missile impact Poland"]
    assert retry_lines("missile impact Hmielek Poland", "Russian missile lands in Poland", []) == ["missile impact Poland"]
    assert retry_lines("Russian missile Poland", "Russian missile lands in Poland", t) == []
    print("ok")
elif __name__ == "__main__":
    main()
