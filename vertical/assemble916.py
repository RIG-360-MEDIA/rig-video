"""Final 9:16 video of a checked VO-only story (project.json with edit.beats) - the Review page's video.
usage (t7, a python with numpy + soundfile + faster_whisper): assemble916.py <project dir> <work dir> [project.json to use]
  -> <work dir>/final_916.mp4 + build.json
Each cut: its range downloaded at source resolution (up to 1080p, MARGIN s spare each side) and cut exactly; a text shot
(post_or_document) keeps the whole frame (--fit); any other cut is converted, then cropcheck.py asks whether the vertical
frame still shows what the shot was picked for at its key moment, else it is made whole too.
Sound (sound916): each shot whose cut has a "sound" (the checker's suggestion, the editor's word) gets that foley
sound, a first shot with sound leads in with it before the voice, and up to two loud shots are lengthened from the spare footage into a sound-up between beats. Graphics (gfx916): captions,
title card, quote cards. One final encode.
Files are named by the cut (video, start, length, kind), so a rebuild after an edit only makes the changed cuts.
When YouTube refuses the download (bot check on a shared IP), the checker's own <=480p copy is used and counted as low.
Prints PROGRESS k/n and STAGE <what>."""
import json, os, pathlib, subprocess, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import gfx916, sound916
H = pathlib.Path.home()
FF = str(H / "anchor-studio/repos/ffmpeg-shared/current/bin/ffmpeg")
YT = os.environ.get("VO_YTDLP", str(H / "anchor-studio/repos/social_verifier/ytdlp_node.sh"))
PY, V = str(H / "anchor-studio/vertical/.venv/bin/python"), str(H / "anchor-studio/vertical") + "/"
CACHE = pathlib.Path(os.environ.get("VO_CACHE", H / "vo_check" / "cache"))
FMT = "bv*[height<=1080][vcodec^=avc1]/bv*[height<=1080]/b[height<=1080]"
MARGIN = 4.0


def run(*a, **k):
    return subprocess.run([str(x) for x in a], check=True, **k)


def download(c, raw):
    """(file, offset of its first frame in the source video, full quality?)"""
    st, meta = c["src"]["start"], raw.with_suffix(".json")
    if raw.exists():                        # raws made before the sidecar had 2 s spare
        return raw, json.loads(meta.read_text())["a"] if meta.exists() else max(0.0, st - 2), True
    a = max(0.0, st - MARGIN)
    for _ in range(2):                      # a stall is ended by the socket timeout / overall limit and tried again
        try:
            run(YT, "-q", "--no-warnings", "--socket-timeout", "30", "-f", FMT, "--merge-output-format", "mp4",
                "--force-keyframes-at-cuts", "--download-sections", f"*{a:.2f}-{st + c['secs'] + MARGIN:.2f}",
                "-o", raw, f"https://www.youtube.com/watch?v={c['src']['youtubeId']}", timeout=600, capture_output=True)
            if raw.exists():
                meta.write_text(json.dumps({"a": a}))
                return raw, a, True
        except subprocess.SubprocessError as e:
            if b"not a bot" in (getattr(e, "stderr", b"") or b""):
                break                       # the IP is blocked: trying again does not help
        raw.unlink(missing_ok=True)
    low = CACHE / f"{c['src']['youtubeId']}.mp4"
    if low.exists():
        return low, 0.0, False
    raise RuntimeError(f"could not download {c['src']['youtubeId']}")


def secs_of(f):
    return float(subprocess.run([FF[:-6] + "ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)],
                                capture_output=True, text=True).stdout or 0)


def build(pd, out, pj=None):
    out.mkdir(parents=True, exist_ok=True)
    pj = pj or pd / "project.json"
    p = json.load(open(pj))
    lines = {s["id"]: s for s in p["versions"]["vo_only"]}
    beats = p["edit"]["beats"]
    n = sum(len(b["cuts"]) for b in beats) + 3
    cuts, voices, k = [], {}, 0
    for b in beats:
        s = lines[b["sectionId"]]
        for c in b["cuts"]:
            k += 1
            print(f"PROGRESS {k}/{n}", flush=True)
            cut = {"beat": b["sectionId"], "shows": c["shows"], "secs": c["secs"], "before": 0.0, "after": 0.0}
            if c["src"]["kind"] != "video":                     # one of our own pictures: held for the cut, whole (--fit), silent
                img = pd / c["poster"].split(f"/files/{p['id']}/", 1)[1].split("?")[0]
                key = f"{img.stem}_{c['secs']:.2f}"
                v, how = out / f"v_{key}_pic.mp4", out / f"v_{key}_pic.how.json"
                if not (v.exists() and how.exists()):
                    src = out / f"src_{key}.mp4"
                    run(FF, "-v", "error", "-y", "-loop", "1", "-t", f"{c['secs']:.3f}", "-i", img, "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2,fps=25",
                        "-c:v", "libx264", "-crf", "14", "-pix_fmt", "yuv420p", src)
                    run(PY, V + "vconv.py", src, v, "--fit", capture_output=True, text=True)
                    how.write_text(json.dumps({"how": "whole frame: own picture", "full": True}))
                cut["loud"] = -1
            else:
                key = f"{c['src']['youtubeId']}_{c['src']['start']:.2f}_{c['secs']:.2f}"
                v, how = out / f"v_{key}_{c['kind']}.mp4", out / f"v_{key}_{c['kind']}.how.json"
                f, a, full = download(c, out / f"raw_{key}.mp4")
                cut.update(raw=f, a=a, start=c["src"]["start"], before=round(c["src"]["start"] - a, 2),
                           after=round(max(0.0, secs_of(f) - (c["src"]["start"] - a) - c["secs"] - 0.1), 2),
                           loud=sound916.loud(c), prompt=sound916.prompt(c), kind=c["kind"])
                if not (v.exists() and how.exists()) or full and not json.loads(how.read_text()).get("full", True):
                    src = out / f"src_{key}.mp4"
                    run(FF, "-v", "error", "-y", "-ss", f"{c['src']['start'] - a:.3f}", "-t", f"{c['secs']:.3f}", "-i", f,
                        "-an", "-c:v", "libx264", "-crf", "14", "-preset", "medium", src)
                    conv = lambda *x: run(PY, V + "vconv.py", src, v, *x, capture_output=True, text=True)
                    if c["kind"] == "post_or_document":
                        conv("--fit"); h = {"how": "whole frame: text shot"}
                    else:
                        conv()
                        fo = c["src"].get("focus")
                        r = subprocess.run([PY, V + "cropcheck.py", str(src), str(v), c["shows"],
                                            *([f"{fo - c['src']['start']:.2f}"] if fo is not None else []), "--line", s["text"]],
                                           capture_output=True, text=True).stdout
                        r = json.loads(r or '{"ok": false, "missing": "no answer"}')
                        h = {"how": "converter", "check": r}
                        if not r.get("ok"):
                            conv("--fit"); h["how"] = "whole frame: crop check failed"
                    h["full"] = full
                    how.write_text(json.dumps(h))
            cut.update(v=v, key=key, **json.loads(how.read_text()))
            cuts.append(cut)
            print(k, b["sectionId"], c["kind"], c["shows"][:50], "|", cut["how"], "" if cut["full"] else "| 480p copy", flush=True)
        t = p["_takes"][s["voice"]["pick"]]
        w = out / f"voice_{b['sectionId']}.wav"
        run(FF, "-v", "error", "-y", "-i", t["file"], "-af", f"silenceremove=start_periods=1:start_threshold=-45dB,apad,"
            f"atrim=end={b['secs']:.3f},highpass=f=70,loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000", "-ac", "2", w)
        voices[b["sectionId"]] = w.name

    ups = sound916.place(cuts)                                  # lead-in + sound-ups: some cuts are lengthened
    for c in cuts:
        c["len"], c["vx"] = round(c["secs"] + c["pre"] + c["post"], 2), c["v"]
        if c["pre"] or c["post"]:
            x = f"{c['key']}_{c['pre']:.2f}_{c['post']:.2f}"
            c["vx"] = out / f"vx_{x}_{c['kind']}.mp4"
            if not c["vx"].exists():
                src = out / f"xsrc_{x}.mp4"
                run(FF, "-v", "error", "-y", "-ss", f"{c['start'] - c['pre'] - c['a']:.3f}", "-t", f"{c['len']:.3f}", "-i", c["raw"],
                    "-an", "-c:v", "libx264", "-crf", "14", "-preset", "medium", src)
                run(PY, V + "vconv.py", src, c["vx"], *(["--fit"] if c["how"].startswith("whole") else []), capture_output=True, text=True)
    print(f"PROGRESS {n - 2}/{n}\nSTAGE Making the sound", flush=True)
    fx = sound916.foley(out, [(c["vx"], c["prompt"]) for c in cuts if c["loud"] >= 0])
    for c in cuts:
        c["fx"] = fx.get(c["vx"]) if c["loud"] >= 0 else None
    print(f"PROGRESS {n - 1}/{n}\nSTAGE Mixing and captions", flush=True)
    vs = {b: out / w for b, w in voices.items()}
    ln = sound916.mix(out, cuts, vs)
    (out / "plan.json").write_text(json.dumps({"cuts": [{k: c[k] for k in ("beat", "len", "pre")} for c in cuts], "voices": voices}))
    gfx = gfx916.ass(out, pj)
    print(f"PROGRESS {n}/{n}\nSTAGE Finishing the video", flush=True)
    (out / "v.txt").write_text("".join(f"file '{pathlib.Path(c['vx']).name}'\n" for c in cuts))
    run(FF, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", out / "v.txt", "-i", out / "mix.wav", "-filter_complex",
        f"[0:v]ass={gfx}:fontsdir={gfx916.FONTS}[v];[1:a]{ln},aresample=48000[a]", "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-shortest",
        "-movflags", "+faststart", out / "final_916.mp4")
    keep = ("beat", "shows", "prompt", "secs", "loud", "pre", "post", "how", "full", "check")
    (out / "build.json").write_text(json.dumps({"cuts": [{k: c[k] for k in keep if k in c} for c in cuts],
                                                "soundUps": ups, "foley": sum(bool(c.get("fx")) for c in cuts)}, indent=1))
    print("final", out / "final_916.mp4")

if __name__ == "__main__":
    build(pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]), *sys.argv[3:4])
