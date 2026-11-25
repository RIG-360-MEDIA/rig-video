"""Check: step_search (anchor formats) searches part 2 while part 1's clips are being cut (one at a time), and a failed
cut fails the search job. A fake footage backend stands in. python test_search_pipelining.py"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../studio-app/pipeline"))
import worker

# step_search: part 2 searches while part 1's clips are cut (one part at a time), and a failed cut fails the job
import contextlib, time
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
        if s["id"] == "v2" and FAIL: raise RuntimeError("cut failed")
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
