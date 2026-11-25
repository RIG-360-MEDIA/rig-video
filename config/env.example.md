# Secrets and settings on the machines (never in git)

All files are mode 600, owned by the service user. Values are kept by the owner; a backup of the RIG keys lives on the
private `secrets-backup` branch of Yash-2704/rig-platform. Only the variable NAMES are listed here.

## trijya-7

| File | Variables | Used by |
|---|---|---|
| `~/.config/rigvideo/api.env` | `RIGVIDEO_WRITER_KEY`, `RIGVIDEO_DAILY_AUTO` (1 = daily run on), `RIGVIDEO_DAILY_AT` (IST, default 08:00) | rigvideo-api.service |
| `~/.config/anchor-studio/db.env` | `ANALYTICS_DB_URL` (RIG Hetzner DB, read-only user, for the daily DNL picks) | daily selection |
| `~/.config/anchor-studio/footage.env` | `GROQ_API_KEY`, `GROQ_API_KEY_2..7`, `OPENAI_API_KEY` (unused by RIG-Video), `YOUTUBE_API_KEY`, `GOOGLE_CSE_API_KEY`, `GOOGLE_CSE_CX` | footage search backend |
| `~/.config/anchor-studio/llm.env` | `GROQ_API_KEY` (comma list), `RIG_GATEWAY_KEY` | LLM fallback pool |
| `~/.config/anchor-studio/search.env` | `TAVILY_API_KEY`, `SERPAPI_KEY` | story pictures / photo search |
| `~/.config/anchor-studio/youtube.env` | `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN`, `YT_PENDING_PLAYLIST_ID`, `YT_BULLETIN_PLAYLIST_ID` | upload + Post (DNL channel) |
| `~/.config/rigvideo/tunnel.token` | Cloudflare Tunnel token (Rigtvnews tunnel) for the public link | rigvideo-tunnel.service |
| `~/.config/anchor-studio/footage-auth` | the footage backend's login password (one line) | footage backend + worker |
| `~/warp/wgcf-account.toml`, `~/warp/wgcf-profile.conf`, `~/warp/wireproxy.conf` | Cloudflare WARP account + WireGuard key | warp-proxy.service |
| `~/.ssh/to_trijya3` | ssh key to t3 (voice runs, writer switch, deploys) | worker, deploy |
| `~/.ssh/rigvideo_deploy_t8` | ssh key to t8, forced to `~/vision/deploy_recv.sh` | deploy |
| `~/anchor-studio/rigvideo-data/session.key` | signs site sessions (made on first start) | API |
| `~/anchor-studio/rigvideo-data/users.json` | accounts (scrypt hashes) | API |

## trijya-3

| File | Holds |
|---|---|
| `~/rigvideo/llm/api.key` | same value as `RIGVIDEO_WRITER_KEY` on t7 |

## Settings with defaults (set in the unit or api.env only to change them)

`RIGVIDEO_RENDER_WINDOW` (IST, `00:00-07:00`), `RIGVIDEO_AUTO_PUBLISH_MIN` (anchor-only goes public this long after its
render, 60), `RIGVIDEO_AUTO_RESUME` (times a job cut off by a restart starts again by itself, 2),
`RIGVIDEO_NO_SELECTION=1` (test instances: no daily picks), `LLM_PROVIDERS` (in rigvideo-api.service).
