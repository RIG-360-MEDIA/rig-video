"""VO-only 9:16 converter (prototype v1). One clip in -> 1080x1920, 24 fps, H.264, no audio, plus a JSON sidecar.

Rules come from docs/rig-video/vertical-converter/GOLDEN_SET.md (RIG-NEWS-AI- repo). Five models, all MIT/Apache:
TransNetV2 (cuts), RF-DETR Small (people + objects), YuNet (faces), UNISAL (saliency), RapidOCR det (text boxes).
Per shot the layout is one of:
  PASS   already 9:16 or narrower (after bars are removed): scaled, never cropped
  LOCKED one fixed full-height 9:16 crop for the whole shot (default: a steady frame)
  TRACK  the crop follows the subject, smoothed, speed-limited, never across a cut
  FIT    the whole frame over a blurred, darkened copy of itself (universal fallback)
  SPLIT  two far-apart people, stacked (strict gate)
  SWEEP  stills: FIT with a slow push-in
v1 (2026-11-19): text cut by a crop edge is blurred over (graphics as a band, scene text as a box, checked by OCR on the
output), large cut scene text -> FIT; picture-in-picture people are never the subject; subjects ranked by size + saliency.
usage: python vconv.py in.mp4 out.mp4 [--preview preview.mp4] [--fit]   (--fit: whole frame on blur, nothing cut off)
"""
import collections
import json
import os
import pathlib
import re
import subprocess
import sys
import time

import cv2
import numpy as np
import torch
from concurrent.futures import ThreadPoolExecutor

HERE = pathlib.Path(__file__).resolve().parent
MODELS = HERE / "models"
_SHARED = pathlib.Path.home() / "anchor-studio/repos/ffmpeg-shared/current/bin/ffmpeg"
FFMPEG = os.environ.get("VCONV_FFMPEG") or (str(_SHARED) if _SHARED.exists() else "ffmpeg")   # any ffmpeg with NVENC
FPS, OW, OH = 24, 1080, 1920
AW = 640                          # analysis width
MAX_UP = 2.0                      # Q9: a crop may be upscaled at most 2x, else FIT
SAMPLE = 6                        # analyse every 6th frame (4 per second)
SPEED = 0.15                      # Q31: max crop speed, share of frame width per second
LOCK_TRAVEL = 0.15                # Q32: subject travel under this -> LOCKED
CONF_MIN = 0.5                    # Q38
TEXT_HEAVY = 0.08                 # Q28: OCR text area share -> FIT
TRIM_MAX = 0.15                   # Q30: FIT may trim at most 15% off an edge to drop a logo/ticker
TEXT_SAMPLES = 6                  # OCR samples per shot (text found anywhere in the shot is guarded)
VERIFY_FRAMES = 4                 # Q27 check: OCR on this many output crops per shot
BIG_TEXT = 0.06                   # scene text this tall (share of height) carries the story: cut -> FIT, not blurred
TEXT_SCORE = 0.6                  # OCR detection score below this is not text
TEXT_MAX_H = 0.10                 # a detected "text line" taller than this share of the image is a texture
STATIC = 0.006                    # a box whose edges move less than this share of width is still
RENDER_THREADS = int(os.environ.get("VCONV_THREADS", "16"))   # output frames composed in parallel
SAL_KEEP = 0.35                   # a crop must keep at least this share of the shot's saliency, else FIT
DEV = "cuda" if torch.cuda.is_available() else "cpu"
TIMES = {}                        # seconds per stage for the current clip (reset by convert)


class tick:
    def __init__(self, k):
        self.k = k

    def __enter__(self):
        self.t = time.perf_counter()

    def __exit__(self, *a):
        TIMES[self.k] = TIMES.get(self.k, 0.0) + time.perf_counter() - self.t


# ------------------------------------------------------------------ input

def probe(src):
    j = json.loads(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                                   "stream=width,height:stream_side_data=rotation:format=duration", "-of", "json", src],
                                  capture_output=True, text=True, check=True).stdout)
    s = j["streams"][0]
    rot = abs(int(next((d.get("rotation", 0) for d in s.get("side_data_list", [])), 0))) % 180
    w, h = (s["height"], s["width"]) if rot == 90 else (s["width"], s["height"])
    return w, h, float(j["format"].get("duration") or 0)


def frames(src, vf, w, h):
    """Decoded frames (BGR uint8) after the ffmpeg filter chain vf, at w x h. Rotation is applied by ffmpeg itself."""
    p = subprocess.Popen([FFMPEG, "-v", "error", "-i", src, "-vf", f"{vf},scale={w}:{h}:flags=lanczos,format=bgr24",
                          "-f", "rawvideo", "-"], stdout=subprocess.PIPE)
    n = w * h * 3
    while True:
        b = p.stdout.read(n)
        if len(b) < n:
            break
        yield np.frombuffer(b, np.uint8).reshape(h, w, 3)
    p.wait()


def black_bars(src, w, h):
    """Q7: union of picture area across the clip (cropdetect, reset=0 keeps the largest box)."""
    r = subprocess.run([FFMPEG, "-v", "info", "-i", src, "-vf", "fps=2,cropdetect=limit=24:round=2:reset=0", "-f", "null", "-"],
                       capture_output=True, text=True)
    m = re.findall(r"crop=(\d+):(\d+):(\d+):(\d+)", r.stderr)
    if not m:
        return 0, 0, w, h
    cw, ch, x, y = map(int, m[-1])
    if cw < w * 0.3 or ch < h * 0.3:          # a mostly dark clip: don't trust it
        return 0, 0, w, h
    return x, y, cw, ch


def blurred_sides(fr):
    """Q8: a vertical clip shown inside a landscape frame with blurred copies on the sides. Returns (x0, x1) of the sharp
    middle in this frame's coordinates, or None."""
    g = [cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) for f in fr[:: max(1, len(fr) // 12)]]
    sharp = np.mean([np.abs(cv2.Laplacian(x, cv2.CV_32F)).mean(0) for x in g], 0)
    W = len(sharp)
    k = max(3, W // 64)
    sharp = np.convolve(sharp, np.ones(k) / k, "same")
    mid = np.median(sharp[int(W * .4):int(W * .6)])
    on = np.where(sharp > mid * 0.35)[0]
    if not len(on) or mid < 2:
        return None
    x0, x1 = on[0], on[-1] + 1
    side = np.r_[sharp[:max(1, x0 - k)], sharp[x1 + k:]]
    if (x1 - x0) > W * 0.75 or abs((x0 + x1) / 2 - W / 2) > W * 0.08 or not len(side) or side.mean() > mid * 0.3:
        return None
    return int(x0), int(x1)


# ------------------------------------------------------------------ models

class Models:
    def __init__(self):
        from rapidocr import RapidOCR
        from rfdetr import RFDETRSmall
        from transnetv2_pytorch import TransNetV2
        sys.path.insert(0, str(MODELS / "unisal"))
        import unisal
        self.tn = TransNetV2(device=DEV).eval()
        torch.use_deterministic_algorithms(False)   # TransNetV2's package turns these on globally; on CUDA its dilated
        torch.backends.cudnn.deterministic = False  # 3D convs then fall back to an op that has no CUDA kernel
        from rfdetr.assets.coco_classes import COCO_CLASSES
        self.det = RFDETRSmall()
        self.names = COCO_CLASSES                    # class_id is the COCO id (1 = person, 91-number scheme with gaps)
        self.face = cv2.FaceDetectorYN.create(str(MODELS / "face_detection_yunet_2023mar.onnx"), "", (AW, 360), 0.7)
        gpu = DEV == "cuda" and os.environ.get("VCONV_OCR_GPU", "1") == "1"
        if gpu:                                          # onnxruntime-gpu 1.23.2 (CUDA 12 build): same CUDA/cuDNN libs as torch cu128. Never install the CUDA 13 extras: nvidia-cudnn-cu13 overwrites torch's cuDNN files and shifts every model's numbers
            import onnxruntime
            onnxruntime.preload_dlls()
        self.ocr = RapidOCR(params={"EngineConfig.onnxruntime.use_cuda": True,
                                    "EngineConfig.onnxruntime.cuda_ep_cfg.cudnn_conv_algo_search": "HEURISTIC"} if gpu else None)
        run = MODELS / "unisal/training_runs/pretrained_unisal"
        self.sal = unisal.model.UNISAL(**json.loads((run / "UNISAL.json").read_text()))
        self.sal.load_best_weights(run)
        self.sal = self.sal.to(DEV).eval()

    def cuts(self, fr):
        """Shot boundaries: list of (start, end) frame ranges. TransNetV2 on 48x27 frames."""
        with tick("cuts"):
            return self._cuts(fr)

    def _cuts(self, fr):
        small = torch.from_numpy(np.stack([cv2.resize(f[:, :, ::-1], (48, 27), interpolation=cv2.INTER_AREA) for f in fr]))
        with torch.no_grad():
            p = self.tn.predict_frames(small.to(DEV), quiet=True)[0]   # predict_frames does not move its input
        p = np.asarray(p.cpu() if hasattr(p, "cpu") else p).reshape(-1)
        cut = [i for i in range(1, len(p)) if p[i] > 0.5 and p[i - 1] <= 0.5]
        b = [0] + cut + [len(fr)]
        return [(b[i], b[i + 1]) for i in range(len(b) - 1) if b[i + 1] > b[i]]

    def objects(self, imgs):
        with tick("det"):
            return self._objects(imgs)

    def _objects(self, imgs):
        out = self.det.predict([f[:, :, ::-1].copy() for f in imgs], threshold=0.45)
        out = out if isinstance(out, list) else [out]
        res = []
        for d in out:
            res.append([(self.names.get(int(c), str(c)), float(s), b.tolist())
                        for b, s, c in zip(d.xyxy, d.confidence, d.class_id)])
        return res

    def faces(self, img):
        with tick("faces"):
            return self._faces(img)

    def _faces(self, img):
        h, w = img.shape[:2]
        self.face.setInputSize((w, h))
        _, f = self.face.detect(img)
        return [] if f is None else [(float(x[14]), [x[0], x[1], x[0] + x[2], x[1] + x[3]]) for x in f]

    def text(self, img):
        with tick("ocr"):
            return self._text(img)

    def _text(self, img):
        r = self.ocr(img, use_det=True, use_cls=False, use_rec=False)
        boxes = getattr(r, "boxes", None)
        if boxes is None:
            return []
        sc = getattr(r, "scores", None)
        sc = [1.0] * len(boxes) if sc is None else list(sc)
        out = [[float(b[:, 0].min()), float(b[:, 1].min()), float(b[:, 0].max()), float(b[:, 1].max())]
               for b, c in zip(np.asarray(boxes), sc) if c >= TEXT_SCORE]
        # a text line is wider than tall, and either short or very wide (a two-line lower third on its plate);
        # tall squarish boxes are textures (fire, steel, aerials) read as text
        H = img.shape[0]
        return [t for t in out if t[2] - t[0] >= t[3] - t[1] and
                (t[3] - t[1] <= TEXT_MAX_H * H or (t[2] - t[0] >= 3 * (t[3] - t[1]) and t[3] - t[1] <= 0.25 * H))]

    def saliency(self, imgs):
        with tick("sal"):
            return self._saliency(imgs)

    def _saliency(self, imgs):
        """One saliency map per image (same size as the image), from UNISAL's video (DHF1K) head."""
        h, w = imgs[0].shape[:2]
        x = torch.stack([torch.from_numpy(cv2.resize(f[:, :, ::-1], (384, 224), interpolation=cv2.INTER_AREA).copy())
                         .permute(2, 0, 1).float() / 255 for f in imgs])
        x = (x - torch.tensor([.485, .456, .406])[:, None, None]) / torch.tensor([.229, .224, .225])[:, None, None]
        with torch.no_grad():
            y = self.sal(x[None].to(DEV), target_size=(h, w), source="DHF1K", static=len(imgs) == 1)
        return [m / (m.sum() + 1e-9) for m in y[0, :, 0].exp().cpu().numpy()]


# ------------------------------------------------------------------ per-shot decision

def iou(a, b):
    x0, y0, x1, y1 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    i = max(0, x1 - x0) * max(0, y1 - y0)
    return i / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - i + 1e-9)


def tracks(dets):
    """Greedy IoU linking of per-sample boxes into tracks: [{label, boxes: {sample_idx: box}}]."""
    ts = []
    for k, ds in enumerate(dets):
        for lab, s, b in sorted(ds, key=lambda d: -d[1]):
            best = max((t for t in ts if t["label"] == lab and k - 1 in t["boxes"] and k not in t["boxes"]),
                       key=lambda t: iou(t["boxes"][k - 1], b), default=None)
            if best and iou(best["boxes"][k - 1], b) > 0.2:
                best["boxes"][k] = b
            else:
                ts.append({"label": lab, "boxes": {k: b}})
    return ts


def smooth_path(xs, n_frames, W, wc):
    """Per-sample target centres -> per-frame left edge: dead zone, Gaussian smoothing, speed limit (Q31-33)."""
    idx = np.arange(len(xs)) * SAMPLE
    x = np.interp(np.arange(n_frames), idx, xs)
    dz = 0.03 * W                                            # dead zone: ignore small subject motion
    held = x.copy()
    for i in range(1, len(x)):
        held[i] = held[i - 1] if abs(x[i] - held[i - 1]) < dz else x[i] - np.sign(x[i] - held[i - 1]) * dz
    s = max(1, int(FPS / 3))
    k = np.exp(-0.5 * (np.arange(-3 * s, 3 * s + 1) / s) ** 2)
    sm = np.convolve(np.pad(held, 3 * s, mode="edge"), k / k.sum(), "valid")
    vmax = SPEED * W / FPS
    for _ in range(2):                                       # forward and backward clamp
        for i in range(1, len(sm)):
            sm[i] = sm[i - 1] + np.clip(sm[i] - sm[i - 1], -vmax, vmax)
        sm = sm[::-1]
    return np.clip(sm - wc / 2, 0, W - wc)


def on_overlay(t, overlays, H):
    """Text sitting on a pixel-stable overlay (logo, ticker bar). Only small/short overlays count: on a locked-off
    camera the whole background is pixel-stable and must not swallow scene text."""
    cx, cy = (t[0] + t[2]) / 2, (t[1] + t[3]) / 2
    return any(o[3] - o[1] <= 0.2 * H and (iou(t, o) > 0.3 or (o[0] <= cx <= o[2] and o[1] <= cy <= o[3])) for o in overlays)


def is_graphic(t, s, overlays, H):
    """Q29: channel graphics (ticker, lower third, caption, timestamp) vs text in the scene. A graphic sits in the top
    22% or bottom 40% of the frame (burned-in subtitles sit at 60-70%) and is either on a pixel-stable overlay or at the same height in most text samples."""
    if on_overlay(t, overlays, H):
        return True
    cy = (t[1] + t[3]) / 2
    if 0.22 * H < cy < 0.60 * H:
        return False
    if len(s["text"]) < 3:
        return True
    h = t[3] - t[1]
    same = sum(any(min(t[3], u[3]) - max(t[1], u[1]) > 0.6 * min(h, u[3] - u[1]) for u in ts) for ts in s["text"])
    return same >= 0.6 * len(s["text"])


def crosses(t, lefts, w):
    """True if a window edge (window = [left, left + w) at any frame) cuts through box t."""
    lefts = np.asarray(lefts, float)
    return bool(np.any((t[0] < lefts) & (lefts < t[2])) or np.any((t[0] < lefts + w) & (lefts + w < t[2])))


def blur_patch(img, r):
    """Q27/Q30: cover rect r = [x0, y0, x1, y1] (img pixels, may extend past the edges) with a strong blur, feathered
    outward only, so the covered text is unreadable and the patch has no hard edge. Edits img in place."""
    h, w = img.shape[:2]
    x0, y0, x1, y1 = (int(round(v)) for v in (max(0, r[0]), max(0, r[1]), min(w, r[2]), min(h, r[3])))
    if x1 - x0 < 2 or y1 - y0 < 2:
        return
    e = max(2, (y1 - y0) // 3)
    X0, Y0, X1, Y1 = max(0, x0 - e), max(0, y0 - e), min(w, x1 + e), min(h, y1 + e)
    roi = img[Y0:Y1, X0:X1].astype(np.float32)
    k = max(2.0, (y1 - y0) / 4)                                  # the text line shrinks to ~4 px before coming back
    small = cv2.resize(roi, (max(1, int((X1 - X0) / k)), max(1, int((Y1 - Y0) / k))), interpolation=cv2.INTER_AREA)
    bl = cv2.GaussianBlur(cv2.resize(small, (X1 - X0, Y1 - Y0), interpolation=cv2.INTER_LINEAR), (0, 0), k / 2)
    m = np.zeros((Y1 - Y0, X1 - X0), np.float32)
    m[y0 - Y0:y1 - Y0, x0 - X0:x1 - X0] = 1
    m = np.maximum(m, cv2.GaussianBlur(m, (0, 0), e / 2))[..., None]
    img[Y0:Y1, X0:X1] = (roi * (1 - m) + bl * m).astype(np.uint8)


def grow(t, px, py, W, H):
    return [max(0.0, t[0] - px), max(0.0, t[1] - py), min(float(W), t[2] + px), min(float(H), t[3] + py)]


def text_guard(m, fr, s, windows, W, H, overlays):
    """Q27: no text line may be cut by a crop edge. windows = [(per-frame lefts, width)] in analysis pixels.
    Graphics the edge cuts get a full-width blur band; scene text and inset boxes get a blur over their own box; large
    scene text that would be cut sends the shot to FIT. Then a check: OCR on crops of frames between the text samples
    (patches applied, 2x up) and any text touching a crop edge gets a patch too.
    Returns (patches, fit_reason or None, patches added by the check)."""
    pad_x = 0.01 * W
    patches = []
    boxes = [(t, is_graphic(t, s, overlays, H), False) for ts in s["text"] for t in ts]
    boxes += [(p["mean"], False, True) for p in s.get("tracks", []) if p.get("pip")]
    for t, gr, inset in boxes:
        if not any(crosses(t, l, w) for l, w in windows):
            continue
        py = 0.3 * (t[3] - t[1])
        if gr:
            patches.append([0.0, max(0.0, t[1] - py), float(W), min(float(H), t[3] + py)])
        elif not inset and t[3] - t[1] >= BIG_TEXT * H:
            return [], f"large text in the scene ({(t[3] - t[1]) / H:.0%} of height) would be cut by the crop", 0
        else:
            patches.append(grow(t, pad_x, py, W, H))
    ts = s["tsamp"]
    check = [(ts[i] + ts[i + 1]) // 2 for i in range(len(ts) - 1)] or [(s["a"] + s["b"]) // 2]
    with tick("verify"):
        return _verify(m, fr, s, windows, W, H, patches, check, pad_x)


def _verify(m, fr, s, windows, W, H, patches, check, pad_x):
    added = 0
    for f in check[:: max(1, -(-len(check) // VERIFY_FRAMES))]:
        k = f - s["a"]
        for lefts, w in windows:
            l, wi = int(round(lefts[min(k, len(lefts) - 1)])), int(round(w))
            crop = fr[f][:, l:l + wi].copy()
            for p in patches:
                blur_patch(crop, [p[0] - l, p[1], p[2] - l, p[3]])
            for t in m.text(cv2.resize(crop, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)):
                t = [v / 2 for v in t]
                if t[0] <= 2 or t[2] >= wi - 2:
                    patches.append(grow([t[0] + l, t[1], t[2] + l, t[3]], pad_x, 0.3 * (t[3] - t[1]), W, H))
                    added += 1
    return patches, None, added


def analyse(m, fr, a, b, W, H, overlays):
    """All model signals for frames fr[a:b] (analysis size W x H). Models run only when a crop is possible."""
    samp = list(range(a, b, SAMPLE)) or [a]
    imgs = [fr[i] for i in samp]
    g = [cv2.cvtColor(x, cv2.COLOR_BGR2GRAY).astype(np.float32) for x in imgs]
    d = [np.abs(g[i] - g[i - 1]) for i in range(1, len(g))]
    tsamp = samp[:: max(1, -(-len(samp) // TEXT_SAMPLES))]
    s = {"a": a, "b": b, "samp": samp, "tsamp": tsamp, "gmean": np.mean(g, 0),
         "motion": float(np.mean([x.mean() for x in d])) if d else 0.0, "text": [m.text(fr[i]) for i in tsamp]}
    s["still"] = len(g) > 1 and s["motion"] < 1.0
    s["text_share"] = float(np.median([sum((t[2] - t[0]) * (t[3] - t[1]) for t in ts if not is_graphic(t, s, overlays, H))
                                       for ts in s["text"]])) / (W * H)   # Q28: graphics are banded, not counted
    if s["text_share"] > TEXT_HEAVY or (s["still"] and (b - a) / FPS >= 2):
        return s
    s["dets"] = m.objects(imgs)
    s["faces"] = [m.faces(x) for x in imgs]
    s["sal"] = m.saliency(imgs)
    tr = [t for t in tracks(s["dets"]) if len(t["boxes"]) >= max(1, 0.4 * len(samp))]
    for t in tr:
        bs = np.array(list(t["boxes"].values()), float)
        t["mean"] = bs.mean(0).tolist()
        t["static"] = len(bs) >= 3 and float(bs.std(0).max()) < STATIC * W
        t["demote"] = False
        if t["static"] and d:                            # Q21: a still person in a moving scene (poster, screen, inset)
            mask = np.ones((H, W), bool)
            x0, y0, x1, y1 = (int(v) for v in grow(t["mean"], 0.03 * W, 0.03 * H, W, H))
            mask[y0:y1, x0:x1] = False
            t["demote"] = mask.any() and float(np.mean([x[mask].mean() for x in d])) > 3.0
    s["tracks"] = tr
    return s


def mark_pip(sigs, W, H):
    """Q16/Q21: a still person at the same spot in two different shots whose surroundings differ is a
    picture-in-picture inset (sign-language interpreter, studio guest box): never a subject, and blurred if a crop cuts
    it. Same spot + same surroundings is just the same locked-off camera (interview A-B-A cuts) and is left alone."""
    st = [(i, t) for i, s in enumerate(sigs) if s for t in s.get("tracks", []) if t["static"] and t["label"] == "person"]
    for x in range(len(st)):
        for y in range(x + 1, len(st)):
            (i, p), (j, q) = st[x], st[y]
            if i == j or iou(p["mean"], q["mean"]) < 0.6:
                continue
            u = [min(p["mean"][0], q["mean"][0]), min(p["mean"][1], q["mean"][1]),
                 max(p["mean"][2], q["mean"][2]), max(p["mean"][3], q["mean"][3])]
            mask = np.ones((H, W), bool)
            x0, y0, x1, y1 = (int(v) for v in grow(u, 0.03 * W, 0.03 * H, W, H))
            mask[y0:y1, x0:x1] = False
            if mask.any() and float(np.abs(sigs[i]["gmean"] - sigs[j]["gmean"])[mask].mean()) > 20:
                p["pip"] = q["pip"] = True


def decide(m, fr, s, W, H, overlays):
    """Layout for one shot from its signals s. Returns a dict with mode, reason, confidence, x path, patches."""
    a, b, samp = s["a"], s["b"], s["samp"]
    n = b - a
    wc = H * 9 / 16
    sec = n / FPS
    out = {"start": a, "end": b, "mode": "FIT", "reason": "", "confidence": 0.0, "wc": wc}
    if s["text_share"] > TEXT_HEAVY:
        out.update(reason=f"text-heavy frame ({s['text_share']:.0%} text)", confidence=1.0)
        return out
    if s["still"] and sec >= 2:
        out.update(mode="SWEEP", reason="still image: slow push-in on the whole frame", confidence=1.0)
        return out

    faces, sal = s["faces"], s["sal"]
    pips = [grow(t["mean"], 0.02 * W, 0.02 * H, W, H) for t in s["tracks"] if t.get("pip")]
    if pips:                                             # an inset's face is not where the story is
        sal = [x.copy() for x in sal]
        for x in sal:
            for q in pips:
                x[int(q[1]):int(np.ceil(q[3])), int(q[0]):int(np.ceil(q[2]))] = 0
    salm = np.mean(sal, 0)
    col = salm.sum(0)
    cs = np.cumsum(np.r_[0, col])
    iw = int(round(wc))

    def share_at(left, c=cs):                            # share of the saliency inside the window at left
        l = int(np.clip(round(left), 0, W - iw))
        return float((c[l + iw] - c[l]) / (c[-1] + 1e-9))

    area = lambda bx: (bx[2] - bx[0]) * (bx[3] - bx[1]) / (W * H)
    mass = lambda bx: float(salm[int(bx[1]):int(np.ceil(bx[3])), int(bx[0]):int(np.ceil(bx[2]))].sum())
    inside = lambda fb, bx: bx[0] <= (fb[0] + fb[2]) / 2 <= bx[2] and bx[1] <= (fb[1] + fb[3]) / 2 <= bx[3]

    def aim(t, k):                                       # Q17: face (if inside the person box) else upper body
        bx = t["boxes"].get(k)
        if bx is None:
            return None
        if t["label"] == "person":
            f = [fb for _, fb in faces[k] if inside(fb, bx)]
            if f:
                return (f[0][0] + f[0][2]) / 2
        return (bx[0] + bx[2]) / 2

    def score(t):                                        # Q16/Q22: size + saliency + presence + centrality
        mb = t["mean"]
        cx = (mb[0] + mb[2]) / 2 / W
        v = len(t["boxes"]) / len(samp) * (area(mb) + 0.5 * mass(mb)) * (1.2 - abs(cx - 0.5))
        return v * (0.2 if t["demote"] else 1.0)

    def big(t):                                          # clearly the focus by size alone
        mb = t["mean"]
        if area(mb) >= 0.08 or (t["label"] == "person" and mb[3] - mb[1] >= 0.35 * H):
            return True
        return any(fb[2] - fb[0] >= 0.04 * W for k, bx in t["boxes"].items() for _, fb in faces[k] if inside(fb, bx))

    tr = [t for t in s["tracks"] if not t.get("pip")]
    people = sorted([t for t in tr if t["label"] == "person" and area(t["mean"]) > 0.006], key=score, reverse=True)
    objs = [t for t in tr if t["label"] != "person" and area(t["mean"]) > 0.02]
    cands = sorted(people + objs, key=score, reverse=True)
    ok = [l for l in range(0, W - iw + 1) if not any(crosses(q, [l], iw) for q in pips)]   # never cut an inset
    if not ok:
        out.update(reason="every crop would cut through a picture-in-picture inset", confidence=1.0)
        return out
    best = max(ok, key=share_at)
    s_win = share_at(best)

    def clear(left):                                     # nearest inset-safe left within 30% of the crop, else None
        l = min(ok, key=lambda v: abs(v - left))
        return float(l) if abs(l - left) <= 0.3 * wc else None
    insets = sum(1 for t in s["tracks"] if t.get("pip"))
    note = f"; {insets} inset person(s) ignored" if insets else ""

    subj, why, targets = None, "", None
    if cands and cands[0]["label"] == "person":
        p0 = people[0]
        if len(people) >= 2:
            p1 = people[1]
            both = [k for k in p0["boxes"] if k in p1["boxes"]]
            if len(both) >= 0.5 * len(samp):
                xs = [min(p0["boxes"][k][0], p1["boxes"][k][0]) for k in both] + [max(p0["boxes"][k][2], p1["boxes"][k][2]) for k in both]
                span = max(xs) - min(xs)
                wide = all(np.mean([x[2] - x[0] for x in t["boxes"].values()]) / W > 0.045 for t in (p0, p1))
                gap = abs(np.mean([aim(p0, k) for k in both]) - np.mean([aim(p1, k) for k in both])) / W
                if span <= wc * 0.95:
                    subj, why = p0, "two people framed together"
                    targets = [((min(p0["boxes"][k][0], p1["boxes"][k][0]) + max(p0["boxes"][k][2], p1["boxes"][k][2])) / 2
                                if k in p0["boxes"] and k in p1["boxes"] else None) for k in range(len(samp))]
                elif wide and gap >= 0.20 and sec >= 2.5 and len(people) == 2:
                    ws = H * OW / (OH / 2)
                    cx = [float(np.mean([aim(t, k) for k in both])) for t in (p0, p1)]
                    patches, fit, added = text_guard(m, fr, s, [(np.full(n, np.clip(c - ws / 2, 0, W - ws)), ws) for c in cx], W, H, overlays)
                    if fit:
                        out.update(reason=fit, confidence=1.0)
                        return out
                    out.update(mode="SPLIT", reason="two people too far apart for one crop" + note, confidence=1.0,
                               pair=[cx], patches=patches, patches_by_check=added)
                    return out
                elif len(people) >= 3 and score(people[0]) < 2 * score(people[1]):
                    out.update(reason=f"{len(people)} people, none dominant", confidence=0.0)
                    return out
        if subj is None:
            subj, why = p0, "main person"
    elif cands:
        subj, why = cands[0], f"main object ({cands[0]['label']})"

    if subj is not None:
        targets = targets or [aim(subj, k) for k in range(len(samp))]
        known = [t for t in targets if t is not None]
        s_t = share_at(np.median(known) - wc / 2)
        if not big(subj) and s_t < 0.8 * s_win:          # Q16: a small subject only wins if it is where the eye goes
            why = (f"small {subj['label']} holds {s_t:.0%} of the eye-catching area vs {s_win:.0%} elsewhere: "
                   "saliency decides")
            subj = None

    if subj is None:                                     # Q24: no subject -> saliency
        lead = (why + "; ") if why else "no subject: "
        if s_win < 0.6:
            out.update(reason=f"{lead}saliency spread out ({s_win:.0%} fits): whole frame{note}", confidence=s_win)
            return out
        out.update(mode="LOCKED", reason=f"{lead}saliency concentrated ({s_win:.0%} in one window){note}",
                   confidence=s_win, x=[float(best)] * n)
    else:
        hit = sum(t is not None for t in targets) / len(samp)
        if hit < CONF_MIN:
            out.update(reason=f"{why} found in only {hit:.0%} of the shot", confidence=hit)
            return out
        fill, xs = known[0], []
        for t in targets:                                # hold the last known aim through misses
            fill = t if t is not None else fill
            xs.append(fill)
        if max(xs) - min(xs) <= LOCK_TRAVEL * W:
            left = float(np.clip(np.median(xs) - wc / 2, 0, W - wc))
            for t in (t for ts in s["text"] for t in ts if not is_graphic(t, s, overlays, H)):
                if t[0] < left < t[2] or t[0] < left + wc < t[2]:      # first try to move clear of scene text
                    inside_w = t[2] - t[0] <= wc
                    cand = [t[0], t[2] - wc] if inside_w else [t[2], t[0] - wc]
                    new = min(cand, key=lambda c: abs(c - left))
                    if 0 <= new <= W - wc and abs(new - left) < wc * 0.3:
                        left = float(new)
            left = clear(left)
            if left is None:
                out.update(reason=f"{why}, but the crop would cut through a picture-in-picture inset", confidence=1.0)
                return out
            keep = share_at(left)
            out.update(mode="LOCKED", reason=f"{why}, little movement{note}", x=[left] * n)
        else:
            path = smooth_path(xs, n, W, wc)
            if any(crosses(q, path, wc) for q in pips):
                out.update(reason=f"{why}, but the moving crop would cut through a picture-in-picture inset", confidence=1.0)
                return out
            keep = float(np.mean([share_at(path[min(k * SAMPLE, n - 1)], np.cumsum(np.r_[0, sal[k].sum(0)]))
                                  for k in range(len(samp))]))
            out.update(mode="TRACK", reason=f"{why} moves across the frame{note}", x=[float(v) for v in path])
        if keep < SAL_KEEP:                              # the crop would drop most of what draws the eye
            out.update(mode="FIT", reason=f"{why}, but the crop keeps only {keep:.0%} of the eye-catching area", confidence=keep)
            out.pop("x")
            return out
        out["confidence"] = hit * min(1.0, keep / 0.6)
        if out["confidence"] < CONF_MIN:
            out.update(mode="FIT", reason=f"{why}: low confidence ({out['confidence']:.2f})")
            out.pop("x")
            return out

    patches, fit, added = text_guard(m, fr, s, [(out["x"], wc)], W, H, overlays)
    if fit:
        out.update(mode="FIT", reason=fit, confidence=1.0)
        out.pop("x")
        return out
    out.update(patches=patches, patches_by_check=added)
    return out


def find_overlays(fr):
    """Persistent overlays (logos, tickers, bugs): edge-rich regions that stay identical through the clip while the rest
    changes. Returns boxes in analysis coordinates."""
    if len(fr) < 24:
        return []
    pick = fr[:: max(1, len(fr) // 24)]
    g = np.stack([cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).astype(np.float32) for f in pick])
    if np.abs(np.diff(g, axis=0)).mean() < 2.0:          # the whole clip is static: nothing stands out
        return []
    stable = (g.std(0) < 4) & (np.abs(cv2.Laplacian(g.mean(0), cv2.CV_32F)) > 20)
    stable = cv2.dilate(stable.astype(np.uint8), np.ones((9, 9), np.uint8))
    n, _, st, _ = cv2.connectedComponentsWithStats(stable)
    H, W = g.shape[1:]
    return [[float(x), float(y), float(x + w), float(y + h)] for x, y, w, h, a in st[1:] if a > W * H * 0.0015 and w < W * 0.9]


def fit_trim(overlays, W, H):
    """Q30: smallest edge trim (<= 15% per edge) that drops overlays sitting at the frame edges, for FIT."""
    l, t, r, b = 0.0, 0.0, float(W), float(H)
    for x0, y0, x1, y1 in overlays:
        opts = [("l", x1, x1 / W), ("r", x0, (W - x0) / W), ("t", y1, y1 / H), ("b", y0, (H - y0) / H)]
        side, v, cost = min(opts, key=lambda o: o[2])
        if cost <= TRIM_MAX:
            if side == "l": l = max(l, v)
            if side == "r": r = min(r, v)
            if side == "t": t = max(t, v)
            if side == "b": b = min(b, v)
    return [l / W, t / H, r / W, b / H]


# ------------------------------------------------------------------ render

def fit_frame(img, trim=None, zoom=1.0):
    h, w = img.shape[:2]
    if trim:
        img = img[int(trim[1] * h):int(trim[3] * h), int(trim[0] * w):int(trim[2] * w)]
        h, w = img.shape[:2]
    s = max(OW / w, OH / h)
    bg = cv2.resize(img, (max(1, int(w * s / 8)), max(1, int(h * s / 8))), interpolation=cv2.INTER_AREA)
    bg = cv2.GaussianBlur(bg, (0, 0), 6)
    bg = cv2.resize(bg, (max(OW, int(np.ceil(w * s))), max(OH, int(np.ceil(h * s)))), interpolation=cv2.INTER_LINEAR)
    y0, x0 = (bg.shape[0] - OH) // 2, (bg.shape[1] - OW) // 2
    bg = (bg[y0:y0 + OH, x0:x0 + OW] * 0.7).astype(np.uint8)
    f = min(OW / w, OH / h) * zoom
    fg = cv2.resize(img, (int(w * f), int(h * f)), interpolation=cv2.INTER_LANCZOS4 if f > 1 else cv2.INTER_AREA)
    fh, fw = fg.shape[:2]
    cy, cx = (OH - fh) // 2, (OW - fw) // 2
    sy, sx = max(0, -cy), max(0, -cx)
    bg[max(0, cy):max(0, cy) + min(fh, OH), max(0, cx):max(0, cx) + min(fw, OW)] = fg[sy:sy + min(fh, OH), sx:sx + min(fw, OW)]
    return bg


def render(src, vf, cw, ch, shots, scale, out, trim, preview=None):
    enc = subprocess.Popen([FFMPEG, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{OW}x{OH}", "-r", str(FPS),
                            "-i", "-", "-c:v", "h264_nvenc", "-preset", "p6", "-rc", "vbr", "-cq", "18", "-b:v", "0",
                            "-profile:v", "high", "-pix_fmt", "yuv420p", "-colorspace", "bt709", "-color_primaries", "bt709",
                            "-color_trc", "bt709", "-movflags", "+faststart", out], stdin=subprocess.PIPE)
    pv = None
    if preview:
        pv = subprocess.Popen([FFMPEG, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", "1920x1080", "-r", str(FPS),
                               "-i", "-", "-c:v", "h264_nvenc", "-preset", "p4", "-cq", "24", "-pix_fmt", "yuv420p", preview],
                              stdin=subprocess.PIPE)
    by = {i: s for s in shots for i in range(s["start"], s["end"])}

    def compose(i, img):                                 # one output frame; cv2 releases the GIL, so threads run in parallel
        s = by.get(i) or shots[-1]
        mode, k = s["mode"], i - s["start"]
        if mode in ("LOCKED", "TRACK"):
            l = int(round(s["x"][min(k, len(s["x"]) - 1)] * scale))
            w = int(round(s["wc"] * scale))
            o = cv2.resize(patched(img, l, w, s, scale), (OW, OH), interpolation=cv2.INTER_LANCZOS4)
        elif mode == "SPLIT":
            w = int(round(ch * OW / (OH / 2)))
            halves = []
            for cx in s["pair"][0]:
                l = int(np.clip(cx * scale - w / 2, 0, cw - w))
                halves.append(cv2.resize(patched(img, l, w, s, scale), (OW, OH // 2), interpolation=cv2.INTER_LANCZOS4))
            o = np.vstack(halves)
        elif mode == "PASS":
            o = fit_frame(img)
        elif mode == "SWEEP":
            o = fit_frame(img, trim, 1.0 + 0.06 * k / max(1, s["end"] - s["start"]))
        else:
            o = fit_frame(img, trim)
        o = np.ascontiguousarray(o).tobytes()
        return o, (preview_frame(img, np.frombuffer(o, np.uint8).reshape(OH, OW, 3), s, k, scale).tobytes() if pv else None)

    pend = collections.deque()

    def emit():
        o, q = pend.popleft().result()
        enc.stdin.write(o)
        if q:
            pv.stdin.write(q)

    with ThreadPoolExecutor(RENDER_THREADS) as ex:      # frames stay in order: results are written in submit order
        for i, img in enumerate(frames(src, vf, cw, ch)):
            pend.append(ex.submit(compose, i, img))
            if len(pend) >= 2 * RENDER_THREADS:          # bounded: at most this many frames in memory
                emit()
        while pend:
            emit()
    for p in (enc, pv):
        if p:
            p.stdin.close()
            p.wait()


def patched(img, l, w, s, scale):
    """The crop img[:, l:l+w] with the shot's blur patches (analysis coords) applied."""
    c = img[:, l:l + w].copy()
    for p in s.get("patches", []):
        blur_patch(c, [p[0] * scale - l, p[1] * scale, p[2] * scale - l, p[3] * scale])
    return c


def preview_frame(img, o, s, k, scale):
    """Review frame: source with the crop drawn (left), the 9:16 output (right), mode + reason on top."""
    canvas = np.full((1080, 1920, 3), 18, np.uint8)
    h, w = img.shape[:2]
    f = min(1280 / w, 900 / h)
    src = cv2.resize(img, (int(w * f), int(h * f)))
    if s["mode"] in ("LOCKED", "TRACK"):
        l = s["x"][min(k, len(s["x"]) - 1)] * scale * f
        cv2.rectangle(src, (int(l), 0), (int(l + s["wc"] * scale * f), src.shape[0] - 1), (0, 200, 255), 3)
    elif s["mode"] == "SPLIT":
        ws = h * OW / (OH / 2) * f
        for cx in s["pair"][0]:
            l = float(np.clip(cx * scale * f - ws / 2, 0, src.shape[1] - ws))
            cv2.rectangle(src, (int(l), 0), (int(l + ws), src.shape[0] - 1), (0, 200, 255), 3)
    for p in s.get("patches", []):                       # blur patches in magenta
        cv2.rectangle(src, (int(p[0] * scale * f), int(p[1] * scale * f)), (int(p[2] * scale * f), int(p[3] * scale * f)),
                      (255, 0, 255), 2)
    canvas[150:150 + src.shape[0], 20:20 + src.shape[1]] = src
    small = cv2.resize(o, (540, 960))
    canvas[100:1060, 1360:1900] = small
    cv2.putText(canvas, f"{s['mode']}  conf {s['confidence']:.2f}", (20, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (255, 255, 255), 3)
    cv2.putText(canvas, s["reason"][:90], (20, 110), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (200, 200, 200), 2)
    return canvas


# ------------------------------------------------------------------ main

def convert(m, src, out, preview=None, whole=False):
    t0 = time.time()
    TIMES.clear()
    with tick("probe"):
        w, h, dur = probe(src)
    with tick("bars"):
        bx, by_, bw, bh = black_bars(src, w, h) if not whole else (0, 0, w, h)   # --fit keeps bands (captions sit in them)
    vf = f"bwdif=deint=interlaced,fps={FPS},crop={bw}:{bh}:{bx}:{by_}"
    ah = int(round(AW * bh / bw / 2) * 2)
    with tick("decode"):
        fr = list(frames(src, vf, AW, ah))
    with tick("sides"):
        side = blurred_sides(fr) if bw > bh and not whole else None
    if side:                                           # Q8: keep only the sharp middle
        x0, x1 = int(side[0] * bw / AW), int(side[1] * bw / AW)
        bx, bw = bx + x0, (x1 - x0) // 2 * 2
        vf = f"bwdif=deint=interlaced,fps={FPS},crop={bw}:{bh}:{bx}:{by_}"
        with tick("decode"):
            fr = list(frames(src, vf, AW, int(round(AW * bh / bw / 2) * 2)))
    W, H = fr[0].shape[1], fr[0].shape[0]
    info = {"input": src, "source": [w, h], "duration": round(dur, 2), "bars": [bx, by_, bw, bh],
            "blurred_sides": bool(side), "frames": len(fr)}
    if bw / bh <= 9 / 16 * 1.05:                       # Q5: already vertical
        shots = [{"start": 0, "end": len(fr), "mode": "PASS", "reason": "already 9:16 or narrower", "confidence": 1.0}]
        overlays, trim = [], None
    else:
        with tick("overlays"):
            overlays = find_overlays(fr)
        trim = fit_trim(overlays, W, H)
        cuts = m.cuts(fr)
        if OH / bh > MAX_UP:                           # Q9: no crop at all
            why = f"source {bh}p: a crop would be upscaled {OH / bh:.1f}x (> {MAX_UP}x)"
            shots = [{"start": a, "end": b, "mode": "FIT", "reason": why, "confidence": 0.0} for a, b in cuts]
        else:
            sigs, errs = [], {}
            for a, b in cuts:
                try:
                    with tick("analyse"):
                        sigs.append(analyse(m, fr, a, b, W, H, overlays))
                except Exception as e:                 # Q39: any model error -> FIT for that shot
                    sigs.append(None)
                    errs[a] = f"error: {e}"[:200]
            mark_pip(sigs, W, H)                       # needs every shot's people first
            shots = []
            for (a, b), sg in zip(cuts, sigs):
                try:
                    with tick("decide"):
                        s = decide(m, fr, sg, W, H, overlays) if sg else None
                except Exception as e:
                    errs[a], s = f"error: {e}"[:200], None
                shots.append(s or {"start": a, "end": b, "mode": "FIT", "reason": errs[a], "confidence": 0.0})
        for i, s in enumerate(shots):                  # Q14: tiny shots follow a neighbour
            if s["end"] - s["start"] < FPS / 2 and len(shots) > 1:
                nb = shots[i - 1] if i else shots[i + 1]
                if nb["mode"] in ("FIT", "SWEEP", "PASS"):
                    s.update(mode="FIT", reason="very short shot: follows its neighbour")
                    s.pop("x", None)
                    s.pop("patches", None)
    if whole and shots[0]["mode"] != "PASS":           # --fit: the whole frame, nothing cropped or trimmed (a crop that
        shots = [{"start": 0, "end": len(fr), "mode": "FIT", "reason": "whole frame asked (crop check failed or text shot)",
                  "confidence": 1.0}]                  # lost what the shot was picked for, or text that must stay)
        trim = None
    with tick("render"):
        render(src, vf, bw, bh, shots, bw / W, out, trim if any(v not in (0.0, 1.0) for v in trim or []) else None, preview)
    info.update(shots=[{k: (v if k not in ("x", "patches") else [[round(c, 1) for c in p] for p in v] if k == "patches"
                            else [round(v[0], 1), round(v[-1], 1)]) for k, v in s.items() if k != "wc"} for s in shots],
                overlays=overlays, fit_trim=trim, seconds=round(time.time() - t0, 2),
                timing={k: round(v, 2) for k, v in TIMES.items()})
    pathlib.Path(out).with_suffix(".json").write_text(json.dumps(info, indent=1, default=float))
    return info


def selftest():
    W = 640
    p = smooth_path([100, 100, 500, 500, 500], 30, W, 202)
    assert np.all(np.abs(np.diff(p)) <= SPEED * W / FPS + 1e-6) and p.min() >= 0 and p.max() <= W - 202
    assert fit_trim([[600, 10, 635, 40]], 640, 360)[2] < 1.0           # a corner logo is trimmed
    assert fit_trim([[200, 100, 400, 250]], 640, 360) == [0, 0, 1, 1]   # a central box is not
    t = tracks([[("person", .9, [0, 0, 10, 10])], [("person", .9, [1, 0, 11, 10])], [("car", .9, [50, 50, 90, 90])]])
    assert len(t) == 2 and len(t[0]["boxes"]) == 2
    o = fit_frame(np.zeros((360, 640, 3), np.uint8))
    assert o.shape == (OH, OW, 3)
    for shape, trim in (((1080, 1916, 3), [0, .15, 1, 1]), ((1077, 1913, 3), [.02, .1, .97, .93]), ((1080, 1920, 3), None)):
        assert fit_frame(np.zeros(shape, np.uint8), trim, 1.06).shape == (OH, OW, 3)   # rounding never leaves a short bg
    assert crosses([90, 0, 110, 10], [100], 50) and not crosses([90, 0, 110, 10], [80], 50)
    assert crosses([140, 0, 160, 10], [100], 50) and not crosses([0, 0, 50, 10], [100], 50)
    img = np.zeros((360, 640, 3), np.uint8)
    cv2.putText(img, "BREAKING NEWS", (200, 300), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 3)
    before = img.copy()
    blur_patch(img, [180, 260, 480, 320])
    assert img.shape == before.shape and np.abs(img[:, :150].astype(int) - before[:, :150]).max() == 0   # far pixels untouched
    assert img[270:310, 200:460].std() < before[270:310, 200:460].std() * 0.5                           # text smeared
    blur_patch(img, [-50, -50, 5, 5])                                                                     # off-edge: no crash
    sig = {"text": [[[10, 330, 600, 350]]] * 4}
    assert is_graphic([10, 330, 600, 350], sig, [], 360) and not is_graphic([200, 150, 400, 170], sig, [], 360)
    g1, g2 = np.zeros((360, 640), np.float32), np.full((360, 640), 120, np.float32)
    mk = lambda: {"label": "person", "static": True, "mean": [500, 200, 620, 350]}
    sg = [{"tracks": [mk()], "gmean": g1}, {"tracks": [mk()], "gmean": g2}]
    mark_pip(sg, 640, 360)
    assert sg[0]["tracks"][0].get("pip") and sg[1]["tracks"][0].get("pip")                            # inset over new scene
    sg = [{"tracks": [mk()], "gmean": g1}, {"tracks": [mk()], "gmean": g1.copy()}]
    mark_pip(sg, 640, 360)
    assert not sg[0]["tracks"][0].get("pip")                                                              # same camera again
    print("selftest ok")


if __name__ == "__main__":
    if sys.argv[1:] == ["--selftest"]:
        selftest()
        sys.exit()
    a = sys.argv[1:]
    pv = a[a.index("--preview") + 1] if "--preview" in a else None
    m = Models()
    print(json.dumps(convert(m, a[0], a[1], pv, whole="--fit" in a), default=float)[:2000])
