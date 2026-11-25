Local edits to third-party ComfyUI nodes, saved from trijya-7 before it was handed over (2026-10-29).

- `firstblockcache-f7a2712-generated-frames.patch` — `ComfyUI-MiniMaxH3-FirstBlockCache` at `f7a2712`: adds the preset
  "H3 Fast generated-frames — 0.10 / max 2", which decides cache hits on the median video latent frame (+ audio rows)
  so chain overlap frames do not swamp the measure. **Experimental, not used by the locked recipe** (the recipe uses
  "H3 Fast — 0.10 / max 2"; FirstBlockCache cannot skip chain steps with lcm anyway, see baseline/RECIPE_CURRENT.md).
  Apply with `git -C custom_nodes/ComfyUI-MiniMaxH3-FirstBlockCache apply <patch>` only if you want that preset.
