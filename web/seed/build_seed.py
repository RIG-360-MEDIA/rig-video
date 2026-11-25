"""Build the studio's seed data from our real past work.

Reads  ~/studio-seed/raw  (copied from t8 ~/ndc-archive): the footage repo's database and cut clips,
       the Moscow and Lipetsk studio projects, the DNL selection of 27 Oct 2026, finished videos.
Writes web/public/seed/: desk.json, anchors.json, library.json, projects/<id>.json, media/.

Shapes follow web/src/data/types.ts. The one authored item is the French-protests script (written
from the real pick's article, as the script writer would); everything else is copied from real runs.
Run: ~/.cache/anchor-tools/bin/python web/seed/build_seed.py
"""
import graphics, treatments  # seed/ siblings
import json, re, sqlite3, subprocess, urllib.request
from pathlib import Path

RAW = Path.home() / "studio-seed/raw"
REG = Path.home() / "Developer/RIG-NEWS-AI-/anchor_registry"
OUT = Path(__file__).resolve().parents[1] / "public/seed"
MEDIA = OUT / "media"
DB = sqlite3.connect(RAW / "live_cutter.db")
DB.row_factory = sqlite3.Row


def w(rel, data):
    p = OUT / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=1, ensure_ascii=False))


def ff(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


def probe(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=width,height",
                        "-of", "json", str(p)], capture_output=True, text=True)
    j = json.loads(r.stdout or "{}")
    v = next((s for s in j.get("streams", []) if s.get("width")), {})
    return float(j.get("format", {}).get("duration", 0) or 0), v.get("width", 16), v.get("height", 9)


def media(rel):
    p = MEDIA / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def url(p: Path):
    return "/seed/" + str(p.relative_to(OUT))


def words(t):
    return len(t.split())


# ---------------- anchors ----------------
ANCHORS = {}


def anchors():
    out = []
    for a in json.loads((REG / "registry.json").read_text())["anchors"]:
        aid = a["id"]
        face, frame, voice = media(f"anchors/{aid}_face.jpg"), media(f"anchors/{aid}_frame.jpg"), media(f"anchors/{aid}_voice.mp3")
        if not face.exists():
            ff("-i", str(REG / a["identity_face"]), "-vf", "scale=320:-2", "-q:v", "4", str(face))
            ff("-i", str(REG / a["identity_ref"]), "-vf", "scale=960:-2", "-q:v", "4", str(frame))
            if a.get("voice_file"):
                ff("-i", str(REG / a["voice_file"]), "-t", "12", "-b:a", "96k", str(voice))
        x = {"id": aid, "name": a.get("name") or aid.replace("_", " ").title(),
             "gender": "male" if a.get("gender") == "M" else "female",
             "face": url(face), "frame": url(frame), "voiceSample": url(voice) if voice.exists() else "",
             "wordsPerSecond": 2.45, "regions": a.get("affinity") or [], "offered": a.get("status") == "ready"}
        ANCHORS[aid] = x
        out.append(x)
    # measured paces from our voice runs (words / seconds of picked takes)
    ANCHORS["maren_ashcroft"]["wordsPerSecond"] = 2.71
    ANCHORS["arjun_malhotra"]["wordsPerSecond"] = 2.52
    w("anchors.json", out)


# ---------------- footage repo → SectionVisuals ----------------
FLAG_OF = {"Text": "text", "Label:vertical": "vertical", "Label:website": "logo", "Label:presenter": "presenter"}


def thumb(youtube_id):
    p = media(f"yt/{youtube_id}.jpg")
    if not p.exists():
        try:
            data = urllib.request.urlopen(f"https://i.ytimg.com/vi/{youtube_id}/mqdefault.jpg", timeout=15).read()
            p.write_bytes(data)
        except Exception:
            return None
    return url(p)


def moment_posters(project):
    """Uncut moments get YouTube's own frame nearest their start (mq1/mq2/mq3 sit at about 25/50/75%),
    so two moments of one video don't share the video thumbnail."""
    for v in project["visuals"].values():
        for f in v["found"]:
            used = set()
            for m in sorted(f["moments"], key=lambda x: x["start"]):
                if m.get("posterNear"):
                    m.pop("poster", None)  # re-pick so moments of one video get different frames
                if m.get("poster"):
                    continue
                frac = m["start"] / max(f["duration"], 1)
                want = 1 if frac < 0.375 else 2 if frac < 0.625 else 3
                free = [k for k in (1, 2, 3) if k not in used] or [1, 2, 3]
                i = min(free, key=lambda k: abs(k - want))
                used.add(i)
                dst = media(f"yt/{f['youtubeId']}_{i}.jpg")
                if not dst.exists():
                    try:
                        dst.write_bytes(urllib.request.urlopen(f"https://i.ytimg.com/vi/{f['youtubeId']}/mq{i}.jpg", timeout=15).read())
                    except Exception:
                        continue
                m["poster"] = url(dst)
                m["posterNear"] = True
    return project


def cut(src: Path, dst: Path, start=0.0, dur=20.0):
    if not dst.exists():
        ff("-ss", str(start), "-i", str(src), "-t", str(dur), "-vf", "scale=-2:360,fps=25", "-c:v", "libx264",
           "-preset", "veryfast", "-crf", "28", "-c:a", "aac", "-b:a", "64k", "-movflags", "+faststart", str(dst))
    return dst


def poster(src: Path, dst: Path, at=1.0):
    if not dst.exists():
        ff("-ss", str(at), "-i", str(src), "-frames:v", "1", "-vf", "scale=480:-2", "-q:v", "5", str(dst))
    return dst


def repo_section(pid_title, key, shot_flags=None):
    """One footage-repo project (one per script section) → keywords + found videos with moments."""
    proj = DB.execute("select * from footage_projects where title=? order by created_at desc", (pid_title,)).fetchone()
    pid = proj["id"]
    kws, found = [], []
    clips = {(c["video_id"], round(c["start_seconds"])): c for c in DB.execute(
        "select * from footage_clips where project_id=? and status='done'", (pid,))}
    for k in DB.execute("select * from footage_keywords where project_id=? order by position", (pid,)):
        kws.append({"id": k["id"][:8], "text": k["text"], "reason": k["rationale"], "state": "done"})
        for v in DB.execute("select * from footage_videos where keyword_id=? order by relevance desc", (k["id"],)):
            if v["relevance"] < 10:
                continue
            moments = json.loads(v["moments_json"] or "[]")
            flags = set()
            for m in moments:
                c = clips.get((v["video_id"], round(m["start"])))
                if c:
                    f = RAW / "footage_clips" / pid / f"{c['id']}.mp4"
                    if f.exists():
                        base = f"{key}_{c['label']}"
                        cut(f, media(f"clips/{base}.mp4"))
                        poster(media(f"clips/{base}.mp4"), media(f"clips/{base}.jpg"))
                        m["clip"] = url(media(f"clips/{base}.mp4"))
                        m["poster"] = url(media(f"clips/{base}.jpg"))
                        fl = (shot_flags or {}).get(c["label"], set())
                        flags |= fl
                        m["flags"] = sorted(fl)
            found.append({
                "id": v["id"][:10], "keywordId": k["id"][:8], "youtubeId": v["video_id"], "title": v["title"],
                "channel": v["channel"], "publishedAt": v["published_at"], "duration": v["duration_seconds"] or 0,
                "thumb": thumb(v["video_id"]) or "", "relevance": v["relevance"], "verdict": v["verdict"],
                "hasCaptions": bool(v["has_transcript"]), "moments": moments, "flags": sorted(flags),
            })
    found.sort(key=lambda f: -f["relevance"])
    # dedupe the same YouTube video found by two keywords
    seen, uniq = set(), []
    for f in found:
        if f["youtubeId"] in seen:
            continue
        seen.add(f["youtubeId"])
        uniq.append(f)
    return {"keywords": kws, "found": uniq, "photos": [], "uploads": [], "maps": [], "placed": []}


def place(vis, seconds_wanted):
    """Place clipped moments in fit order until the section is filled (or as far as wanted)."""
    t, n = 0.0, 0
    for f in vis["found"]:
        for i, m in enumerate(f["moments"]):
            if not m.get("clip") or t >= seconds_wanted:
                continue
            d = min(5.0, seconds_wanted - t)
            vis["placed"].append({"id": f"p{n}", "ref": {"kind": "moment", "videoId": f["id"], "moment": i},
                                  "in": 0.0, "out": round(d, 1), "muted": True, "useTreated": bool(f.get("treatment"))})
            t += d
            n += 1
    return t


def secs(text, aid):
    return round(words(text) / ANCHORS[aid]["wordsPerSecond"], 1)


def shot_flags_efea(p):
    out = {}
    for s in p["shots"]:
        label = Path(s["clip"]).stem  # a1_1
        tag = s["verdict"].split()[0].rstrip(";")
        if not s["keep"] and tag in FLAG_OF:
            out.setdefault(label, set()).add(FLAG_OF[tag])
    return out


def merged(sections, aid):
    return [{"id": "all", "kind": "anchor", "text": " ".join(s["text"] for s in sections)}]


# ---------------- projects ----------------
def moscow():
    p = json.loads((RAW / "projects/story-efea/project.json").read_text())
    aid = "maren_ashcroft"
    fl = shot_flags_efea(p)
    facts = [{"label": k, "value": v} for k, v in p["facts"]]
    lt = p["lt"]
    subs = {"a1": "155 drones launched toward the capital overnight", "a2": "Mayor Sobyanin: five reached the city and were shot down",
            "a3": "Air defence engaged at long range across the region", "a4": "Moscow airports reopen after overnight restrictions"}
    sections, visuals = [], {}
    for part in p["parts"]:
        s = {"id": part["id"], "kind": part["kind"], "text": p["texts"].get(part["id"], part["text"])}
        if part["kind"] == "anchor":
            s["lt"] = {"kicker": lt["location"], "headline": lt["headline"] if part["id"] == "a1" else
                       ("MOSCOW REPELS OVERNIGHT DRONE WAVE" if part["id"] != "a4" else "AIRPORTS REOPEN AFTER DRONE ALERT"),
                       "subline": subs[part["id"]]}
        s["voice"] = {"state": "making", "takes": [], "pick": None}
        sections.append(s)
        vis = repo_section(f"The Night the Sky Over Moscow Turned Into a Frontline {part['id']}", f"mos_{part['id']}", fl)
        want = secs(s["text"], aid)
        if part["kind"] == "anchor":
            # behind the anchor: one still, from the best clipped moment's poster
            vis["photos"] = [{"id": f"ph_{part['id']}", "src": next((m["poster"] for f in vis["found"] for m in f["moments"] if m.get("poster")), ""),
                              "caption": "Frame from the top-scoring clip for this part", "credit": "Footage search", "source": "repo"}]
            if part["id"] != "a4":
                vis["placed"] = [{"id": "behind", "ref": {"kind": "photo", "id": f"ph_{part['id']}"}, "in": 0, "out": want, "muted": True, "useTreated": False}]
        else:
            place(vis, want if part["id"] != "v1" else want - 8)   # VO 1 left 8 s short: the locked state
        visuals[part["id"]] = vis
    return {
        "id": "story-efea", "headline": p["headline"], "createdAt": "2026-10-27T12:58:00+05:30", "updatedAt": "2026-11-10T14:02:00+05:30",
        "source": {"kind": "link", "url": p["url"], "site": "democracynewslive.com", "text": p.get("body", "")[:4000]},
        "targetSeconds": 90, "anchorId": aid, "tone": p.get("tone", "Urgent"), "stage": "visuals", "format": "anchor_vo",
        "versions": {"anchor_vo": sections, "anchor_only": merged(sections, aid)},
        "ticker": [lt["ticker"], "Sobyanin: drones intercepted on approach to the capital",
                   "Vnukovo and Domodedovo restrict flights during the attack", "Air defence active across the Moscow region overnight"],
        "facts": facts, "visuals": visuals,
    }


def drones616():
    b = json.loads((RAW / "drones616_footage_beats.json").read_text())
    aid = "maren_ashcroft"
    sections, visuals = [], {}
    for beat in b["beats"]:
        kind = "anchor" if beat["id"].startswith("a") else "vo"
        s = {"id": beat["id"], "kind": kind, "text": beat["text"],
             "voice": {"state": "ready", "takes": [], "pick": None}}
        if kind == "anchor":
            s["lt"] = {"kicker": "RUSSIA", "headline": "616 DRONES DOWNED IN OVERNIGHT ATTACK", "subline": "Strikes reach 19 regions, Moscow and Crimea"}
        sections.append(s)
        vis = repo_section(f"Russia 616 drones - hybrid example {beat['id']}", f"d616_{beat['id']}")
        place(vis, secs(beat["text"], aid))
        visuals[beat["id"]] = vis
    return {
        "id": "story-d616", "headline": "Russia says it downed 616 Ukrainian drones in one night",
        "createdAt": "2026-10-25T15:12:00+05:30", "updatedAt": "2026-11-10T13:41:00+05:30",
        "source": {"kind": "text", "text": " ".join(x["text"] for x in b["beats"])},
        "targetSeconds": 60, "anchorId": aid, "tone": "Serious", "stage": "render", "format": "anchor_vo",
        "versions": {"anchor_vo": sections, "anchor_only": merged(sections, aid)},
        "ticker": ["Russia: 616 Ukrainian drones destroyed overnight", "Sheremetyevo halts arrivals and departures",
                   "Over 80 drones downed over Rostov-on-Don"],
        "facts": [{"label": "What", "value": "Russia says 616 Ukrainian drones were destroyed in one night"},
                  {"label": "Where", "value": "19 regions, the Moscow region and Crimea"},
                  {"label": "When", "value": "Night of 23 October 2026"}],
        "visuals": visuals,
        "render": {"projectId": "story-d616", "state": "rendering", "queuePosition": 0, "percent": 62, "etaIso": None},
    }


def lipetsk():
    p = json.loads((RAW / "projects/story-62ba/project.json").read_text())
    aid = "maren_ashcroft"
    takes_by_part = {}
    for tj in (RAW / "projects/story-62ba/voice").glob("t*/takes/*.wav"):
        m = re.search(r"_(a\d)_s(\d+)\.wav$", tj.name)
        if m:
            takes_by_part.setdefault(m.group(1), []).append(tj)
    photo = media("photos/lipetsk_1.jpg")
    if not photo.exists():
        ff("-i", str(RAW / "projects/story-62ba/media/photos/photo_1.jpg"), "-vf", "scale=1280:-2", "-q:v", "4", str(photo))
    ph = {"id": "ph1", "src": url(photo), "caption": p["photos"][0]["note"], "credit": p["photos"][0]["credit"], "source": "article"}
    sections, visuals = [], {}
    lt = p["lt"]
    for part in p["parts"]:
        files = sorted(takes_by_part.get(part["id"], []))[-3:]
        takes = []
        for f in files:
            dst = media(f"voice/lipetsk_{f.stem}.mp3")
            if not dst.exists():
                ff("-i", str(f), "-b:a", "96k", str(dst))
            takes.append({"id": f.stem.split("_")[-1], "src": url(dst), "seconds": round(probe(dst)[0], 2)})
        picked = (p.get("voice", {}).get(part["id"]) or {}).get("src", "")
        pick = next((t["id"] for t in takes if t["id"] in picked), takes[0]["id"] if takes else None)
        s = {"id": part["id"], "kind": "anchor", "text": p["texts"].get(part["id"], part["text"]),
             "lt": {"kicker": lt["location"], "headline": lt["headline"], "subline": "Polyclinic and homes damaged, one man in hospital"},
             "voice": {"state": "ready", "takes": takes, "pick": pick}}
        sections.append(s)
        visuals[part["id"]] = {"keywords": [], "found": [], "photos": [ph], "uploads": [], "maps": [],
                               "placed": [{"id": "behind", "ref": {"kind": "photo", "id": "ph1"}, "in": 0,
                                           "out": next((t["seconds"] for t in takes if t["id"] == pick), 12), "muted": True, "useTreated": False}]}
    return {
        "id": "story-62ba", "headline": p["headline"], "createdAt": "2026-10-27T13:40:00+05:30", "updatedAt": "2026-11-10T12:15:00+05:30",
        "source": {"kind": "link", "url": p.get("url") or "", "site": "militarnyi.com", "text": p.get("body", "")[:4000]},
        "targetSeconds": 60, "anchorId": aid, "tone": p.get("tone", "Serious"), "stage": "review", "format": "anchor_vo",
        "versions": {"anchor_vo": sections, "anchor_only": merged(sections, aid)},
        "ticker": [lt["ticker"], "Governor Artamonov: debris hit polyclinic on Merkulov Street"],
        "facts": [{"label": k, "value": v} for k, v in p["facts"]], "visuals": visuals,
    }


def france(pick):
    """Script stage. The script is written from the pick's article, as the script writer would."""
    aid = "eleanor_marsh"
    sections = [
        {"id": "a1", "kind": "anchor", "text": "Masked far-right groups attacked peaceful protesters in Nice, Montpellier and Nancy on the evening of October twenty-fourth, and the police are now accused of standing by.",
         "lt": {"kicker": "FRANCE", "headline": "POLICE ACCUSED OF SHIELDING FAR-RIGHT ATTACKERS", "subline": "Attacks on marchers in Nice, Montpellier and Nancy"}},
        {"id": "v1", "kind": "vo", "text": "Videos shared online show officers in Nice watching as masked men moved in on the march. Protesters say the attackers walked away without arrest. Similar scenes were reported in Montpellier and Nancy."},
        {"id": "v2", "kind": "vo", "text": "Legal complaints have now been filed against far-right militias. La France Insoumise and the Greens accuse the government of enabling the groups through its silence."},
        {"id": "a2", "kind": "anchor", "text": "Interior Minister Laurent Nuñez denies it. \"We protect no one,\" he said. The opposition wants an inquiry into how the police handled the night.",
         "lt": {"kicker": "PARIS", "headline": "NUÑEZ: \"WE PROTECT NO ONE\"", "subline": "Opposition calls for an inquiry into the police response"}},
    ]
    return {
        "id": "story-fr24", "headline": pick["headline"], "createdAt": "2026-11-10T14:20:00+05:30", "updatedAt": "2026-11-10T14:26:00+05:30",
        "source": {"kind": "link", "url": "", "site": "DNL selection", "text": pick["body"][:4000]},
        "targetSeconds": 60, "anchorId": aid, "tone": "Serious", "stage": "script", "format": "anchor_vo",
        "versions": {"anchor_vo": sections, "anchor_only": merged(sections, aid)},
        "ticker": ["France: far-right groups attack marchers in three cities", "Interior Minister Nuñez denies police complicity",
                   "Legal action filed against far-right militias"],
        "facts": [{"label": "What", "value": "Masked far-right groups attacked peaceful protesters; police accused of complicity"},
                  {"label": "Where", "value": "Nice, Montpellier and Nancy, France"},
                  {"label": "When", "value": "Evening of 24 October 2026"},
                  {"label": "Who", "value": "Interior Minister Laurent Nuñez; La France Insoumise; Les Écologistes"},
                  {"label": "Quote", "value": "\"On ne protège personne\" (Nuñez)"}],
        "visuals": {},
    }


def picks():
    d = json.loads((RAW / "selection/2026-10-27.json").read_text())
    out = []
    for x in d["picks"] + d["reserves"][:3]:
        lab = x.get("label") or {}
        out.append({"id": x["event_id"][:8], "headline": x["headline"], "deck": x["deck"],
                    "type": lab.get("category") or "turmoil_unrest", "place": lab.get("country") or x.get("country") or "",
                    "source": f"{x['sources']} sources" if isinstance(x["sources"], int) else "", "url": "",
                    "publishedAt": f"{x.get('age_h', 0):.0f}h ago", "body": x["body"][:3000]})
    return out


def library():
    L = RAW / "library"
    items = []
    for f, title, sec_title, aid, when in [
        ("sge2", "Global Strategic Assessment: SGE 2", "", "arjun_malhotra", "2026-11-03T17:22:00+05:30"),
        ("inject_1", "Americas: power without Congress", "", "priya_nair", "2026-11-06T11:05:00+05:30"),
        ("inject_2", "Europe: war, polls and borders", "", "priya_nair", "2026-11-06T11:40:00+05:30"),
        ("inject_4", "Africa: the Sahel and the Red Sea", "", "priya_nair", "2026-11-06T12:10:00+05:30"),
    ]:
        src = L / f"{f}.mp4"
        if not src.exists():
            continue
        v, pimg = media(f"library/{f}.mp4"), media(f"library/{f}.jpg")
        if not v.exists():
            v.write_bytes(src.read_bytes())
            pimg.write_bytes((L / f"{f}.jpg").read_bytes())
        items.append({"id": f, "projectId": None, "headline": title, "anchorId": aid, "madeAt": when,
                      "seconds": round(probe(v)[0]), "video": url(v), "poster": url(pimg), "origin": "studio"})
    still = media("library/inject_2_anchor.jpg")  # sign-in page: Priya at the desk
    if not still.exists() and media("library/inject_2.mp4").exists():
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "4", "-i", str(media("library/inject_2.mp4")), "-frames:v", "1", "-q:v", "3", str(still)], check=True)
    return items


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    anchors()
    pk = picks()
    projects = [moscow(), drones616(), lipetsk(), france(json.loads((RAW / "selection/2026-10-27.json").read_text())["picks"][0])]
    for p in projects:
        w(f"projects/{p['id']}.json", treatments.apply(graphics.apply(moment_posters(p))))
    lib = library()
    w("library.json", lib)
    w("desk.json", {
        "user": {"id": "u1", "name": "Yash Aggarwal", "email": "dev-admin@anchor-studio.local", "role": "admin", "workspaceId": "dnl"},
        "workspace": {"id": "dnl", "name": "DNL", "kind": "dnl", "picksFeed": True},
        "picks": [{k: v for k, v in x.items() if k != "body"} for x in pk[1:]],
        "pickBodies": {x["id"]: x["body"] for x in pk},
        "projects": [p["id"] for p in projects],
        "queue": [projects[1]["render"]],
        "library": [x["id"] for x in lib],
    })
    print("anchors", len(ANCHORS), "picks", len(pk), "projects", len(projects), "library", len(lib))
    for p in projects:
        found = sum(len(v["found"]) for v in p["visuals"].values())
        print(" ", p["id"], p["stage"], len(p["versions"]["anchor_vo"]), "sections,", found, "found videos")
