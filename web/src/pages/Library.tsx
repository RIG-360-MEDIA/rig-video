import { useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { AnimatePresence, motion } from "motion/react";
import { MagnifyingGlass, Play, DownloadSimple, CopySimple, FilmStrip, X } from "@phosphor-icons/react";
import { useStore, duplicateFromLibrary, anchorOf, toast } from "@/data/store";
import type { LibraryItem } from "@/data/types";
import { PhonePlayer, RoughCutPlayer, VideoPlayer } from "@/components/player";
import { Button, Dialog, Empty, Segmented, Tag, Tip, cx, istDate, mmss } from "@/components/ui";
import { FinishedActions } from "./Render";

type Sort = "new" | "old" | "long";

export default function Library() {
  const lib = useStore((s) => s.library);
  const anchors = useStore((s) => s.anchors);
  const [q, setQ] = useState("");
  const [anchor, setAnchor] = useState<string>("all");
  const [sort, setSort] = useState<Sort>("new");
  const [open, setOpen] = useState<string | null>(null);
  const used = anchors.filter((a) => lib.some((x) => x.anchorId === a.id));
  const list = useMemo(() => {
    const t = q.trim().toLowerCase();
    const l = lib.filter((x) => (anchor === "all" || x.anchorId === anchor) && (!t || x.headline.toLowerCase().includes(t)));
    return [...l].sort((a, b) => sort === "long" ? b.seconds - a.seconds : sort === "old" ? a.madeAt.localeCompare(b.madeAt) : b.madeAt.localeCompare(a.madeAt));
  }, [lib, q, anchor, sort]);
  const it = lib.find((x) => x.id === open);
  const totalMin = Math.round(lib.reduce((n, x) => n + x.seconds, 0) / 60);

  return (
    <div className="mx-auto max-w-[1680px] px-5 pt-8 pb-20">
      <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-[26px] font-semibold tracking-[-0.02em]">Library</h1>
          <p className="mt-1 text-g8"><span className="edge">{lib.length}</span> video{lib.length === 1 ? "" : "s"} · <span className="edge">{totalMin}</span> minute{totalMin === 1 ? "" : "s"} made</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex h-9 w-[260px] items-center gap-2 rounded-sm border border-g5 bg-g1 px-2.5 focus-within:border-g8">
            <MagnifyingGlass size={15} className="text-g8" />
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search headlines" aria-label="Search headlines" className="min-w-0 flex-1 bg-transparent text-[13.5px] outline-none focus-visible:outline-none" />
            {q && <button onClick={() => setQ("")} aria-label="Clear search" className="text-g8 hover:text-g10"><X size={13} /></button>}
          </label>
          <Segmented size="sm" label="Sort" value={sort} set={setSort} options={[{ v: "new", l: "Newest" }, { v: "old", l: "Oldest" }, { v: "long", l: "Longest" }]} />
        </div>
      </div>
      <div className="mb-6 flex flex-wrap gap-1.5" role="radiogroup" aria-label="Anchor">
        {[{ id: "all", name: "All anchors", face: "" }, ...used].map((a) => (
          <button key={a.id} role="radio" aria-checked={anchor === a.id} onClick={() => setAnchor(a.id)}
            className={cx("flex h-8 items-center gap-2 rounded-full border pr-3 text-[12.5px] transition-colors", a.face ? "pl-1" : "pl-3", anchor === a.id ? "border-g9 bg-g9 text-g0" : "border-g5 text-g9 hover:border-g7")}>
            {a.face && <img src={a.face} alt="" className="size-6 rounded-full object-cover" />}{a.name}
          </button>
        ))}
      </div>

      {list.length === 0 ? (
        <Empty icon={<FilmStrip size={32} />} title={lib.length ? "Nothing matches" : "No videos yet"} action={lib.length ? <Button kind="secondary" size="sm" onClick={() => { setQ(""); setAnchor("all"); }}>Clear filters</Button> : undefined}>
          {lib.length ? "Try another word or anchor." : "Rendered videos land here."}
        </Empty>
      ) : (
        <motion.ul layout className="grid grid-cols-1 gap-x-5 gap-y-8 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4">
          <AnimatePresence initial={false}>
            {list.map((x, i) => <Card key={x.id} x={x} i={i} onOpen={() => setOpen(x.id)} />)}
          </AnimatePresence>
        </motion.ul>
      )}
      <Player it={it} onClose={() => setOpen(null)} />
    </div>
  );
}

function Card({ x, i, onOpen }: { x: LibraryItem; i: number; onOpen: () => void }) {
  const vid = useRef<HTMLVideoElement>(null);
  const a = anchorOf(x.anchorId);
  const fresh = Date.now() - new Date(x.madeAt).getTime() < 6 * 3600_000;
  return (
    <motion.li layout initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, scale: 0.97 }} transition={{ duration: 0.3, delay: Math.min(i, 8) * 0.03, ease: [0.16, 1, 0.3, 1] }}>
      <button onClick={onOpen} className="group block w-full text-left"
        onMouseEnter={() => { const v = vid.current; if (v) { v.currentTime = Math.min(30, x.seconds / 3); void v.play().catch(() => {}); } }}
        onMouseLeave={() => vid.current?.pause()}>
        <div className="relative aspect-video overflow-hidden rounded-[2px] bg-g3 ring-1 ring-g4 transition-shadow group-hover:ring-g7">
          {x.poster && <img src={x.poster} alt="" loading="lazy" className="absolute inset-0 size-full object-cover" />}
          {x.video && <video ref={vid} src={x.video} poster={x.poster} muted playsInline preload="none" className="absolute inset-0 size-full object-cover opacity-0 transition-opacity duration-300 group-hover:opacity-100" />}
          <span className="absolute inset-0 grid place-items-center">
            <span className="grid size-12 scale-90 place-items-center rounded-full bg-black/55 opacity-0 backdrop-blur-sm transition-all duration-200 group-hover:scale-100 group-hover:opacity-100"><Play size={20} weight="fill" /></span>
          </span>
          <span className="absolute right-1.5 bottom-1.5 rounded-xs bg-black/75 px-1.5 font-mono text-[11px] text-edge">{mmss(x.seconds)}</span>
          {!x.video && <span className="absolute top-1.5 left-1.5"><Tip label="Plays as a rough cut until the full editor is built"><span><Tag tone="edge" className="bg-black/70">Rough cut</Tag></span></Tip></span>}
          {fresh && <span className="absolute top-1.5 right-1.5"><Tag tone="marker">New</Tag></span>}
        </div>
        <div className="mt-2.5 flex items-start gap-2.5">
          {a && <img src={a.face} alt="" className="mt-0.5 size-7 shrink-0 rounded-full object-cover" />}
          <div className="min-w-0">
            <div className="line-clamp-2 text-[14px] leading-snug font-semibold text-g10 group-hover:underline">{x.headline}</div>
            <div className="mt-0.5 text-[12.5px] text-g8">{a?.name} · {istDate(x.madeAt)}</div>
          </div>
        </div>
      </button>
    </motion.li>
  );
}

function Player({ it, onClose }: { it?: LibraryItem; onClose: () => void }) {
  const projects = useStore((s) => s.projects);
  const nav = useNavigate();
  const p = it?.projectId ? projects[it.projectId] : undefined;
  async function again() {
    if (!it) return;
    const id = await duplicateFromLibrary(it.id);
    if (id) { toast("Copied into a new story"); nav(`/story/${id}/script`); }
  }
  return (
    <Dialog open={!!it} onOpenChange={(v) => !v && onClose()} title={it?.headline ?? ""} wide="full">
      {it && (
        <div>
          {it.video ? <VideoPlayer src={it.video} poster={it.poster} autoPlay />
            : p ? (p.format === "vo_only" ? <div className="flex justify-center bg-g0 py-5"><PhonePlayer p={p} autoPlay width={280} /></div> : <div className="mx-auto w-full max-w-[calc(66dvh*16/9)]"><RoughCutPlayer p={p} autoPlay /></div>) : <div className="grid aspect-video place-items-center text-g8">This video's file is no longer kept.</div>}
          <div className="flex flex-wrap items-center gap-3 border-t border-g4 px-5 py-3.5">
            <div className="mr-auto text-[13px] text-g8">{anchorOf(it.anchorId)?.name} · <span className="edge">{mmss(it.seconds)}</span> · {istDate(it.madeAt)}</div>
            {it.video ? (
              <a href={it.video} download className="inline-flex h-8 items-center gap-1.5 rounded-sm border border-g5 px-3 text-[13px] font-semibold text-g10 transition-colors hover:border-g8"><DownloadSimple size={15} />Download</a>
            ) : <Tip label="The rough cut has no file yet. The render machine makes the file."><span><Button kind="secondary" size="sm" disabled icon={<DownloadSimple size={15} />}>Download</Button></span></Tip>}
            {p ? <Button kind="secondary" size="sm" icon={<CopySimple size={15} />} onClick={again}>Make another from this</Button>
              : <Tip label="Made before the studio kept its stories, so there is nothing to copy."><span><Button kind="secondary" size="sm" disabled icon={<CopySimple size={15} />}>Make another from this</Button></span></Tip>}
            {p?.stage === "done" && <FinishedActions p={p} compact />}
          </div>
        </div>
      )}
    </Dialog>
  );
}
