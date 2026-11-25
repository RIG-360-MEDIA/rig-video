#!/bin/bash
# Voice box (t3): Chatterbox + weights, voice_lab tools, BtbN ffmpeg with Rubber Band. Same steps as e2e_setup.sh section 9/8.
set -uo pipefail
export PATH=$HOME/.local/bin:$PATH HF_XET_HIGH_PERFORMANCE=1 UV_HTTP_TIMEOUT=600
R=~/anchor-studio/repos; mkdir -p $R/chatterbox ~/anchor-studio/{models/chatterbox,studio/bin,studio/refs}
retry(){ until "$@"; do echo "retrying: $*"; sleep 5; done; }
cd $R/chatterbox && uv venv -q --python 3.12 .venv
retry uv pip install -q --python .venv/bin/python -r ~/anchor-studio/chatterbox.txt --index-url https://pypi.org/simple \
  --extra-index-url https://download.pytorch.org/whl/cu124 --index-strategy unsafe-best-match --no-deps
retry .venv/bin/python -c "
from huggingface_hub import hf_hub_download
for f in ['t3_cfg.safetensors', 's3gen.safetensors', 've.safetensors', 'conds.pt', 'tokenizer.json']:
    hf_hub_download('ResembleAI/chatterbox', f, local_dir='$HOME/anchor-studio/models/chatterbox')"
echo "chatterbox: $(.venv/bin/python -c 'import torch, chatterbox;print(torch.__version__, torch.cuda.is_available())' 2>&1 | tail -1)"
mkdir -p $R/ffmpeg-shared && cd $R/ffmpeg-shared
retry wget -q https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-n8.1-latest-linux64-gpl-shared-8.1.tar.xz
tar xf ffmpeg-n8.1-latest-linux64-gpl-shared-8.1.tar.xz && ln -sfn ffmpeg-n8.1-latest-linux64-gpl-shared-8.1 current && rm -f *.tar.xz
echo "ffmpeg: $(current/bin/ffmpeg -hide_banner -filters 2>/dev/null | grep -c rubberband) rubberband filter(s)"
echo "VOICE SETUP DONE"
