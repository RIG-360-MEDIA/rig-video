"""Anchor video finishing helpers used by tools/sourcetrack/assemble_*.py: refine_quad() finds the studio wall's corners
on the rendered plate (shifted up to +-20 px to the best edge fit; skipped if alignment is poor, so H3's own wall stays),
lt_story() builds the graphics package input for lt_remotion/apply_broadcast_package.mjs, plus NODE, CHROME_LIBS
(Remotion's headless Chrome libraries) and OUTRO (the DNL outro)."""
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


