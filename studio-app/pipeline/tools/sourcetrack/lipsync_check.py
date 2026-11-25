"""Lip-sync + audio-lock check for an anchor video (camera locked, one face).
1. audio lock: the video's audio vs the expected master (cross-correlation peak and offset).
2. lip sync: mouth openness per frame (darkness of the mouth region, which rises when the mouth opens) vs the audio's
   loudness per frame; the best lag in +-12 frames and its correlation. In sync = best lag near 0 with a clear peak.
usage: lipsync_check.py video.mp4 [master.wav] [start_s end_s]   (window optional, in video seconds)
Measure an anchor clip on its own (or a piece cut out of a finished video): the mouth box is found from frames across the
whole file, so on a finished video with footage segments it can land on the wrong face and report a false lag.
"""
import subprocess, sys
import cv2, numpy as np, soundfile as sf
from scipy.signal import correlate

FPS, SR = 24, 16000


def audio(path):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32)


def mouth_box(cap, n):
    det = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    boxes = []
    for i in np.linspace(0, n - 1, 25).astype(int):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(i)); ok, f = cap.read()
        if ok:
            fs = det.detectMultiScale(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY), 1.1, 5, minSize=(40, 40))
            if len(fs):
                boxes.append(max(fs, key=lambda b: b[2] * b[3]))
    x, y, w, h = np.median(np.array(boxes), axis=0).astype(int)
    return x + w // 4, y + int(h * 0.68), w // 2, int(h * 0.25), len(boxes), (x, y, w, h)


def z(v):
    return (v - v.mean()) / (v.std() + 1e-9)


def main():
    vid = sys.argv[1]
    master = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2].endswith(".wav") else None
    win = [float(v) for v in sys.argv[3:5]] if len(sys.argv) > 4 else None
    a = audio(vid)
    if master:
        m, sr = sf.read(master, dtype="float32")
        m = audio(master) if sr != SR or m.ndim > 1 else m
        k = min(len(a), len(m))
        c = correlate(a[:k], m[:k], "full", method="fft")
        lag = int(np.argmax(np.abs(c))) - (k - 1)
        peak = float(np.max(np.abs(c)) / (np.linalg.norm(a[:k]) * np.linalg.norm(m[:k]) + 1e-9))
        print(f"AUDIO vs master: correlation {peak:.3f} at offset {lag / SR * 1000:+.1f} ms (video {len(a) / SR:.2f} s, master {len(m) / SR:.2f} s)")
    cap = cv2.VideoCapture(vid); n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    mx, my, mw, mh, found, face = mouth_box(cap, n)
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    dark = []
    while True:
        ok, f = cap.read()
        if not ok:
            break
        g = cv2.cvtColor(f[my:my + mh, mx:mx + mw], cv2.COLOR_BGR2GRAY).astype(np.float32)
        dark.append(-np.percentile(g, 10))                  # open mouth -> dark interior -> low 10th percentile
    dark = np.array(dark)
    hop = SR // FPS
    rms = np.array([np.sqrt(np.mean(a[i * hop:(i + 1) * hop] ** 2) + 1e-12) for i in range(len(dark))])
    loud = 20 * np.log10(rms + 1e-6)
    lo, hi = (int(win[0] * FPS), int(win[1] * FPS)) if win else (0, len(dark))
    d, l = z(np.diff(dark[lo:hi])), z(np.diff(loud[lo:hi]))  # changes, so slow lighting/pose drift does not count
    lags = range(-12, 13)
    cc = [float(np.mean(d[max(0, k):len(d) + min(0, k)] * l[max(0, -k):len(l) - max(0, k)])) for k in lags]
    best = int(np.argmax(cc))
    print(f"FACE found in {found}/25 samples, face box {face}, mouth box {(mx, my, mw, mh)}")
    print(f"LIPSYNC frames {lo}-{hi}: best lag {list(lags)[best]:+d} frames (+ = mouth after sound), corr {cc[best]:.3f}, "
          f"corr at 0 {cc[12]:.3f}, median |corr| {np.median(np.abs(cc)):.3f}")


if __name__ == "__main__":
    main()
