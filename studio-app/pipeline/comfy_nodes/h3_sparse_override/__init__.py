# H3 Sol-Attn via the attention OVERRIDE only — so it stacks with FirstBlockCache.
#
# ComfyUI's BlockSparseAttention installs BOTH an attention override and per-block `double_block` replacements
# (a chunked, memory-saving QKV producer). The block replacements collide with FirstBlockCache, which owns
# the DiT block slots. This node keeps the identical sparse kernel call (comfy_kitchen.sol_attn, same tau /
# sink / extra-token semantics, same sigma window via nodes_sparse_attention.SparseAttnPatch) but only hooks
# `optimized_attention_override`, unwrapping H3's AttentionTensorContainer inputs. Text/ref/audio rows stay
# exact (sink_conditioning) because the H3 model publishes `minimax_h3_layout` on every call.
# Dense fallback: outside the window / below min_tokens / dense_blocks → the original attention, untouched.
import logging

import comfy_kitchen as ck
import torch

import comfy.patcher_extension
from comfy.ldm.modules.attention import AttentionTensorContainer
from comfy_extras import nodes_sparse_attention as nsa


def _make_override(patch, previous):
    def override(func, q, k, v, heads, mask=None, attn_precision=None,
                 skip_reshape=False, skip_output_reshape=False, **kwargs):
        to = kwargs.get("transformer_options") or {}

        def dense():
            kw = dict(mask=mask, attn_precision=attn_precision, skip_reshape=skip_reshape,
                      skip_output_reshape=skip_output_reshape, **kwargs)
            return func(q, k, v, heads, **kw) if previous is None else previous(func, q, k, v, heads, **kw)

        if mask is not None or not skip_reshape:
            return dense()
        qt = q.peek() if isinstance(q, AttentionTensorContainer) else q
        tokens = qt.shape[2]                                   # BHND
        reason = patch.dense_reason(to, tokens, to.get("block_index"))
        if reason is not None:
            patch.log_once(("dense", tokens, reason), f"dense ({tokens} tokens): {reason}")
            return dense()
        take = lambda t: t.take() if isinstance(t, AttentionTensorContainer) else t
        b, _, _, dim_head = qt.shape
        qs, ks, vs = (take(t).transpose(1, 2) for t in (q, k, v))   # -> B N H D
        if qs.dtype == torch.float32:
            qs, ks, vs = (t.to(torch.bfloat16) for t in (qs, ks, vs))
        sink, sink_q = patch.sinks(to, tokens)
        out = ck.sol_attn(qs, ks, vs, tau=patch.tau, scale=kwargs.get("scale"),
                          sink_blocks=list(sink), sink_q=list(sink_q), topk_ratio=patch.topk_ratio,
                          token_aug=patch.extra_tokens)
        patch.log_once(("sparse", tokens), f"sparse {tuple(qs.shape)}, sinks {sink}/{sink_q}")
        if skip_output_reshape:
            return out.transpose(1, 2)
        return out.reshape(b, -1, heads * dim_head)
    return override


class H3SparseAttentionOverride:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "model": ("MODEL",),
            "tau": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 4.0, "step": 0.05}),
            "start_percent": ("FLOAT", {"default": 0.4, "min": 0.0, "max": 1.0, "step": 0.01}),
            "end_percent": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.01}),
            "dense_blocks": ("STRING", {"default": "0-2, 47-49"}),
            "min_tokens": ("INT", {"default": 12288, "min": 0, "max": 1 << 20}),
            "extra_tokens": ("INT", {"default": 256, "min": 0, "max": 256, "step": 64}),
            "sink_conditioning": (["exact_kv_and_rows", "exact_kv", "off"],),
            "verbose": ("BOOLEAN", {"default": True}),
        }}

    RETURN_TYPES = ("MODEL",)
    FUNCTION = "apply"
    CATEGORY = "MiniMax H3/optimization"

    def apply(self, model, tau, start_percent, end_percent, dense_blocks, min_tokens, extra_tokens,
              sink_conditioning, verbose):
        ms = model.get_model_object("model_sampling")
        patch = nsa.SparseAttnPatch(tau=tau, topk_ratio=0.0, vsa=False,
                                    sigma_start=float(ms.percent_to_sigma(start_percent)),
                                    sigma_end=float(ms.percent_to_sigma(end_percent)),
                                    min_tokens=min_tokens, dense_blocks=nsa.parse_block_list(dense_blocks),
                                    sink_conditioning=sink_conditioning, extra_tokens=extra_tokens, verbose=verbose)
        m = model.clone()

        def install(to):
            cur = to.get("optimized_attention_override")
            if cur in patch.installed:
                return
            o = _make_override(patch, cur)
            patch.installed.add(o)
            to["optimized_attention_override"] = o

        install(m.model_options["transformer_options"])
        m.add_callback_with_key(comfy.patcher_extension.CallbacksMP.ON_PREPARE_STATE, "h3_sparse_override",
                                lambda mp, ts, mo: install(mo["transformer_options"]))
        m.add_callback_with_key(comfy.patcher_extension.CallbacksMP.ON_CLEANUP, "h3_sparse_override",
                                lambda mp: patch.reset())
        logging.info(f"H3SparseAttentionOverride: tau={tau} window={start_percent}-{end_percent} dense={dense_blocks}")
        return (m,)


NODE_CLASS_MAPPINGS = {"H3SparseAttentionOverride": H3SparseAttentionOverride}
NODE_DISPLAY_NAME_MAPPINGS = {"H3SparseAttentionOverride": "MiniMax H3 Sparse Attention (override-only, FBC-compatible)"}
