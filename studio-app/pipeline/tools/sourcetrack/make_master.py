"""source_track voice master (TEST, separate from the daily pipeline): one TTS take per beat -> one continuous master whose
beats line up with H3 shots. Beat 1 fills the seed shot (raw L1 frames); beat k>1 fills chain shot k's DELIVERED frames
(raw - 39 context). Pauses are silence padding, so every window holds exactly its own beat. One finish (high-pass +
loudness) over the whole master, then it is cut at frame boundaries (24 fps) into:
  master_full.wav   the whole read (what the final video must carry)
  master_seed.wav   seed window, L1 frames (seed job's Source Timeline)
  master_chain.wav  everything after the seed (chain job's Source Timeline; the pack starts it at 0 after the prelude)
  shots.json        per shot: beat text, raw frames, delivered frames, speech seconds

usage: make_master.py <out_dir> <take1.wav> <take2.wav> ... (in beat order)
"""
import json, math, pathlib, subprocess, sys
import numpy as np, soundfile as sf

FPS, CTX, SR = 24, 39, 24000
VALID = [5 + 17 * k for k in range(30)]                      # H3 valid lengths: L % 17 == 5
LEAD, GAP, TAIL = 0.25, 0.35, 0.6                            # seconds: before the first word, min pause after a beat, after the last


def trimmed(path):
    """Mono float32 at SR with leading/trailing silence (< -45 dBFS) removed, 30 ms kept each side."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    x = np.frombuffer(raw, np.float32)
    env = np.convolve(np.abs(x), np.ones(240) / 240, "same")
    on = np.where(env > 10 ** (-45 / 20))[0]
    pad = int(0.03 * SR)
    return x[max(0, on[0] - pad):on[-1] + pad]


def up(frames):
    return next(L for L in VALID if L >= frames)


def main():
    out, takes = pathlib.Path(sys.argv[1]), sys.argv[2:]
    out.mkdir(parents=True, exist_ok=True)
    parts, shots = [], []
    for i, t in enumerate(takes):
        x = trimmed(t); d = len(x) / SR
        lead = LEAD if i == 0 else 0.0
        need = lead + d + (TAIL if i == len(takes) - 1 else GAP)
        if i == 0:
            raw = up(math.ceil(need * FPS)); delivered = raw
        else:
            raw = up(math.ceil(need * FPS) + CTX); delivered = raw - CTX
        win = np.zeros(delivered * SR // FPS, np.float32)
        win[int(lead * SR):int(lead * SR) + len(x)] = x
        parts.append(win)
        shots.append({"take": pathlib.Path(t).name, "raw_frames": raw, "delivered_frames": delivered,
                      "speech_s": round(d, 2), "pause_after_s": round(delivered / FPS - lead - d, 2)})
    full = np.concatenate(parts)
    sf.write(out / "master_raw.wav", full, SR)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(out / "master_raw.wav"), "-af",
                    "highpass=f=70,loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", str(SR), "-ac", "1", str(out / "master_full.wav")], check=True)
    y, _ = sf.read(out / "master_full.wav", dtype="float32")
    y = np.pad(y, (0, max(0, len(full) - len(y))))[:len(full)]      # loudnorm keeps length; guard the last samples
    cut = shots[0]["delivered_frames"] * SR // FPS
    sf.write(out / "master_full.wav", y, SR)
    sf.write(out / "master_seed.wav", y[:cut], SR)
    sf.write(out / "master_chain.wav", y[cut:], SR)
    total = sum(s["delivered_frames"] for s in shots)
    assert len(y) == total * SR // FPS and all(s["raw_frames"] in VALID for s in shots)
    json.dump({"fps": FPS, "context": CTX, "sr": SR, "total_frames": total, "shots": shots}, open(out / "shots.json", "w"), indent=1)
    for s in shots:
        print(s)
    print(f"master {total / FPS:.2f} s, seed {shots[0]['raw_frames']} frames + chain {[s['raw_frames'] for s in shots[1:]]}")


if __name__ == "__main__":
    main()
