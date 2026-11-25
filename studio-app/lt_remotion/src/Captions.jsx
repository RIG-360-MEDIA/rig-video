import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";

// Social-style burned-in captions (TikTok/Reels convention): short word
// groups, bold caps, heavy dark stroke for legibility over any background,
// bottom-third position so they clear a name tag/lower third if both are
// present. Timing is driven entirely by `cues` (start/end in seconds, plus
// text) — nothing about a specific video's dialogue is hardcoded here.
//
// cues shape: [{ start: 0.0, end: 0.73, text: "GOOD EVENING." }, ...]

const easeOutCubic = (t) => 1 - Math.pow(1 - t, 3);

export const Captions = ({ cues = [], marginBottomPercent = 14, fontSize = 4.2 }) => {
  const frame = useCurrentFrame();
  const { fps, width } = useVideoConfig();
  const t = frame / fps;

  const active = cues.find((c) => t >= c.start && t < c.end);
  if (!active) return null;

  const localT = t - active.start;
  const dur = active.end - active.start;
  const inDur = Math.min(0.08, dur * 0.3);
  const progress = easeOutCubic(Math.min(1, localT / inDur));
  const scale = 0.92 + 0.08 * progress;
  const opacity = progress;

  const px = (width * fontSize) / 100;

  return (
    <AbsoluteFill
      style={{
        justifyContent: "flex-end",
        alignItems: "center",
        paddingBottom: `${marginBottomPercent}%`,
      }}
    >
      <div
        style={{
          fontFamily: "Arial, Helvetica, sans-serif",
          fontWeight: 900,
          fontSize: px,
          lineHeight: 1.15,
          color: "#FFFFFF",
          textAlign: "center",
          maxWidth: "88%",
          padding: "0 4%",
          letterSpacing: "0.01em",
          textShadow: [
            "-3px -3px 0 #000",
            "3px -3px 0 #000",
            "-3px 3px 0 #000",
            "3px 3px 0 #000",
            "0 3px 10px rgba(0,0,0,0.55)",
          ].join(", "),
          transform: `scale(${scale})`,
          opacity,
        }}
      >
        {active.text}
      </div>
    </AbsoluteFill>
  );
};
