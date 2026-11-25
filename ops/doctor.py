#!/usr/bin/env python3
"""Is RIG-Video ready to run by itself? Run on trijya-7: python3 ops/doctor.py. Exit 1 when something the daily run
needs is down. Also run by deploy.sh after each release and by the scheduled 'doctor' workflow (07:30 and 23:30 IST,
after t7's daily 07:00 restart and before the 00:00 render window)."""
import json, os, pathlib, shutil, subprocess, sys, urllib.request

HOME = pathlib.Path.home()
DATA = pathlib.Path(os.environ.get("STUDIO_DATA", HOME / "anchor-studio" / "rigvideo-data"))
bad = []


def check(name, ok, detail="", critical=True):
    print(f"{'OK  ' if ok else ('FAIL' if critical else 'WARN')}  {name}{'  ' + detail if detail else ''}")
    if not ok and critical:
        bad.append(name)


def http(url, timeout=6, proxy=None):
    try:
        h = [urllib.request.ProxyHandler({"https": proxy, "http": proxy})] if proxy else []
        with urllib.request.build_opener(*h).open(url, timeout=timeout) as r:
            return r.status, r.read(2000).decode("utf-8", "replace")
    except Exception as e:
        return getattr(e, "code", 0), str(e)


def sh(*a, timeout=25):
    try:
        return subprocess.run(a, capture_output=True, text=True, timeout=timeout)
    except Exception as e:
        return subprocess.CompletedProcess(a, 1, "", str(e))


for u in ("rigvideo-api", "warp-proxy", "vo-vision", "actions-runner"):
    en = sh("systemctl", "--user", "is-enabled", u).stdout.strip()
    ac = sh("systemctl", "--user", "is-active", u).stdout.strip()
    check(f"t7 {u}", en == "enabled" and ac == "active", f"{en}/{ac}")

st, body = http("http://100.72.225.89:8770/api/health")
h = json.loads(body) if st == 200 else {}
check("API answers", st == 200, h.get("version", body[:120]))
check("API job loop alive", bool(h.get("monitor")))

env = {}
for line in (HOME / ".config/rigvideo/api.env").read_text().splitlines() if (HOME / ".config/rigvideo/api.env").exists() else []:
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
check("daily auto-start on", env.get("RIGVIDEO_DAILY_AUTO") == "1", f"RIGVIDEO_DAILY_AUTO={env.get('RIGVIDEO_DAILY_AUTO')} at {env.get('RIGVIDEO_DAILY_AT', '08:00')} IST")

# YouTube refuses the office IP: downloads go through Cloudflare WARP (warp-proxy.service, SOCKS5 :18091)
r = sh("curl", "-s", "-m", "8", "-o", "/dev/null", "-w", "%{http_code}", "-x", "socks5h://127.0.0.1:18091", "https://www.youtube.com/generate_204")
check("YouTube via WARP", r.stdout == "204", r.stdout or r.stderr[:80])

st, _ = http("http://100.72.225.89:11620/health")
check("t7 clip-checker model :11620", st in (200, 503), f"HTTP {st} (503 = asleep/loading, wakes on use)")
st, _ = http("http://100.95.0.11:11610/health")
check("t8 vision model :11610", st in (200, 503), f"HTTP {st}")
r = sh("ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-i", str(HOME / ".ssh/to_trijya3"), "trijya-3@100.99.155.88",
       "test -x rigvideo/llm/gpu.sh && test -x anchor-studio/repos/chatterbox/.venv/bin/python && echo ready")
check("t3 writer + voice box reachable", r.stdout.strip() == "ready", (r.stderr or r.stdout).strip()[:100])

free = shutil.disk_usage(DATA).free / 1e9
check("t7 data disk free", free > 40, f"{free:.0f} GB")
r = sh("nvidia-smi", "--query-gpu=temperature.gpu,memory.used", "--format=csv,noheader")
check("t7 GPU", r.returncode == 0, r.stdout.strip(), critical=False)

print("\nREADY" if not bad else f"\nNOT READY: {', '.join(bad)}")
sys.exit(1 if bad else 0)
