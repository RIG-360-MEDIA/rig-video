"""Posting to YouTube: a finished video is uploaded unlisted once ("Awaiting approval"); Post makes it public; never
twice; anchor-only goes public by itself after 60 minutes; Post all; the title and description."""
import datetime as dt

import app as api
import store
from conftest import at_stage, jobs


def post(c, pid, **kw):
    return c.post(f"/api/projects/{pid}/post", json={"platform": "youtube", "title": "Floods in Nepal", **kw})


def test_post_defaults(ed):
    p = at_stage("done")
    d = ed.get(f"/api/projects/{p['id']}/post").json()
    assert d["platforms"] == ["youtube"] and d["title"] == p["headline"]
    assert d["description"].startswith("Video Bulletin") and "AI-generated voice" in d["description"]


def test_long_headline_is_cut_on_a_word(ed):
    p = at_stage("done", headline="Floods " * 30)
    t = ed.get(f"/api/projects/{p['id']}/post").json()["title"]
    assert len(t) <= 100 and t.endswith("...") and not t[:-3].endswith(" ")


def test_dnl_link_goes_in_the_description():
    p = at_stage("done")
    store.update(p["id"], lambda q: q["source"].update(url="https://democracynewslive.com/long-read/abc"))
    assert "Read the full story: https://democracynewslive.com/long-read/abc" in api.post_text(store.read(p["id"]))[1]


def test_post(ed, spawned):
    p = at_stage("done")
    q = post(ed, p["id"]).json()
    assert q["posts"]["youtube"]["state"] == "posting" and q["posts"]["youtube"]["by"] == "ed@rig.test"
    assert spawned[-1] == (p["id"], "post", ("youtube",))


def test_post_refusals(ed, spawned):
    p = at_stage("done")
    assert post(ed, p["id"], platform="tiktok").status_code == 400
    assert post(ed, p["id"], title="  ").status_code == 400
    r = at_stage("review")
    assert post(ed, r["id"]).status_code == 409                     # no final video yet
    for state in ("posted", "posting", "uploading"):
        store.update(p["id"], lambda q, s=state: q.setdefault("posts", {}).update(youtube={"state": s, "videoId": "Y"}))
        assert post(ed, p["id"]).status_code == 409, state
    assert spawned == []


def test_stale_final_cannot_be_posted(ed):
    p = at_stage("done")
    store.update(p["id"], lambda q: q["versions"]["vo_only"][0]["voice"].update(pick="t9"))     # changed since it was made
    assert post(ed, p["id"]).status_code == 409


def test_failed_post_keeps_its_upload_never_a_second_one(ed):
    p = at_stage("done")
    store.update(p["id"], lambda q: q.setdefault("posts", {}).update(youtube={"state": "failed", "videoId": "Y1", "url": "u", "sent": 5}))
    q = post(ed, p["id"]).json()
    assert q["posts"]["youtube"]["videoId"] == "Y1" and store.read(p["id"])["posts"]["youtube"]["sent"] == 5


def built(p, minutes_ago):
    t = (store.now() - dt.timedelta(minutes=minutes_ago)).isoformat(timespec="seconds")
    store.update(p["id"], lambda q: q["final"].update(builtAt=t))
    return store.read(p["id"])


def test_finished_video_is_uploaded_unlisted_once(spawned):
    p = built(at_stage("done"), 5)
    api.auto_post(p)
    yt = store.read(p["id"])["posts"]["youtube"]
    assert yt["state"] == "uploading" and yt["auto"] and spawned[-1] == (p["id"], "post", ("youtube", "upload"))
    api.auto_post(store.read(p["id"]))                              # already uploading: nothing more
    assert jobs(spawned) == ["post"]


def test_vo_video_never_goes_public_by_itself(spawned):
    p = built(at_stage("done"), 5)
    store.update(p["id"], lambda q: q.setdefault("posts", {}).update(youtube={"state": "awaiting", "videoId": "Y", "title": "t", "description": "d"}))
    api.auto_post(built(store.read(p["id"]), 600))
    assert spawned == []


def test_anchor_only_goes_public_after_60_minutes(spawned):
    p = built(at_stage("done", fmt="anchor_only"), 5)
    store.update(p["id"], lambda q: q.setdefault("posts", {}).update(youtube={"state": "awaiting", "videoId": "Y", "title": "t", "description": "d"}))
    api.auto_post(store.read(p["id"]))
    assert spawned == []                                            # 5 minutes: not yet
    api.auto_post(built(store.read(p["id"]), 61))
    assert spawned[-1] == (p["id"], "post", ("youtube",)) and store.read(p["id"])["posts"]["youtube"]["by"] == "auto"


def test_old_finals_are_left_alone(spawned):
    api.auto_post(built(at_stage("done"), 25 * 60))
    assert spawned == []


def test_post_all(ed, spawned):
    a, b, c = at_stage("done"), at_stage("done"), at_stage("review")
    store.update(b["id"], lambda q: q.setdefault("posts", {}).update(youtube={"state": "posted", "videoId": "Y"}))
    out = ed.post("/api/post-all", json={"ids": [a["id"], b["id"], c["id"], "nope-123"]}).json()
    assert out["posted"] == [a["id"]] and set(out["skipped"]) == {b["id"], c["id"], "nope-123"}
    assert jobs(spawned) == ["post"]


def test_post_all_skips_other_workspaces_stories(outsider, spawned):
    a = at_stage("done")
    out = outsider.post("/api/post-all", json={"ids": [a["id"]]}).json()
    assert out == {"posted": [], "skipped": {a["id"]: "Not found."}} and spawned == []
