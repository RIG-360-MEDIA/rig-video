"""Assemble a NO-voiceover story video (the default format, user 2026-10-26): anchor appearances (each its own
source_track render) alternate with footage segments that keep their own sound. DNL graphics (name tag on the first
appearance only, headline lower third, ticker, location, logo) are applied to each anchor appearance alone, never to
footage; the DNL outro closes the video; the whole mix ends at -14 LUFS.
usage (tools venv on trijya-7): assemble_novo.py <work_dir> <order>   e.g. "a1 v1 a2 v2 a3 v3 a4"
  work_dir: <aX>.mp4 renders, appearances.json (make_appearances.py), edl.json ({"meta", "ticker",
            "beats": {"aX": {"wall": [file, start]}, "vX": {"shots": [[clip, in, out], ...]}}})
"""
import json, os, pathlib, subprocess, sys
from assemble_hybrid import CONFORM, FF, FPS, SR, TOOLS_PY, APP, ff, post

LUFS_SEGMENT, LUFS_FINAL = -16, -14


def frames_of(p):
    return int(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames", "-show_entries",
                               "stream=nb_read_frames", "-of", "csv=p=0", str(p)], capture_output=True, text=True).stdout.split(",")[0])   # ffprobe 6.1 prints "448," when the stream has side data


def graphics(src, out, meta, ticker, first):
    story = post.lt_story(meta, ticker)
    story.pop("outro")                                          # the outro is added once, at the very end
    story["lowerThird"].update(holdSeconds=8, repeatEverySeconds=0)
    if not first:                                               # name tag only on the anchor's first appearance
        story["nameTag"] = {"inSeconds": 0.0, "holdSeconds": 0.0, "outSeconds": 0.0}
        story["lowerThird"]["startSeconds"] = 0.6
    sj = out.with_suffix(".json"); sj.write_text(json.dumps(story, indent=2, ensure_ascii=False))
    env = dict(os.environ, PATH=str(pathlib.Path(post.NODE).parent) + ":" + os.environ["PATH"])
    if post.CHROME_LIBS.exists():
        env["LD_LIBRARY_PATH"] = str(post.CHROME_LIBS) + ":" + env.get("LD_LIBRARY_PATH", "")
    subprocess.run([post.NODE, str(post.APP / "lt_remotion" / "apply_broadcast_package.mjs"), str(src), str(sj), str(out)],
                   check=True, cwd=post.APP, env=env)


def main():
    work = pathlib.Path(sys.argv[1]).resolve(); order = sys.argv[2].split()
    seg = work / "segments"; seg.mkdir(exist_ok=True)
    apps = {a["id"]: a for a in json.load(open(work / "appearances.json"))}
    edl = json.load(open(work / "edl.json"))
    parts, wavs, first = [], [], True
    for i, b in enumerate(order):
        out = seg / f"{i:02d}_{b}.mp4"
        if b in apps:
            a = apps[b]
            if not out.exists():
                cl = work / f"{b}.mp4"
                if a["shots"] > 1:                                  # colour-lock the chain's shots to its first
                    cl = seg / f"{b}_cl.mp4"
                    bounds = ",".join(str(328 + k * 289) for k in range(a["shots"] - 1))
                    subprocess.run([TOOLS_PY, str(APP / "tools" / "colorlock.py"), str(work / f"{b}.mp4"), str(cl), bounds], check=True)
                body = seg / f"{b}_body.mp4"
                ff("-i", cl, "-frames:v", a["keep_frames"], "-af", f"aresample={SR},atrim=end_sample={a['keep_frames'] * SR // FPS}", "-c:v", "libx264", "-crf", 14, "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "256k", body)
                quad = post.refine_quad(body)
                if quad and edl["beats"].get(b, {}).get("wall"):
                    wall = seg / f"{b}_wall.mp4"; w = edl["beats"][b]["wall"]
                    ff("-ss", w[1], "-i", w[0], "-t", a["keep_frames"] / FPS + 0.5, "-an", "-vf", CONFORM, "-c:v", "libx264", "-crf", 16, wall)
                    walled = seg / f"{b}_walled.mp4"
                    subprocess.run([TOOLS_PY, str(APP / "tools" / "wall_comp.py"), str(body), str(wall), "0", str(walled), quad, "broll"], check=True)
                    body = walled
                graphics(body, out, edl["meta"], edl["ticker"], first)
            first = False
            # the anchor's sound is his finished voice master itself (sample-exact; no AAC in the audio path)
            w = seg / f"{i:02d}_{b}.wav"
            ff("-i", work / b / "master_seed.wav", "-i", work / b / "master_chain.wav", "-filter_complex",
               f"[0:a][1:a]concat=n=2:v=0:a=1,aresample={SR},atrim=end_sample={a['keep_frames'] * SR // FPS}" if a["shots"] > 1
               else f"[0:a]aresample={SR},atrim=end_sample={a['keep_frames'] * SR // FPS}", "-ac", 1, "-c:a", "pcm_s16le", w)
            wavs.append(w)
        elif not out.exists():
            clips = edl["beats"][b]["shots"]
            ins, fc = [], []
            for k, (path, s, o) in enumerate(clips):
                ins += ["-ss", f"{s:.3f}", "-t", f"{o - s:.3f}", "-i", path]
                fc.append(f"[{k}:v]{CONFORM},setpts=PTS-STARTPTS[v{k}];[{k}:a]aresample={SR},asetpts=PTS-STARTPTS[s{k}]")
            m = len(clips)
            fc.append("".join(f"[v{k}][s{k}]" for k in range(m)) + f"concat=n={m}:v=1:a=1[vc][a0];"
                      f"[vc]setpts=N/({FPS}*TB)[v];"                # exactly one frame per 1/24 s (joined shots leave gaps)
                      f"[a0]loudnorm=I={LUFS_SEGMENT}:TP=-1.5:LRA=11,aresample={SR}[a]")
            fc[-1] += ";[a]asplit=2[a1][a2]"
            ff(*ins, "-filter_complex", ";".join(fc), "-map", "[v]", "-map", "[a1]", "-fps_mode", "cfr", "-r", FPS, "-c:v", "libx264", "-crf", 16,
               "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", SR, "-b:a", "256k", out,
               "-map", "[a2]", "-ac", 1, "-ar", SR, "-c:a", "pcm_s16le", out.with_suffix(".wav"))     # exact audio for the join
        if b not in apps:
            w = out.with_suffix(".wav")
            ff("-i", w, "-af", f"apad,atrim=end_sample={frames_of(out) * SR // FPS}", "-c:a", "pcm_s16le", w.with_name(w.stem + "_x.wav"))
            wavs.append(w.with_name(w.stem + "_x.wav"))
        parts.append(out); print("segment", out.name, f"{frames_of(out) / FPS:.2f}s", flush=True)
    outro = seg / "99_outro.mp4"
    if not outro.exists():
        ff("-i", post.OUTRO, "-vf", CONFORM.replace("crop=iw*0.9:ih*0.9,", ""), "-c:v", "libx264", "-crf", 16,
           "-c:a", "aac", "-ar", SR, "-b:a", "256k", outro)
    parts.append(outro)
    w = outro.with_suffix(".wav")                               # the outro comes last: its own AAC offset cannot shift anything
    ff("-i", outro, "-vn", "-ac", 1, "-ar", SR, "-af", f"apad,atrim=end_sample={frames_of(outro) * SR // FPS}", "-c:a", "pcm_s16le", w)
    wavs.append(w)
    # join: video segments as they are, audio from the sample-exact PCM above, one loudness pass, one encode
    # video joined frame by frame (concat filter: exact frame counts, unlike the concat demuxer, which places each file
    # by its container length -- AAC tails then shift every later segment); audio = the sample-exact PCM above
    al = work / "segments_audio.txt"; al.write_text("".join(f"file '{w}'\n" for w in wavs))
    final = work / "final.mp4"
    ins = [x for p in parts for x in ("-i", str(p))]
    vcat = "".join(f"[{k}:v]setpts=PTS-STARTPTS[v{k}];" for k in range(len(parts))) + \
        "".join(f"[v{k}]" for k in range(len(parts))) + f"concat=n={len(parts)}:v=1:a=0[v]"
    ff(*ins, "-f", "concat", "-safe", 0, "-i", al, "-filter_complex", vcat, "-map", "[v]", "-map", f"{len(parts)}:a",
       "-af", f"loudnorm=I={LUFS_FINAL}:TP=-1:LRA=11,aresample={SR}", "-fps_mode", "cfr", "-r", FPS, "-c:v", "libx264",
       "-crf", 16, "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "256k", final)
    print("FINAL", final, f"{frames_of(final) / FPS:.2f}s")


if __name__ == "__main__":
    main()
