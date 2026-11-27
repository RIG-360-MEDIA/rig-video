"""Shared setup for the regression suite (pytest, run from the repo root: `pytest tests`).

Every test gets its own empty data folder, so tests never see each other's stories and never touch real data.
The API runs in-process (FastAPI's TestClient); it never starts the job loop. Machine jobs (write, voice, search,
render, post...) are NOT run: `spawned` records which job the API asked for, so a test checks the decision, not the GPU.
Nothing here reaches trijya-3/7/8, YouTube, an LLM or the RIG database. See docs/TESTING.md."""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import types

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
# A throwaway HOME: the code under test can never read this machine's keys (~/.config, ~/.ssh) or real data.
os.environ["HOME"] = tempfile.mkdtemp(prefix="rv-home-")
os.environ.setdefault("STUDIO_DATA", tempfile.mkdtemp(prefix="rv-tests-"))
for k in [k for k in os.environ if k.endswith(("_API_KEY", "_KEY", "_TOKEN", "_DB_URL")) or k.startswith(("GROQ", "LLM_"))]:
    del os.environ[k]
os.environ["RIGVIDEO_APP"] = str(ROOT / "studio-app")
os.environ["RIGVIDEO_NO_SELECTION"] = "1"
os.environ.pop("RIGVIDEO_DAILY_AUTO", None)
os.environ.pop("RIGVIDEO_RENDER_WINDOW", None)
for p in (ROOT / "server", ROOT / "studio-app" / "pipeline"):
    sys.path.insert(0, str(p))

import app as api  # noqa: E402
import store  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

PASSWORD = "test password 1"


class NoRealProcess(AssertionError):
    pass


def _refuse(*a, **k):
    raise NoRealProcess(f"a test tried to start a real process: {a[0] if a else k}")


@pytest.fixture(autouse=True)
def studio_data(tmp_path, monkeypatch):
    """A fresh, empty studio data folder for each test; module state the API keeps in memory is cleared."""
    monkeypatch.setattr(store, "DATA", tmp_path)
    monkeypatch.setattr(store, "PROJECTS", tmp_path / "projects")
    monkeypatch.setattr(store, "WORKSPACES", {"dnl": {"id": "dnl", "name": "DNL", "kind": "dnl", "picksFeed": True},
                                              "other": {"id": "other", "name": "Other", "kind": "newsroom", "picksFeed": False}})
    monkeypatch.setattr(api, "FAILS", {})
    monkeypatch.setattr(api, "RUNNING", {})
    # the API's own clock only (the 1 s pause after a wrong password); other code keeps the real time module
    monkeypatch.setattr(api, "time", types.SimpleNamespace(sleep=lambda s: None, time=time.time))
    monkeypatch.setattr(api.subprocess, "Popen", _refuse)          # nothing may start a real worker / ffmpeg
    monkeypatch.setattr(api.subprocess, "run", _refuse)
    store.PROJECTS.mkdir(parents=True)
    return tmp_path


@pytest.fixture(autouse=True)
def spawned(monkeypatch):
    """Every machine job the API starts, as (story id, job, args), in order."""
    calls = []
    monkeypatch.setattr(api, "spawn", lambda pid, job, *a: calls.append((pid, job, a)))
    monkeypatch.setattr(api, "spawn_cut", lambda pid: calls.append((pid, "cut", ())))
    monkeypatch.setattr(api, "spawn_keyword", lambda pid, sid, kid: calls.append((pid, "keyword", (sid, kid))))
    return calls


def jobs(calls, pid=None):
    return [c[1] for c in calls if pid is None or c[0] == pid]


# ------------------------------------------------------------------ people

def make_user(email="ed@rig.test", role="editor", workspace="dnl", name="Ed"):
    store.adduser(email, name, role, workspace, PASSWORD)
    return next(u for u in store.users() if u["email"] == email)


@pytest.fixture
def client():
    """A browser with nobody signed in."""
    return TestClient(api.app)


def signed_in(email="ed@rig.test", role="editor", workspace="dnl"):
    """A browser signed in through the real /api/login."""
    if not any(u["email"] == email for u in store.users()):
        make_user(email, role, workspace)
    c = TestClient(api.app)
    r = c.post("/api/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return c


@pytest.fixture
def ed():
    return signed_in()


@pytest.fixture
def outsider():
    """Someone signed in to another workspace: must never see or change a DNL story."""
    return signed_in("out@other.test", "admin", "other")


# ------------------------------------------------------------------ stories, built the way the real code builds them

ARTICLE = ("Floods hit the Kathmandu valley on Monday after three days of heavy rain, officials said. At least 42 people "
           "have died and 1,200 homes were damaged, according to the Nepal Home Ministry. Rescue teams from the army "
           "and police are searching for people trapped in Lalitpur and Bhaktapur. The government has opened 18 "
           "shelters and asked residents near rivers to move to higher ground. Weather officials warned that more rain "
           "is expected through Thursday. Schools in the valley will stay closed for the rest of the week.")


def new_story(fmt="vo_only", user_id="u0", workspace="dnl", headline="Floods hit Kathmandu valley", **extra):
    return api.make_project(headline, {"kind": "text", "url": None, "name": None, "site": None, "text": ARTICLE},
                            60, "NP", fmt, workspace, user_id, extra)


def sections(fmt, voice="ready"):
    v = (lambda i: {"state": voice, "takes": [{"id": f"t{i}"}], "pick": f"t{i}"}) if voice else (lambda i: None)
    if fmt == "vo_only":
        out = [{"id": f"b{i}", "kind": "vo", "text": f"Beat {i} line.", "picture": "flood water", "search": "Kathmandu floods",
                "cls": "event", "voice": v(i)} for i in (1, 2, 3)]
    else:
        out = [{"id": k, "kind": "anchor" if k[0] == "a" else "vo", "text": f"{k} line.", "voice": v(i)}
               for i, k in enumerate(("a1", "v1", "a2"))]
    return [{k: x for k, x in s.items() if x is not None} for s in out]


def edit_ready(sids):
    return {"state": "ready", "flow": "", "beats": [{"sectionId": s, "secs": 6.0, "cuts": [
        {"id": f"c{s}", "src": {"youtubeId": "yt1", "start": 1.0}, "secs": 6.0, "kind": "footage", "sound": "rain"}]} for s in sids]}


def at_stage(stage, fmt="vo_only", **extra):
    """A story as the real flow leaves it at `stage` (script written / approved / reviewed / queued / done)."""
    p = new_story(fmt, **extra)
    pid = p["id"]

    def f(q):
        secs = sections(fmt, voice=None if stage == "script" else "ready")
        q["versions"][fmt] = secs
        if fmt != "vo_only":
            q["versions"]["anchor_only"] = [dict(s, kind="anchor") for s in secs]
        if stage == "script":
            return
        store.approved(q)
        for s in q["versions"][fmt]:
            s["voice"] = {"state": "ready", "takes": [{"id": "t1"}], "pick": "t1"}
        if fmt == "vo_only":
            q["edit"] = edit_ready([s["id"] for s in q["versions"][fmt]])
        q["stage"] = "review" if stage in ("review", "render", "done") else "visuals"
        if stage in ("render", "done"):
            q["stage"], q["_queuedAt"], q["extras"] = "render", store.stamp(), {"outro": True}
            q["render"] = {"projectId": pid, "state": "queued", "queuePosition": 0, "percent": 0, "etaIso": None}
        if stage == "done":
            q["stage"] = "done"
            q["render"] = {"state": "done"}
            q["final"] = {"state": "ready", "video": f"/files/{pid}/final.mp4", "poster": "", "seconds": 60,
                          "fp": store.final_fp(q), "builtAt": store.stamp()}
            q["videoId"] = "lib-" + pid
            q["_library"] = {"id": "lib-" + pid, "projectId": pid, "headline": q["headline"], "anchorId": q["anchorId"],   # as worker.py makes it
                             "madeAt": store.stamp(), "video": q["final"]["video"], "poster": "", "seconds": 60, "origin": "studio"}
    store.update(pid, f)
    return store.read(pid)


def write_selection(picks, reserves=(), day=None):
    """A selection file like worker.py selection writes (only the fields the API reads)."""
    day = day or store.now().strftime("%Y-%m-%d")
    d = store.DATA / "selection"
    d.mkdir(parents=True, exist_ok=True)
    row = lambda i, h: {"event_id": f"{i:08d}-aaaa-bbbb-cccc-dddddddddddd", "headline": h, "deck": "d", "body": ARTICLE,
                        "label": {"category": "death_disaster", "country": "NP"}, "sources": 12, "age_h": 2}
    sel = {"picks": [row(i, h) for i, h in enumerate(picks, 1)],
           "reserves": [row(100 + i, h) for i, h in enumerate(reserves, 1)]}
    (d / f"{day}.json").write_text(json.dumps(sel))
    return [r["event_id"][:8] for r in sel["picks"]], [r["event_id"][:8] for r in sel["reserves"]]


@pytest.fixture(autouse=True, scope="session")
def nothing_leaks_outside_test_folders():
    """Proof of isolation: no test may write into the shared default data folder."""
    yield
    leaked = list(pathlib.Path(os.environ["STUDIO_DATA"]).rglob("project.json"))
    assert not leaked, f"a test wrote outside its own folder: {leaked[:3]}"
