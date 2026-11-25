import os
import pathlib
import secrets

# One account (the RIG-Video worker logs in with it too). The password lives outside git:
# $FOOTAGE_AUTH_PASSWORD, else ~/.config/anchor-studio/footage-auth (mode 600). Empty = every login fails.
AUTH_USERNAME = os.environ.get("FOOTAGE_AUTH_USERNAME", "rig360media")
_file = pathlib.Path.home() / ".config" / "anchor-studio" / "footage-auth"
AUTH_PASSWORD = os.environ.get("FOOTAGE_AUTH_PASSWORD") or (_file.read_text().strip() if _file.exists() else "")

# There's exactly one hardcoded account, so a single shared session token
# (rather than a per-user token store) is enough. Regenerated on every
# process start, which just means existing browser sessions need to log in
# again after a backend restart.
SESSION_TOKEN = secrets.token_hex(24)
