#!/bin/bash
# RIG-Video script-model bench setup: user-space CUDA toolchain + llama.cpp + candidate GGUFs. Touches only ~/rigvideo.
set -euo pipefail
R=$HOME/rigvideo/llm; mkdir -p $R/models $R/bin; cd $R
exec > >(tee -a $R/setup.log) 2>&1
echo "start $(date -u +%FT%TZ)"
if [ ! -x $R/bin/micromamba ]; then
  curl -sL https://micro.mamba.pm/api/micromamba/linux-64/latest | tar -xj -C $R bin/micromamba
fi
export MAMBA_ROOT_PREFIX=$R/mamba
[ -d $R/mamba/envs/cuda ] || $R/bin/micromamba create -y -q -n cuda -c nvidia/label/cuda-12.8.1 -c conda-forge cuda-nvcc cuda-cudart-dev libcublas-dev cuda-version=12.8 cmake ninja gxx_linux-64=13 git
E=$R/mamba/envs/cuda; export PATH=$E/bin:$PATH CUDA_HOME=$E
# models download in parallel with the build
dl(){ [ -s models/$2 ] || curl -sfL --retry 5 -C - -o models/$2 "https://huggingface.co/$1/resolve/main/$2"; echo "got $2 $(du -h models/$2 | cut -f1)"; }
( dl unsloth/Qwen3.6-35B-A3B-GGUF Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf; dl unsloth/gemma-4-26B-A4B-it-GGUF gemma-4-26B-A4B-it-UD-Q4_K_XL.gguf ) &
[ -d llama.cpp ] || git clone -q --depth 1 https://github.com/ggml-org/llama.cpp
cd llama.cpp
cmake -B build -G Ninja -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES="86;89" -DCMAKE_BUILD_TYPE=Release -DLLAMA_CURL=OFF -DCMAKE_CUDA_COMPILER=$E/bin/nvcc >/dev/null
cmake --build build -j 8 --target llama-server llama-bench llama-cli 2>&1 | tail -2
echo "built $(git rev-parse --short HEAD)"
wait; echo "done $(date -u +%FT%TZ)"
