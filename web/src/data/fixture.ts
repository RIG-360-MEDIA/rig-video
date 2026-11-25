// DEV ONLY. A VO-only project built from a real clip-checker edit list (public/seed/media/vo/F9/edit.json,
// local media, not in git), for building the VO-only screens before the API serves them. store.ts imports this
// module only under import.meta.env.DEV, so production builds leave it out; the project never reaches the API.
import type { BeatEdit, EditCandidate, EditCut, EditSource, Project, Section, StoryEdit } from "./types";
import { FIXTURE_ID } from "./store";

const DIR = "/seed/media/vo/F9/";

// The writer's own beats for this story (research_notes/vo_script_study/gemma/gemma_vo_fresh_v3.json, F9):
// edit.json carries the line but not the writer's picture hint and search.
const WRITER: Record<string, { picture: string; search: string }> = {
  B1: { picture: "Bulk carrier Miro G stuck in sand off coast", search: "Miro G ship grounded Landes" },
  B2: { picture: "Rafale SAR helicopter flying in storm", search: "Rafale SAR helicopter Cazaux" },
  B3: { picture: "Spanish rescue tugboat on heavy seas", search: "Spanish rescue tugboat Bilbao" },
  B4: { picture: "Miro G ship stuck on coastline", search: "Miro G ship Landes coast" },
};

interface RawCut {
  shot: number; video: string; start: number; end: number; secs: number; at: number; kind: string; fit: string; shows: string;
  title?: string; poster: string; clip?: string; fill?: boolean; swapped?: boolean; review?: string; repeat?: boolean;
  image?: string; url?: string; page?: string;
}
interface RawCand { n: number; video: string; start: number; end: number; kind: string; fit: string; shows: string; poster?: string; clip?: string; image?: string; url?: string; page?: string }
interface RawBeat { beat: string; text: string; secs: number; cuts: RawCut[]; fill: string[]; why: string; candidates: RawCand[] }
interface Raw { sid: string; headline: string; flow: string; beats: RawBeat[] }

const file = (f?: string) => (f ? DIR + f : undefined);

function source(x: RawCut | RawCand, titles: Map<string, string>): EditSource {
  if (x.video === "own") return { kind: "picture", url: x.url ?? x.image ?? "", page: x.page ?? "", title: ("title" in x && x.title) || x.shows };
  return { kind: "video", youtubeId: x.video, title: ("title" in x && x.title) || titles.get(x.video) || "", start: x.start, end: x.end };
}

/** edit.json (the checker's file) to the contract in types.ts. */
export function mapEdit(raw: Raw): StoryEdit {
  const titles = new Map(raw.beats.flatMap((b) => b.cuts.filter((c) => c.title).map((c) => [c.video, c.title!] as const)));
  const beats: BeatEdit[] = raw.beats.map((b) => ({
    sectionId: b.beat, secs: b.secs, notes: b.fill, why: b.why,
    cuts: b.cuts.map((c, i): EditCut => ({
      id: `${b.beat}-c${i}`, shot: c.shot, at: c.at, secs: c.secs, src: source(c, titles),
      kind: c.kind as EditCut["kind"], fit: c.fit as EditCut["fit"], shows: c.shows,
      poster: file(c.poster) ?? c.image ?? "", clip: file(c.clip),
      fill: c.fill, swapped: c.swapped, review: c.review, repeat: c.repeat,
    })),
    // the checker also lists the shots it ruled out (fit "no", no poster): they cannot be swapped in
    candidates: b.candidates.filter((c) => c.fit !== "no" && (c.poster || c.image)).map((c): EditCandidate => ({
      shot: c.n, src: source(c, titles), kind: c.kind, fit: c.fit, shows: c.shows, poster: file(c.poster) ?? c.image ?? "", clip: file(c.clip),
    })),
  }));
  return { state: "ready", flow: raw.flow, beats };
}

export async function buildFixture(): Promise<Project> {
  const r = await fetch(DIR + "edit.json");
  if (!r.ok) throw new Error("no fixture media");
  const raw: Raw = await r.json();
  const edit = mapEdit(raw);
  const beats: Section[] = raw.beats.map((b) => ({ id: b.beat, kind: "vo", text: b.text, ...WRITER[b.beat] }));
  const now = new Date().toISOString();
  return {
    id: FIXTURE_ID, headline: raw.headline, createdAt: "2026-11-20T09:00:00+05:30", updatedAt: now,
    source: { kind: "text", site: "Dev fixture: clip checker run on story F9", text: "France, 2026-11-20. " + raw.beats.map((b) => b.text).join(" ") },
    targetSeconds: Math.round(edit.beats.reduce((n, b) => n + b.secs, 0)),
    anchorId: "", tone: "Serious", stage: "review", format: "vo_only",
    versions: { anchor_vo: [], anchor_only: [], vo_only: beats },
    lt: { kicker: "", headline: "", subline: "" }, ticker: [], facts: [],
    visuals: Object.fromEntries(beats.map((b) => [b.id, { keywords: [], found: [], photos: [], uploads: [], maps: [], placed: [] }])),
    edit,
  };
}
