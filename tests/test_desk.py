"""The Desk: today's picks (reserves step in for used or removed ones), stories, the render queue and the library,
only from the signed-in person's workspace; preferences."""
import store
from conftest import at_stage, new_story, write_selection


def test_desk_shape(ed):
    d = ed.get("/api/desk").json()
    assert set(d) >= {"user", "workspace", "picks", "hiddenPicks", "defaults", "formats", "anchors", "projects", "jobs", "queue", "library"}
    assert d["formats"] == ["anchor_vo", "anchor_only", "vo_only"]
    assert d["anchors"] and all({"id", "name", "face", "offered"} <= set(a) for a in d["anchors"])


def test_picks_show_and_reserves_fill_in(ed):
    picks, reserves = write_selection(["Floods in Nepal", "Strike on Kharkiv"], ["Reserve one"])
    d = ed.get("/api/desk").json()
    assert [p["headline"] for p in d["picks"]] == ["Floods in Nepal", "Strike on Kharkiv"]
    assert d["picks"][0]["url"].startswith("https://democracynewslive.com/long-read/")
    new_story(_pick=picks[0])                                       # pick 1 made into a story
    d = ed.get("/api/desk").json()
    assert [p["headline"] for p in d["picks"]] == ["Strike on Kharkiv", "Reserve one"] and d["picks"][1]["reserve"]


def test_removed_picks_and_bring_back(ed):
    picks, _ = write_selection(["A", "B"])
    assert ed.put("/api/prefs", json={"hiddenPicks": [picks[0]]}).status_code == 200
    assert [p["headline"] for p in ed.get("/api/desk").json()["picks"]] == ["B"]
    ed.put("/api/prefs", json={"hiddenPicks": []})
    assert len(ed.get("/api/desk").json()["picks"]) == 2


def test_no_selection_yet_is_empty_not_an_error(ed):
    assert ed.get("/api/desk").json()["picks"] == []


def test_other_workspace_gets_no_picks_and_no_dnl_stories(outsider):
    write_selection(["A"])
    new_story()
    d = outsider.get("/api/desk").json()
    assert d["picks"] == [] and d["projects"] == [] and d["library"] == [] and d["queue"] == []


def test_archived_stories_leave_desk_and_library(ed):
    p = at_stage("done")
    assert [x["id"] for x in ed.get("/api/desk").json()["library"]] == ["lib-" + p["id"]]
    store.update(p["id"], lambda q: q.update(_archived=True))
    d = ed.get("/api/desk").json()
    assert d["library"] == [] and p["id"] not in [x["id"] for x in d["projects"]]


def test_private_fields_never_reach_the_site(ed):
    new_story(_pick="abc", _secret="x")
    for p in ed.get("/api/desk").json()["projects"]:
        assert not [k for k in p if k.startswith("_")], p.keys()


def test_prefs_only_known_defaults(ed):
    pr = ed.put("/api/prefs", json={"defaults": {"format": "vo_only", "length": 90, "evil": 1}}).json()
    assert pr["defaults"]["format"] == "vo_only" and pr["defaults"]["length"] == 90 and "evil" not in pr["defaults"]
    assert ed.put("/api/prefs", json={"defaults": {"format": "made_up"}}).json()["defaults"]["format"] == "vo_only"
    assert ed.get("/api/desk").json()["defaults"]["length"] == 90


def test_prefs_are_per_person(ed):
    from conftest import signed_in
    ed.put("/api/prefs", json={"defaults": {"length": 120}})
    other = signed_in("ana@rig.test")
    assert other.get("/api/desk").json()["defaults"]["length"] == 60


def test_queue_order_and_jobs_on_desk(ed):
    a, b = at_stage("render"), at_stage("render")
    store.update(a["id"], lambda q: q.update(_queuedAt="2026-11-27T01:00:00+05:30"))
    store.update(b["id"], lambda q: q.update(_queuedAt="2026-11-27T00:30:00+05:30"))
    s = new_story()
    store.job(s["id"], "write", state="running", progress=0.4, note="Writing the script")
    d = ed.get("/api/desk").json()
    assert [q["projectId"] for q in d["queue"]] == [b["id"], a["id"]]
    assert d["jobs"][s["id"]]["kind"] == "write" and d["jobs"][s["id"]]["progress"] == 0.4


def test_health_is_public_and_names_the_version(client):
    h = client.get("/api/health").json()
    assert h["ok"] is True and "version" in h


def test_public_anchors_only_offered_ones_and_no_private_fields(client):
    out = client.get("/api/anchors").json()
    assert out and all(a["offered"] for a in out)
    assert all(set(a) == {"id", "name", "gender", "face", "voiceSample", "regions", "offered"} for a in out)
