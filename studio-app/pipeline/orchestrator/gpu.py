"""GPU window (user rule 2026-10-03): usually free; if not, pause whatever is running and restart it after our run.

Known tenants on trijya-7: ollama-robin.service (ROBIN production, ~22 GB), pt-worker-box-gpu.service (Pranav-Tools GPU
jobs) and the transient collect-vision-llm.service (~12.4 GB; relaunched with its systemd-run line). All are stopped/started
through systemd (collect-ollama too: killing only its llama-server runners lets `ollama serve` respawn them). Any other GPU-holding process is recorded (cmdline/cwd/env) and SIGTERM'd, and
relaunched identically on restore. The LaBSE embed server (~1-2 GB, kept alive by its own cron watchdog) is NOT
paused: renders on 2026-10-02 ran fine beside it and its watchdog would respawn it anyway.

Restore never depends on the orchestrator surviving: pause() also schedules a one-shot systemd timer for the hard
stop + 5 min that runs `gpu.py restore`; the orchestrator calls restore early when it finishes.
"""
import json
import os
import pathlib
import signal
import subprocess
import sys
import time

SMI = "/usr/lib/wsl/lib/nvidia-smi" if os.path.exists("/usr/lib/wsl/lib/nvidia-smi") else "nvidia-smi"
SERVICES = ["ollama-robin.service", "pt-worker-box-gpu.service", "collect-ollama.service", "vo-vision.service"]   # vo-vision: the VO clip checker's model (12.5 GB awake)   # systemd --user units we pause (as t8kf_run.sh does)
# Transient unit: stopping it deletes it, so restore relaunches it exactly as baseline/HANDOFF.md section 1 documents.
TRANSIENT = {"collect-vision-llm.service": ["systemd-run", "--user", "--unit=collect-vision-llm", "--slice=app.slice", "/usr/bin/bash",
                                           "-c", "exec bash ~/collect-vision/serve_vision.sh >> ~/collect-vision/vision-llm.log 2>&1"]}
LEAVE_ALONE = ("embed_server.py", "embed_launch.sh")               # small, proven compatible, self-respawning
FREE_MIB, FREE_UTIL = 4000, 10


def utc_cal(ts):
    """systemd OnCalendar string (UTC) for a unix timestamp."""
    return time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(ts))


def usage():
    out = subprocess.check_output([SMI, "--query-gpu=memory.used,utilization.gpu", "--format=csv,noheader,nounits"], text=True)
    mem, util = [int(x) for x in out.strip().splitlines()[0].split(",")]
    return mem, util


def is_free():
    mem, util = usage()
    return mem < FREE_MIB and util < FREE_UTIL


def _gpu_pids():
    out = subprocess.run([SMI, "--query-compute-apps=pid", "--format=csv,noheader"], capture_output=True, text=True).stdout
    return [int(x) for x in out.split() if x.strip().isdigit() and os.path.exists(f"/proc/{x.strip()}")]


def _proc(pid):
    p = pathlib.Path(f"/proc/{pid}")
    env = dict(kv.split("=", 1) for kv in p.joinpath("environ").read_bytes().decode(errors="replace").split("\0") if "=" in kv)
    return {"pid": pid, "cmdline": p.joinpath("cmdline").read_bytes().decode(errors="replace").split("\0")[:-1],
            "cwd": os.readlink(p / "cwd"), "env": env}


def _unit_active(u):
    return subprocess.run(["systemctl", "--user", "is-active", "--quiet", u]).returncode == 0


def _unit_of(pid):
    cg = pathlib.Path(f"/proc/{pid}/cgroup").read_text()
    return next((u for u in SERVICES + list(TRANSIENT) if u in cg), None)


def tenants_active():
    """Known GPU tenants that are up. pt-worker can start a GPU job at any moment, so an idle-looking GPU is not enough."""
    return [u for u in SERVICES + list(TRANSIENT) if _unit_active(u)]


def pause(record_file, restore_at_utc, log=print):
    """Free the GPU. Writes what was stopped to record_file and schedules the independent restore."""
    rf = pathlib.Path(record_file)
    rec = json.loads(rf.read_text()) if rf.exists() else {"services": [], "procs": []}   # never drop an unrestored record
    save = lambda: rf.write_text(json.dumps(rec, indent=2))
    save()
    # the independent restore is scheduled BEFORE anything stops, and the record is written after every stop: if a later
    # stop fails (or this process dies), whatever was already stopped still comes back
    subprocess.run(["systemd-run", "--user", f"--unit=anchor-gpu-restore-{int(time.time())}",
                    f"--on-calendar={restore_at_utc}", "--timer-property=AccuracySec=1s",
                    sys.executable, os.path.abspath(__file__), "restore", str(record_file)], check=True)
    log(f"GPU: restore scheduled at {restore_at_utc} (independent systemd timer)")
    for u in SERVICES + list(TRANSIENT):
        if _unit_active(u):
            subprocess.run(["systemctl", "--user", "stop", u], check=True)
            rec["services"].append(u)
            save()
            log(f"GPU: stopped {u}")
    time.sleep(5)
    mine = []                                                       # only pids found NOW: an old record's pids (from before a
    for pid in _gpu_pids():                                         # VM restart) may belong to an unrelated process today
        try:
            info = _proc(pid)
        except (FileNotFoundError, PermissionError):
            continue
        cmd = " ".join(info["cmdline"])
        if _unit_of(pid) or any(x in cmd for x in LEAVE_ALONE) or "main.py --listen" in cmd:
            continue
        if not any(p["cmdline"] == info["cmdline"] for p in rec["procs"]):   # one entry per command: restore runs it once
            rec["procs"].append(info)
        mine.append(pid)
        save()
        os.kill(pid, signal.SIGTERM)
        log(f"GPU: SIGTERM pid {pid}: {cmd[:120]}")
    for _ in range(30):
        if all(not os.path.exists(f"/proc/{pid}") for pid in mine):
            break
        time.sleep(1)
    for pid in mine:
        if os.path.exists(f"/proc/{pid}"):
            os.kill(pid, signal.SIGKILL)
    save()
    return rec


def restore(record_file, log=print):
    """Bring back exactly what pause() stopped. Idempotent."""
    rf = pathlib.Path(record_file)
    if not rf.exists():
        return
    rec = json.loads(rf.read_text())
    for u in rec["services"]:
        if not _unit_active(u):
            cmd = TRANSIENT.get(u, ["systemctl", "--user", "start", u])
            subprocess.run([os.path.expanduser(c) if c.startswith("~") else c for c in cmd])
            log(f"GPU: restarted {u}")
    running = set()                                                 # every live command line (not only GPU ones)
    for d in pathlib.Path("/proc").glob("[0-9]*"):
        try:
            running.add(tuple(d.joinpath("cmdline").read_bytes().decode(errors="replace").split("\0")[:-1]))
        except OSError:
            pass
    for p in rec["procs"]:
        if tuple(p["cmdline"]) in running:                          # already back (e.g. restored once before): never twice
            continue
        subprocess.Popen(p["cmdline"], cwd=p["cwd"], env=p["env"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
        log(f"GPU: relaunched {' '.join(p['cmdline'])[:120]}")
    rf.rename(rf.with_suffix(".restored.json"))


def wait_free(deadline_ts, log=print):
    while time.time() < deadline_ts:
        if is_free():
            return True
        time.sleep(15)
    mem, util = usage()
    log(f"GPU still busy at deadline: {mem} MiB, {util}%")
    return False


if __name__ == "__main__":
    if sys.argv[1:2] == ["restore"]:
        restore(sys.argv[2])
    elif sys.argv[1:2] == ["status"]:
        print(usage(), "free" if is_free() else "busy", "tenants up:", tenants_active())
