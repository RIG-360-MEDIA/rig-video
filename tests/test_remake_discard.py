"""Remake and Discard of a finished video (Render page, Review, Desk): Remake sends it back to Review without its video
(or straight back into the queue); Discard takes it off the Desk and the Library; neither is allowed while the video is
public or being uploaded; an upload awaiting approval is remembered, not lost."""
import pytest

import store
from conftest import at_stage, new_story


def yt(p, **v):
    store.update(p["id"], lambda q: q.setdefault("posts", {}).update(youtube=v))


def test_remake_opens_it_again(ed):
    p = at_stage("done")
    yt(p, state="awaiting", videoId="Y1")
    r = ed.post(f"/api/projects/{p['id']}/remake", json={})
    assert r.status_code == 200
    q = store.read(p["id"])
    assert q["stage"] == "review" and not {"render", "final", "_library", "videoId"} & q.keys() and "youtube" not in q["posts"]
    assert q["_oldPosts"][0]["videoId"] == "Y1" and q["_oldPosts"][0]["droppedAt"]
    assert ed.get("/api/desk").json()["library"] == []
    assert ed.post(f"/api/projects/{p['id']}/remake", json={}).status_code == 409            # not rendered any more


def test_remake_now_goes_straight_back_into_the_queue_with_its_outro(ed, spawned):
    p = at_stage("done")
    store.update(p["id"], lambda q: q.update(extras={"outro": False}))
    q = ed.post(f"/api/projects/{p['id']}/remake", json={"now": True}).json()
    assert q["stage"] == "render" and q["render"]["state"] == "queued" and store.read(p["id"])["extras"] == {"outro": False}
    assert spawned == []


def test_remake_only_a_finished_video(ed):
    for stage in ("script", "visuals", "review", "render"):
        assert ed.post(f"/api/projects/{at_stage(stage)['id']}/remake", json={}).status_code == 409, stage


@pytest.mark.parametrize("state", ["posted", "posting", "uploading"])
def test_public_or_uploading_video_cannot_be_remade_or_discarded(ed, state):
    p = at_stage("done")
    yt(p, state=state, videoId="Y2")
    assert ed.post(f"/api/projects/{p['id']}/remake", json={}).status_code == 409
    assert ed.post(f"/api/projects/{p['id']}/archive").status_code == 409
    q = store.read(p["id"])
    assert q["stage"] == "done" and not q.get("_archived")


def test_post_job_running_blocks_both(ed):
    p = at_stage("done")
    store.job(p["id"], "post", state="running")
    assert ed.post(f"/api/projects/{p['id']}/remake", json={}).status_code == 409
    assert ed.post(f"/api/projects/{p['id']}/archive").status_code == 409


def test_discard_awaiting_video(ed):
    p = at_stage("done")
    yt(p, state="awaiting", videoId="Y3")
    assert ed.post(f"/api/projects/{p['id']}/archive").status_code == 200
    d = ed.get("/api/desk").json()
    assert store.read(p["id"])["_archived"] and d["library"] == [] and p["id"] not in [x["id"] for x in d["projects"]]


def test_discard_refused_while_the_machine_works_on_it(ed):
    p = new_story()
    store.job(p["id"], "write", state="running")
    assert ed.post(f"/api/projects/{p['id']}/archive").status_code == 409


def test_failed_upload_can_be_remade(ed):
    p = at_stage("done")
    yt(p, state="failed", error="quota")
    assert ed.post(f"/api/projects/{p['id']}/remake", json={}).status_code == 200
