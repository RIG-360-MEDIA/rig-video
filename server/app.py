"""RIG-Video web API (trijya-7). The site (web/) talks only to this; each machine job runs as `worker.py <job> <id>`
in the tools venv, so a crash there never takes the API down. The render queue starts one render at a time, only after
a person pressed Render (the GPU go).
run: uvicorn app:app --host <tailscale ip> --port 8770   (deploy/rigvideo-api.service)"""
import datetime as dt
import json
import os
import pathlib
import re
import secrets
import subprocess
import sys
import threading
import time

from fastapi import Body, Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import store  # noqa: E402

APPDIR = pathlib.Path(os.environ.get("RIGVIDEO_APP", store.HOME / "anchor-studio" / "studio-app"))
REG = APPDIR / "anchor_registry"
TOOLS_PY = os.environ.get("ANCHOR_TOOLS_PY", str(store.HOME / ".cache" / "anchor-tools" / "bin" / "python"))
DIST = HERE.parent / "dist"
app = FastAPI(title="RIG-Video")
LOCK = threading.Lock()
RUNNING = {}                                                       # (project id, job) -> Popen
COOKIE = "rv_session"
FORMATS = ("anchor_vo", "anchor_only", "vo_only")
CUT_KEYS = ("id", "shot", "at", "secs", "src", "kind", "fit", "shows", "sound", "poster", "clip", "fill", "swapped", "review", "repeat", "byUser")


# ------------------------------------------------------------------ auth

def user(request: Request):
    u = store.session_user(request.cookies.get(COOKIE))
    if not u:
        raise HTTPException(401, "Sign in first.")
    return u


def mine(pid, u):
    try:
        p = store.read(pid)
    except KeyError:
        raise HTTPException(404, "No such story.")
    if p.get("_workspace") != u["workspaceId"]:
        raise HTTPException(404, "No such story.")
    return p


FAILS = {}                                                          # sign-in failures: key -> [times]; in memory
FAIL_MAX, FAIL_WINDOW = 5, 900                                      # 5 wrong passwords in 15 min locks that email / address


def client_ip(request):
    """The visitor's address: Cloudflare's header on the public link (rigtvnews.rig360media.com), else the socket."""
    return request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "?")


def locked(keys, now):
    for k in keys:
        FAILS[k] = [t for t in FAILS.get(k, []) if now - t < FAIL_WINDOW]
    return any(len(FAILS[k]) >= FAIL_MAX for k in keys)


@app.post("/api/login")
def login(request: Request, response: Response, body: dict = Body(...)):
    email = str(body.get("email") or "").strip().lower()
    keys, now = ("email:" + email, "ip:" + client_ip(request)), time.time()
    with LOCK:
        if locked(keys, now):
            raise HTTPException(429, "Too many wrong passwords. Try again in 15 minutes.")
    u = store.check_password(email, str(body.get("password") or ""))
    if not u:
        with LOCK:
            for k in keys:
                FAILS.setdefault(k, []).append(now)
        time.sleep(1)
        raise HTTPException(401, "That email and password don't match.")
    with LOCK:
        FAILS.pop(keys[0], None)
    https = request.headers.get("x-forwarded-proto") == "https" or os.environ.get("RIGVIDEO_HTTPS") == "1"
    response.set_cookie(COOKIE, store.session_token(u["id"]), max_age=30 * 86400, httponly=True, samesite="lax",
                        secure=https)
    return {"ok": True}


@app.post("/api/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE)
    return {"ok": True}


# ------------------------------------------------------------------ jobs

def spawn(pid, job, *args):
    with LOCK:
        pr = RUNNING.get((pid, job))
        j = (store.read(pid).get("_jobs") or {}).get(job) or {}
        if pr and pr.poll() is None or j.get("state") == "running" and alive(j.get("os_pid")):
            return                                                  # already running: it picks up the new work itself
        store.job(pid, job, state="running", progress=0.0, note="Starting", error=None)
        logf = open(store.pdir(pid) / "log.txt", "a")
        logf.write(f"\n===== {store.stamp()} {job} {' '.join(args)}\n")
        logf.flush()
        RUNNING[(pid, job)] = subprocess.Popen([TOOLS_PY, str(HERE / "worker.py"), job, pid, *args], stdout=logf,
                                               stderr=subprocess.STDOUT, cwd=HERE, start_new_session=True)
        store.job(pid, job, os_pid=RUNNING[(pid, job)].pid)


def alive(os_pid):
    return bool(os_pid) and os.path.exists(f"/proc/{os_pid}")


def queue():
    ps = [p for p in store.all_projects() if (p.get("render") or {}).get("state") in ("queued", "rendering", "assembling")]
    return sorted(ps, key=lambda p: (p["render"]["state"] == "queued", p.get("_queuedAt", "")))


AUTO_RESUME = int(os.environ.get("RIGVIDEO_AUTO_RESUME", "2"))      # restarts of one job before it is left failed


def resume(p, job, j):
    """A job whose process vanished (the machine restarted under it) starts again on its own, up to AUTO_RESUME times.
    The search resumes its footage projects; other steps start over. A render goes back in the queue (it
    waits for the render window); a post is never repeated by itself (it could upload twice)."""
    n = (p.get("render") or {}).get("resumes", 0) if job == "render" else j.get("resumes", 0)
    if job == "post" or n >= AUTO_RESUME:
        return False
    print(f"resume {p['id']} {job} ({n + 1}/{AUTO_RESUME})", flush=True)
    if job == "render":
        store.job(p["id"], job, state=None)
        store.update(p["id"], lambda q: q["render"].update(state="queued", resumes=n + 1))
    else:
        spawn(p["id"], job, *(["again"] if job == "final" else []))
        store.job(p["id"], job, resumes=n + 1)
    return True


def monitor():
    """Reap ended jobs (a job whose process is gone is marked failed); start the next render when the GPU is free."""
    while True:
        try:
            with LOCK:
                for key, pr in list(RUNNING.items()):
                    if pr.poll() is not None:
                        del RUNNING[key]
            for p in store.all_projects():
                for job, j in (p.get("_jobs") or {}).items():
                    if j.get("state") == "running" and (p["id"], job) not in RUNNING and not alive(j.get("os_pid")):
                        if resume(p, job, j):                       # a restart cut it off: start it again by itself
                            continue
                        store.job(p["id"], job, state="failed", error="Interrupted (machine restart?). Try again.",
                                  note="Interrupted (machine restart?). Try again.")
                        if job == "render":
                            store.update(p["id"], lambda q: (q["render"].update(state="failed", heldReason="Interrupted. Send it to render again."), q.update(stage="review")))
                        if job == "final":
                            store.update(p["id"], lambda q: q.setdefault("final", {}).update(state="failed", note="Interrupted. Make it again."))
                        if job == "post":
                            store.update(p["id"], lambda q: [x.update(state="failed", error="Interrupted. Post again.")
                                                             for x in (q.get("posts") or {}).values() if x.get("state") in ("posting", "uploading")])
                try:
                    auto_post(p)
                except Exception as e:                              # one story's trouble never stops the monitor
                    print("auto_post", p.get("id"), repr(e), flush=True)
            q = queue()
            if q and q[0]["render"]["state"] == "queued" and not any(k[1] == "render" for k in RUNNING) and store.in_render_window():
                store.update(q[0]["id"], lambda x: x["render"].update(state="rendering"))
                spawn(q[0]["id"], "render")
            today = store.DATA / "selection" / f"{store.now():%Y-%m-%d}.json"
            sel = getattr(monitor, "sel", None)                    # today's DNL picks: once a day, a retry each 30 min
            if os.environ.get("RIGVIDEO_NO_SELECTION") != "1" and not today.exists() and (sel is None or sel.poll() is not None and time.time() - monitor.sel_t > 1800):
                today.parent.mkdir(parents=True, exist_ok=True)
                monitor.sel_t = time.time()
                monitor.sel = subprocess.Popen([TOOLS_PY, str(HERE / "worker.py"), "selection"], stdout=open(today.parent / "log.txt", "a"),
                                               stderr=subprocess.STDOUT, cwd=HERE, start_new_session=True)
            if os.environ.get("RIGVIDEO_DAILY_AUTO") == "1" and store.now().strftime("%H:%M") >= os.environ.get("RIGVIDEO_DAILY_AT", "08:00"):
                daily_start()                                       # once a day (a marker file per day)
        except Exception as e:                                     # keep the loop alive; the next tick retries
            print("monitor:", repr(e), flush=True)
        time.sleep(4)


@app.on_event("startup")
def _start():
    store.PROJECTS.mkdir(parents=True, exist_ok=True)
    threading.Thread(target=monitor, name="monitor", daemon=True).start()


# ------------------------------------------------------------------ desk

def registry():
    return json.load(open(REG / "registry.json"))["anchors"]


def anchors():
    try:
        cal = json.loads((store.DATA / "calibration.json").read_text())
    except (OSError, json.JSONDecodeError):
        cal = {}
    return [{"id": a["id"], "name": a.get("name") or a["id"].replace("_", " ").title(), "gender": "male" if a.get("gender") == "M" else "female",
             "face": f"/anchor-media/{a['id']}/face.jpg", "frame": f"/anchor-media/{a['id']}/frame.jpg",
             "voiceSample": f"/anchor-media/{a['id']}/voice.mp3" if a.get("voice_file") else "",
             "wordsPerSecond": (cal.get(a["id"]) or {}).get("wps") or a.get("voice_wps") or 2.85,
             "regions": a.get("affinity") or [], "offered": a.get("status") == "ready"} for a in registry()]


def selection():
    """Today's DNL picks (newest selection file): Pick[] and their article bodies."""
    d = store.DATA / "selection"
    files = sorted(d.glob("20*.json")) if d.exists() else []
    if not files:
        return [], {}
    sel = json.loads(files[-1].read_text())
    made = dt.datetime.fromtimestamp(files[-1].stat().st_mtime, store.IST)
    picks, bodies = [], {}
    main = len(sel.get("picks") or [])
    for i, x in enumerate((sel.get("picks") or []) + (sel.get("reserves") or [])):
        lab = x.get("label") or {}
        pid = x["event_id"][:8]
        picks.append({"id": pid, **({"reserve": True} if i >= main else {}), "headline": x["headline"], "deck": x.get("deck") or "", "type": lab.get("category") or "turmoil_unrest",
                      "place": lab.get("country") or x.get("country") or "", "source": f"{x['sources']} sources" if isinstance(x.get("sources"), int) else "",
                      "url": f"https://democracynewslive.com/long-read/{x['event_id']}",
                      "publishedAt": (made - dt.timedelta(hours=float(x.get("age_h") or 0))).isoformat(timespec="minutes")})
        bodies[pid] = x.get("body") or ""
    return picks, bodies


def job_view(p):
    """The site's jobs map: writing and footage search, with progress (voice shows on each section)."""
    for k in ("write", "search", "check", "voice"):
        j = (p.get("_jobs") or {}).get(k)
        if j and (k != "voice" or j.get("state") == "failed"):    # voice progress shows on each part; only its failure shows here
            return {"kind": k, "progress": j.get("progress") or 0, "note": j.get("note") or "", **({"failed": True} if j.get("state") == "failed" else {}),
                    **({"parts": j["parts"]} if j.get("parts") and j.get("state") != "failed" else {})}   # per part: what the search is doing there
    return None


def view(p):
    """A project as the site sees it, with its place in the render queue."""
    out = store.public(p)
    if out.get("render") and out["render"]["state"] in ("queued", "rendering", "assembling"):
        out["render"] = {**out["render"], "queuePosition": next((i for i, q in enumerate(queue()) if q["id"] == p["id"]), 0)}
        if out["render"]["state"] == "queued" and store.render_hold():
            out["render"]["waitNote"] = "Renders are on hold tonight; they start when the hold is lifted"
        elif out["render"]["state"] == "queued" and not store.in_render_window():
            out["render"]["waitNote"] = f"Starts at {os.environ.get('RIGVIDEO_RENDER_WINDOW', '00:00-07:00').split('-')[0]} IST"
    return out


@app.get("/api/health")
def health():
    """For deploys and the boot check: the API answers, which release it runs, and whether the job loop is alive."""
    v = HERE.parent / "VERSION"
    return {"ok": True, "version": v.read_text().strip() if v.exists() else "dev",
            "monitor": any(t.name == "monitor" and t.is_alive() for t in threading.enumerate())}


@app.get("/api/desk")
def desk(u=Depends(user)):
    ws = store.WORKSPACES[u["workspaceId"]]
    ps = [p for p in store.all_projects(u["workspaceId"]) if not p.get("_archived")]
    picks = selection()[0] if ws["picksFeed"] else []
    used = {p.get("_pick") for p in store.all_projects(u["workspaceId"])}      # a pick made into a story leaves the list for everyone
    pr = store.prefs(u["id"])
    n = sum(not x.get("reserve") for x in picks)                    # as many cards as the day's picks: one used or removed
    picks = [x for x in picks if x["id"] not in used and x["id"] not in pr["hiddenPicks"]][:n]   # is replaced by the next reserve
    picks += [view_pick(x) for x in own_picks(u["workspaceId"]) if x["id"] not in used]           # the desk's own picks
    lib = sorted([p["_library"] for p in ps if p.get("_library")], key=lambda x: x["madeAt"], reverse=True)
    return {"user": {k: u[k] for k in ("id", "name", "email", "role", "workspaceId")}, "workspace": ws,
            "picks": picks, "hiddenPicks": pr["hiddenPicks"], "defaults": pr["defaults"],
            "formats": list(FORMATS), "anchors": anchors(), "projects": [view(p) for p in ps], "jobs": {p["id"]: j for p in ps if (j := job_view(p))},
            "queue": [view(p)["render"] for p in queue() if p.get("_workspace") == u["workspaceId"]], "library": lib}


@app.put("/api/prefs")
def prefs(body: dict = Body(...), u=Depends(user)):
    pr = store.prefs(u["id"])
    if isinstance(body.get("defaults"), dict):
        pr["defaults"] = {**pr["defaults"], **{k: v for k, v in body["defaults"].items() if k in pr["defaults"] and (k != "format" or v in FORMATS)}}
    if isinstance(body.get("hiddenPicks"), list):
        pr["hiddenPicks"] = [str(x)[:20] for x in body["hiddenPicks"]][-500:]
    store.save_prefs(u["id"], pr)
    return pr


# ------------------------------------------------------------------ projects

REGION = {"RU": "russia_ukraine", "UA": "russia_ukraine", "IN": "south_asia", "PK": "south_asia", "BD": "south_asia", "LK": "south_asia",
          "NP": "south_asia", "IL": "middle_east", "PS": "middle_east", "IR": "middle_east", "SA": "middle_east", "IQ": "middle_east",
          "SY": "middle_east", "LB": "middle_east", "YE": "middle_east", "EG": "middle_east", "TR": "turkey", "US": "north_america",
          "CA": "north_america", "BR": "latin_america", "MX": "latin_america", "AR": "latin_america", "CO": "latin_america",
          "VE": "latin_america", "CN": "east_asia", "JP": "east_asia", "KR": "east_asia", "TW": "east_asia", "PH": "southeast_asia",
          "ID": "southeast_asia", "TH": "southeast_asia", "GB": "uk", "AU": "oceania", "NZ": "oceania", "NG": "africa", "KE": "africa",
          "ZA": "africa", "ET": "africa", "SD": "africa"}


def pick_anchor(country):
    """Region is a preference: the first ready anchor whose affinity matches the story's region, else the first ready one."""
    ready = [a for a in registry() if a.get("status") == "ready"]
    want = REGION.get((country or "").upper(), "europe")
    return next((a["id"] for a in ready if want in (a.get("affinity") or [])), ready[0]["id"])


@app.post("/api/projects")
def create(body: dict = Body(...), u=Depends(user)):
    kind, text = body.get("kind"), str(body.get("text") or "").strip()
    seconds = int(body.get("seconds") or store.prefs(u["id"])["defaults"]["length"])
    if not 20 <= seconds <= 600:
        raise HTTPException(400, "Choose a length between 20 seconds and 10 minutes.")
    url, place, headline = str(body.get("url") or "").strip(), "", ""
    if kind == "pick":
        pick, text = find_pick(str(body.get("pickId") or ""), u["workspaceId"])
        if not pick:
            raise HTTPException(404, "That story is no longer in today's selection.")
        url, place, headline = pick["url"], pick["place"], pick["headline"]
    elif kind == "link":
        if not re.match(r"https?://", url):
            raise HTTPException(400, "That is not a link. Paste a link starting with http, or the article text.")
    elif kind in ("text", "file"):
        if len(text.split()) < 40:
            raise HTTPException(400, "That looks too short to be an article. Paste the full text or a link.")
    else:
        raise HTTPException(400, "Unknown source.")
    fmt = body.get("format") or store.prefs(u["id"])["defaults"]["format"]
    if fmt not in FORMATS:
        raise HTTPException(400, "Unknown format.")
    name = str(body.get("name") or "")
    headline = headline or (re.sub(r"\.(pdf|docx?|txt)$", "", name, flags=re.I).replace("_", " ") if name else
                            text.split("\n")[0][:90] if text else url.rstrip("/").rsplit("/", 1)[-1].replace("-", " ")[:90])
    site = ("DNL selection" if not pick.get("own") else source_site(url, pick)) if kind == "pick" else (re.sub(r"^www\.", "", url.split("/")[2]) if url else None)
    p = make_project(headline or "New story", {"kind": "link" if kind == "pick" else kind, "url": url or None, "name": name or None,
                                               "site": site, "text": text}, seconds, place, fmt, u["workspaceId"], u["id"],
                     {"_pick": pick["id"]} if kind == "pick" else {})
    spawn(p["id"], "write")
    return view(store.read(p["id"]))


def make_project(headline, source, seconds, place, fmt, ws, uid, extra):
    return store.create({"headline": headline, "source": source, "targetSeconds": seconds, "anchorId": pick_anchor(place),
                         "tone": "Serious", "stage": "script", "format": fmt, "versions": {"anchor_vo": [], "anchor_only": [], "vo_only": []},
                         "_place": place, "lt": {"kicker": "", "headline": "", "subline": ""}, "ticker": [], "facts": [], "visuals": {},
                         "_workspace": ws, "_by": uid, **extra})


# ------------------------------------------------------------------ daily run, phase 1 (DNL): picks -> checked footage, by 18:00

def daily_start(only=None):
    """Today's main picks become 1-minute stories: VO only first, the script approved by itself once written, then
    voices, footage search and clip check as usual. After the check the worker keeps it VO only or gives it an anchor
    (store.text_share). Editors take over on the footage page. Once a day (marker daily/<date>.json) when today's
    selection exists; `only` (pick ids, reserves too) starts just those, any time, from the newest selection (a manual run)."""
    day = store.now().strftime("%Y-%m-%d")
    mark = store.DATA / "daily" / f"{day}.json"
    if only is None and (mark.exists() or not (store.DATA / "selection" / f"{day}.json").exists()):
        made = {p.get("_pick") for p in store.all_projects("dnl")}    # the desk's own picks never wait for DNL's selection
        return [start_pick(x, x["text"], x["by"], day) for x in own_picks("dnl") if x["id"] not in made]
    owner = next((x for x in store.users() if x.get("workspaceId") == "dnl" and x.get("role") == "admin"), None) or \
        next(x for x in store.users() if x.get("workspaceId") == "dnl")
    made = {p.get("_pick") for p in store.all_projects("dnl")}
    picks, bodies = selection()
    own = own_picks("dnl")
    bodies.update({x["id"]: x["text"] for x in own})
    started = []
    for x in picks + own:
        if x["id"] in made or (x["id"] not in only if only is not None else x.get("reserve")):   # by hand: any pick
            continue
        started.append(start_pick(x, bodies[x["id"]], x.get("by") or owner["id"], day))
    if only is None:
        mark.parent.mkdir(parents=True, exist_ok=True)
        mark.write_text(json.dumps({"at": store.stamp(), "projects": started}))
    return started


def start_pick(x, text, uid, day):
    """A pick becomes a daily-run story: 1-minute VO only, its script approved by itself once written; then voices,
    footage search and clip check; editors take over on the footage page and it renders overnight like the rest."""
    p = make_project(x["headline"], {"kind": "text" if x.get("own") and text else "link", "url": x["url"] or None, "name": x.get("name"),
                                     "site": source_site(x["url"], x), "text": text},
                     60, x["place"], "vo_only", "dnl", uid,
                     {"_pick": x["id"], "_daily": day, "_autoApprove": True,
                      "formatWhy": {"by": "auto", "text": "Daily run: starts with no anchor; the footage check decides.", "at": store.stamp()}})
    spawn(p["id"], "write")
    return p["id"]


def source_site(url, pick):
    if not pick.get("own"):
        return "DNL selection"
    return re.sub(r"^www\.", "", url.split("/")[2]) if url else "Added by an editor"


# ------------------------------------------------------------------ the desk's own picks (2026-11-28)
# An editor adds a story of their own to today's picks (a link, pasted text or a file). It runs through the daily
# pipeline like DNL's picks: added before the daily run (08:00) it waits and starts with it; added later it starts
# at once. Stored per pick in DATA/own_picks/<id>.json; a pick is today's only (the day it was added, IST).

def own_picks(ws):
    d, day = store.DATA / "own_picks", store.now().strftime("%Y-%m-%d")
    out = []
    for f in sorted(d.glob("own-*.json")) if d.exists() else []:
        try:
            x = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if x.get("workspaceId") == ws and x.get("day") == day:
            out.append(x)
    return sorted(out, key=lambda x: x["at"])


def find_pick(pid, ws):
    """(pick, article text) for one of today's picks of this workspace (DNL's or the desk's own), else (None, "")."""
    if store.WORKSPACES[ws]["kind"] == "dnl":
        picks, bodies = selection()
        x = next((x for x in picks if x["id"] == pid), None)
        if x:
            return x, bodies[x["id"]]
    x = next((x for x in own_picks(ws) if x["id"] == pid), None)
    return (x, x["text"]) if x else (None, "")


def daily_done(day):
    """The daily run has started today (its marker), or its time has passed: an own pick added now starts at once."""
    return (store.DATA / "daily" / f"{day}.json").exists() or store.now().strftime("%H:%M") >= os.environ.get("RIGVIDEO_DAILY_AT", "08:00")


def view_pick(x):
    waits = not daily_done(x["day"])
    return {k: x[k] for k in ("id", "headline", "deck", "type", "place", "source", "url", "publishedAt")} | \
        {"own": True, "addedBy": x["byName"], **({"waiting": f"Starts with the daily run at {os.environ.get('RIGVIDEO_DAILY_AT', '08:00')} IST"} if waits else {})}


def add_own_pick(kind, text, url, name, u):
    if store.WORKSPACES[u["workspaceId"]]["kind"] != "dnl":
        raise HTTPException(400, "Picks are part of the DNL daily run. Use New video instead.")
    text, url = text.strip(), url.strip()
    if kind == "link":
        if not re.match(r"https?://", url):
            raise HTTPException(400, "That is not a link. Paste a link starting with http, or the article text.")
    elif kind in ("text", "file"):
        if len(text.split()) < 40:
            raise HTTPException(400, "That looks too short to be an article. Paste the full text or a link.")
    else:
        raise HTTPException(400, "Unknown source.")
    if any(x["url"] and x["url"] == url for x in own_picks(u["workspaceId"])):
        raise HTTPException(409, "That link is already in today's picks.")
    day = store.now().strftime("%Y-%m-%d")
    headline = (re.sub(r"\.(pdf|docx?|txt|md)$", "", name, flags=re.I).replace("_", " ") if name else
                text.split("\n")[0][:90] if text else url.rstrip("/").rsplit("/", 1)[-1].replace("-", " ")[:90]) or "Your story"
    x = {"id": "own-" + secrets.token_hex(4), "own": True, "workspaceId": u["workspaceId"], "day": day, "at": store.stamp(), "by": u["id"],
         "byName": u.get("name") or u.get("email") or "an editor", "kind": kind, "headline": headline,
         "deck": " ".join(text.split()[:40]) if text else url, "type": "", "place": "", "url": url,
         "source": "Added by " + (u.get("name") or u.get("email") or "an editor"), "publishedAt": store.stamp(), "name": name or None,
         "text": text[:40000]}
    d = store.DATA / "own_picks"
    d.mkdir(parents=True, exist_ok=True)
    store._write(d / f"{x['id']}.json", x)
    started = None
    if daily_done(day):                                             # after 08:00: into the pipeline now
        started = start_pick(x, x["text"], u["id"], day)
    return {"pick": view_pick(x), "started": started}


@app.post("/api/picks")
def add_pick(body: dict = Body(...), u=Depends(user)):
    """Desk: add a story of your own to today's picks ({kind: link|text, url|text})."""
    return add_own_pick(str(body.get("kind") or ""), str(body.get("text") or ""), str(body.get("url") or ""), "", u)


@app.post("/api/picks/file")
def add_pick_file(file: UploadFile = File(...), u=Depends(user)):
    data = file.file.read(20 * 2 ** 20 + 1)
    if len(data) > 20 * 2 ** 20:
        raise HTTPException(413, "That file is over 20 MB.")
    text = re.sub(r"[ \t]+", " ", file_text(file.filename or "", data)).strip()[:40000]
    return add_own_pick("file", text, "", file.filename or "", u)


@app.delete("/api/picks/{pick}")
def remove_pick(pick: str, u=Depends(user)):
    """Take an own pick off today's picks (for everyone) before it has become a story."""
    x = next((x for x in own_picks(u["workspaceId"]) if x["id"] == pick), None)
    if not x:
        raise HTTPException(404, "No such pick.")
    if any(p.get("_pick") == pick for p in store.all_projects(u["workspaceId"])):
        raise HTTPException(409, "That pick is already a story. Discard the story instead.")
    (store.DATA / "own_picks" / f"{pick}.json").unlink()
    return {"ok": True}


@app.post("/api/daily/start")
def daily_start_now(body: dict = Body(default={}), u=Depends(user)):
    """Start the daily run by hand for the given picks (DNL workspace)."""
    if store.WORKSPACES[u["workspaceId"]]["kind"] != "dnl" or not body.get("pickIds"):
        raise HTTPException(400, "Give the pick ids (DNL workspace).")
    return {"started": daily_start([str(x) for x in body["pickIds"]])}


def file_text(name, data):
    """The words of a .txt/.md, .docx (stdlib zip+xml) or .pdf (pypdf) source."""
    ext = pathlib.Path(name).suffix.lower()
    if ext in (".txt", ".md"):
        return data.decode("utf-8", "replace")
    if ext == ".docx":
        import io, zipfile, xml.etree.ElementTree as ET
        try:
            root = ET.fromstring(zipfile.ZipFile(io.BytesIO(data)).read("word/document.xml"))
        except (zipfile.BadZipFile, KeyError, ET.ParseError):
            raise HTTPException(400, "That Word file could not be read.")
        w = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        return "\n".join("".join(t.text or "" for t in para.iter(w + "t")) for para in root.iter(w + "p"))
    if ext == ".pdf":
        import io, pypdf
        try:
            return "\n".join(pg.extract_text() or "" for pg in pypdf.PdfReader(io.BytesIO(data)).pages)
        except Exception:                                       # pypdf raises many kinds on a broken file
            raise HTTPException(400, "That PDF could not be read.")
    raise HTTPException(400, "Use a PDF, Word (.docx) or text file.")


@app.post("/api/projects/file")
def create_from_file(file: UploadFile = File(...), seconds: int = Form(60), format: str = Form(""), u=Depends(user)):
    data = file.file.read(20 * 2 ** 20 + 1)
    if len(data) > 20 * 2 ** 20:
        raise HTTPException(413, "That file is over 20 MB.")
    text = re.sub(r"[ \t]+", " ", file_text(file.filename or "", data)).strip()[:40000]
    return create({"kind": "file", "name": file.filename, "text": text, "seconds": seconds, "format": format or None}, u)


def busy(p, job):
    return ((p.get("_jobs") or {}).get(job) or {}).get("state") == "running"


@app.put("/api/projects/{pid}")
def save(pid: str, body: dict = Body(...), u=Depends(user)):
    """The site's edits. It owns the words and its choices; the machine owns voices, found footage and renders.
    Lists the machine fills (keywords, uploads, maps) can only lose items here; adding goes through the actions."""
    p = mine(pid, u)
    if busy(p, "write"):
        raise HTTPException(409, "The script is still being written.")
    revoice, write = [], []
    if "format" in body and body["format"] not in FORMATS:
        raise HTTPException(400, "Unknown format.")

    def merge(q):
        for k in ("headline", "targetSeconds", "tone", "format", "facts", "ticker", "lt"):
            if k in body:
                q[k] = body[k]
        q["versions"].setdefault(q["format"], [])
        if body.get("stage") in ("script", "visuals", "review") and q["stage"] in ("script", "visuals", "review"):
            q["stage"] = body["stage"]
        anchor_changed = "anchorId" in body and body["anchorId"] != q["anchorId"]
        if anchor_changed:
            if body["anchorId"] not in {a["id"] for a in registry()}:
                raise HTTPException(400, "No such anchor.")
            q["anchorId"] = body["anchorId"]
        for fmt, secs in (body.get("versions") or {}).items():
            if fmt not in FORMATS:
                continue
            q["versions"].setdefault(fmt, [])
            old = {s["id"]: s for s in q["versions"][fmt]}
            new = []
            for s in secs:
                o = old.get(s["id"], {})
                x = {"id": str(s["id"])[:24], "kind": "vo" if s.get("kind") == "vo" else "anchor", "text": str(s.get("text") or "")}
                for k in ("picture", "search", "cls"):                # VO-only beats: what is on screen, its search, event/archive
                    v = s.get(k, o.get(k))
                    if v is not None:
                        x[k] = str(v)[:300]
                v = o.get("voice")
                if v is None and q["stage"] != "script" and fmt == q["format"]:
                    v = {"state": "making", "takes": [], "pick": None}   # a section added after approval
                if v is not None:
                    v = dict(v)
                    if (s.get("voice") or {}).get("pick") in {t["id"] for t in v.get("takes", [])}:
                        v["pick"] = s["voice"]["pick"]
                    if x["text"] != o.get("text", x["text"]) or x["kind"] != o.get("kind", x["kind"]) or anchor_changed:
                        v.update(state="making", takes=[] if anchor_changed else v.get("takes", []))
                    if v["state"] in ("making", "redoing"):
                        revoice.append(x["id"])
                    x["voice"] = v
                new.append(x)
            q["versions"][fmt] = new
        if q["stage"] != "script":                                  # parts added after approval need a visuals entry too
            for x in q["versions"][q["format"]]:
                q["visuals"].setdefault(x["id"], new_visuals())
        for sid, v in (body.get("visuals") or {}).items():
            have = q["visuals"].get(sid)
            if not have:
                continue
            have["placed"] = v.get("placed", have["placed"])
            for k in ("keywords", "uploads", "maps"):
                keep = {x["id"] for x in v.get(k, have[k])}
                gone = [x["id"] for x in have[k] if x["id"] not in keep]
                if k == "keywords" and gone:
                    q.setdefault("_removedKeywords", {}).setdefault(sid, []).extend(gone)
                have[k] = [x for x in have[k] if x["id"] in keep]
            live = {k["id"] for k in have["keywords"]}
            have["found"] = [f for f in have["found"] if f["keywordId"] in live]
        e = q.get("edit")                                           # VO only: the person's changes to the checker's cuts
        for b in ((body.get("edit") or {}).get("beats") or []) if e and e.get("state") == "ready" else []:
            have = next((x for x in e["beats"] if x["sectionId"] == b.get("sectionId")), None)
            if have is not None and isinstance(b.get("cuts"), list):
                have["cuts"] = [{k: c[k] for k in CUT_KEYS if k in c} for c in b["cuts"] if isinstance(c, dict) and isinstance(c.get("src"), dict)]
                for c in have["cuts"]:
                    if "sound" in c:                                # the foley prompt: plain text, short
                        c["sound"] = " ".join(str(c["sound"] or "").split())[:80]
        if q["stage"] == "script" and not q["versions"][q["format"]] and not busy(q, "write"):
            write.append(1)                                         # switched to a format not written yet
    p = store.update(pid, merge)
    if write:
        spawn(pid, "write")
    if revoice and p["stage"] != "script":
        spawn(pid, "voice")
    if uncut(p):
        spawn_cut(pid)
    return view(p)


def uncut(p):
    """Some placed moment has no clip yet (and did not fail to cut)."""
    found = {f["id"]: f for v in p["visuals"].values() for f in v.get("found", [])}
    for v in p["visuals"].values():
        for x in v.get("placed", []):
            f = x["ref"]["kind"] == "moment" and found.get(x["ref"]["videoId"])
            m = f and x["ref"]["moment"] < len(f["moments"]) and f["moments"][x["ref"]["moment"]]
            if m and not m.get("clip") and not m.get("cutFailed"):
                return True
    return False


CUTTING = {}


def spawn_cut(pid):
    with LOCK:
        pr = CUTTING.get(pid)
        if pr and pr.poll() is None:
            return                                                  # the running one loops until nothing is left
        logf = open(store.pdir(pid) / "log.txt", "a")
        CUTTING[pid] = subprocess.Popen([TOOLS_PY, str(HERE / "worker.py"), "cut", pid], stdout=logf, stderr=subprocess.STDOUT,
                                        cwd=HERE, start_new_session=True)


new_visuals = store.new_visuals


@app.post("/api/projects/{pid}/approve")
def approve(pid: str, u=Depends(user)):
    p = mine(pid, u)
    if busy(p, "write") or not p["versions"][p["format"]]:
        raise HTTPException(409, "Wait until the script is written.")

    store.update(pid, store.approved)
    spawn(pid, "voice")
    spawn(pid, "search")
    return view(store.read(pid))


@app.post("/api/projects/{pid}/switch")
def switch(pid: str, body: dict = Body(...), u=Depends(user)):
    """Footage page: make the story the other type (with anchor = anchor_vo, no anchor = vo_only). A script for that
    type is written if there is none (and approved by itself), then its voices and footage step run."""
    p = mine(pid, u)
    fmt = body.get("format")
    if fmt not in ("vo_only", "anchor_vo") or fmt == p["format"]:
        raise HTTPException(400, "Choose the other type.")
    if p["stage"] in ("render", "done") or busy(p, "write"):
        raise HTTPException(409, "Not while it is being written or rendered.")
    return view(switch_to(pid, fmt, f"Switched by {u.get('name') or u.get('email') or 'an editor'}", "editor"))


def switch_to(pid, fmt, why, by):
    out = {}
    p = store.update(pid, lambda q: out.update(job=store.switched(q, fmt, why, by)))
    if out["job"] == "write":
        spawn(pid, "write")
    else:
        spawn(pid, "voice")
        spawn(pid, "search")
    return p


@app.post("/api/projects/{pid}/retry")
def retry(pid: str, body: dict = Body(...), u=Depends(user)):
    p = mine(pid, u)
    job = body.get("job")
    if job == "check":                                              # VO only: check the story (or one beat) again, any time
        if p["format"] != "vo_only" or p["stage"] == "script" or busy(p, "check"):
            raise HTTPException(409, "The clips can be checked once the script is approved, and not while a check runs.")
        sids = [str(body["sid"])] if body.get("sid") else []
        if sids and sids[0] not in {s["id"] for s in p["versions"]["vo_only"]}:
            raise HTTPException(404, "No such beat.")
        store.update(pid, lambda q: q.setdefault("edit", {"state": "waiting", "flow": "", "beats": []}).update(state="checking", progress=0))
        store.job(pid, job, state=None)
        spawn(pid, job, *sids)
        return view(store.read(pid))
    if job == "write" and p["stage"] == "script" and not p["versions"].get(p["format"]) and not busy(p, "write"):
        spawn(pid, job)                                             # a format whose version was never written
        return view(store.read(pid))
    if ((p.get("_jobs") or {}).get(job) or {}).get("state") != "failed":
        raise HTTPException(409, "Nothing to retry.")
    store.job(pid, job, state=None)
    spawn(pid, job)
    return view(store.read(pid))


@app.post("/api/projects/{pid}/revoice")
def revoice(pid: str, body: dict = Body(...), u=Depends(user)):
    p = mine(pid, u)
    sid = body.get("sid")

    def f(q):
        s = next((s for s in q["versions"][q["format"]] if s["id"] == sid and s.get("voice")), None)
        if not s:
            raise HTTPException(404, "No such part.")
        s["voice"].update(state="redoing", note=str(body.get("note") or "")[:300])
    store.update(p["id"], f)
    spawn(pid, "voice")
    return view(store.read(pid))


REWRITE = """You edit a TV news script for a serious news channel. Rewrite each given section as asked, using ONLY facts
from the SOURCE, the FACTS list (the journalist's own notes; where they differ from the source, they win) and facts the
journalist states in the request. Never add any other fact, number, name, place or claim. Keep the section's job: an
anchor section is read on camera, a VO section is read over footage. Numbers as digits, attribute claims, no questions.
LENGTH: each section has "words" (its length now) and "target" (the length timed to the video). Unless the request is
about length, stay within 10% of "words". When asked to make it shorter or longer, end within 10% of "target" if that
is the asked direction, otherwise change the length by about a quarter. Every section you are given must change.
Return strict JSON: {"sections": [{"id": "...", "text": "..."}]} with only the sections you were given."""


@app.post("/api/projects/{pid}/rewrite")
def rewrite(pid: str, body: dict = Body(...), u=Depends(user)):
    """AI rewrite: proposals per section; the site keeps or rejects each. Runs here (short), on the script model."""
    p = mine(pid, u)
    sys.path.insert(0, str(APPDIR / "pipeline"))
    from orchestrator import common, llm
    import writer
    common.load_env()
    secs = [s for s in p["versions"][p["format"]] if body.get("scope") in ("all", s["id"])]
    ask = ", ".join(str(c) for c in body.get("chips") or []) + (f". {body['note']}" if body.get("note") else "")
    wps = next((a["wordsPerSecond"] for a in anchors() if a["id"] == p["anchorId"]), 2.85)
    _, _, a_words, v_words = writer.plan(p["targetSeconds"], 328 / 24 - 0.7, wps)       # the writer's timed lengths
    facts = "\n".join(f"{f.get('label', '')}: {f.get('value', '')}" for f in p.get("facts") or [])
    have, out = {s["id"]: s["text"] for s in secs}, {}
    for _ in range(2):                                              # one more try for sections that came back unchanged
        todo = [s for s in secs if s["id"] not in out]
        if not todo:
            break
        try:
            with store.gpu("writer"):
                r = writer.ask(REWRITE, f"SOURCE:\nHEADLINE: {p['headline']}\n\n{p['source']['text'][:14000]}\n\nFACTS:\n{facts}"
                               f"\n\nASKED: {ask or 'tighten it'}\n\nSECTIONS:\n" + json.dumps(
                                   [{"id": s["id"], "kind": s["kind"], "text": s["text"], "words": len(s["text"].split()),
                                     "target": a_words if s["kind"] == "anchor" else v_words} for s in todo], ensure_ascii=False),
                               {"type": "object", "required": ["sections"], "properties": {"sections": {"type": "array", "items": {
                                   "type": "object", "required": ["id", "text"], "properties": {"id": {"enum": [s["id"] for s in todo]},
                                                                                             "text": {"type": "string"}}}}}},
                               max_tokens=4000, log=lambda *a: None)
        except (llm.LLMUnavailable, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            if out:
                break
            raise HTTPException(503, "The script model is not answering right now. Try again in a minute.")
        for x in r.get("sections") or []:
            if isinstance(x, dict) and x.get("id") in have and str(x.get("text") or "").strip():
                t = str(x["text"]).strip()
                if t != have[x["id"]]:
                    out[x["id"]] = t
    return out


# ------------------------------------------------------------------ visuals: keywords, uploads, maps

PLACES = []


def named(text, common):
    """Places a text names. Whole capitalised runs ("The New York Fire Department"); their longest 3- or 2-word phrase
    that is a place name (alternate names count: "New York" = New York City) wins, and its words are not tried alone
    (13 Nov: "York" alone gave York, England). Leftover single words match a place's main name. Biggest place first."""
    multi = {n for x in PLACES for n in x[0] if " " in n}
    phrases, singles = [], set()
    for run in re.findall(r"\b[A-Z][a-z]+(?:[ -][A-Z][a-z]+)*\b", text):
        w, used = re.split(r"[ -]", run), set()
        for n in (3, 2):
            for i in range(len(w) - n + 1):
                ph = " ".join(w[i:i + n]).lower()
                if not used & set(range(i, i + n)) and ph in multi:
                    phrases.append(ph)
                    used |= set(range(i, i + n))
        singles |= {x for j, x in enumerate(w) if j not in used}
    singles -= common
    best = {}
    for x in sorted(PLACES, key=lambda x: -x[5]):
        for key in [ph for ph in phrases if ph in x[0]] + ([x[1]] if x[1] in singles else []):
            best.setdefault(key, x)
    seen, out = set(), []
    for x in best.values():
        if x[1] not in seen:
            seen.add(x[1]); out.append(x)
    return out


@app.get("/api/places")
def places(q: str = "", text: str = "", u=Depends(user)):
    """Towns and cities (GeoNames cities15000, rigvideo-data/geo) whose name starts with q, biggest first, for the map
    maker. With text: the places a script names (exact name, capitalised in the text), to start the map with."""
    if not PLACES:
        for line in open(store.DATA / "geo" / "cities15000.txt", encoding="utf-8"):
            c = line.split("\t")
            names = {c[1].lower(), c[2].lower(), *(a.lower() for a in c[3].split(",") if a and a.isascii())}
            PLACES.append((names, c[1], float(c[4]), float(c[5]), c[8], int(c[14] or 0)))
    if text:
        import writer
        return [{"name": n, "lat": la, "lon": lo, "iso": iso} for _, n, la, lo, iso, _ in named(text, writer.COMMON)[:4]]
    q = q.strip().lower()
    if len(q) < 2:
        return []
    main = lambda x: x[1].lower().startswith(q) or x[1].encode("ascii", "ignore").decode().lower().startswith(q)
    hits = sorted((x for x in PLACES if any(n.startswith(q) for n in x[0])), key=lambda x: (not main(x), -x[5]))[:6]
    return [{"name": n, "lat": la, "lon": lo, "iso": iso} for _, n, la, lo, iso, _ in hits]

@app.post("/api/projects/{pid}/keywords")
def add_keyword(pid: str, body: dict = Body(...), u=Depends(user)):
    p = mine(pid, u)
    sid, text = body.get("sid"), str(body.get("text") or "").strip()[:120]
    if sid not in p["visuals"] or not text:
        raise HTTPException(400, "Type a keyword.")
    if any(k["text"].lower() == text.lower() for k in p["visuals"][sid]["keywords"]):
        raise HTTPException(409, "That keyword is already searched.")
    kid = "k" + secrets.token_hex(3)
    store.update(pid, lambda q: q["visuals"][sid]["keywords"].append({"id": kid, "text": text, "reason": "Added by you", "state": "queued",
                                                                      "progress": "Waiting for the search"}))
    spawn_keyword(pid, sid, kid)
    return view(store.read(pid))


def spawn_keyword(pid, sid, kid):
    """Keyword jobs queue behind the search lock in their own processes (several may wait)."""
    logf = open(store.pdir(pid) / "log.txt", "a")
    subprocess.Popen([TOOLS_PY, str(HERE / "worker.py"), "keyword", pid, sid, kid], stdout=logf, stderr=subprocess.STDOUT, cwd=HERE,
                     start_new_session=True)


@app.post("/api/projects/{pid}/keywords/{kid}/research")
def research(pid: str, kid: str, body: dict = Body(...), u=Depends(user)):
    p = mine(pid, u)
    sid = body.get("sid")
    k = next((k for k in (p["visuals"].get(sid) or {}).get("keywords", []) if k["id"] == kid), None)
    if not k:
        raise HTTPException(404, "No such keyword.")
    store.update(pid, lambda q: next(x for x in q["visuals"][sid]["keywords"] if x["id"] == kid).update(state="queued", progress="Searching again"))
    spawn_keyword(pid, sid, kid)
    return view(store.read(pid))


@app.post("/api/projects/{pid}/moments")
def add_moment(pid: str, body: dict = Body(...), u=Depends(user)):
    """A range the user marked on a whole found video -> a moment of that video (an existing one when the range is the
    same), so it is placed, cut and rendered like any other. Returns {"moment": index, "project": view}."""
    mine(pid, u)
    vid = str(body.get("videoId") or "")
    try:
        a, b = round(float(body["start"]), 2), round(float(body["end"]), 2)
    except (KeyError, TypeError, ValueError):
        raise HTTPException(400, "A start and an end are needed.")
    out = {}

    def f(q):
        v = next((x for vs in q["visuals"].values() for x in vs.get("found", []) if x["id"] == vid), None)
        if not v:
            raise HTTPException(404, "No such video.")
        end = min(b, v["duration"] or b)
        if not 0 <= a < end:
            raise HTTPException(400, "The clip must start before it ends, inside the video.")
        i = next((i for i, m in enumerate(v["moments"]) if abs(m["start"] - a) < 0.15 and abs(m["end"] - end) < 0.15), None)
        if i is None:
            v["moments"].append({"start": a, "end": end, "label": "Your clip", "description": "", "score": 0, "custom": True})
            i = len(v["moments"]) - 1
        out["i"] = i
    p = store.update(pid, f)
    return {"moment": out["i"], "project": view(p)}


IMG = {".jpg", ".jpeg", ".png", ".webp"}
VID = {".mp4", ".mov", ".m4v", ".webm"}
MAX_UPLOAD = 500 * 2 ** 20


def save_file(pid, sub, f: UploadFile, allowed):
    ext = pathlib.Path(f.filename or "").suffix.lower()
    if ext not in allowed:
        raise HTTPException(400, "Use a picture (JPG, PNG, WebP) or a video (MP4, MOV, WebM).")
    dst = store.pdir(pid) / "media" / sub / f"{secrets.token_hex(4)}{ext}"
    dst.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with open(dst, "wb") as out:
        while chunk := f.file.read(2 ** 20):
            n += len(chunk)
            if n > MAX_UPLOAD:
                out.close()
                dst.unlink()
                raise HTTPException(413, "That file is over 500 MB.")
            out.write(chunk)
    return dst


def probe_seconds(f):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)], capture_output=True, text=True)
    try:
        return round(float(r.stdout.strip()), 2)
    except ValueError:
        raise HTTPException(400, "That video could not be read.")


@app.post("/api/projects/{pid}/uploads")
def upload(pid: str, sid: str = Form(...), file: UploadFile = File(...), u=Depends(user)):
    p = mine(pid, u)
    if sid not in p["visuals"]:
        raise HTTPException(404, "No such part.")
    dst = save_file(pid, "uploads", file, IMG | VID)
    item = {"id": "up" + secrets.token_hex(3), "src": f"/files/{pid}/{dst.relative_to(store.pdir(pid))}",
            "kind": "video" if dst.suffix in VID else "image", "name": (file.filename or dst.name)[:120]}
    if item["kind"] == "video":
        item["seconds"] = probe_seconds(dst)
    store.update(pid, lambda q: q["visuals"][sid]["uploads"].append(item))
    return item


@app.post("/api/projects/{pid}/maps")
def add_map(pid: str, sid: str = Form(...), title: str = Form(""), file: UploadFile = File(...), u=Depends(user)):
    p = mine(pid, u)
    if sid not in p["visuals"]:
        raise HTTPException(404, "No such part.")
    dst = save_file(pid, "maps", file, IMG)
    item = {"id": "map" + secrets.token_hex(3), "src": f"/files/{pid}/{dst.relative_to(store.pdir(pid))}", "title": title[:120]}
    store.update(pid, lambda q: q["visuals"][sid]["maps"].append(item))
    return item


# ------------------------------------------------------------------ render queue, archive, library

@app.post("/api/projects/{pid}/render")
def render(pid: str, body: dict = Body(default={}), u=Depends(user)):
    p = mine(pid, u)
    secs = p["versions"][p["format"]]
    if any((s.get("voice") or {}).get("state") != "ready" for s in secs):
        raise HTTPException(409, "Wait until every part has its voice.")
    if p["format"] == "vo_only" and (p.get("edit") or {}).get("state") != "ready":
        raise HTTPException(409, "Wait until the edit is checked.")

    def f(q):
        q["stage"], q["_queuedAt"] = "render", store.stamp()
        q["extras"] = {"outro": body.get("outro") is not False}       # the DNL outro after the last part (on unless switched off)
        q["render"] = {"projectId": pid, "state": "queued", "queuePosition": 0, "percent": 0, "etaIso": None}
    store.update(pid, f)
    return view(store.read(pid))


# ------------------------------------------------------------------ VO only: the final video and posting it

@app.post("/api/projects/{pid}/final")
def remake_final(pid: str, u=Depends(user)):
    """Make the final video again; shots that came from the 480p copy are downloaded again."""
    p = mine(pid, u)
    if not store.final_fp(p):
        raise HTTPException(409, "The final video is made once every voice is ready and the edit is checked.")
    if busy(p, "final"):
        raise HTTPException(409, "The final video is being made right now.")
    if not store.in_render_window():
        raise HTTPException(409, "Final videos are made during the night render window (00:00-07:00 IST), not while renders are on hold.")
    store.update(pid, lambda q: q.setdefault("final", {}).update(state="building", progress=0, note="Starting"))
    spawn(pid, "final", "again")
    return view(store.read(pid))


PLATFORMS = ("youtube",)                                            # connected accounts; the others come with their keys


def post_text(p):
    """YouTube title + description; the "Read the full story" line maps the video to its DNL story
    in the CMS (src/lib/youtube/client.ts storyIdOf)."""
    title = p["headline"] if len(p["headline"]) <= 100 else p["headline"][:97].rsplit(" ", 1)[0] + "..."
    link = (p.get("source") or {}).get("url") or ""
    secs = p["versions"].get(p["format"]) or []
    lines = ["Video Bulletin", "", secs[0]["text"] if secs else ""]
    if "/long-read/" in link:
        lines += ["", f"Read the full story: {link}"]
    who = next((a["name"] for a in registry() if a["id"] == p["anchorId"]), None)
    lines += ["", f"Voiced by {who or 'an AI voice'}, an AI-generated voice." if p["format"] == "vo_only" else
              f"Presented by {who or 'an AI anchor'}, an AI-generated news anchor.",
              "The script is written from Democracy News Live's reporting."]
    return title, "\n".join(lines).strip()


@app.get("/api/projects/{pid}/post")
def post_defaults(pid: str, u=Depends(user)):
    p = mine(pid, u)
    title, description = post_text(p)
    return {"platforms": list(PLATFORMS), "title": title, "description": description}


@app.post("/api/projects/{pid}/post")
def post_video(pid: str, body: dict = Body(...), u=Depends(user)):
    """Post the final video (the person pressed Post and confirmed): public on the DNL YouTube channel, like the CMS's
    Approve (it was uploaded unlisted into "Awaiting approval" when its render finished)."""
    p = mine(pid, u)
    if body.get("platform") not in PLATFORMS:
        raise HTTPException(400, "That account is not connected yet.")
    title = str(body.get("title") or "").strip()[:100]
    if not title:
        raise HTTPException(400, "Give it a title.")
    why = can_post(p, body["platform"])
    if why:
        raise HTTPException(409, why)
    queue_post(pid, body["platform"], title, str(body.get("description") or "").strip()[:5000], u.get("email") or u["id"])
    return view(store.read(pid))


def can_post(p, platform):
    """'' when the story's final video can be posted there, else why not."""
    f = store.public(p).get("final") or {}
    if f.get("state") != "ready" or f.get("stale"):
        return "Wait until the final video is made."
    have = (p.get("posts") or {}).get(platform) or {}
    if have.get("state") == "posted":
        return "This video is already posted there."
    if have.get("state") in ("posting", "uploading") or busy(p, "post"):
        return "It is being uploaded right now."
    return ""


def queue_post(pid, platform, title, description, by, upload_only=False, extra=None):
    def f_(q):
        old = (q.get("posts") or {}).get(platform) or {}             # a failed post keeps its upload: never a second one
        keep = {k: old[k] for k in ("videoId", "url", "fp", "sent", "queued", "uploadedAt", "autoAt") if k in old} | (extra or {})
        q.setdefault("posts", {})[platform] = {**keep, "state": "uploading" if upload_only else "posting", "title": title,
                                               "description": description, "by": by, "at": store.stamp(), **({"auto": True} if by == "auto" else {})}
    store.update(pid, f_)
    spawn(pid, "post", platform, *(["upload"] if upload_only else []))


AUTO_PUBLISH_MIN = float(os.environ.get("RIGVIDEO_AUTO_PUBLISH_MIN", "60"))   # anchor-only: public this long after its render


def auto_post(p):
    """Monitor: a story whose render just finished goes up to YouTube unlisted ("Awaiting approval"); an anchor-only one
    goes public AUTO_PUBLISH_MIN after its render unless someone posted it sooner (user 2026-11-24). Finals older than a
    day (made before this existed) are left alone."""
    f = store.public(p).get("final") or {}
    if p.get("stage") != "done" or f.get("state") != "ready" or f.get("stale") or not f.get("builtAt") or busy(p, "post"):
        return
    age = (store.now() - dt.datetime.fromisoformat(f["builtAt"])).total_seconds() / 60
    yt = (p.get("posts") or {}).get("youtube")
    if yt is None and age < 24 * 60:
        title, description = post_text(p)
        at = dt.datetime.fromisoformat(f["builtAt"]) + dt.timedelta(minutes=AUTO_PUBLISH_MIN)
        queue_post(p["id"], "youtube", title, description, "auto", upload_only=True,
                   extra={"autoAt": at.isoformat(timespec="seconds")} if p["format"] == "anchor_only" else None)
    elif yt and yt.get("state") == "awaiting" and p["format"] == "anchor_only" and age >= AUTO_PUBLISH_MIN:
        queue_post(p["id"], "youtube", yt["title"], yt["description"], "auto")


@app.post("/api/post-all")
def post_all(body: dict = Body(...), u=Depends(user)):
    """Desk "Post all": each listed story's final video to YouTube with its default title and description (the same
    checks as one Post). Returns {posted: [ids], skipped: {id: why}}."""
    out = {"posted": [], "skipped": {}}
    for pid in body.get("ids") or []:
        try:
            p = mine(str(pid), u)
        except HTTPException:
            out["skipped"][pid] = "Not found."
            continue
        why = can_post(p, "youtube")
        if why:
            out["skipped"][pid] = why
            continue
        yt = (p.get("posts") or {}).get("youtube") or {}
        title, description = (yt["title"], yt["description"]) if yt.get("title") else post_text(p)
        queue_post(pid, "youtube", title, description, u.get("email") or u["id"])
        out["posted"].append(pid)
    return out


@app.post("/api/projects/{pid}/cancel")
def cancel(pid: str, u=Depends(user)):
    p = mine(pid, u)
    if (p.get("render") or {}).get("state") != "queued":
        raise HTTPException(409, "Only a waiting render can be cancelled.")

    def f(q):
        q["stage"] = "review"
        q.pop("render", None)
    return view(store.update(pid, f))


@app.post("/api/projects/{pid}/moveup")
def move_up(pid: str, u=Depends(user)):
    mine(pid, u)
    q = [p for p in queue() if p["render"]["state"] == "queued"]
    i = next((i for i, p in enumerate(q) if p["id"] == pid), -1)
    if i > 0:                                                       # swap the waiting times of it and the one ahead
        a, b = q[i - 1]["_queuedAt"], q[i]["_queuedAt"]
        store.update(q[i]["id"], lambda x: x.update(_queuedAt=a))
        store.update(q[i - 1]["id"], lambda x: x.update(_queuedAt=b))
    return {"ok": True}


def finished_why(p):
    """'' when a rendered story's video may be thrown away (Remake / Discard), else why not."""
    yt = (p.get("posts") or {}).get("youtube") or {}
    if yt.get("state") in ("posted", "posting"):
        return "This video is public on YouTube. Take it down there first."
    if yt.get("state") == "uploading" or busy(p, "post"):
        return "It is being uploaded right now. Try again in a few minutes."
    return ""


@app.post("/api/projects/{pid}/remake")
def remake(pid: str, body: dict = Body(default={}), u=Depends(user)):
    """A rendered story is opened again: its video is dropped and it goes back to Review to be changed and rendered
    again ({"now": true}: straight back into the render queue as it is). A YouTube upload awaiting approval is left
    there and remembered in _oldPosts; the new video gets its own upload."""
    p = mine(pid, u)
    if p.get("stage") != "done":
        raise HTTPException(409, "Only a rendered story can be made again.")
    if why := finished_why(p):
        raise HTTPException(409, why)

    def f(q):
        q["stage"] = "review"
        for k in ("render", "final", "_library", "videoId"):
            q.pop(k, None)
        if yt := (q.get("posts") or {}).pop("youtube", None):
            q.setdefault("_oldPosts", []).append({**yt, "droppedAt": store.stamp()})
    store.update(pid, f)
    return render(pid, {"outro": (p.get("extras") or {}).get("outro", True)}, u) if body.get("now") else view(store.read(pid))


@app.post("/api/projects/{pid}/archive")
def archive(pid: str, u=Depends(user)):
    p = mine(pid, u)
    if p.get("stage") == "done" and (why := finished_why(p)):
        raise HTTPException(409, why)
    if any(j.get("state") == "running" for j in (p.get("_jobs") or {}).values()):
        raise HTTPException(409, "The machine is working on this story. Wait until it finishes.")
    store.update(pid, lambda q: q.update(_archived=True))
    return {"ok": True}


@app.post("/api/library/{item}/duplicate")
def duplicate(item: str, u=Depends(user)):
    src = mine(item.removeprefix("lib-"), u)
    keep = {k: v for k, v in src.items() if not k.startswith("_") and k not in ("id", "render", "videoId", "createdAt", "updatedAt")}
    keep["versions"] = {f: [{k: s[k] for k in ("id", "kind", "text", "picture", "search", "cls") if k in s} for s in secs]
                        for f, secs in src["versions"].items()}
    keep.pop("edit", None)
    p = store.create({**keep, "headline": f"{src['headline']} (copy)", "stage": "script", "visuals": {},
                      "_workspace": u["workspaceId"], "_by": u["id"], "_search": src.get("_search", {}),
                      **{k: src[k] for k in ("_vo", "_place") if k in src}})
    return view(p)


# ------------------------------------------------------------------ files

@app.get("/files/{pid}/{rel:path}")
def files(pid: str, rel: str, u=Depends(user)):
    mine(pid, u)
    base = store.pdir(pid).resolve()
    f = (base / rel).resolve()
    if base not in f.parents or not f.is_file() or rel.startswith(("footage/", "render/", "voice/")) and "/takes/" not in rel:
        raise HTTPException(404)
    return FileResponse(f)


ANCHOR_SRC = {"face.jpg": ("identity_face", ["-vf", "scale=320:-2", "-q:v", "4"]), "frame.jpg": ("identity_ref", ["-vf", "scale=960:-2", "-q:v", "4"]),
              "voice.mp3": ("voice_file", ["-t", "12", "-b:a", "96k"])}


@app.get("/api/anchors")
def public_anchors():
    """The presenters on offer, for the public landing page (signed-out visitors): name, face, voice sample only."""
    return [{k: a[k] for k in ("id", "name", "gender", "face", "voiceSample", "regions", "offered")} for a in anchors() if a["offered"]]


PUBLIC_MEDIA = ("face.jpg", "voice.mp3")                            # shown on the landing page; frame.jpg needs sign-in


@app.get("/anchor-media/{aid}/{name}")
def anchor_media(request: Request, aid: str, name: str):
    if name not in PUBLIC_MEDIA:
        user(request)
    a = next((a for a in registry() if a["id"] == aid), None)
    if not a or name not in ANCHOR_SRC or not a.get(ANCHOR_SRC[name][0]):
        raise HTTPException(404)
    out = store.DATA / "anchors" / f"{aid}_{name}"
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        key, args = ANCHOR_SRC[name]
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(REG / a[key]), *args, str(out)], check=True)
    return FileResponse(out, headers={"Cache-Control": "max-age=86400"})


if DIST.exists():                                                   # the built site, with client-side routes
    @app.get("/{path:path}")
    def site(path: str):
        f = (DIST / path).resolve()
        return FileResponse(f if path and DIST in f.parents and f.is_file() else DIST / "index.html")
