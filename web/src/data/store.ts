// App state, kept in step with the RIG-Video API (web/server/app.py). Edits apply here at once and are saved to the
// server a moment later; the machine's work (writing, voices, footage, renders) arrives by polling /api/desk.
import { useSyncExternalStore } from "react";
import { produce } from "immer";
import type {
  Anchor, Format, Id, LibraryItem, LowerThird, PlacedItem, Project, RenderJob, Section,
  SectionVisuals, User, Workspace, Pick, Upload, MapItem, BeatEdit, EditCandidate, EditCut, EditSource, StoryEdit, Platform,
} from "./types";

export interface Defaults { format: Format; length: number; captions: "file" | "burned" | "none"; aiLabel: boolean; outro: boolean }
export interface Toast { id: number; text: string; tone?: "ok" | "bad" }
export interface Job { kind: "write" | "search" | "voice" | "check"; progress: number; note: string; failed?: boolean; parts?: Record<Id, string> }   // parts: what the search is doing on each part

export interface State {
  ready: boolean;
  signedIn: boolean;
  user: User | null;
  workspace: Workspace | null;
  picks: Pick[];
  hiddenPicks: Id[];
  anchors: Anchor[];
  projects: Record<Id, Project>;
  order: Id[];
  queue: RenderJob[];
  library: LibraryItem[];
  defaults: Defaults;
  formats: Format[];        // what this server can make; VO only appears once the API lists it
  jobs: Record<Id, Job>;
  toasts: Toast[];
}

let state: State = {
  ready: false, signedIn: false, user: null, workspace: null, picks: [], hiddenPicks: [],
  anchors: [], projects: {}, order: [], queue: [], library: [],
  defaults: { format: "anchor_vo", length: 60, captions: "file", aiLabel: true, outro: true },
  formats: ["anchor_vo", "anchor_only"],
  jobs: {}, toasts: [],
};
const subs = new Set<() => void>();
const emit = () => subs.forEach((f) => f());

function set(fn: (d: State) => void) {
  state = produce(state, fn);
  emit();
}

export function useStore<T>(sel: (s: State) => T): T {
  return useSyncExternalStore((f) => { subs.add(f); return () => subs.delete(f); }, () => sel(state));
}
export const getState = () => state;

// ---------------------------------------------------------------- server

class ApiError extends Error {}

async function api<T>(path: string, init?: RequestInit & { json?: unknown }): Promise<T> {
  const r = await fetch(path, {
    ...init, credentials: "same-origin",
    headers: init?.json !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: init?.json !== undefined ? JSON.stringify(init.json) : init?.body,
  });
  if (r.status === 401 && path !== "/api/login") { set((d) => { d.signedIn = false; }); throw new ApiError("Sign in again."); }
  if (!r.ok) {
    let msg = `Something went wrong (${r.status}). Try again.`;
    try { const j = await r.json(); if (typeof j.detail === "string") msg = j.detail; } catch { /* not JSON */ }
    throw new ApiError(msg);
  }
  return r.json();
}
const post = <T,>(path: string, json: unknown = {}) => api<T>(path, { method: "POST", json });
export type Place = { name: string; lat: number; lon: number; iso: string };
/** Map maker places: by name prefix, or the ones a script names. */
export const findPlaces = (by: { q?: string; text?: string }) =>
  api<Place[]>(`/api/places?${new URLSearchParams(by as Record<string, string>)}`).catch(() => [] as Place[]);
/** Run an action; its error becomes a toast. */
async function act<T>(p: Promise<T>): Promise<T | null> {
  try { return await p; } catch (e) { toast((e as Error).message, "bad"); return null; }
}

interface Desk {
  user: User; workspace: Workspace; picks: Pick[]; hiddenPicks: Id[]; defaults: Defaults;
  anchors: Anchor[]; projects: Project[]; jobs: Record<Id, Job>; queue: RenderJob[]; library: LibraryItem[];
  formats?: Format[];       // absent: an API from before VO only
}

// Edits not yet saved: the project keeps its local words and choices over what a poll brings back.
const dirty = new Set<Id>();
const saveTimers: Record<Id, number> = {};
const editNo: Record<Id, number> = {};
const removed: Record<Id, Set<Id>> = {};
const forget = (id: Id, x: Id) => { (removed[id] ??= new Set()).add(x); };

/** The fields the person owns (as app.py's save() merges them), from `mine` over the server's copy. */
function overlay(server: Project, mine: Project): Project {
  return produce(server, (d) => {
    Object.assign(d, { headline: mine.headline, targetSeconds: mine.targetSeconds, anchorId: mine.anchorId, tone: mine.tone,
      format: mine.format, facts: mine.facts, ticker: mine.ticker, lt: mine.lt });
    if (["script", "visuals", "review"].includes(mine.stage) && ["script", "visuals", "review"].includes(server.stage)) d.stage = mine.stage;
    for (const f of Object.keys(mine.versions) as Format[]) {
      const srv = new Map((server.versions[f] ?? []).map((s) => [s.id, s]));
      d.versions[f] = (mine.versions[f] ?? []).map((s) => {
        const o = srv.get(s.id);
        const voice = o?.voice ? { ...o.voice, pick: s.voice?.pick && o.voice.takes.some((t) => t.id === s.voice!.pick) ? s.voice.pick : o.voice.pick } : s.voice;
        return { ...s, voice: o && (o.text !== s.text || o.kind !== s.kind) && voice ? { ...voice, state: "making" as const } : voice };
      });
    }
    for (const [sid, v] of Object.entries(mine.visuals)) {
      const sv = d.visuals[sid];
      if (!sv) continue;
      sv.placed = v.placed;
      const gone = removed[server.id] ?? new Set<Id>();       // what the person deleted; anything else the server added stays
      sv.keywords = sv.keywords.filter((x) => !gone.has(x.id));
      sv.uploads = sv.uploads.filter((x) => !gone.has(x.id));
      sv.maps = sv.maps.filter((x) => !gone.has(x.id));
      sv.found = sv.found.filter((f) => sv.keywords.some((k) => k.id === f.keywordId));
    }
    // the person owns the cuts; the server owns the check (a new check replaces them)
    if (mine.edit?.state === "ready" && server.edit?.state === "ready") d.edit = { ...server.edit, beats: mine.edit.beats };
  });
}

function body(p: Project) {
  return {
    headline: p.headline, targetSeconds: p.targetSeconds, anchorId: p.anchorId, tone: p.tone, format: p.format,
    facts: p.facts, ticker: p.ticker, lt: p.lt, stage: p.stage, versions: p.versions,
    visuals: Object.fromEntries(Object.entries(p.visuals).map(([sid, v]) => [sid, {
      placed: v.placed, keywords: v.keywords.map((k) => ({ id: k.id })), uploads: v.uploads.map((u) => ({ id: u.id })), maps: v.maps.map((m) => ({ id: m.id })),
    }])),
    ...(p.edit ? { edit: { beats: p.edit.beats.map((b) => ({ sectionId: b.sectionId, cuts: b.cuts })) } } : {}),
  };
}

function scheduleSave(id: Id) {
  dirty.add(id);
  editNo[id] = (editNo[id] ?? 0) + 1;
  clearTimeout(saveTimers[id]);
  saveTimers[id] = window.setTimeout(() => void saveNow(id), 600);
}

async function saveNow(id: Id) {
  const p = state.projects[id];
  if (!p) return;
  const n = editNo[id];
  try {
    const saved = await api<Project>(`/api/projects/${id}`, { method: "PUT", json: body(p) });
    const edited = editNo[id] !== n;
    set((d) => { d.projects[id] = edited ? overlay(saved, d.projects[id]) : saved; });
    if (!edited) { dirty.delete(id); delete removed[id]; }
  } catch (e) {
    toast(`Not saved: ${(e as Error).message}`, "bad");
    saveTimers[id] = window.setTimeout(() => void saveNow(id), 5000);
  }
}

/** Save pending edits now (before an action that reads them on the server). */
async function flush(id: Id) {
  if (!dirty.has(id)) return;
  clearTimeout(saveTimers[id]);
  await saveNow(id);
}

const failedSeen = new Set<string>();
function apply(desk: Desk) {
  set((d) => {
    d.ready = true; d.signedIn = true; d.user = desk.user; d.workspace = desk.workspace;
    d.picks = desk.picks; d.hiddenPicks = desk.hiddenPicks; d.defaults = desk.defaults;
    d.anchors = desk.anchors; d.queue = desk.queue; d.library = desk.library; d.jobs = desk.jobs;
    d.formats = desk.formats ?? ["anchor_vo", "anchor_only"];
    d.projects = Object.fromEntries(desk.projects.map((p) => [p.id, dirty.has(p.id) && d.projects[p.id] ? overlay(p, d.projects[p.id]) : p]));
    d.order = desk.projects.map((p) => p.id);
  });
  for (const [id, j] of Object.entries(desk.jobs)) {
    const key = `${id}:${j.kind}:${j.note}`;
    if (j.failed && !failedSeen.has(key)) { failedSeen.add(key); toast(j.note, "bad"); }
  }
  notifyRendered(desk.library);
}

let pollTimer = 0;
async function poll() {
  clearTimeout(pollTimer);
  if (state.signedIn && document.visibilityState === "visible") {
    try { apply(await api<Desk>("/api/desk")); } catch { /* signed out or offline: the next tick retries */ }
  }
  if (state.signedIn) pollTimer = window.setTimeout(() => void poll(), 3000);
}
document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible" && state.signedIn) void poll(); });

export async function boot() {
  if (state.ready) return;
  try {
    apply(await api<Desk>("/api/desk"));
    void poll();
  } catch {
    set((d) => { d.ready = true; d.signedIn = false; });
  }
}

// ---------------------------------------------------------------- toasts

let toastId = 0;
export function toast(text: string, tone?: Toast["tone"]) {
  const id = ++toastId;
  set((d) => { d.toasts.push({ id, text, tone }); });
  setTimeout(() => set((d) => { d.toasts = d.toasts.filter((t) => t.id !== id); }), 3600);
}

// ---------------------------------------------------------------- auth

export async function signIn(email: string, password: string): Promise<string | null> {
  try {
    await post("/api/login", { email, password });
    apply(await api<Desk>("/api/desk"));
    void poll();
    return null;
  } catch (e) { return (e as Error).message; }
}
export function signOut() {
  void post("/api/logout");
  set((d) => { d.signedIn = false; d.projects = {}; d.order = []; d.library = []; d.queue = []; d.picks = []; });
}

// ---------------------------------------------------------------- timing

export const wordsOf = (t: string) => (t.trim() ? t.trim().split(/\s+/).length : 0);
export function anchorOf(id: Id) { return state.anchors.find((a) => a.id === id); }
export function sectionSeconds(s: Section, anchorId: Id): { sec: number; measured: boolean } {
  const take = s.voice?.takes.find((t) => t.id === s.voice?.pick);
  if (take && s.voice?.state === "ready") return { sec: take.seconds, measured: true };
  const wps = anchorOf(anchorId)?.wordsPerSecond ?? 2.5;
  return { sec: wordsOf(s.text) / wps, measured: false };
}
export function sections(p: Project): Section[] { return p.versions[p.format] ?? []; }
export function totalSeconds(p: Project) { return sections(p).reduce((n, s) => n + sectionSeconds(s, p.anchorId).sec, 0); }

export function parseLength(raw: string): number | null {
  const t = raw.trim().toLowerCase();
  if (!t) return null;
  let m = t.match(/^(\d+):(\d{1,2})$/); if (m) return +m[1] * 60 + +m[2];
  m = t.match(/^(\d+(?:\.\d+)?)\s*(m|min|mins|minute|minutes)$/); if (m) return Math.round(+m[1] * 60);
  m = t.match(/^(\d+)\s*(s|sec|secs|second|seconds)?$/); if (m) return +m[1];
  m = t.match(/^(\d+)\s*m(?:in)?\s*(\d+)\s*s(?:ec)?$/); if (m) return +m[1] * 60 + +m[2];
  return null;
}

// placed seconds per section vs what it needs
export function fillOf(p: Project, s: Section) {
  if (p.format === "vo_only") {   // VO only: the edit's cuts against the beat
    const b = beatOf(p, s.id);
    const need = b?.secs ?? sectionSeconds(s, p.anchorId).sec; const have = b ? cutsSecs(b) : 0;
    return { need, have, full: have >= need - SHORT, behind: false };
  }
  const need = sectionSeconds(s, p.anchorId).sec;
  const pool = storyPool(p, s.id).found;
  const placed = (p.visuals[s.id]?.placed ?? []).filter((x) => x.ref.kind !== "moment" || !pool.find((f) => f.id === (x.ref as { videoId: Id }).videoId)?.moments[x.ref.moment]?.cutFailed);
  const have = placed.reduce((n, x) => n + (x.out - x.in), 0);
  if (s.kind === "anchor") return { need, have: placed.length ? need : 0, full: !!placed.length, behind: true };
  return { need, have, full: have >= need - 0.25, behind: false };
}

// ---------------------------------------------------------------- projects

const uid = (p = "x") => p + Math.random().toString(36).slice(2, 8);

function mutate(id: Id, fn: (p: Project) => void) {
  if (!state.projects[id]) return;
  set((d) => {
    const p = d.projects[id]; fn(p);
    if (p.stage !== "script") for (const s of sections(p)) p.visuals[s.id] ??= { keywords: [], found: [], photos: [], uploads: [], maps: [], placed: [] };   // parts added after approval
  });
  scheduleSave(id);
}

/** A new story: the server writes the script; resolves to its id (null when refused). */
export async function createProject(input: { kind: "link" | "file" | "text" | "pick"; text: string; name?: string; url?: string; pickId?: Id; seconds: number; format?: Format; file?: File }): Promise<Id | null> {
  let p: Project | null;
  if (input.file && !input.text.trim()) {
    const fd = new FormData();
    fd.append("file", input.file); fd.append("seconds", String(input.seconds));
    if (input.format) fd.append("format", input.format);
    p = await act(api<Project>("/api/projects/file", { method: "POST", body: fd }));
  } else {
    const { file: _f, ...rest } = input;
    p = await act(post<Project>("/api/projects", rest));
  }
  if (!p) return null;
  set((d) => {
    d.projects[p.id] = p; d.order.unshift(p.id);
    d.jobs[p.id] = { kind: "write", progress: 0, note: "Starting" };
    if (input.pickId) d.picks = d.picks.filter((x) => x.id !== input.pickId);   // the server drops used picks for everyone
  });
  return p.id;
}

export const setFormat = (id: Id, f: Format) => mutate(id, (p) => { p.format = f; });
export const setTarget = (id: Id, s: number) => mutate(id, (p) => { p.targetSeconds = s; });
export const setAnchor = (id: Id, a: Id) => mutate(id, (p) => {
  p.anchorId = a;
  if (p.stage !== "script") sections(p).forEach((s) => { if (s.voice) s.voice = { state: "making", takes: [], pick: null }; });
});
export const setFact = (id: Id, i: number, value: string) => mutate(id, (p) => { p.facts[i].value = value; });
export const setTicker = (id: Id, lines: string[]) => mutate(id, (p) => { p.ticker = lines; });
export const setHeadline = (id: Id, h: string) => mutate(id, (p) => { p.headline = h; });

export function editSection(id: Id, sid: Id, patch: Partial<Section>) {
  mutate(id, (p) => {
    const s = sections(p).find((x) => x.id === sid);
    if (!s) return;
    Object.assign(s, patch);
    if (patch.text !== undefined && s.voice && p.stage !== "script") s.voice.state = "making";
  });
}
export function setLT(id: Id, lt: Partial<LowerThird>) { mutate(id, (p) => { p.lt = { ...p.lt, ...lt }; }); }
export const MIN_TICKER = 5;
export function reorderSections(id: Id, ids: Id[]) {
  mutate(id, (p) => { const by = new Map(sections(p).map((s) => [s.id, s])); p.versions[p.format] = ids.map((i) => by.get(i)!).filter(Boolean); });
}
export function addSection(id: Id, kind: "anchor" | "vo", after?: Id) {
  mutate(id, (p) => {
    const list = sections(p);
    const s: Section = { id: uid(kind === "anchor" ? "a" : "v"), kind, text: "" };
    const at = after ? list.findIndex((x) => x.id === after) + 1 : list.length;
    list.splice(at, 0, s);
  });
}
export function deleteSection(id: Id, sid: Id) { mutate(id, (p) => { p.versions[p.format] = sections(p).filter((s) => s.id !== sid); }); }
export function turnInto(id: Id, sid: Id, kind: "anchor" | "vo") {
  mutate(id, (p) => {
    const s = sections(p).find((x) => x.id === sid); if (!s) return;
    s.kind = kind;
  });
}
export function mergeNext(id: Id, sid: Id) {
  mutate(id, (p) => {
    const l = sections(p); const i = l.findIndex((s) => s.id === sid);
    if (i < 0 || i >= l.length - 1) return;
    l[i].text = `${l[i].text} ${l[i + 1].text}`.trim(); l.splice(i + 1, 1);
  });
}
export function splitAt(id: Id, sid: Id, at: number) {
  mutate(id, (p) => {
    const l = sections(p); const i = l.findIndex((s) => s.id === sid); if (i < 0) return;
    const s = l[i]; const a = s.text.slice(0, at).trim(); const b = s.text.slice(at).trim();
    if (!a || !b) return;
    s.text = a; l.splice(i + 1, 0, { id: uid(s.kind === "anchor" ? "a" : "v"), kind: s.kind, text: b });
  });
}

// AI rewrite on the script model: proposals the person keeps or rejects per section.
export type RewriteAsk = { scope: "all" | Id; chips: string[]; note: string };
export async function proposeRewrite(id: Id, ask: RewriteAsk): Promise<Record<Id, string>> {
  await flush(id);
  return (await act(post<Record<Id, string>>(`/api/projects/${id}/rewrite`, ask))) ?? {};
}

/** Replace a project with the server's copy after an action (keeping edits made meanwhile). */
function took(p: Project | null) {
  if (p) set((d) => { d.projects[p.id] = dirty.has(p.id) && d.projects[p.id] ? overlay(p, d.projects[p.id]) : p; });
}

export function approveScript(id: Id) {
  set((d) => {
    const p = d.projects[id]; p.stage = "visuals";
    if (p.format === "vo_only") p.edit ??= { state: "waiting", flow: "", beats: [] };   // the clip check runs after the footage search
    sections(p).forEach((s) => {
      if (!s.voice || s.voice.state !== "ready") s.voice = { state: "making", takes: [], pick: null };
      if (!p.visuals[s.id]) p.visuals[s.id] = { keywords: [], found: [], photos: [], uploads: [], maps: [], placed: [] };
    });
  });
  void flush(id).then(() => act(post<Project>(`/api/projects/${id}/approve`)).then(took));
}

export function voiceProgress(p: Project) {
  const l = sections(p).filter((s) => s.voice);
  if (!l.length) return null;
  const done = l.filter((s) => s.voice!.state === "ready").length;
  return { done, total: l.length, busy: done < l.length };
}
export const pickTake = (id: Id, sid: Id, take: Id) => mutate(id, (p) => { const s = sections(p).find((x) => x.id === sid); if (s?.voice) s.voice.pick = take; });
export function revoice(id: Id, sid: Id, note: string) {
  set((d) => { const s = sections(d.projects[id]).find((x) => x.id === sid); if (s?.voice) { s.voice.state = "redoing"; s.voice.note = note; } });
  void flush(id).then(() => act(post<Project>(`/api/projects/${id}/revoice`, { sid, note })).then(took));
}
/** Run a job again; `sid` narrows the clip check to one beat. */
export function retryJob(id: Id, job: Job["kind"], sid?: Id) {
  set((d) => {
    d.jobs[id] = { kind: job, progress: 0, note: "Starting again", ...(sid ? { parts: { [sid]: "Checking again" } } : {}) };
    const e = d.projects[id]?.edit; if (job === "check" && !sid && e) { e.state = "checking"; e.progress = 0; }
  });
  void act(post<Project>(`/api/projects/${id}/retry`, sid ? { job, sid } : { job })).then(took);
}

// ---------------------------------------------------------------- the edit (vo_only): the clip checker's edit list, as the person changes it

const SHORT = 0.25;   // seconds a beat may be short and still count as filled
export const beatOf = (p: Project, sid: Id) => p.edit?.beats.find((b) => b.sectionId === sid);
export const cutsSecs = (b: BeatEdit) => b.cuts.reduce((n, c) => n + c.secs, 0);
/** How many seconds the beat's pictures run out before its line ends (0 when filled). */
export function shortBy(b: BeatEdit) { const d = b.secs - cutsSecs(b); return d > SHORT ? d : 0; }
const roomOf = (s: EditSource) => (s.kind === "video" ? (s.shotEnd ?? s.end) - s.start : Infinity);

/** Stretch or shrink the cuts, in proportion, to fill the beat. A video cut never runs past the end of its shot. */
export function retime(b: BeatEdit) {
  const room = (c: EditCut) => (c.src.kind === "video" && c.src.shotEnd !== undefined ? Math.max(c.secs, c.src.shotEnd - c.src.start) : Infinity);
  let left = b.secs; let free = [...b.cuts];
  while (free.length && left > 0) {      // water-fill: the cuts that hit their shot's end hand the rest to the others
    const k = left / free.reduce((n, c) => n + c.secs, 0);
    const capped = free.filter((c) => c.secs * k > room(c));
    if (!capped.length) { free.forEach((c) => { c.secs *= k; }); break; }
    capped.forEach((c) => { c.secs = room(c); left -= c.secs; });
    free = free.filter((c) => !capped.includes(c));
  }
  for (const c of b.cuts) { c.secs = Math.round(c.secs * 100) / 100; if (c.src.kind === "video") c.src.end = Math.round((c.src.start + c.secs) * 100) / 100; }
}
/** Story times follow the beat order and the cut lengths. */
function restamp(e: StoryEdit) {
  let t = 0;
  for (const b of e.beats) { let a = t; for (const c of b.cuts) { c.at = Math.round(a * 100) / 100; a += c.secs; } t += b.secs; }
}
/** The index of the cut that already plays the same stretch of the same video (or the same picture) as a candidate, or -1. */
export function usedAs(b: BeatEdit, c: EditCandidate): number {
  return b.cuts.findIndex((x) => x.src.kind === "video" && c.src.kind === "video"
    ? x.src.youtubeId === c.src.youtubeId && x.src.start < c.src.end && c.src.start < x.src.end
    : x.src.kind === "picture" && c.src.kind === "picture" && x.src.url === c.src.url);
}
const CUT_KINDS: EditCut["kind"][] = ["footage", "speech", "photo", "post_or_document"];
const FITS: EditCut["fit"][] = ["exact", "subject", "topic"];
function cutFrom(c: EditCandidate, want: number): EditCut {
  const secs = Math.round(Math.min(want, roomOf(c.src)) * 100) / 100;
  const src: EditSource = c.src.kind === "video" ? { ...c.src, end: c.src.start + secs, shotEnd: c.src.shotEnd ?? c.src.end } : { ...c.src };
  return { id: uid("c"), shot: c.shot, at: 0, secs, src, shows: c.shows, sound: c.sound ?? "", poster: c.poster, clip: c.clip, byUser: true,
    kind: CUT_KINDS.find((k) => k === c.kind) ?? "footage", fit: FITS.find((f) => f === c.fit) ?? "topic" };
}
function editBeat(id: Id, sid: Id, fn: (b: BeatEdit) => void) {
  mutate(id, (p) => { const b = beatOf(p, sid); if (!b || !p.edit) return; fn(b); restamp(p.edit); });
}
/** Take a cut out; the others stretch to fill the beat. */
export const removeCut = (id: Id, sid: Id, cid: Id) => editBeat(id, sid, (b) => { b.cuts = b.cuts.filter((c) => c.id !== cid); if (shortBy(b)) retime(b); });
export const moveCuts = (id: Id, sid: Id, ids: Id[]) => editBeat(id, sid, (b) => { const by = new Map(b.cuts.map((c) => [c.id, c])); b.cuts = ids.map((i) => by.get(i)!).filter(Boolean); });
/** Put a candidate in a cut's place for the same seconds (as far as its shot runs). */
export const swapCut = (id: Id, sid: Id, cid: Id, cand: EditCandidate) => editBeat(id, sid, (b) => {
  const i = b.cuts.findIndex((c) => c.id === cid); if (i < 0) return;
  b.cuts[i] = { ...cutFrom(cand, b.cuts[i].secs), id: b.cuts[i].id };   // same id: the slot stays selected
  if (shortBy(b)) retime(b);
});
/** Add a candidate at the end of a short beat. It gets at least 2 s (no flash cuts); then every cut is re-timed to fill the beat. */
export const addCut = (id: Id, sid: Id, cand: EditCandidate) => editBeat(id, sid, (b) => { b.cuts.push(cutFrom(cand, Math.max(shortBy(b), 2))); retime(b); });
export const checkAgain = (id: Id, sid?: Id) => retryJob(id, "check", sid);
/** The scene sound made for a cut ("" = none): the checker's suggestion, the editor's word. */
export const setCutSound = (id: Id, sid: Id, cid: Id, sound: string) => editBeat(id, sid, (b) => {
  const c = b.cuts.find((x) => x.id === cid); if (c) c.sound = sound.slice(0, 80);
});

// ---------------------------------------------------------------- footage keywords (the footage repo, via the server)

export function addKeyword(id: Id, sid: Id, text: string) {
  if (state.projects[id]?.visuals[sid]?.keywords.some((k) => k.text.toLowerCase() === text.toLowerCase())) { toast("That keyword is already searched", "bad"); return; }
  void flush(id).then(() => act(post<Project>(`/api/projects/${id}/keywords`, { sid, text })).then(took));
}
export const removeKeyword = (id: Id, sid: Id, kid: Id) => mutate(id, (p) => {
  forget(id, kid);
  const v = p.visuals[sid]; v.keywords = v.keywords.filter((k) => k.id !== kid); v.found = v.found.filter((f) => f.keywordId !== kid);
});
export function researchKeyword(id: Id, sid: Id, kid: Id) {
  set((d) => { const k = d.projects[id].visuals[sid].keywords.find((x) => x.id === kid); if (k) { k.state = "queued"; k.progress = "Searching again"; } });
  void act(post<Project>(`/api/projects/${id}/keywords/${kid}/research`, { sid })).then(took);
}

// ---------------------------------------------------------------- visuals: placing, uploads, maps

/** A range marked on a whole found video becomes one of its moments (the same one when the range matches); its index. */
export async function addMoment(id: Id, videoId: Id, start: number, end: number): Promise<number | null> {
  const r = await act(post<{ moment: number; project: Project }>(`/api/projects/${id}/moments`, { videoId, start, end }));
  if (!r) return null;
  took(r.project);
  return r.moment;
}

export function place(id: Id, sid: Id, item: Omit<PlacedItem, "id">) {
  mutate(id, (p) => { p.visuals[sid].placed.push({ ...item, id: uid("p") }); });
}
export const unplace = (id: Id, sid: Id, pid: Id) => mutate(id, (p) => { p.visuals[sid].placed = p.visuals[sid].placed.filter((x) => x.id !== pid); });
export const updatePlaced = (id: Id, sid: Id, pid: Id, patch: Partial<PlacedItem>) =>
  mutate(id, (p) => { const x = p.visuals[sid].placed.find((y) => y.id === pid); if (x) Object.assign(x, patch); });
export const reorderPlaced = (id: Id, sid: Id, ids: Id[]) =>
  mutate(id, (p) => { const by = new Map(p.visuals[sid].placed.map((x) => [x.id, x])); p.visuals[sid].placed = ids.map((i) => by.get(i)!).filter(Boolean); });

async function sendFile<T>(path: string, fields: Record<string, string | Blob>, name?: string): Promise<T | null> {
  const fd = new FormData();
  for (const [k, v] of Object.entries(fields)) { if (v instanceof Blob) fd.append(k, v, name); else fd.append(k, v); }
  return act(api<T>(path, { method: "POST", body: fd }));
}
export async function addUpload(id: Id, sid: Id, file: File) {
  const u = await sendFile<Upload>(`/api/projects/${id}/uploads`, { sid, file }, file.name);
  if (u) set((d) => { d.projects[id].visuals[sid].uploads.push(u); });
  return u;
}
export const removeUpload = (id: Id, sid: Id, uidv: Id) => mutate(id, (p) => {
  forget(id, uidv);
  const v = p.visuals[sid]; v.uploads = v.uploads.filter((u) => u.id !== uidv);
  v.placed = v.placed.filter((x) => !(x.ref.kind === "upload" && x.ref.id === uidv));
});
export const removeMap = (id: Id, sid: Id, mid: Id) => mutate(id, (p) => {
  forget(id, mid);
  const v = p.visuals[sid]; v.maps = v.maps.filter((m) => m.id !== mid);
  v.placed = v.placed.filter((x) => !(x.ref.kind === "map" && x.ref.id === mid));
});
/** A map made in the browser (a JPEG data URL) is stored on the server like an upload. */
export async function addMap(id: Id, sid: Id, m: { src: string; title: string }) {
  const blob = await (await fetch(m.src)).blob();
  const made = await sendFile<MapItem>(`/api/projects/${id}/maps`, { sid, title: m.title, file: blob }, "map.jpg");
  if (made) set((d) => { d.projects[id].visuals[sid].maps.push(made); });
  return made;
}

export function continueToReview(id: Id) { mutate(id, (p) => { p.stage = "review"; }); }
export const setStage = (id: Id, stage: Project["stage"]) => mutate(id, (p) => { p.stage = stage; });

// ---------------------------------------------------------------- render queue (one render at a time on the GPU)

export function sendToRender(id: Id, extras: { outro: boolean }) {
  void flush(id).then(() => act(post<Project>(`/api/projects/${id}/render`, extras)).then(took)).then(() => poll());
}
// ---------------------------------------------------------------- VO only: the final video and posting it

/** Make the final video again (shots from the 480p copy are downloaded again). */
export function remakeFinal(id: Id) {
  set((d) => { const p = d.projects[id]; if (p) p.final = { ...(p.final ?? {}), state: "building", progress: 0, note: "Starting" }; });
  void act(post<Project>(`/api/projects/${id}/final`)).then(took);
}
export const postDefaults = (id: Id) => api<{ platforms: Platform[]; title: string; description: string }>(`/api/projects/${id}/post`);
export function postVideo(id: Id, platform: Platform, title: string, description: string) {
  set((d) => { const p = d.projects[id]; if (p) p.posts = { ...(p.posts ?? {}), [platform]: { state: "posting", title, description } }; });
  void act(post<Project>(`/api/projects/${id}/post`, { platform, title, description })).then(took).then(() => poll());
}
/** Footage page: make the story the other type (a script for it is written and approved by itself if there is none). */
export function switchFormat(id: Id, format: "vo_only" | "anchor_vo") {
  void flush(id).then(() => act(post<Project>(`/api/projects/${id}/switch`, { format }))).then(took).then(() => poll());
}
/** Footage page Continue: queue the render (both types). Renders run only in the night window. */
export function queueRender(id: Id) {
  const p = state.projects[id];
  sendToRender(id, { outro: p?.format !== "vo_only" && state.defaults.outro });
  toast("Queued for tonight's render (00:00–07:00 IST)", "ok");
}
export async function postAll(ids: Id[]) {
  const r = await act(post<{ posted: Id[]; skipped: Record<Id, string> }>("/api/post-all", { ids }));
  if (r) toast(`Uploading ${r.posted.length} ${r.posted.length === 1 ? "video" : "videos"} to YouTube${Object.keys(r.skipped).length ? `, ${Object.keys(r.skipped).length} skipped` : ""}.`, "ok");
  void poll();
}
/** Finished and not posted to YouTube yet (or its post failed). */
export const awaitingPost = (p: Project) => p.stage === "done" && p.final?.state === "ready" && !p.final.stale && !["posted", "posting", "uploading"].includes(p.posts?.youtube?.state ?? "");
export function cancelRender(id: Id) { void act(post<Project>(`/api/projects/${id}/cancel`)).then(took).then(() => poll()); }
export function moveUp(id: Id) { void act(post(`/api/projects/${id}/moveup`)).then(() => poll()); }

const libSeen = new Set<Id>();
let libPrimed = false;
function notifyRendered(lib: LibraryItem[]) {
  for (const it of lib) {
    if (libPrimed && !libSeen.has(it.id)) { toast(`Rendered: ${it.headline}`, "ok"); notify(`Rendered: ${it.headline}`); }
    libSeen.add(it.id);
  }
  libPrimed = true;
}

function notify(text: string) {
  try { if ("Notification" in window && Notification.permission === "granted") new Notification("RIG-Video", { body: text }); } catch { /* not allowed */ }
}

export function posterOf(p: Project): string {
  const cut = p.edit?.beats.find((b) => b.cuts.length)?.cuts[0];
  if (cut) return cut.poster;
  for (const s of sections(p)) {
    const v = p.visuals[s.id];
    for (const x of v?.placed ?? []) { const m = mediaOf(p, s.id, x); if (m?.poster) return m.poster; }
  }
  return anchorOf(p.anchorId)?.frame ?? "";
}

/** Every found video and photo in the story, own part first. Anchor parts get no search of their own and pick from these. */
export function storyPool(p: Project, sid?: Id) {
  const vs = [...(sid && p.visuals[sid] ? [p.visuals[sid]] : []), ...sections(p).map((s) => p.visuals[s.id]).filter(Boolean)];
  const seen = new Set<Id>();
  const uniq = <T extends { id: Id }>(xs: T[]) => xs.filter((x) => !seen.has(x.id) && (seen.add(x.id), true));
  return { found: uniq(vs.flatMap((v) => v.found)), photos: uniq(vs.flatMap((v) => v.photos)) };
}

/** Resolve a placed item to something playable/showable. */
export function mediaOf(p: Project, sid: Id, x: PlacedItem): { kind: "video" | "image"; src: string; poster?: string; label: string; code: string } | null {
  const v: SectionVisuals | undefined = p.visuals[sid];
  if (!v) return null;
  const idx = sections(p).findIndex((s) => s.id === sid) + 1;
  if (x.ref.kind === "moment") {
    const ref = x.ref;
    const pool = storyPool(p, sid).found;
    const f = pool.find((y) => y.id === ref.videoId); const m = f?.moments[ref.moment];
    if (!f || !m) return null;
    const fi = pool.indexOf(f) + 1;
    const src = m.clip ? (x.useTreated && m.treat ? m.treat.preview : m.clip) : undefined;
    return src ? { kind: "video", src, poster: m.poster ?? f.thumb, label: m.label, code: frameCode(idx, fi) }
      : { kind: "image", src: m.poster ?? f.thumb, label: m.label, code: frameCode(idx, fi) };
  }
  const ref = x.ref;
  const pool = ref.kind === "photo" ? storyPool(p, sid).photos : ref.kind === "upload" ? v.uploads : v.maps;
  const it = (pool as { id: Id; src: string }[]).find((y) => y.id === ref.id);
  if (!it) return null;
  const kind = ref.kind === "upload" && (it as Upload).kind === "video" ? "video" : "image";
  const label = "caption" in it ? (it as { caption: string }).caption : "title" in it ? (it as MapItem).title : (it as Upload).name;
  return { kind, src: it.src, label, code: `${ref.kind === "map" ? "MAP" : ref.kind === "upload" ? "UP" : "PH"}·${idx.toString().padStart(2, "0")}` };
}
export const frameCode = (roll: number, frame: number) => `R${roll.toString().padStart(2, "0")}·F${frame.toString().padStart(2, "0")}`;

// ---------------------------------------------------------------- picks, defaults, archive, library

function savePrefs() { void act(api("/api/prefs", { method: "PUT", json: { defaults: state.defaults, hiddenPicks: state.hiddenPicks } })); }
/** Remove a pick from the list: the server leaves it out and fills its place from the day's reserves. */
async function savePicks() { await act(api("/api/prefs", { method: "PUT", json: { defaults: state.defaults, hiddenPicks: state.hiddenPicks } })); void poll(); }
/** Desk: a story of your own into today's picks (a link, pasted text or a file). Before 08:00 it waits for the daily run;
 *  after, it starts at once. Returns the new story's id when it started, "" when it waits, null when refused. */
export async function addOwnPick(input: { text: string; file?: File }): Promise<Id | "" | null> {
  const t = input.text.trim();
  let r: { started: Id | null } | null;
  if (input.file && !t) {
    const fd = new FormData();
    fd.append("file", input.file);
    r = await act(api<{ started: Id | null }>("/api/picks/file", { method: "POST", body: fd }));
  } else {
    r = await act(post<{ started: Id | null }>("/api/picks", /^https?:\/\/\S+$/.test(t) ? { kind: "link", url: t } : { kind: "text", text: t }));
  }
  if (!r) return null;
  try { apply(await api<Desk>("/api/desk")); } catch { /* the next poll has it */ }
  return r.started ?? "";
}
export async function removeOwnPick(pid: Id) {
  if (!(await act(api<{ ok: boolean }>(`/api/picks/${pid}`, { method: "DELETE" })))) return;
  set((d) => { d.picks = d.picks.filter((x) => x.id !== pid); });
}
export const hidePick = (pid: Id) => { set((d) => { d.hiddenPicks.push(pid); }); void savePicks(); };
export const showHiddenPicks = () => { set((d) => { d.hiddenPicks = []; }); void savePicks(); };
export const setDefaults = (patch: Partial<Defaults>) => { set((d) => { Object.assign(d.defaults, patch); }); savePrefs(); };
/** A rendered story opened again: its video is dropped; back to Review (now: straight back into the render queue). */
export function remakeStory(id: Id, now: boolean) {
  return act(post<Project>(`/api/projects/${id}/remake`, { now })).then((p) => { took(p); void poll(); return !!p; });
}
export function archiveProject(id: Id) {
  void act(post(`/api/projects/${id}/archive`)).then((ok) => { if (ok) set((d) => { d.order = d.order.filter((x) => x !== id); }); });
}
export async function duplicateFromLibrary(itemId: Id): Promise<Id | null> {
  const p = await act(post<Project>(`/api/library/${itemId}/duplicate`));
  if (!p) return null;
  set((d) => { d.projects[p.id] = p; d.order.unshift(p.id); });
  return p.id;
}
