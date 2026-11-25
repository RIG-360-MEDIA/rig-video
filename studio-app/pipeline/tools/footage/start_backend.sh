#!/usr/bin/env bash
# Start the footage repo's backend (social_verifier "Live Cutter") on trijya-7, localhost:8787, for our footage step.
# - Groq keys come from ~/.config/anchor-studio/llm.env into this process's environment only (never written to disk).
# - A dynamically linked ffmpeg (BtbN gpl-shared) goes first on PATH: the static ~/.local/bin/ffmpeg segfaults on
#   network input, which broke clip downloads.
# - Branch dnl-trijya-whisper adds a speech-to-text fallback (YouTube refuses caption downloads to this machine, 429)
#   and a local-LLM option.
# - Keys: ~/.config/anchor-studio/footage.env (mode 600; the footage org's Groq, YouTube Data API and Google CSE keys)
#   when present, else our own llm.env Groq keys.
# - LLM: FOOTAGE_LLM=local (default) = the clip checker's Qwen3-VL 8B server on trijya-8 (vision_serve.sh), same speed
#   as Groq (~2 s a call) and no daily cap; Groq only when that server can't be reached. FOOTAGE_LLM=groq = Groq only.
set -euo pipefail
R=$HOME/anchor-studio/repos/social_verifier
DATA=${FOOTAGE_DATA_DIR:-$HOME/anchor-studio/footage/data}
mkdir -p "$DATA"
pkill -f "[u]vicorn app.main:app --host 127.0.0.1 --port 8787" && sleep 3 || true
eval "$(python3 - <<'PY'
import pathlib, shlex
e = dict(l.split("=", 1) for l in pathlib.Path.home().joinpath(".config/anchor-studio/llm.env").read_text().splitlines()
         if "=" in l and not l.startswith("#"))
ks = [k.strip() for k in e["GROQ_API_KEY"].strip().strip('"').split(",") if k.strip()]
for i, k in enumerate(ks[:7]):
    print("export " + ("GROQ_API_KEY" if i == 0 else "GROQ_API_KEY_%d" % (i + 1)) + "=" + shlex.quote(k))
PY
)"
# PO-token server (bgutil, localhost:4416): caption URLs then carry a real PO token, as YouTube's own web player sends.
NODE_BIN=$HOME/.nvm/versions/node/v20.20.2/bin
POT=$HOME/anchor-studio/repos/bgutil-ytdlp-pot-provider/server
if ! curl -sf -m 3 localhost:4416/ping >/dev/null; then
  (cd "$POT" && setsid nohup "$NODE_BIN/node" build/main.js --port 4416 --host 127.0.0.1 > "$DATA/pot_server.log" 2>&1 < /dev/null &)
fi
# CUDA libraries (pip wheels in the venv) for speech-to-text on the GPU
NV=$R/.venv/lib/python3.12/site-packages/nvidia
export LD_LIBRARY_PATH=$NV/cublas/lib:$NV/cudnn/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}
export PATH=$HOME/anchor-studio/repos/ffmpeg-shared/current/bin:$PATH DATA_DIR=$DATA YTDLP_BIN=$R/ytdlp_node.sh
ORG=$HOME/.config/anchor-studio/footage.env
if [ -f "$ORG" ]; then
  set -a; . "$ORG"; set +a
  unset OPENAI_API_KEY                                   # verifier-only; the footage step never needs it
fi
if [ "${FOOTAGE_LLM:-local}" = local ]; then
  export LLM_BASE_URL=${FOOTAGE_LLM_URL:-http://100.95.0.11:11610/v1} LLM_MODEL=${FOOTAGE_LLM_MODEL:-qwen3-vl-q4}
fi
export FOOTAGE_VIDEOS_PER_KEYWORD=${FOOTAGE_VIDEOS_PER_KEYWORD:-4} FOOTAGE_KEYWORDS_PER_WAVE=${FOOTAGE_KEYWORDS_PER_WAVE:-3}
cd $R/backend
nohup $R/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8787 > "$DATA/backend.log" 2>&1 &
for _ in $(seq 30); do curl -sf localhost:8787/api/health >/dev/null && { echo "footage backend up (data $DATA)"; exit 0; }; sleep 1; done
echo "footage backend did not start; see $DATA/backend.log" >&2; exit 1
