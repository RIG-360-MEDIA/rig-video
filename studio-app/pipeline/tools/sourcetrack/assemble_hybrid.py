"""Assemble a hybrid video (TEST): source_track anchor render + voiceover beats over footage -> final.mp4 with the DNL
graphics package and outro. Uses the deployed daily post helpers read-only (colour-lock, wall quad check, wall_comp,
lt_remotion package).
  anchor beat: its frames of the colour-locked anchor render, trimmed to lead + speech + 0.45 s, with story footage on the
               studio wall; sound = the master slice (identical to the render's own locked audio)
  vo beat:     its chosen shots back to back, filling the beat exactly (10 % centre crop removes corner logos), natural
               sound -18 dB under the master slice
usage (tools venv on trijya-7): assemble_hybrid.py <work_dir>
  work_dir: anchor.mp4 (raw render), master_full.wav, timeline.json, shots.json (hybrid_master.py), edl.json:
  {"meta": {anchor_name, lt_headline, location, kicker}, "ticker": [...],
   "beats": {"a1": {"wall": [clip, start_s]}, "v1": {"shots": [[clip, in_s, out_s], ...]}, ...}}
"""
import json, os, pathlib, subprocess, sys
APP = pathlib.Path(__file__).resolve().parents[2]   # this pipeline folder (studio-app/pipeline)
sys.path.insert(0, str(APP))
from orchestrator import post                                       # noqa: E402
from orchestrator.common import TOOLS_PY                            # noqa: E402

W, H, FPS, SR = 1280, 736, 24, 48000
FF = str(pathlib.Path.home() / "anchor-studio" / "repos" / "ffmpeg-shared" / "current" / "bin" / "ffmpeg")
os.environ["PATH"] = str(pathlib.Path(FF).parent) + os.pathsep + os.environ.get("PATH", "")   # colorlock/wall_comp call "ffmpeg"
CONFORM = f"crop=iw*0.9:ih*0.9,scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,fps={FPS},format=yuv420p"


def ff(*args):
    subprocess.run([FF, "-v", "error", "-y", *map(str, args)], check=True)


def main():
    work = pathlib.Path(sys.argv[1]).resolve(); seg = work / "segments"; seg.mkdir(exist_ok=True)
    tl, shots, edl = (json.load(open(work / f)) for f in ("timeline.json", "shots.json", "edl.json"))
    bounds, cum = [], 0
    for s in shots["shots"][:-1]:
        cum += s["delivered_frames"]; bounds.append(cum)
    cl = work / "anchor_colorlocked.mp4"
    subprocess.run([TOOLS_PY, str(APP / "tools" / "colorlock.py"), str(work / "anchor.mp4"), str(cl), ",".join(map(str, bounds))], check=True)
    quad = post.refine_quad(cl)
    print("wall quad", quad)
    parts = []
    for i, b in enumerate(tl["beats"]):
        a0, n = b["start_frame"] / FPS, b["frames"]
        e = edl["beats"][b["beat"]]
        out = seg / f"{i:02d}_{b['beat']}.mp4"
        if out.exists():                                               # re-run: keep finished segments
            parts.append(out); continue
        if b["type"] == "anchor":
            lead = 0.25 if i == 0 else 0.0
            n = min(n, round((lead + b["speech_s"] + 0.45) * FPS))
            v0 = b["anchor_video_start_frame"] / FPS
            body = seg / f"{i:02d}_body.mp4"
            ff("-ss", f"{v0:.4f}", "-i", cl, "-frames:v", n, "-c:v", "libx264", "-crf", 14, "-pix_fmt", "yuv420p", "-c:a", "aac", body)
            if quad and e.get("wall"):
                wall = seg / f"{i:02d}_wall.mp4"
                ff("-ss", e["wall"][1], "-i", e["wall"][0], "-t", n / FPS + 0.5, "-an", "-vf", CONFORM, "-c:v", "libx264", "-crf", 16, wall)
                walled = seg / f"{i:02d}_walled.mp4"
                subprocess.run([TOOLS_PY, str(APP / "tools" / "wall_comp.py"), str(body), str(wall), "0", str(walled), quad, "broll"], check=True)
                body = walled
            ff("-i", body, "-ss", f"{a0:.4f}", "-t", n / FPS, "-i", work / "master_full.wav", "-map", "0:v", "-map", "1:a",
               "-frames:v", n, "-c:v", "libx264", "-crf", 14, "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", SR, "-b:a", "256k", out)
        else:
            clips = e["shots"]; total = sum(o - s for _, s, o in clips)
            ins, fc, cur = [], [], 0
            for k, (path, s, o) in enumerate(clips):                       # each shot gets its share of the beat, last one exact
                f = (n - cur) if k == len(clips) - 1 else round(n * (o - s) / total)
                cur += f
                # read only the shot itself; if its share is longer, hold its last frame (never show the next shot)
                ins += ["-ss", f"{s:.3f}", "-t", f"{o - s:.3f}", "-i", path]
                fc.append(f"[{k}:v]{CONFORM},tpad=stop_mode=clone:stop_duration=2,trim=end_frame={f},setpts=PTS-STARTPTS[v{k}];"
                          f"[{k}:a]aresample={SR},apad,atrim=end={f / FPS:.4f},asetpts=PTS-STARTPTS,volume=-18dB[n{k}]")
            m = len(clips)
            fc.append("".join(f"[v{k}][n{k}]" for k in range(m)) + f"concat=n={m}:v=1:a=1[v][nat];"
                      f"[{m}:a]aresample={SR}[vo];[vo][nat]amix=inputs=2:duration=first:normalize=0[a]")
            ff(*ins, "-ss", f"{a0:.4f}", "-t", n / FPS, "-i", work / "master_full.wav", "-filter_complex", ";".join(fc),
               "-map", "[v]", "-map", "[a]", "-frames:v", n, "-c:v", "libx264", "-crf", 16, "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-ar", SR, "-b:a", "256k", out)
        parts.append(out); print("segment", out.name, f"{n / FPS:.2f}s", flush=True)
    # Join sample-exactly: AAC adds a little padding per segment, which adds up to frames of lip-sync drift over a
    # joined programme. Each segment's audio is cut to exactly its frames as PCM, the PCM is joined, encoded once.
    wavs = []
    for p in parts:
        frames = int(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames", "-show_entries",
                                     "stream=nb_read_frames", "-of", "csv=p=0", str(p)], capture_output=True, text=True).stdout.split(",")[0])   # ffprobe 6.1 prints "448," when the stream has side data
        w = p.with_suffix(".wav")
        ff("-i", p, "-vn", "-ac", 1, "-ar", SR, "-af", f"apad,atrim=end_sample={frames * SR // FPS}", "-c:a", "pcm_s16le", w)
        wavs.append(w)
    vl, al = work / "segments.txt", work / "segments_audio.txt"
    vl.write_text("".join(f"file '{p}'\n" for p in parts)); al.write_text("".join(f"file '{w}'\n" for w in wavs))
    prog = work / "programme.mp4"
    ff("-f", "concat", "-safe", 0, "-i", vl, "-f", "concat", "-safe", 0, "-i", al, "-map", "0:v", "-map", "1:a",
       "-c:v", "libx264", "-crf", 14, "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "256k", prog)
    story = work / "lt_story.json"
    story.write_text(json.dumps(post.lt_story(edl["meta"], edl["ticker"]), indent=2, ensure_ascii=False))
    env = dict(os.environ, PATH=str(pathlib.Path(post.NODE).parent) + ":" + os.environ["PATH"])
    if post.CHROME_LIBS.exists():
        env["LD_LIBRARY_PATH"] = str(post.CHROME_LIBS) + ":" + env.get("LD_LIBRARY_PATH", "")
    subprocess.run([post.NODE, str(post.APP / "lt_remotion" / "apply_broadcast_package.mjs"), str(prog), str(story), str(work / "final.mp4")],
                   check=True, cwd=post.APP, env=env)
    print("FINAL", work / "final.mp4")


if __name__ == "__main__":
    main()
