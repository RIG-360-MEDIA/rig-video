"""The one treatment assembly applies to each cut moment, matching the real pipeline
(pipeline/tools/footage/clean_shots.py + assembly): a 10 % centre crop that removes corner logos,
or, for vertical phone video, the clip full-height over a blurred, darkened copy of itself.
Presenter and burned-in-text shots are not treated; the shot cleaner drops them (shown as warnings).
usage: python3 seed/treatments.py   (from web/)"""
import json, pathlib, subprocess

OUT = pathlib.Path(__file__).resolve().parent.parent / "public" / "seed"
VF = {
    "crop": "crop=iw*0.9:ih*0.9,scale=640:360",
    "blur_fill": "split[a][b];[a]scale=640:360:force_original_aspect_ratio=increase,crop=640:360,boxblur=20:2,eq=brightness=-0.12[bg];"
                 "[b]crop=ih*9/16:ih,scale=-2:360[fg];[bg][fg]overlay=(W-w)/2:0",
}


# Pillarboxed phone video among the seed clips, judged by eye from frames at 1 s and 9 s (2026-11-10).
# The pipeline decides this per shot with its SigLIP labeller + side-bar check on trijya; simple pixel tests
# misfire on plain sky and on blurry smoke, so the seed records the human call.
VERTICAL = {"d616_a1_a1_3", "mos_a3_a3_2"}


def treat_moment(m):
    if not m.get("clip"):
        m.pop("treat", None); return
    src = OUT / m["clip"].removeprefix("/seed/")
    flags = set(m.get("flags", [])) - {"vertical"}
    if src.stem in VERTICAL:
        flags.add("vertical")
    m["flags"] = sorted(flags)
    kind = "blur_fill" if "vertical" in flags else "crop"
    dst = OUT / "media" / "treated" / f"{src.stem}_{kind}.mp4"
    if not dst.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-vf", VF[kind], "-c:v", "libx264", "-preset", "veryfast",
                        "-crf", "26", "-an", "-movflags", "+faststart", str(dst)], check=True)
    m["treat"] = {"kind": kind, "preview": "/seed/" + str(dst.relative_to(OUT))}


def apply(project):
    for v in project.get("visuals", {}).values():
        for f in v.get("found", []):
            f.pop("treatment", None)
            for m in f["moments"]:
                treat_moment(m)
            f["flags"] = sorted({x for m in f["moments"] for x in m.get("flags", [])})
    return project


if __name__ == "__main__":
    for f in sorted((OUT / "projects").glob("*.json")):
        f.write_text(json.dumps(apply(json.loads(f.read_text())), ensure_ascii=False, indent=1))
        print("treated", f.name)
