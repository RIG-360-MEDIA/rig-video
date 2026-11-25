import React from "react";
import { Composition } from "remotion";
import { BroadcastPackage } from "./BroadcastPackage.jsx";
import { Captions } from "./Captions.jsx";

// Duration/fps/resolution are read from the story JSON at render time
// (via calculateMetadata) so each composition matches whatever video it's
// being applied to — nothing about a specific video is hardcoded here.

export const RemotionRoot = () => {
  return (
    <>
      <Composition
        id="BroadcastPackage"
        component={BroadcastPackage}
        durationInFrames={1416}
        fps={24}
        width={1280}
        height={736}
        defaultProps={{
          story: {
            anchorName: "ANCHOR NAME",
            anchorTitle: "ANCHOR",
            headline: "HEADLINE",
            lowerThird: { kicker: "BREAKING NEWS", holdSeconds: 8 },
            ticker: { tag: "LIVE", items: [] },
          },
        }}
        calculateMetadata={({ props }) => {
          const v = props.story?.video ?? {};
          return {
            durationInFrames: Math.round((v.durationSeconds ?? 59) * (v.fps ?? 24)),
            fps: v.fps ?? 24,
            width: v.width ?? 1280,
            height: v.height ?? 736,
          };
        }}
      />

      {/* Standalone captions overlay — same on-any-video pattern as
          BroadcastPackage above (duration/fps/resolution read from `video`
          at render time), but with just the caption cues as content. */}
      <Composition
        id="Captions"
        component={Captions}
        durationInFrames={192}
        fps={24}
        width={736}
        height={1280}
        defaultProps={{
          cues: [],
          video: {},
        }}
        calculateMetadata={({ props }) => {
          const v = props.video ?? {};
          return {
            durationInFrames: Math.round((v.durationSeconds ?? 8) * (v.fps ?? 24)),
            fps: v.fps ?? 24,
            width: v.width ?? 736,
            height: v.height ?? 1280,
          };
        }}
      />
    </>
  );
};
