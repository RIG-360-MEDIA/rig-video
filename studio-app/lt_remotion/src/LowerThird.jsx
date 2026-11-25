import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";

// BBC-Reith-inspired headline lower third: dark charcoal gradient panel, one
// accent color (rule + left stripe), mixed serif (headline) / sans (kicker)
// hierarchy, real drop shadow.
//
// Motion: crisp cubic-bezier slide+fade reveal/exit (same language as
// NameTag) — a staggered two-stage reveal (kicker chip settles fractionally
// before the headline panel) is the one flourish broadcast packages commonly
// use; no spring/bounce anywhere.

const ACCENT = "#E31B23";
const BASE_ALPHA = 0.92;

const easeOutCubic = (t) => 1 - Math.pow(1 - t, 3);
const easeInCubic = (t) => t * t * t;

const stageProgress = (t, delay, inDur, holdEnd, outSeconds) => {
  const lt = t - delay;
  if (lt < 0) return 0;
  if (lt < inDur) return easeOutCubic(Math.min(1, lt / inDur));
  if (lt < holdEnd) return 1;
  const p = (lt - holdEnd) / outSeconds;
  return 1 - easeInCubic(Math.min(1, p));
};

export const LowerThird = ({
  kicker = "BREAKING NEWS",
  headline = "HEADLINE",
  startFrame = 0,
  holdSeconds = 8,
  inSeconds = 0.45,
  outSeconds = 0.4,
  repeatEverySeconds = 0,
  subline = "",
}) => {
  const frame = useCurrentFrame();
  const { fps, width } = useVideoConfig();

  const tAbs = (frame - startFrame) / fps;
  const holdEnd = inSeconds + holdSeconds;
  const outEnd = holdEnd + outSeconds;
  if (tAbs < 0) return null;
  // If repeatEverySeconds is set (and longer than one full show), the headline
  // re-enters every cycle instead of clearing forever — show for `outEnd`
  // seconds, then a gap until the next cycle.
  const t =
    repeatEverySeconds && repeatEverySeconds > outEnd
      ? tAbs % repeatEverySeconds
      : tAbs;
  if (t > outEnd) return null;

  const barProgress = stageProgress(t, 0, inSeconds, holdEnd, outSeconds);
  const kickerProgress = stageProgress(t, 0.06, inSeconds, holdEnd, outSeconds);
  const headlineProgress = stageProgress(t, 0.12, inSeconds, holdEnd, outSeconds);

  const slideX = interpolate(barProgress, [0, 1], [-60, 0]);
  const opacity = barProgress;
  const kickerSlide = interpolate(kickerProgress, [0, 1], [-24, 0]);
  const headlineSlide = interpolate(headlineProgress, [0, 1], [-16, 0]);

  const leftMargin = 64;
  const barWidth = Math.min(width - leftMargin * 2, 1120);

  return (
    <AbsoluteFill>
      <div
        style={{
          position: "absolute",
          left: leftMargin,
          bottom: 96,
          width: barWidth,
          transform: `translateX(${slideX}px)`,
          opacity,
          filter: "drop-shadow(0 10px 22px rgba(0,0,0,0.55))",
          fontFamily: "'Helvetica Neue', Arial, sans-serif",
        }}
      >

        <div
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 8,
            transform: `translateX(${kickerSlide}px)`,
            opacity: kickerProgress,
            marginBottom: 8,
          }}
        >
          <span
            style={{
              background: ACCENT,
              color: "#FFFFFF",
              padding: "5px 12px 4px",
              fontSize: 20,
              fontWeight: 700,
              letterSpacing: 2,
              textTransform: "uppercase",
              boxShadow: "0 2px 6px rgba(0,0,0,0.45)",
            }}
          >
            {kicker}
          </span>
        </div>

        <div
          style={{
            background: `linear-gradient(180deg, rgba(24,27,32,${BASE_ALPHA}) 0%, rgba(12,14,18,${BASE_ALPHA}) 100%)`,
            borderLeft: `5px solid ${ACCENT}`,
            padding: "20px 28px",
            transform: `translateX(${headlineSlide}px)`,
          }}
        >
          <div
            style={{
              fontFamily: "Georgia, 'Times New Roman', serif",
              fontWeight: 700,
              fontSize: 34,
              lineHeight: 1.22,
              color: "#FFFFFF",
              letterSpacing: 0.2,
              textShadow: "0 1px 2px rgba(0,0,0,0.4)",
            }}
          >
            {headline}
          </div>
          {subline ? (
            <div
              style={{
                marginTop: 8,
                fontSize: 21,
                fontWeight: 500,
                lineHeight: 1.25,
                color: "#D9DCE1",
                letterSpacing: 0.6,
                textTransform: "uppercase",
              }}
            >
              {subline}
            </div>
          ) : null}
        </div>
      </div>
    </AbsoluteFill>
  );
};
