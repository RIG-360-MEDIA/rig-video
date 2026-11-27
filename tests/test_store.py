"""Storage (store.py): story ids are safe folder names; every change happens under a lock so the server and the
workers never overwrite each other; render window and hold; the VO text-share rule; type switching."""
import datetime as dt
import multiprocessing
import os

import pytest

import store
from conftest import at_stage, new_story

IST = store.IST
T = lambda h, m=30, d=23: dt.datetime(2026, 11, d, h, m, tzinfo=IST)


@pytest.mark.parametrize("pid", ["..", "../x", "a/b", "AB", "ab", "x" * 61, "", None, "a b"])
def test_unsafe_ids_are_refused(pid):
    with pytest.raises(KeyError):
        store.pdir(pid)


def test_ids_are_slugs():
    p = store.create({"headline": "Floods hit Nepal's capital, 42 dead!"})
    assert p["id"].startswith("floods-hit-nepal-s-capital-") and store.pdir(p["id"]).is_dir()
    assert store.create({"headline": ""})["id"].startswith("story-")


def _bump(args):
    data, pid, n = args
    store.DATA, store.PROJECTS = data, data / "projects"
    for _ in range(n):
        store.update(pid, lambda q: q.update(count=q.get("count", 0) + 1))


def test_parallel_writers_lose_nothing():
    """4 processes x 25 changes to one story: the lock keeps every one (the server and the workers do this all day)."""
    p = new_story()
    ctx = multiprocessing.get_context("fork" if hasattr(os, "fork") else "spawn")
    with ctx.Pool(4) as pool:
        pool.map(_bump, [(store.DATA, p["id"], 25)] * 4)
    assert store.read(p["id"])["count"] == 100


def test_jobs_merge_and_clear():
    p = new_story()
    store.job(p["id"], "write", state="running", progress=0.5)
    store.job(p["id"], "write", note="half")
    assert store.read(p["id"])["_jobs"]["write"] == {"state": "running", "progress": 0.5, "note": "half"}
    store.job(p["id"], "write", state=None)
    assert "write" not in store.read(p["id"])["_jobs"]


def test_render_window(monkeypatch):
    assert store.in_render_window(T(0, 0)) and store.in_render_window(T(6, 59)) and not store.in_render_window(T(7, 0))
    assert not store.in_render_window(T(23)) and not store.in_render_window(T(12))
    monkeypatch.setenv("RIGVIDEO_RENDER_WINDOW", "22:00-02:00")                 # a window across midnight
    assert store.in_render_window(T(23)) and store.in_render_window(T(1)) and not store.in_render_window(T(3))


def test_render_hold_ends_by_itself():
    (store.DATA / "render_hold_until").write_text(T(7).isoformat())
    assert not store.in_render_window(T(0)) and store.render_hold(T(6))
    assert store.render_hold(T(8)) is None and store.in_render_window(T(1, d=24))
    (store.DATA / "render_hold_until").write_text("garbage")
    assert store.render_hold(T(1)) is None and store.in_render_window(T(1))


def test_text_share_rule():
    c = lambda k, s=3.0: {"kind": k, "secs": s}
    e = {"edit": {"beats": [{"sectionId": "b1", "secs": 6.0, "cuts": [c("footage"), c("post_or_document")]},
                            {"sectionId": "b2", "secs": 7.0, "cuts": [c("footage"), c("footage")]},
                            {"sectionId": "b3", "secs": 4.0, "cuts": []}]}}
    share, short = store.text_share(e)
    assert share == 0.25 and short == ["b2", "b3"]
    assert store.text_share({}) == (0.0, [])


def test_switch_type():
    q = {"format": "vo_only", "versions": {"vo_only": [{"id": "b1"}], "anchor_vo": []}, "visuals": {}, "stage": "visuals", "render": {}}
    assert store.switched(q, "anchor_vo", "why", "auto") == "write" and q["stage"] == "script" and q["_autoApprove"] and "render" not in q
    q["versions"]["anchor_vo"] = [{"id": "s1"}]
    assert store.switched(q, "vo_only", "back", "editor") == "approved" and q["stage"] == "visuals" and q["formatWhy"]["by"] == "editor"


def test_final_goes_stale_when_the_edit_or_a_voice_changes():
    p = at_stage("done")
    assert store.public(p)["final"]["stale"] is False
    store.update(p["id"], lambda q: q["edit"]["beats"][0]["cuts"][0].update(secs=5.0))
    assert store.public(store.read(p["id"]))["final"]["stale"] is True


def test_public_hides_private_keys():
    p = new_story(_secret="s")
    assert not [k for k in store.public(store.read(p["id"])) if k.startswith("_")]


def test_passwords():
    store.adduser("A@B.C", "A", "admin", "dnl", "pw one")
    assert store.check_password("a@b.c ", "pw one") and not store.check_password("a@b.c", "pw two")
    store.adduser("a@b.c", "A", "admin", "dnl", "pw new")                       # re-adding replaces, never duplicates
    assert len(store.users()) == 1 and store.check_password("a@b.c", "pw new")
    assert oct((store.DATA / "users.json").stat().st_mode)[-3:] == "600"


def test_prefs_default_and_save():
    assert store.prefs("u1")["defaults"]["length"] == 60
    store.save_prefs("u1", {"defaults": {"length": 90}, "hiddenPicks": []})
    assert store.prefs("u1")["defaults"]["length"] == 90
