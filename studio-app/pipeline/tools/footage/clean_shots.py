"""Footage step, after footage_api.py: downloaded clips -> clean single shots usable as B-roll.
The repo's clips are mostly other channels' TV packages (presenters, BREAKING panels, tickers, maps, vertical phone video;
baseline/FOOTAGE_REPO_USAGE.md). Per clip: split into shots (frame-histogram cuts); per shot (>= 1.5 s), 3 frames are
labelled with SigLIP-2 (cached on trijya) as clean scene footage vs presenter / graphic / map / vertical / call / website,
burned-in text in the frame centre is measured with RapidOCR, and side bars are detected. Corner bugs (channel logos) are
expected and removed later by a 10 % centre crop in assembly.
Writes <out>/shots.json (every shot with its verdict and reasons) and <out>/kept.jpg / rejected.jpg contact sheets.
usage (tools venv on trijya-7): clean_shots.py <footage_run_dir> <out_dir>
"""
import json, pathlib, sys
import cv2, numpy as np
from PIL import Image

MIN_SHOT_S, MAX_SHOT_S, SAMPLE_FPS = 1.5, 8.0, 6   # a longer shot is offered as pieces of at most 8 s, each judged alone
CLEAN = ["real news footage of an outdoor scene with buildings, streets or people",
         "night footage of explosions, fire or air defence fire in the sky",
         "an airport terminal, a departures board or aircraft on an airport apron",
         "military equipment, soldiers or drones in the field"]
REJECT = {"presenter": "a TV news presenter or reporter talking to the camera",
          "graphic": "a TV news graphic or title card with large text",
          "map": "a map or an infographic",
          "vertical": "a vertical phone video with blurred or dark bars on the left and right",
          "call": "a video call or talk show with several people in boxes",
          "website": "a screenshot of a website or a social media post"}
_M = []
NO_SIGLIP = (pathlib.Path.home() / "e2e" / "no_siglip").exists()   # SigLIP on a CPU-only venv is ~1 min a clip


def siglip(images):
    """Label shares per image over CLEAN + REJECT (zero-shot, local weights only)."""
    import torch
    from transformers import AutoModel, AutoProcessor
    if not _M:
        m = "google/siglip2-so400m-patch14-384"
        _M.extend([AutoModel.from_pretrained(m, local_files_only=True).eval(), AutoProcessor.from_pretrained(m, local_files_only=True)])
    model, proc = _M
    labels = CLEAN + list(REJECT.values())
    with torch.no_grad():
        x = proc(text=labels, images=images, padding="max_length", max_length=64, return_tensors="pt")
        p = torch.softmax(model(**x).logits_per_image, dim=-1).numpy()
    return p, len(CLEAN)


_OCR = []


def centre_text(img):
    """Fraction of the centre 76 % of the frame covered by confident text (lower thirds, captions, panels)."""
    if not _OCR:
        from rapidocr_onnxruntime import RapidOCR
        _OCR.append(RapidOCR())
    h, w = img.shape[:2]
    c = img[int(h * .12):int(h * .88), int(w * .12):int(w * .88)]
    area = 0.0
    for box, txt, conf in (_OCR[0](c)[0] or []):
        if conf > 0.6 and len(txt.strip()) >= 3:
            xs, ys = [p[0] for p in box], [p[1] for p in box]
            area += (max(xs) - min(xs)) * (max(ys) - min(ys))
    return area / (c.shape[0] * c.shape[1])


def side_bars(img):
    """Pillarbox: both outer 14 % strips much flatter (blurred/dark padding) than the centre."""
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    w = g.shape[1]; k = int(w * .14)
    lap = lambda a: cv2.Laplacian(a, cv2.CV_64F).var()
    c = lap(g[:, k:w - k]) + 1e-6
    return lap(g[:, :k]) / c < 0.15 and lap(g[:, w - k:]) / c < 0.15


def shots_of(path):
    cap = cv2.VideoCapture(str(path)); fps = cap.get(cv2.CAP_PROP_FPS) or 24; step = max(1, round(fps / SAMPLE_FPS))
    frames, hists, i = [], [], 0
    while True:
        ok, f = cap.read()
        if not ok:
            break
        if i % step == 0:
            small = cv2.resize(f, (480, 270))
            h = cv2.calcHist([cv2.cvtColor(small, cv2.COLOR_BGR2HSV)], [0, 1], None, [32, 32], [0, 180, 0, 256])
            frames.append((i / fps, small)); hists.append(cv2.normalize(h, h).flatten())
        i += 1
    cuts = [0] + [j for j in range(1, len(hists)) if cv2.compareHist(hists[j - 1], hists[j], cv2.HISTCMP_CORREL) < 0.55] + [len(frames)]
    out, most = [], max(2, int(MAX_SHOT_S * fps / step))
    for a0, b0 in zip(cuts, cuts[1:]):
        n = -(-(b0 - a0) // most)                                     # pieces of at most MAX_SHOT_S, equal length
        for a, b in ((a0 + (b0 - a0) * k // n, a0 + (b0 - a0) * (k + 1) // n) for k in range(n)):
            if b - a < 2:
                continue
            t0, t1 = frames[a][0], frames[b - 1][0] + step / fps
            if t1 - t0 >= MIN_SHOT_S:
                out.append({"start": round(t0, 2), "end": round(t1, 2), "frames": [frames[a + (b - a) * q // 4][1] for q in (1, 2, 3)],
                            "hist": hists[(a + b) // 2]})
    return out


def sheet(items, path, cols=4):
    if not items:
        return
    tiles = [cv2.resize(it["frames"][1], (320, 180)) for it in items]
    for t, it in zip(tiles, items):
        cv2.putText(t, f"{it['id']} {it['end'] - it['start']:.1f}s", (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
        cv2.putText(t, it["verdict"][:34], (6, 172), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 255, 255), 1)
    while len(tiles) % cols:
        tiles.append(np.zeros_like(tiles[0]))
    cv2.imwrite(str(path), np.vstack([np.hstack(tiles[r:r + cols]) for r in range(0, len(tiles), cols)]))


def main():
    run, out = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]); out.mkdir(parents=True, exist_ok=True)
    picks = [p for p in json.load(open(run / "clips.json")) if p.get("file")]
    allshots = []
    for p in picks:
        for k, s in enumerate(shots_of(p["file"])):
            if NO_SIGLIP:                                                   # ponytail: no label check, a human reviews every frame
                probs, nc = np.array([[1.0] * len(CLEAN) + [0.0] * len(REJECT)] * 3), len(CLEAN)
            else:
                probs, nc = siglip([Image.fromarray(cv2.cvtColor(f, cv2.COLOR_BGR2RGB)) for f in s["frames"]])
            clean = float(probs[:, :nc].sum(1).min())                       # weakest of the 3 frames decides
            worst = list(REJECT)[int(probs[:, nc:].mean(0).argmax())]
            text = centre_text(s["frames"][1]); bars = side_bars(s["frames"][1])
            twin = next((o["id"] for o in allshots if o["keep"] and o["beat"] == p["beat"] and o["clip"] != p["file"]
                         and cv2.compareHist(o["hist"], s["hist"], cv2.HISTCMP_CORREL) > 0.97), None)   # a reupload / the same stream
            why = [r for r, bad in (("label:" + worst, clean < 0.5), (f"text {text:.0%}", text > 0.03), ("side bars", bars),
                                    (f"same as {twin}", twin)) if bad]
            s.update(id=f"{p['beat']}_{p['n']}_{k}", beat=p["beat"], clip=p["file"], video_id=p["video_id"], title=p["title"],
                     clean=round(clean, 2), text=round(text, 3), bars=bool(bars), keep=not why,
                     verdict="KEEP " + max(CLEAN, key=lambda c: probs[:, CLEAN.index(c)].mean())[:24] if not why else "; ".join(why))
            allshots.append(s)
            print(s["id"], f"{s['start']:.1f}-{s['end']:.1f}", s["verdict"], flush=True)
    sheet([s for s in allshots if s["keep"]], out / "kept.jpg"); sheet([s for s in allshots if not s["keep"]], out / "rejected.jpg")
    json.dump([{k: v for k, v in s.items() if k not in ("frames", "hist")} for s in allshots], open(out / "shots.json", "w"), indent=1, ensure_ascii=False)
    print(f"{sum(s['keep'] for s in allshots)} clean shots of {len(allshots)}")


if __name__ == "__main__":
    main()
