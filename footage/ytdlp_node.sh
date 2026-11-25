#!/bin/bash
# The footage repo's yt-dlp. Node 22: yt-dlp 2026.10+ marks node 20 unsupported (JS challenge solver off).
# 2026-11-25: YouTube answers LOGIN_REQUIRED to every client from the office IP (shared by t3/t7/t8), so downloads go out
# through Cloudflare WARP (warp-proxy.service, userspace wireproxy, 127.0.0.1:18091); direct if that proxy is down.
P=()
# only when the proxy really reaches YouTube (a dead tunnel must never stall a download)
[ "$(curl -s -m4 -o /dev/null -w "%{http_code}" -x socks5h://127.0.0.1:18091 https://www.youtube.com/generate_204)" = 204 ] && P=(--proxy socks5h://127.0.0.1:18091)
exec ~/anchor-studio/repos/social_verifier/.venv/bin/yt-dlp --js-runtimes node:$HOME/.nvm/versions/node/v22.23.5/bin/node "${P[@]}" "$@"
