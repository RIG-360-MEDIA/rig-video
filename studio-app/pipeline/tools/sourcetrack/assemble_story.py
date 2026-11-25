"""Assemble a story video for the studio app: anchor appearances (each its own source_track render) and, between them,
voiceover parts (pictures with their own sound muted, the anchor's voice over them; user default 2026-10-27) or footage
parts that keep their own sound (the no-voiceover option). DNL graphics (name tag on the first appearance only, headline
lower third, ticker, location, logo) only over the anchor's shots; the DNL outro only when edl meta "outro" is set (NDC
videos have none, user 2026-10-28; RIG-Video ends with it, user 2026-11-13); joined frame-exactly
with sample-exact audio; the whole mix ends at -14 LUFS. Same anchor handling as assemble_novo.py.
usage (tools venv on trijya-7): assemble_story.py <work_dir> <order>   e.g. "a1 v1 a2 v2 a3 v3 a4"
  work_dir: <aX>.mp4 renders + <aX>/ masters, appearances.json (make_appearances.py), edl.json:
  {"meta": {anchor_name, lt_headline, location, kicker}, "ticker": [...],
   "beats": {"aX": {"wall": [file, start]},
             "vX": {"pictures": file, "voice": wav}          voiceover: pictures exactly as long as the voice wav
             "nX": {"shots": [[clip, in, out], ...]}}}       footage with its own sound
Writes final.mp4 and segments.json ([[beat, frames], ...]).
"""
import json, pathlib, subprocess, sys
from assemble_hybrid import CONFORM, FPS, SR, TOOLS_PY, APP, ff, post
from assemble_novo import LUFS_FINAL, LUFS_SEGMENT, frames_of, graphics
FADE_OUT = 0.6                                                  # seconds; natural-sound (sot) segments only


def anchor(work, seg, i, b, a, edl, first):
    out = seg / f"{i:02d}_{b}.mp4"
    if not out.exists():
        cl = work / f"{b}.mp4"
        if a["shots"] > 1:                                      # colour-lock the chain's shots to its first
            cl = seg / f"{b}_cl.mp4"
            bounds = ",".join(str(328 + k * 289) for k in range(a["shots"] - 1))
            subprocess.run([TOOLS_PY, str(APP / "tools" / "colorlock.py"), str(work / f"{b}.mp4"), str(cl), bounds], check=True)
        body = seg / f"{b}_body.mp4"
        ff("-i", cl, "-frames:v", a["keep_frames"], "-af", f"aresample={SR},atrim=end_sample={a['keep_frames'] * SR // FPS}",
           "-c:v", "libx264", "-crf", 14, "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "256k", body)
        quad = post.refine_quad(body)
        if quad and edl["beats"].get(b, {}).get("wall"):
            wall = seg / f"{b}_wall.mp4"; w = edl["beats"][b]["wall"]
            ff("-ss", w[1], "-i", w[0], "-t", a["keep_frames"] / FPS + 0.5, "-an", "-vf", CONFORM, "-c:v", "libx264", "-crf", 16, wall)
            walled = seg / f"{b}_walled.mp4"
            subprocess.run([TOOLS_PY, str(APP / "tools" / "wall_comp.py"), str(body), str(wall), "0", str(walled), quad, "broll"], check=True)
            body = walled
        graphics(body, out, edl["meta"], edl["ticker"], first)
    w = seg / f"{i:02d}_{b}.wav"                                # the anchor's sound = his finished voice master itself
    ff("-i", work / b / "master_seed.wav", "-i", work / b / "master_chain.wav", "-filter_complex",
       f"[0:a][1:a]concat=n=2:v=0:a=1,aresample={SR},atrim=end_sample={a['keep_frames'] * SR // FPS}" if a["shots"] > 1
       else f"[0:a]aresample={SR},atrim=end_sample={a['keep_frames'] * SR // FPS}", "-ac", 1, "-c:a", "pcm_s16le", w)
    return out, w


def voiceover(seg, i, b, spec):
    """Pictures muted; the voice wav (already led, padded and finished) is the sound, cut to the video's frames."""
    out = seg / f"{i:02d}_{b}.mp4"
    n = int(round(float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", spec["voice"]],
                                       capture_output=True, text=True).stdout) * FPS))
    if not out.exists():
        ff("-i", spec["pictures"], "-frames:v", n, "-an", "-vf", "setpts=N/(24*TB)", "-fps_mode", "cfr", "-r", FPS,
           "-c:v", "libx264", "-crf", 16, "-pix_fmt", "yuv420p", out)
    n = frames_of(out)
    w = seg / f"{i:02d}_{b}.wav"
    ff("-i", spec["voice"], "-af", f"aresample={SR},apad,atrim=end_sample={n * SR // FPS}", "-ac", 1, "-c:a", "pcm_s16le", w)
    return out, w


def natural(seg, i, b, spec):
    """Footage with its own sound (no-voiceover format), as assemble_novo.py."""
    out = seg / f"{i:02d}_{b}.mp4"
    if not out.exists():
        clips, ins, fc = spec["shots"], [], []
        for k, (path, s, o) in enumerate(clips):
            ins += ["-ss", f"{s:.3f}", "-t", f"{o - s:.3f}", "-i", path]
            fc.append(f"[{k}:v]{CONFORM},setpts=PTS-STARTPTS[v{k}];[{k}:a]aresample={SR},asetpts=PTS-STARTPTS[s{k}]")
        m = len(clips)
        fc.append("".join(f"[v{k}][s{k}]" for k in range(m)) + f"concat=n={m}:v=1:a=1[vc][a0];[vc]setpts=N/({FPS}*TB)[v];"
                  f"[a0]loudnorm=I={LUFS_SEGMENT}:TP=-1.5:LRA=11,aresample={SR}[a]")
        ff(*ins, "-filter_complex", ";".join(fc), "-map", "[v]", "-map", "[a]", "-fps_mode", "cfr", "-r", FPS, "-c:v", "libx264",
           "-crf", 16, "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", SR, "-b:a", "256k", out)
    w = seg / f"{i:02d}_{b}.wav"
    d = frames_of(out) / FPS                                    # sound-ups fade in and out instead of cutting hard (user 2026-11-03)
    ff("-i", out, "-vn", "-ac", 1, "-ar", SR, "-af", f"apad,atrim=end_sample={frames_of(out) * SR // FPS},"
       f"afade=t=in:d=0.15,afade=t=out:st={max(0, d - FADE_OUT):.3f}:d={min(FADE_OUT, d):.3f}", "-c:a", "pcm_s16le", w)
    return out, w


def main():
    work = pathlib.Path(sys.argv[1]).resolve(); order = sys.argv[2].split()
    seg = work / "segments"; seg.mkdir(exist_ok=True)
    apps = {a["id"]: a for a in json.load(open(work / "appearances.json"))}
    edl = json.load(open(work / "edl.json"))
    parts, wavs, segments, first = [], [], [], not edl["meta"].get("no_name_tag")   # NDC bulletin: name tag in section 1 only
    for i, b in enumerate(order):
        spec = edl["beats"].get(b, {})
        if b in apps:
            out, w = anchor(work, seg, i, b, apps[b], edl, first); first = False
        elif "voice" in spec:
            out, w = voiceover(seg, i, b, spec)
        else:
            out, w = natural(seg, i, b, spec)
        parts.append(out); wavs.append(w); segments.append([b, frames_of(out)])
        print("segment", out.name, f"{segments[-1][1] / FPS:.2f}s", flush=True)
    if edl["meta"].get("outro"):                                # RIG-Video: the DNL outro closes the video (NDC jobs leave it out)
        outro = seg / "99_outro.mp4"
        if not outro.exists():
            ff("-i", post.OUTRO, "-vf", CONFORM.replace("crop=iw*0.9:ih*0.9,", ""), "-c:v", "libx264", "-crf", 16,
               "-c:a", "aac", "-ar", SR, "-b:a", "256k", outro)
        w = outro.with_suffix(".wav")                           # last, so its AAC offset cannot shift anything
        ff("-i", outro, "-vn", "-ac", 1, "-ar", SR, "-af", f"apad,atrim=end_sample={frames_of(outro) * SR // FPS}", "-c:a", "pcm_s16le", w)
        parts.append(outro); wavs.append(w); segments.append(["outro", frames_of(outro)])
    al = work / "segments_audio.txt"; al.write_text("".join(f"file '{x}'\n" for x in wavs))
    final = work / "final.mp4"
    ins = [x for p in parts for x in ("-i", str(p))]
    vcat = "".join(f"[{k}:v]setpts=PTS-STARTPTS[v{k}];" for k in range(len(parts))) + \
        "".join(f"[v{k}]" for k in range(len(parts))) + f"concat=n={len(parts)}:v=1:a=0[v]"
    ff(*ins, "-f", "concat", "-safe", 0, "-i", al, "-filter_complex", vcat, "-map", "[v]", "-map", f"{len(parts)}:a",
       "-af", f"loudnorm=I={LUFS_FINAL}:TP=-1:LRA=11,aresample={SR}", "-fps_mode", "cfr", "-r", FPS, "-c:v", "libx264",
       "-crf", 16, "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart", final)
    (work / "segments.json").write_text(json.dumps(segments))
    print("FINAL", final, f"{frames_of(final) / FPS:.2f}s")


if __name__ == "__main__":
    main()
