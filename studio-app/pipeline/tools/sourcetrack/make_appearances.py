"""Anchor appearances for a story video (TEST): each appearance is rendered on its own (user rule 2026-10-26), from a
fresh seed, never chained to another appearance. Inside one appearance every shot is 328 frames (seed 328 delivered,
each continuation 328 raw = 289 new frames), so a chain never mixes lengths. Lines are written to fill their shots; the
take is then time-fitted (pitch kept, at most +-9 %) so lead + speech + 0.45 s ends exactly with the last shot -- no
silent tail (user, 2026-10-26). A line of any other length is not refused (NDC, user 2026-11-01): it gets as many 328-frame
shots as it needs, unstretched, and keep_frames cuts the render where the line ends (the edit never shows the silence).
One loudness finish over all appearances together (same gain everywhere), then each appearance gets its own folder:
  <out>/<id>/master_seed.wav, master_chain.wav (may be empty), shots.json, story.json (beats = per-shot text for <d>)
  <out>/appearances.json  (speech length and kept frames per appearance, for assembly)
usage: make_appearances.py <out_dir> <anchor_id> <script.json> <id>=<take.wav> ...   (script.json: {"scripts": {id: text}})
"""
import json, math, pathlib, re, subprocess, sys
import numpy as np, soundfile as sf
from make_master import CTX, FPS, SR, trimmed

SHOT, LEAD, KEEP_TAIL = 328, 0.25, 0.45
MAX_FIT = 0.09                                                 # largest tempo change allowed to fill the shots


def fit(x, target_s):
    """Time-stretch x (mono, SR) to target_s, pitch preserved (Rubber Band via ffmpeg)."""
    ratio = (len(x) / SR) / target_s
    if abs(ratio - 1) < 0.002:
        return x
    r = subprocess.run(["ffmpeg", "-v", "error", "-f", "f32le", "-ar", str(SR), "-ac", "1", "-i", "-", "-af",
                        f"rubberband=tempo={ratio:.5f}:pitchq=quality", "-f", "f32le", "-"], input=x.tobytes(),
                       capture_output=True, check=True).stdout
    y = np.frombuffer(r, np.float32); n = int(round(target_s * SR))
    return np.pad(y, (0, max(0, n - len(y))))[:n]


def split_sentences(text, durations_s, speech_s):
    """Assign each sentence to the shot where its middle falls (time ~ characters), as the <d> text of that shot."""
    sents = re.split(r"(?<=[.!?])\s+", text.strip())
    total = sum(len(s) for s in sents); t = LEAD; bounds = np.cumsum(durations_s); per = [[] for _ in durations_s]
    for s in sents:
        mid = t + speech_s * (len(s) / total) / 2; t += speech_s * len(s) / total
        per[int(np.searchsorted(bounds, mid, side="right")) if mid < bounds[-1] else len(per) - 1].append(s)
    return [" ".join(p) for p in per]


def main():
    out, aid, script = pathlib.Path(sys.argv[1]), sys.argv[2], json.load(open(sys.argv[3]))["scripts"]
    apps = [a.split("=", 1) for a in sys.argv[4:]]
    wins, meta = [], []
    for app, take in apps:
        x = trimmed(take); d0 = len(x) / SR
        n = max(1, round(((LEAD + d0 + KEEP_TAIL) * FPS - CTX) / (SHOT - CTX)))    # shot count whose fill is closest
        frames = SHOT + (n - 1) * (SHOT - CTX)
        target = frames / FPS - LEAD - KEEP_TAIL
        keep = frames
        if abs(d0 / target - 1) <= MAX_FIT:                    # close to whole shots: time-fit so speech ends with the last shot
            x = fit(x, target)
        else:                                                  # any other length (NDC 2026-11-01: short lines are fine): enough
            n = max(1, math.ceil(((LEAD + d0 + KEEP_TAIL) * FPS - CTX) / (SHOT - CTX)))   # 328-frame shots, voice as
            frames = SHOT + (n - 1) * (SHOT - CTX)                                       # spoken, the render is cut
            keep = min(frames, math.ceil((LEAD + d0 + KEEP_TAIL) * FPS))                 # where the line ends
            target = d0
        d = len(x) / SR
        w = np.zeros(frames * SR // FPS, np.float32); w[int(LEAD * SR):int(LEAD * SR) + len(x)] = x
        wins.append(w); meta.append({"id": app, "take": pathlib.Path(take).name, "speech_s": round(d, 2), "shots": n,
                                     "tempo": round(d0 / target, 3), "frames": frames, "keep_frames": keep})
    raw = out / "all_raw.wav"; out.mkdir(parents=True, exist_ok=True)
    sf.write(raw, np.concatenate(wins), SR)
    fin = out / "all_finished.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(raw), "-af", "highpass=f=70,loudnorm=I=-16:TP=-1.5:LRA=11",
                    "-ar", str(SR), "-ac", "1", str(fin)], check=True)
    y, _ = sf.read(fin, dtype="float32"); y = np.pad(y, (0, max(0, sum(map(len, wins)) - len(y))))
    pos, spf = 0, SR // FPS
    for w, m in zip(wins, meta):
        a = y[pos:pos + len(w)]; pos += len(w)
        d = out / m["id"]; d.mkdir(exist_ok=True)
        sf.write(d / "master_seed.wav", a[:SHOT * spf], SR)
        sf.write(d / "master_chain.wav", a[SHOT * spf:] if m["shots"] > 1 else np.zeros(spf, np.float32), SR)
        shots = [{"raw_frames": SHOT, "delivered_frames": SHOT if k == 0 else SHOT - CTX} for k in range(m["shots"])]
        json.dump({"fps": FPS, "context": CTX, "sr": SR, "total_frames": m["frames"], "shots": shots}, open(d / "shots.json", "w"), indent=1)
        texts = split_sentences(script[m["id"]], [s["delivered_frames"] / FPS for s in shots], m["speech_s"])
        json.dump({"run": f"{out.name}_{m['id']}", "anchor": aid, "beats": texts}, open(d / "story.json", "w"), indent=1)
        print(m, [t[:50] for t in texts])
    json.dump(meta, open(out / "appearances.json", "w"), indent=1)


if __name__ == "__main__":
    main()
