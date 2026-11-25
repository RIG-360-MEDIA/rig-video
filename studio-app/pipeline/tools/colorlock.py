# Colour-lock (PIPELINE_ARCHITECTURE §8): per-part constant HSV gain so every part's mid-frame
# brightness (V) and saturation (S) match part 1's. usage: colorlock.py in.mp4 out.mp4 b1,b2,b3,...  (part boundaries in frames)
import subprocess, sys, cv2, numpy as np
src, out, bounds = sys.argv[1], sys.argv[2], [int(x) for x in sys.argv[3].split(",")]
cap = cv2.VideoCapture(src); n = int(cap.get(7)); W, H = int(cap.get(3)), int(cap.get(4))
edges = [0] + bounds + [n]
def mid_stats(i):
    cap.set(1, i); ok, f = cap.read(); h = cv2.cvtColor(f, cv2.COLOR_BGR2HSV).astype(np.float32)
    return h[..., 2].mean(), h[..., 1].mean()
st = [mid_stats((a + b) // 2) for a, b in zip(edges, edges[1:])]
gains = [(st[0][0] / v, st[0][1] / s) for v, s in st]
print("gains (V,S):", [f"{g[0]:.3f},{g[1]:.3f}" for g in gains])
cap.set(1, 0)
ff = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", "24", "-i", "-",
                       "-i", src, "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p", "-c:a", "copy", out],
                      stdin=subprocess.PIPE)
part = 0
for i in range(n):
    ok, f = cap.read()
    while i >= edges[part + 1]: part += 1
    gv, gs = gains[part]
    if part:
        h = cv2.cvtColor(f, cv2.COLOR_BGR2HSV).astype(np.float32)
        h[..., 2] *= gv; h[..., 1] *= gs
        f = cv2.cvtColor(h.clip(0, 255).astype(np.uint8), cv2.COLOR_HSV2BGR)
    ff.stdin.write(f.tobytes())
ff.stdin.close(); ff.wait()
c2 = cv2.VideoCapture(out)
for a, b in zip(edges, edges[1:]):
    c2.set(1, (a + b) // 2); ok, f = c2.read(); h = cv2.cvtColor(f, cv2.COLOR_BGR2HSV).astype(np.float32)
    print(f"verify {a}-{b}: bright {h[...,2].mean():.1f} sat {h[...,1].mean():.1f}")
