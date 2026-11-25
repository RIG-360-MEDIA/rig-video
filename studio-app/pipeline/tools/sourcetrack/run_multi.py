"""Render several independent anchor appearances in ONE ComfyUI session (no restart / model reload between them), one
after another: each appearance's seed job, then its chain job when it has more than one shot. Uses the deployed app's
comfy/gpu helpers read-only; refuses to run while the daily service is active; kills ComfyUI and restores tenants at the end.
usage (tools venv on trijya-7): run_multi.py <base_dir> <id>[:seed|:chain|:both] ...
  <base_dir>/<id>/ holds <run>_seed.json, <run>_chain.json, master_seed.wav, master_chain.wav, shots.json, run.txt (= <run>)
"""
import json, pathlib, shutil, sys, time
APP = pathlib.Path(__file__).resolve().parents[2]   # this pipeline folder (studio-app/pipeline)
sys.path.insert(0, str(APP)); sys.path.insert(0, str(APP / "tools" / "new_anchors"))
from runlib import COMFY_IN, ensure_gpu, log                       # noqa: E402
from orchestrator import comfy, gpu                                # noqa: E402

base = pathlib.Path(sys.argv[1])
todo = [(a.split(":")[0], a.split(":")[1] if ":" in a else "both") for a in sys.argv[2:]]
PAUSED, times = base / "paused.json", {}


def job(d, run, kind, out_run, minutes):
    t0 = time.time()
    ok, secs, err = comfy.wait(comfy.submit(d / f"{run}_{kind}.json"), time.time() + minutes * 60, log, f"{d.name} {kind}")
    times[f"{d.name}_{kind}"] = round(secs / 60, 2)
    log(f"{d.name} {kind}: {'done' if ok else 'FAILED ' + str(err)} in {secs / 60:.1f} min")
    if not ok:
        raise SystemExit(f"{d.name} {kind} failed: {err}")
    final = comfy.newest(f"h3_chains/{out_run}/final/*.mp4")
    shutil.copy2(final, d / f"{out_run}.mp4")
    return final


try:
    ensure_gpu(base.name, PAUSED)
    comfy.start(log)
    for app, stage in todo:
        d = base / app; run = (d / "run.txt").read_text().strip()
        shots = len(json.load(open(d / "shots.json"))["shots"])
        shutil.copy2(d / "master_seed.wav", COMFY_IN / f"{run}_master_seed.wav")
        shutil.copy2(d / "master_chain.wav", COMFY_IN / f"{run}_master_chain.wav")
        if stage in ("seed", "both"):
            shutil.copy2(job(d, run, "seed", f"{run}_seed", 45), COMFY_IN / f"{run}_seed.mp4")
        if stage in ("chain", "both") and shots > 1:
            job(d, run, "chain", run, 60 * shots)
    log(f"TIMES {json.dumps(times)}")
    log("ALL DONE")
finally:
    json.dump(times, open(base / "times.json", "w"), indent=1)
    comfy.kill(log)
    gpu.restore(PAUSED, log)
    log("tenants restored (if any were paused)")
