"""Studio data on disk (trijya-7), shared by the web server and the job workers. Stdlib only.

  <DATA>/projects/<id>/project.json   a Project (web/src/data/types.ts) plus private keys starting with "_"
  <DATA>/projects/<id>/...            its media (voice takes, clips, uploads, render), served as /files/<id>/...
  <DATA>/users.json                   accounts (scrypt hashes); made with `python store.py adduser ...`
  <DATA>/prefs/<user>.json            defaults and hidden picks
  <DATA>/selection/<date>.json        today's DNL picks
Every read-modify-write of a project holds an flock on its folder, so the server and the workers never overwrite
each other."""
import contextlib
import datetime as dt
import fcntl
import hashlib
import hmac
import json
import os
import pathlib
import re
import secrets
import sys

HOME = pathlib.Path.home()
DATA = pathlib.Path(os.environ.get("STUDIO_DATA", HOME / "anchor-studio" / "rigvideo-data"))
PROJECTS = DATA / "projects"
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
WORKSPACES = {"dnl": {"id": "dnl", "name": "DNL", "kind": "dnl", "picksFeed": True}}


def now():
    return dt.datetime.now(IST)


def stamp():
    return now().isoformat(timespec="seconds")


def pdir(pid):
    if not re.fullmatch(r"[a-z0-9-]{3,60}", pid or ""):
        raise KeyError(pid)
    return PROJECTS / pid


@contextlib.contextmanager
def _lock(path, shared=False):
    """shared: many holders at once (footage searches, clip checks), all kept out while one exclusive holder (a render) runs."""
    with open(path, "a+") as f:
        fcntl.flock(f, fcntl.LOCK_SH if shared else fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _write(f, data):
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False))
    os.replace(tmp, f)


def read(pid):
    d = pdir(pid)
    if not (d / "project.json").exists():
        raise KeyError(pid)
    with _lock(d / ".lock"):
        return json.loads((d / "project.json").read_text())


def update(pid, f):
    """f(project) mutates it in place under the lock; returns the saved project."""
    d = pdir(pid)
    with _lock(d / ".lock"):
        p = json.loads((d / "project.json").read_text())
        f(p)
        p["updatedAt"] = stamp()
        _write(d / "project.json", p)
        return p


def job(pid, kind, **fields):
    """Merge fields into the project's running job of this kind (write, voice, search, render); None removes it."""
    def f(p):
        jobs = p.setdefault("_jobs", {})
        if fields.get("state") is None and "state" in fields:
            jobs.pop(kind, None)
        else:
            jobs[kind] = {**jobs.get(kind, {}), **fields}
    return update(pid, f)


# ---------------------------------------------------------------- trijya-3's GPU: the script model and the voice model take turns

T3 = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20", "-i", os.environ.get("ANCHOR_VOICE_KEY", str(HOME / ".ssh" / "to_trijya3")),
      os.environ.get("ANCHOR_VOICE_HOST", "trijya-3@100.99.155.88")]


@contextlib.contextmanager
def gpu(use):
    """Hold t3's GPU for "writer" (shared: scripts run side by side) or "voice" (exclusive: waits for running scripts).
    ~/rigvideo/llm/gpu.sh on t3 loads the asked model and unloads the other.
    ponytail: a steady stream of scripts can keep voice waiting; add a turn queue if that ever happens."""
    import subprocess
    DATA.mkdir(parents=True, exist_ok=True)
    with open(DATA / "t3gpu.lock", "a+") as f:
        fcntl.flock(f, fcntl.LOCK_SH if use == "writer" else fcntl.LOCK_EX)
        try:
            subprocess.run(T3 + [f"~/rigvideo/llm/gpu.sh {use}"], check=True, timeout=900, capture_output=True)
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def slug(text):
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return "-".join(s.split("-")[:5])[:40].strip("-") or "story"


def create(p):
    PROJECTS.mkdir(parents=True, exist_ok=True)
    p["id"] = f"{slug(p.get('headline'))}-{secrets.token_hex(2)}"
    d = PROJECTS / p["id"]
    d.mkdir(parents=True)
    p["createdAt"] = p["updatedAt"] = stamp()
    _write(d / "project.json", p)
    return p


def all_projects(workspace=None):
    out = []
    for d in PROJECTS.iterdir() if PROJECTS.exists() else []:
        try:
            p = json.loads((d / "project.json").read_text())
        except (OSError, json.JSONDecodeError):
            continue                                                # mid-write: the next poll has it
        if workspace is None or p.get("_workspace") == workspace:
            out.append(p)
    return sorted(out, key=lambda p: p.get("createdAt", ""), reverse=True)


def new_visuals():
    return {"keywords": [], "found": [], "photos": [], "uploads": [], "maps": [], "placed": []}


def approved(q):
    """Script approved (mutates the project): the footage page opens; voices and the footage step start (caller spawns
    voice + search)."""
    q["stage"] = "visuals"
    if q["format"] == "vo_only":
        q["edit"] = {"state": "waiting", "flow": "", "beats": []}     # the clip check runs after the search and the voices
    for s in q["versions"][q["format"]]:
        if not s.get("voice") or s["voice"]["state"] != "ready":
            s["voice"] = {"state": "making", "takes": [], "pick": None}
        q["visuals"].setdefault(s["id"], new_visuals())


def switched(q, fmt, why, by):
    """Change a story's format (mutates). Returns the job to start: "write" when that format has no script yet (it is
    approved by itself once written), else "approved" (voices + footage step for it)."""
    q["format"], q["formatWhy"] = fmt, {"by": by, "text": why, "at": stamp()}
    q.pop("render", None)
    if not q["versions"].get(fmt):
        q["stage"], q["_autoApprove"] = "script", True
        return "write"
    approved(q)
    return "approved"


def text_share(p):
    """VO only, checked edit: (share of cuts that are text shots, beats whose pictures run out). The daily run keeps
    a story VO-only when text shots <= 35% and no beat is short; else it gets an anchor."""
    beats = (p.get("edit") or {}).get("beats") or []
    cuts = [c for b in beats for c in b["cuts"]]
    short = [b["sectionId"] for b in beats if not b["cuts"] or sum(c["secs"] for c in b["cuts"]) < b["secs"] - 0.25]
    return (sum(c["kind"] == "post_or_document" for c in cuts) / max(1, len(cuts))), short


def in_render_window(t=None):
    """Renders (anchor and VO final) start only inside RIGVIDEO_RENDER_WINDOW (IST, default 00:00-07:00)."""
    a, b = (dt.time.fromisoformat(x) for x in os.environ.get("RIGVIDEO_RENDER_WINDOW", "00:00-07:00").split("-"))
    t = (t or now()).time()
    return a <= t < b if a < b else t >= a or t < b


def final_fp(p):
    """VO only: what the final 9:16 video is made of (every cut and every picked voice). A different value = the video
    on Review is out of date and is made again. None while there is nothing to make."""
    e = p.get("edit") or {}
    if p.get("format") != "vo_only" or e.get("state") != "ready" or not e.get("beats"):
        return None
    secs = p["versions"]["vo_only"]
    if any((s.get("voice") or {}).get("state") != "ready" for s in secs):
        return None
    parts = [[b["sectionId"], b["secs"], [[c["src"].get("youtubeId"), c["src"].get("start"), c["secs"], c["kind"]] + ([c["sound"]] if "sound" in c else [])
              for c in b["cuts"]]]
             for b in e["beats"]] + [s["voice"]["pick"] for s in secs]
    return hashlib.sha1(json.dumps(parts).encode()).hexdigest()[:12]


def public(p):
    """What the site sees: the Project without private keys. VO only: `final.stale` when the edit or a voice changed
    since the final video was made."""
    out = {k: v for k, v in p.items() if not k.startswith("_")}
    lib = p.get("_library")
    if lib and not out.get("final"):                              # an anchor video finished before finals were recorded
        out["final"] = {"state": "ready", "video": lib["video"], "poster": lib["poster"], "seconds": lib["seconds"]}
    if out.get("final"):
        out["final"] = {**out["final"], "stale": out["final"].get("fp") != final_fp(p)}
    return out


# ---------------------------------------------------------------- users and sessions

def users():
    try:
        return json.loads((DATA / "users.json").read_text())
    except (OSError, json.JSONDecodeError):
        return []


def _hash(password, salt):
    return hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2 ** 14, r=8, p=1).hex()


def check_password(email, password):
    u = next((u for u in users() if u["email"] == email.strip().lower()), None)
    if u and hmac.compare_digest(u["hash"], _hash(password, u["salt"])):
        return u
    return None


def _secret():
    f = DATA / "session.key"
    if not f.exists():
        DATA.mkdir(parents=True, exist_ok=True)
        f.write_text(secrets.token_hex(32))
        f.chmod(0o600)
    return f.read_text().strip().encode()


def session_token(uid):
    exp = int(now().timestamp()) + 30 * 86400
    msg = f"{uid}.{exp}"
    return msg + "." + hmac.new(_secret(), msg.encode(), "sha256").hexdigest()


def session_user(token):
    try:
        uid, exp, sig = (token or "").rsplit(".", 2)
    except ValueError:
        return None
    good = hmac.new(_secret(), f"{uid}.{exp}".encode(), "sha256").hexdigest()
    if not hmac.compare_digest(sig, good) or int(exp) < now().timestamp():
        return None
    return next((u for u in users() if u["id"] == uid), None)


def prefs(uid):
    try:
        return json.loads((DATA / "prefs" / f"{uid}.json").read_text())
    except (OSError, json.JSONDecodeError):
        return {"defaults": {"format": "anchor_vo", "length": 60, "captions": "file", "aiLabel": True, "outro": True}, "hiddenPicks": []}


def save_prefs(uid, data):
    (DATA / "prefs").mkdir(parents=True, exist_ok=True)
    _write(DATA / "prefs" / f"{uid}.json", data)


def adduser(email, name, role, workspace, password):
    """Pre-made accounts (no sign-up yet): python store.py adduser <email> <name> <admin|editor> <workspace> (password on stdin)."""
    us = [u for u in users() if u["email"] != email.lower()]
    salt = secrets.token_hex(16)
    us.append({"id": "u" + secrets.token_hex(4), "email": email.lower(), "name": name, "role": role, "workspaceId": workspace,
               "salt": salt, "hash": _hash(password, salt)})
    DATA.mkdir(parents=True, exist_ok=True)
    _write(DATA / "users.json", us)
    (DATA / "users.json").chmod(0o600)


if __name__ == "__main__":
    if sys.argv[1:2] == ["adduser"]:
        adduser(*sys.argv[2:6], sys.stdin.readline().rstrip("\n"))
        print("ok")
    else:                                                           # self-check of sessions and passwords
        DATA = pathlib.Path(os.environ.get("TMPDIR", "/tmp")) / f"store-check-{secrets.token_hex(3)}"
        PROJECTS = DATA / "projects"
        adduser("a@b.c", "A", "admin", "dnl", "pw one")
        assert check_password("A@B.C ", "pw one") and not check_password("a@b.c", "pw two")
        uid = users()[0]["id"]
        assert session_user(session_token(uid))["id"] == uid
        t = session_token(uid)
        assert session_user(t[:-1] + ("1" if t[-1] == "0" else "0")) is None and session_user("x") is None
        p = create({"headline": "Floods hit Nepal", "_workspace": "dnl"})
        update(p["id"], lambda q: q.update(stage="script"))
        job(p["id"], "write", state="running", progress=0.5)
        assert read(p["id"])["_jobs"]["write"]["progress"] == 0.5
        job(p["id"], "write", state=None)
        assert "write" not in read(p["id"])["_jobs"] and "_jobs" not in public(read(p["id"]))
        T = lambda h: dt.datetime(2026, 11, 23, h, 30, tzinfo=IST)
        assert in_render_window(T(0)) and in_render_window(T(6)) and not in_render_window(T(7)) and not in_render_window(T(23))
        c = lambda k, s=3.0: {"kind": k, "secs": s}
        e = {"format": "vo_only", "edit": {"beats": [{"sectionId": "b1", "secs": 6.0, "cuts": [c("footage"), c("post_or_document")]},
                                                     {"sectionId": "b2", "secs": 7.0, "cuts": [c("footage"), c("footage")]}]}}
        assert text_share(e) == (0.25, ["b2"])
        q = {"format": "vo_only", "versions": {"vo_only": [{"id": "b1"}], "anchor_vo": []}, "visuals": {}, "stage": "visuals"}
        assert switched(q, "anchor_vo", "why", "auto") == "write" and q["stage"] == "script" and q["_autoApprove"]
        q["versions"]["anchor_vo"] = [{"id": "s1"}]
        assert switched(q, "vo_only", "back", "editor") == "approved" and q["stage"] == "visuals" and q["formatWhy"]["by"] == "editor"
        print("store ok")
