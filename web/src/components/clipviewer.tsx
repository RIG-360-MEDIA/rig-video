// Clip viewer over the page. With the whole found video downloaded: it plays in full, its moments sit below as jump
// buttons that also set the in/out handles, and any range the person marks can be used. Without it (still downloading,
// or too long to download): the moment's own cut clip, with Treated / Original tabs.
import { useEffect, useState } from "react";
import { CaretLeft, CaretRight, ArrowLeft, ArrowRight } from "@phosphor-icons/react";
import type { FoundVideo, Id } from "@/data/types";
import { addMoment } from "@/data/store";
import { Button, Dialog, IconButton, Kbd, Segmented, Tag, cx, mmss, istDate } from "./ui";
import { ClipPlayer } from "./player";

const TREAT: Record<string, string> = { crop: "a 10% crop from the centre, which takes the channel logo in the corner out.", blur_fill: "vertical phone video sits full height over a blurred, darker copy of itself." };

export interface ViewerTarget { video: FoundVideo; moment: number; code: string }

export function ClipViewer({ pid, target, onClose, onUse, useLabel, next, prev, placedAs }: {
  pid: Id; target: ViewerTarget | null; onClose: () => void;
  onUse: (t: { videoId: string; moment: number; in: number; out: number; muted: boolean; useTreated: boolean }) => void;
  useLabel: string; next?: () => void; prev?: () => void; placedAs?: number;
}) {
  const v = target?.video; const m = v?.moments[target!.moment];
  const whole = !!v?.source;
  const [inT, setIn] = useState(0); const [outT, setOut] = useState(5);
  const [cue, setCue] = useState({ t: 0, n: 0 });
  const [muted, setMuted] = useState(true);
  const [view, setView] = useState<"treated" | "original">("treated");
  const [busy, setBusy] = useState(false);
  const len = m?.clip ? Math.max(1, m.end - m.start) : 0;

  const jump = (i: number) => {                          // a moment: handles on it, playhead to its start
    const x = v!.moments[i];
    setIn(x.start); setOut(Math.min(x.end, v!.duration || x.end)); setCue((c) => ({ t: x.start, n: c.n + 1 }));
  };
  useEffect(() => {
    if (!m) return;
    setView("treated");
    if (whole) jump(target!.moment);
    else { setIn(0); setOut(Math.min(len || 5, 6)); }
  }, [target?.video.id, target?.moment, whole]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!target) return;
    const k = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).tagName === "INPUT") return;
      if (e.key === "ArrowRight" && next) next();
      if (e.key === "ArrowLeft" && prev) prev();
    };
    window.addEventListener("keydown", k); return () => window.removeEventListener("keydown", k);
  }, [target, next, prev]);

  if (!v || !m) return <Dialog open={false} onOpenChange={onClose} title="">{null}</Dialog>;
  const on = whole ? v.moments.findIndex((x) => !x.cutFailed && Math.abs(x.start - inT) < 0.15 && Math.abs(Math.min(x.end, v.duration || x.end) - outT) < 0.15) : target!.moment;
  const cur = on >= 0 ? v.moments[on] : undefined;
  const warn = (cur?.flags ?? []).filter((f) => f === "presenter" || f === "text");
  const treated = !whole && !!m.treat && view === "treated";
  const src = whole ? v.source! : treated ? m.treat!.preview : m.clip;

  async function use() {
    if (!whole) return onUse({ videoId: v!.id, moment: target!.moment, in: inT, out: m!.clip ? outT : 5, muted, useTreated: treated });
    setBusy(true);                                       // the marked range becomes a moment of this video (or is one already)
    const i = on >= 0 ? on : await addMoment(pid, v!.id, inT, outT);
    setBusy(false);
    if (i !== null) onUse({ videoId: v!.id, moment: i, in: 0, out: outT - inT, muted, useTreated: true });
  }

  return (
    <Dialog open={!!target} onOpenChange={(o) => !o && onClose()} title={whole ? v.title : m.label} wide="full">
      <div className="grid lg:grid-cols-[minmax(0,1fr)_340px]">
        <div className="min-w-0 border-g4 p-5 lg:border-r">
          {src ? (
            <ClipPlayer key={src} src={src} poster={whole ? v.thumb : m.poster} kind={m.treat?.kind} cue={whole ? cue : undefined}
              inT={inT} outT={outT} setIn={setIn} setOut={setOut} muted={muted} setMuted={setMuted} />
          ) : (
            <div className="relative aspect-video overflow-hidden rounded-[2px] bg-black">
              <img src={m.poster ?? v.thumb} alt="" className="size-full object-cover opacity-70" />
              <div className="absolute inset-0 grid place-items-center bg-black/60 text-center backdrop-blur-[2px]">
                {m.cutFailed
                  ? <div><p className="text-[14px] text-g10">This clip could not be downloaded</p><p className="mt-1 text-[12.5px] text-g8">Pick another moment.</p></div>
                  : <div><p className="text-[14px] text-g10">The video is still downloading</p><p className="mt-1 text-[12.5px] text-g8">It plays here as soon as it is ready.</p></div>}
              </div>
            </div>
          )}
          {src && (
            <div className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-3">
              {!whole && m.treat && <Segmented label="Viewer" size="sm" value={view} set={setView} options={[{ v: "treated", l: "Treated" }, { v: "original", l: "Original" }]} />}
              <span className="flex items-center gap-3 text-[13px] text-g8">
                <span>In <span className="edge">{mmss(inT, true)}</span></span><span>Out <span className="edge">{mmss(outT, true)}</span></span>
                <span>Uses <span className="edge">{(outT - inT).toFixed(1)}s</span></span>
              </span>
              <span className="text-[12px] text-g8">Drag the amber handles on the bar, or press <Kbd>I</Kbd> <Kbd>O</Kbd> at the playhead.</span>
            </div>
          )}
          {whole && (
            <div className="mt-6">
              <div className="mb-2 text-[12px] font-semibold text-g8">Moments in this video · click one to jump there</div>
              <div className="flex flex-wrap gap-2">
                {v.moments.map((x, i) => !x.cutFailed && (
                  <button key={i} onClick={() => jump(i)} aria-pressed={on === i}
                    className={cx("max-w-full rounded-sm border px-2.5 py-1.5 text-left text-[12.5px] transition-colors",
                      on === i ? "border-edge bg-edge/12 text-g10" : "border-g5 text-g9 hover:border-g7")}>
                    <span className="edge">{mmss(x.start)}–{mmss(Math.min(x.end, v.duration || x.end))}</span>
                    <span className="ml-2 line-clamp-1 inline">{x.custom ? "Your clip" : x.label}</span>
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
        <aside className="flex flex-col p-5">
          <div className="text-[13px] leading-snug font-semibold text-g10">{v.title}</div>
          <div className="mt-1 text-[12.5px] text-g8">{v.channel}{v.publishedAt ? ` · ${istDate(v.publishedAt)}` : ""} · {mmss(v.duration)} · <span className="edge">{target!.code}</span></div>
          <div className="mt-3 flex flex-wrap gap-1.5">
            <Tag tone={v.relevance >= 70 ? "ok" : v.relevance >= 40 ? "warn" : "neutral"}>{v.relevance >= 70 ? "Strong fit" : v.relevance >= 40 ? "Partial" : "Weak"} {v.relevance}</Tag>
            {!v.hasCaptions && <Tag>No captions</Tag>}
            {cur?.estimated && <Tag>≈ estimated time</Tag>}
          </div>
          {cur ? <>
            {cur.description && <p className="mt-4 text-[13px] leading-relaxed text-g9">{cur.description}</p>}
            {cur.fit && <p className="mt-2 text-[12.5px] leading-relaxed text-g8"><span className="font-semibold text-g9">Fits: </span>{cur.fit}</p>}
          </> : <p className="mt-4 text-[13px] leading-relaxed text-g9">Your own clip: {mmss(inT, true)}–{mmss(outT, true)}.</p>}
          {whole
            ? <p className="mt-4 rounded-sm border border-g5 bg-g2 p-3 text-[12.5px] leading-relaxed text-g9"><span className="font-semibold text-g10">Treatment: </span>logos at the edges are cropped out and upright phone video gets a blurred fill, when the clip is cut.</p>
            : m.treat && <p className="mt-4 rounded-sm border border-g5 bg-g2 p-3 text-[12.5px] leading-relaxed text-g9"><span className="font-semibold text-g10">Treatment: </span>{TREAT[m.treat.kind]}</p>}
          {warn.length > 0 && <p className="mt-2 rounded-sm border border-warn/40 bg-warn/8 p-3 text-[12.5px] leading-relaxed text-g9">{warn.map((f) => (f === "presenter" ? "A presenter on camera" : "On-screen text")).join(" and ")} in this shot. Treatment can't remove {warn.length > 1 ? "these" : "it"}; pick a cleaner moment if you can.</p>}
          <div className="mt-auto space-y-3 pt-6">
            <Button kind="primary" className="w-full" disabled={busy || !src} onClick={() => void use()}>
              {whole ? `Use this · ${(outT - inT).toFixed(1)} s` : placedAs ? `Picked as ${placedAs}. Use again` : useLabel}
            </Button>
            {whole && <p className="text-center text-[12px] text-g8">{useLabel} · {mmss(inT, true)}–{mmss(outT, true)}{placedAs && on === target!.moment ? ` · picked as ${placedAs}` : ""}</p>}
            {!whole && m.treat && view === "original" && <p className="text-center text-[12px] text-warn">Uses the original, without the treatment</p>}
            <div className="flex items-center justify-between text-[12px] text-g8">
              <span className="flex items-center gap-1"><Kbd><ArrowLeft size={10} weight="bold" /></Kbd><Kbd><ArrowRight size={10} weight="bold" /></Kbd> moments</span>
              <span className="flex gap-1">
                <IconButton label="Previous moment" size="sm" onClick={prev} disabled={!prev}><CaretLeft size={14} /></IconButton>
                <IconButton label="Next moment" size="sm" onClick={next} disabled={!next}><CaretRight size={14} /></IconButton>
              </span>
            </div>
          </div>
        </aside>
      </div>
    </Dialog>
  );
}
