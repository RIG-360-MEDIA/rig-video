# Footage backend (vendored)

Copy of the footage search backend ("Live Cutter") from https://github.com/Daksh288948921904/social_verifier,
branch `dnl-trijya-whisper` at 5504871 (our commits on top of upstream: whisper fallback, local LLM first,
`limit:N` / `after:` query options, bare-list script parse). Only `backend/` is kept; the upstream web frontend,
Docker and Render files are not used by RIG-Video and were left out.

Changed here: `backend/app/core/auth.py` reads its password from `$FOOTAGE_AUTH_PASSWORD` or
`~/.config/anchor-studio/footage-auth` instead of the code.

Runs on t7 at `~/anchor-studio/repos/social_verifier` (localhost:8787). The RIG-Video worker starts it on demand with
`studio-app/pipeline/tools/footage/start_backend.sh`. `ytdlp_node.sh` (here) is the yt-dlp wrapper every RIG-Video
download uses (Node 22 + Cloudflare WARP).
