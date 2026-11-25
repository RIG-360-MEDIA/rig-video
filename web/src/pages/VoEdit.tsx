// Visuals for VO only: "the edit". The clip checker picks which shots play under each beat, in what order and
// for how long; here the editor plays, swaps, removes and reorders them. Each beat's bar is its seconds, each cut
// a segment as long as it plays.
import { useEffect, useMemo, useRef, useState, useSyncExternalStore, type ReactNode } from "react";
import { useNavigate } from "react-router";
import { AnimatePresence, motion } from "motion/react";
import { DndContext, closestCenter, PointerSensor, useSensor, useSensors, type DragEndEvent } from "@dnd-kit/core";
import { SortableContext, horizontalListSortingStrategy, useSortable, arrayMove } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import {
  ArrowClockwise, ArrowLeft, ArrowRight, ArrowSquareOut, ChatCircleText, CircleNotch, Eye, FileText, FilmSlate, FilmStrip,
  Image as ImageIcon, Lock, Microphone, Plus, SpeakerHigh, Trash, Warning, WarningCircle,
} from "@phosphor-icons/react";
import {
  useStore, sections, sectionSeconds, beatOf, cutsSecs, shortBy, usedAs, removeCut, moveCuts, swapCut, addCut, checkAgain, queueRender, setCutSound,
} from "@/data/store";
import { FormatSwitch } from "@/components/story";
import type { BeatEdit, EditCandidate, EditCut, EditSource, Project, Section } from "@/data/types";
import { Button, Empty, Ring, Segmented, Sheet, Skeleton, Tag, Tip, cx, mmss } from "@/components/ui";
import { Frame } from "@/components/frames";

type Sel = { sid: string; cid: string } | { sid: string; gap: true };
const EASE = [0.16, 1, 0.3, 1] as const;

export default function VoEdit({ p }: { p: Project }) {
  const nav = useNavigate();
  const list = sections(p);
  const e = p.edit;
  const locked = p.stage === "render" || p.stage === "done";
  const [sel, setSel] = useState<Sel | null>(null);
  const wide = useMedia("(min-width: 1024px)");
  const short = list.flatMap((s) => { const b = beatOf(p, s.id); return b && shortBy(b) ? [{ s, by: shortBy(b) }] : []; });
  const names = useMemo(() => Object.fromEntries(list.map((s, i) => [s.id, `Beat ${i + 1}`])), [list]);
  // a selection whose cut is gone (removed, re-checked) falls back to nothing
  const live = sel && beatOf(p, sel.sid) && ("gap" in sel ? shortBy(beatOf(p, sel.sid)!) > 0 : beatOf(p, sel.sid)!.cuts.some((c) => c.id === sel.cid)) ? sel : null;

  if (!list.length) return <Empty icon={<FilmStrip size={32} />} title="No beats yet">Write and approve the script first.</Empty>;
  const inspector = <Inspector p={p} sel={live} names={names} locked={locked} onSelect={setSel} />;
  const footer = <div className="space-y-3"><FormatSwitch p={p} locked={locked} />
    <ContinueGate p={p} short={short} names={names} locked={locked} onFix={(sid) => setSel({ sid, gap: true })}
      onGo={() => { queueRender(p.id); nav("/desk"); }} /></div>;
  return (
    <div className="mx-auto grid max-w-[1680px] grid-cols-1 lg:h-[calc(100vh-52px)] lg:grid-cols-[minmax(0,1fr)_380px]">
      <section className="min-w-0 px-4 pt-5 pb-12 sm:px-5 lg:overflow-auto lg:px-8" aria-labelledby="edit-h">
        <EditHead p={p} locked={locked} />
        {e && e.state !== "failed" && (
          <ol className="mt-6 space-y-3">
            {list.map((s, i) => <BeatRow key={s.id} p={p} s={s} n={i + 1} sel={live} onSelect={setSel} locked={locked} />)}
          </ol>
        )}
        {!wide && <div className="mt-6">{footer}</div>}
      </section>
      {wide ? (
        <aside className="flex min-h-0 flex-col border-l border-g4" aria-label="Selected cut">
          <div className="min-h-0 flex-1 overflow-auto">{inspector}</div>
          <div className="border-t border-g4 p-4">{footer}</div>
        </aside>
      ) : (
        <Sheet open={!!live} onOpenChange={(v) => { if (!v) setSel(null); }} title="The edit" width={420}>
          {inspector}
        </Sheet>
      )}
    </div>
  );
}

function useMedia(q: string) {
  return useSyncExternalStore((f) => { const m = matchMedia(q); m.addEventListener("change", f); return () => m.removeEventListener("change", f); }, () => matchMedia(q).matches);
}

// ------------------------------------------------------------------ top: how the edit reads, and where the check is

function EditHead({ p, locked }: { p: Project; locked: boolean }) {
  const e = p.edit;
  const job = useStore((s) => s.jobs[p.id]);
  const beats = e?.beats ?? [];
  const cuts = beats.flatMap((b) => b.cuts);
  const videos = new Set(cuts.flatMap((c) => (c.src.kind === "video" ? [c.src.youtubeId] : []))).size;
  const need = beats.reduce((n, b) => n + b.secs, 0);
  const have = beats.reduce((n, b) => n + Math.min(b.secs, cutsSecs(b)), 0);
  const checking = e?.state === "checking" || (job?.kind === "check" && !job.failed && !job.parts);
  const pct = Math.round((e?.progress ?? job?.progress ?? 0) * 100);
  return (
    <header>
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
        <div className="min-w-0">
          <h2 id="edit-h" className="text-[19px] font-semibold">The edit</h2>
          <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-[12.5px] text-g8">
            {!e || e.state === "waiting" ? <Tag>Waiting</Tag>
              : checking ? <span className="flex items-center gap-2 text-g9"><Ring pct={pct} size={20} label={<span />} />Checking the clips<span className="edge">{pct}%</span></span>
              : e.state === "failed" ? <Tag tone="bad">Check failed</Tag>
              : <Tag tone="ok">Ready</Tag>}
            {cuts.length > 0 && (
              <span className="flex flex-wrap gap-x-2 font-mono text-[11.5px] tracking-wide text-edge uppercase">
                <span>{beats.length} beats</span><span className="text-g6">·</span><span>{cuts.length} cuts</span><span className="text-g6">·</span>
                <span>{videos} {videos === 1 ? "video" : "videos"}</span><span className="text-g6">·</span><span>{mmss(have, true)} of {mmss(need, true)}</span>
              </span>
            )}
          </div>
        </div>
        {e && e.state !== "waiting" && !locked && (
          <Button kind="secondary" size="sm" icon={<ArrowClockwise size={14} />} disabled={checking} onClick={() => checkAgain(p.id)}>Check the whole story again</Button>
        )}
      </div>
      {e?.flow && e.state !== "failed" && <p className="mt-3 max-w-[72ch] text-[14px] leading-relaxed text-g9">{e.flow}</p>}
      {(!e || e.state === "waiting") && (
        <p className="mt-3 max-w-[72ch] text-[13.5px] text-g8">The clip check builds the edit once the voice is made and the footage search is done: for each beat it picks which shots play, in what order and for how long.</p>
      )}
      {e?.state === "failed" && (
        <div role="alert" className="mt-4 flex flex-wrap items-center gap-3 rounded-md border border-bad/40 bg-bad/8 px-4 py-3 text-[13.5px]">
          <WarningCircle size={18} weight="fill" className="shrink-0 text-bad" />
          <span className="min-w-0 flex-1 text-g10">{e.note || "The clip check stopped before it finished."}</span>
          {!locked && <Button kind="secondary" size="sm" icon={<ArrowClockwise size={14} />} onClick={() => checkAgain(p.id)}>Check again</Button>}
        </div>
      )}
    </header>
  );
}

// ------------------------------------------------------------------ one beat: its line, and its cuts as a bar of seconds

function BeatRow({ p, s, n, sel, onSelect, locked }: { p: Project; s: Section; n: number; sel: Sel | null; onSelect: (s: Sel | null) => void; locked: boolean }) {
  const b = beatOf(p, s.id);
  const job = useStore((st) => st.jobs[p.id]);
  const e = p.edit!;
  const busy = (job?.kind === "check" && !job.failed && (!job.parts || !!job.parts[s.id])) || e.state === "checking" || e.state === "waiting";
  const start = p.edit!.beats.slice(0, p.edit!.beats.findIndex((x) => x.sectionId === s.id)).reduce((t, x) => t + x.secs, 0);
  const gap = b ? shortBy(b) : 0;
  const voice = sectionSeconds(s, p.anchorId);
  const drift = b && voice.measured && Math.abs(voice.sec - b.secs) > 0.5;
  const on = sel?.sid === s.id;
  return (
    <motion.li layout="position" transition={{ duration: 0.3, ease: EASE }}
      className={cx("rounded-md border bg-g1 transition-colors", on ? "border-g6" : "border-g4")} aria-labelledby={`beat-${s.id}`}>
      <div className="grid gap-x-6 gap-y-3 p-4 xl:grid-cols-[minmax(0,300px)_minmax(0,1fr)]">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <Microphone size={14} weight="fill" className="text-vo" />
            <h3 id={`beat-${s.id}`} className="narrow text-[13.5px] font-semibold">Beat {n}</h3>
            {b && <span className="edge text-[11.5px]">{mmss(start, true)}–{mmss(start + b.secs, true)}</span>}
            {gap > 0 && <Tag tone="warn">{gap.toFixed(1)} s short</Tag>}
            {b && busy && job?.parts?.[s.id] && <span className="flex items-center gap-1 text-[12px] text-g9"><CircleNotch size={12} className="animate-spin" />Checking again</span>}
          </div>
          <p className="mt-2 text-[14px] leading-relaxed text-g10">{s.text}</p>
          {s.picture && <p className="mt-2 flex gap-1.5 text-[12.5px] leading-snug text-g8"><Eye size={14} className="mt-px shrink-0" /><span><span className="sr-only">On screen: </span>{s.picture}</span></p>}
          {drift && <p className="mt-2 text-[12.5px] text-warn">The voice now runs {voice.sec.toFixed(1)} s, not {b!.secs.toFixed(1)} s. Check again to re-time this beat.</p>}
        </div>
        <div className="min-w-0">
          {b ? <CutBar p={p} b={b} start={start} sel={on ? sel : null} onSelect={onSelect} locked={locked} busy={busy} />
            : busy ? <Skeleton className="h-[112px]" />
            : <div className="flex h-[112px] flex-col items-center justify-center gap-2 rounded-md border border-dashed border-g5 text-[13px] text-g8">
                Not checked yet. This beat was added after the clip check.
                {!locked && <Button kind="secondary" size="sm" icon={<ArrowClockwise size={14} />} onClick={() => checkAgain(p.id, s.id)}>Check this beat</Button>}
              </div>}
          {b && (
            <div className="mt-2 flex items-start gap-3">
              <Notes b={b} />
              {!locked && !busy && (
                <Tip label="Pick this beat's shots again">
                  <button onClick={() => checkAgain(p.id, s.id)} className="-mt-1 ml-auto inline-flex h-7 shrink-0 items-center gap-1.5 rounded-sm px-2 text-[12.5px] font-semibold text-g9 transition-colors hover:bg-g3 hover:text-g10">
                    <ArrowClockwise size={13} />Check again
                  </button>
                </Tip>
              )}
            </div>
          )}
        </div>
      </div>
    </motion.li>
  );
}

function CutBar({ p, b, start, sel, onSelect, locked, busy }: { p: Project; b: BeatEdit; start: number; sel: Sel | null; onSelect: (s: Sel | null) => void; locked: boolean; busy: boolean }) {
  // drag with the pointer; from the keyboard, select a cut (Enter or Space) and move it with Earlier / Later
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 5 } }));
  const gap = shortBy(b);
  const ids = b.cuts.map((c) => c.id);
  function end(ev: DragEndEvent) {
    if (!ev.over || ev.active.id === ev.over.id) return;
    moveCuts(p.id, b.sectionId, arrayMove(ids, ids.indexOf(String(ev.active.id)), ids.indexOf(String(ev.over.id))));
  }
  return (
    <div className={cx("relative rounded-md bg-[#060607] p-2 ring-1 ring-g4 transition-opacity", busy && "pointer-events-none opacity-50")} aria-busy={busy}>
      <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={end}
        accessibility={{ screenReaderInstructions: { draggable: "Select the cut to play, swap or remove it, and to move it earlier or later." } }}>
        <SortableContext items={ids} strategy={horizontalListSortingStrategy}>
          <ol className="flex h-24 gap-[3px]" aria-label={`Cuts, in play order.${locked ? "" : " Drag a cut to move it, or select it to move, swap or remove it."}`}>
            {b.cuts.map((c, i) => (
              <CutTile key={c.id} c={c} n={i + 1} on={!!sel && !("gap" in sel) && sel.cid === c.id} locked={locked}
                onClick={() => onSelect(sel && !("gap" in sel) && sel.cid === c.id ? null : { sid: b.sectionId, cid: c.id })} />
            ))}
            {gap > 0 && (
              <li className="flex min-w-[28px] [container-type:inline-size]" style={{ flexGrow: gap, flexBasis: 0 }}>
                <button disabled={locked} onClick={() => onSelect({ sid: b.sectionId, gap: true })} aria-label={`${gap.toFixed(1)} seconds with no picture. Fill it`}
                  className={cx("flex size-full flex-col items-center justify-center gap-0.5 rounded-[2px] border border-dashed text-warn transition-colors",
                    "bg-[repeating-linear-gradient(135deg,transparent_0_6px,color-mix(in_srgb,var(--color-warn)_9%,transparent)_6px_12px)]",
                    sel && "gap" in sel ? "border-warn" : "border-warn/50 hover:border-warn")}>
                  <Plus size={14} weight="bold" />
                  <span className="hidden font-mono text-[11px] @min-[64px]:block">{gap.toFixed(1)} s</span>
                </button>
              </li>
            )}
            {b.cuts.length === 0 && gap === 0 && <li className="grid flex-1 place-items-center text-[12.5px] text-g8">No cuts</li>}
          </ol>
        </SortableContext>
      </DndContext>
      <div className="mt-1.5 flex justify-between font-mono text-[11px] text-edge" aria-hidden>
        <span>{mmss(start, true)}</span><span>{mmss(start + b.secs, true)}</span>
      </div>
    </div>
  );
}

const FIT: Record<string, { tone: "ok" | "neutral" | "warn"; l: string; hint: string }> = {
  exact: { tone: "ok", l: "Exact", hint: "Filmed at this event" },
  subject: { tone: "neutral", l: "Subject", hint: "The right subject, not filmed at this event" },
  topic: { tone: "warn", l: "Topic", hint: "The same kind of scene, from somewhere else" },
};
const KIND: Record<string, { I: typeof FilmSlate; l: string }> = {
  footage: { I: FilmSlate, l: "Footage" }, speech: { I: ChatCircleText, l: "Speech" }, photo: { I: ImageIcon, l: "Photo" }, post_or_document: { I: FileText, l: "Post or document" },
};
const fitOf = (f: string) => FIT[f] ?? { tone: "neutral" as const, l: f, hint: f };
const kindOf = (k: string) => KIND[k] ?? { I: FilmSlate, l: k };
/** The one mark a cut carries on its tile, most important first. */
function markOf(c: EditCut): { l: string; tone: "warn" | "neutral" | "edge"; hint: string } | null {
  // with `swapped`, `review` says what was wrong with the shot it replaced
  if (c.swapped) return { l: "Swapped", tone: "neutral", hint: c.review ? `The review swapped this shot in. It replaced: ${c.review}` : "The review swapped this shot in" };
  if (c.review) return { l: "Review", tone: "warn", hint: `Flagged by the review: ${c.review}` };
  if (c.repeat) return { l: "Repeat", tone: "warn", hint: "This shot also plays in another beat" };
  if (c.fill) return { l: "Fill", tone: "neutral", hint: "Added to fill the beat out" };
  if (c.byUser) return { l: "Yours", tone: "edge", hint: "You put this shot here" };
  return null;
}

function CutTile({ c, n, on, locked, onClick }: { c: EditCut; n: number; on: boolean; locked: boolean; onClick: () => void }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: c.id, disabled: locked });
  const fit = fitOf(c.fit); const kind = kindOf(c.kind); const mark = markOf(c);
  return (
    <li ref={setNodeRef} className="relative flex min-w-[28px] [container-type:inline-size]"
      style={{ flexGrow: c.secs, flexBasis: 0, transform: CSS.Transform.toString(transform), zIndex: isDragging ? 10 : undefined,
        transition: [transition, "flex-grow 320ms cubic-bezier(0.16,1,0.3,1)"].filter(Boolean).join(", ") }}>
      <button {...attributes} {...listeners} onClick={onClick} aria-pressed={on}
        aria-label={`Cut ${n}, ${c.secs.toFixed(1)} seconds, ${fit.l.toLowerCase()} fit, ${kind.l.toLowerCase()}: ${c.shows}${mark ? `. ${mark.hint}` : ""}`}
        className={cx("group relative size-full overflow-hidden rounded-[2px] bg-g3 ring-1 transition-[box-shadow,filter] duration-150",
          on ? "ring-2 ring-g10" : "ring-g4 hover:ring-g7", isDragging ? "cursor-grabbing shadow-[0_16px_40px_-12px_rgba(0,0,0,0.9)] brightness-110" : !locked && "cursor-grab")}>
        <img src={c.poster} alt="" draggable={false} className="absolute inset-0 size-full object-cover" />
        <span className="absolute inset-0 bg-gradient-to-t from-black/75 via-black/10 to-black/40" />
        <span className="pointer-events-none absolute top-0.5 left-1 font-marker text-[22px] leading-none text-marker [paint-order:stroke_fill] [-webkit-text-stroke:5px_#0a0b0d]">{n}</span>
        <span className="absolute top-1 right-1 hidden items-center gap-1 @min-[84px]:flex">
          <Tag tone={fit.tone} className="bg-black/75">{fit.l}</Tag>
        </span>
        <span className="absolute bottom-1 left-1 hidden items-center gap-1 @min-[96px]:flex">
          <kind.I size={13} className="shrink-0 text-g10" aria-hidden />
          {mark && <Tag tone={mark.tone} className="bg-black/75">{mark.l}</Tag>}
        </span>
        <span className="absolute right-1 bottom-1 hidden rounded-xs bg-black/70 px-1 font-mono text-[11px] text-edge @min-[44px]:block">{c.secs.toFixed(1)}</span>
        {mark?.tone === "warn" && <span className="absolute inset-x-0 top-0 h-[2px] bg-warn" aria-hidden />}
      </button>
    </li>
  );
}

const NOTE: Record<string, string> = {
  "story footage": "Filled from the story's footage", "own picture": "Uses one of our own pictures", "topic footage": "Filled from footage of the same kind of scene",
  "repeat dropped": "A repeated shot was dropped",
};
function Notes({ b }: { b: BeatEdit }) {
  const notes = b.notes.filter((x) => !/^\d+(\.\d+)?\s*s short$/i.test(x.trim())).map((x) => NOTE[x.trim().toLowerCase()] ?? x.charAt(0).toUpperCase() + x.slice(1));
  const flagged = b.cuts.flatMap((c, i) => (c.review || c.swapped ? [{ n: i + 1, swapped: !!c.swapped, text: c.review }] : []));
  if (!notes.length && !flagged.length) return null;
  return (
    <ul className="flex min-w-0 flex-wrap gap-x-4 gap-y-1 text-[12px] text-g8">
      {notes.map((x) => <li key={x} className="flex items-center gap-1.5"><span className="size-1 rounded-full bg-g7" />{x}</li>)}
      {flagged.map((f) => f.swapped
        ? <li key={f.n} className="flex items-center gap-1.5"><span className="size-1 rounded-full bg-g7" />Cut {f.n} swapped in by the review{f.text ? ` (replaced: ${f.text})` : ""}</li>
        : <li key={f.n} className="flex items-center gap-1.5"><Warning size={12} className="text-warn" />Cut {f.n} flagged by the review: {f.text}</li>)}
    </ul>
  );
}

// ------------------------------------------------------------------ right: the selected cut (or the gap at a beat's end)

function Inspector({ p, sel, names, locked, onSelect }: { p: Project; sel: Sel | null; names: Record<string, string>; locked: boolean; onSelect: (s: Sel | null) => void }) {
  const b = sel ? beatOf(p, sel.sid) : undefined;
  const [preview, setPreview] = useState<EditCandidate | null>(null);
  const top = useRef<HTMLDivElement>(null);
  useEffect(() => { if (preview) top.current?.scrollIntoView({ block: "start", behavior: "smooth" }); }, [preview]);
  const [frame, setFrame] = useState<"crop" | "full">("crop");
  const key = sel ? ("gap" in sel ? `${sel.sid}-gap` : sel.cid) : "none";
  const [seen, setSeen] = useState(key);
  if (seen !== key) { setSeen(key); setPreview(null); }   // a new selection drops the candidate preview

  if (!sel || !b) return <Legend />;
  const gap = "gap" in sel;
  const i = gap ? -1 : b.cuts.findIndex((c) => c.id === sel.cid);
  const c = gap ? undefined : b.cuts[i];
  const shown = preview ?? c;
  const pick = (cand: EditCandidate) => {
    if (gap) { addCut(p.id, b.sectionId, cand); onSelect(null); }
    else if (c) swapCut(p.id, b.sectionId, c.id, cand);
  };
  const move = (d: -1 | 1) => { const ids = b.cuts.map((x) => x.id); moveCuts(p.id, b.sectionId, arrayMove(ids, i, i + d)); };
  return (
    <div className="scroll-mt-4 p-5" ref={top}>
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="text-[15px] font-semibold">{names[b.sectionId]} · {gap ? <span className="text-warn">{shortBy(b).toFixed(1)} s short</span> : `cut ${i + 1} of ${b.cuts.length}`}</h2>
        {c && <span className="edge text-[13px]">{c.secs.toFixed(1)} s</span>}
      </div>

      {shown ? (
        <>
          <div className="mt-4 flex items-start gap-4">
            <Clip key={(preview ? "p" : "c") + (shown.clip ?? shown.poster)} src={shown.clip} poster={shown.poster} frame={frame} />
            <div className="min-w-0 flex-1 space-y-3">
              <Segmented size="sm" label="Framing" value={frame} set={setFrame} options={[{ v: "crop", l: "9:16" }, { v: "full", l: "Original" }]} />
              <p className="text-[12px] leading-snug text-g8">{frame === "crop" ? "Centre crop, standing in for the reframer." : "The shot as it was filmed."}</p>
              {preview && <Tag tone="vo">Option {b.candidates.indexOf(preview) + 1}</Tag>}
            </div>
          </div>
          <p className="mt-4 text-[14px] leading-snug text-g10">{shown.shows}</p>
          {preview ? (
            <p className="mt-2 flex items-center gap-2 text-[12.5px] text-g8"><SpeakerHigh size={14} className="shrink-0" />{preview.sound || "No sound"}</p>
          ) : c && (
            <label className="mt-2 -mx-1 flex items-center gap-2 rounded-sm px-1 py-1 text-[12.5px] text-g8 focus-within:bg-g2"
              title="The scene sound made for this shot under the voice. Leave empty for none.">
              <SpeakerHigh size={14} className="shrink-0" /><span className="shrink-0">Sound</span>
              <input value={c.sound ?? ""} readOnly={locked} onChange={(e) => setCutSound(p.id, b.sectionId, c.id, e.target.value)}
                placeholder={c.sound === undefined ? "Chosen when the video is made" : "No sound"} aria-label={`Cut ${i + 1}: scene sound`}
                className="min-w-0 flex-1 bg-transparent text-g9 outline-none focus-visible:outline-none" />
            </label>
          )}
          <Facts src={shown.src} fit={shown.fit} kind={shown.kind} at={preview ? undefined : c?.at} />
          {preview ? (
            <div className="mt-4 flex gap-2">
              <Button kind="primary" size="sm" disabled={locked || usedAs(b, preview) >= 0} onClick={() => { pick(preview); setPreview(null); }}>{gap ? "Add to the beat" : `Swap into cut ${i + 1}`}</Button>
              <Button kind="ghost" size="sm" onClick={() => setPreview(null)}>{gap ? "Close" : "Back to the cut"}</Button>
            </div>
          ) : c && (
            <>
              <Flags c={c} />
              {!locked && (
                <div className="mt-4 flex flex-wrap gap-2">
                  <Button kind="secondary" size="sm" icon={<ArrowLeft size={13} />} disabled={i === 0} onClick={() => move(-1)}>Earlier</Button>
                  <Button kind="secondary" size="sm" disabled={i === b.cuts.length - 1} onClick={() => move(1)}>Later<ArrowRight size={13} /></Button>
                  <Button kind="danger" size="sm" icon={<Trash size={13} />} className="ml-auto" onClick={() => removeCut(p.id, b.sectionId, c.id)}>Remove</Button>
                </div>
              )}
            </>
          )}
        </>
      ) : (
        <p className="mt-3 text-[13px] leading-relaxed text-g8">The pictures run out {shortBy(b).toFixed(1)} s before the line ends. Add one of the beat's other shots below; the cuts are re-timed to fill the beat.</p>
      )}

      <section className="mt-7" aria-labelledby="alts-h">
        <div className="mb-3 flex items-baseline justify-between">
          <h3 id="alts-h" className="text-[13.5px] font-semibold">{gap ? "Shots to add" : "Swap with"}</h3>
          <span className="edge text-[11.5px]">{b.candidates.length}</span>
        </div>
        {b.candidates.length === 0 ? <p className="text-[12.5px] text-g8">The check found no other shots for this beat. Check the beat again.</p> : (
          <div className="grid grid-cols-2 gap-x-3 gap-y-4">
            {b.candidates.map((x, k) => {
              const used = usedAs(b, x);
              return <Frame key={k} src={x.poster} code={`ALT·${String(k + 1).padStart(2, "0")}`} label={x.shows} dim={used >= 0}
                sub={used >= 0 ? `In use as cut ${used + 1}` : `${fitOf(x.fit).l} · ${kindOf(x.kind).l}`}
                seconds={x.src.kind === "video" ? x.src.end - x.src.start : undefined} seed={k}
                onOpen={() => setPreview(x)} onAdd={locked || used >= 0 ? undefined : () => pick(x)} />;
            })}
          </div>
        )}
      </section>
      {b.why && (
        <section className="mt-7 border-t border-g4 pt-4">
          <h3 className="text-[12.5px] font-semibold text-g8">Why the check chose these shots</h3>
          <p className="mt-1 text-[12.5px] leading-relaxed text-g8">{b.why}</p>
        </section>
      )}
    </div>
  );
}

function Clip({ src, poster, frame }: { src?: string; poster: string; frame: "crop" | "full" }) {
  return (
    <div className="relative aspect-[9/16] w-[148px] shrink-0 overflow-hidden rounded-[3px] bg-black ring-1 ring-g5">
      {src ? <video src={src} poster={poster} autoPlay muted loop playsInline className={cx("absolute inset-0 size-full", frame === "crop" ? "object-cover" : "object-contain")} />
        : <img src={poster} alt="" className={cx("absolute inset-0 size-full", frame === "crop" ? "object-cover" : "object-contain")} />}
    </div>
  );
}

function Facts({ src, fit, kind, at }: { src: EditSource; fit: string; kind: string; at?: number }) {
  const f = fitOf(fit); const k = kindOf(kind);
  const row = (l: string, v: ReactNode) => <><dt className="text-g8">{l}</dt><dd className="min-w-0 text-g9">{v}</dd></>;
  return (
    <dl className="mt-3 grid grid-cols-[84px_minmax(0,1fr)] gap-x-3 gap-y-1.5 text-[12.5px]">
      {src.kind === "video" ? <>
        {row("Video", <a href={`https://www.youtube.com/watch?v=${src.youtubeId}&t=${Math.floor(src.start)}s`} target="_blank" rel="noreferrer"
          className="inline-flex max-w-full items-center gap-1 underline decoration-g6 underline-offset-2 hover:text-g10"><span className="truncate">{src.title || src.youtubeId}</span><ArrowSquareOut size={12} className="shrink-0" /></a>)}
        {row("In the video", <span className="edge">{mmss(src.start, true)}–{mmss(src.end, true)}</span>)}
      </> : <>
        {row("Picture", <a href={src.page || src.url} target="_blank" rel="noreferrer" className="inline-flex max-w-full items-center gap-1 underline decoration-g6 underline-offset-2 hover:text-g10"><span className="truncate">{src.title || hostOf(src.page || src.url)}</span><ArrowSquareOut size={12} className="shrink-0" /></a>)}
        {row("Found on", hostOf(src.page || src.url))}
      </>}
      {at !== undefined && row("In the story", <span className="edge">{mmss(at, true)}</span>)}
      {row("Fit", <span className="flex items-center gap-2"><Tag tone={f.tone}>{f.l}</Tag><span className="truncate text-g8">{f.hint}</span></span>)}
      {row("Kind", <span className="flex items-center gap-1.5"><k.I size={13} />{k.l}</span>)}
    </dl>
  );
}
const hostOf = (u: string) => { try { return new URL(u).hostname.replace(/^www\./, ""); } catch { return u; } };

function Flags({ c }: { c: EditCut }) {
  const items = [
    c.review && !c.swapped && { warn: true, t: `Flagged by the review: ${c.review}` },
    c.swapped && { warn: false, t: c.review ? `The review swapped this shot in. It replaced: ${c.review}.` : "The review swapped this shot in." },
    c.repeat && { warn: true, t: "This shot also plays in another beat." },
    c.fill && { warn: false, t: "Added to fill the beat out." },
    c.byUser && { warn: false, t: "You put this shot here." },
  ].filter(Boolean) as { warn: boolean; t: string }[];
  if (!items.length) return null;
  return (
    <ul className="mt-3 space-y-1 text-[12.5px]">
      {items.map((x) => <li key={x.t} className={cx("flex gap-2", x.warn ? "text-warn" : "text-g9")}>{x.warn ? <Warning size={14} className="mt-px shrink-0" /> : <span className="mt-[7px] size-1 shrink-0 rounded-full bg-g7" />}{x.t}</li>)}
    </ul>
  );
}

function Legend() {
  return (
    <div className="p-5">
      <h2 className="text-[15px] font-semibold">Cuts</h2>
      <p className="mt-1.5 text-[13px] leading-relaxed text-g8">Click a cut to play it, swap it for another shot or take it out; the others stretch to fill the beat. Drag cuts to change their order.</p>
      <dl className="mt-5 space-y-2.5 text-[12.5px]">
        {Object.values(FIT).map((f) => <div key={f.l} className="flex items-center gap-3"><dt className="w-[64px]"><Tag tone={f.tone}>{f.l}</Tag></dt><dd className="text-g9">{f.hint}</dd></div>)}
      </dl>
      <dl className="mt-5 grid grid-cols-2 gap-y-2 text-[12.5px] text-g9">
        {Object.values(KIND).map((k) => <div key={k.l} className="flex items-center gap-2"><dt><k.I size={14} className="text-g8" /></dt><dd>{k.l}</dd></div>)}
      </dl>
    </div>
  );
}

// ------------------------------------------------------------------ continue: allowed with short beats, but says so

function ContinueGate({ p, short, names, locked, onFix, onGo }: { p: Project; short: { s: Section; by: number }[]; names: Record<string, string>; locked: boolean; onFix: (sid: string) => void; onGo: () => void }) {
  const e = p.edit;
  if (!e || e.state !== "ready") {
    return (
      <div className="flex h-11 w-full items-center justify-center gap-2 rounded-sm border border-dashed border-g6 text-[13px] text-g9">
        {e?.state === "checking" ? <CircleNotch size={14} className="animate-spin" /> : <Lock size={14} />}
        {e?.state === "failed" ? "Check the edit again to continue" : "Continue opens once the edit is checked"}
      </div>
    );
  }
  return (
    <div className="space-y-3">
      <AnimatePresence initial={false}>
        {short.length > 0 && (
          <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }} exit={{ opacity: 0, height: 0 }} transition={{ duration: 0.24, ease: EASE }} className="overflow-hidden">
            <div className="flex gap-2 text-[12.5px] leading-snug text-warn">
              <Warning size={15} className="mt-px shrink-0" />
              <span>
                {short.map((x, k) => <span key={x.s.id}>{k > 0 && ", "}<button className="underline decoration-warn/40 underline-offset-2 hover:decoration-warn" onClick={() => onFix(x.s.id)}>{names[x.s.id]}</button> {x.by.toFixed(1)} s</span>)}
                {" "}short. {short.length === 1 ? "Its pictures run" : "Their pictures run"} out before the line ends.
              </span>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
      <Button kind="primary" size="lg" className="w-full" disabled={locked} onClick={onGo}>
        {locked ? (p.stage === "done" ? "Rendered" : "Queued for tonight\u2019s render") : short.length ? "Continue anyway" : "Continue"} <ArrowRight size={16} weight="bold" />
      </Button>
    </div>
  );
}
