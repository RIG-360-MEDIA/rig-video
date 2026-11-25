"""POST (CPU, runs while the next story renders): colour-lock -> wall composite -> LT package + DNL outro.

Wraps the existing tools (pipeline/tools/colorlock.py, wall_comp.py, lt_remotion/apply_broadcast_package.mjs).
Wall corners are stored per set and re-verified on every render: the stored quad is shifted up to +-20 px to the
best edge alignment with the plate; if alignment is poor the composite is SKIPPED (H3's own wall stays) and flagged -
a misplaced overlay is worse than none.
"""
import json
import os
import pathlib
import subprocess

import cv2
import numpy as np

from .common import APP, PIPE, TOOLS_PY

SETS = {   # ponytail: one set today; quad measured on the plate, refined per render. Re-measure if the plate changes.
    "set7": {"plate": APP / "bg_options" / "option_C_tall_room_set" / "plate_1280x736.png",
             "quad": [[717, 232], [1270, 182], [1272, 512], [717, 500]], "min_align": 0.6},
}
OUTRO = APP / "DNL Outro.mp4"
CHROME_LIBS = pathlib.Path.home() / ".local" / "chrome-libs" / "root" / "usr" / "lib" / "x86_64-linux-gnu"
NODE = os.environ.get("ANCHOR_NODE", str(next(iter(sorted(pathlib.Path.home().glob(".nvm/versions/node/v*/bin/node"))), "node")))


def boundaries(seed_job, chain_job):
    """Shot boundaries in frames: seed length, then each shot adds L-39 (context overlap)."""
    s = json.load(open(seed_job)); s = s.get("prompt", s)
    g = json.load(open(chain_job)); g = g.get("prompt", g)
    cum, out = s["136"]["inputs"]["length"], []
    for sh in json.loads(g["1700"]["inputs"]["plan_json"])["shots"]:
        out.append(cum)
        cum += sh["length"] - 39
    return out, cum     # starts of shots 2..n, total frames


def refine_quad(video, set_name="set7", log=print):
    """Grayscale correlation of the plate vs a render frame along the wall border, over +-20 px shifts.
    Calibrated 2026-10-03 on set7_fbc: correct 0.94, 12 px off -0.13, other set -0.13 -> threshold 0.6."""
    st = SETS[set_name]
    g = lambda im: cv2.cvtColor(im, cv2.COLOR_BGR2GRAY).astype(np.float32)
    P = g(cv2.resize(cv2.imread(str(st["plate"])), (1280, 736)))
    cap = cv2.VideoCapture(str(video)); cap.set(cv2.CAP_PROP_POS_FRAMES, 12); ok, fr = cap.read()
    if not ok:
        return None
    F = g(fr)
    q0 = np.float32(st["quad"])
    band = np.zeros(F.shape, np.uint8)
    cv2.polylines(band, [np.int32(q0)], True, 255, 24)
    m = band > 0
    b = F[m] - F[m].mean()

    def ncc(dx, dy):
        Ps = cv2.warpAffine(P, np.float32([[1, 0, dx], [0, 1, dy]]), (P.shape[1], P.shape[0]))
        a = Ps[m] - Ps[m].mean()
        return float((a * b).sum() / np.sqrt((a * a).sum() * (b * b).sum() + 1e-9))

    score, dx, dy = max((ncc(dx, dy), dx, dy) for dx in range(-20, 21, 2) for dy in range(-20, 21, 2))
    log(f"wall quad correlation {score:.2f} at shift ({dx},{dy})")
    if score < st["min_align"]:
        return None
    return " ".join(f"{x + dx:.0f},{y + dy:.0f}" for x, y in q0)


def lt_story(meta, ticker_items):
    return {"anchorName": meta["anchor_name"], "anchorTitle": "News Anchor", "headline": meta["lt_headline"],
            "location": meta["location"], "logo": str(APP / "lt_remotion" / "assets" / "logo.png"), "outro": str(OUTRO),
            "lowerThird": {"kicker": meta["kicker"], "subline": meta.get("subline", ""), "holdSeconds": 6, "repeatEverySeconds": 20},
            "ticker": {"tag": "LIVE", "speedPxPerSecond": 90, "items": ticker_items}, "nameTag": {"holdSeconds": 4.5}}


def run(raw, work, bounds, wall_video, meta, ticker_items, log=print):
    """raw chain video -> work/final.mp4. Returns dict of produced paths + flags."""
    work = pathlib.Path(work)
    work.mkdir(parents=True, exist_ok=True)
    flags = []
    if not OUTRO.exists():
        raise FileNotFoundError(f"DNL outro missing at {OUTRO} - final would be < 60 s")
    cl = work / "colorlocked.mp4"
    subprocess.run([TOOLS_PY, str(PIPE / "tools" / "colorlock.py"), str(raw), str(cl), ",".join(map(str, bounds))],
                   check=True, capture_output=True)
    quad = refine_quad(cl, log=log)
    walled = work / "walled.mp4"
    if quad:
        subprocess.run([TOOLS_PY, str(PIPE / "tools" / "wall_comp.py"), str(cl), str(wall_video), "0", str(walled), quad, "clean"],
                       check=True, capture_output=True)
    else:
        flags.append("wall composite skipped: wall not where the set says (kept H3's own wall)")
        walled = cl
    story = work / "lt_story.json"
    story.write_text(json.dumps(lt_story(meta, ticker_items), indent=2, ensure_ascii=False))
    final = work / "final.mp4"
    env = dict(os.environ, PATH=str(pathlib.Path(NODE).parent) + os.pathsep + os.environ.get("PATH", ""))
    if CHROME_LIBS.exists():   # NSS libs unpacked in user space (no OS packages installed) for Remotion's headless Chrome
        env["LD_LIBRARY_PATH"] = str(CHROME_LIBS) + os.pathsep + env.get("LD_LIBRARY_PATH", "")
    subprocess.run([NODE, str(APP / "lt_remotion" / "apply_broadcast_package.mjs"), str(walled), str(story), str(final)],
                   check=True, cwd=APP, env=env, capture_output=True)
    return {"colorlocked": cl, "walled": walled, "final": final, "flags": flags, "quad": quad}
