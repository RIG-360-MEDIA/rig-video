import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";

// Broadcast identity super: name + title, shown briefly when the anchor
// first appears on screen. Simpler/smaller than the full headline lower
// third (same accent + font family for brand consistency), positioned in
// the same lower-left zone since it clears before the headline LT enters.
//
// Motion: crisp, professional cubic-bezier slide+fade — no spring/bounce.
// Broadcast graphics reveal fast and precisely; a bouncy physics spring
// reads as "app UI," not "broadcast."

const ACCENT = "#E31B23";

const easeOutCubic = (t) => 1 - Math.pow(1 - t, 3);
const easeInCubic = (t) => t * t * t;

export const NameTag = ({
  name = "ANCHOR NAME",
  title = "ANCHOR",
  startFrame = 0,
  holdSeconds = 4.5,
  inSeconds = 0.35,
  outSeconds = 0.35,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const t = (frame - startFrame) / fps; // local seconds since this element's start
  const inDur = inSeconds;
  const holdEnd = inDur + holdSeconds;
  const outEnd = holdEnd + outSeconds;

  if (t < 0 || t > outEnd) return null;

  let progress; // 0 = hidden, 1 = fully shown
  if (t < inDur) {
    progress = easeOutCubic(Math.min(1, t / inDur));
  } else if (t < holdEnd) {
    progress = 1;
  } else {
    const p = (t - holdEnd) / outSeconds;
    progress = 1 - easeInCubic(Math.min(1, p));
  }

  const slideX = interpolate(progress, [0, 1], [-40, 0]);
  const opacity = progress;

  return (
    <AbsoluteFill>
      <div
        style={{
          position: "absolute",
          left: 64,
          bottom: 96,
          transform: `translateX(${slideX}px)`,
          opacity,
          filter: "drop-shadow(0 8px 18px rgba(0,0,0,0.5))",
          fontFamily: "'Helvetica Neue', Arial, sans-serif",
        }}
      >
        <div style={{ height: 4, width: 72, background: ACCENT, marginBottom: 6 }} />
        <div
          style={{
            background: "linear-gradient(180deg, rgba(24,27,32,0.92) 0%, rgba(12,14,18,0.92) 100%)",
            borderLeft: `5px solid ${ACCENT}`,
            padding: "14px 24px",
            display: "inline-block",
          }}
        >
          <div style={{ color: "#FFFFFF", fontSize: 28, fontWeight: 700, letterSpacing: 0.3 }}>
            {name}
          </div>
          <div
            style={{
              color: "#C9CCD1",
              fontSize: 17,
              fontWeight: 600,
              letterSpacing: 1.5,
              textTransform: "uppercase",
              marginTop: 2,
            }}
          >
            {title}
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};
