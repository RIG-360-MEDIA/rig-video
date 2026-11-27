"""Machine-job logic (server/worker.py) with the GPU, the LLM, the voice and YouTube replaced by fakes:
numbers read aloud, the editor's re-voice notes, name re-spelling for searches, the anchor wall, stalled searches,
event dates, part-by-part search pipelining, and the daily run's chain: write -> approve itself -> voice + search ->
(after the check) keep VO only or give it an anchor."""
import contextlib
import datetime as dt
import time

import pytest

import store
import worker
from conftest import ARTICLE, at_stage, new_story


@pytest.fixture
def started(monkeypatch):
    calls = []
    monkeypatch.setattr(worker, "start_job", lambda pid, job, *a: calls.append((pid, job)))
    monkeypatch.setattr(store, "gpu", lambda use: contextlib.nullcontext())
    return calls


# ------------------------------------------------------------------ speech text

@pytest.mark.parametrize("text,said", [
    ("42 people", "forty-two people"), ("1,200 homes", "one thousand two hundred homes"), ("in 2026", "in twenty twenty-six"),
    ("3.5%", "three point five per cent"),
    ("Smith & Sons", "Smith and Sons"), ("rain - then floods", "rain, then floods"), ("101", "one hundred and one"),
    ("2,000,000", "two million"),
])
def test_numbers_are_written_out_for_the_voice(text, said):
    assert worker.spoken(text) == said


def test_names_found_in_a_story():
    nm = worker.story_names({"lt": {"kicker": "EUROPE"}}, "The European Union has approved aid for Ukraine. High Representative "
                            "Kaja Kallas said Russia's attacks continue. This package follows a NATO meeting on Monday.")
    assert {"European", "Ukraine", "Kaja", "Kallas", "Russia", "NATO", "Europe"} <= set(nm) and not {"High", "This", "Monday", "The"} & set(nm), nm


def test_anchor_wall_shows_the_right_shot():
    ss = [{"id": k, "kind": "anchor" if k[0] == "a" else "vo"} for k in ("a1", "v1", "a2", "v2", "a3")]
    sh = {"v1": ["v1s1", "v1s2"], "v2": ["v2s1"]}
    assert [worker.wall_shot(ss, i, sh) for i in (0, 2, 4)] == ["v1s1", "v1s2", "v2s1"]
    assert worker.wall_shot(ss, 4, {"v1": ["x"], "v2": []}) == "x" and worker.wall_shot(ss, 0, {}) is None


@pytest.mark.parametrize("note,want", [
    ("Slower", (0.7, 0.4, "x", 0.9)),
    ("Less flat. Faster", (0.9, 0.35, "x", 1.1)),
])
def test_revoice_notes(note, want):
    assert worker.asked(note, 0.7, 0.4, "x") == want


def test_revoice_spelling_and_pause():
    assert worker.asked("Fix a name. Lipetsk is LEE-petsk", 0.7, 0.4, "Drones hit Lipetsk today.")[2] == "Drones hit LEE-petsk today."
    assert worker.asked("Pause before the last line", 0.7, 0.4, "One. Two. Three.")[2] == "One. Two. ... Three."


def test_misspelled_names_are_respelled_for_search():
    t = ["WATCH: An explosion is heard in Chmielek as Russian missiles land in Poland"]
    assert worker.retry_lines("missile impact Hmielek Poland", "Russian missile lands in Poland", t) == ["missile impact Chmielek Poland", "missile impact Poland"]
    assert worker.retry_lines("missile impact Hmielek Poland", "Russian missile lands in Poland", []) == ["missile impact Poland"]
    assert worker.retry_lines("Russian missile Poland", "Russian missile lands in Poland", t) == []


def test_slow_search_is_waited_for_a_stalled_one_stops():
    class C:
        def __init__(self, seq):
            self.seq = iter(seq)

        def get(self, url):
            return type("R", (), {"json": lambda _s, x=next(self.seq): x})()
    mk = lambda n, st="analyzing": {"segments": [{"keywords": [{"status": st, "videos": [{"analyzed": True}] * n}]}], "clips": []}
    assert worker.poll(C([mk(0), mk(1), mk(2), mk(3, "done")]), "x", lambda x: worker.keywords_of(x)[0]["status"] == "done", every=0.01, most=0.015)
    with pytest.raises(worker.Say):
        worker.poll(C([mk(1)] * 50), "x", lambda x: False, every=0.01, most=0.05)


# ------------------------------------------------------------------ event date (which footage is "the event")

D = lambda s: dt.date.fromisoformat("2026-11-" + s)


def test_first_reported():
    q = worker.event_query("US Shoots Down Iranian Drones Targeting Bahrain Amid Escalating Middle East Tensions")
    news = [(D("17"), "Iran's Revolutionary Guard claims another attack on U.S. radar system in Bahrain"),
            (D("15"), "Iran claims drone attack on US military airbase in Bahrain"),
            (D("13"), "Bahrain: United States said it intercepted Iranian drone attacks"),
            (D("13"), "US says shot down two Iranian drones targeted at Bahrain"),
            (dt.date(2026, 6, 6), "US strikes Iranian sites after Iran launches drones in latest Gulf flare-up"),
            (D("10"), "Bahrain fishing fleet sees record catch")]
    assert worker.first_reported([q], news, D("14")) == D("13")
    assert worker.first_reported([q], news[:1] + news[2:3], D("14")) is None       # one report on a day is not enough
    assert worker.first_reported([q], news, D("12")) is None


def test_stated_dates():
    S = lambda t, made="2026-11-13": worker.stated_date(t, dt.date.fromisoformat(made))
    assert S("November 9, around 12:00") == D("09") and S("Around 5:45 AM on October 24, 2024.") == dt.date(2024, 10, 24)
    assert S("Shortly before midnight on a Thursday.") == D("12") and S("9th of November") == D("09")
    assert S("December 30") == dt.date(2025, 12, 30) and S("this week") is None


def test_stated_day_confirmed_by_reports():
    aliaga = [(D("09"), "Explosion at steel plant in western Turkey leaves 16 dead"), (D("09"), "Turkey steel factory blast kills 17"),
              (D("12"), "Death toll in steel plant blast rises to 19")]
    qs = ["The Silence After the Blast", "TURKEY STEEL PLANT BLAST DEATH TOLL"]
    assert worker.first_reported(qs, aliaga, D("10"), back=1) == D("09")
    assert worker.first_reported(qs, aliaga, D("13")) is None


# ------------------------------------------------------------------ anchor formats: part 2 searches while part 1 is cut

def test_search_pipelining(monkeypatch):
    ev = []
    P2 = {"id": "x", "format": "anchor_vo", "createdAt": "2026-11-20T09:00:00+05:30", "visuals": {"v1": {}, "v2": {}}, "_search": {}}
    monkeypatch.setattr(worker.store, "read", lambda pid: P2)
    monkeypatch.setattr(worker.store, "update", lambda pid, f: f(P2))
    monkeypatch.setattr(worker.store, "job", lambda *a, **k: None)
    monkeypatch.setattr(worker.store, "_lock", lambda path, **k: contextlib.nullcontext())
    monkeypatch.setattr(worker, "sv_client", lambda: None)
    monkeypatch.setattr(worker, "start_job", lambda *a: ev.append("check job"))
    monkeypatch.setattr(worker, "sections", lambda p: [{"id": "v1", "kind": "vo", "text": "a"}, {"id": "v2", "kind": "vo", "text": "b"}])
    monkeypatch.setattr(worker, "photos_for", lambda *a: [])
    monkeypatch.setattr(worker, "part", lambda pid, sid, text=None: None)
    fail = {"on": False}

    def fake_search(c, p, s, checks=None, **k):
        ev.append(f"search {s['id']}")

        def check():
            ev.append(f"check {s['id']} start")
            time.sleep(0.3)
            ev.append(f"check {s['id']} end")
            if s["id"] == "v2" and fail["on"]:
                raise RuntimeError("cut failed")
        return checks.submit(check)
    monkeypatch.setattr(worker, "search_section", fake_search)
    worker.step_search(P2)
    assert ev.index("search v2") < ev.index("check v1 end") < ev.index("check v2 start"), ev
    ev.clear()
    fail["on"] = True
    with pytest.raises(RuntimeError):
        worker.step_search(P2)                                      # a failed cut fails the job, never swallowed


# ------------------------------------------------------------------ the daily chain with a fake writer

BEATS = {"headline": "Floods in Kathmandu", "event_filmed": True, "event_search": "Kathmandu floods", "beats": [
    {"picture": "event", "shows": "flood water in Kathmandu streets", "search": "Kathmandu floods",
     "text": "Floods hit the Kathmandu valley after three days of heavy rain, officials said, damaging homes."},
    {"picture": "event", "shows": "army rescue teams in Lalitpur", "search": "Lalitpur rescue",
     "text": "Rescue teams from the army and police are searching for people trapped in Lalitpur and Bhaktapur."}]}


def test_vo_script_is_written_and_saved(monkeypatch, started):
    monkeypatch.setattr(worker.writer, "ask", lambda *a, **k: BEATS)
    p = new_story("vo_only")
    worker.step_write(store.read(p["id"]))
    q = store.read(p["id"])
    assert [b["id"] for b in q["versions"]["vo_only"]] == ["b1", "b2"]
    assert q["versions"]["vo_only"][0]["search"] == "Kathmandu floods" and q["_vo"]["eventFilmed"] is True
    assert q["stage"] == "script" and started == []                  # an editor's story waits for Approve


def test_daily_story_approves_itself_then_voice_and_search(monkeypatch, started):
    monkeypatch.setattr(worker.writer, "ask", lambda *a, **k: BEATS)
    p = new_story("vo_only", _autoApprove=True, _daily="2026-11-28")
    worker.step_write(store.read(p["id"]))
    q = store.read(p["id"])
    assert q["stage"] == "visuals" and "_autoApprove" not in q and q["edit"]["state"] == "waiting"
    assert [j for _, j in started] == ["voice", "search"]


def test_writer_that_returns_nothing_fails_with_a_message(monkeypatch, started):
    monkeypatch.setattr(worker.writer, "ask", lambda *a, **k: {"beats": []})
    p = new_story("vo_only")
    with pytest.raises(worker.Say, match="did not return"):
        worker.step_write(store.read(p["id"]))
    assert store.read(p["id"])["versions"]["vo_only"] == []


def test_too_short_source_is_refused(started):
    p = new_story("vo_only")
    store.update(p["id"], lambda q: q["source"].update(text="Too short."))
    with pytest.raises(worker.Say, match="too short"):
        worker.step_write(store.read(p["id"]))


def test_writer_busy_editor_story_fails_fast(monkeypatch, started):
    def busy(*a, **k):
        raise worker.writer.Busy("busy")
    monkeypatch.setattr(worker.writer, "ask", busy)
    with pytest.raises(worker.writer.Busy):
        worker.step_write(store.read(new_story("vo_only")["id"]))


def checked(text_cuts, foot_cuts, short=False):
    p = at_stage("review", _daily="2026-11-28", formatWhy={"by": "auto", "text": "", "at": ""})
    cuts = [{"kind": "post_or_document", "secs": 2.0}] * text_cuts + [{"kind": "footage", "secs": 2.0}] * foot_cuts
    store.update(p["id"], lambda q: q.update(edit={"state": "ready", "beats": [{"sectionId": "b1", "secs": 2.0 * len(cuts) + (5 if short else 0), "cuts": cuts}]}))
    return store.read(p["id"])


def test_mostly_filmed_story_stays_vo_only(started):
    p = checked(1, 3)                                               # 25% text shots
    worker.decide_type(p)
    q = store.read(p["id"])
    assert q["format"] == "vo_only" and q["formatWhy"]["decided"] and "no anchor" in q["formatWhy"]["text"] and started == []


def test_mostly_text_story_gets_an_anchor(started):
    p = checked(2, 2)                                               # 50% text shots
    worker.decide_type(p)
    q = store.read(p["id"])
    assert q["format"] == "anchor_vo" and q["formatWhy"]["decided"] and q["stage"] == "script" and [j for _, j in started] == ["write"]


def test_short_of_pictures_gets_an_anchor(started):
    p = checked(0, 3, short=True)
    worker.decide_type(p)
    assert store.read(p["id"])["format"] == "anchor_vo"


def test_type_is_decided_once_and_only_for_the_daily_run(started):
    p = checked(2, 2)
    store.update(p["id"], lambda q: q["formatWhy"].update(decided=True))
    worker.decide_type(store.read(p["id"]))
    e = at_stage("review")
    worker.decide_type(e)
    assert store.read(p["id"])["format"] == "vo_only" and store.read(e["id"])["format"] == "vo_only" and started == []
