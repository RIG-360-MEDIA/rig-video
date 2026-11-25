# Converter speed (2026-11-20 IST, t8)

t7 went offline at about 12:50 IST, so this ran on t8 (RTX 4070 12 GB, 24 threads, shared with tenants). The converter
is in t8 `~/vertical`, in its own venv. Code: anchor-studio-dnl `pipeline/tools/vertical/vconv.py` (commits acedb40,
999a533).

Clips: the 30 v1 clips, downloaded again on t8. 4 came back audio-only because t8's yt-dlp lacks t7's PO-token wrapper,
so 25 clips with video were used, about 474 s in total. The zero-loss check is `compare.py`: the same shots, modes, crop
paths and blur patches in every JSON, and an md5 of the decoded output frames.

| Run | Time for 25 clips | × clip length | Median | p95 | Output vs baseline |
|---|---|---|---|---|---|
| Baseline (v1) | 878 s | 1.85 | 1.52 | 3.28 | — |
| Output frames composed in 8 threads | 479 s | 1.01 | 0.83 | 2.10 | identical |
| + OCR on GPU | 274 s | 0.58 | 0.54 | 0.86 | identical except one OCR box (below) |
| + 16 render threads (now the default) | 224 s | 0.47 | 0.45 | 0.75 | identical to the line above |

Golden-set target Q43 is ≤ 0.5× clip length, set for the 4090. It is met on the 4070. t8's tenant load shifts these
numbers by about ±15% between runs.

## What was slow and what fixed it
- **Composing 1080×1920 frames one by one (55%).** Text blur patches made it worse: up to 242 ms per frame on clips with
  many patches. Fix: frames are composed in a bounded thread pool (cv2 releases the GIL) and written in order. The
  output is bit-identical.
- **OCR on the CPU (20%), 243 ms per frame.** Fix: OCR on the GPU, 28 ms per frame. It needs **onnxruntime-gpu 1.23.2**
  (the CUDA 12 build) so it shares torch's CUDA 12.8 / cuDNN 9.19 libraries.
  - Trap: onnxruntime-gpu 1.32 needs CUDA 13. Its `[cuda,cudnn]` extras install `nvidia-cudnn-cu13`, which overwrites
    torch's cuDNN files in `site-packages/nvidia/cudnn`. Torch then runs cuDNN 9.28, every model's numbers shift, and
    crops changed on 3 shots (2 visibly worse). This was undone: the cu12 wheels were reinstalled and torch reports cuDNN
    91900 again.
  - The one difference left: in one shot, a blur patch over a small text box is 0.5 px off at analysis size (about
    1.5 px in the output, on a feathered patch). GPU and CPU OCR float noise. Same crop, same mode.

## What's left (not needed for the target)
- Render is still about half the time: the 1080p decode, and the bgr→yuv conversion plus the pipe into NVENC.
- The clip is decoded 3 times (cropdetect, analysis, render).
- t7's venv still has onnxruntime-gpu 1.32, so OCR there quietly runs on the CPU. When the converter runs on t7, install
  1.23.2 there too (`pip install onnxruntime-gpu==1.23.2`, no extras).
