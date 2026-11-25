#!/usr/bin/env bash
# t8 end of a RIG-Video deploy. The deploy key from t7 (~/.ssh/rigvideo_deploy_t8) is forced to this script in
# ~/.ssh/authorized_keys:  command="/home/trijya-8/vision/deploy_recv.sh",restrict ssh-ed25519 ... rigvideo-deploy@t7
# stdin: a tar of the repo's hosts/t8 (vision/, systemd/). Installs them, keeps vision-llm enabled for boot and restarts
# it only when its start script changed. Nothing else on t8 is touched.
set -euo pipefail
[ "${SSH_ORIGINAL_COMMAND:-deploy}" = deploy ] || { echo "only: deploy" >&2; exit 2; }
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
tar -xzf - -C "$T"
ch=$(rsync -a --itemize-changes "$T/vision/" "$HOME/vision/" | grep -v '^\.' || true)
rsync -a "$T/systemd/" "$HOME/.config/systemd/user/"
echo "$ch"
systemctl --user daemon-reload
systemctl --user enable -q vision-llm
if echo "$ch" | grep -q vision_serve.sh || ! systemctl --user is-active -q vision-llm; then
  systemctl --user restart vision-llm
fi
echo "t8 ok"
