"""After a machine restart: a cut-off job starts again by itself (at most RIGVIDEO_AUTO_RESUME times), a render goes
back in the queue, a post is never repeated by itself (it could upload twice); the monitor marks what it gives up."""
import app as api
import store
from conftest import at_stage, jobs, new_story


def running(job, **extra):
    p = new_story()
    store.update(p["id"], lambda q: q.update(render={"state": "rendering"}, **extra))
    store.job(p["id"], job, state="running", os_pid=999999999)
    return store.read(p["id"])


def test_a_cut_off_job_starts_again(spawned):
    p = running("check")
    assert api.resume(p, "check", p["_jobs"]["check"]) and jobs(spawned) == ["check"]
    assert store.read(p["id"])["_jobs"]["check"]["resumes"] == 1
    assert not api.resume(store.read(p["id"]), "check", {"resumes": 2})      # gave up: left failed for an editor


def test_final_resumes_with_again(spawned):
    p = running("final")
    api.resume(p, "final", {})
    assert spawned[-1][1:] == ("final", ("again",))


def test_render_goes_back_in_the_queue(spawned):
    p = running("render")
    assert api.resume(p, "render", {"state": "running"})
    r = store.read(p["id"])
    assert r["render"]["state"] == "queued" and r["render"]["resumes"] == 1 and "render" not in r["_jobs"] and spawned == []


def test_a_post_is_never_repeated_by_itself(spawned):
    p = running("post")
    assert not api.resume(p, "post", {}) and spawned == []


def one_tick(monkeypatch):
    """Run one pass of the monitor loop (it normally loops forever)."""
    class Stop(Exception):
        pass

    def stop(s):
        raise Stop
    monkeypatch.setattr(api.time, "sleep", stop)
    try:
        api.monitor()
    except Stop:
        pass


def test_monitor_gives_up_and_marks_failed(monkeypatch, spawned):
    monkeypatch.setattr(api, "AUTO_RESUME", 0)
    r = running("render", stage="render")
    p = running("post")
    store.update(p["id"], lambda q: q.update(posts={"youtube": {"state": "posting"}}))
    one_tick(monkeypatch)
    r, p = store.read(r["id"]), store.read(p["id"])
    assert r["_jobs"]["render"]["state"] == "failed" and r["render"]["state"] == "failed" and r["stage"] == "review"
    assert p["_jobs"]["post"]["state"] == "failed" and p["posts"]["youtube"]["state"] == "failed" and spawned == []


def test_monitor_starts_a_render_only_in_the_window(monkeypatch, spawned):
    p = at_stage("render")
    monkeypatch.setattr(store, "in_render_window", lambda t=None: False)
    one_tick(monkeypatch)
    assert spawned == [] and store.read(p["id"])["render"]["state"] == "queued"
    monkeypatch.setattr(store, "in_render_window", lambda t=None: True)
    one_tick(monkeypatch)
    assert spawned == [(p["id"], "render", ())] and store.read(p["id"])["render"]["state"] == "rendering"


def test_monitor_one_render_at_a_time(monkeypatch, spawned):
    a, b = at_stage("render"), at_stage("render")
    monkeypatch.setattr(store, "in_render_window", lambda t=None: True)

    class Alive:
        def poll(self):
            return None
    monkeypatch.setitem(api.RUNNING, (a["id"], "render"), Alive())
    one_tick(monkeypatch)
    assert spawned == []


def test_monitor_never_starts_selection_when_switched_off(monkeypatch, spawned):
    one_tick(monkeypatch)                                           # RIGVIDEO_NO_SELECTION=1 in tests: no worker started
    assert not (store.DATA / "selection").exists()
