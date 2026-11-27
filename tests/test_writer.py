"""The script writer's code checks (server/writer.py): timing plan, section order, every number and name must come
from the article, VO-only beat rules; and the writer's GPU-busy detection."""
import http.server
import json
import threading
import time

import pytest

import writer


def test_plan():
    assert writer.plan(60, 328 / 24 - 0.7, 2.85)[:2] == (3, 2)
    apps, vos, a, v = writer.plan(120, 13, 2.85)
    assert vos == apps - 1 and a == round(13 * 2.85)
    assert writer.plan(20, 13, 2.85)[:2] == (1, 0) and writer.plan(6000, 13, 2.85)[0] == 10


def test_order():
    assert writer.order_ok([{"kind": k} for k in ("anchor", "vo", "anchor")], 2, 1)
    assert not writer.order_ok([{"kind": k} for k in ("vo", "anchor", "anchor")], 2, 1)
    assert not writer.order_ok([{"kind": "anchor"}], 2, 1)


def test_facts_must_come_from_the_article():
    art = "Seven people died on November 11 in Zvenigovsky district. Police say 1,144 incidents."
    sc = {"sections": [{"kind": "anchor", "text": "Seven people have died in Zvenigovsky. Police say 1,144 incidents on Tuesday."}],
          "headline": "7 dead", "lt": {"kicker": "MARI EL"}, "ticker": ["12 hurt"]}
    got = writer.notes(sc, art, 12, 30)
    assert any("Tuesday" in x for x in got) and any("12" in x for x in got), got
    assert not any("1,144" in x or "Zvenigovsky" in x or "'7'" in x for x in got), got


def test_small_numbers_written_as_words_count():
    assert writer.fact_notes("x", "3 people", "three people were hurt", set()) == []
    assert writer.fact_notes("x", "21 people", "twenty-one", set()) != []


def test_demonyms_match_the_country():
    assert writer.in_text("Iranian", "iran said") and writer.in_text("Armenian", "armenia") and not writer.in_text("Peruvian", "chile")


def test_vo_beat_rules():
    vo = {"supported_seconds": 30, "pictured_date": "", "beats": [
        {"picture": "archive", "shows": "tension", "search": "Kerch bridge attack on Tuesday 2026", "text": "Tension remains on Tuesday. 12 boats, 40 drones."},
        {"picture": "event", "shows": "smoke over the Kerch bridge", "search": "Kerch bridge strike",
         "text": "Ukraine says its forces have struck the Kerch bridge, which links Russia to occupied Crimea, police say."}]}
    got = writer.vo_notes(vo, "Ukraine struck the Kerch bridge linking Russia to occupied Crimea with drones, police said.", 30)
    for want in ("Beat 1 is archive", "the number 12", "more than one number", "'Tuesday'", "search 'Kerch", "too short", "not something a camera"):
        assert any(want in x for x in got), (want, got)
    assert any(x.startswith("event_search ''") for x in got) and not any(x.startswith("Beat 2") for x in got), got


def test_vo_quote_as_archive_and_named_people():
    g = writer.vo_notes({"beats": [{"picture": "archive", "shows": "Kosiniak-Kamysz at a podium", "search": "Kosiniak-Kamysz Poland",
                                    "text": "Deputy Prime Minister Wladyslaw Kosiniak-Kamysz has called the strike a provocation."}]}, "", 30)
    assert any("not archive" in x for x in g), g
    g = writer.vo_notes({"supported_seconds": 30, "event_filmed": False, "beats": [{"picture": "archive", "shows": "Tedros Ghebreyesus speaking",
                         "search": "WHO measles", "text": "Vaccination rates have fallen to 92 percent, says the CNAAP."}]}, "vaccination 92 percent CNAAP", 30)
    assert any("check the line is about them" in x for x in g) and any("CNAAP" in x for x in g), g


def test_vo_length_against_the_asked_seconds():
    beat = {"picture": "event", "shows": "smoke over the Kerch bridge", "search": "Kerch bridge strike"}
    line = lambda n: " ".join(["words"] * n)
    assert any("play about 20 s" in x for x in writer.vo_notes({"beats": [{**beat, "text": line(58)}]}, "", 30))
    assert not any(" s, the video is" in x for x in writer.vo_notes({"beats": [{**beat, "text": line(88)}]}, "", 30))
    assert any("cut to about" in x for x in writer.vo_notes({"supported_seconds": 26, "beats": [{**beat, "text": line(110)}]}, "", 30))


def test_pictured_date_only_a_real_earlier_event():
    assert writer.vo_pictured_date({"pictured_date": "2025-10-17"}, "riots on 17 October", "2025-11-19") == "2025-10-17"
    assert writer.vo_pictured_date({"pictured_date": "2026-11-15"}, "on November 15", "2026-11-17") == ""
    assert writer.vo_pictured_date({"pictured_date": "2023-06-21"}, "the zoo said", "2026-11-17") == ""
    assert writer.vo_pictured_date({"pictured_date": "garbage"}, "", "2026-11-17") == ""


# ------------------------------------------------------------------ busy detection against a local fake writer

class H(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        if self.server.fast is None:
            time.sleep(3)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for ch in ['{"a"', ': 1', '}'] * (1 if self.server.fast else 40):
            self.wfile.write(b"data: " + json.dumps({"choices": [{"delta": {"content": ch}}]}).encode() + b"\n\n")
            self.wfile.flush()
            time.sleep(0 if self.server.fast else 0.5)
        self.wfile.write(b"data: [DONE]\n\n")

    def log_message(self, *a):
        pass


@pytest.fixture
def fake_writer(monkeypatch):
    def serve(fast):
        s = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        s.fast = fast
        threading.Thread(target=s.serve_forever, daemon=True).start()
        monkeypatch.setenv("LLM_PROVIDERS", json.dumps([{"name": "t3", "base_url": f"http://127.0.0.1:{s.server_port}/v1", "key_env": "K", "model": "w"}]))
        monkeypatch.setenv("K", "x")
    monkeypatch.setattr(writer, "CHECK_AFTER_S", 2)
    monkeypatch.setattr(writer, "MIN_TPS", 6)
    return serve


def test_fast_writer_answers(fake_writer):
    fake_writer(True)
    assert writer.ask("s", "u", {}, 10) == {"a": 1}


def test_slow_writer_is_busy(fake_writer):
    fake_writer(False)
    with pytest.raises(writer.Busy, match="busy"):
        writer.ask("s", "u", {}, 10)


def test_silent_writer_is_busy(fake_writer, monkeypatch):
    monkeypatch.setattr(writer, "FIRST_TOKEN_S", 1)
    fake_writer(None)
    with pytest.raises(writer.Busy):
        writer.ask("s", "u", {}, 10)
