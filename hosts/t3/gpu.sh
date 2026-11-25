#!/bin/bash
# t3: ~/rigvideo/llm/gpu.sh writer|voice : load the script model (rigvideo-writer) or free the GPU for the voice model.
# Called by t7 (store.gpu) under its lock; exits once the asked mode is ready.
cd ~/rigvideo/llm
case "$1" in
  writer)
    systemctl --user is-active -q rigvideo-writer || systemctl --user start rigvideo-writer
    for i in $(seq 200); do                                   # /health says ok while still loading: ask for one token
      curl -s -m 30 -H "Authorization: Bearer $(cat api.key)" -H "Content-Type: application/json" \
        -d '{"model":"writer","messages":[{"role":"user","content":"hi"}],"max_tokens":1}' \
        http://100.99.155.88:8780/v1/chat/completions | grep -q '"choices"' && exit 0
      systemctl --user is-active -q rigvideo-writer || { echo "writer failed to start" >&2; exit 1; }
      sleep 3
    done
    echo "writer not ready after 10 min" >&2; exit 1 ;;
  voice)
    systemctl --user stop rigvideo-writer
    while pgrep -f "[l]lama-server -m .*--port 8780" >/dev/null; do sleep 1; done ;;
  *) echo "usage: gpu.sh writer|voice" >&2; exit 2 ;;
esac
