"""Shared steps for the new-anchor GPU runs: log, free the GPU (pause tenants with the user's go; restore later), render H3 jobs."""
import json, os, pathlib, shutil, subprocess, sys, time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from orchestrator import comfy, gpu                                # noqa: E402
from orchestrator.common import COMFY_IN, STUDIO, now   # noqa: E402

HOLD = STUDIO / "NEW_ANCHORS_HOLD"
FFMPEG = str(pathlib.Path.home() / ".local" / "bin" / "ffmpeg")


def log(msg):
    print(f"[{now():%Y-%m-%d %H:%M} IST] {msg}", flush=True)


def run(cmd, **kw):
    log("RUN " + " ".join(map(str, cmd))[:200])
    subprocess.run(list(map(str, cmd)), check=True, **kw)


def ensure_gpu(what, paused):
    """Make the GPU free: pause the known tenants if anything holds it (user go 2026-10-15), then wait until it is free."""
    if HOLD.exists():
        log("NEW_ANCHORS_HOLD present - stopping"); sys.exit(0)
    if subprocess.run(["systemctl", "--user", "is-active", "--quiet", "anchor-daily.service"]).returncode == 0:
        log("the daily run is active - not touching the GPU"); sys.exit(1)
    # a ComfyUI killed a moment ago still holds VRAM for a few seconds: give it a minute before pausing anything
    if not shutil.which("systemd-run") or not os.path.isdir("/run/systemd/system"):   # cloud container box (some images ship
                                                                    # systemd-run without systemd): no tenants of others to pause;
        if not gpu.wait_free(time.time() + 900, log):               # our own footage/voice jobs finish and free the card
            raise SystemExit("GPU did not become free within 15 min")
        mem, util = gpu.usage(); log(f"GPU free ({mem} MiB, {util}%)")
        return
    if gpu.tenants_active() or not gpu.wait_free(time.time() + 60, log):
        mem, util = gpu.usage()
        log(f"GPU held ({mem} MiB, {util}%) before {what}: pausing tenants, backup restore timer in 5 h")
        gpu.pause(paused, gpu.utc_cal(time.time() + 5 * 3600), log=log)
    if not gpu.wait_free(time.time() + 900, log):
        raise SystemExit("GPU did not become free within 15 min of pausing the tenants")
    mem, util = gpu.usage(); log(f"GPU free ({mem} MiB, {util}%)")


