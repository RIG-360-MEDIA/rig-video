"""Shared paths (studio-app, ComfyUI install, tools python), the IST clock, logging and env loading
(~/.config/anchor-studio/*.env) for the pipeline code."""
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
TOOLS_PY = os.environ.get("ANCHOR_TOOLS_PY", str(HOME / ".cache" / "anchor-tools" / "bin" / "python"))
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))



def now():
    return dt.datetime.now(IST)


def load_env():
    """~/.config/anchor-studio/*.env (KEY=VALUE lines, mode 600) -> os.environ. Never logged."""
    for f in sorted((HOME / ".config" / "anchor-studio").glob("*.env")):
        for line in f.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


