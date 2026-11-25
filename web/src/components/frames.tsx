// Contact-sheet frames: the tile every found moment, photo, upload and map is shown as,
// and the china-marker loop that marks a frame as picked.
import { motion } from "motion/react";
import { Plus, FilmSlate, Image as ImageIcon, MapTrifold, UploadSimple } from "@phosphor-icons/react";
import type { Flag } from "@/data/types";
import { Tag, Tip, cx, mmss } from "./ui";

const FLAG: Record<Flag, string> = { logo: "Logo", text: "Text", vertical: "Portrait", presenter: "Presenter" };
export const flagLabel = (f: Flag) => FLAG[f];

export function MarkerLoop({ n, seed = 0 }: { n?: number; seed?: number }) {
  // a slightly different hand-drawn loop per frame
  const j = (k: number) => ((Math.sin(seed * 9.13 + k * 3.7) + 1) / 2) * 2.4 - 1.2;
  const d = `M ${8 + j(1)} ${52 + j(2)} C ${4 + j(3)} ${20 + j(4)}, ${40 + j(5)} ${3 + j(6)}, ${100 + j(7)} ${5 + j(8)} S ${197 + j(9)} ${28 + j(1)}, ${194 + j(2)} ${60 + j(3)} S ${150 + j(4)} ${110 + j(5)}, ${90 + j(6)} ${108 + j(7)} S ${3 + j(8)} ${92 + j(9)}, ${11 + j(1)} ${46 + j(2)}`;
  return (
    <>
      <svg viewBox="0 0 200 112" preserveAspectRatio="none" className="pointer-events-none absolute -inset-[7px] z-10 h-[calc(100%+14px)] w-[calc(100%+14px)] overflow-visible" aria-hidden>
        <motion.path d={d} fill="none" stroke="var(--color-marker)" strokeWidth={3.2} strokeLinecap="round" vectorEffect="non-scaling-stroke"
          initial={{ pathLength: 0, opacity: 0.6 }} animate={{ pathLength: 1, opacity: 1 }} transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }} />
      </svg>
      {n !== undefined && (
        <motion.span key={n} initial={{ opacity: 0, scale: 0.6, rotate: -14 }} animate={{ opacity: 1, scale: 1, rotate: -8 }} transition={{ duration: 0.22, delay: 0.16, ease: [0.16, 1, 0.3, 1] }}
          className="pointer-events-none absolute -top-5 -right-1.5 z-20 font-marker text-[42px] leading-none text-marker [paint-order:stroke_fill] [-webkit-text-stroke:6px_#0a0b0d]">{n}</motion.span>
      )}
    </>
  );
}

export interface FrameProps {
  src: string; code: string; label: string; sub?: string;
  seconds?: number; score?: number; estimated?: boolean; flags?: Flag[]; kind?: "moment" | "photo" | "upload" | "map";
  noClip?: boolean; cutFailed?: boolean; picked?: number; seed?: number;
  onOpen?: () => void; onAdd?: () => void; draggable?: boolean; dim?: boolean;
}

export function Frame({ src, code, label, sub, seconds, score, estimated, flags, kind = "moment", noClip, cutFailed, picked, seed, onOpen, onAdd, dim }: FrameProps) {
  const tone = score === undefined ? "neutral" : score >= 70 ? "ok" : score >= 40 ? "warn" : "neutral";
  const Icon = kind === "photo" ? ImageIcon : kind === "map" ? MapTrifold : kind === "upload" ? UploadSimple : FilmSlate;
  return (
    <motion.figure layout="position" initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }} className="group relative min-w-0">
      <div className="relative">
        <button onClick={onOpen} onDoubleClick={onAdd} aria-label={`${label}${picked ? `, picked ${picked}` : ""}. Open`}
          className={cx("relative block aspect-video w-full overflow-hidden rounded-[2px] bg-g3 ring-1 ring-g4 transition-[filter,box-shadow] duration-200 hover:ring-g7",
            picked === undefined && "group-hover:brightness-110")}>
          {src ? <img src={src} alt="" loading="lazy" className={cx("size-full object-cover", dim && "opacity-35 grayscale")} /> : <span className="grid size-full place-items-center text-g8"><Icon size={22} /></span>}
          <span className="absolute inset-x-0 bottom-0 h-1/2 bg-gradient-to-t from-black/70 to-transparent" />
          {seconds !== undefined && <span className="absolute right-1.5 bottom-1 rounded-xs bg-black/70 px-1 font-mono text-[11px] text-edge">{mmss(seconds)}</span>}
          <span className="absolute top-1.5 left-1.5 flex flex-wrap gap-1">
            {score !== undefined && <Tag tone={tone} className="bg-black/75 backdrop-blur-sm">{score}</Tag>}
            {estimated && <Tip label="Times are a guess: the video had no captions."><span><Tag tone="neutral" className="bg-black/75">≈ time</Tag></span></Tip>}
          </span>
          {flags && flags.length > 0 && (
            <span className="absolute bottom-1 left-1.5 flex gap-1">{flags.map((f) => <Tag key={f} tone="warn" className="bg-black/70">{flagLabel(f)}</Tag>)}</span>
          )}
          {cutFailed ? <span className="absolute top-1.5 right-1.5"><Tip label="This moment could not be downloaded from YouTube, so it can't be used."><span><Tag tone="warn" className="bg-black/70">Can't cut</Tag></span></Tip></span>
            : noClip && <span className="absolute top-1.5 right-1.5"><Tip label="The video is still downloading. It plays as soon as it is ready."><span><Tag tone="neutral" className="bg-black/70">Downloading</Tag></span></Tip></span>}
        </button>
        {picked !== undefined && <MarkerLoop n={picked} seed={seed ?? picked} />}
        {onAdd && picked === undefined && (
          <button onClick={onAdd} aria-label={`Use ${label}`}
            className="absolute right-1.5 bottom-6 grid size-7 translate-y-1 place-items-center rounded-full bg-marker text-white opacity-0 shadow-lg transition-all duration-150 group-hover:translate-y-0 group-hover:opacity-100 focus-visible:translate-y-0 focus-visible:opacity-100">
            <Plus size={14} weight="bold" />
          </button>
        )}
      </div>
      <figcaption className="mt-1.5 min-w-0">
        <div className="flex items-baseline gap-2">
          <span className="edge shrink-0 text-[11px]">{code}</span>
          <span className="truncate text-[12.5px] text-g9" title={label}>{label}</span>
        </div>
        {sub && <div className="truncate text-[11.5px] text-g8" title={sub}>{sub}</div>}
      </figcaption>
    </motion.figure>
  );
}
