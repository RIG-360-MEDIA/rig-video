# Replace the H3 video-wall content with real footage/graphics, keeping the anchor in front.
# usage: wall_comp.py seed.mp4 content.mp4 content_start_s out.mp4 "x,y x,y x,y x,y" [broll|clean]
#   quad = wall corners TL TR BR BL measured on the rendered video (camera is locked)
#   broll = muted/soft b-roll; clean = graphics/posters stay sharp, full colour
# Needs: opencv, numpy, rembg (u2net_human_seg). Runs on CPU (~2 min per 13 s shot).
import subprocess, sys
import cv2, numpy as np
from rembg import new_session, remove

seed, broll, start, out = sys.argv[1], sys.argv[2], float(sys.argv[3]), sys.argv[4]
QUAD = np.float32([[float(v) for v in c.split(",")] for c in sys.argv[5].split()])
CLEAN = len(sys.argv) > 6 and sys.argv[6] == "clean"

cap_s, cap_b = cv2.VideoCapture(seed), cv2.VideoCapture(broll)
W, H = int(cap_s.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap_s.get(cv2.CAP_PROP_FRAME_HEIGHT))
n = int(cap_s.get(cv2.CAP_PROP_FRAME_COUNT))
sess = new_session("u2net_human_seg")

wall = np.zeros((H, W), np.uint8)
cv2.fillConvexPoly(wall, QUAD.astype(np.int32), 255)
wall = cv2.GaussianBlur(wall, (5, 5), 0).astype(np.float32) / 255  # soft 2px edge


def warp(f, bw, bh):
    M = cv2.getPerspectiveTransform(np.float32([[0, 0], [bw, 0], [bw, bh], [0, bh]]), QUAD)
    return cv2.warpPerspective(f, M, (W, H), flags=cv2.INTER_LINEAR)


def content_frame(i):
    cap_b.set(cv2.CAP_PROP_POS_MSEC, (start + i / 24.0) * 1000)
    ok, f = cap_b.read()
    if not ok:  # content shorter than the video: hold the last good frame
        cap_b.set(cv2.CAP_PROP_POS_FRAMES, max(0, cap_b.get(cv2.CAP_PROP_FRAME_COUNT) - 1)); ok, f = cap_b.read()
    bw, bh = 960, int(960 * f.shape[0] / f.shape[1])
    f = cv2.resize(f, (bw, bh), interpolation=cv2.INTER_AREA)
    f = cv2.GaussianBlur(f, (0, 0), 0.6 if CLEAN else 1.6)   # soft, like a screen seen past focus
    if not CLEAN:
        hsv = cv2.cvtColor(f, cv2.COLOR_BGR2HSV).astype(np.float32)
        hsv[..., 1] *= 0.6                                   # muted / desaturated
        f = cv2.cvtColor(hsv.clip(0, 255).astype(np.uint8), cv2.COLOR_HSV2BGR)
    return warp(f, bw, bh)


ff = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", "24",
                       "-i", "-", "-i", seed, "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-crf", "16",
                       "-pix_fmt", "yuv420p", "-c:a", "copy", out], stdin=subprocess.PIPE)
stats = None
for i in range(n):
    ok, fr = cap_s.read()
    if not ok:
        break
    person = remove(fr, session=sess, only_mask=True, post_process_mask=True).astype(np.float32) / 255
    alpha = (wall * (1 - person))[..., None]
    b = content_frame(i).astype(np.float32)
    if stats is None:  # match the new content's exposure/colour to H3's own lit wall
        m = alpha[..., 0] > 0.9
        src, dst = b[m], fr[m].astype(np.float32)
        stats = (src.mean(0), src.std(0) + 1e-3, dst.mean(0), dst.std(0))
    sm, ss, dm, ds = stats
    k = 0.25 if CLEAN else 0.5
    b = (1 - k) * b + k * ((b - sm) / ss * ds + dm)
    comp = fr.astype(np.float32) * (1 - alpha) + b.clip(0, 255) * alpha
    ff.stdin.write(comp.astype(np.uint8).tobytes())
    if i % 50 == 0:
        print(i, "/", n, flush=True)
ff.stdin.close(); ff.wait()
print("wrote", out)
