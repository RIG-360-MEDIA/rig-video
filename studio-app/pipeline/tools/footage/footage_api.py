"""Footage step: drive the footage repo's backend (start_backend.sh, localhost:8787) through its Footage API the way an
editor uses the Footage tab (baseline/FOOTAGE_REPO_USAGE.md):
  one project per beat (a dated one-segment script) -> its suggested keywords (any with a wrong year dropped) + one
  dated keyword of ours per beat -> fetch -> edit plan -> download the top `--picks` moments per segment (one per video).
Writes <out>/project.json (every video, verdict, moment, the edit plan) and <out>/clips/<segment>_<n>.mp4 + clips.json.

usage (repo venv on trijya-7): footage_api.py <beats.json> <out_dir> --date YYYY-MM-DD --place PLACE [--picks 4] [--suggested 2]
  beats.json = {"title": "...", "beats": [{"id": "v1", "text": "...", "keyword": "our dated keyword"}, ...]}
"""
import argparse, json, pathlib, re, sys, time
import httpx

B = "http://127.0.0.1:8787/api"
SV = pathlib.Path.home() / "anchor-studio" / "repos" / "social_verifier" / "backend"


def login():
    sys.path.insert(0, str(SV))
    from app.core.auth import AUTH_PASSWORD, AUTH_USERNAME   # the backend's own single account
    tok = httpx.post(f"{B}/auth/login", json={"username": AUTH_USERNAME, "password": AUTH_PASSWORD}, timeout=30).json()["token"]
    return httpx.Client(headers={"Authorization": f"Bearer {tok}"}, timeout=120)


LIVE = re.compile(r"\bLIVE\b|\blive ?stream|\b24/7\b", re.I)


def briefs(text, most=3):
    """A footage brief as separate searches: "rallies, polling stations; tankers in Hormuz" -> 3 keywords (at most `most`; the backend's own suggestions run too)."""
    items = [x.strip(" .") for x in re.split(r"[,;]|\bthen\b", text) if len(x.strip(" .")) > 2]
    return items[:most] or [text]


def poll(c, pid, done, every=10, label=""):
    t0 = time.time()
    while True:
        p = c.get(f"{B}/footage/projects/{pid}").json()
        if done(p):
            return p
        if label:
            print(f"  {label} {time.time() - t0:.0f}s", flush=True)
        time.sleep(every)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("beats"); ap.add_argument("out")
    ap.add_argument("--date", required=True); ap.add_argument("--place", required=True)
    ap.add_argument("--picks", type=int, default=4)
    ap.add_argument("--suggested", type=int, default=2, help="how many of its suggested keywords to run per beat (LLM budget)")
    a = ap.parse_args()
    spec, out = json.load(open(a.beats)), pathlib.Path(a.out)
    (out / "clips").mkdir(parents=True, exist_ok=True)
    year = a.date[:4]
    c = login()
    # One project per beat: each script is one beat, so the backend's LLM has nothing to split (a small local model
    # mis-splits a multi-beat script). The dateline keeps its keywords on the right date.
    pids, seg_of, run = {}, {}, []
    for b in spec["beats"]:
        script = f"{a.place.upper()}, {a.date} - news report. Events of {a.date}.\n\nSEGMENT 1 — {b['text']}\n"
        pids[b["id"]] = c.post(f"{B}/footage/projects", json={"mode": "script", "title": f"{spec['title']} {b['id']}",
                                                              "script": script}).json()["id"]
    for bid, pid in list(pids.items()):
        p = poll(c, pid, lambda p: p["status"] != "analyzing")
        b = next(x for x in spec["beats"] if x["id"] == bid)
        if not p["segments"]:   # local LLM can abort ("token repeat limit") and leave no segment: one fresh project, else skip
            script = f"{a.place.upper()}, {a.date} - news report. Events of {a.date}.\n\nSEGMENT 1 — {b['text']}\n"
            pid = pids[bid] = c.post(f"{B}/footage/projects", json={"mode": "script", "title": f"{spec['title']} {bid} retry",
                                                                   "script": script}).json()["id"]
            p = poll(c, pid, lambda p: p["status"] != "analyzing")
            if not p["segments"]:
                print(f"  {bid}: no segment after a retry, skipped", flush=True); del pids[bid]; continue
        s = next((x for x in p["segments"] if b["text"][:40] in x["script_excerpt"]), p["segments"][-1])
        seg_of[bid] = s
        mine = [f"{k} {s['title']} {year}" if len(k.split()) < 3 else f"{k} {year}"    # an editor's list "rallies, polling stations; ..."
                for k in briefs(b["keyword"])]                     # = one dated search each; a bare "rallies" gets the topic
        for kw in mine:
            c.post(f"{B}/footage/projects/{pid}/segments/{s['id']}/keywords", json={"text": kw})
        s = next(x for x in c.get(f"{B}/footage/projects/{pid}").json()["segments"] if x["id"] == s["id"])
        ours = [k for k in s["keywords"] if k["text"] in mine]
        sug = [k for k in s["keywords"] if k not in ours and (not re.search(r"\b(19|20)\d\d\b", k["text"]) or year in k["text"])]
        keep = sug[:a.suggested if len(ours) < 2 else 1 if len(ours) < 3 else 0] + ours   # its own only to fill up to 3 (time)
        c.post(f"{B}/footage/projects/{pid}/batches", json={"keyword_ids": [k["id"] for k in keep]})
        run += [k["id"] for k in keep]
        print(" BEAT", bid, s["title"], "|", [k["text"] for k in keep], flush=True)
    done = lambda p: all(k["status"] in ("done", "error") for s in p["segments"] for k in s["keywords"] if k["id"] in run)
    for bid, pid in pids.items():
        poll(c, pid, done, every=30, label=f"keywords {bid}")
    picks, dumps = [], {}
    for bid, pid in pids.items():
        c.post(f"{B}/footage/projects/{pid}/edit-plan")
        p = poll(c, pid, lambda p: (p["edit_plan"] or {}).get("status") != "building")
        s = next(x for x in p["segments"] if x["id"] == seg_of[bid]["id"])
        ms = sorted(((m, v) for k in s["keywords"] for v in k["videos"] for m in v["moments"]), key=lambda x: -x[0].get("score", 0))
        seen, titles, want = set(), set(), []
        for m, v in ms:
            t = re.sub(r"\W+", " ", v["title"].lower()).strip()
            if v["video_id"] in seen or t in titles or LIVE.search(v["title"]):   # one moment per video; reuploads and live streams out
                continue
            seen.add(v["video_id"]); titles.add(t)
            want.append({"video_id": v["video_id"], "video_title": v["title"], "segment_position": s["position"],
                         "label": f"{bid}_{len(seen)}", "start": m["start"], "end": m["end"]})
            picks.append({"beat": bid, "n": len(seen), "video_id": v["video_id"], "title": v["title"], "channel": v["channel"],
                          "relevance": v["relevance"], "score": m.get("score"), "estimated": bool(m.get("estimated")),
                          "start": m["start"], "end": m["end"], "shows": m.get("description", ""), "project": pid})
            if len(seen) == a.picks:
                break
        c.post(f"{B}/footage/projects/{pid}/clips", json={"clips": want})
    for bid, pid in pids.items():
        p = poll(c, pid, lambda p: not any(x["status"] in ("queued", "downloading") for x in p["clips"]), label=f"downloads {bid}")
        dumps[bid] = p
        files = {(cl["video_id"], cl["start_seconds"]): cl for cl in p["clips"]}
        for pk in (x for x in picks if x["beat"] == bid):
            cl = files.get((pk["video_id"], pk["start"]))
            pk["status"] = cl["status"] if cl else "missing"
            if cl and cl["status"] == "done":
                dst = out / "clips" / f"{pk['beat']}_{pk['n']}.mp4"
                dst.write_bytes(c.get(f"{B}/footage/clips/{cl['id']}/file").content); pk["file"] = str(dst)
    json.dump(dumps, open(out / "project.json", "w"), indent=1, ensure_ascii=False)
    json.dump(picks, open(out / "clips.json", "w"), indent=1, ensure_ascii=False)
    vids = [v for p in dumps.values() for s in p["segments"] for k in s["keywords"] for v in k["videos"]]
    print(f"videos {len(vids)}, with transcript {sum(v['has_transcript'] for v in vids)}; "
          f"clips {sum(pk['status'] == 'done' for pk in picks)}/{len(picks)}", flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
