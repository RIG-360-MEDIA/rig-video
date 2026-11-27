"""Story selection (orchestrator/select_stories.py), the logic after the database read: hard news only (never sports or
entertainment, never private tragedies), a pick needs 8+ outlets, mix caps per country and type, no two reports of
the same story, an 800-character article and a public DNL page; reserves fill a thin day."""
import datetime as dt

import pytest

from orchestrator import llm, select_stories as S

NOW = dt.datetime(2026, 11, 28, 6, 0, tzinfo=dt.timezone.utc)
BODY = "Body. " * 200


def cand(i, title, country="UA", outlets=10, hours=2, topic="WORLD", deck="", body=BODY, entity=None):
    return {"id": f"{i:08d}-0000-0000-0000-000000000000", "title": title, "deck": deck, "body": body, "topic": topic, "country": country,
            "sources": outlets, "articles": outlets, "last_seen": NOW - dt.timedelta(hours=hours), "first_seen": NOW - dt.timedelta(hours=hours + 5),
            "entity": entity, "entities": [], "members": {f"m{i}"}, "images": [], "recent3h": 1, "prior3h": 0, "tier1_share": 0.2,
            "followup": False, "editor": None, "src": {f"s{i}-{k}:{'IN' if k % 2 else 'GB'}" for k in range(outlets)}}


def event(c, category="war_conflict", keep=True):
    e = S.score(S.summarise([c], NOW))
    e["label"] = {"keep": keep, "category": category}
    return S.score(e)


@pytest.fixture(autouse=True)
def no_llm(monkeypatch):
    monkeypatch.setattr(llm, "available", lambda: False)


def test_keyword_rules_keep_hard_news_and_drop_soft_news():
    titles = {"a": ("Missile strike kills 12 in Kharkiv", "WORLD", True), "b": ("India beats Japan in Asian Games final", "SPORTS", False),
              "c": ("Bollywood actor's film breaks box office record", "ENTERTAINMENT", False),
              "d": ("Youth leaps to death from apartment tower", "INDIA", False), "e": ("Earthquake collapses buildings in Peru", "WORLD", True),
              "f": ("Football match ends in deadly crush", "SPORTS", False), "g": ("New smartphone sales record", "TECH", False)}
    events = [{"lead": {"id": k, "title": t, "deck": "", "topic": tp}, "country": "XX"} for k, (t, tp, _) in titles.items()]
    S.classify(events, log=lambda *a: None)
    assert {e["lead"]["id"]: e["label"]["keep"] for e in events} == {k: v[2] for k, v in titles.items()}


def test_llm_label_outside_hard_categories_is_dropped(monkeypatch):
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: {"labels": [{"id": "a", "keep": True, "category": "entertainment"},
                                                                      {"id": "b", "keep": True, "category": "war_conflict", "country": "IL"}]})
    events = [{"lead": {"id": "a", "title": "x", "deck": "", "topic": "WORLD"}, "country": "XX"},
              {"lead": {"id": "b", "title": "y", "deck": "", "topic": "SPORTS"}, "country": "XX"}]
    S.classify(events, log=lambda *a: None)
    assert [e["label"]["keep"] for e in events] == [False, False]            # sports topic never kept, whatever the model says


def test_country_corrected_by_the_label(monkeypatch):
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: {"labels": [{"id": "a", "keep": True, "category": "death_disaster", "country": "PA"}]})
    events = [{"lead": {"id": "a", "title": "Quake", "deck": "", "topic": "WORLD"}, "country": "IR"}]
    S.classify(events, log=lambda *a: None)
    assert events[0]["country"] == "PA" and events[0]["label"]["dnl_country"] == "IR"


def test_a_pick_needs_8_outlets_a_reserve_3():
    big, small = event(cand(1, "Missile strike on Kharkiv grid", outlets=12)), event(cand(2, "Flood in Assam villages", "IN", outlets=4))
    picks, reserves = S.pick([big, small], log=lambda *a: None)
    assert picks[0] is big and (small in picks or small in reserves)      # a thin day: a fitting reserve fills the 10
    tiny = event(cand(3, "Bus crash near Lima", "PE", outlets=2))
    picks, reserves = S.pick([tiny], log=lambda *a: None)
    assert picks == [] and reserves == []


def test_mix_caps_per_country():
    evs = [event(cand(i, f"Strike number {i} hits city {i} grid{i}", "UA", outlets=20 - i), "war_conflict") for i in range(6)]
    picks, reserves = S.pick(evs, log=lambda *a: None)
    assert sum(e["country"] == "UA" for e in picks) == S.PICK_CAPS[0]


def test_never_two_reports_of_the_same_story():
    a = event(cand(1, "Zaporizhzhia nuclear plant loses power after strike", outlets=20))
    b = event(cand(2, "Zaporizhzhia nuclear plant power cut, IAEA warns", outlets=15))
    picks, reserves = S.pick([a, b], log=lambda *a: None)
    assert a in picks and b not in picks + reserves


def test_short_article_or_dead_page_is_skipped():
    short = event(cand(1, "Missile strike on Odesa port", body="Too short."))
    killed = event(cand(2, "Dam burst floods Libyan town", "LY"))
    ok = event(cand(3, "Wildfire forces evacuations in Chile", "CL"))
    picks, _ = S.pick([short, killed, ok], log=lambda *a: None, live_fn=lambda sid: sid != killed["lead"]["id"])
    assert picks == [ok]


def test_already_made_stories_are_left_out():
    a, b = event(cand(1, "Missile strike on Odesa port")), event(cand(2, "Dam burst floods Libyan town", "LY"))
    picks, _ = S.pick([a, b], log=lambda *a: None, exclude={a["lead"]["id"]})
    assert picks == [b]


def test_rejected_events_are_never_picked():
    sport = event(cand(1, "Cup final ends in record win", outlets=40), "rule", keep=False)
    picks, reserves = S.pick([sport], log=lambda *a: None)
    assert picks == [] and reserves == []


def test_fresher_and_wider_coverage_scores_higher():
    old = event(cand(1, "Strike on Kyiv", hours=40, outlets=12))
    new = event(cand(2, "Strike on Lviv", hours=1, outlets=12))
    wide = event(cand(3, "Strike on Dnipro", hours=1, outlets=30))
    assert wide["score"] > new["score"] > old["score"]


def test_same_event_fragments_are_grouped():
    a = cand(1, "Earthquake of magnitude 7 strikes Peru coast", "PE")
    b = cand(2, "Peru earthquake magnitude 7 coast strikes", "PE")
    c = cand(3, "Election results announced in Ghana", "GH")
    groups = S.group_events([a, b, c], log=lambda *a: None)
    assert sorted(len(g) for g in groups) == [1, 2]


def test_published_pick_has_what_the_desk_reads():
    e = event(cand(1, "Missile strike on Odesa port"))
    pub = S._pub(e)
    assert {"event_id", "headline", "deck", "body", "label", "sources", "age_h", "country"} <= set(pub)
