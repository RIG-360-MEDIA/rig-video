import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";

// Classic broadcast news ticker: dark strip pinned to the bottom edge, a
// colored tag on the left, and a continuously/seamlessly looping horizontal
// scroll of headline items. Fades in once and then PERSISTS to the end of
// the video (no exit) — the ticker is the one element broadcast packages
// keep on screen throughout, unlike the temporary name-tag/headline LT.

const ACCENT = "#E31B23";
const STRIP_BG = "rgba(10,12,15,0.94)";

const easeOutCubic = (t) => 1 - Math.pow(1 - t, 3);

export const Ticker = ({
  tag = "LIVE",
  items = ["No ticker items provided"],
  startFrame = 0,
  inSeconds = 0.4,
  speedPxPerSecond = 90, // broadcast-crawl pace (was 140: read as too fast); override via story.ticker.speedPxPerSecond
}) => {
  const frame = useCurrentFrame();
  const { fps, width } = useVideoConfig();

  const t = (frame - startFrame) / fps;
  if (t < 0) return null;

  const opacity = easeOutCubic(Math.min(1, t / inSeconds));

  const separator = "     •     ";
  const joined = items.join(separator) + separator;
  const approxCharWidthPx = 15.5;
  const contentWidth = joined.length * approxCharWidthPx;

  const scrolledPx = Math.max(0, t) * speedPxPerSecond;
  const x = -(scrolledPx % contentWidth);

  const stripHeight = 46;
  const tagWidth = 108;

  return (
    <AbsoluteFill>
      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          bottom: 0,
          height: stripHeight,
          background: STRIP_BG,
          display: "flex",
          alignItems: "center",
          fontFamily: "'Helvetica Neue', Arial, sans-serif",
          overflow: "hidden",
          opacity,
        }}
      >
        <div
          style={{
            width: tagWidth,
            height: "100%",
            background: ACCENT,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            flexShrink: 0,
          }}
        >
          <span style={{ color: "#FFFFFF", fontWeight: 800, fontSize: 20, letterSpacing: 1.5 }}>
            {tag}
          </span>
        </div>

        <div
          style={{
            position: "relative",
            width: width - tagWidth,
            height: "100%",
            overflow: "hidden",
          }}
        >
          <div
            style={{
              position: "absolute",
              whiteSpace: "nowrap",
              top: "50%",
              transform: `translate(${x}px, -50%)`,
              color: "#F2F2F2",
              fontSize: 22,
              fontWeight: 600,
            }}
          >
            {joined}
            {joined}
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};
