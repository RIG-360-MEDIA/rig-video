"""Check: vision_check sends only the search's matched moments, shows the checker's PROGRESS lines on the part, and adds its
picks; a failed check cuts nothing. A local fake stands in for ssh to t8. python test_vision_progress.py"""
import datetime as dt, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../studio-app/pipeline"))
import worker

P = {"headline": "H", "visuals": {"v1": {}}}
notes, cuts = [], []
worker.store.read = lambda pid: P
worker.store.update = lambda pid, f: f(P)
worker.find = lambda p, sid: {"text": "T"}
worker.event_date = lambda p: dt.date(2026, 11, 17)
worker.story_facts = lambda p: []
worker.part = lambda pid, sid, text=None: notes.append(text)
worker.cut = lambda c, pid, sid, svp, picked: cuts.append(picked)
FAKE = r'''import json, sys
job = json.load(sys.stdin)
v = job[0]["videos"]
assert [x["id"] for x in v] == ["a"] and v[0]["moments"] == [[10, 20]], v   # b has no matched moment; checked ones not resent
for line in ("shots 0/3", "shots 3/3", "videos", "facts", "place"):
    print("PROGRESS v1", line, file=sys.stderr, flush=True)
print("noise", file=sys.stderr)
if sys.argv[1].startswith("fail"): sys.exit(1)
print(json.dumps({"picked": [{"video": "a", "start": 12, "end": 15, "relevance": 3, "shows": "x"}], "wrong_videos": []}))'''
found = lambda: [{"youtubeId": "a", "title": "A", "duration": 60, "moments": [{"start": 10, "end": 20}, {"start": 30, "end": 33, "checked": True}]},
                 {"youtubeId": "b", "title": "B", "duration": 60, "moments": []}]
worker.V8SSH = [sys.executable, "-c", FAKE]
out = worker.vision_check(None, "ok", "v1", {}, found())
assert notes == ["Checking clips", "Checking clips: 0 of 3 shots", "Checking clips: 3 of 3 shots", "Checking where each video was filmed",
                 "Checking the shots against the story facts", "Checking where the shots were filmed", "Cutting the checked clips", None], notes
assert out[0]["moments"][-1]["checked"] and cuts[0][0][1] == 2
notes.clear(); cuts.clear()
out = worker.vision_check(None, "fail", "v1", {}, found())
assert notes[-1] is None and not cuts and len(out[0]["moments"]) == 2
print("vision progress ok")

# step_search: part 2 searches while part 1's clip check runs (one check at a time), and a failed check fails the job
import contextlib, threading, time
ev, log_ = [], []
P2 = {"id": "x", "format": "anchor_vo", "createdAt": "2026-11-20T09:00:00+05:30", "visuals": {"v1": {}, "v2": {}}, "_search": {}}
worker.store.read = lambda pid: P2
worker.store.update = lambda pid, f: f(P2)
worker.store.job = lambda *a, **k: None
worker.store._lock = lambda path, **k: contextlib.nullcontext()
worker.sv_client = lambda: None
worker.start_job = lambda *a: ev.append("check job")
worker.sections = lambda p: [{"id": "v1", "kind": "vo", "text": "a"}, {"id": "v2", "kind": "vo", "text": "b"}]
worker.photos_for = lambda *a: []
worker.part = lambda pid, sid, text=None: None
def fake_search(c, p, s, checks=None, **k):
    ev.append(f"search {s['id']}")
    def check():
        ev.append(f"check {s['id']} start"); time.sleep(0.3); ev.append(f"check {s['id']} end")
        if s["id"] == "v2" and FAIL: raise RuntimeError("t8 down")
    return checks.submit(check)
worker.search_section = fake_search
FAIL = False
worker.step_search(P2)
assert ev.index("search v2") < ev.index("check v1 end") and ev.index("check v1 end") < ev.index("check v2 start"), ev
ev.clear(); FAIL = True
try:
    worker.step_search(P2); raise AssertionError("failed check was swallowed")
except RuntimeError:
    pass
print("search pipelining ok")
