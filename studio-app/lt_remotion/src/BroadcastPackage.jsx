import React from "react";
import { AbsoluteFill, useVideoConfig } from "remotion";
import { NameTag } from "./NameTag.jsx";
import { LowerThird } from "./LowerThird.jsx";
import { Ticker } from "./Ticker.jsx";
import { LocationBug } from "./LocationBug.jsx";
import { Logo } from "./Logo.jsx";

// Sequences the three broadcast elements from one "story" object — the
// single per-video content source. Nothing here is hardcoded: every video
// supplies its own anchorName/anchorTitle/headline/tickerItems via story.json.
//
// Timeline (all overridable per-story):
//   name tag  : 0s              -> clears after (in+hold+out)
//   ticker    : shortly after 0 -> persists to the end of the video (no exit)
//   headline  : starts once the name tag has cleared -> holds -> clears

export const BroadcastPackage = ({ story }) => {
  const { fps } = useVideoConfig();

  const nameIn = story.nameTag?.inSeconds ?? 0.35;
  const nameHold = story.nameTag?.holdSeconds ?? 4.5;
  const nameOut = story.nameTag?.outSeconds ?? 0.35;
  const nameTotalSeconds = nameIn + nameHold + nameOut;

  const tickerStartSeconds = story.ticker?.startSeconds ?? 0.4;

  // Location bug (top-left): where the NEWS is, not the newsroom. Accepts
  // story.location as a plain string, or { text, startSeconds } for control.
  const locationText =
    typeof story.location === "string" ? story.location : story.location?.text ?? "";
  const locationStartSeconds =
    (typeof story.location === "object" ? story.location?.startSeconds : undefined) ?? 0.5;

  const ltGapSeconds = story.lowerThird?.startDelayAfterNameTagSeconds ?? 0.3;
  const ltStartSeconds = story.lowerThird?.startSeconds
    ?? (nameTotalSeconds + ltGapSeconds);
  const ltStartFrame = Math.round(ltStartSeconds * fps);

  return (
    <AbsoluteFill>
      <Ticker
        tag={story.ticker?.tag ?? "LIVE"}
        items={story.ticker?.items ?? []}
        startFrame={Math.round(tickerStartSeconds * fps)}
        speedPxPerSecond={story.ticker?.speedPxPerSecond ?? 90}
      />
      {(story.lowerThirds ?? []).map((l, i) => (
        <LowerThird
          key={i}
          kicker={l.kicker ?? story.lowerThird?.kicker ?? "BREAKING NEWS"}
          headline={l.headline}
          subline={l.subline ?? ""}
          startFrame={Math.round(l.start * fps)}
          holdSeconds={l.hold ?? 7}
        />
      ))}
      {story.lowerThirds ? null : <LowerThird
        kicker={story.lowerThird?.kicker ?? "BREAKING NEWS"}
        headline={story.headline}
        subline={story.lowerThird?.subline ?? ""}
        startFrame={ltStartFrame}
        holdSeconds={story.lowerThird?.holdSeconds ?? 8}
        repeatEverySeconds={story.lowerThird?.repeatEverySeconds ?? 0}
      />}
      <NameTag
        name={story.anchorName}
        title={story.anchorTitle ?? "ANCHOR"}
        startFrame={0}
        holdSeconds={nameHold}
        inSeconds={nameIn}
        outSeconds={nameOut}
      />
      <LocationBug
        location={locationText}
        startFrame={Math.round(locationStartSeconds * fps)}
      />
      <Logo
        src={typeof story.logo === "string" ? story.logo : story.logo?.src ?? ""}
        heightPx={(typeof story.logo === "object" ? story.logo?.heightPx : undefined) ?? 60}
        startFrame={Math.round(((typeof story.logo === "object" ? story.logo?.startSeconds : undefined) ?? 0.5) * fps)}
      />
    </AbsoluteFill>
  );
};
