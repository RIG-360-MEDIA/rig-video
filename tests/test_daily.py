"""The daily run (08:00): today's main picks become 1-minute VO-only stories that approve themselves; once a day; never
two stories from one pick; reserves only by hand; the manual start for chosen picks."""
import store
import app as api
from conftest import jobs, make_user, new_story, write_selection


def test_daily_run_makes_the_main_picks(spawned):
    make_user(role="admin")
    picks, reserves = write_selection(["A", "B"], ["R"])
    started = api.daily_start()
    ps = {p["_pick"]: p for p in store.all_projects("dnl")}
    assert set(ps) == set(picks) and len(started) == 2
    for p in ps.values():
        assert p["format"] == "vo_only" and p["targetSeconds"] == 60 and p["_autoApprove"] and p["_daily"] and p["formatWhy"]["by"] == "auto"
    assert jobs(spawned) == ["write", "write"]


def test_once_a_day(spawned):
    make_user(role="admin")
    write_selection(["A"])
    api.daily_start()
    assert api.daily_start() == [] and len(store.all_projects()) == 1


def test_no_selection_no_run(spawned):
    make_user(role="admin")
    assert api.daily_start() == [] and not (store.DATA / "daily").exists()


def test_never_two_stories_from_one_pick(spawned):
    make_user(role="admin")
    picks, _ = write_selection(["A", "B"])
    new_story(_pick=picks[0])                                       # an editor already made pick A by hand
    api.daily_start()
    assert sorted(p.get("_pick") for p in store.all_projects()) == sorted(picks)


def test_by_hand_for_chosen_picks_incl_reserves(ed, spawned):
    picks, reserves = write_selection(["A", "B"], ["R"])
    r = ed.post("/api/daily/start", json={"pickIds": [reserves[0]]}).json()
    assert len(r["started"]) == 1 and store.read(r["started"][0])["_pick"] == reserves[0]
    assert ed.post("/api/daily/start", json={"pickIds": [reserves[0]]}).json()["started"] == []   # already made
    assert ed.post("/api/daily/start", json={}).status_code == 400


def test_by_hand_is_dnl_only(outsider):
    write_selection(["A"])
    assert outsider.post("/api/daily/start", json={"pickIds": ["00000001"]}).status_code == 400
