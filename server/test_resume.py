"""Check: a job cut off by a machine restart starts again by itself (at most RIGVIDEO_AUTO_RESUME times); a render goes
back in the queue; a post is never repeated. python test_resume.py (API venv)"""
import json, os, sys, tempfile
os.environ["STUDIO_DATA"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import app, store

spawned = []
app.spawn = lambda pid, job, *a: spawned.append((pid, job, a))


def mk(pid):
    d = store.PROJECTS / pid
    d.mkdir(parents=True, exist_ok=True)
    (d / "project.json").write_text(json.dumps({"id": pid, "render": {"state": "rendering"}, "_jobs": {}}))
    return store.read(pid)


assert app.resume(mk("aaa"), "check", {}) and spawned == [("aaa", "check", ())]
assert store.read("aaa")["_jobs"]["check"]["resumes"] == 1
assert not app.resume(store.read("aaa"), "check", {"resumes": 2})            # gave up: left failed for an editor
assert app.resume(mk("fff"), "final", {}) and spawned[-1] == ("fff", "final", ("again",))
assert app.resume(mk("rrr"), "render", {"state": "running"})
r = store.read("rrr")
assert r["render"]["state"] == "queued" and r["render"]["resumes"] == 1 and "render" not in r["_jobs"]
r["render"]["resumes"] = 2
assert not app.resume(r, "render", {})
assert not app.resume(mk("ppp"), "post", {})                                 # never uploads twice by itself
print("ok")
