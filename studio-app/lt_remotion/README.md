# Broadcast Package (final pipeline stage)

Remotion-based lower-third + name-tag + ticker overlay, applied as the **last step** of the H3 main pipeline — after the video is generated, chained, and color-locked.

## What it produces (per story, driven entirely by content — nothing hardcoded)

1. **Anchor name tag** — name + title, appears at the very start, holds ~4.5s, clears cleanly.
2. **Headline lower third** — enters once the name tag has cleared, holds (default 8s), clears cleanly. BBC-Reith-inspired: dark charcoal gradient panel, serif headline / sans kicker, single red accent, drop shadow.
3. **Ticker** — fades in early, **persists to the last frame** (no exit) — scrolling crawl of related headlines.
4. **Location bug** — top-left corner super naming **where the news is happening** (the story's dateline/location — *not* the studio/newsroom). Red location-pin tab + dark panel, fades in early and **persists to the last frame**. Only rendered when `story.location` is supplied.

All motion uses crisp cubic-bezier ease-in/out (no spring/bounce) — matches professional broadcast reveal timing, not app-UI physics.

## Usage

```bash
node apply_broadcast_package.mjs <input_video.mp4> <story.json> <output_video.mp4>
```

The script auto-probes the input video's resolution/fps/duration via `ffprobe` and merges them in at render time — `story.json` only needs to describe **content**, never technical video specs, so the same story-file shape works for any video length/resolution.

### `story.json` shape

```json
{
  "anchorName": "David Bennett",
  "anchorTitle": "News Anchor",
  "headline": "HEADLINE TEXT",
  "location": "CITY OR REGION",
  "lowerThird": { "kicker": "BREAKING NEWS", "holdSeconds": 8 },
  "ticker": { "tag": "LIVE", "items": ["headline 1", "headline 2", "..."] },
  "nameTag": { "holdSeconds": 4.5 }
}
```

Every field has a sane default in `src/Root.jsx` / `src/BroadcastPackage.jsx` except `headline`, `anchorName`, and `ticker.items`, which should come from the actual story for that run — see `story.example.json` for a filled-in example matching a real generated video.

- **`location`** (optional): the dateline/location **of the news** — the city or region the story is about, **not** the newsroom. Plain string (e.g. `"GAZA"`), or `{ "text": "GAZA", "startSeconds": 0.5 }` to control when it fades in. Omit it and no location bug is drawn.
- **`logo`** (optional): channel logo bug, top-right corner, persists to the end. A path to a PNG (resolved relative to the story file, then CWD — the apply script inlines it, so no asset plumbing needed), or `{ "src": "logo.png", "heightPx": 60, "startSeconds": 0.5 }`. A `data:`/`http(s):` URL is used as-is. Omit it and no logo is drawn. A transparent PNG is recommended; tight-crop the padding for best corner placement.
- **`lowerThird.repeatEverySeconds`** (optional): if set (and longer than one full show ≈ hold + ~0.85s), the headline lower-third **re-enters every N seconds** instead of clearing forever — it shows, holds, clears, waits, then returns. Omit (or `0`) for the default single appearance.

## Pipeline integration

This is the final stage after color-lock correction (`H3_MAIN_VERSION_LOCKED.md` Part 4). Once the final chained + corrected video lands on the Mac:

```bash
node lt_remotion/apply_broadcast_package.mjs \
  output/<final_video>.mp4 \
  <story_for_this_run>.json \
  output/<final_video>_broadcast.mp4
```

The `story.json` for a given run should be derived from the same script used to generate the video's dialogue (headline = the lede/hook line; ticker items = the other story beats; anchor name = whichever identity was used for that render).

## Rendering settings (why these flags, not the obvious ones)

`--codec=prores --prores-profile=4444 --image-format=png --pixel-format=yuva444p10le`

The default Remotion CLI invocation (`--codec=prores --prores-profile=4444` alone) does **not** produce alpha — it captures intermediate frames as JPEG (no alpha channel possible) and silently outputs `yuv422p12le`. The two extra flags are required; verify a real render actually has alpha before trusting it:

```bash
ffmpeg -ss 2 -i overlay.mov -frames:v 1 -pix_fmt rgba check.png
python3 -c "from PIL import Image; import numpy as np; a=np.array(Image.open('check.png')); print(a[...,3].min(), a[...,3].max())"
# should NOT be uniform (e.g. not "255 255" everywhere)
```

## GPU usage

None. Confirmed via the render log itself (`"Encoder: prores_ks, hardware accelerated: false"`) — rendering is headless-Chromium frame capture + CPU-based ProRes encoding, multi-core parallel (~300% CPU observed), not GPU-accelerated.
