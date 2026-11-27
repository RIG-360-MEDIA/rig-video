"""The browser tests' server: the real API + the built site on 127.0.0.1:8799 over a throwaway data folder with one
account and stories at every stage. No machine job can run (the tools Python is /bin/false).
usage: python tests/e2e/serve.py   (after the site is built: web/dist is copied to dist/ like a release does)"""
import datetime as dt
import os
import pathlib
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
os.environ["STUDIO_DATA"] = tempfile.mkdtemp(prefix="rv-e2e-")
os.environ["ANCHOR_TOOLS_PY"] = "/bin/false"
os.environ["RIGVIDEO_DAILY_AT"] = "23:59"          # own picks added in the tests wait for the daily run (deterministic)
sys.path.insert(0, str(HERE.parent))
import conftest as c  # noqa: E402  (sets the safe environment, then imports the app)
import store  # noqa: E402

store.adduser("e2e@rig.test", "Eddie", "admin", "dnl", c.PASSWORD)
c.write_selection(["Floods hit Kathmandu valley", "Missile strike on Kharkiv grid"], ["Wildfire forces evacuations in Chile"])
old = (store.now() - dt.timedelta(days=2)).isoformat(timespec="seconds")   # finished long ago: no automatic upload
ids = {}
for name, stage, head in (("script", "script", "Script stage story"), ("visuals", "visuals", "Visuals stage story"),
                          ("review", "review", "Review stage story"), ("done", "done", "Finished story to remake"),
                          ("discard", "done", "Finished story to discard"), ("public", "done", "Already public story")):
    p = c.at_stage(stage, headline=head)
    if stage == "done":
        store.update(p["id"], lambda q: (q["final"].update(builtAt=old),
                                         q.setdefault("posts", {}).update(youtube={"state": "awaiting", "videoId": "Yawait", "title": head, "description": ""})))
    ids[name] = p["id"]
store.update(ids["public"], lambda q: q["posts"].update(youtube={"state": "posted", "videoId": "Ypub", "title": "x", "description": ""}))
(pathlib.Path(os.environ["STUDIO_DATA"]) / "ids.txt").write_text(" ".join(f"{k}={v}" for k, v in ids.items()))
print("E2E_IDS", " ".join(f"{k}={v}" for k, v in ids.items()), flush=True)

import uvicorn  # noqa: E402
uvicorn.run(c.api.app, host="127.0.0.1", port=8799, log_level="warning")
