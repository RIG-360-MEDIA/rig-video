import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";

// Channel logo bug, top-right corner. Persistent station ident that fades in
// early and holds to the last frame (like the ticker / location bug). The
// image itself is supplied per-run (story.logo) — the apply script inlines
// the PNG the user provides as a data URI, so nothing is hardcoded here.
//
// Motion: a plain fade in (no slide) — a station logo should feel bolted to
// the corner, not animated in like an editorial super.

const easeOutCubic = (t) => 1 - Math.pow(1 - t, 3);

export const Logo = ({
  src = "",
  heightPx = 60,
  marginPx = 40,
  startFrame = 0,
  inSeconds = 0.5,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  if (!src) return null; // only renders when a logo is supplied

  const t = (frame - startFrame) / fps;
  if (t < 0) return null;
  const opacity = easeOutCubic(Math.min(1, t / inSeconds));

  return (
    <AbsoluteFill>
      <img
        src={src}
        alt="logo"
        style={{
          position: "absolute",
          top: marginPx,
          right: marginPx,
          height: heightPx,
          width: "auto",
          opacity,
          filter: "drop-shadow(0 4px 12px rgba(0,0,0,0.55))",
        }}
      />
    </AbsoluteFill>
  );
};
