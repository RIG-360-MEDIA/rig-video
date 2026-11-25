import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";

// Location bug: a small top-left super naming WHERE THE NEWS IS happening
// (the story's dateline / location — NOT the studio/newsroom). Persists for
// the whole story once it fades in, the way a broadcast location super sits
// in-corner throughout a package. Same accent + font family + dark gradient
// panel as the NameTag / LowerThird for brand consistency.
//
// Motion: crisp cubic-bezier slide+fade in (no spring/bounce); no exit —
// it holds to the last frame like the ticker.

const ACCENT = "#E31B23";
const easeOutCubic = (t) => 1 - Math.pow(1 - t, 3);

export const LocationBug = ({
  location = "",
  startFrame = 0,
  inSeconds = 0.4,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  if (!location) return null; // nothing hardcoded — only renders when supplied

  const t = (frame - startFrame) / fps;
  if (t < 0) return null;

  const progress = easeOutCubic(Math.min(1, t / inSeconds)); // fade/slide in, then persist
  const slideX = interpolate(progress, [0, 1], [-32, 0]);
  const opacity = progress;

  return (
    <AbsoluteFill>
      <div
        style={{
          position: "absolute",
          left: 48,
          top: 48,
          transform: `translateX(${slideX}px)`,
          opacity,
          filter: "drop-shadow(0 6px 14px rgba(0,0,0,0.5))",
          fontFamily: "'Helvetica Neue', Arial, sans-serif",
          display: "inline-flex",
          alignItems: "stretch",
        }}
      >
        {/* red tab with a location-pin glyph */}
        <div
          style={{
            background: ACCENT,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: "0 12px",
          }}
        >
          <svg width="16" height="20" viewBox="0 0 16 20" fill="none" aria-hidden="true">
            <path
              d="M8 0C3.58 0 0 3.4 0 7.6 0 13.3 8 20 8 20s8-6.7 8-12.4C16 3.4 12.42 0 8 0z"
              fill="#FFFFFF"
            />
            <circle cx="8" cy="7.4" r="3" fill={ACCENT} />
          </svg>
        </div>
        {/* dark panel with the location name */}
        <div
          style={{
            background:
              "linear-gradient(180deg, rgba(24,27,32,0.92) 0%, rgba(12,14,18,0.92) 100%)",
            padding: "10px 20px",
            display: "flex",
            alignItems: "center",
          }}
        >
          <span
            style={{
              color: "#FFFFFF",
              fontSize: 22,
              fontWeight: 700,
              letterSpacing: 2.5,
              textTransform: "uppercase",
            }}
          >
            {location}
          </span>
        </div>
      </div>
    </AbsoluteFill>
  );
};
