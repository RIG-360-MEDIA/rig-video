"""A story's way through the site: edits on Script, Approve, the footage step (keywords, moments, uploads, maps),
switching type, retries and re-voicing, then Render, the queue (order, move up, cancel). Each step checks which machine
job it starts and what it refuses."""
import pytest

import app as api
import store
from conftest import at_stage, jobs, new_story


def code(r):
    return r.status_code


# ------------------------------------------------------------------ script

def test_edits_save_and_cannot_jump_to_render(ed):
    p = at_stage("script")
    r = ed.put(f"/api/projects/{p['id']}", json={"headline": "New headline", "tone": "Grave", "stage": "render"})
    q = r.json()
    assert q["headline"] == "New headline" and q["tone"] == "Grave" and q["stage"] == "script"


def test_no_edits_while_the_script_is_written(ed):
    p = new_story()
    store.job(p["id"], "write", state="running")
    assert code(ed.put(f"/api/projects/{p['id']}", json={"headline": "x"})) == 409
    assert store.read(p["id"])["headline"] != "x"


def test_unknown_format_or_anchor_refused(ed):
    p = at_stage("script")
    assert code(ed.put(f"/api/projects/{p['id']}", json={"format": "hologram"})) == 400
    assert code(ed.put(f"/api/projects/{p['id']}", json={"anchorId": "nobody"})) == 400


def test_switching_to_an_unwritten_format_writes_it(ed, spawned):
    p = at_stage("script", fmt="vo_only")
    ed.put(f"/api/projects/{p['id']}", json={"format": "anchor_vo"})
    assert jobs(spawned) == ["write"]


def test_approve_needs_a_script_then_starts_voice_and_footage(ed, spawned):
    p = new_story()
    assert code(ed.post(f"/api/projects/{p['id']}/approve")) == 409 and spawned == []
    p = at_stage("script")
    q = ed.post(f"/api/projects/{p['id']}/approve").json()
    assert q["stage"] == "visuals" and jobs(spawned) == ["voice", "search"]
    assert all(s["voice"]["state"] == "making" for s in q["versions"]["vo_only"])
    assert set(q["visuals"]) == {"b1", "b2", "b3"} and q["edit"]["state"] == "waiting"


def test_changed_line_after_approval_is_voiced_again(ed, spawned):
    p = at_stage("visuals")
    secs = p["versions"]["vo_only"]
    secs[0] = {**secs[0], "text": "A new first line."}
    q = ed.put(f"/api/projects/{p['id']}", json={"versions": {"vo_only": secs}}).json()
    assert q["versions"]["vo_only"][0]["voice"]["state"] == "making" and q["versions"]["vo_only"][1]["voice"]["state"] == "ready"
    assert jobs(spawned) == ["voice"]


def test_new_anchor_revoices_everything(ed, spawned):
    p = at_stage("visuals", fmt="anchor_vo")
    other = next(a["id"] for a in api.registry() if a["id"] != p["anchorId"])
    q = ed.put(f"/api/projects/{p['id']}", json={"anchorId": other, "versions": {"anchor_vo": p["versions"]["anchor_vo"]}}).json()
    assert all(s["voice"]["state"] == "making" and s["voice"]["takes"] == [] for s in q["versions"]["anchor_vo"])
    assert jobs(spawned) == ["voice"]


def test_picking_another_take_keeps_it_ready(ed, spawned):
    p = at_stage("visuals")
    store.update(p["id"], lambda q: q["versions"]["vo_only"][0]["voice"].update(takes=[{"id": "t1"}, {"id": "t2"}]))
    secs = store.read(p["id"])["versions"]["vo_only"]
    secs[0]["voice"] = {"pick": "t2"}
    q = ed.put(f"/api/projects/{p['id']}", json={"versions": {"vo_only": secs}}).json()
    assert q["versions"]["vo_only"][0]["voice"] == {"state": "ready", "takes": [{"id": "t1"}, {"id": "t2"}], "pick": "t2"} and spawned == []


def test_edit_cuts_keep_only_known_fields_and_short_sound(ed):
    p = at_stage("review")
    cut = {"id": "c1", "src": {"youtubeId": "y"}, "secs": 3, "kind": "footage", "sound": "  sirens   " + "x" * 200, "evil": "<script>"}
    q = ed.put(f"/api/projects/{p['id']}", json={"edit": {"beats": [{"sectionId": "b1", "cuts": [cut, {"no": "src"}]}]}}).json()
    got = q["edit"]["beats"][0]["cuts"]
    assert len(got) == 1 and "evil" not in got[0] and len(got[0]["sound"]) == 80 and got[0]["sound"].startswith("sirens x")


# ------------------------------------------------------------------ type switch, retry, revoice

def test_switch_type(ed, spawned):
    p = at_stage("visuals")
    assert code(ed.post(f"/api/projects/{p['id']}/switch", json={"format": "vo_only"})) == 400        # already that type
    q = ed.post(f"/api/projects/{p['id']}/switch", json={"format": "anchor_vo"}).json()
    assert q["format"] == "anchor_vo" and q["stage"] == "script" and q["formatWhy"]["by"] == "editor" and jobs(spawned) == ["write"]


def test_no_switch_while_rendering(ed):
    p = at_stage("render")
    assert code(ed.post(f"/api/projects/{p['id']}/switch", json={"format": "anchor_vo"})) == 409


def test_retry_only_a_failed_job(ed, spawned):
    p = at_stage("visuals")
    assert code(ed.post(f"/api/projects/{p['id']}/retry", json={"job": "voice"})) == 409
    store.job(p["id"], "voice", state="failed", error="t3 down")
    assert code(ed.post(f"/api/projects/{p['id']}/retry", json={"job": "voice"})) == 200 and jobs(spawned) == ["voice"]
    assert "voice" not in store.read(p["id"]).get("_jobs", {})


def test_check_again_one_beat(ed, spawned):
    p = at_stage("review")
    assert code(ed.post(f"/api/projects/{p['id']}/retry", json={"job": "check", "sid": "zz"})) == 404
    q = ed.post(f"/api/projects/{p['id']}/retry", json={"job": "check", "sid": "b2"}).json()
    assert q["edit"]["state"] == "checking" and spawned[-1][1:] == ("check", ("b2",))


def test_revoice_one_part_with_a_note(ed, spawned):
    p = at_stage("visuals")
    q = ed.post(f"/api/projects/{p['id']}/revoice", json={"sid": "b2", "note": "Slower"}).json()
    v = q["versions"]["vo_only"][1]["voice"]
    assert v["state"] == "redoing" and v["note"] == "Slower" and jobs(spawned) == ["voice"]
    assert code(ed.post(f"/api/projects/{p['id']}/revoice", json={"sid": "nope"})) == 404


# ------------------------------------------------------------------ footage page

def test_keywords(ed, spawned):
    p = at_stage("visuals")
    q = ed.post(f"/api/projects/{p['id']}/keywords", json={"sid": "b1", "text": "Kathmandu rescue"}).json()
    k = q["visuals"]["b1"]["keywords"][-1]
    assert k["text"] == "Kathmandu rescue" and k["state"] == "queued" and spawned[-1] == (p["id"], "keyword", ("b1", k["id"]))
    assert code(ed.post(f"/api/projects/{p['id']}/keywords", json={"sid": "b1", "text": "kathmandu RESCUE"})) == 409
    assert code(ed.post(f"/api/projects/{p['id']}/keywords", json={"sid": "b1", "text": " "})) == 400
    assert code(ed.post(f"/api/projects/{p['id']}/keywords/{k['id']}/research", json={"sid": "b1"})) == 200
    assert code(ed.post(f"/api/projects/{p['id']}/keywords/kzz/research", json={"sid": "b1"})) == 404


def test_removed_keyword_is_remembered_and_its_videos_go(ed):
    p = at_stage("visuals")
    store.update(p["id"], lambda q: q["visuals"]["b1"].update(
        keywords=[{"id": "k1", "text": "a"}, {"id": "k2", "text": "b"}],
        found=[{"id": "v1", "keywordId": "k1", "moments": []}, {"id": "v2", "keywordId": "k2", "moments": []}]))
    q = ed.put(f"/api/projects/{p['id']}", json={"visuals": {"b1": {"keywords": [{"id": "k2"}]}}}).json()
    assert [k["id"] for k in q["visuals"]["b1"]["keywords"]] == ["k2"] and [f["id"] for f in q["visuals"]["b1"]["found"]] == ["v2"]
    assert store.read(p["id"])["_removedKeywords"] == {"b1": ["k1"]}


def test_site_cannot_add_machine_lists(ed):
    p = at_stage("visuals")
    q = ed.put(f"/api/projects/{p['id']}", json={"visuals": {"b1": {"uploads": [{"id": "fake", "src": "/etc/passwd"}]}}}).json()
    assert q["visuals"]["b1"]["uploads"] == []


def test_marked_moment(ed):
    p = at_stage("visuals")
    store.update(p["id"], lambda q: q["visuals"]["b1"]["found"].append({"id": "v1", "keywordId": "k1", "duration": 30.0,
                                                                         "moments": [{"start": 2.0, "end": 5.0}]}))
    r = ed.post(f"/api/projects/{p['id']}/moments", json={"videoId": "v1", "start": 2.05, "end": 5.1}).json()
    assert r["moment"] == 0                                         # the same range: the existing moment
    r = ed.post(f"/api/projects/{p['id']}/moments", json={"videoId": "v1", "start": 10, "end": 99}).json()
    m = r["project"]["visuals"]["b1"]["found"][0]["moments"][1]
    assert r["moment"] == 1 and m["end"] == 30.0 and m["custom"]
    assert code(ed.post(f"/api/projects/{p['id']}/moments", json={"videoId": "v1", "start": 9, "end": 3})) == 400
    assert code(ed.post(f"/api/projects/{p['id']}/moments", json={"videoId": "v9", "start": 1, "end": 3})) == 404
    assert code(ed.post(f"/api/projects/{p['id']}/moments", json={"videoId": "v1"})) == 400


def test_uploads_and_maps(ed, monkeypatch):
    p = at_stage("visuals")
    up = ed.post(f"/api/projects/{p['id']}/uploads", data={"sid": "b1"}, files={"file": ("photo.JPG", b"\xff\xd8jpg")}).json()
    assert up["kind"] == "image" and up["src"].startswith(f"/files/{p['id']}/media/uploads/")
    assert ed.get(up["src"]).content == b"\xff\xd8jpg"
    monkeypatch.setattr(api, "probe_seconds", lambda f: 12.5)
    vid = ed.post(f"/api/projects/{p['id']}/uploads", data={"sid": "b1"}, files={"file": ("clip.mp4", b"mp4")}).json()
    assert vid["kind"] == "video" and vid["seconds"] == 12.5
    assert code(ed.post(f"/api/projects/{p['id']}/uploads", data={"sid": "b1"}, files={"file": ("x.exe", b"x")})) == 400
    assert code(ed.post(f"/api/projects/{p['id']}/uploads", data={"sid": "zz"}, files={"file": ("a.jpg", b"x")})) == 404
    m = ed.post(f"/api/projects/{p['id']}/maps", data={"sid": "b2", "title": "Valley"}, files={"file": ("map.png", b"png")}).json()
    assert m["title"] == "Valley"
    assert code(ed.post(f"/api/projects/{p['id']}/maps", data={"sid": "b2"}, files={"file": ("map.mp4", b"x")})) == 400
    q = store.read(p["id"])["visuals"]
    assert len(q["b1"]["uploads"]) == 2 and len(q["b2"]["maps"]) == 1


def test_upload_over_500mb_is_refused_and_not_kept(ed, monkeypatch):
    p = at_stage("visuals")
    monkeypatch.setattr(api, "MAX_UPLOAD", 10)
    assert code(ed.post(f"/api/projects/{p['id']}/uploads", data={"sid": "b1"}, files={"file": ("a.jpg", b"x" * 11)})) == 413
    assert not list((store.pdir(p["id"]) / "media" / "uploads").glob("*"))


def test_places(ed, monkeypatch):
    geo = store.DATA / "geo"
    geo.mkdir()
    row = lambda name, alts, lat, lon, iso, pop: "\t".join(["1", name, name, alts, str(lat), str(lon), "P", "PPL", iso] + [""] * 5 + [str(pop)])
    geo.joinpath("cities15000.txt").write_text("\n".join([row("Kathmandu", "Katmandu", 27.7, 85.3, "NP", 1442271),
                                                          row("Kathua", "", 32.4, 75.5, "IN", 59866),
                                                          row("New York City", "New York", 40.7, -74.0, "US", 8804190),
                                                          row("York", "", 53.9, -1.1, "GB", 153717)]) + "\n")
    monkeypatch.setattr(api, "PLACES", [])
    assert [x["name"] for x in ed.get("/api/places", params={"q": "kat"}).json()] == ["Kathmandu", "Kathua"]
    assert ed.get("/api/places", params={"q": "k"}).json() == []
    named = [x["name"] for x in ed.get("/api/places", params={"text": "Firefighters in New York and Kathmandu said."}).json()]
    assert set(named) == {"New York City", "Kathmandu"}                 # "York" alone is not York, England


# ------------------------------------------------------------------ render and the queue

def test_render_needs_every_voice_and_a_checked_edit(ed):
    p = at_stage("visuals")
    store.update(p["id"], lambda q: q["versions"]["vo_only"][0]["voice"].update(state="making"))
    assert code(ed.post(f"/api/projects/{p['id']}/render", json={})) == 409
    store.update(p["id"], lambda q: (q["versions"]["vo_only"][0]["voice"].update(state="ready"), q["edit"].update(state="checking")))
    assert code(ed.post(f"/api/projects/{p['id']}/render", json={})) == 409
    store.update(p["id"], lambda q: q["edit"].update(state="ready"))
    q = ed.post(f"/api/projects/{p['id']}/render", json={"outro": False}).json()
    assert q["stage"] == "render" and q["render"]["state"] == "queued" and store.read(p["id"])["extras"] == {"outro": False}


def test_render_starts_no_job_by_itself(ed, spawned):
    p = at_stage("review")
    ed.post(f"/api/projects/{p['id']}/render", json={})
    assert spawned == []                                            # the job loop starts it, only in the render window


def test_waiting_render_says_when_it_starts(ed, monkeypatch):
    p = at_stage("render")
    monkeypatch.setattr(store, "in_render_window", lambda t=None: False)
    assert "Starts at 00:00" in ed.get("/api/desk").json()["projects"][0]["render"]["waitNote"]
    (store.DATA / "render_hold_until").write_text((store.now() + store.dt.timedelta(hours=5)).isoformat())
    assert "on hold" in ed.get("/api/desk").json()["projects"][0]["render"]["waitNote"]


def test_cancel_only_while_waiting(ed):
    p = at_stage("render")
    q = ed.post(f"/api/projects/{p['id']}/cancel").json()
    assert q["stage"] == "review" and "render" not in q
    store.update(p["id"], lambda q: (q.update(stage="render"), q.update(render={"state": "rendering"})))
    assert code(ed.post(f"/api/projects/{p['id']}/cancel")) == 409


def test_move_up(ed):
    ids = []
    for t in ("01", "02", "03"):
        p = at_stage("render")
        store.update(p["id"], lambda q, t=t: q.update(_queuedAt=f"2026-11-27T00:{t}:00+05:30"))
        ids.append(p["id"])
    ed.post(f"/api/projects/{ids[2]}/moveup")
    assert [p["id"] for p in api.queue()] == [ids[0], ids[2], ids[1]]
    ed.post(f"/api/projects/{ids[0]}/moveup")                       # already first: nothing changes
    assert [p["id"] for p in api.queue()] == [ids[0], ids[2], ids[1]]


def test_running_render_stays_ahead_of_waiting_ones(ed):
    a, b = at_stage("render"), at_stage("render")
    store.update(b["id"], lambda q: (q["render"].update(state="rendering"), q.update(_queuedAt="2030-01-01T00:00:00+05:30")))
    assert api.queue()[0]["id"] == b["id"]


def test_final_again_only_in_the_window_and_when_ready(ed, spawned, monkeypatch):
    p = at_stage("review")
    monkeypatch.setattr(store, "in_render_window", lambda t=None: False)
    assert code(ed.post(f"/api/projects/{p['id']}/final")) == 409
    monkeypatch.setattr(store, "in_render_window", lambda t=None: True)
    assert code(ed.post(f"/api/projects/{p['id']}/final")) == 200 and spawned[-1][1:] == ("final", ("again",))
    a = at_stage("review", fmt="anchor_vo")
    assert code(ed.post(f"/api/projects/{a['id']}/final")) == 409


def test_rewrite_returns_only_changed_sections(ed, monkeypatch):
    import contextlib
    import writer
    p = at_stage("script", fmt="anchor_vo")
    monkeypatch.setattr(store, "gpu", lambda use: contextlib.nullcontext())
    monkeypatch.setattr(writer, "ask", lambda *a, **k: {"sections": [{"id": "a1", "text": "Shorter a1."}, {"id": "v1", "text": "v1 line."}]})
    assert ed.post(f"/api/projects/{p['id']}/rewrite", json={"scope": "all", "chips": ["Shorter"]}).json() == {"a1": "Shorter a1."}


def test_rewrite_when_the_model_is_down(ed, monkeypatch):
    import contextlib
    import writer
    from orchestrator import llm
    p = at_stage("script", fmt="anchor_vo")
    monkeypatch.setattr(store, "gpu", lambda use: contextlib.nullcontext())

    def down(*a, **k):
        raise llm.LLMUnavailable("down")
    monkeypatch.setattr(writer, "ask", down)
    assert code(ed.post(f"/api/projects/{p['id']}/rewrite", json={"scope": "all"})) == 503


def test_duplicate_from_library(ed):
    p = at_stage("done")
    q = ed.post(f"/api/library/lib-{p['id']}/duplicate").json()
    assert q["id"] != p["id"] and q["headline"].endswith("(copy)") and q["stage"] == "script" and "render" not in q
    assert all("voice" not in s for s in q["versions"]["vo_only"]) and q["visuals"] == {}
