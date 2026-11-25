#!/usr/bin/env bash
# The VO clip checker's vision model on trijya-7 (user 2026-11-21: the VL model may move to t7 for speed): llama.cpp
# llama-server, Qwen3-VL 8B Instruct Q8_0 (+ F16 vision encoder) from Qwen's own GGUF repo, on the 4090.
# OpenAI-compatible on the Tailscale address only, port 11620. One request at a time (the checker calls it story by
# story), 32k context, q8 KV cache, frames at >= 1024 tokens (Qwen-VL needs it for detail; same as trijya-8): ~12.5 GB of VRAM while awake. Sleeps after 10 idle minutes (frees the GPU for
# renders and the other tenants), wakes on the next call. Built from llama.cpp 0fb8f15 (same as trijya-8) for sm_89.
cd ~/vo_check/src/build/bin
M=~/vo_check/models
exec ./llama-server -m $M/Qwen3VL-8B-Instruct-Q8_0.gguf --mmproj $M/mmproj-Qwen3VL-8B-Instruct-F16.gguf \
  --alias vlm --host 100.72.225.89 --port 11620 -ngl 99 -fa on -np 1 -c 32768 -ctk q8_0 -ctv q8_0 --jinja --image-min-tokens 1024 \
  -b 2048 -ub 512 --sleep-idle-seconds 600 --no-webui
