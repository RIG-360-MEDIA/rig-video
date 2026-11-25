"""After the 9:16 conversion: does the vertical cut still show what the editor picked the shot for?
The vision model sees the original frame and the vertical frame at the same moment (the shot's key moment, if known, else
its middle) with the editor's description and the spoken line, and judges the picture only: an 8B model can't compare
text reliably (2026-11-22: it passed a lost headline and failed lost place labels), so text shots (kind
post_or_document) go to --fit by rule before this check. A small flash at the edge of a wide shot, or a caption, is easily cropped or
trimmed away: then the cut is made again with `vconv.py --fit` (the whole frame on a blurred copy, nothing cut off).

usage: python cropcheck.py src.mp4 out916.mp4 "what the shot shows" [key moment, s from the cut's start] [--line "spoken line"]
       -> prints {"ok": bool, "missing": str, "at": [s, ...]}
"""
import base64
import json
import os
import sys
import urllib.request

import cv2

VLM = [u for u in os.environ.get("VO_VLM", "http://100.72.225.89:11620/v1,http://100.95.0.11:11610/v1").split(",") if u]

ASK = """Two pictures of the same moment of a news video. Picture A is the original wide frame. Picture B is that frame after
it was reframed to vertical 9:16 for phones: B may cut off the sides, or show the whole frame small over a blurred copy.
The editor chose this shot because it shows: "{shows}".{line}
Judge only the picture and ignore all text: logos, tickers, captions, subtitles, place names and time stamps don't
count (text shots are kept whole before this check). Did B lose what matters for this shot and its line: the person,
the place, or the moment (a flash, smoke, a hit, a vehicle)? Something small but still visible in B is fine. "ok" is
true only when B still shows it.
Answer with JSON only:
{{"ok": true | false, "missing": "<what B lost, max 12 words; empty when ok>"}}"""


def frame(path, t):
    cap = cv2.VideoCapture(str(path))
    cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, t) * 1000)
    ok, f = cap.read()
    return f if ok else None


def jpg(img, width):
    h, w = img.shape[:2]
    img = cv2.resize(img, (width, round(h * width / w / 2) * 2), interpolation=cv2.INTER_AREA) if w > width else img
    return "data:image/jpeg;base64," + base64.b64encode(cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 88])[1].tobytes()).decode()


def vlm(content):
    body = json.dumps({"model": "vlm", "temperature": 0, "max_tokens": 200, "response_format": {"type": "json_object"},
                       "messages": [{"role": "user", "content": content}]}).encode()
    err = None
    for url in VLM:
        try:
            req = urllib.request.Request(f"{url}/chat/completions", body, {"Content-Type": "application/json"})
            d = json.loads(urllib.request.urlopen(req, timeout=300).read())
            return json.loads(d["choices"][0]["message"]["content"] or "{}")
        except Exception as e:                                   # this server is down or busy: try the next
            err = e
    raise RuntimeError(f"no vision server answered: {err}")


def check(src, out, shows, key=None, line=""):
    """{"ok", "missing", "at"}: judged at the key moment (else the middle).
    A check that cannot run says ok=False, so the safe whole-frame version is used."""
    cap = cv2.VideoCapture(str(src))
    dur = (cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0) / (cap.get(cv2.CAP_PROP_FPS) or 25)
    ts = [round(min(max(key if key is not None else dur / 2, 0.05), max(0.05, dur - 0.05)), 2)]   # the key moment only: a
                                                                 # brief flash is gone by the middle, in A too
    for t in ts:
        a, b = frame(src, t), frame(out, t)
        if a is None or b is None:
            return {"ok": False, "missing": "could not read the frames", "at": ts}
        try:
            r = vlm([{"type": "text", "text": ASK.format(shows=shows, line=f'\nThe line spoken over it: "{line}"' if line else "")}, {"type": "text", "text": "Picture A:"},
                     {"type": "image_url", "image_url": {"url": jpg(a, 1280)}}, {"type": "text", "text": "Picture B:"},
                     {"type": "image_url", "image_url": {"url": jpg(b, 1080)}}])
        except Exception as e:
            return {"ok": False, "missing": f"check failed: {e}"[:120], "at": ts}
        if r.get("ok") is not True:
            return {"ok": False, "missing": str(r.get("missing") or "")[:120], "at": ts}
    return {"ok": True, "missing": "", "at": ts}


if __name__ == "__main__":
    a = sys.argv[1:]
    line = a.pop(a.index("--line") + 1) if "--line" in a else ""
    a = [x for x in a if x != "--line"]
    print(json.dumps(check(a[0], a[1], a[2], float(a[3]) if len(a) > 3 else None, line)))
