import React from "react";
import { Composition } from "remotion";
import { BroadcastPackage } from "./BroadcastPackage.jsx";

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

    </>
  );
};
