# H3StepProfiler — measure where one H3 sampling step spends its time. Test-install only.
#
# Every diffusion-model call:   CUDA-event wall time of the whole forward (+ pre-block / blocks / final split),
#                               and per-block sub-module time (adaln, attention, mlp) via CUDA events.
# On ONE chosen call (profile_call): torch.profiler over the full forward → kernel-level table
#                               (GEMM int8, attention kernel, elementwise, H2D weight copies, idle gaps).
# Output: <ComfyUI>/output/h3prof/<tag>_calls.jsonl and <tag>_kernels.txt / <tag>_trace.json
import json, os, time
import torch
import comfy.patcher_extension as pe
import folder_paths

OUT = os.path.join(folder_paths.get_output_directory(), "h3prof")


class _Timer:
    """Accumulate CUDA-event intervals per label for the current forward."""
    def __init__(self):
        self.pending = []  # (label, start_event, end_event)

    def wrap(self, label, fn):
        def inner(*a, **k):
            s, e = torch.cuda.Event(enable_timing=True), torch.cuda.Event(enable_timing=True)
            s.record()
            with torch.autograd.profiler.record_function(label):
                out = fn(*a, **k)
            e.record()
            self.pending.append((label, s, e))
            return out
        return inner

    def collect(self):
        torch.cuda.synchronize()
        tot = {}
        for label, s, e in self.pending:
            tot[label] = tot.get(label, 0.0) + s.elapsed_time(e)
        self.pending = []
        return tot


class H3StepProfiler:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"model": ("MODEL",),
                             "tag": ("STRING", {"default": "run"}),
                             "profile_call": ("INT", {"default": 3, "min": 0, "max": 200})}}

    RETURN_TYPES = ("MODEL",)
    FUNCTION = "apply"
    CATEGORY = "MiniMax H3/debug"

    def apply(self, model, tag, profile_call):
        os.makedirs(OUT, exist_ok=True)
        m = model.clone()
        dm = m.get_model_object("diffusion_model")
        timer = _Timer()
        for i, blk in enumerate(dm.blocks):                       # sub-module timing inside every DiT block
            for sub in ("adaln_proj", "attn", "mlp"):
                mod = getattr(blk, sub)
                m.add_object_patch(f"diffusion_model.blocks.{i}.{sub}.forward", timer.wrap(sub, mod.forward))
        state = {"n": 0}
        log = open(os.path.join(OUT, f"{tag}_calls.jsonl"), "a")

        def wrapper(executor, *args, **kwargs):
            n = state["n"]; state["n"] += 1
            torch.cuda.synchronize(); t0 = time.perf_counter()
            s, e = torch.cuda.Event(enable_timing=True), torch.cuda.Event(enable_timing=True)
            s.record()
            if n == profile_call:
                acts = [torch.profiler.ProfilerActivity.CPU, torch.profiler.ProfilerActivity.CUDA]
                with torch.profiler.profile(activities=acts, record_shapes=False) as prof:
                    out = executor(*args, **kwargs)
                    torch.cuda.synchronize()
                ka = prof.key_averages()
                with open(os.path.join(OUT, f"{tag}_kernels.txt"), "w") as f:
                    f.write(ka.table(sort_by="cuda_time_total", row_limit=60))
                    f.write("\n\n=== by self CUDA time ===\n")
                    f.write(ka.table(sort_by="self_cuda_time_total", row_limit=60))
                try:
                    prof.export_chrome_trace(os.path.join(OUT, f"{tag}_trace.json"))
                except Exception as ex:  # trace export is a nice-to-have
                    print("[H3StepProfiler] trace export failed:", ex)
            else:
                out = executor(*args, **kwargs)
            e.record(); torch.cuda.synchronize()
            wall = (time.perf_counter() - t0) * 1000
            parts = timer.collect()
            seg = {}
            if n == 0:  # token budget of the packed sequence (attention cost ~ length^2)
                try:
                    x, ctx = args[0], args[2]
                    seg = {"text_ctx_tokens": int(ctx.shape[1]), "video_latent": list(x[0].shape), "audio_latent": list(x[1].shape)}
                    pl = (kwargs.get("minimax_payload") or {}).get("layout")
                    if pl is not None:
                        seg["seq_len"] = int(pl.seq_len)
                        seg["segments"] = [[str(k), int(b - a)] for a, b, k in pl.segments]
                    refs = (kwargs.get("minimax_payload") or {}).get("refs") or []
                    seg["refs"] = [{kk: (list(v.shape) if hasattr(v, "shape") else v) for kk, v in r.items() if kk in ("kind", "latent_t", "ref_audio_t")} for r in refs]
                except Exception as ex:
                    seg = {"token_probe_error": str(ex)}
            rec = {"call": n, "wall_ms": round(wall, 1), "gpu_ms": round(s.elapsed_time(e), 1), **({"tokens": seg} if seg else {}),
                   "parts_ms": {k: round(v, 1) for k, v in parts.items()},
                   "blocks_sum_ms": round(sum(parts.values()), 1),
                   "vram_alloc_gb": round(torch.cuda.memory_allocated() / 2**30, 2),
                   "vram_peak_gb": round(torch.cuda.max_memory_allocated() / 2**30, 2),
                   "profiled": n == profile_call}
            log.write(json.dumps(rec) + "\n"); log.flush()
            print(f"[H3StepProfiler] {rec}")
            torch.cuda.reset_peak_memory_stats()
            return out

        m.add_wrapper_with_key(pe.WrappersMP.DIFFUSION_MODEL, "h3_step_profiler", wrapper)
        return (m,)


NODE_CLASS_MAPPINGS = {"H3StepProfiler": H3StepProfiler}
NODE_DISPLAY_NAME_MAPPINGS = {"H3StepProfiler": "MiniMax H3 Step Profiler (debug)"}
