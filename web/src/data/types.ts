// The data contract between the studio frontend and its backend.
// The API (web/server/app.py) sends exactly these shapes, so the
// backend later only has to return the same JSON from /api/*.

export type Id = string;
export type Seconds = number;

export interface Workspace { id: Id; name: string; kind: "dnl" | "own"; picksFeed: boolean }
export interface User { id: Id; name: string; email: string; role: "admin" | "editor"; workspaceId: Id }

export interface Anchor {
  id: Id; name: string; gender: "male" | "female";
  face: string;            // portrait image
  frame: string;           // studio frame (anchor at the desk)
  voiceSample: string;     // short audio file
  wordsPerSecond: number;  // measured speaking pace, drives live timing
  regions: string[];
  offered: boolean;
}

/** A story the DNL selection chose for today (DNL workspace only). */
export interface Pick {
  id: Id; headline: string; deck: string; type: StoryType; place: string;
  source: string; url: string; publishedAt: string;
}
export type StoryType = "war_conflict" | "death_disaster" | "democracy" | "turmoil_unrest";

export type Format = "anchor_vo" | "anchor_only" | "vo_only";   // vo_only: 9:16, voice over real footage, no anchor on screen
export type Stage = "script" | "visuals" | "review" | "render" | "done";

export interface LowerThird { kicker: string; headline: string; subline: string }

export interface VoiceTake { id: Id; src: string; seconds: Seconds }
export interface SectionVoice {
  state: "waiting" | "making" | "ready" | "redoing";
  takes: VoiceTake[];
  pick: Id | null;          // take in use
  note?: string;            // what the user asked to change
}

export interface Section {
  id: Id; kind: "anchor" | "vo"; text: string;
  voice?: SectionVoice;     // exists once the script is approved
  picture?: string;         // vo_only beats: what should be on screen (the person can edit it)
  search?: string;          // vo_only beats: the footage search the writer chose for it
}

export interface Fact { label: string; value: string }

export interface Project {
  id: Id; headline: string; createdAt: string; updatedAt: string;
  source: { kind: "link" | "file" | "text"; url?: string; name?: string; site?: string; text: string };
  targetSeconds: Seconds;
  anchorId: Id;
  tone: string;
  stage: Stage;
  format: Format;
  /** Every version is kept; switching format only changes which one is shown. `vo_only` is present
   *  (an empty list until written) only when the server can write and run VO-only stories. */
  versions: Record<"anchor_vo" | "anchor_only", Section[]> & { vo_only?: Section[] };
  /** One lower third for the whole video, shown while the anchor is on camera. */
  lt: LowerThird;
  /** At least five lines; the ticker loops them along the bottom. */
  ticker: string[];
  facts: Fact[];
  visuals: Record<Id, SectionVisuals>;  // key: section id
  render?: RenderJob;
  videoId?: Id;                          // library item once done
  edit?: StoryEdit;                      // vo_only: the clip checker's edit list, changed by the person
  final?: FinalVideo;                    // the finished video (vo_only: made by the night render; anchor: the render's final.mp4)
  formatWhy?: { by: "auto" | "editor"; text: string; at: string; decided?: boolean };   // why the story has its type
  posts?: Partial<Record<Platform, Post>>;
}

/** VO only: the finished 9:16 video. `stale`: the edit or a voice changed since; a new one is being made. `low`: shots
 *  taken from the checker's 480p copy because YouTube refused the full-quality download. */
export interface FinalVideo {
  state: "building" | "ready" | "failed"; progress?: number; note?: string | null; stale?: boolean;
  video?: string; poster?: string; seconds?: Seconds; cuts?: number; low?: number; whole?: number; builtAt?: string;
}
export type Platform = "youtube";
/** YouTube: uploading (by itself after the render) -> awaiting (unlisted, "Awaiting approval") -> posting -> posted (public). */
export interface Post {
  state: "uploading" | "awaiting" | "posting" | "posted" | "failed"; title: string; description: string; videoId?: string; url?: string;
  error?: string; postedAt?: string; at?: string;
  autoAt?: string;          // anchor-only: goes public by itself then
  auto?: boolean;           // it did
}

// ---------- The edit (vo_only): which shots play under each beat, in what order and for how long ----------

export type EditSource =
  | { kind: "video"; youtubeId: string; title: string; start: Seconds; end: Seconds;
      shotEnd?: Seconds }   // where the shot ends in the source video: re-timing never stretches a cut past it (absent: no limit known)
  | { kind: "picture"; url: string; page: string; title: string };   // our own found picture

export interface EditCut {
  id: Id; shot: number;
  at: Seconds;              // story time it starts
  secs: Seconds;            // how long it plays
  src: EditSource;
  kind: "footage" | "speech" | "photo" | "post_or_document";
  fit: "exact" | "subject" | "topic";
  shows: string;            // what the checker saw in the shot
  sound?: string;           // the scene sound made for it ("" = none); unset on edits from before 2026-11-24
  poster: string; clip?: string;   // URLs
  fill?: boolean;           // added to fill the beat out
  swapped?: boolean;        // the review swapped it in
  review?: string;          // why the review flagged it
  repeat?: boolean;         // the shot also plays elsewhere in the story
  byUser?: boolean;         // the person put it here
}
export interface EditCandidate { shot: number; src: EditSource; kind: string; fit: string; shows: string; sound?: string; poster: string; clip?: string }
export interface BeatEdit {
  sectionId: Id; secs: Seconds;    // the beat's length the cuts must fill (its voice)
  cuts: EditCut[]; candidates: EditCandidate[];
  notes: string[];                 // the checker's notes: "story footage", "own picture", "1.2 s short", ...
  why: string;
}
export interface StoryEdit {
  state: "waiting" | "checking" | "ready" | "failed";
  progress?: number;               // 0..1 while checking
  note?: string;
  flow: string;                    // one sentence on how the edit reads
  beats: BeatEdit[];
}

// ---------- Visuals (shapes follow the footage repo's API, plus ours) ----------

export interface Keyword {
  id: Id; text: string; reason: string;
  state: "idle" | "queued" | "searching" | "done" | "error";
  progress?: string;
}

export type Flag = "logo" | "text" | "vertical" | "presenter";
/** What assembly does to a cut clip: a 10 % centre crop (removes corner logos), or blur fill for vertical video. */
export type Treatment = "crop" | "blur_fill";

export interface Moment {
  start: Seconds; end: Seconds; label: string; description: string;
  fit: string; score: number; estimated: boolean;
  clip?: string;            // cut file, when downloaded
  cutFailed?: boolean;      // the download or cut failed; this moment cannot be used
  poster?: string;          // still from the cut file, else the YouTube frame nearest the moment
  posterNear?: boolean;     // poster is that nearest YouTube frame, not from our cut
  flags?: Flag[];           // what our shot check found in this moment
  treat?: { kind: Treatment; preview: string };  // the one treatment assembly applies, once cut
  custom?: boolean;         // a range the person marked on the whole video
}

export interface FoundVideo {
  id: Id; keywordId: Id; youtubeId: string; title: string; channel: string;
  publishedAt: string | null; duration: Seconds; thumb: string;
  relevance: number;        // 0-100 fit score from the repo
  verdict: string; hasCaptions: boolean;
  moments: Moment[];
  flags: Flag[];
  source?: string;          // the whole video, downloaded after the search: it plays in the viewer and clips are cut from it
}

export interface Photo { id: Id; src: string; caption: string; credit: string; source: string }
export interface Upload { id: Id; src: string; kind: "video" | "image"; name: string; seconds?: Seconds }
export interface MapItem { id: Id; src: string; title: string }

export interface PlacedItem {
  id: Id;
  ref: { kind: "moment"; videoId: Id; moment: number } | { kind: "photo" | "upload" | "map"; id: Id };
  in: Seconds; out: Seconds;   // for stills: 0..seconds shown
  muted: boolean;
  useTreated: boolean;
}

export interface SectionVisuals {
  keywords: Keyword[];
  found: FoundVideo[];
  photos: Photo[];
  uploads: Upload[];
  maps: MapItem[];
  placed: PlacedItem[];        // play order
}

// ---------- Render queue and library ----------

export interface RenderJob {
  projectId: Id;
  state: "queued" | "rendering" | "assembling" | "held" | "done" | "failed";
  queuePosition: number;       // 0 = on the machine now
  waitNote?: string;           // queued outside the night render window: "Starts at 00:00 IST"
  percent: number;
  etaIso: string | null;
  heldReason?: string;
}

export interface LibraryItem {
  id: Id; projectId: Id | null; headline: string; anchorId: Id;
  madeAt: string; seconds: Seconds; video: string; poster: string;
  origin: "studio" | "daily";
}

