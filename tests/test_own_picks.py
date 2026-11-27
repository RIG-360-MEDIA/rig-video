"""The desk's own picks: an editor adds a story of their own (link, pasted text, file) to today's picks. Before the
08:00 daily run it waits and starts with it; after 08:00 it starts at once. Either way it runs the daily pipeline:
1-minute VO only, script approved by itself, then voices and footage, then the editor and the overnight render."""
import datetime as dt

import pytest

import app as api
import store
from conftest import ARTICLE, jobs, make_user, signed_in, write_selection


def at(hour, minute=0):
    t = dt.datetime.combine(dt.date(2026, 11, 28), dt.time(hour, minute), store.IST)
    return lambda: t


@pytest.fixture
def morning(monkeypatch):
    monkeypatch.setattr(store, "now", at(7, 15))


@pytest.fixture
def daytime(monkeypatch):
    monkeypatch.setattr(store, "now", at(11, 30))


def add(c, **body):
    return c.post("/api/picks", json=body)


def own(c):
    return [p for p in c.get("/api/desk").json()["picks"] if p.get("own")]


def test_added_before_8_waits_on_the_desk(ed, spawned, morning):
    r = add(ed, kind="text", text=ARTICLE)
    assert r.status_code == 200, r.text
    assert r.json()["started"] is None and spawned == [] and store.all_projects() == []
    p = own(ed)[0]
    assert p["headline"].startswith("Floods hit the Kathmandu valley") and p["addedBy"] == "Ed" and "08:00" in p["waiting"]


def test_waiting_picks_start_with_the_daily_run(ed, spawned, morning, monkeypatch):
    make_user("boss@rig.test", role="admin")
    add(ed, kind="link", url="https://example.com/news/dam-burst-in-libya")
    write_selection(["DNL pick"])
    monkeypatch.setattr(store, "now", at(8, 0))
    api.daily_start()
    ps = {p["headline"]: p for p in store.all_projects()}
    assert set(ps) == {"DNL pick", "dam burst in libya"}
    mine = ps["dam burst in libya"]
    assert mine["format"] == "vo_only" and mine["targetSeconds"] == 60 and mine["_autoApprove"] and mine["_daily"] == "2026-11-28"
    assert mine["source"]["url"] == "https://example.com/news/dam-burst-in-libya" and mine["source"]["site"] == "example.com"
    assert mine["_by"] == store.users()[0]["id"]                                 # the editor who added it
    assert jobs(spawned) == ["write", "write"] and own(ed) == []                  # it left the picks: it is a story now


def test_own_picks_start_even_if_dnl_selection_is_late(ed, spawned, morning, monkeypatch):
    add(ed, kind="text", text=ARTICLE)
    monkeypatch.setattr(store, "now", at(8, 5))
    assert len(api.daily_start()) == 1 and jobs(spawned) == ["write"]
    assert api.daily_start() == []                                               # never twice


def test_added_after_8_starts_at_once(ed, spawned, daytime):
    r = add(ed, kind="text", text=ARTICLE).json()
    p = store.read(r["started"])
    assert p["_pick"] == r["pick"]["id"] and p["_autoApprove"] and p["format"] == "vo_only" and jobs(spawned) == ["write"]
    assert p["source"]["kind"] == "text" and p["source"]["text"] == ARTICLE and own(ed) == []


def test_from_a_file(ed, spawned, morning):
    r = ed.post("/api/picks/file", files={"file": ("Libya_dam.txt", ARTICLE.encode())})
    assert r.status_code == 200 and r.json()["pick"]["headline"] == "Libya dam"


@pytest.mark.parametrize("body,code", [({"kind": "text", "text": "Too short."}, 400), ({"kind": "link", "url": "nope"}, 400),
                                       ({"kind": "magic"}, 400)])
def test_refused(ed, spawned, morning, body, code):
    assert add(ed, **body).status_code == code and own(ed) == [] and spawned == []


def test_same_link_twice_is_refused(ed, morning):
    add(ed, kind="link", url="https://example.com/a")
    assert add(ed, kind="link", url="https://example.com/a").status_code == 409


def test_everyone_on_the_desk_sees_it_and_anyone_can_remove_it(ed, morning):
    add(ed, kind="text", text=ARTICLE)
    ana = signed_in("ana@rig.test")
    pid = own(ana)[0]["id"]
    assert ana.delete(f"/api/picks/{pid}").status_code == 200 and own(ed) == []
    assert ana.delete(f"/api/picks/{pid}").status_code == 404


def test_a_started_pick_cannot_be_removed(ed, daytime):
    r = add(ed, kind="text", text=ARTICLE).json()
    assert ed.delete(f"/api/picks/{r['pick']['id']}").status_code == 409


def test_editor_can_use_it_by_hand_like_any_pick(ed, spawned, morning):
    pid = add(ed, kind="text", text=ARTICLE).json()["pick"]["id"]
    p = ed.post("/api/projects", json={"kind": "pick", "pickId": pid, "seconds": 90, "format": "anchor_vo"}).json()
    assert p["targetSeconds"] == 90 and p["source"]["text"] == ARTICLE and store.read(p["id"])["_pick"] == pid and own(ed) == []


def test_only_today(ed, morning, monkeypatch):
    add(ed, kind="text", text=ARTICLE)
    monkeypatch.setattr(store, "now", lambda: dt.datetime(2026, 11, 29, 7, 0, tzinfo=store.IST))
    assert own(ed) == []


def test_other_workspaces_neither_add_nor_see_dnl_picks(ed, outsider, morning):
    pid = add(ed, kind="text", text=ARTICLE).json()["pick"]["id"]
    assert own(outsider) == [] and outsider.delete(f"/api/picks/{pid}").status_code == 404
    assert add(outsider, kind="text", text=ARTICLE).status_code == 400
    assert outsider.post("/api/projects", json={"kind": "pick", "pickId": pid}).status_code == 404


def test_dnl_picks_unchanged_by_own_picks(ed, morning):
    write_selection(["A", "B"])
    add(ed, kind="text", text=ARTICLE)
    heads = [p["headline"] for p in ed.get("/api/desk").json()["picks"]]
    assert heads[:2] == ["A", "B"] and len(heads) == 3
