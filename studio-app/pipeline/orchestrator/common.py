"""Shared paths, IST clock, logging, env loading and run-state checkpoints for the daily orchestrator."""
import datetime as dt
import json
import os
import pathlib

APP = pathlib.Path(__file__).resolve().parents[2]            # studio-app (lt_remotion, bg_options, DNL Outro.mp4 live here)
PIPE = APP / "pipeline"
HOME = pathlib.Path.home()
STUDIO = HOME / "anchor-studio"
COMFY = STUDIO / "repos" / "ComfyUI-v038"                     # v0.38 install; input/ is a symlink to production's
COMFY_IN = COMFY / "input"
DAILY = STUDIO / "daily"                                      # run/<date>/... state, logs, intermediates
OUTPUT = STUDIO / "output" / "daily"                          # finished videos
TOOLS_PY = os.environ.get("ANCHOR_TOOLS_PY", str(HOME / ".cache" / "anchor-tools" / "bin" / "python"))
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
OFF_SWITCH = STUDIO / "ANCHOR_OFF"

# Daily schedule (IST). Generation window is the user's 18:00-23:00 rule; ANCHOR_HARD_STOP overrides the stop for one
# evening (set with `systemctl --user set-environment`, cleared by a one-off timer the next morning).
SELECT_AT, GPU_AT, RENDER_START = "17:30", os.environ.get("ANCHOR_GPU_AT", "17:55"), os.environ.get("ANCHOR_RENDER_START", "18:00")
HARD_STOP = os.environ.get("ANCHOR_HARD_STOP", "23:00")
REST_BETWEEN_VIDEOS_S = 0                                     # user rule 2026-10-22: no GPU rest between videos (was 10 min)


def now():
    return dt.datetime.now(IST)


def today_at(hhmm, day=None):
    """IST datetime of hh:mm on `day` (today); "24:45" is 00:45 the next day (a run allowed past midnight)."""
    h, m = map(int, hhmm.split(":"))
    d = (day or now().date()) + dt.timedelta(days=h // 24)
    return dt.datetime(d.year, d.month, d.day, h % 24, m, tzinfo=IST)


def load_env():
    """~/.config/anchor-studio/*.env (KEY=VALUE lines, mode 600) -> os.environ. Never logged."""
    for f in sorted((HOME / ".config" / "anchor-studio").glob("*.env")):
        for line in f.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


class Run:
    """One day's run directory + checkpointed state.json (so --resume continues exactly where it stopped)."""

    def __init__(self, date=None, root=None):
        self.date = date or now().strftime("%Y-%m-%d")
        self.dir = pathlib.Path(root or DAILY) / self.date
        self.dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.dir / "state.json"
        self.state = json.loads(self.state_file.read_text()) if self.state_file.exists() else {"steps": {}, "stories": {}}

    def save(self):
        tmp = self.state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, indent=2, default=str))
        tmp.replace(self.state_file)                          # atomic: a crash never leaves half a state file

    def done(self, step):
        return self.state["steps"].get(step) == "done"

    def mark(self, step, status="done"):
        self.state["steps"][step] = status
        self.save()

    def story(self, sid):
        return self.state["stories"].setdefault(sid, {})

    def log(self, msg):
        line = f"[{now():%H:%M:%S} IST] {msg}"
        print(line, flush=True)
        with open(self.dir / "run.log", "a") as f:
            f.write(line + "\n")

    def write(self, name, obj):
        p = self.dir / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=str))
        return p

    def read(self, name):
        return json.loads((self.dir / name).read_text())
