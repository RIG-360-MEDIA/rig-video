#!/usr/bin/env bash
# Install this checkout of RIG-Video on its machines. Runs on trijya-7 (the GitHub Actions runner runs it for every
# published release; by hand: deploy/deploy.sh <version>). Order: t3 + t8 files, t7 files, enable the boot services,
# restart what changed, then check the API answers with the new version. Exit 1 = not healthy (the release workflow
# then re-installs the last good release).
#
#   repo                    -> machine
#   server/                 -> t7 ~/anchor-studio/rigvideo/server        API + job steps (rigvideo-api.service, :8770)
#   web/ (built)            -> t7 ~/anchor-studio/rigvideo/dist          the site
#   studio-app/             -> t7 ~/anchor-studio/studio-app             pipeline code, anchor registry, lower-thirds package
#   vertical/               -> t7 ~/anchor-studio/vertical               9:16 final video tools
#   footage/                -> t7 ~/anchor-studio/repos/social_verifier  footage search backend (started on demand, :8787)
#   hosts/t7/               -> t7 ~/vo_check, ~/.config/systemd/user     clip-checker model (vo-vision, :11620), units
#   hosts/t3/ + voice_lab   -> t3 ~/rigvideo/llm, ~/anchor-studio/voice_lab   script model switch, voice takes
#   hosts/t8/               -> t8 ~/vision, ~/.config/systemd/user       vision model (vision-llm, :11610)
set -euo pipefail
SRC=$(cd "$(dirname "$0")/.." && pwd)
VER=${1:-$(git -C "$SRC" describe --tags --always --dirty)}
A=$HOME/anchor-studio
STATE=$HOME/.local/state/rig-video
T3=trijya-3@100.99.155.88; T3KEY=$HOME/.ssh/to_trijya3
T8=trijya-8@100.95.0.11;   T8KEY=$HOME/.ssh/rigvideo_deploy_t8        # forced to t8 ~/vision/deploy_recv.sh
say() { echo "[$(TZ=Asia/Kolkata date +%H:%M:%S) IST] $*"; }
put() { rsync -a --itemize-changes --exclude __pycache__ --exclude '*.pyc' "$@" | grep -v '^\.' || true; }

[ -d "$SRC/web/dist" ] || { echo "web/dist missing: run deploy/check.sh first (it builds the site)" >&2; exit 2; }
[ -s "$HOME/.config/anchor-studio/footage-auth" ] || { echo "~/.config/anchor-studio/footage-auth missing (see docs/HANDOFF.md, Secrets)" >&2; exit 2; }
mkdir -p "$STATE/backups"

say "release $VER: backup of the current t7 code"
tar -czf "$STATE/backups/$(date -u +%Y%m%dT%H%M%SZ)-before-$VER.tgz" -C "$HOME" --ignore-failed-read \
  anchor-studio/rigvideo/server anchor-studio/rigvideo/dist anchor-studio/rigvideo/VERSION anchor-studio/studio-app/pipeline \
  anchor-studio/studio-app/anchor_registry/registry.json anchor-studio/studio-app/lt_remotion/src anchor-studio/vertical/*.py anchor-studio/repos/social_verifier/backend/app \
  anchor-studio/repos/social_verifier/start_backend.sh anchor-studio/repos/social_verifier/ytdlp_node.sh vo_check/vo_vision_serve.sh \
  .config/systemd/user/rigvideo-api.service .config/systemd/user/vo-vision.service .config/systemd/user/warp-proxy.service .config/systemd/user/rigvideo-tunnel.service 2>/dev/null
ls -t "$STATE/backups"/*.tgz | tail -n +21 | xargs -r rm --                 # keep the last 20

say "t3: script model switch + voice tools"
SSH3="ssh -o BatchMode=yes -o ConnectTimeout=20 -i $T3KEY"
put -e "$SSH3" "$SRC/hosts/t3/gpu.sh" "$T3:rigvideo/llm/gpu.sh"
put -e "$SSH3" "$SRC/hosts/t3/systemd/" "$T3:.config/systemd/user/"
put -e "$SSH3" "$SRC/studio-app/pipeline/tools/voice_lab/chatterbox_takes.py" "$T3:anchor-studio/voice_lab/"
$SSH3 "$T3" 'systemctl --user daemon-reload'

say "t8: vision model + clip checker"
tar -czf - -C "$SRC/hosts/t8" vision systemd | ssh -o BatchMode=yes -o ConnectTimeout=20 -i "$T8KEY" "$T8" deploy

say "t7: API, site, pipeline, 9:16 tools, footage backend"
put "$SRC/server/" "$A/rigvideo/server/"
put --delete "$SRC/web/dist/" "$A/rigvideo/dist/"
put "$SRC/studio-app/" "$A/studio-app/"                                  # adds/updates only: media and node_modules stay
put "$SRC/vertical/" "$A/vertical/"
FOOT=$(put "$SRC/footage/backend/" "$A/repos/social_verifier/backend/"; put "$SRC/footage/ytdlp_node.sh" "$A/repos/social_verifier/")
echo "$FOOT"
VIS=$(put "$SRC/hosts/t7/vo_vision_serve.sh" "$HOME/vo_check/")
put "$SRC/hosts/t7/systemd/" "$HOME/.config/systemd/user/"
echo "$VER" > "$A/rigvideo/VERSION"

say "t7: boot services on, restart what changed"
systemctl --user daemon-reload
systemctl --user enable warp-proxy vo-vision rigvideo-api actions-runner 2>/dev/null || systemctl --user enable warp-proxy vo-vision rigvideo-api
if [ -s "$HOME/.config/rigvideo/tunnel.token" ]; then                    # public link (rigtvnews.rig360media.com)
  systemctl --user enable rigvideo-tunnel; systemctl --user is-active -q rigvideo-tunnel || systemctl --user start rigvideo-tunnel
fi
systemctl --user is-active -q warp-proxy || systemctl --user start warp-proxy
[ -n "$VIS" ] && systemctl --user restart vo-vision || systemctl --user is-active -q vo-vision || systemctl --user start vo-vision
if [ -n "$FOOT" ] && curl -sf -m 3 localhost:8787/api/health >/dev/null; then    # running on old code: start it again
  bash "$A/studio-app/pipeline/tools/footage/start_backend.sh" || say "footage backend restart failed (the worker starts it when needed)"
fi
systemctl --user restart rigvideo-api                                       # KillMode=process: running jobs keep going

say "health"
for _ in $(seq 30); do
  got=$(curl -sf -m 3 http://100.72.225.89:8770/api/health 2>/dev/null || true)
  if echo "$got" | grep -q "\"version\":\"$VER\"" && echo "$got" | grep -q '"monitor":true'; then
    echo "$VER" > "$STATE/last-good"
    say "release $VER is live"
    python3 "$SRC/ops/doctor.py" || say "doctor found problems outside this release (see above)"
    exit 0
  fi
  sleep 2
done
say "API did not come up with $VER: $(journalctl --user -u rigvideo-api -n 15 --no-pager 2>&1 | tail -15)"
exit 1
