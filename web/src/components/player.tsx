// Rough-cut player: the story's real voice over its picked pictures, with the lower thirds and ticker
// drawn on top. Runs in the browser, no GPU. Used on Review and for studio videos in the Library.
import { useEffect, useMemo, useRef, useState, useCallback } from "react";
import { AnimatePresence, motion } from "motion/react";
import { Play, Pause, SkipBack, SpeakerHigh, SpeakerSlash, CornersOut, CornersIn, ArrowsLeftRight } from "@phosphor-icons/react";
import { sections, sectionSeconds, mediaOf, anchorOf } from "@/data/store";
import type { LowerThird, Project } from "@/data/types";
import { IconButton, Tip, cx, mmss } from "./ui";
import { Mark } from "./shell";

export interface CutItem { kind: "video" | "image"; src: string; start: number; dur: number; in: number; code: string; label: string; poster?: string }
export interface CutSeg { sid: string; kind: "anchor" | "vo"; n: number; start: number; dur: number; lt?: LowerThird; audio?: string; items: CutItem[]; behind?: CutItem }

export function buildCut(p: Project): CutSeg[] {
  let t = 0; let na = 0; let nv = 0;
  return sections(p).map((s) => {
    const dur = Math.max(1, sectionSeconds(s, p.anchorId).sec);
    const take = s.voice?.takes.find((x) => x.id === s.voice?.pick);
    const placed = p.visuals[s.id]?.placed ?? [];
    const items: CutItem[] = [];
    let it = 0;
    const total = placed.reduce((n, x) => n + (x.out - x.in), 0) || 1;
    for (const x of placed) {
      const m = mediaOf(p, s.id, x); if (!m) continue;
      const d = s.kind === "anchor" ? dur : ((x.out - x.in) / total) * Math.max(dur, total);
      items.push({ kind: m.kind, src: m.src, start: t + it, dur: d, in: x.in, code: m.code, label: m.label });
      it += d;
    }
    const seg: CutSeg = { sid: s.id, kind: s.kind, n: s.kind === "anchor" ? ++na : ++nv, start: t, dur, lt: s.kind === "anchor" ? p.lt : undefined, audio: take?.src, items };
    if (s.kind === "anchor") seg.behind = items[0];
    t += dur;
    return seg;
  });
}

export interface Extras { captions: "file" | "burned" | "none"; aiLabel: boolean; outro: boolean }
const OUTRO_S = 11.84;                                          // DNL Outro.mp4

export function RoughCutPlayer({ p, autoPlay, time, onTime, compact, extras }: { p: Project; autoPlay?: boolean; time?: { t: number; nonce: number }; onTime?: (t: number) => void; compact?: boolean; extras?: Extras }) {
  const cut = useMemo(() => buildCut(p), [p]);
  const body = cut.reduce((n, s) => n + s.dur, 0);
  const total = body + (extras?.outro ? OUTRO_S : 0);
  const [t, setT] = useState(0);
  const [playing, setPlaying] = useState(!!autoPlay);
  const [muted, setMuted] = useState(false);
  const audio = useRef<HTMLAudioElement>(null);
  const stage = useRef<HTMLDivElement>(null);
  const last = useRef(0);
  const tRef = useRef(0);
  const anchor = anchorOf(p.anchorId);
  const fs = useFull<HTMLDivElement>();

  const seg = cut.find((s) => t >= s.start && t < s.start + s.dur) ?? cut[cut.length - 1];
  const item = seg?.kind === "vo" ? seg.items.find((i) => t >= i.start && t < i.start + i.dur) ?? seg.items[seg.items.length - 1] : undefined;

  const seek = useCallback((nt: number) => {
    const c = Math.max(0, Math.min(total - 0.01, nt));
    tRef.current = c; setT(c); onTime?.(c);
    const s = cut.find((x) => c >= x.start && c < x.start + x.dur);
    const a = audio.current;
    if (a && s?.audio) { if (!a.src.endsWith(s.audio)) a.src = s.audio; a.currentTime = Math.max(0, c - s.start); }
  }, [cut, total, onTime]);

  useEffect(() => { if (time) seek(time.t); }, [time?.nonce]); // eslint-disable-line react-hooks/exhaustive-deps

  // clock
  useEffect(() => {
    if (!playing) return;
    let raf = 0;
    last.current = performance.now();
    const step = (now: number) => {
      const dt = (now - last.current) / 1000; last.current = now;
      const nt = tRef.current + dt;
      if (nt >= total) { setPlaying(false); seek(0); return; }
      const prev = cut.find((x) => tRef.current >= x.start && tRef.current < x.start + x.dur);
      const next = cut.find((x) => nt >= x.start && nt < x.start + x.dur);
      tRef.current = nt; setT(nt); onTime?.(nt);
      if (next && prev !== next) {
        const a = audio.current;
        if (a) { if (next.audio) { a.src = next.audio; a.currentTime = 0; void a.play().catch(() => {}); } else a.pause(); }
      }
      raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    const a = audio.current;
    const s = cut.find((x) => tRef.current >= x.start && tRef.current < x.start + x.dur);
    if (a && s?.audio) { if (!a.src.endsWith(s.audio)) a.src = s.audio; a.currentTime = tRef.current - s.start; void a.play().catch(() => {}); }
    return () => { cancelAnimationFrame(raf); audio.current?.pause(); };
  }, [playing]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { if (audio.current) audio.current.muted = muted; }, [muted]);

  function key(e: React.KeyboardEvent) {
    if (e.key === " " || e.key === "k") { e.preventDefault(); setPlaying((v) => !v); }
    else if (e.key === "ArrowRight") seek(tRef.current + (e.shiftKey ? 5 : 1));
    else if (e.key === "ArrowLeft") seek(tRef.current - (e.shiftKey ? 5 : 1));
    else if (e.key === "l") seek(tRef.current + 5);
    else if (e.key === "j") seek(tRef.current - 5);
    else if (e.key === "f") fs.toggle();
  }

  const inOutro = t >= body;
  const caption = extras?.captions === "burned" && seg && !inOutro ? captionAt(sections(p).find((x) => x.id === seg.sid)?.text ?? "", (t - seg.start) / seg.dur) : "";
  const ltOn = !inOutro && seg?.kind === "anchor" && seg.lt?.headline && t - seg.start > 0.6 && t - seg.start < Math.min(seg.dur - 0.4, 8);
  return (
    <div ref={fs.ref} className={cx("flex flex-col bg-black outline-none", fs.cls)} tabIndex={0} onKeyDown={key} aria-label="Rough cut preview. Space plays, arrows step, F full screen.">
      <div ref={stage} className={cx("relative aspect-video w-full overflow-hidden bg-g0 [container-type:inline-size]", fs.stageCls)}>
        {/* picture */}
        <AnimatePresence initial={false}>
          {seg?.kind === "anchor" && (
            <motion.div key={`a-${seg.sid}`} className="absolute inset-0" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.25 }}>
              {anchor && <img src={anchor.frame} alt="" className="absolute inset-0 size-full object-cover" />}
              {seg.behind && (
                <div className="absolute top-[12%] right-[6%] w-[30%] overflow-hidden rounded-[2px] shadow-[0_10px_30px_rgba(0,0,0,0.6)] ring-1 ring-white/10">
                  <Media item={seg.behind} t={t} playing={playing} />
                </div>
              )}
            </motion.div>
          )}
          {seg?.kind === "vo" && item && (
            <motion.div key={`v-${item.start}`} className="absolute inset-0" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.2 }}>
              <Media item={item} t={t} playing={playing} fill />
            </motion.div>
          )}
          {seg?.kind === "vo" && !item && (
            <motion.div key={`empty-${seg.sid}`} className="absolute inset-0 grid place-items-center text-[13px] text-g8" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
              No pictures placed for VO {seg.n}
            </motion.div>
          )}
        </AnimatePresence>
        {/* graphics */}
        <div className="absolute top-[4.5%] right-[3.5%]"><Mark className="h-[clamp(14px,2.4vw,22px)] text-[clamp(8px,1.2vw,11px)]" /></div>
        <AnimatePresence>
          {ltOn && seg?.lt && (
            <motion.div key={`lt-${seg.sid}`} className="absolute bottom-[15%] left-[5%] max-w-[70%]"
              initial={{ clipPath: "inset(0 100% 0 0)" }} animate={{ clipPath: "inset(0 0% 0 0)" }} exit={{ clipPath: "inset(0 0 0 100%)" }} transition={{ duration: 0.45, ease: [0.16, 1, 0.3, 1] }}>
              <div className="flex items-stretch">
                {seg.lt.kicker && <span className="flex items-center bg-marker px-[0.8em] text-[clamp(8px,1.25vw,13px)] font-black tracking-wide text-white uppercase">{seg.lt.kicker}</span>}
                <span className="bg-white px-[0.7em] py-[0.25em] text-[clamp(10px,1.9vw,21px)] font-extrabold text-g0 uppercase" style={{ fontVariationSettings: '"wdth" 88' }}>{seg.lt.headline}</span>
              </div>
              {seg.lt.subline && <div className="mt-px inline-block bg-g0/85 px-[0.8em] py-[0.25em] text-[clamp(8px,1.3vw,14px)] text-white">{seg.lt.subline}</div>}
            </motion.div>
          )}
        </AnimatePresence>
        {p.ticker.length > 0 && !inOutro && (
          <div className="absolute right-0 bottom-0 left-0 flex h-[7%] items-stretch overflow-hidden bg-g0/90 text-[clamp(8px,1.25vw,13px)] text-white">
            <span className="flex shrink-0 items-center bg-marker px-[0.9em] font-black">DNL</span>
            <div className="relative flex-1 overflow-hidden">
              <div className="absolute inset-y-0 flex items-center whitespace-nowrap" style={{ transform: `translateX(${100 - ((t * 7) % 260)}%)` }}>
                {p.ticker.map((x, i) => <span key={i} className="px-[1.5em] font-semibold uppercase">{x}<span className="ml-[1.5em] inline-block size-[0.45em] translate-y-[-0.1em] bg-marker" /></span>)}
              </div>
            </div>
          </div>
        )}
        {extras?.aiLabel && !inOutro && <span className="absolute top-[4.5%] left-[3.5%] rounded-[0.3em] bg-black/55 px-[0.6em] py-[0.2em] text-[1.6cqw] font-semibold text-white/90">AI anchor</span>}
        {caption && <div className="absolute inset-x-[12%] bottom-[8.5%] text-center"><span className="box-decoration-clone bg-black/75 px-[0.4em] py-[0.1em] text-[2.2cqw] leading-[1.35] font-semibold text-white">{caption}</span></div>}
        <AnimatePresence>
          {inOutro && (
            <motion.div key="outro" className="absolute inset-0 grid place-items-center bg-g0" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
              <div className="text-center"><Mark className="mx-auto h-[8cqw] text-[4cqw]" /><div className="mt-[1.5cqw] text-[2.4cqw] font-semibold tracking-wide text-white">Democracy News Live</div></div>
            </motion.div>
          )}
        </AnimatePresence>
        {!playing && t === 0 && (
          <button onClick={() => setPlaying(true)} className="absolute inset-0 grid place-items-center bg-black/25 transition-colors hover:bg-black/10" aria-label="Play">
            <span className="grid size-16 place-items-center rounded-full bg-marker/95 shadow-[0_10px_30px_-6px_rgba(0,0,0,0.7)]"><Play size={26} weight="fill" className="ml-1 text-white" /></span>
          </button>
        )}
        <audio ref={audio} preload="auto" />
      </div>
      {/* controls */}
      <div className={cx("flex items-center gap-2 border-t border-g4 bg-g1 px-2", compact ? "h-10" : "h-12")}>
        <IconButton label={playing ? "Pause (Space)" : "Play (Space)"} onClick={() => setPlaying((v) => !v)}>{playing ? <Pause size={18} weight="fill" /> : <Play size={18} weight="fill" />}</IconButton>
        <IconButton label="Back to start" size="sm" onClick={() => seek(0)}><SkipBack size={15} weight="fill" /></IconButton>
        <span className="w-[110px] edge text-[12.5px]">{mmss(t, true)} <span className="text-g8">/ {mmss(total)}</span></span>
        <Scrub cut={cut} total={total} t={t} seek={seek} />
        <IconButton label={muted ? "Sound on" : "Mute"} size="sm" onClick={() => setMuted((m) => !m)}>{muted ? <SpeakerSlash size={16} /> : <SpeakerHigh size={16} />}</IconButton>
        <IconButton label={fs.full ? "Leave full screen (Esc)" : "Full screen (F)"} size="sm" onClick={fs.toggle}>{fs.full ? <CornersIn size={16} /> : <CornersOut size={16} />}</IconButton>
      </div>
    </div>
  );
}

/** The burned-in caption at a point in a part: the text in chunks of about seven words, spread over the part. */
function captionAt(text: string, frac: number) {
  const w = text.split(/\s+/).filter(Boolean); const n = Math.max(1, Math.ceil(w.length / 7));
  const i = Math.min(n - 1, Math.max(0, Math.floor(frac * n)));
  return w.slice(i * 7, i * 7 + 7).join(" ");
}

function Scrub({ cut, total, t, seek }: { cut: CutSeg[]; total: number; t: number; seek: (t: number) => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const at = (x: number) => { const r = ref.current!.getBoundingClientRect(); return ((x - r.left) / r.width) * total; };
  return (
    <div ref={ref} role="slider" aria-label="Position" aria-valuemin={0} aria-valuemax={Math.round(total)} aria-valuenow={Math.round(t)} tabIndex={-1}
      className="relative mx-1 flex h-6 flex-1 cursor-pointer items-center gap-px"
      onPointerDown={(e) => { (e.target as HTMLElement).setPointerCapture(e.pointerId); seek(at(e.clientX)); }}
      onPointerMove={(e) => { if (e.buttons) seek(at(e.clientX)); }}>
      {cut.map((s) => (
        <div key={s.sid} className={cx("h-1.5 rounded-[1px]", s.kind === "anchor" ? "bg-anchor/45" : "bg-vo/45")} style={{ flexGrow: s.dur }} />
      ))}
      {total - cut.reduce((n, s) => n + s.dur, 0) > 0.01 && <div className="h-1.5 rounded-[1px] bg-g6" style={{ flexGrow: total - cut.reduce((n, s) => n + s.dur, 0) }} title="Outro" />}
      <div className="pointer-events-none absolute top-0 bottom-0 w-[2px] -translate-x-1/2 rounded bg-marker" style={{ left: `${(t / total) * 100}%` }} />
    </div>
  );
}

/** One picture: video clips play muted from their in-point; stills get a slow, smooth zoom (no shake). */
function Media({ item, t, playing, fill }: { item: CutItem; t: number; playing: boolean; fill?: boolean }) {
  const v = useRef<HTMLVideoElement>(null);
  const local = t - item.start;
  useEffect(() => {
    const el = v.current; if (!el) return;
    if (Math.abs(el.currentTime - (item.in + local)) > 0.35) el.currentTime = item.in + Math.max(0, local);
    if (playing) void el.play().catch(() => {}); else el.pause();
  }, [playing, item.src]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { const el = v.current; if (el && !playing) el.currentTime = item.in + Math.max(0, local); }, [t, playing]); // eslint-disable-line react-hooks/exhaustive-deps
  const zoom = 1 + Math.min(1, Math.max(0, local / Math.max(1, item.dur))) * 0.06;
  return item.kind === "video"
    ? <video ref={v} src={item.src} poster={item.poster} muted playsInline className={cx("size-full object-cover", fill && "absolute inset-0")} />
    : <img src={item.src} alt="" className={cx("size-full object-cover will-change-transform", fill && "absolute inset-0")} style={{ transform: `scale(${zoom})` }} />;
}

/** A rendered video file with the same controls as the rough cut. Height is capped so a dialog's footer stays on screen. */
export function VideoPlayer({ src, poster, autoPlay }: { src: string; poster?: string; autoPlay?: boolean }) {
  const v = useRef<HTMLVideoElement>(null);
  const fs = useFull<HTMLDivElement>();
  const bar = useRef<HTMLDivElement>(null);
  const [t, setT] = useState(0); const [d, setD] = useState(0);
  const [playing, setPlaying] = useState(false); const [muted, setMuted] = useState(false);
  const toggle = () => { const el = v.current; if (!el) return; if (el.paused) void el.play().catch(() => {}); else el.pause(); };
  const seek = (x: number) => { const el = v.current; if (el && d) el.currentTime = Math.max(0, Math.min(d - 0.05, x)); };
  const at = (x: number) => { const r = bar.current!.getBoundingClientRect(); return ((x - r.left) / r.width) * d; };
  function key(e: React.KeyboardEvent) {
    if (e.key === " " || e.key === "k") { e.preventDefault(); toggle(); }
    else if (e.key === "ArrowRight") seek(t + (e.shiftKey ? 10 : 5));
    else if (e.key === "ArrowLeft") seek(t - (e.shiftKey ? 10 : 5));
    else if (e.key === "m") setMuted((m) => !m);
    else if (e.key === "f") fs.toggle();
  }
  useEffect(() => { if (v.current) v.current.muted = muted; }, [muted]);
  return (
    <div ref={fs.ref} className={cx("flex flex-col bg-black outline-none", fs.cls)} tabIndex={0} onKeyDown={key} aria-label="Video. Space plays, arrows skip, F full screen.">
      <div className="relative grid place-items-center bg-black">
        <video ref={v} src={src} poster={poster} autoPlay={autoPlay} playsInline onClick={toggle}
          onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)} onTimeUpdate={(e) => setT(e.currentTarget.currentTime)} onLoadedMetadata={(e) => setD(e.currentTarget.duration)}
          className={cx("aspect-video w-full object-contain", fs.full ? "max-h-[calc(100dvh-48px)]" : "max-h-[66dvh]")} />
        {!playing && t === 0 && (
          <button onClick={toggle} className="absolute inset-0 grid place-items-center bg-black/25 transition-colors hover:bg-black/10" aria-label="Play">
            <span className="grid size-16 place-items-center rounded-full bg-marker/95 shadow-[0_10px_30px_-6px_rgba(0,0,0,0.7)]"><Play size={26} weight="fill" className="ml-1 text-white" /></span>
          </button>
        )}
      </div>
      <div className="flex h-12 items-center gap-2 border-t border-g4 bg-g1 px-2">
        <IconButton label={playing ? "Pause (Space)" : "Play (Space)"} onClick={toggle}>{playing ? <Pause size={18} weight="fill" /> : <Play size={18} weight="fill" />}</IconButton>
        <IconButton label="Back to start" size="sm" onClick={() => seek(0)}><SkipBack size={15} weight="fill" /></IconButton>
        <span className="w-[110px] edge text-[12.5px]">{mmss(t)} <span className="text-g8">/ {mmss(d)}</span></span>
        <div ref={bar} role="slider" aria-label="Position" aria-valuemin={0} aria-valuemax={Math.round(d)} aria-valuenow={Math.round(t)} tabIndex={-1}
          className="relative mx-1 flex h-6 flex-1 cursor-pointer items-center"
          onPointerDown={(e) => { (e.target as HTMLElement).setPointerCapture(e.pointerId); seek(at(e.clientX)); }}
          onPointerMove={(e) => { if (e.buttons) seek(at(e.clientX)); }}>
          <div className="h-1.5 w-full rounded-[1px] bg-g4"><div className="h-full rounded-[1px] bg-g8" style={{ width: `${d ? (t / d) * 100 : 0}%` }} /></div>
          <div className="pointer-events-none absolute top-0 bottom-0 w-[2px] -translate-x-1/2 rounded bg-marker" style={{ left: `${d ? (t / d) * 100 : 0}%` }} />
        </div>
        <IconButton label={muted ? "Sound on (M)" : "Mute (M)"} size="sm" onClick={() => setMuted((m) => !m)}>{muted ? <SpeakerSlash size={16} /> : <SpeakerHigh size={16} />}</IconButton>
        <IconButton label={fs.full ? "Leave full screen (Esc)" : "Full screen (F)"} size="sm" onClick={fs.toggle}>{fs.full ? <CornersIn size={16} /> : <CornersOut size={16} />}</IconButton>
      </div>
    </div>
  );
}

/** Full screen for a player box. Uses the browser's full screen; where that is blocked (some embedded
 *  browsers), the box is pinned over the whole window instead. Esc leaves either way. */
export function useFull<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [full, setFull] = useState(false);
  useEffect(() => {
    const on = () => setFull(!!document.fullscreenElement && document.fullscreenElement === ref.current);
    document.addEventListener("fullscreenchange", on);
    return () => document.removeEventListener("fullscreenchange", on);
  }, []);
  useEffect(() => {
    if (!full || document.fullscreenElement) return;
    const k = (e: KeyboardEvent) => { if (e.key === "Escape") { e.stopPropagation(); setFull(false); } };
    window.addEventListener("keydown", k, true); return () => window.removeEventListener("keydown", k, true);
  }, [full]);
  const toggle = useCallback(() => {
    if (full) { if (document.fullscreenElement) void document.exitFullscreen().catch(() => {}); setFull(false); return; }
    const el = ref.current; if (!el) return;
    el.requestFullscreen().then(() => setFull(true), () => setFull(true));
    setTimeout(() => setFull(true), 0);
  }, [full]);
  // ponytail: the pinned fallback renders in place; a transformed ancestor (an open dialog) would offset it, so dialogs use the real API first.
  const cls = full ? "fixed inset-0 z-[300] justify-center" : "";
  const stageCls = full ? "mx-auto w-[min(100vw,calc((100dvh-48px)*16/9))]" : "";
  return { ref, full, toggle, cls, stageCls };
}

/** A cut clip, with a seek bar that also carries the in/out handles. With a treatment, the original and the
 *  treated version play in sync with a wipe divider over one frame. */
export function ClipPlayer({ src, treated, kind, poster, inT, outT, setIn, setOut, muted, setMuted, cue }: {
  src: string; treated?: string; kind?: string; poster?: string;
  inT: number; outT: number; setIn: (t: number) => void; setOut: (t: number) => void; muted: boolean; setMuted: (m: boolean) => void;
  cue?: { t: number; n: number };   // jump here (a new n jumps again, even to the same time)
}) {
  const a = useRef<HTMLVideoElement>(null); const b = useRef<HTMLVideoElement>(null);
  const bar = useRef<HTMLDivElement>(null); const stage = useRef<HTMLDivElement>(null);
  const [t, setT] = useState(0); const [d, setD] = useState(0);
  const [playing, setPlaying] = useState(true);
  const [wipe, setWipe] = useState(50);
  const fs = useFull<HTMLDivElement>();
  const grab = useRef<"in" | "out" | "head" | null>(null);

  useEffect(() => { setT(0); setPlaying(true); }, [src]);
  useEffect(() => {
    if (!treated) return;
    const id = setInterval(() => { if (a.current && b.current && Math.abs(a.current.currentTime - b.current.currentTime) > 0.08) b.current.currentTime = a.current.currentTime; }, 200);
    return () => clearInterval(id);
  }, [treated]);
  useEffect(() => { if (a.current) a.current.muted = muted; }, [muted]);
  const cued = useRef(-1);
  useEffect(() => { if (cue && d > 0 && cued.current !== cue.n) { cued.current = cue.n; seek(cue.t); } }, [cue, d]); // eslint-disable-line react-hooks/exhaustive-deps

  const seek = (x: number) => { const c = Math.max(0, Math.min((d || 0) - 0.04, x)); [a.current, b.current].forEach((v) => { if (v) v.currentTime = c; }); setT(c); };
  const toggle = () => { const p = !playing; setPlaying(p); [a.current, b.current].forEach((v) => (p ? void v?.play().catch(() => {}) : v?.pause())); };
  const at = (x: number) => { const r = bar.current!.getBoundingClientRect(); return Math.max(0, Math.min(d, ((x - r.left) / r.width) * d)); };
  const pct = (x: number) => `${d ? (x / d) * 100 : 0}%`;
  const move = (x: number) => {
    const v = +at(x).toFixed(1);
    if (grab.current === "in") setIn(Math.min(v, outT - 0.5));
    else if (grab.current === "out") setOut(Math.max(v, inT + 0.5));
    else seek(v);
  };
  const wipeAt = (x: number) => { const r = stage.current!.getBoundingClientRect(); setWipe(Math.max(0, Math.min(100, ((x - r.left) / r.width) * 100))); };
  function key(e: React.KeyboardEvent) {
    if ((e.target as HTMLElement).tagName === "INPUT") return;
    if (e.key === " " || e.key === "k") { e.preventDefault(); toggle(); }
    else if (e.key === "," ) seek(t - 0.04);
    else if (e.key === ".") seek(t + 0.04);
    else if (e.key === "i" || e.key === "[") setIn(Math.min(+t.toFixed(1), outT - 0.5));
    else if (e.key === "o" || e.key === "]") setOut(Math.max(+t.toFixed(1), inT + 0.5));
    else if (e.key === "f") fs.toggle();
    else if (e.key === "m") setMuted(!muted);
  }
  return (
    <div ref={fs.ref} className={cx("flex flex-col bg-black outline-none", fs.cls)} tabIndex={0} onKeyDown={key} aria-label="Clip. Space plays, I and O set in and out, F full screen.">
      <div ref={stage} className={cx("relative aspect-video w-full overflow-hidden bg-black select-none", treated && "cursor-ew-resize", fs.stageCls)}
        onPointerDown={(e) => { if (!treated) return toggle(); (e.target as HTMLElement).setPointerCapture(e.pointerId); wipeAt(e.clientX); }}
        onPointerMove={(e) => treated && e.buttons && wipeAt(e.clientX)}>
        <video ref={a} key={src} src={src} poster={poster} autoPlay loop playsInline muted={muted} className="absolute inset-0 size-full object-cover"
          onTimeUpdate={(e) => setT(e.currentTarget.currentTime)} onLoadedMetadata={(e) => setD(e.currentTarget.duration)} />
        {treated && <>
          <div className="absolute inset-0" style={{ clipPath: `inset(0 0 0 ${wipe}%)` }}>
            <video ref={b} key={treated} src={treated} autoPlay loop muted playsInline className="absolute inset-0 size-full object-cover" />
          </div>
          <div className="pointer-events-none absolute top-0 bottom-0 w-[2px] bg-white shadow-[0_0_0_1px_rgba(0,0,0,0.4)]" style={{ left: `${wipe}%` }}>
            <span className="absolute top-1/2 left-1/2 grid size-8 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full bg-white text-g0"><ArrowsLeftRight size={15} weight="bold" /></span>
          </div>
          <span className="absolute top-2 left-2 rounded-xs bg-black/70 px-1.5 py-0.5 text-[11px] font-semibold">Original</span>
          <span className="absolute top-2 right-2 rounded-xs bg-black/70 px-1.5 py-0.5 text-[11px] font-semibold text-edge">Treated · {kind === "blur_fill" ? "blur fill" : "10% crop"}</span>
        </>}
      </div>
      <div className="flex h-12 items-center gap-2 border-t border-g4 bg-g1 px-2">
        <IconButton label={playing ? "Pause (Space)" : "Play (Space)"} onClick={toggle}>{playing ? <Pause size={18} weight="fill" /> : <Play size={18} weight="fill" />}</IconButton>
        <span className="w-[124px] shrink-0 edge text-[12.5px] whitespace-nowrap">{mmss(t, true)} <span className="text-g8">/ {mmss(d)}</span></span>
        <div ref={bar} role="slider" aria-label="Position" aria-valuemin={0} aria-valuemax={Math.round(d)} aria-valuenow={Math.round(t)} tabIndex={-1}
          className="relative mx-2 h-8 flex-1 cursor-pointer touch-none"
          onPointerDown={(e) => { (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId); const h = (e.target as HTMLElement).dataset.h as "in" | "out" | undefined; grab.current = h ?? "head"; if (!h) seek(at(e.clientX)); }}
          onPointerMove={(e) => { if (e.buttons && grab.current) move(e.clientX); }}
          onPointerUp={() => { grab.current = null; }}>
          <div className="absolute inset-x-0 top-1/2 h-1.5 -translate-y-1/2 rounded-[1px] bg-g4" />
          <div className="absolute top-1/2 h-1.5 -translate-y-1/2 bg-edge/70" style={{ left: pct(inT), width: `calc(${pct(outT)} - ${pct(inT)})` }} />
          <div className="absolute top-1/2 h-1.5 -translate-y-1/2 bg-g8/50" style={{ width: pct(t) }} />
          {(["in", "out"] as const).map((h) => (
            <Tip key={h} label={h === "in" ? "Drag to set where the clip starts (I)" : "Drag to set where it ends (O)"}>
              <span data-h={h} className="absolute top-0 bottom-0 z-10 w-3 -translate-x-1/2 cursor-ew-resize" style={{ left: pct(h === "in" ? inT : outT) }}>
                <span data-h={h} className={cx("absolute inset-y-1 left-1/2 w-[3px] -translate-x-1/2 rounded-full bg-edge", h === "in" ? "rounded-r-none" : "rounded-l-none")} />
              </span>
            </Tip>
          ))}
          <div className="pointer-events-none absolute top-0.5 bottom-0.5 w-[2px] -translate-x-1/2 rounded bg-marker" style={{ left: pct(t) }} />
        </div>
        <IconButton label={muted ? "Sound on (M)" : "Mute (M)"} size="sm" onClick={() => setMuted(!muted)}>{muted ? <SpeakerSlash size={16} /> : <SpeakerHigh size={16} />}</IconButton>
        <IconButton label={fs.full ? "Leave full screen (Esc)" : "Full screen (F)"} size="sm" onClick={fs.toggle}>{fs.full ? <CornersIn size={16} /> : <CornersOut size={16} />}</IconButton>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- VO only: the 9:16 preview

export interface VoSeg { sid: string; n: number; start: number; dur: number; text: string; audio?: string; cuts: CutItem[]; gap: number }

/** The VO-only story on one clock: each beat as long as its voice (the edit's seconds), its cuts in play order. */
export function buildVoCut(p: Project): VoSeg[] {
  let t = 0;
  return sections(p).map((s, i) => {
    const b = p.edit?.beats.find((x) => x.sectionId === s.id);
    const dur = Math.max(1, b?.secs ?? sectionSeconds(s, p.anchorId).sec);
    const take = s.voice?.takes.find((x) => x.id === s.voice?.pick);
    let at = t;
    const cuts = (b?.cuts ?? []).map((c, k): CutItem => {
      const it: CutItem = { kind: c.clip ? "video" : "image", src: c.clip ?? (c.src.kind === "picture" && c.src.url ? c.src.url : c.poster), start: at, dur: c.secs, in: 0, code: `B${i + 1}·${k + 1}`, label: c.shows, poster: c.poster };
      at += c.secs; return it;
    });
    const seg: VoSeg = { sid: s.id, n: i + 1, start: t, dur, text: s.text, audio: take?.src, cuts, gap: Math.max(0, t + dur - at) };
    t += dur;
    return seg;
  });
}

/** A phone-shaped 9:16 preview: the cuts in sequence, each centre-cropped (a stand-in for the reframer), under the
 *  beat's line as a caption and over the voice where it is made. */
export function PhonePlayer({ p, time, onTime, autoPlay, width = 300 }: { p: Project; time?: { t: number; nonce: number }; onTime?: (t: number) => void; autoPlay?: boolean; width?: number }) {
  const cut = useMemo(() => buildVoCut(p), [p]);
  const total = Math.max(0.01, cut.reduce((n, s) => n + s.dur, 0));
  const [t, setT] = useState(0);
  const [playing, setPlaying] = useState(!!autoPlay);
  const [muted, setMuted] = useState(false);
  const audio = useRef<HTMLAudioElement>(null);
  const bar = useRef<HTMLDivElement>(null);
  const tRef = useRef(0); const last = useRef(0);
  const segAt = (x: number) => cut.find((s) => x >= s.start && x < s.start + s.dur);
  const seg = segAt(t) ?? cut[cut.length - 1];
  const item = seg?.cuts.find((i) => t >= i.start && t < i.start + i.dur);
  const voiced = cut.some((s) => s.audio);

  const seek = useCallback((nt: number) => {
    const c = Math.max(0, Math.min(total - 0.01, nt));
    tRef.current = c; setT(c); onTime?.(c);
    const s = cut.find((x) => c >= x.start && c < x.start + x.dur); const a = audio.current;
    if (a && s?.audio) { if (!a.src.endsWith(s.audio)) a.src = s.audio; a.currentTime = Math.max(0, c - s.start); }
  }, [cut, total, onTime]);
  useEffect(() => { if (time) seek(time.t); }, [time?.nonce]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!playing) return;
    let raf = 0;
    last.current = performance.now();
    const step = (now: number) => {
      const nt = tRef.current + (now - last.current) / 1000; last.current = now;
      if (nt >= total) { setPlaying(false); seek(0); return; }
      const prev = segAt(tRef.current); const next = segAt(nt);
      tRef.current = nt; setT(nt); onTime?.(nt);
      if (next && prev !== next) { const a = audio.current; if (a) { if (next.audio) { a.src = next.audio; a.currentTime = 0; void a.play().catch(() => {}); } else a.pause(); } }
      raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    const a = audio.current; const s = segAt(tRef.current);
    if (a && s?.audio) { if (!a.src.endsWith(s.audio)) a.src = s.audio; a.currentTime = tRef.current - s.start; void a.play().catch(() => {}); }
    return () => { cancelAnimationFrame(raf); audio.current?.pause(); };
  }, [playing]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (audio.current) audio.current.muted = muted; }, [muted]);

  function key(e: React.KeyboardEvent) {
    if (e.key === " " || e.key === "k") { e.preventDefault(); setPlaying((v) => !v); }
    else if (e.key === "ArrowRight") seek(tRef.current + (e.shiftKey ? 5 : 1));
    else if (e.key === "ArrowLeft") seek(tRef.current - (e.shiftKey ? 5 : 1));
  }
  const at = (x: number) => { const r = bar.current!.getBoundingClientRect(); return ((x - r.left) / r.width) * total; };
  const caption = seg ? captionAt(seg.text, (t - seg.start) / seg.dur) : "";
  return (
    <div className="flex flex-col items-center gap-3 outline-none" tabIndex={0} onKeyDown={key} aria-label="9:16 preview. Space plays, arrows step." style={{ width: `min(${width + 14}px, 100%)` }}>
      <div className="w-full rounded-[26px] bg-g2 p-[7px] ring-1 ring-g5 shadow-[0_30px_80px_-30px_rgba(0,0,0,0.9)]">
        <div className="relative aspect-[9/16] w-full overflow-hidden rounded-[19px] bg-black [container-type:inline-size]">
          <AnimatePresence initial={false}>
            {item ? (
              <motion.div key={`${seg!.sid}-${item.start}`} className="absolute inset-0" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.16 }}>
                <Media item={item} t={t} playing={playing} fill />
              </motion.div>
            ) : seg && (
              <motion.div key={`gap-${seg.sid}`} className="absolute inset-0 grid place-items-center px-[10%] text-center text-[4.2cqw] text-warn" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
                {seg.cuts.length ? `No picture for the last ${seg.gap.toFixed(1)} s of beat ${seg.n}` : `No pictures for beat ${seg.n}`}
              </motion.div>
            )}
          </AnimatePresence>
          {caption && (
            <div className="pointer-events-none absolute inset-x-[8%] bottom-[17%] text-center">
              <span className="box-decoration-clone rounded-[0.2em] bg-black/70 px-[0.35em] py-[0.08em] text-[5.4cqw] leading-[1.42] font-semibold text-white">{caption}</span>
            </div>
          )}
          {!playing && t === 0 && (
            <button onClick={() => setPlaying(true)} className="absolute inset-0 grid place-items-center bg-black/25 transition-colors hover:bg-black/10" aria-label="Play">
              <span className="grid size-14 place-items-center rounded-full bg-marker/95 shadow-[0_10px_30px_-6px_rgba(0,0,0,0.7)]"><Play size={24} weight="fill" className="ml-1 text-white" /></span>
            </button>
          )}
          <audio ref={audio} preload="auto" />
        </div>
      </div>
      <div className="flex w-full items-center gap-1.5">
        <IconButton label={playing ? "Pause (Space)" : "Play (Space)"} size="sm" onClick={() => setPlaying((v) => !v)}>{playing ? <Pause size={16} weight="fill" /> : <Play size={16} weight="fill" />}</IconButton>
        <span className="edge shrink-0 text-[12px] whitespace-nowrap">{mmss(t, true)} <span className="text-g8">/ {mmss(total)}</span></span>
        <div ref={bar} role="slider" aria-label="Position" aria-valuemin={0} aria-valuemax={Math.round(total)} aria-valuenow={Math.round(t)} tabIndex={-1}
          className="relative flex h-6 flex-1 cursor-pointer items-center gap-px"
          onPointerDown={(e) => { (e.target as HTMLElement).setPointerCapture(e.pointerId); seek(at(e.clientX)); }}
          onPointerMove={(e) => { if (e.buttons) seek(at(e.clientX)); }}>
          {cut.map((s) => <div key={s.sid} className="h-1.5 rounded-[1px] bg-vo/45" style={{ flexGrow: s.dur }} />)}
          <div className="pointer-events-none absolute top-0 bottom-0 w-[2px] -translate-x-1/2 rounded bg-marker" style={{ left: `${(t / total) * 100}%` }} />
        </div>
        <IconButton label={!voiced ? "No voice made yet" : muted ? "Sound on" : "Mute"} size="sm" disabled={!voiced} onClick={() => setMuted((m) => !m)}>{muted || !voiced ? <SpeakerSlash size={15} /> : <SpeakerHigh size={15} />}</IconButton>
      </div>
    </div>
  );
}
