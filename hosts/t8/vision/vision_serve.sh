#!/usr/bin/env bash
# The clip checker's model server on trijya-8: llama.cpp llama-server on Ollama's own qwen3-vl 8B Q4_K_M files (same
# weights as before), OpenAI-compatible on 100.95.0.11:11610 (Tailscale): the footage search on trijya-7 uses it
# for its text calls too (moment finding, script analysis), so Groq's daily caps never stall a search. 4 calls at once on one shared KV pool. --image-min-tokens
# 1024 keeps the frames at the size Ollama gave them (~1030 tokens each): same answers, 1.25x faster (bench 2026-11-19).
# Sleeps (frees the GPU for the tenants) after 15 idle minutes, like Ollama's keep-alive; wakes on the next call.
# The binary bundle (CUDA 12 libs inside) is ~/vision/llamacpp, built on trijya-3 at llama.cpp 0fb8f15 for sm_86/89.
cd ~/vision/llamacpp
B=~/vision/models/blobs
export LD_LIBRARY_PATH=$PWD
exec ./llama-server -m $B/sha256-a0c1f7c1356ebc4135b6d12f726c18487669f1a7099156323d0f7b4ca91aca99 \
  --mmproj $B/sha256-85aa79666ee786bcc4fe69ac343db5ad468b71ad6272c12bfd8dfb29a8bdf18a \
  --alias qwen3-vl-q4 --host 100.95.0.11 --port 11610 -ngl 99 -fa on -np 4 -c 24576 --jinja -kvu -b 2048 -ub 512 \
  --cache-reuse 256 --image-min-tokens 1024 --sleep-idle-seconds 900 --no-webui
