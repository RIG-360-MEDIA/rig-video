"""Check: Remake sends a rendered story back to Review without its video (or straight into the queue with now) and keeps a
YouTube upload awaiting approval in _oldPosts; Remake and Discard refuse a video that is public; a discarded story leaves
the library. python test_remake.py (API venv)"""
import json, os, sys, tempfile
os.environ["STUDIO_DATA"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fastapi import HTTPException
import app, store

U = {"id": "u", "workspaceId": "dnl"}
app.view = lambda p: p


def mk(pid, yt=None):
    d = store.PROJECTS / pid
    d.mkdir(parents=True, exist_ok=True)
    ready = {"voice": {"state": "ready"}}
    p = {"id": pid, "_workspace": "dnl", "stage": "done", "format": "anchor_vo", "versions": {"anchor_vo": [ready]}, "_jobs": {},
         "render": {"state": "done"}, "final": {"state": "ready", "video": "v"}, "videoId": "lib-" + pid,
         "_library": {"id": "lib-" + pid, "madeAt": "2026-11-26T01:00:00"}, "extras": {"outro": False}, "posts": {"youtube": yt} if yt else {}}
    (d / "project.json").write_text(json.dumps(p))


def code(f, *a):
    try:
        f(*a)
        return 200
    except HTTPException as e:
        return e.status_code


mk("aaa", {"state": "awaiting", "videoId": "Y1"})
app.remake("aaa", {}, U)
a = store.read("aaa")
assert a["stage"] == "review" and not {"render", "final", "_library", "videoId"} & a.keys() and "youtube" not in a["posts"], a
assert a["_oldPosts"][0]["videoId"] == "Y1"
assert code(app.remake, "aaa", {}, U) == 409                                   # not rendered any more

mk("bbb")
app.remake("bbb", {"now": True}, U)
b = store.read("bbb")
assert b["stage"] == "render" and b["render"]["state"] == "queued" and b["extras"]["outro"] is False

mk("ccc", {"state": "posted", "videoId": "Y2"})
assert code(app.remake, "ccc", {}, U) == 409 and code(app.archive, "ccc", U) == 409

mk("ddd", {"state": "awaiting", "videoId": "Y3"})
assert code(app.archive, "ddd", U) == 200 and store.read("ddd")["_archived"]
print("ok")
