import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { AnimatePresence, motion } from "motion/react";
import { DndContext, closestCenter, KeyboardSensor, PointerSensor, useSensor, useSensors, type DragEndEvent } from "@dnd-kit/core";
import { SortableContext, sortableKeyboardCoordinates, useSortable, verticalListSortingStrategy, arrayMove } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import {
  DotsSixVertical, DotsThree, Scissors, ArrowsMerge, Trash, VideoCamera, Microphone, Sparkle, Plus, ArrowRight, ArrowUp, ArrowDown, Link as LinkIcon, FileText, TextAa, Play, Pause, Check, X,
  Eye, FilmStrip,
} from "@phosphor-icons/react";
import {
  useStore, sections, sectionSeconds, totalSeconds, editSection, setLT, reorderSections, addSection, deleteSection, turnInto, mergeNext, splitAt, setFormat,
  setFact, setTicker, setAnchor, approveScript, proposeRewrite, anchorOf, wordsOf, setTarget, parseLength, MIN_TICKER, retryJob, type RewriteAsk,
} from "@/data/store";
import type { Project, Section, Anchor } from "@/data/types";
import { useProject } from "@/components/story";
import { Mark } from "@/components/shell";
import { Button, Dialog, Empty, IconButton, Menu, Segmented, Sheet, Textarea, Tip, cx, mmss, Skeleton, LiveSeconds, FORMAT_OPTIONS } from "@/components/ui";

export default function ScriptPage() {
  const p = useProject()!;
  const job = useStore((s) => s.jobs[p.id]);
  const writing = job?.kind === "write" && !job.failed;
  const locked = writing || (p.stage !== "script" && p.stage !== "visuals" && p.stage !== "review");   // the server refuses edits while it writes
  const list = sections(p);
  const total = totalSeconds(p);
  const nav = useNavigate();
  const [rewrite, setRewrite] = useState<RewriteAsk["scope"] | null>(null);
  const vo = p.format === "vo_only";
  const canVo = "vo_only" in p.versions;   // the server adds the VO-only version only once it can write one

  return (
    <div className="mx-auto grid grid-cols-1 max-w-[1680px] gap-0 lg:grid-cols-[minmax(0,1fr)_400px]">
      <div className="min-w-0 border-g4 px-5 pt-6 pb-32 lg:border-r lg:pr-8">
        {/* format + total */}
        <div className="sticky top-[52px] z-20 -mx-5 mb-5 border-b border-g4 bg-g0/95 px-5 pt-1 pb-3 backdrop-blur-md lg:-mr-8 lg:pr-8">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <Segmented label="Format" value={p.format} set={(v) => !locked && setFormat(p.id, v)}
              options={FORMAT_OPTIONS.map((o) => (o.v === "vo_only" && !canVo ? { ...o, off: "This story has no VO-only version. It can be written once the server supports VO only." } : o))} />
            <TotalVsTarget p={p} total={total} />
          </div>
          <TargetBar total={total} target={p.targetSeconds} />
        </div>

        {writing && list.length === 0 && <WritingSkeleton note={job.note} />}
        {vo && !writing && list.length === 0 && (
          <Empty icon={<FilmStrip size={30} />} title="No VO-only version yet"
            action={!locked && <Button kind="secondary" onClick={() => retryJob(p.id, "write")}>Write the VO-only version</Button>}>
            VO only is written as beats: one line each, over one kind of picture. The other versions are kept.
          </Empty>
        )}
        <SectionList p={p} locked={locked} onRewrite={(sid) => setRewrite(sid)} writingNote={writing ? job.note : undefined} />

        {!writing && !locked && p.format === "anchor_vo" && (
          <div className="mt-3 flex gap-2">
            <Button kind="ghost" size="sm" icon={<Plus size={14} />} onClick={() => addSection(p.id, "anchor")}>Anchor part</Button>
            <Button kind="ghost" size="sm" icon={<Plus size={14} />} onClick={() => addSection(p.id, "vo")}>Voiceover part</Button>
          </div>
        )}
        {!writing && !locked && vo && list.length > 0 && (
          <div className="mt-3"><Button kind="ghost" size="sm" icon={<Plus size={14} />} onClick={() => addSection(p.id, "vo")}>Beat</Button></div>
        )}
        {!vo && <Graphics p={p} locked={locked} />}
      </div>

      <aside className="px-5 pt-6 pb-32 lg:sticky lg:top-[52px] lg:h-[calc(100vh-52px)] lg:overflow-auto lg:pl-7">
        <AnchorPanel p={p} locked={locked} />
        <Facts p={p} locked={locked} writing={writing} />
        <Button kind="secondary" className="mt-5 w-full" icon={<Sparkle size={16} weight="fill" className="text-marker-ink" />} onClick={() => setRewrite("all")} disabled={writing || locked}>
          Rewrite with AI
        </Button>
        <SourceCard p={p} />
      </aside>

      {/* approve bar */}
      <div className="fixed right-0 bottom-0 left-0 z-20 border-t border-g4 bg-g1/95 backdrop-blur-md">
        <div className="mx-auto flex h-16 max-w-[1680px] items-center justify-between gap-4 px-5">
          <span className="text-[13px] text-g8">
            {p.stage === "script" ? (vo ? "Approving makes the voice and starts the footage search; the clip check builds the edit after it." : tickerOk(p) ? "Approving starts the voice on the GPU and the footage search, side by side." : `The ticker needs at least ${MIN_TICKER} lines before approving.`) : `Approved. Edits here re-voice only the ${vo ? "beats" : "parts"} you change.`}
          </span>
          {p.stage === "script" ? (
            <Button kind="primary" size="lg" disabled={writing || list.length === 0 || list.some((s) => !s.text.trim()) || (!vo && !tickerOk(p))}
              onClick={() => { approveScript(p.id); nav(`/story/${p.id}/visuals`); }}>Approve script <ArrowRight size={16} weight="bold" /></Button>
          ) : (
            <Button kind="secondary" size="lg" onClick={() => nav(`/story/${p.id}/visuals`)}>Go to visuals <ArrowRight size={16} weight="bold" /></Button>
          )}
        </div>
      </div>

      <RewriteSheet p={p} scope={rewrite} onClose={() => setRewrite(null)} />
    </div>
  );
}

// ------------------------------------------------------------------ total vs target

function TotalVsTarget({ p, total }: { p: Project; total: number }) {
  const [edit, setEdit] = useState(false);
  const [val, setVal] = useState(mmss(p.targetSeconds));
  const diff = total - p.targetSeconds;
  const over = Math.abs(diff) > p.targetSeconds * 0.1;
  const measured = sections(p).every((s) => sectionSeconds(s, p.anchorId).measured);
  return (
    <div className="flex items-center gap-3 text-[13px]">
      <span className="text-g8">{measured ? "Measured" : "Estimated"}</span>
      <LiveSeconds sec={total} className="text-[19px] font-medium text-g10" />
      <span className="text-g8">of</span>
      {edit ? (
        <input autoFocus value={val} onChange={(e) => setVal(e.target.value)} aria-label="Target length"
          onBlur={() => { const s = parseLength(val); if (s) setTarget(p.id, s); setEdit(false); }}
          onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); if (e.key === "Escape") setEdit(false); }}
          className="h-7 w-16 rounded-sm border border-g6 bg-g1 text-center font-mono text-[13px] text-edge outline-none" />
      ) : (
        <Tip label="Change the target length"><button onClick={() => { setVal(mmss(p.targetSeconds)); setEdit(true); }} className="edge text-[15px] underline decoration-g6 decoration-dotted underline-offset-4 hover:decoration-edge">{mmss(p.targetSeconds)}</button></Tip>
      )}
      <motion.span key={Math.round(diff)} initial={{ scale: 0.92, opacity: 0.6 }} animate={{ scale: 1, opacity: 1 }}
        className={cx("rounded-xs px-1.5 py-0.5 font-mono text-[12px]", !over ? "bg-ok/12 text-ok" : "bg-warn/15 text-warn")}>
        {diff >= 0 ? "+" : "−"}{mmss(Math.abs(diff))}
      </motion.span>
    </div>
  );
}

function TargetBar({ total, target }: { total: number; target: number }) {
  const max = Math.max(total, target) * 1.08;
  return (
    <div className="relative mt-3 h-1.5 rounded-full bg-g4" aria-hidden>
      <motion.div className={cx("absolute inset-y-0 left-0 rounded-full", total > target * 1.1 ? "bg-warn" : "bg-edge")} initial={false}
        animate={{ width: `${(total / max) * 100}%` }} transition={{ duration: 0.45, ease: [0.16, 1, 0.3, 1] }} />
      <div className="absolute -top-1 -bottom-1 w-px bg-g10" style={{ left: `${(target / max) * 100}%` }} />
    </div>
  );
}

function WritingSkeleton({ note }: { note: string }) {
  return (
    <div className="space-y-3" aria-live="polite">
      <p className="text-[13px] text-g8">{note}…</p>
      {[0, 1, 2].map((i) => <Skeleton key={i} className="h-[104px]" />)}
    </div>
  );
}

// ------------------------------------------------------------------ sections

function SectionList({ p, locked, onRewrite, writingNote }: { p: Project; locked: boolean; onRewrite: (sid: string) => void; writingNote?: string }) {
  const list = sections(p);
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }), useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }));
  function end(e: DragEndEvent) {
    if (!e.over || e.active.id === e.over.id) return;
    const ids = list.map((s) => s.id);
    reorderSections(p.id, arrayMove(ids, ids.indexOf(String(e.active.id)), ids.indexOf(String(e.over.id))));
  }
  let na = 0; let nv = 0;
  return (
    <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={end}>
      <SortableContext items={list.map((s) => s.id)} strategy={verticalListSortingStrategy}>
        <ol className="space-y-2.5">
          <AnimatePresence initial={false}>
            {list.map((s, i) => (
              <SectionCard key={s.id} p={p} s={s} n={p.format === "vo_only" ? i + 1 : s.kind === "anchor" ? ++na : ++nv} index={i} last={i === list.length - 1} locked={locked} onRewrite={onRewrite} />
            ))}
          </AnimatePresence>
          {writingNote && list.length > 0 && <li><Skeleton className="h-[104px]" /></li>}
        </ol>
      </SortableContext>
    </DndContext>
  );
}

function SectionCard({ p, s, n, index, last, locked, onRewrite }: { p: Project; s: Section; n: number; index: number; last: boolean; locked: boolean; onRewrite: (sid: string) => void }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: s.id, disabled: locked || p.format === "anchor_only" });
  const ta = useRef<HTMLTextAreaElement>(null);
  const { sec, measured } = sectionSeconds(s, p.anchorId);
  const prev = useRef(sec);
  const delta = sec - prev.current;
  if (Math.abs(delta) >= 0.5) prev.current = sec;
  const ids = sections(p).map((x) => x.id);
  const vo = p.format === "vo_only";
  const name = vo ? `Beat ${n}` : p.format === "anchor_only" ? "Anchor, whole script" : s.kind === "anchor" ? `Anchor ${n}` : `Voiceover ${n}`;
  return (
    <motion.li ref={setNodeRef} layout={!isDragging} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, height: 0, marginTop: 0 }}
      transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
      style={{ transform: CSS.Transform.toString(transform), transition, zIndex: isDragging ? 10 : undefined }}
      className={cx("group relative rounded-md border bg-g1 transition-[border-color,box-shadow]", isDragging ? "border-g7 shadow-[0_20px_50px_-15px_rgba(0,0,0,0.9)]" : "border-g4 hover:border-g5 focus-within:border-g6")}>
      <div className="flex items-center gap-2 px-3 pt-2.5">
        {p.format !== "anchor_only" && !locked ? (
          <button {...attributes} {...listeners} aria-label={`Drag to reorder ${vo ? "beat" : s.kind === "anchor" ? "anchor part" : "voiceover part"} ${n}`}
            className="-ml-1 cursor-grab rounded-xs p-0.5 text-g6 hover:text-g9 active:cursor-grabbing"><DotsSixVertical size={18} weight="bold" /></button>
        ) : <span className="w-1" />}
        {s.kind === "anchor" ? <VideoCamera size={15} weight="fill" className="text-anchor" /> : <Microphone size={15} weight="fill" className="text-vo" />}
        <span className={cx("text-[12.5px] font-semibold", s.kind === "anchor" ? "text-anchor" : "text-vo")}>{name}</span>
        <span className="text-[12px] text-g8">{wordsOf(s.text)} words</span>
        <div className="ml-auto flex items-center gap-2">
          <AnimatePresence>
            {Math.abs(delta) >= 0.5 && (
              <motion.span key={sec.toFixed(1)} initial={{ opacity: 1, y: 0 }} animate={{ opacity: 0, y: delta > 0 ? -6 : 6 }} transition={{ duration: 1.1 }}
                className={cx("font-mono text-[11px]", delta > 0 ? "text-warn" : "text-ok")}>
                {delta > 0 ? <ArrowUp size={11} weight="bold" className="inline" /> : <ArrowDown size={11} weight="bold" className="inline" />}{Math.abs(delta).toFixed(1)}s
              </motion.span>
            )}
          </AnimatePresence>
          <LiveSeconds sec={sec} measured={measured} className="text-[14px]" />
          {!locked && (
            <Menu trigger={<IconButton label="Part options" size="sm"><DotsThree size={18} weight="bold" /></IconButton>} items={[
              { label: vo ? "Rewrite this beat" : "Rewrite this part", icon: <Sparkle size={14} />, onSelect: () => onRewrite(s.id) },
              { label: "Split at the cursor", icon: <Scissors size={14} />, onSelect: () => splitAt(p.id, s.id, ta.current?.selectionStart ?? Math.floor(s.text.length / 2)), disabled: p.format === "anchor_only" },
              { label: vo ? "Merge with the next beat" : "Merge with the next part", icon: <ArrowsMerge size={14} />, onSelect: () => mergeNext(p.id, s.id), disabled: last || p.format === "anchor_only" },
              ...(vo ? [] : [{ label: s.kind === "anchor" ? "Make it a voiceover" : "Make it an anchor part", icon: s.kind === "anchor" ? <Microphone size={14} /> : <VideoCamera size={14} />, onSelect: () => turnInto(p.id, s.id, s.kind === "anchor" ? "vo" : "anchor"), disabled: p.format === "anchor_only" }]),
              { label: "Move up", icon: <ArrowUp size={14} />, onSelect: () => reorderSections(p.id, arrayMove(ids, index, index - 1)), disabled: index === 0 || p.format === "anchor_only" },
              { label: "Move down", icon: <ArrowDown size={14} />, onSelect: () => reorderSections(p.id, arrayMove(ids, index, index + 1)), disabled: last || p.format === "anchor_only" },
              "sep",
              { label: vo ? "Delete beat" : "Delete part", icon: <Trash size={14} />, onSelect: () => deleteSection(p.id, s.id), danger: true, disabled: sections(p).length < 2 },
            ]} />
          )}
        </div>
      </div>
      <textarea ref={ta} value={s.text} readOnly={locked} onChange={(e) => editSection(p.id, s.id, { text: e.target.value })} aria-label={`${name} text`}
        placeholder={vo ? "One idea, said over one kind of picture" : s.kind === "anchor" ? "What the anchor says on camera" : "What the anchor says over the pictures"}
        className={cx("block w-full resize-none bg-transparent px-4 pt-2 text-[15.5px] leading-[1.6] text-g10 outline-none [field-sizing:content] focus-visible:outline-none", vo ? "pb-2" : "pb-3.5")} />
      {vo && (
        <label className="mx-3 mb-2.5 flex items-start gap-2 rounded-sm px-1 py-1 text-[12.5px] leading-snug text-g8 focus-within:bg-g2">
          <Eye size={14} className="mt-px shrink-0" /><span className="shrink-0">On screen</span>
          <textarea rows={1} value={s.picture ?? ""} readOnly={locked} onChange={(e) => editSection(p.id, s.id, { picture: e.target.value })} aria-label={`${name}: what should be on screen`}
            placeholder="What the pictures should show" title={s.search ? `Footage search: ${s.search}` : undefined}
            className="min-w-0 flex-1 resize-none bg-transparent text-g9 outline-none [field-sizing:content] focus-visible:outline-none" />
        </label>
      )}
    </motion.li>
  );
}

const LT_MAX = { kicker: 14, headline: 48, subline: 70 } as const;
const TICKER_MAX = 90;
export const tickerOk = (p: Project) => p.ticker.filter((x) => x.trim()).length >= MIN_TICKER;

/** The one lower third and the ticker, edited next to a live preview of how they sit on the anchor shot. */
export function Graphics({ p, locked }: { p: Project; locked: boolean }) {
  return (
    <section className="mt-10" aria-labelledby="gfx-h">
      <div className="mb-3 flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h2 id="gfx-h" className="text-[17px] font-semibold">On-screen graphics</h2>
        <span className="text-[12.5px] text-g8">One lower third for the video, and the ticker that loops along the bottom.</span>
      </div>
      <div className="grid grid-cols-1 gap-5 2xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <GraphicsPreview p={p} />
        <div className="min-w-0 space-y-5">
          <LTEditor p={p} locked={locked} />
          <Ticker p={p} locked={locked} />
        </div>
      </div>
    </section>
  );
}

export function GraphicsPreview({ p }: { p: Project }) {
  const a = anchorOf(p.anchorId);
  const lines = p.ticker.filter((x) => x.trim());
  return (
    <div className="relative aspect-video overflow-hidden rounded-[2px] bg-g2 ring-1 ring-g4 [container-type:inline-size]">
      {a && <img src={a.frame} alt="" className="absolute inset-0 size-full object-cover" />}
      <div className="absolute top-[4.5%] right-[3.5%]"><Mark className="h-[4cqw] text-[2cqw]" /></div>
      <motion.div key={p.lt.headline + p.lt.kicker} className="absolute bottom-[15%] left-[5%] max-w-[78%]"
        initial={{ clipPath: "inset(0 100% 0 0)" }} animate={{ clipPath: "inset(0 0% 0 0)" }} transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }}>
        <div className="flex items-stretch">
          {p.lt.kicker && <span className="flex items-center bg-marker px-[0.8em] text-[2.2cqw] font-black tracking-wide text-white uppercase">{p.lt.kicker}</span>}
          <span className="bg-white px-[0.7em] py-[0.25em] text-[3.4cqw] leading-tight font-extrabold text-g0 uppercase" style={{ fontVariationSettings: '"wdth" 88' }}>{p.lt.headline || "Headline"}</span>
        </div>
        {p.lt.subline && <div className="mt-px inline-block bg-g0/85 px-[0.8em] py-[0.25em] text-[2.3cqw] text-white">{p.lt.subline}</div>}
      </motion.div>
      <div className="absolute inset-x-0 bottom-0 flex h-[7%] items-stretch overflow-hidden bg-g0/90 text-[2.2cqw] text-white">
        <span className="flex shrink-0 items-center bg-marker px-[0.9em] font-black">DNL</span>
        <div className="relative flex-1 overflow-hidden">
          <div className="absolute inset-y-0 flex animate-[ticker_var(--d)_linear_infinite] items-center whitespace-nowrap" style={{ "--d": `${Math.max(12, lines.join("").length / 9)}s` } as React.CSSProperties}>
            {[...lines, ...lines].map((x, i) => <span key={i} className="px-[1.5em] font-semibold uppercase">{x}<span className="ml-[1.5em] inline-block size-[0.45em] translate-y-[-0.1em] bg-marker" /></span>)}
          </div>
        </div>
      </div>
    </div>
  );
}

export function LTEditor({ p, locked }: { p: Project; locked: boolean }) {
  const lt = p.lt;
  const field = (k: keyof typeof LT_MAX, label: string, cls: string, ph: string) => (
    <label className="grid grid-cols-[76px_minmax(0,1fr)] items-center gap-3">
      <span className="text-[12px] text-g8">{label}</span>
      <span className="relative flex min-w-0 items-center">
        <input value={lt[k]} readOnly={locked} maxLength={LT_MAX[k] + 10} placeholder={ph} onChange={(e) => setLT(p.id, { [k]: e.target.value })}
          className={cx("h-9 w-full min-w-0 rounded-xs px-2.5 pr-14 outline-none placeholder:normal-case focus-visible:outline-none", cls)} />
        <span className={cx("pointer-events-none absolute right-2 font-mono text-[11px]", lt[k].length > LT_MAX[k] ? "font-semibold text-bad" : "text-g8")}>{lt[k].length}/{LT_MAX[k]}</span>
      </span>
    </label>
  );
  return (
    <div className="space-y-1.5 rounded-md border border-g4 bg-g1 p-4">
      <div className="mb-2 flex items-baseline justify-between"><h3 className="text-[13.5px] font-semibold">Lower third</h3><span className="text-[12px] text-g8">shown while the anchor is on camera</span></div>
      {field("kicker", "Place", "bg-marker font-black text-[12px] uppercase tracking-wide text-white placeholder:text-white/60", "e.g. MOSCOW")}
      {field("headline", "Headline", "bg-g10 text-g0 font-extrabold uppercase text-[13px] placeholder:text-g7", "What happened, in capitals")}
      {field("subline", "Line below", "bg-g3 text-g10 text-[13px] border border-g5", "One line of detail")}
    </div>
  );
}

export function Ticker({ p, locked }: { p: Project; locked: boolean }) {
  const [draft, setDraft] = useState("");
  const filled = p.ticker.filter((x) => x.trim()).length;
  const short = Math.max(0, MIN_TICKER - filled);
  const add = () => { if (draft.trim()) { setTicker(p.id, [...p.ticker, draft.trim()]); setDraft(""); } };
  return (
    <div className="rounded-md border border-g4 bg-g1" aria-labelledby="ticker-h">
      <div className="flex items-baseline justify-between gap-3 px-4 pt-3.5 pb-2">
        <h3 id="ticker-h" className="text-[13.5px] font-semibold">Ticker</h3>
        <span className={cx("text-[12px]", short ? "font-semibold text-warn" : "text-g8")}>
          <span className="edge">{filled}</span> lines{short ? ` · ${short} more needed (at least ${MIN_TICKER})` : ""}
        </span>
      </div>
      <ol className="border-t border-g4">
        <AnimatePresence initial={false}>
          {p.ticker.map((line, i) => (
            <motion.li key={i} layout initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }} exit={{ opacity: 0, height: 0 }} className="group flex items-center gap-3 border-b border-g4 px-4">
              <span className="w-4 shrink-0 font-mono text-[11px] text-edge">{String(i + 1).padStart(2, "0")}</span>
              <input value={line} readOnly={locked} aria-label={`Ticker line ${i + 1}`} onChange={(e) => setTicker(p.id, p.ticker.map((x, j) => (j === i ? e.target.value : x)))}
                className="h-10 min-w-0 flex-1 bg-transparent text-[13px] font-semibold tracking-wide uppercase outline-none focus-visible:outline-none" />
              <span className={cx("font-mono text-[11px]", line.length > TICKER_MAX ? "text-bad" : "text-g8")}>{line.length}/{TICKER_MAX}</span>
              {!locked && <IconButton label="Remove line" size="sm" className="opacity-0 group-hover:opacity-100 focus:opacity-100" onClick={() => setTicker(p.id, p.ticker.filter((_, j) => j !== i))}><X size={13} /></IconButton>}
            </motion.li>
          ))}
        </AnimatePresence>
        {!locked && (
          <li className="flex items-center gap-3 px-4">
            <Plus size={12} className="w-4 shrink-0 text-g8" />
            <input value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="Add a ticker line and press Enter" aria-label="New ticker line"
              onKeyDown={(e) => { if (e.key === "Enter") add(); }} onBlur={add}
              className="h-10 flex-1 bg-transparent text-[13px] outline-none focus-visible:outline-none" />
          </li>
        )}
      </ol>
    </div>
  );
}

// ------------------------------------------------------------------ right panel

function AnchorPanel({ p, locked }: { p: Project; locked: boolean }) {
  const a = anchorOf(p.anchorId);
  const [open, setOpen] = useState(false);
  const vo = p.format === "vo_only";
  return (
    <section aria-labelledby="anchor-h">
      <h2 id="anchor-h" className="mb-2.5 text-[13px] font-semibold text-g8">{vo ? "Voice" : "Anchor"}</h2>
      <div className="flex items-center gap-3 rounded-md border border-g4 bg-g1 p-3">
        {a && <img src={a.face} alt="" className="size-14 rounded-sm object-cover" />}
        <div className="min-w-0 flex-1">
          <div className="font-semibold">{a?.name}</div>
          <div className="text-[12.5px] text-g8"><span className="edge">{a?.wordsPerSecond.toFixed(2)}</span> words/s · {vo ? "not on camera" : p.tone.toLowerCase()}</div>
          {a && <VoiceSample a={a} />}
        </div>
        {!a && <span className="flex-1 text-[13px] text-g8">No {vo ? "voice" : "anchor"} chosen</span>}
        {!locked && <Button kind="ghost" size="sm" onClick={() => setOpen(true)}>Change</Button>}
      </div>
      <AnchorPicker open={open} onOpenChange={setOpen} p={p} />
    </section>
  );
}

export function VoiceSample({ a, compact }: { a: Anchor; compact?: boolean }) {
  const [on, setOn] = useState(false);
  const el = useRef<HTMLAudioElement | null>(null);
  function toggle(e: React.MouseEvent) {
    e.stopPropagation();
    if (!el.current) { el.current = new Audio(a.voiceSample); el.current.onended = () => setOn(false); }
    if (on) { el.current.pause(); setOn(false); } else { el.current.currentTime = 0; void el.current.play(); setOn(true); }
  }
  return (
    <button onClick={toggle} className={cx("mt-1 inline-flex items-center gap-1.5 text-[12.5px] font-medium text-g9 hover:text-g10", compact && "mt-0")} aria-label={`${on ? "Stop" : "Hear"} ${a.name}'s voice`}>
      {on ? <Pause size={12} weight="fill" /> : <Play size={12} weight="fill" />}{on ? "Playing" : "Hear the voice"}
      {on && <span className="flex h-3 items-end gap-[2px]">{[0, 1, 2, 3].map((i) => <motion.span key={i} className="w-[2px] bg-marker" animate={{ height: ["30%", "100%", "45%"] }} transition={{ duration: 0.6, repeat: Infinity, delay: i * 0.12 }} />)}</span>}
    </button>
  );
}

const REGION: Record<string, string> = { europe: "Europe", russia_ukraine: "Russia & Ukraine", global: "Global", africa: "Africa", middle_east: "Middle East", turkey: "Turkey", latin_america: "Latin America", south_asia: "South Asia", north_america: "North America", caribbean: "Caribbean", oceania: "Oceania", uk: "UK", east_asia: "East Asia", southeast_asia: "Southeast Asia" };
export const regionName = (r: string) => REGION[r] ?? r;

export function AnchorPicker({ open, onOpenChange, p }: { open: boolean; onOpenChange: (v: boolean) => void; p: Project }) {
  const anchors = useStore((s) => s.anchors).filter((a) => a.offered);
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title={p.format === "vo_only" ? "Choose the voice" : "Choose the anchor"} wide>
      {p.format === "vo_only" && <p className="border-b border-g4 px-5 py-3 text-[12.5px] text-g8">VO only shows no anchor on screen. The anchor you choose reads the script.</p>}
      <div className="grid grid-cols-2 gap-3 p-5 sm:grid-cols-3 md:grid-cols-5" role="radiogroup" aria-label={p.format === "vo_only" ? "Voice" : "Anchor"}>
        {anchors.map((a) => {
          const on = a.id === p.anchorId;
          return (
            <div key={a.id} role="radio" aria-checked={on} tabIndex={0} onClick={() => { setAnchor(p.id, a.id); onOpenChange(false); }}
              onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setAnchor(p.id, a.id); onOpenChange(false); } }}
              className={cx("group cursor-pointer rounded-md border p-2 text-left transition-colors", on ? "border-marker bg-marker/8" : "border-g4 hover:border-g6")}>
              <div className="relative aspect-[4/5] overflow-hidden rounded-sm bg-g3">
                <img src={a.face} alt="" className="size-full object-cover transition-transform duration-300 group-hover:scale-[1.03]" />
                {on && <span className="absolute top-1.5 right-1.5 grid size-5 place-items-center rounded-full bg-marker"><Check size={12} weight="bold" /></span>}
              </div>
              <div className="mt-2 text-[13px] font-semibold">{a.name}</div>
              <div className="truncate text-[11.5px] text-g8">{a.regions.map(regionName).join(", ")}</div>
              <VoiceSample a={a} />
            </div>
          );
        })}
      </div>
      {p.stage !== "script" && <p className="border-t border-g4 px-5 py-3 text-[12.5px] text-warn">Changing the {p.format === "vo_only" ? "voice makes a new voice for every beat" : "anchor makes a new voice for every part"} (about 3 minutes on the GPU).</p>}
    </Dialog>
  );
}

function Facts({ p, locked, writing }: { p: Project; locked: boolean; writing: boolean }) {
  return (
    <section className="mt-7" aria-labelledby="facts-h">
      <div className="mb-2.5 flex items-baseline justify-between"><h2 id="facts-h" className="text-[13px] font-semibold text-g8">From the source</h2><span className="text-[11.5px] text-g8">edit any fact</span></div>
      {writing && p.facts.length === 0 ? <div className="space-y-2">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-11" />)}</div> : (
        <dl className="divide-y divide-g4 rounded-md border border-g4 bg-g1">
          {p.facts.map((f, i) => (
            <div key={i} className="grid grid-cols-[76px_minmax(0,1fr)] gap-3 px-3 py-2.5">
              <dt className="pt-0.5 text-[12px] font-semibold text-g8">{f.label}</dt>
              <dd>
                <textarea value={f.value} readOnly={locked} onChange={(e) => setFact(p.id, i, e.target.value)} aria-label={f.label} placeholder="Not found in the source"
                  className="block w-full resize-none bg-transparent text-[13.5px] leading-snug text-g10 outline-none [field-sizing:content] focus-visible:outline-none" />
              </dd>
            </div>
          ))}
        </dl>
      )}
    </section>
  );
}

function SourceCard({ p }: { p: Project }) {
  const icon = p.source.kind === "link" ? <LinkIcon size={14} /> : p.source.kind === "file" ? <FileText size={14} /> : <TextAa size={14} />;
  return (
    <section className="mt-7" aria-labelledby="src-h">
      <h2 id="src-h" className="mb-2.5 text-[13px] font-semibold text-g8">Source</h2>
      <div className="rounded-md border border-g4 bg-g1 p-3 text-[13px]">
        <div className="flex items-center gap-2 text-g9">{icon}{p.source.url ? <a href={p.source.url} target="_blank" rel="noreferrer" className="truncate underline decoration-g6 hover:text-g10">{p.source.site ?? p.source.url}</a> : <span>{p.source.name ?? p.source.site ?? "Pasted text"}</span>}</div>
        {p.source.text && <p className="mt-2 line-clamp-6 text-[12.5px] leading-relaxed text-g8">{p.source.text.replace(/^#+\s*/gm, "")}</p>}
      </div>
    </section>
  );
}

// ------------------------------------------------------------------ AI rewrite

const CHIPS = ["Too long", "Too short", "More context", "Simpler", "Stronger opening", "Change the tone"];

function RewriteSheet({ p, scope, onClose }: { p: Project; scope: RewriteAsk["scope"] | null; onClose: () => void }) {
  const [chips, setChips] = useState<string[]>([]);
  const [note, setNote] = useState("");
  const [sc, setSc] = useState<RewriteAsk["scope"]>("all");
  const [busy, setBusy] = useState(false);
  const [props, setProps] = useState<Record<string, string> | null>(null);
  const [decided, setDecided] = useState(0);
  const open = scope !== null;
  const list = sections(p);
  const label = useMemo(() => { let a = 0; let v = 0; return Object.fromEntries(list.map((s, i) => [s.id, p.format === "vo_only" ? `Beat ${i + 1}` : s.kind === "anchor" ? `Anchor ${++a}` : `Voiceover ${++v}`])); }, [list, p.format]);

  function reset(v: boolean) { if (!v) { onClose(); setProps(null); setChips([]); setNote(""); } }
  async function run() {
    setBusy(true);
    const r = await proposeRewrite(p.id, { scope: sc, chips, note });
    setBusy(false); setProps(r); setDecided(0);
  }
  // start from the scope the sheet was opened with (only on open: the user's own choice must not be reset each render)
  useEffect(() => { if (scope) setSc(scope); }, [scope]);

  return (
    <Sheet open={open} onOpenChange={reset} title={props ? "Compare and choose" : "Rewrite with AI"} width={props ? 860 : 440}>
      {!props ? (
        <div className="space-y-6 p-5">
          <div>
            <div className="mb-2 text-[13px] font-semibold">What to rewrite</div>
            <Segmented label="Rewrite scope" value={sc === "all" ? "all" : "one"} set={(v) => setSc(v === "all" ? "all" : (scope && scope !== "all" ? scope : list[0].id))}
              options={[{ v: "all", l: "Whole script" }, { v: "one", l: sc !== "all" ? label[sc] ?? "One part" : p.format === "vo_only" ? "One beat" : "One part" }]} />
            {sc !== "all" && (
              <select value={sc} onChange={(e) => setSc(e.target.value)} className="mt-2 h-8 w-full rounded-sm border border-g5 bg-g1 px-2 text-[13px] text-g10" aria-label="Which part">
                {list.map((s) => <option key={s.id} value={s.id}>{label[s.id]}</option>)}
              </select>
            )}
          </div>
          <div>
            <div className="mb-2 text-[13px] font-semibold">What should change?</div>
            <div className="flex flex-wrap gap-1.5">
              {CHIPS.map((c) => {
                const on = chips.includes(c);
                return <button key={c} aria-pressed={on} onClick={() => setChips(on ? chips.filter((x) => x !== c) : [...chips, c])}
                  className={cx("h-8 rounded-full border px-3 text-[13px] transition-colors", on ? "border-marker bg-marker/12 text-g10" : "border-g5 text-g9 hover:border-g7")}>{on && <Check size={12} weight="bold" className="mr-1 inline text-marker-ink" />}{c}</button>;
              })}
            </div>
          </div>
          <div>
            <label htmlFor="rw-note" className="mb-2 block text-[13px] font-semibold">Anything else</label>
            <Textarea id="rw-note" rows={4} value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. Mention that the airports reopened by morning. Keep the mayor's quote." />
            <p className="mt-2 text-[12.5px] text-g8">Uses only the source article, the facts on the right (your edits count) and facts you type here. Nothing changes until you choose.</p>
          </div>
          <Button kind="primary" className="w-full" disabled={busy || (!chips.length && !note.trim())} onClick={run}>
            {busy ? <><span className="size-3.5 animate-spin rounded-full border-2 border-white/40 border-t-white" />Rewriting</> : <>Rewrite</>}
          </Button>
        </div>
      ) : (
        <div className="p-5">
          {Object.keys(props).length === 0 ? (
            <p className="text-[13.5px] text-g8">{decided ? "All changes decided. Press Done, or Ask again for another rewrite." : "Nothing to change for that request. Try a different instruction."}</p>
          ) : (
            <div className="space-y-4">
              {Object.entries(props).map(([sid, text]) => {
                const s = list.find((x) => x.id === sid); if (!s) return null;
                const before = sectionSeconds(s, p.anchorId).sec;
                const after = wordsOf(text) / (anchorOf(p.anchorId)?.wordsPerSecond ?? 2.5);
                return (
                  <Proposal key={sid} title={label[sid]} before={s.text} after={text} beforeSec={before} afterSec={after}
                    use={() => { editSection(p.id, sid, { text }); setDecided((d) => d + 1); setProps((x) => { const n = { ...x! }; delete n[sid]; return n; }); }}
                    keep={() => { setDecided((d) => d + 1); setProps((x) => { const n = { ...x! }; delete n[sid]; return n; }); }} />
                );
              })}
            </div>
          )}
          <div className="mt-5 flex justify-between">
            <Button kind="ghost" onClick={() => setProps(null)}>Ask again</Button>
            <Button kind="secondary" onClick={() => reset(false)}>Done</Button>
          </div>
        </div>
      )}
    </Sheet>
  );
}

function Proposal({ title, before, after, beforeSec, afterSec, use, keep }: { title: string; before: string; after: string; beforeSec: number; afterSec: number; use: () => void; keep: () => void }) {
  return (
    <motion.div layout initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="overflow-hidden rounded-md border border-g4">
      <div className="flex items-center justify-between border-b border-g4 bg-g2 px-3 py-2 text-[13px] font-semibold">{title}
        <span className="flex items-center gap-2"><Button kind="quiet" size="sm" onClick={keep}>Keep mine</Button><Button kind="primary" size="sm" onClick={use}>Use new</Button></span>
      </div>
      <div className="grid md:grid-cols-2">
        <div className="border-g4 p-3.5 md:border-r"><div className="mb-1.5 flex justify-between text-[11.5px] text-g8"><span>Now</span><span className="edge">{mmss(beforeSec)}</span></div><p className="text-[14px] leading-relaxed text-g8"><Diff a={before} b={after} side="old" /></p></div>
        <div className="bg-ok/[0.04] p-3.5"><div className="mb-1.5 flex justify-between text-[11.5px] text-g8"><span>New</span><span className="edge">{mmss(afterSec)}</span></div><p className="text-[14px] leading-relaxed text-g10"><Diff a={before} b={after} /></p></div>
      </div>
    </motion.div>
  );
}

/** Word diff: new words highlighted. */
/** Word diff (LCS). "old" marks what goes, "new" marks what comes in. */
function Diff({ a, b, side = "new" }: { a: string; b: string; side?: "old" | "new" }) {
  const A = a.split(/\s+/).filter(Boolean); const B = b.split(/\s+/).filter(Boolean);
  // ponytail: O(n*m) table, fine for a section (a few hundred words)
  const L = Array.from({ length: A.length + 1 }, () => new Array<number>(B.length + 1).fill(0));
  for (let i = A.length - 1; i >= 0; i--) for (let j = B.length - 1; j >= 0; j--) L[i][j] = A[i] === B[j] ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
  const out: { w: string; ch: boolean }[] = [];
  let i = 0, j = 0;
  while (i < A.length || j < B.length) {
    if (i < A.length && j < B.length && A[i] === B[j]) { out.push({ w: side === "old" ? A[i] : B[j], ch: false }); i++; j++; }
    else if (j < B.length && (i >= A.length || L[i][j + 1] >= L[i + 1][j])) { if (side === "new") out.push({ w: B[j], ch: true }); j++; }
    else { if (side === "old") out.push({ w: A[i], ch: true }); i++; }
  }
  return <>{out.map((x, k) => <span key={k}>{k ? " " : ""}{x.ch ? (side === "new" ? <mark className="rounded-[2px] bg-ok/20 text-g10">{x.w}</mark> : <del className="text-bad/80 decoration-bad/70">{x.w}</del>) : x.w}</span>)}</>;
}
