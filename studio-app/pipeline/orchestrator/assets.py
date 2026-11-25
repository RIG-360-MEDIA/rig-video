"""ASSETS: ONE photo that shows this story for the studio wall -> a slow Ken-Burns video.

Layer 0 (free, no keys; user decision 2026-10-11, research in baseline/WALL_PHOTO_RESEARCH.md): photos WITH captions from the
story's own coverage (our DB's member articles + local-language Bing News RSS), names linked to Wikidata, caption gates, the
text LLM picks like a picture editor, then size / collage / burned-in text filters. Fallback: the subject's Commons image,
then the DNL logo card. Downloaded at SCRIPT time (a dead link never blocks POST). Caption/credit/page -> meta.json.
"""
import html
import io
import json
import os
import pathlib
import re
import subprocess
import urllib.parse
import urllib.request

from PIL import Image, ImageStat

from . import llm
from .common import APP

LOGO = APP / "lt_remotion" / "assets" / "logo.png"
W, H, FPS, XF = 1920, 1080, 24, 0.8
TITLE_S = 4.0             # story title card on the wall before the photo (user 2026-10-23)
FONTS = ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
         "/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/Library/Fonts/Arial Bold.ttf")


def _dhash(im):
    g = im.convert("L").resize((9, 8))
    px = list(g.getdata())
    return sum(1 << i for i in range(64) if px[(i // 8) * 9 + i % 8] > px[(i // 8) * 9 + i % 8 + 1])


BROADCASTERS = ("bbc", "cnn", "news", "ndtv", "aajtak", "abp", "zee", "wion", "ians", "ani", "republic", "timesnow", "etnow", "et",
                "indiatoday", "sky", "fox", "msnbc", "cbs", "nbc", "abc", "aljazeera", "trt", "dw", "france24", "euronews", "cgtn",
                "tass", "ria", "live", "breaking", "exclusive",
                "post", "times", "herald", "tribune", "journal", "gazette", "express", "telegraph", "guardian", "mail", "daily",
                "scmp", "reuters", "afp")      # newspapers' corner logos too ("South China Morning Post"); <=4 letters = whole word
RUN_TOGETHER = {"bbc", "cnn", "news", "ndtv", "abp", "zee"}   # OCR reads "BBC NEWS" as "BBCNEWS"; not "post" (POSTER)
_OCR = []


def _ocr(path):
    """RapidOCR boxes [(box, text, conf)] or None when no OCR engine is installed (the engine is loaded once)."""
    try:
        if not _OCR:
            from rapidocr_onnxruntime import RapidOCR
            _OCR.append(RapidOCR())
    except ImportError:
        return None
    return _OCR[0](str(path))[0] or []


def _text_area(path, boxes=None):
    """Fraction of the image covered by detected text; None when no OCR engine is installed."""
    boxes = _ocr(path) if boxes is None else boxes
    if boxes is None:
        return None
    im = Image.open(path)
    area = 0.0
    for box, txt, conf in boxes:
        if conf > 0.6 and len(txt.strip()) >= 3:
            xs, ys = [p[0] for p in box], [p[1] for p in box]
            area += (max(xs) - min(xs)) * (max(ys) - min(ys))
    return area / (im.width * im.height)


def _corner_logo(path, boxes):
    """A broadcaster's logo/bug in a corner ("BBC NEWS", "ET NOW"). Photo credits ("Name/REUTERS") and signs in the scene
    are left alone: only broadcaster words count (measured 2026-10-12 on 50 picks)."""
    im = Image.open(path)
    for box, txt, conf in boxes or []:
        cx, cy = sum(p[0] for p in box) / 4 / im.width, sum(p[1] for p in box) / 4 / im.height
        words = re.findall(r"[a-z0-9]+", _fold(txt))
        joined = "".join(words)
        if conf > 0.6 and (cx < 0.3 or cx > 0.7) and (cy < 0.22 or cy > 0.78) and "/" not in txt \
                and any((b in words or (b in RUN_TOGETHER and (joined.startswith(b) or joined.endswith(b)))) if len(b) <= 4
                        else b in joined for b in BROADCASTERS):
            return txt.strip()
    return None


_SIG = []
SIG_LABELS = {"photo": "a news photograph of a real scene", "collage": "a collage of two different photos side by side",
              "vertical": "a vertical phone video with blurred bars on the left and right",
              "plainbars": "a portrait photo with empty dark bars on both sides", "map": "a map", "chart": "an infographic or a chart",
              "graphic": "a screenshot of a website or a TV news graphic with text", "logo": "a logo"}


def _siglip(im):
    """SigLIP-2 (open weights, Apache-2.0, cached on trijya) label shares for one image; None if the model is not available.
    It judges what the picture LOOKS like (photo vs collage/map/graphic/padded portrait) - never who or which event."""
    try:
        import torch
        if not _SIG:
            from transformers import AutoModel, AutoProcessor
            m = "google/siglip2-so400m-patch14-384"
            model, proc = AutoModel.from_pretrained(m, local_files_only=True).eval(), AutoProcessor.from_pretrained(m, local_files_only=True)
            with torch.no_grad():
                tf = model.get_text_features(**proc(text=[f"This is {v}." for v in SIG_LABELS.values()], padding="max_length",
                                                    max_length=64, return_tensors="pt"))
                tf = getattr(tf, "pooler_output", tf)
            _SIG.append((model, proc, tf / tf.norm(dim=-1, keepdim=True)))
        model, proc, tf = _SIG[0]
        with torch.no_grad():
            f = model.get_image_features(**proc(images=im, return_tensors="pt"))
            f = getattr(f, "pooler_output", f)
            p = torch.softmax((f / f.norm(dim=-1, keepdim=True)) @ tf.T * model.logit_scale.exp() + model.logit_bias, dim=-1)[0]
        return dict(zip(SIG_LABELS, p.tolist()))
    except Exception:  # noqa: BLE001 - no transformers / model not downloaded: the other filters still run
        return None


def _scene(path, sentence):
    """How much the photo LOOKS like the story's ideal-photo sentence (SigLIP-2 cosine; None without the model). Used only to
    rank photos the captions already qualified - it cannot tell which event or which person."""
    if not sentence or _siglip(Image.new("RGB", (64, 64))) is None:     # loads the model once
        return None
    import torch
    model, proc, _ = _SIG[0]
    with torch.no_grad():
        t = model.get_text_features(**proc(text=[f"This is {sentence}."], padding="max_length", max_length=64, return_tensors="pt"))
        t = getattr(t, "pooler_output", t)
        f = model.get_image_features(**proc(images=Image.open(path).convert("RGB"), return_tensors="pt"))
        f = getattr(f, "pooler_output", f)
    return float((f / f.norm(dim=-1, keepdim=True) @ (t / t.norm(dim=-1, keepdim=True)).T)[0, 0])


def _side_detail(im):
    """Detail in the outer 15% columns vs the centre: padded/blurred side bars score near 0 (measured 0.02-0.16), real photos
    and portraits 0.3+."""
    import numpy as np
    g = np.asarray(im.convert("L").resize((640, 360)), dtype=np.float32)
    d = np.abs(np.diff(g, axis=0))[:, :-1] + np.abs(np.diff(g, axis=1))[:-1, :]
    col = d.mean(axis=0)
    return float(max(col[:96].mean(), col[-96:].mean()) / (col[224:416].mean() + 1e-6))


def _looks_wrong(im):
    """Why this is not a single clean news photo (collage, map, graphic, logo card, padded vertical/portrait), or None.
    Calibrated 2026-10-12: a non-photo label beating 'photo' caught the 2-up collage (0.46 vs 0.33) and the TASS card; 'bars'
    > 0.5 alone also fires on real portraits (0.67-1.0), so it needs empty sides too (<0.2; padded 0.02-0.16, portraits 0.3+)."""
    s = _siglip(im)
    if s is None:
        return None
    worst = max(("collage", "map", "chart", "graphic", "logo"), key=s.get)
    if s[worst] > s["photo"]:
        return f"{worst} {s[worst]:.2f}"
    if max(s["vertical"], s["plainbars"]) > 0.5 and _side_detail(im) < 0.2:
        return f"padded vertical/portrait {max(s['vertical'], s['plainbars']):.2f}"
    return None


def _split_screen(im):
    """News thumbnails are often two photos side by side; a sharp vertical seam in the middle 40% gives them away.
    Measured 2026-10-11: collages 0.49-1.0, single photos 0.12-0.37; plus duplicated halves (one photo shown twice)."""
    import numpy as np
    g = np.asarray(im.convert("L").resize((640, 360)), dtype=np.int16)
    frac = (np.abs(np.diff(g, axis=1)) > 30).mean(axis=0)       # per column: share of rows with a sharp jump
    if float(frac[192:448].max()) >= 0.45:         # ponytail: 2-up seams only; a 3-up grid at 1/3 needs a wider band
        return True
    w, h = im.size                                 # the same photo twice side by side has no sharp seam: halves match
    for c in range(int(w * 0.45), int(w * 0.55) + 1, max(1, w // 100)):   # (dup 10 vs single photos >= 17)
        k = min(c, w - c)
        if bin(_dhash(im.crop((c - k, 0, c, h))) ^ _dhash(im.crop((c, 0, c + k, h)))).count("1") <= 12:
            return True
    return False


def fetch(urls, out_dir, log=print, keep=5, max_text=0.04, min_ar=0.9):
    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    kept, hashes, small, warned = [], [], [], False
    for u in urls:
        try:
            req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0 (anchor-studio wall fetch)"})
            data = urllib.request.urlopen(req, timeout=20).read()
            im = Image.open(io.BytesIO(data)).convert("RGB")
        except Exception as e:  # noqa: BLE001 — publisher 403s / dead links are expected
            log(f"photo skipped ({type(e).__name__}): {u[:90]}")
            continue
        ar = im.width / im.height
        if not min_ar <= ar <= 2.4 or sum(ImageStat.Stat(im).stddev) / 3 < 25:   # banners, logos, flat graphics
            continue
        if _split_screen(im):
            log(f"photo dropped (split-screen collage): {u[:90]}")
            continue
        h = _dhash(im)
        if any(bin(h ^ x).count("1") <= 10 for x in hashes):
            continue
        p = out_dir / f"photo_{h:016x}.jpg"                          # unique per image across repeated calls
        im.save(p, quality=92)
        boxes = _ocr(p)
        ta = _text_area(p, boxes)
        if ta is None and not warned:
            log("WARNING: no OCR engine (rapidocr) installed - text-heavy photos cannot be filtered")
            warned = True
        if ta is not None and ta > max_text:      # scene text (a plane's lettering) 0.03; banners, maps, text cards 0.05+
            log(f"photo dropped (text covers {ta:.0%}): {u[:90]}")
            continue
        logo = _corner_logo(p, boxes)
        if logo:
            log(f"photo dropped (broadcaster logo '{logo}'): {u[:90]}")
            continue
        wrong = _looks_wrong(im)
        if wrong:
            log(f"photo dropped ({wrong}): {u[:90]}")
            continue
        hashes.append(h)
        (kept if im.width >= 800 else small).append({"path": str(p), "url": u, "w": im.width, "h": im.height})
        if len(kept) >= keep:
            break
    if len(kept) < 2:                                              # accept smaller photos rather than none
        kept += small[:keep - len(kept)]
    return kept


# Stock-photo libraries: a smiling model captioned with the story would put a stranger's face on a named person's story.
STOCK = ("pexels.com", "unsplash.com", "pixabay.com", "shutterstock.", "istockphoto.", "freepik.", "stock.adobe.", "dreamstime.",
         "alamy.", "123rf.", "depositphotos.")
_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"}


# ---------------------------------------------------------------- wall photo, layer 0 (free, no keys; user decision 2026-10-11)
# Research: baseline/WALL_PHOTO_RESEARCH.md. Pixels cannot tell "this quake's rubble" from "a quake's rubble" - only the photo's
# CAPTION, date and place can. So: harvest photos WITH captions from the story's own coverage (our DB's member articles + local-
# language Bing News RSS), link the story's names to Wikidata (aliases in the local language, the subject's portrait/poster),
# gate on caption text, let the text LLM pick like a picture editor, then the size/collage/text filters decide.
ENTITIES = """You prepare a news picture search. From the story, return JSON:
{"entities": [{"name": "<as written>", "type": "person|place|event|work|object|organisation",
               "what": "<2-4 words saying what it is, e.g. Israeli documentary film, Panamanian town, US press secretary>"}],
               (the 2-5 the event itself is about - NEVER people or countries that only reacted, commented or condemned)
 "subject": "<the ONE person, work, place or object this story is mainly about>",
 "lang": "<ISO code of the language spoken where it happened, e.g. es, ar, hi, he, fr; en if English-speaking>",
 "visual": ["<3-6 concrete things a camera would see in a photo of THIS story, English, e.g. collapsed building, rubble,
             missile, airport, poster>"],
 "visual_local": ["<the same words in that local language>"],
 "ideal_photo": "<one sentence describing the ideal photo of THIS story as a camera would see it, e.g. collapsed houses
                 and rubble in a small town after an earthquake; a woman speaking at the White House press briefing podium>",
 "news_queries": ["<3 short news searches (2-4 words, no dates) for coverage of THIS event: 1) in the local language,
                   2) in English, 3) just the 2-3 key names in English. Put a rare name/title that could be spell-corrected in
                   double quotes on its own, e.g. \"NAZA\" documentary>"]}"""
EDITOR = """You are a TV news picture editor choosing the photo for the studio screen behind the anchor reading this story.
Each candidate line: [n] caption | alt text | article headline | outlet | article date | source. Captions may be in any
language. Choose photos that SHOW this story: the scene of this event or its aftermath, or its named subject (the person
the story is about, the film's poster for a film story, the place/object involved). A captioned photo that names this
event's place and date beats one without a caption. Never choose: a file/archive photo, a different or older event, a
map, chart, graphic or logo, a screenshot, someone not in the story, a generic illustration, or a person who only reacted
to or commented on the event (a spokesperson at a podium elsewhere) unless the story is about them. If the story is mainly
about a person (see SUBJECT), a clear photo of THAT person beats photos of anyone else. For a disaster, attack or crash, a
photo of the impact (the damage, the strike site, rescuers, people affected) beats a general or skyline view of the area.
Judge ONLY from what the caption/headline says: a caption that does not describe the photo (an agency slug such as
"TOPSHOT-UKRAINE-...", a bare place name) is weak evidence, and your "why" must restate what the caption says.
Return JSON {"picks": [{"n": <number>, "why": "<8 words>"}]} - up to 8, best first; [] if none fits."""
FILE_WORDS = ("file photo", "file image", "file pic", "archive", "archivo", "archives", "representational", "representative image",
              "illustrative", "illustration", "ilustración", "imagen de referencia", "stock photo", "symbolic", "symbolbild",
              "फाइल फोटो", "फ़ाइल फोटो", "प्रतीकात्मक", "صورة أرشيفية", "أرشيف", "תמונת ארכיון", "photo d'archives", "foto de archivo")
JUNK_URL = re.compile(r"\.svg|logo|icon|avatar|sprite|placeholder|default[-_]|favicon|banner|/ads?/|1x1|pixel", re.I)
WIKI_UA = {"User-Agent": "AnchorStudio/1.0 (DNL news video pipeline; https://global.democracynewslive.com)"}


def _fold(t):
    """Lower-case, accents off: 'Panamá' == 'panama'."""
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFKD", t or "").lower() if not unicodedata.combining(c))


def _get(url, headers=_UA, limit=900_000, timeout=15):
    return urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout).read(limit).decode("utf-8", "ignore")


def _attrs(tag):
    return {k.lower(): html.unescape(v1 or v2) for k, v1, v2 in re.findall(r'([\w:-]+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\')', tag)}


def page_photos(url):
    """Photos an article page shows, each with whatever caption the page gives: og:image (+og:image:alt), JSON-LD ImageObject
    captions, <figure> + <figcaption>. Returns {"url", "title", "date", "photos": [{"img", "caption", "kind"}]} or None."""
    try:
        t = _get(url)
    except Exception:  # noqa: BLE001 - paywalls, 403s, timeouts are expected
        return None
    meta = {}
    for tag in re.findall(r"<meta\b[^>]*>", t, re.I):
        a = _attrs(tag)
        k = a.get("property") or a.get("name") or ""
        if k and "content" in a:
            meta.setdefault(k.lower(), a["content"])
    title = meta.get("og:title") or html.unescape((re.search(r"<title[^>]*>(.*?)</title>", t, re.S | re.I) or [None, ""])[1]).strip()
    date = meta.get("article:published_time") or ""
    photos = []
    if meta.get("og:image"):
        photos.append({"img": meta["og:image"], "caption": meta.get("og:image:alt") or meta.get("twitter:image:alt") or "", "kind": "lead"})
    for block in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', t, re.S | re.I):
        try:
            stack = [json.loads(block.strip())]
        except ValueError:
            continue
        while stack:
            x = stack.pop()
            if isinstance(x, list):
                stack += x
            elif isinstance(x, dict):
                if not date and isinstance(x.get("datePublished"), str):
                    date = x["datePublished"]
                if x.get("@type") == "ImageObject" and isinstance(x.get("url"), str) and isinstance(x.get("caption"), str):
                    photos.append({"img": x["url"], "caption": x["caption"], "kind": "jsonld"})
                stack += [v for v in x.values() if isinstance(v, (dict, list))]
    for fig in re.findall(r"<figure\b.*?</figure>", t, re.S | re.I)[:6]:
        img = re.search(r"<img\b[^>]*>", fig, re.I)
        cap = re.search(r"<figcaption[^>]*>(.*?)</figcaption>", fig, re.S | re.I)
        if img and cap:
            a = _attrs(img.group(0))
            src = a.get("data-src") or a.get("src") or ""
            if a.get("srcset"):
                src = a["srcset"].split(",")[-1].strip().split(" ")[0]          # the widest srcset entry
            text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(cap.group(1)))).strip()
            if src.startswith("http") and len(text) > 15:
                photos.append({"img": src, "caption": text, "kind": "figure"})
    seen, out = set(), []
    for p in photos:
        if p["img"] not in seen and not JUNK_URL.search(p["img"]):
            seen.add(p["img"])
            out.append(dict(p, caption=p["caption"][:300]))
    return {"url": url, "title": (title or "")[:200], "date": date[:10], "photos": out[:4]}


def _member_urls(story, cap=80):
    """Article URLs of every fragment merged into this story (our DB, read-only). [] without DB access."""
    ids = [f["id"] if isinstance(f, dict) else f for f in story.get("fragments") or []]
    if not ids:
        return []
    try:
        from . import select_stories
        with select_stories._connect() as con, con.cursor() as cur:
            cur.execute("SELECT a.url FROM analytics.story_cluster_members_v8 m JOIN articles a ON a.id = m.article_id "
                        "WHERE m.story_id::text = ANY(%s) ORDER BY coalesce(a.source_tier, 9), a.published_at DESC NULLS LAST LIMIT %s",
                        (ids, cap))
            return [r["url"] if isinstance(r, dict) else r[0] for r in cur.fetchall()]
    except Exception:  # noqa: BLE001 - no DB here: the story's own thumbnails still come through
        return []


def _news_rss(query, n=12):
    """Bing News RSS (a published feed, not the retired API): article URLs for a local-language query."""
    try:
        t = _get("https://www.bing.com/news/search?format=rss&q=" + urllib.parse.quote(query))
    except Exception:  # noqa: BLE001
        return []
    out = []
    for link in re.findall(r"<item>.*?<link>(.*?)</link>", t, re.S):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(html.unescape(link)).query)
        u = q.get("url", [html.unescape(link)])[0]
        if "bing.com" not in urllib.parse.urlparse(u).netloc:
            out.append(u)
    return out[:n]


def _wikidata(name, langs, what=""):
    """{qid, names (all labels/aliases in en+local), p18 (Commons image URL)} for the Wikidata item whose description agrees
    with `what` (the LLM's 2-4 word gloss), or None. Without that check "NAZA" (a film) linked to a French rapper's portrait."""
    want = {w for w in re.findall(r"\w{4,}", _fold(what))}
    try:
        hits = json.loads(_get("https://www.wikidata.org/w/api.php?action=wbsearchentities&format=json&limit=7&language=en&search="
                               + urllib.parse.quote(name), WIKI_UA))["search"]
        hit = next((h for h in hits if want & set(re.findall(r"\w{4,}", _fold(h.get("description", ""))))), None)
        if hit is None:
            return None
        qid = hit["id"]
        e = json.loads(_get(f"https://www.wikidata.org/w/api.php?action=wbgetentities&format=json&props=labels|aliases|claims"
                            f"&languages={'|'.join(langs)}&ids={qid}", WIKI_UA, limit=4_000_000))["entities"][qid]
    except Exception:  # noqa: BLE001
        return None
    names = {v["value"] for v in e.get("labels", {}).values()} | {a["value"] for v in e.get("aliases", {}).values() for a in v}
    p18 = (e.get("claims", {}).get("P18") or [{}])[0].get("mainsnak", {}).get("datavalue", {}).get("value")
    return {"qid": qid, "names": names | {name}, "p18": f"https://commons.wikimedia.org/wiki/Special:FilePath/{urllib.parse.quote(p18)}?width=1600"
            if p18 else None}


SCENE_POOL, SCENE_RANK_STEP = 4, 0.01   # ponytail: rank step is a guess (SigLIP cosines ~0.05-0.20); tune on labelled picks
TITLE_WORDS = set("""This That These Those With After Amid Over Into From Says What When Where Inside Under Against About Before
Between During Their There Here Will Would Could Should Than Then Them They Your Ours Just More Most Powerful Major Deadly
Breaking Leaving Meets Puts Push Names Slams Moves Fresh Again Still""".split())   # title-case words that are not names
KEYED_PRIMARY = os.environ.get("WALL_KEYED_PRIMARY", "1") == "1"   # user 2026-10-22: keyed search on every story, its hits ranked first
LAYER1_BELOW = 5          # (KEYED_PRIMARY=0 only) fewer captioned photos naming the story than this -> spend free-tier searches
FREE = {"SERPAPI_KEY": 250, "TAVILY_API_KEY": 1000}      # free searches per key (account) per month, checked 2026-10-11
USAGE = pathlib.Path.home() / ".config" / "anchor-studio" / "search_usage.json"


def _take(var, log):
    """A key from the comma-separated pool `var` that is still inside its free monthly allowance (95%), counted locally;
    None when every key is used up (the free layer 0 carries on alone)."""
    from datetime import date
    month = str(date.today())[:7]
    try:
        use = json.loads(USAGE.read_text())
    except (OSError, ValueError):
        use = {}
    use = {month: use.get(month, {})}
    for i, k in enumerate(x.strip() for x in os.environ.get(var, "").split(",") if x.strip()):
        name = f"{var}#{i + 1}"
        if use[month].get(name, 0) < FREE[var] * 0.95:
            use[month][name] = use[month].get(name, 0) + 1
            USAGE.write_text(json.dumps(use))
            return k
    if os.environ.get(var):
        log(f"{var}: free monthly allowance used up on every key")
    return None


def _serpapi_images(query, log):
    """Google Images via SerpAPI (free 250/month/key): past week, with each image's page title, outlet and full size."""
    k = _take("SERPAPI_KEY", log)
    if not k:
        return []
    try:
        r = json.loads(_get("https://serpapi.com/search.json?" + urllib.parse.urlencode(
            {"engine": "google_images", "q": query, "tbs": "qdr:w", "api_key": k}), {}, limit=5_000_000, timeout=40))
    except Exception as e:  # noqa: BLE001
        log(f"SerpAPI failed ({type(e).__name__})")
        return []
    return [{"img": x.get("original") or "", "caption": x.get("title") or "", "page": x.get("link") or ""}
            for x in r.get("images_results") or [] if (x.get("original_width") or 0) >= 900][:25]


def _tavily(query, log):
    """Tavily news search (free 1,000/month/account): (article URLs to harvest captions from, [{url, description}] images)."""
    k = _take("TAVILY_API_KEY", log)
    if not k:
        return [], []
    try:
        req = urllib.request.Request("https://api.tavily.com/search", json.dumps(
            {"query": query, "topic": "news", "days": 7, "max_results": 8, "include_images": True,
             "include_image_descriptions": True}).encode(), {"Content-Type": "application/json", "Authorization": "Bearer " + k})
        r = json.load(urllib.request.urlopen(req, timeout=60))
    except Exception as e:  # noqa: BLE001
        log(f"Tavily failed ({type(e).__name__})")
        return [], []
    imgs = [x if isinstance(x, dict) else {"url": x} for x in r.get("images") or []]
    return [x["url"] for x in r.get("results") or [] if x.get("url")], \
        [{"url": x.get("url") or "", "description": x.get("description") or ""} for x in imgs]


def _too_old(text, since):
    """A date in the image URL/caption older than the event window (e.g. /2022/11/01/) = file photo."""
    for y, m in re.findall(r"(20\d\d)[/_-](\d\d)(?:[/_-]\d\d)?", text):
        if 1 <= int(m) <= 12 and f"{y}-{m}" < since[:7]:
            return True
    return False


def _by_names(cands, names):
    """No-LLM ranking: candidates whose caption + article headline name the most story names (2+), captioned first."""
    def text(c):                                                    # a thumbnail's "title" is the story headline itself: not evidence
        return c["caption"] + ("" if c["kind"] == "thumb" else " " + c["title"])
    n = [(c["kind"] != "ai-desc", sum(x in _fold(text(c)) for x in names), bool(c["caption"]), -i) for i, c in enumerate(cands)]
    return [(-t[3], f"names {t[1]} story words") for t in sorted(n, reverse=True) if t[1] >= 2][:8]   # real captions beat AI hints


def pick(story, out_dir, log=print):
    """[the one photo that shows this story] or [] (-> logo card). See the block comment above."""
    from concurrent.futures import ThreadPoolExecutor
    from datetime import date, timedelta
    out_dir = pathlib.Path(out_dir)
    day = story.get("date") or str(date.today())
    since = str(date.fromisoformat(day[:10]) - timedelta(days=10)) if len(day) >= 10 else day
    ctx = (f"STORY: {story['headline']}\n{story.get('deck') or ''}\nWHERE: {story.get('location') or story.get('country')}\nWHEN: {day}\n"
           f"ARTICLE: {(story.get('body') or '')[:1500]}")
    try:
        plan = llm.chat_json(ENTITIES, ctx, temperature=0.1, max_tokens=3000, log=log)   # reasoning models think ~750 tokens first
    except llm.LLMUnavailable:
        plan = {}
    lang = str(plan.get("lang") or "en")[:5]
    ents = [e for e in plan.get("entities") or [] if isinstance(e, dict) and e.get("name")][:5]
    linked = {e["name"]: _wikidata(e["name"], sorted({"en", lang}), str(e.get("what") or "")) for e in ents}
    names = {_fold(n) for e in ents for n in ((linked.get(e["name"]) or {}).get("names") or {e["name"]}) if len(n) > 2}
    if not names:                                                   # no LLM: the headline's proper names stand in
        names = {re.sub(r"['’]s$", "", _fold(w)) for w in re.findall(r"\b[A-Z][\w'’-]{3,}", story["headline"]) if w not in TITLE_WORDS}
    log(f"wall photo: entities {[(e['name'], e.get('type'), (linked.get(e['name']) or {}).get('qid')) for e in ents]} | lang {lang} | "
        f"queries {plan.get('news_queries')}")

    queries = [str(q) for q in plan.get("news_queries") or []][:3]
    urls = list(dict.fromkeys(_member_urls(story) + [u for q in queries for u in _news_rss(q)]))[:110]
    with ThreadPoolExecutor(16) as ex:
        pages = [p for p in ex.map(page_photos, urls) if p]
    cands, seen = [], set()

    def add(ph, title, page, date, kind):
        """Gate one photo (stock / old date / file-photo words / duplicate) and keep it as a candidate."""
        cap = ph.get("caption") or ""
        if not ph["img"] or ph["img"] in seen or any(s in ph["img"] for s in STOCK) or _too_old(f"{cap} {ph['img']}", since) \
                or any(w in _fold(cap).replace("-", " ") for w in FILE_WORDS) or (date and date < since):   # old article: RSS can return last year's quake
            return
        seen.add(ph["img"])
        cands.append(dict(ph, caption=cap, title=title, page=page, date=date, kind=kind,
                          hit=kind not in ("ai-desc", "thumb") and any(n in _fold(cap + " " + title) for n in names),
                          outlet=urllib.parse.urlparse(page or ph["img"]).netloc.replace("www.", "")))

    for pg in pages:
        for ph in pg["photos"]:
            add(ph, pg["title"], pg["url"], pg["date"], ph["kind"])
    strong = sum(1 for c in cands if c["hit"] and c["caption"])
    if KEYED_PRIMARY or strong < LAYER1_BELOW:                       # keyed search (SerpAPI Google Images + Tavily news)
        en = (queries[1:] or queries or [story["headline"]])
        log(f"wall photo: {strong} captioned photos from free sources name the story - keyed search: {en[:2]}")
        for h in _serpapi_images(en[0], log):
            add(h, h["caption"], h["page"], "", "search")
        art, imgs = _tavily(en[-1], log)
        with ThreadPoolExecutor(8) as ex:
            for pg in [p for p in ex.map(page_photos, art) if p]:
                for ph in pg["photos"]:
                    add(ph, pg["title"], pg["url"], pg["date"], ph["kind"])
        for im in imgs:                                              # Tavily's own AI description: a hint, never proof
            add({"img": im["url"], "caption": f"(AI description) {im['description']}" if im["description"] else ""},
                "", "", "", "ai-desc")
    for u in story.get("images") or []:                             # the story's own thumbnails (no caption) as a last resort
        add({"img": u, "caption": ""}, story["headline"], "", "", "thumb")
    cands.sort(key=lambda c: (not c["hit"], not c["caption"], KEYED_PRIMARY and c["kind"] != "search", c["kind"] == "thumb"))
    cands = cands[:70]
    log(f"wall photo: {len(pages)} article pages, {len(cands)} candidates ({sum(c['hit'] for c in cands)} name the story, "
        f"{sum(bool(c['caption']) for c in cands)} captioned)")

    order = []
    if cands:
        lines = "\n".join(f"[{i}] {c['caption'] or '(no caption)'} | {c['title']} | {c['outlet']} | {c['date'] or '?'} | {c['kind']}"
                          for i, c in enumerate(cands))
        try:
            res = llm.chat_json(EDITOR, ctx[:900] + f"\nSUBJECT: {plan.get('subject') or ''}\n\nCANDIDATES:\n" + lines, temperature=0.0, max_tokens=4000, log=log)
            order = [(int(p["n"]), str(p.get("why") or "")) for p in res.get("picks") or []
                     if isinstance(p, dict) and str(p.get("n", "")).isdigit() and int(p["n"]) < len(cands)]
        except llm.LLMUnavailable:
            order = _by_names(cands, names)
    subj = next((e for e in ents if e["name"] == plan.get("subject") and e.get("type") == "person"), None)
    if subj:                                                        # the LLM still picked Trump for a story about his new press secretary
        sur = _fold(subj["name"].split()[-1])
        order.sort(key=lambda o: sur not in _fold(cands[o[0]]["caption"] + " " + cands[o[0]]["title"]))
    ok = []                                                         # up to 4 photos the captions qualified and the filters passed
    for i, why in order:
        c = cands[i]
        got = fetch([c["img"]], out_dir, log=log, keep=1)
        if got and got[0]["w"] >= 900:
            ok.append(dict(got[0], caption=c["caption"], title=c["title"], page=c["page"], outlet=c["outlet"], why=why, n=i))
            if len(ok) >= SCENE_POOL:
                break
    if ok:
        ideal = str(plan.get("ideal_photo") or f"a news photograph of: {story['headline']}")
        for rank, p in enumerate(ok):                               # scene match, minus a small penalty per editor rank
            p["scene"] = _scene(p["path"], ideal)
            p["score"] = (p["scene"] or 0) - SCENE_RANK_STEP * rank
        best = max(ok, key=lambda p: p["score"])
        log(f"wall photo: ideal '{ideal[:90]}' | scene " + ", ".join(f"[{p['n']}] {p['scene'] if p['scene'] is None else round(p['scene'], 3)}"
                                                                      for p in ok))
        log(f"wall photo: [{best['n']}] {best['outlet']} '{(best['caption'] or best['title'])[:90]}' ({best['w']}x{best['h']}) - {best['why']}")
        return [best]
    ents.sort(key=lambda e: e["name"] != plan.get("subject"))     # the main subject's own image first
    for e in ents:                                                  # the subject itself: portrait / poster / landmark
        w = linked.get(e["name"]) or {}
        if w.get("p18") and e.get("type") in ("person", "work", "place", "object"):
            got = fetch([w["p18"]], out_dir, log=log, keep=1, max_text=0.5 if e.get("type") == "work" else 0.04, min_ar=0.5)
            if got:
                log(f"wall photo: subject image of {e['name']} ({w['qid']}) from Wikimedia Commons")
                return [dict(got[0], caption=f"{e['name']} (Wikimedia Commons)", page=w["p18"], outlet="commons.wikimedia.org")]
    log("wall photo: nothing shows this story - logo card")
    return []


def title_card(title, out):
    """Broadcast title card: bold white headline (<= 3 lines) under a red accent bar on the logo card's navy."""
    from PIL import ImageDraw, ImageFont
    font_path = next((f for f in FONTS if os.path.exists(f)), None)
    words, max_w = title.split(), W * 0.84
    for size in range(int(H * 0.09), int(H * 0.04), -4):          # biggest type that fits 3 lines
        font = ImageFont.truetype(font_path, size) if font_path else ImageFont.load_default(size=size)
        lines = [words[0]]
        for w in words[1:]:
            if font.getlength(f"{lines[-1]} {w}") <= max_w:
                lines[-1] += f" {w}"
            else:
                lines.append(w)
        if len(lines) <= 3 and all(font.getlength(l) <= max_w for l in lines):
            break
    im = Image.new("RGB", (W, H), "#0b1626")
    d = ImageDraw.Draw(im)
    lh = int(size * 1.2)
    top = (H - lh * len(lines)) // 2
    bar_w = int(W * 0.12)
    d.rectangle([(W - bar_w) // 2, top - int(H * 0.06), (W + bar_w) // 2, top - int(H * 0.06) + int(H * 0.012)], fill="#d71920")
    for i, l in enumerate(lines):
        d.text((W / 2, top + i * lh + lh / 2), l, font=font, fill="white", anchor="mm")
    im.save(out)
    return out


def ken_burns(photos, seconds, out, log=print, title=None):
    """Slow push-in per photo, cross-faded; total length >= seconds. Falls back to the DNL logo card.
    With a title, the wall opens on a TITLE_S title card that cross-fades into the photos."""
    srcs = [p["path"] for p in photos] or [str(LOGO)]
    n = len(srcs)
    lead = TITLE_S - XF if title else 0                             # card time before the photo chain starts
    seg = (seconds - lead + XF * (n - 1)) / n + 0.5
    frames = int(seg * FPS)
    args = ["ffmpeg", "-v", "error", "-y"]
    for s in srcs:
        args += ["-i", s]
    f = []
    for i in range(n):
        if photos and photos[i].get("w", 16) / photos[i].get("h", 9) < 1.3:      # poster/portrait: fit it, blurred fill behind
            pre = (f"[{i}:v]split[a{i}][b{i}];[a{i}]scale={W * 1.15:.0f}:{H * 1.15:.0f}:force_original_aspect_ratio=increase,"
                   f"crop={W * 1.15:.0f}:{H * 1.15:.0f},boxblur=30[bg{i}];[b{i}]scale=-2:{H * 1.15:.0f}[fg{i}];"
                   f"[bg{i}][fg{i}]overlay=(W-w)/2:0")
        elif photos:
            pre = f"[{i}:v]scale={W * 1.15:.0f}:{H * 1.15:.0f}:force_original_aspect_ratio=increase,crop={W * 1.15:.0f}:{H * 1.15:.0f}"
        else:   # logo card: centred logo on a dark navy background, still no readable text beyond the mark
            pre = (f"color=c=0x0b1626:s={W * 1.15:.0f}x{H * 1.15:.0f}:d=1[bg{i}];[{i}:v]scale=-1:{H * 0.35:.0f}[lg{i}];"
                   f"[bg{i}][lg{i}]overlay=(W-w)/2:(H-h)/2")
        # zoompan places its crop on whole input pixels, so at 1.15x the slow zoom steps a pixel at a time and the picture
        # shakes; at 8x more pixels the steps are sub-pixel in the output and the push-in is smooth.
        f.append(f"{pre},scale={W * 9.2:.0f}:{H * 9.2:.0f}:flags=bicubic,zoompan=z='1+0.08*on/{frames}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={W}x{H}:fps={FPS},"
                 f"format=yuv420p,setsar=1[v{i}]")
    last = "v0"
    for i in range(1, n):
        f.append(f"[{last}][v{i}]xfade=transition=fade:duration={XF}:offset={i * (seg - XF):.3f}[x{i}]")
        last = f"x{i}"
    if title:
        card = title_card(title, pathlib.Path(out).with_suffix(".title.png"))
        args += ["-loop", "1", "-framerate", str(FPS), "-t", f"{TITLE_S:.2f}", "-i", str(card)]
        f.append(f"[{n}:v]format=yuv420p,setsar=1[tc];[tc][{last}]xfade=transition=fade:duration={XF}:offset={lead:.3f}[xt]")
        last = "xt"
    args += ["-filter_complex", ";".join(f), "-map", f"[{last}]", "-t", f"{seconds + 1:.2f}", "-c:v", "libx264", "-crf", "18",
             "-pix_fmt", "yuv420p", str(out)]
    subprocess.run(args, check=True)
    log(f"wall video: {'title card + ' if title else ''}{n} {'photos' if photos else 'logo card'} -> {out}")
    return out


if __name__ == "__main__":                                         # self-check: logo-card fallback renders
    import tempfile
    d = pathlib.Path(tempfile.mkdtemp())
    ken_burns([], 4, d / "w.mp4", log=lambda *_: None)
    dur = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(d / "w.mp4")]))
    assert dur >= 4, dur
    ken_burns([], 10, d / "t.mp4", log=lambda *_: None, title="POWER TV HEAD ARRESTED IN KARNATAKA CYBERCRIME CASE")
    tdur = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(d / "t.mp4")]))
    assert tdur >= 10, tdur
    for t in (1, 8):
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(t), "-i", str(d / "t.mp4"), "-frames:v", "1", str(d / f"t{t}.png")], check=True)
        print("frame", t, d / f"t{t}.png")
    print("assets self-check OK", dur, tdur)


# ---------------------------------------------------------------- NDC: pictures per VO, next to its footage (user 2026-11-02)
def _bing_images(query, n=30):
    """Bing Images, large and wide (free, no key) -> [{"img", "page", "title"}]."""
    t = _get("https://www.bing.com/images/async?" + urllib.parse.urlencode(
        {"q": query, "first": 0, "count": n, "qft": "+filterui:imagesize-large+filterui:aspect-wide"}), limit=3_000_000)
    out = []
    for m in re.findall(r'm="(\{[^"]+\})"', t):
        j = json.loads(html.unescape(m))
        out.append({"img": j.get("murl") or "", "page": j.get("purl") or "", "title": j.get("t") or ""})
    return out


def _commons_images(query, n=12):
    """Wikimedia Commons bitmaps for the query (free) -> [{"img", "page", "title"}]."""
    d = json.loads(_get("https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(
        {"action": "query", "format": "json", "generator": "search", "gsrsearch": f"{query} filetype:bitmap", "gsrnamespace": 6,
         "gsrlimit": n, "prop": "imageinfo", "iiprop": "url", "iiurlwidth": 1920}), WIKI_UA, limit=3_000_000))
    return [{"img": (pg["imageinfo"][0].get("thumburl") or pg["imageinfo"][0]["url"]), "page": pg["imageinfo"][0].get("descriptionurl", ""),
             "title": pg["title"].removeprefix("File:")} for pg in ((d.get("query") or {}).get("pages") or {}).values() if pg.get("imageinfo")]


def vo_pictures(query, out_dir, keep=6, log=print, names=None):
    """Pictures for one VO's footage brief: Bing + Commons, no stock libraries or junk URLs, then the wall-photo filters
    (size/aspect, collages, broadcaster logos, text, duplicates) -> [{"path", "url", "page", "title"}].
    names: the story's people, places and organisations; a picture is kept only when its title (the page it is from)
    names one of them - captions are the evidence (2026-11-24: Bing gave e-bike adverts and Indian Army pages for an EU
    aid story)."""
    cands = []
    for src in (_bing_images, _commons_images):
        try:
            cands += src(query)
        except Exception as e:  # noqa: BLE001 - one source down must not stop the other
            log(f"picture search {src.__name__} failed ({type(e).__name__})")
    cands = [c for c in cands if c["img"].startswith("http") and not JUNK_URL.search(c["img"])
             and not any(s in c["img"] + c["page"] for s in STOCK)]
    if names:
        rx = re.compile(r"\b(" + "|".join(re.escape(_fold(n)) for n in names) + r")", re.I)
        off = [c for c in cands if not rx.search(_fold(c["title"]))]
        cands = [c for c in cands if c not in off]
        if off:
            log(f"pictures: {len(off)} dropped, their titles name nothing from the story (e.g. {off[0]['title'][:60]!r})")
    by = {c["img"]: c for c in cands}
    return [{**k, "page": by[k["url"]]["page"], "title": by[k["url"]]["title"]} for k in fetch(list(by)[:24], out_dir, log=log, keep=keep)]


def story_pictures(query, out_dir, names, urls=(), keep=24, log=print):
    """Pictures for one whole story (RIG-Video, 2026-11-24; Bing ignores the query from our machines and answers with
    random pictures): Tavily news images + the photos of the story's own and Tavily's news articles (captioned) +
    Google Images (SerpAPI, past week) + Commons. One search per story keeps the keys inside their free allowances.
    Kept only when the caption / page title names the story (names), then the wall-photo filters.
    -> [{"path", "url", "page", "title"}]"""
    cands = []
    arts, imgs = _tavily(query, log)
    cands += [{"img": x["url"], "page": "", "title": x["description"]} for x in imgs]
    for u in list(dict.fromkeys([*urls, *arts[:6]])):
        pg = page_photos(u)
        cands += [{"img": ph["img"], "page": u, "title": f"{ph['caption']} {pg['title']}".strip()} for ph in (pg or {}).get("photos", [])]
    cands += [{"img": x["img"], "page": x["page"], "title": x["caption"]} for x in _serpapi_images(query, log)]
    try:
        cands += _commons_images(query)
    except Exception as e:  # noqa: BLE001
        log(f"picture search Commons failed ({type(e).__name__})")
    rx = re.compile(r"\b(" + "|".join(re.escape(_fold(n)) for n in names) + r")", re.I) if names else None
    keep_c = [c for c in cands if c["img"].startswith("http") and not JUNK_URL.search(c["img"])
              and not any(x in c["img"] + c["page"] for x in STOCK) and (rx is None or rx.search(_fold(c["title"])))]
    log(f"pictures: {len(cands)} found, {len(keep_c)} name the story")
    by = {c["img"]: c for c in keep_c}
    return [{**k, "page": by[k["url"]]["page"], "title": by[k["url"]]["title"]} for k in fetch(list(by)[:keep * 2], out_dir, log=log, keep=keep)]
