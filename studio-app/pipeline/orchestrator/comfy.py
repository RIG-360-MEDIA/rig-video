"""ComfyUI v0.38 client: start once, submit, wait, kill. Same behaviour as pipeline/tools/run_full.sh, in Python."""
import http.client
import json
import os
import pathlib
import shutil
import subprocess
import time
import urllib.request

from .common import COMFY, COMFY_IN, STUDIO

URL = "http://127.0.0.1:8199"
OUT = COMFY / "output"


def _get(path, timeout=10):
    with urllib.request.urlopen(URL + path, timeout=timeout) as r:
        return json.loads(r.read())


def alive():
    """Up and answering. While a big model loads, ComfyUI can stop answering HTTP for a while; that is not death."""
    try:
        _get("/system_stats", 5)
        return True
    except Exception:  # noqa: BLE001
        return False


def running():
    """The ComfyUI process exists (answering or not)."""
    return subprocess.run(["pgrep", "-f", "[m]ain.py --listen"], capture_output=True).returncode == 0


def start(log=print, timeout_s=600):
    if alive():
        return
    logf = open(STUDIO / "comfy_daily.log", "a")
    subprocess.Popen([str(COMFY / ".venv" / "bin" / "python"), "main.py", "--listen", "0.0.0.0", "--port", "8199",
                      "--disable-comfy-compiler", *os.environ.get("COMFY_ARGS", "").split()], cwd=COMFY, stdout=logf, stderr=subprocess.STDOUT,
                     stdin=subprocess.DEVNULL, start_new_session=True)
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        if alive():
            log(f"ComfyUI up in {time.time() - t0:.0f}s")
            return
        time.sleep(5)
    raise RuntimeError("ComfyUI did not come up")


def kill(log=print):
    """User rule: kill ComfyUI by the '[m]ain.py --listen' pattern after the last video."""
    subprocess.run(["pkill", "-9", "-f", "[m]ain.py --listen"])
    log("ComfyUI killed")


def nodes_present(names):
    info = _get("/object_info", 60)
    return [n for n in names if n not in info]


def _queued(g):
    """prompt_id of a queued/running copy of graph g (a submit that timed out may still have been accepted)."""
    q = _get("/queue", 30)
    key = json.dumps(g, sort_keys=True)
    for item in q.get("queue_running", []) + q.get("queue_pending", []):
        if len(item) > 2 and json.dumps(item[2], sort_keys=True) == key:
            return item[1]
    return None


def submit(job_file, tries=4):
    """Queue a job. A slow or dropped answer is retried, never a crash (24 Oct: one 60 s timeout right after a chain
    ended killed the whole evening run); a copy ComfyUI already accepted is reused, never queued twice."""
    g = json.load(open(job_file))
    g = g.get("prompt", g)
    for k in range(tries):
        try:
            req = urllib.request.Request(URL + "/prompt", json.dumps({"prompt": g}).encode(), {"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as r:
                res = json.loads(r.read())
            break
        except (OSError, http.client.HTTPException) as ex:          # timeout / reset / refused
            if k == tries - 1:
                raise
            time.sleep(20 * (k + 1))
            try:
                pid = _queued(g)
            except (OSError, http.client.HTTPException, ValueError):
                pid = None
            if pid:
                return pid
    if res.get("node_errors"):
        raise RuntimeError(f"rejected: {json.dumps(res['node_errors'])[:500]}")
    return res["prompt_id"]


def wait(prompt_id, deadline_ts, log=print, label=""):
    """Block until the prompt finishes. Returns (ok, seconds, error)."""
    t0 = time.time()
    while True:
        if time.time() > deadline_ts:
            interrupt()
            return False, time.time() - t0, "hard deadline reached"
        if not alive() and not running():                         # busy loading weights is not dead (13 Nov: 26 GB encoder)
            return False, time.time() - t0, "ComfyUI died"
        try:
            h = _get(f"/history/{prompt_id}").get(prompt_id)
        except Exception:  # noqa: BLE001
            h = None
        if h and h.get("status", {}).get("completed"):
            return True, time.time() - t0, None
        if h and h.get("status", {}).get("status_str") == "error":
            msgs = [m[1].get("exception_message", "") for m in h["status"].get("messages", []) if m[0] == "execution_error"]
            return False, time.time() - t0, (msgs[0] if msgs else "execution error")[:400]
        time.sleep(15)


def interrupt():
    try:
        urllib.request.urlopen(urllib.request.Request(URL + "/interrupt", b"", {"Content-Type": "application/json"}), timeout=10)
    except Exception:  # noqa: BLE001
        pass


def newest(pattern):
    c = sorted(OUT.glob(pattern), key=os.path.getmtime)
    return c[-1] if c else None


def stage_seed(run):
    """Copy the finished seed into input/ under the name the chain job expects."""
    seed = newest(f"video/{run}_seed_*.mp4")
    if not seed:
        raise FileNotFoundError(f"no seed output for {run}")
    dst = COMFY_IN / f"{run}_seed_00001_.mp4"
    shutil.copy2(seed, dst)
    return pathlib.Path(seed)


def chain_final(run):
    return newest(f"h3_chains/{run}/final/*.mp4")
