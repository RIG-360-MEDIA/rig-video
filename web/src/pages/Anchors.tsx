import { useState } from "react";
import { Link } from "react-router";
import { motion, AnimatePresence } from "motion/react";
import { useStore } from "@/data/store";
import type { Anchor } from "@/data/types";
import { Tag, cx, mmss } from "@/components/ui";
import { VoiceSample, regionName } from "./Script";

export default function Anchors() {
  const anchors = useStore((s) => s.anchors);
  const lib = useStore((s) => s.library);
  const projects = useStore((s) => s.projects);
  const [sel, setSel] = useState(anchors.find((a) => a.offered)?.id ?? anchors[0]?.id);
  const a = anchors.find((x) => x.id === sel);
  const offered = anchors.filter((x) => x.offered);
  const resting = anchors.filter((x) => !x.offered);
  const count = (id: string) => lib.filter((x) => x.anchorId === id).length + Object.values(projects).filter((p) => p.anchorId === id && p.stage !== "done").length;

  return (
    <div className="mx-auto max-w-[1680px] px-5 pt-8 pb-20">
      <h1 className="text-[26px] font-semibold tracking-[-0.02em]">Anchors</h1>
      <p className="mt-1 mb-7 text-g8"><span className="edge">{offered.length}</span> on air · each keeps the same face and the same voice in every video</p>
      <div className="grid grid-cols-1 gap-8 xl:grid-cols-[minmax(0,1fr)_420px]">
        <div className="space-y-8">
          <Grid list={offered} sel={sel} setSel={setSel} count={count} />
          {resting.length > 0 && <div><h2 className="mb-3 text-[13px] font-semibold text-g8">Not offered right now</h2><Grid list={resting} sel={sel} setSel={setSel} count={count} dim /></div>}
        </div>
        <AnimatePresence mode="wait">
          {a && <Detail key={a.id} a={a} />}
        </AnimatePresence>
      </div>
    </div>
  );
}

function Grid({ list, sel, setSel, count, dim }: { list: Anchor[]; sel?: string; setSel: (id: string) => void; count: (id: string) => number; dim?: boolean }) {
  return (
    <ul className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4 2xl:grid-cols-5">
      {list.map((a, i) => (
        <motion.li key={a.id} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3, delay: i * 0.035, ease: [0.16, 1, 0.3, 1] }}>
          <button onClick={() => setSel(a.id)} aria-pressed={sel === a.id} className="group block w-full text-left">
            <div className={cx("relative aspect-[4/5] overflow-hidden rounded-[2px] ring-1 transition-[box-shadow,filter]", sel === a.id ? "ring-2 ring-marker" : "ring-g4 group-hover:ring-g7", dim && "grayscale-[0.6]")}>
              <img src={a.face} alt="" loading="lazy" className="size-full object-cover transition-transform duration-500 group-hover:scale-[1.04]" />
              <span className="absolute inset-x-0 bottom-0 h-1/3 bg-gradient-to-t from-black/80 to-transparent" />
              <span className="absolute bottom-2 left-2.5 font-mono text-[10.5px] text-edge">{count(a.id)} {count(a.id) === 1 ? "story" : "stories"}</span>
            </div>
            <div className="mt-2 text-[14px] font-semibold">{a.name}</div>
            <div className="truncate text-[12px] text-g8">{a.regions.map(regionName).join(", ")}</div>
          </button>
        </motion.li>
      ))}
    </ul>
  );
}

function Detail({ a }: { a: Anchor }) {
  const lib = useStore((s) => s.library).filter((x) => x.anchorId === a.id);
  const projects = useStore((s) => s.projects);
  const open = Object.values(projects).filter((p) => p.anchorId === a.id && p.stage !== "done");
  return (
    <motion.aside initial={{ opacity: 0, x: 12 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -8 }} transition={{ duration: 0.25, ease: [0.16, 1, 0.3, 1] }}
      className="self-start overflow-hidden rounded-md border border-g4 bg-g1 xl:sticky xl:top-[76px]">
      <img src={a.frame} alt={`${a.name} at the studio desk`} className="aspect-video w-full object-cover" />
      <div className="p-5">
        <div className="flex items-start justify-between gap-3">
          <div><h2 className="text-[19px] font-semibold">{a.name}</h2><VoiceSample a={a} /></div>
          {a.offered ? <Tag tone="ok">On air</Tag> : <Tag>Resting</Tag>}
        </div>
        <dl className="mt-5 grid grid-cols-[110px_minmax(0,1fr)] gap-y-2.5 text-[13.5px]">
          <dt className="text-g8">Pace</dt><dd><span className="edge">{a.wordsPerSecond.toFixed(2)}</span> words a second</dd>
          <dt className="text-g8">Covers</dt><dd className="flex flex-wrap gap-1">{a.regions.map((r) => <Tag key={r} tone="neutral">{regionName(r)}</Tag>)}</dd>
          <dt className="text-g8">One minute</dt><dd>about <span className="edge">{Math.round(a.wordsPerSecond * 60)}</span> words</dd>
        </dl>
        <h3 className="mt-6 mb-2 text-[13px] font-semibold text-g8">Stories</h3>
        <ul className="space-y-1.5">
          {open.map((p) => (
            <li key={p.id}><Link to={`/story/${p.id}`} className="flex items-center gap-2 rounded-sm px-2 py-1.5 text-[13px] hover:bg-g3"><Tag tone="edge">{p.stage}</Tag><span className="truncate">{p.headline}</span></Link></li>
          ))}
          {lib.map((x) => (
            <li key={x.id}><Link to="/library" className="flex items-center gap-2 rounded-sm px-2 py-1.5 text-[13px] hover:bg-g3"><span className="edge w-[44px] text-[11.5px]">{mmss(x.seconds)}</span><span className="truncate text-g9">{x.headline}</span></Link></li>
          ))}
          {!open.length && !lib.length && <li className="px-2 text-[13px] text-g8">No stories with {a.name.split(" ")[0]} yet.</li>}
        </ul>
      </div>
    </motion.aside>
  );
}
