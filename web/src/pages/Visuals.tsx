import { useMemo, useRef, useState, type DragEvent } from "react";
import { useNavigate } from "react-router";
import { AnimatePresence, motion } from "motion/react";
import { DndContext, closestCenter, PointerSensor, KeyboardSensor, useSensor, useSensors, type DragEndEvent } from "@dnd-kit/core";
import { SortableContext, useSortable, verticalListSortingStrategy, arrayMove, sortableKeyboardCoordinates } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import {
  VideoCamera, Microphone, Plus, X, ArrowClockwise, Lock, ArrowRight, DotsSixVertical, Trash, MagicWand,
  UploadSimple, MagnifyingGlass, Image as ImageIcon, MapTrifold, FilmStrip, CircleNotch, CheckCircle, Circle, WarningCircle,
} from "@phosphor-icons/react";
import {
  useStore, sections, fillOf, frameCode, mediaOf, place, unplace, updatePlaced, reorderPlaced, addKeyword, removeKeyword, researchKeyword, addUpload, removeUpload, removeMap,
  addMap, queueRender, anchorOf, toast, storyPool,
} from "@/data/store";
import type { FoundVideo, Project, Section } from "@/data/types";
import { useProject, FormatSwitch } from "@/components/story";
import { Button, FillBar, IconButton, Segmented, Tip, cx, mmss, Empty, Skeleton } from "@/components/ui";
import { Frame, MarkerLoop } from "@/components/frames";
import { ClipViewer, type ViewerTarget } from "@/components/clipviewer";
import { MapMaker } from "@/components/mapmaker";
import VoEdit from "./VoEdit";

type Source = "found" | "photos" | "uploads" | "maps";
type Filter = "all" | "strong" | "clean";

export default function VisualsPage() {
  const p = useProject()!;
  return p.format === "vo_only" ? <VoEdit p={p} /> : <AnchorVisuals p={p} />;
}

function AnchorVisuals({ p }: { p: Project }) {
  const nav = useNavigate();
  const list = sections(p);
  const firstShort = list.find((s) => !fillOf(p, s).full);
  const [sid, setSid] = useState<string>(firstShort?.id ?? list[0]?.id);
  const s = list.find((x) => x.id === sid) ?? list[0];
  const locked = p.stage === "render" || p.stage === "done";
  const short = list.filter((x) => !fillOf(p, x).full);
  const names = useNames(list);

  if (!s) return <Empty icon={<FilmStrip size={32} />} title="No parts yet">Write and approve the script first.</Empty>;
  return (
    <div className="mx-auto grid grid-cols-1 max-w-[1680px] lg:h-[calc(100vh-52px)] lg:grid-cols-[232px_minmax(0,1fr)_340px]">
      <SectionRail p={p} list={list} sid={s.id} setSid={setSid} names={names} />
      <Center key={s.id} p={p} s={s} name={names[s.id]} locked={locked} />
      <Picked p={p} s={s} name={names[s.id]} locked={locked}
        footer={
          <div className="space-y-2">
            <FormatSwitch p={p} locked={locked} />
            {short.length > 0 ? (
              <Tip label="Every part needs its pictures before review">
                <button onClick={() => setSid(short[0].id)} className="flex h-11 w-full items-center justify-center gap-2 rounded-sm border border-dashed border-g6 text-[13px] text-g9 transition-colors hover:border-g8 hover:text-g10">
                  <Lock size={14} />{missingText(p, short[0], names[short[0].id])}{short.length > 1 && <span className="text-g8">+{short.length - 1} more</span>}
                </button>
              </Tip>
            ) : (
              <Button kind="primary" size="lg" className="w-full" disabled={locked} onClick={() => { queueRender(p.id); nav("/desk"); }}>
                {locked ? (p.stage === "done" ? "Rendered" : "Queued for tonight\u2019s render") : "Continue"} <ArrowRight size={16} weight="bold" />
              </Button>
            )}
          </div>
        } />
    </div>
  );
}

function useNames(list: Section[]) {
  return useMemo(() => { let a = 0; let v = 0; return Object.fromEntries(list.map((s) => [s.id, s.kind === "anchor" ? `Anchor ${++a}` : `VO ${++v}`])); }, [list]);
}
function missingText(p: Project, s: Section, name: string) {
  const f = fillOf(p, s);
  return s.kind === "anchor" ? `${name} needs a picture` : `${name} needs ${Math.ceil(f.need - f.have)} s more`;
}

// ------------------------------------------------------------------ left: sections, heights proportional to seconds

function SectionRail({ p, list, sid, setSid, names }: { p: Project; list: Section[]; sid: string; setSid: (s: string) => void; names: Record<string, string> }) {
  const job = useStore((s) => s.jobs[p.id]);
  const total = list.reduce((n, s) => n + fillOf(p, s).need, 0);
  return (
    <nav aria-label="Parts" className="border-g4 px-3 pt-5 pb-6 lg:overflow-auto lg:border-r">
      <div className="mb-3 flex items-baseline justify-between px-1">
        <span className="text-[13px] font-semibold">Parts</span>
        <span className="edge text-[12px]">{mmss(total)}</span>
      </div>
      <ol className="flex gap-2 overflow-x-auto pb-1 lg:block lg:space-y-1 lg:overflow-visible lg:pb-0">
        {list.map((s, i) => {
          const f = fillOf(p, s);
          const on = s.id === sid;
          // ponytail: 7 px per second of voice, 44 px floor; parts shorter than 8 s drop the snippet
          const h = Math.max(44, f.need * 7);
          const compact = f.need < 8;
          const searching = job?.kind === "search" && !job.failed && !p.visuals[s.id]?.keywords.length && (s.kind === "vo" || !list.some((x) => x.kind === "vo"));   // only the parts the search covers
          const status = job?.kind === "search" && !job.failed ? job.parts?.[s.id] : undefined;
          return (
            <li key={s.id} className="w-[200px] shrink-0 lg:w-auto">
              <button onClick={() => setSid(s.id)} aria-current={on ? "true" : undefined} style={{ "--h": `${h}px` } as React.CSSProperties}
                className={cx("relative flex h-full w-full flex-col justify-between rounded-sm border px-3 py-2 text-left lg:h-[var(--h)] lg:min-h-0 transition-[background,border-color] duration-150",
                  on ? "border-g7 bg-g3" : "border-g4 bg-g1 hover:border-g6")}>
                {on && <motion.span layoutId="rail-on" className="absolute inset-x-2 -bottom-px h-[3px] rounded-t bg-marker lg:inset-x-auto lg:top-2 lg:bottom-2 lg:-left-[13px] lg:h-auto lg:w-[3px] lg:rounded-t-none lg:rounded-r" />}
                <span className="narrow flex items-center gap-1.5 text-[13.5px] font-semibold">
                  {s.kind === "anchor" ? <VideoCamera size={13} weight="fill" className="text-anchor" /> : <Microphone size={13} weight="fill" className="text-vo" />}
                  {names[s.id]}
                  <span className="ml-auto edge text-[11.5px]">{mmss(f.need)}</span>
                </span>
                {!compact && <span className="mt-0.5 line-clamp-1 text-[11.5px] leading-snug text-g8">{s.text}</span>}
                <span className="mt-1.5 block">
                  <FillBar have={f.have} need={f.need} />
                  <span className={cx("mt-1 items-center justify-between text-[11px]", compact ? "hidden" : "flex")}>
                    {status || searching ? <span className="flex min-w-0 items-center gap-1 text-g8"><CircleNotch size={11} className="shrink-0 animate-spin" /><span className="truncate">{status ?? "Searching"}</span></span>
                      : f.full ? <span className="flex items-center gap-1 text-ok"><CheckCircle size={11} weight="fill" />{s.kind === "anchor" ? "Picture set" : "Filled"}</span>
                      : <span className="text-warn">{s.kind === "anchor" ? "Needs a picture" : `${Math.ceil(f.need - f.have)} s short`}</span>}
                    <span className="font-mono text-g8">R{String(i + 1).padStart(2, "0")}</span>
                  </span>
                </span>
              </button>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

// ------------------------------------------------------------------ centre: what was found

function Center({ p, s, name, locked }: { p: Project; s: Section; name: string; locked: boolean }) {
  const own = p.visuals[s.id] ?? { keywords: [], found: [], photos: [], uploads: [], maps: [], placed: [] };
  const isAnchor = s.kind === "anchor";
  const pool = useMemo(() => storyPool(p, s.id), [p, s.id]);
  const v = isAnchor ? { ...own, found: pool.found, photos: pool.photos } : own;   // anchor parts pick from the whole story
  const searching = useStore((st) => st.jobs[p.id]?.kind === "search");
  const status = useStore((st) => { const j = st.jobs[p.id]; return j?.kind === "search" && !j.failed ? j.parts?.[s.id] : undefined; });
  const roll = sections(p).findIndex((x) => x.id === s.id) + 1;
  const [src, setSrc] = useState<Source>(isAnchor && v.photos.length ? "photos" : "found");
  const [filter, setFilter] = useState<Filter>("all");
  const [viewer, setViewer] = useState<ViewerTarget | null>(null);
  const a = anchorOf(p.anchorId);

  const tiles = useMemo(() => {
    const out: { video: FoundVideo; moment: number; code: string }[] = [];
    v.found.forEach((f, fi) => {
      if (filter === "strong" && f.relevance < 70) return;
      if (filter === "clean" && f.flags.length) return;
      f.moments.forEach((_, mi) => out.push({ video: f, moment: mi, code: frameCode(roll, fi + 1) + (f.moments.length > 1 ? String.fromCharCode(97 + mi) : "") }));
    });
    return out;
  }, [v.found, filter, roll]);
  const pickedNo = (videoId: string, moment: number) => {
    const i = v.placed.findIndex((x) => x.ref.kind === "moment" && x.ref.videoId === videoId && x.ref.moment === moment);
    return i < 0 ? undefined : i + 1;
  };
  function use(t: { videoId: string; moment: number; in: number; out: number; muted: boolean; useTreated: boolean }) {
    if (locked) return;
    if (v.found.find((y) => y.id === t.videoId)?.moments[t.moment]?.cutFailed) { toast("This moment could not be downloaded, so it can't be used.", "bad"); return; }
    if (isAnchor) v.placed.forEach((x) => unplace(p.id, s.id, x.id));
    const f = v.found.find((y) => y.id === t.videoId);
    place(p.id, s.id, { ref: { kind: "moment", videoId: t.videoId, moment: t.moment }, in: t.in, out: isAnchor ? fillOf(p, s).need : t.out, muted: t.muted, useTreated: t.useTreated });
    if (f && !f.moments[t.moment]?.clip) toast("Cutting the clip from the video. It is ready in a few seconds.");
    setViewer(null);
  }
  const quick = (video: FoundVideo, moment: number) => {
    const m = video.moments[moment];
    use({ videoId: video.id, moment, in: 0, out: m.clip ? Math.min(5, m.end - m.start) : 5, muted: true, useTreated: !!m.treat });
  };
  const idx = viewer ? tiles.findIndex((t) => t.video.id === viewer.video.id && t.moment === viewer.moment) : -1;

  return (
    <section className="min-w-0 px-5 pt-5 pb-10 lg:overflow-auto lg:px-7" aria-labelledby="part-h">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <h2 id="part-h" className="flex items-center gap-2 text-[19px] font-semibold">
            {isAnchor ? <VideoCamera size={18} weight="fill" className="text-anchor" /> : <Microphone size={18} weight="fill" className="text-vo" />}{name}
            {isAnchor && <span className="text-[14px] font-normal text-g8">· the screen behind {a?.name.split(" ")[0]}</span>}
          </h2>
          <p className="mt-1 max-w-[80ch] text-[13.5px] leading-relaxed text-g8">{s.text}</p>
        </div>
      </div>

      <Keywords p={p} s={s} locked={locked} />

      <div className="sticky top-0 z-10 -mx-5 mt-4 flex flex-wrap items-center gap-3 border-b border-g4 bg-g0/95 px-5 py-2.5 backdrop-blur lg:-mx-7 lg:px-7">
        <div role="tablist" aria-label="Sources" className="-mx-1 flex max-w-full items-center gap-1 overflow-x-auto px-1 [scrollbar-width:none]">
          {([["found", "Found footage", v.found.length, FilmStrip], ["photos", "Photos", v.photos.length, ImageIcon], ["uploads", "Your uploads", v.uploads.length, UploadSimple], ["maps", "Maps", v.maps.length, MapTrifold]] as const).map(([k, l, n, I]) => (
            <button key={k} role="tab" aria-selected={src === k} onClick={() => setSrc(k)}
              className={cx("narrow relative flex h-8 shrink-0 items-center gap-1.5 rounded-sm px-3 text-[13.5px] font-medium whitespace-nowrap transition-colors", src === k ? "text-g10" : "text-g8 hover:text-g10")}>
              {src === k && <motion.span layoutId="src-tab" className="absolute inset-0 rounded-sm bg-g3 ring-1 ring-g5" transition={{ duration: 0.22 }} />}
              <I size={14} className="relative" /><span className="relative">{l}</span><span className="relative edge text-[11px]">{n}</span>
            </button>
          ))}
        </div>
        {src === "found" && (
          <div className="flex max-w-full items-center gap-2 overflow-x-auto [scrollbar-width:none] lg:ml-auto">
            <Segmented size="sm" label="Show" value={filter} set={setFilter} options={[{ v: "all", l: "All" }, { v: "strong", l: "Strong fit" }, { v: "clean", l: "No logos or text" }]} />
          </div>
        )}
      </div>

      <div className="pt-5">
        {src === "found" && (
          v.found.length === 0 ? (
            v.keywords.some((k) => k.state === "searching") || searching
              ? <div className="grid grid-cols-2 gap-x-4 gap-y-6 md:grid-cols-3 2xl:grid-cols-4">{Array.from({ length: 8 }, (_, i) => <Skeleton key={i} className="aspect-video" />)}</div>
              : <Empty icon={<MagnifyingGlass size={30} />} title="No footage found for this part" action={<span className="text-[13px] text-g8">Add a keyword above, upload your own, or make a map.</span>}>
                  The search found nothing usable with these keywords. Try another keyword.
                </Empty>
          ) : (
            <div className="rounded-md bg-[#060607] p-4 ring-1 ring-g4">
            <div className="mb-4 flex flex-wrap gap-x-3 font-mono text-[11.5px] tracking-wide text-edge uppercase">
              <span>Roll {String(roll).padStart(2, "0")}</span><span className="text-g6">·</span>
              <span>{v.found.length} videos</span><span className="text-g6">·</span>
              <span>{tiles.length} frames</span><span className="text-g6">·</span>
              <span>{v.placed.length} picked</span><span className="text-g6">·</span>
              <span>{mmss(fillOf(p, s).have)} of {mmss(fillOf(p, s).need)}</span>
              {status && <><span className="text-g6">·</span><span className="flex items-center gap-1 text-g9 normal-case"><CircleNotch size={11} className="animate-spin" />{status}</span></>}
            </div>
            <div className="grid grid-cols-2 gap-x-4 gap-y-6 md:grid-cols-3 xl:grid-cols-4">
              {tiles.map((t, i) => {
                const m = t.video.moments[t.moment]!;
                return <Frame key={`${t.video.id}-${t.moment}`} src={m.poster ?? t.video.thumb} code={t.code} label={m.label} sub={t.video.channel}
                  seconds={m.clip ? m.end - m.start : undefined} score={m.score ?? t.video.relevance} estimated={m.estimated} flags={m.flags ?? (t.moment === 0 ? t.video.flags : undefined)}
                  noClip={!m.clip && !t.video.source} cutFailed={m.cutFailed} picked={pickedNo(t.video.id, t.moment)} seed={i} onOpen={() => setViewer(t)} onAdd={locked || m.cutFailed ? undefined : () => quick(t.video, t.moment)} />;
              })}
              {tiles.length === 0 && <p className="col-span-full text-[13px] text-g8">Nothing matches this filter.</p>}
            </div>
            </div>
          )
        )}
        {src === "photos" && <Stills kind="photo" items={v.photos.map((x) => ({ id: x.id, src: x.src, label: x.caption, sub: x.credit }))} p={p} s={s} roll={roll} locked={locked} />}
        {src === "uploads" && <Uploads p={p} s={s} roll={roll} locked={locked} />}
        {src === "maps" && (
          <div className="space-y-8">
            {!locked && <MapMaker suggest={`${s.text} ${p.headline}`} onAdd={async (m) => { const made = await addMap(p.id, s.id, m); if (!made) return; place(p.id, s.id, { ref: { kind: "map", id: made.id }, in: 0, out: isAnchor ? fillOf(p, s).need : 4, muted: true, useTreated: false }); toast("Map added and placed"); }} />}
            {v.maps.length > 0 && <Stills kind="map" items={v.maps.map((x) => ({ id: x.id, src: x.src, label: x.title }))} p={p} s={s} roll={roll} locked={locked} />}
          </div>
        )}
      </div>

      <ClipViewer pid={p.id} target={viewer} onClose={() => setViewer(null)} onUse={use} useLabel={isAnchor ? "Put behind the anchor" : `Use in ${name}`}
        placedAs={viewer ? pickedNo(viewer.video.id, viewer.moment) : undefined}
        next={idx >= 0 && idx < tiles.length - 1 ? () => setViewer(tiles[idx + 1]) : undefined}
        prev={idx > 0 ? () => setViewer(tiles[idx - 1]) : undefined} />
      {/* the next moment is preloaded so stepping through is instant */}
      {idx >= 0 && tiles[idx + 1]?.video.moments[tiles[idx + 1].moment].clip && <link rel="prefetch" href={tiles[idx + 1].video.moments[tiles[idx + 1].moment].clip} />}
    </section>
  );
}

function Keywords({ p, s, locked }: { p: Project; s: Section; locked: boolean }) {
  const v = p.visuals[s.id];
  const [text, setText] = useState("");
  if (!v) return null;
  return (
    <div className="mt-4 flex flex-wrap items-center gap-1.5">
      <span className="mr-1 text-[12.5px] text-g8">Keywords</span>
      <AnimatePresence initial={false}>
        {v.keywords.map((k) => (
          <motion.span key={k.id} layout initial={{ opacity: 0, scale: 0.9 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.9 }}
            className={cx("group inline-flex h-7 max-w-full items-center gap-1.5 rounded-full border pr-1 pl-3 text-[12.5px]", k.state === "searching" ? "border-vo/50 text-g10" : "border-g5 text-g9")}>
            <Tip label={<span>{k.state === "idle" ? "Suggested, not searched yet. Press the arrow to search it." : k.state === "queued" ? "Waiting to be searched" : k.state === "error" ? "This search failed. Press the arrow to try again." : k.reason || "Suggested by the footage search"}{k.progress ? <><br /><span className="text-g8">{k.progress}</span></> : null}</span>}><span className="truncate">{k.text}</span></Tip>
            {k.state === "searching" ? <CircleNotch size={13} className="animate-spin text-vo" />
              : k.state === "done" ? <CheckCircle size={13} weight="fill" className="text-ok/80" />
              : k.state === "error" ? <WarningCircle size={13} weight="fill" className="text-warn" />
              : <Circle size={13} className="text-g7" />}
            {!locked && <>
              <IconButton label={k.state === "idle" ? "Search this" : "Search again"} size="sm" className="size-5 opacity-0 group-hover:opacity-100 focus:opacity-100" onClick={() => researchKeyword(p.id, s.id, k.id)}><ArrowClockwise size={11} /></IconButton>
              <IconButton label="Remove keyword" size="sm" className="size-5 opacity-0 group-hover:opacity-100 focus:opacity-100" onClick={() => removeKeyword(p.id, s.id, k.id)}><X size={11} /></IconButton>
            </>}
          </motion.span>
        ))}
      </AnimatePresence>
      {!locked && (
        <form onSubmit={(e) => { e.preventDefault(); if (text.trim()) { addKeyword(p.id, s.id, text.trim()); setText(""); } }} className="inline-flex">
          <label className="flex h-7 items-center gap-1 rounded-full border border-dashed border-g6 pr-1 pl-2.5 focus-within:border-g8">
            <Plus size={12} className="text-g8" />
            <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Add a keyword" aria-label="Add a keyword and search"
              className="w-[150px] bg-transparent text-[12.5px] outline-none focus-visible:outline-none" />
          </label>
        </form>
      )}
    </div>
  );
}


function Stills({ kind, items, p, s, roll, locked }: { kind: "photo" | "map" | "upload"; items: { id: string; src: string; label: string; sub?: string; video?: boolean; seconds?: number }[]; p: Project; s: Section; roll: number; locked: boolean }) {
  const v = p.visuals[s.id];
  const isAnchor = s.kind === "anchor";
  if (!items.length) return <Empty icon={<ImageIcon size={30} />} title="No photos for this part">Photos come from the story's own coverage. Upload your own or make a map.</Empty>;
  return (
    <div className="grid grid-cols-2 gap-x-4 gap-y-6 md:grid-cols-3 2xl:grid-cols-4">
      {items.map((x, i) => {
        const at = v.placed.findIndex((y) => y.ref.kind === kind && y.ref.id === x.id);
        const add = () => {
          if (isAnchor) v.placed.forEach((y) => unplace(p.id, s.id, y.id));
          place(p.id, s.id, { ref: { kind, id: x.id }, in: 0, out: isAnchor ? fillOf(p, s).need : x.seconds ?? 4, muted: true, useTreated: false });
        };
        return (
          <div key={x.id} className="relative">
            <Frame kind={kind} src={x.video ? "" : x.src} code={`${kind === "map" ? "MAP" : kind === "upload" ? "UP" : "PH"}·${String(roll).padStart(2, "0")}${String.fromCharCode(97 + i)}`}
              label={x.label} sub={x.sub} seconds={x.seconds} picked={at < 0 ? undefined : at + 1} seed={i + 3} onOpen={locked ? undefined : add} onAdd={locked ? undefined : add} />
            {kind === "map" && !locked && <IconButton label={`Remove ${x.label}`} size="sm" className="absolute top-1 right-1 bg-black/60" onClick={() => removeMap(p.id, s.id, x.id)}><Trash size={13} /></IconButton>}
          </div>
        );
      })}
    </div>
  );
}

function Uploads({ p, s, roll, locked }: { p: Project; s: Section; roll: number; locked: boolean }) {
  const v = p.visuals[s.id];
  const [over, setOver] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  async function take(files: FileList | null) {
    for (const f of Array.from(files ?? [])) {
      const isVid = f.type.startsWith("video/");
      if (!isVid && !f.type.startsWith("image/")) { toast(`${f.name}: use a video or an image file`, "bad"); continue; }
      await addUpload(p.id, s.id, f);
    }
  }
  const drop = (e: DragEvent) => { e.preventDefault(); setOver(false); void take(e.dataTransfer.files); };
  return (
    <div className="space-y-6">
      {!locked && (
        <div onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)} onDrop={drop}
          className={cx("flex flex-col items-center rounded-md border border-dashed px-6 py-10 text-center transition-colors", over ? "border-marker bg-marker/5" : "border-g6")}>
          <UploadSimple size={26} className="text-g8" />
          <p className="mt-3 text-[14px] text-g10">Drop your own clips or pictures here</p>
          <p className="mt-1 text-[12.5px] text-g8">Portrait clips are kept and framed over a blurred copy. Nothing is cropped away without you seeing it.</p>
          <Button kind="secondary" size="sm" className="mt-4" onClick={() => input.current?.click()}>Choose files</Button>
          <input ref={input} type="file" multiple accept="video/*,image/*" className="hidden" onChange={(e) => void take(e.target.files)} />
        </div>
      )}
      {v.uploads.length > 0 && (
        <div className="grid grid-cols-2 gap-x-4 gap-y-6 md:grid-cols-3 2xl:grid-cols-4">
          {v.uploads.map((u, i) => {
            const at = v.placed.findIndex((y) => y.ref.kind === "upload" && y.ref.id === u.id);
            const add = () => place(p.id, s.id, { ref: { kind: "upload", id: u.id }, in: 0, out: s.kind === "anchor" ? fillOf(p, s).need : Math.min(u.seconds ?? 4, 8), muted: true, useTreated: false });
            return (
              <div key={u.id} className="relative">
                {u.kind === "video" ? (
                  <figure className="group relative">
                    <div className="relative"><video src={u.src} muted className="aspect-video w-full rounded-[2px] bg-black object-cover ring-1 ring-g4" onMouseEnter={(e) => void e.currentTarget.play()} onMouseLeave={(e) => e.currentTarget.pause()} onClick={add} />
                      {at >= 0 && <MarkerLoop n={at + 1} seed={i} />}</div>
                    <figcaption className="mt-1.5 flex items-baseline gap-2"><span className="edge text-[11px]">UP·{String(roll).padStart(2, "0")}{String.fromCharCode(97 + i)}</span><span className="truncate text-[12.5px] text-g9">{u.name}</span></figcaption>
                  </figure>
                ) : <Frame kind="upload" src={u.src} code={`UP·${String(roll).padStart(2, "0")}${String.fromCharCode(97 + i)}`} label={u.name} picked={at < 0 ? undefined : at + 1} seed={i} onOpen={add} onAdd={add} />}
                {!locked && <IconButton label={`Remove ${u.name}`} size="sm" className="absolute top-1 right-1 bg-black/60" onClick={() => removeUpload(p.id, s.id, u.id)}><Trash size={13} /></IconButton>}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ right: picked, in play order

function Picked({ p, s, name, locked, footer }: { p: Project; s: Section; name: string; locked: boolean; footer: React.ReactNode }) {
  const v = p.visuals[s.id];
  const f = fillOf(p, s);
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }), useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }));
  const placed = v?.placed ?? [];
  function end(e: DragEndEvent) {
    if (!e.over || e.active.id === e.over.id) return;
    const ids = placed.map((x) => x.id);
    reorderPlaced(p.id, s.id, arrayMove(ids, ids.indexOf(String(e.active.id)), ids.indexOf(String(e.over.id))));
  }
  function fill() {
    let have = f.have; let n = 0;
    for (const fv of v.found) fv.moments.forEach((m, mi) => {
      if (!m.clip || have >= f.need - 0.25) return;
      if (placed.some((x) => x.ref.kind === "moment" && x.ref.videoId === fv.id && x.ref.moment === mi)) return;
      const d = Math.min(5, f.need - have, m.end - m.start);
      place(p.id, s.id, { ref: { kind: "moment", videoId: fv.id, moment: mi }, in: 0, out: d, muted: true, useTreated: !!fv.moments[mi]?.treat });
      have += d; n++;
    });
    toast(n ? `Added ${n} ${n === 1 ? "pick" : "picks"} from the edit plan` : "No more cut clips to add. Pick a moment to cut, upload, or add a map.", n ? "ok" : "bad");
  }
  return (
    <aside className="flex flex-col border-g4 lg:min-h-0 lg:border-l" aria-labelledby="picked-h">
      <div className="border-b border-g4 px-5 pt-5 pb-4">
        <div className="flex items-baseline justify-between">
          <h2 id="picked-h" className="text-[14px] font-semibold">{s.kind === "anchor" ? `Behind the anchor · ${name}` : `${name} · play order`}</h2>
          <span className="edge text-[12.5px]">{mmss(f.have)} <span className="text-g8">/ {mmss(f.need)}</span></span>
        </div>
        <FillBar have={f.have} need={f.need} className="mt-2.5" />
        <p className={cx("mt-1.5 text-[12px]", f.full ? "text-ok" : "text-warn")}>
          {f.full ? (s.kind === "anchor" ? "Picture set." : "Filled. Extra seconds are trimmed to the voice.") : s.kind === "anchor" ? "Pick one picture for the studio screen." : `${Math.ceil(f.need - f.have)} s still to fill.`}
        </p>
      </div>
      <div className="min-h-0 flex-1 overflow-auto px-3 py-3">
        {placed.length === 0 ? (
          <div className="mx-2 rounded-md border border-dashed border-g5 px-4 py-8 text-center text-[13px] text-g8">
            Click a frame's <Plus size={11} weight="bold" className="inline text-marker" /> or open it and press Use. Picked frames get a red loop and their number.
          </div>
        ) : (
          <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={end}>
            <SortableContext items={placed.map((x) => x.id)} strategy={verticalListSortingStrategy}>
              <ol className="space-y-1.5">
                <AnimatePresence initial={false}>
                  {placed.map((x, i) => <PickedRow key={x.id} p={p} sid={s.id} x={x} n={i + 1} locked={locked} />)}
                </AnimatePresence>
              </ol>
            </SortableContext>
          </DndContext>
        )}
        {!locked && s.kind === "vo" && !f.full && v.found.some((y) => y.moments.some((m) => m.clip)) && (
          <Button kind="ghost" size="sm" className="mt-3 w-full" icon={<MagicWand size={14} />} onClick={fill}>Fill the rest from the edit plan</Button>
        )}
      </div>
      <div className="border-t border-g4 p-4">{footer}</div>
    </aside>
  );
}

function PickedRow({ p, sid, x, n, locked }: { p: Project; sid: string; x: import("@/data/types").PlacedItem; n: number; locked: boolean }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: x.id, disabled: locked });
  const m = mediaOf(p, sid, x);
  const [edit, setEdit] = useState(false);
  return (
    <motion.li ref={setNodeRef} layout={!isDragging} initial={{ opacity: 0, x: 16 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 16, height: 0 }}
      style={{ transform: CSS.Transform.toString(transform), transition, zIndex: isDragging ? 5 : undefined }}
      className={cx("group rounded-sm border bg-g1", isDragging ? "border-g7 shadow-2xl" : "border-g4")}>
      <div className="flex items-center gap-2 p-1.5 pr-1">
        {!locked && <button {...attributes} {...listeners} aria-label={`Drag pick ${n}`} className="cursor-grab text-g6 hover:text-g9 active:cursor-grabbing"><DotsSixVertical size={16} weight="bold" /></button>}
        <span className="w-5 text-center font-marker text-[17px] leading-none text-marker">{n}</span>
        <span className="relative h-9 w-16 shrink-0 overflow-hidden rounded-[2px] bg-g3">
          {m?.kind === "video" ? <video src={m.src} muted className="size-full object-cover" onMouseEnter={(e) => void e.currentTarget.play()} onMouseLeave={(e) => e.currentTarget.pause()} />
            : m && <img src={m.src} alt="" className="size-full object-cover" />}
          {x.useTreated && <Tip label="Uses the treated version"><span className="absolute bottom-0 left-0 bg-warn px-1 font-mono text-[11px] leading-[14px] font-bold text-g0 uppercase">T</span></Tip>}
        </span>
        <button className="min-w-0 flex-1 text-left" onClick={() => !locked && setEdit((e) => !e)} aria-expanded={edit}>
          <span className="block truncate text-[12.5px] text-g10" title={m?.label}>{m?.label ?? "Missing"}</span>
          <span className="edge block truncate text-[11px]">{m?.code}</span>
        </button>
        <span className="edge text-[12px]">{mmss(x.out - x.in)}</span>
        {!locked && <>
          <IconButton label="Remove" size="sm" onClick={() => unplace(p.id, sid, x.id)}><X size={14} /></IconButton>
        </>}
      </div>
      <AnimatePresence>
        {edit && (
          <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
            <div className="flex items-center gap-3 border-t border-g4 px-3 py-2 text-[12px] text-g8">
              <label className="flex items-center gap-1.5">In <input type="number" step={0.1} min={0} value={x.in} onChange={(e) => updatePlaced(p.id, sid, x.id, { in: Math.max(0, Math.min(+e.target.value, x.out - 0.5)) })} className="h-7 w-16 rounded-xs border border-g5 bg-g0 px-1.5 font-mono text-edge" /></label>
              <label className="flex items-center gap-1.5">Out <input type="number" step={0.1} min={x.in + 0.5} value={x.out} onChange={(e) => updatePlaced(p.id, sid, x.id, { out: Math.max(x.in + 0.5, +e.target.value) })} className="h-7 w-16 rounded-xs border border-g5 bg-g0 px-1.5 font-mono text-edge" /></label>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.li>
  );
}
