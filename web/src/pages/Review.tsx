import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { AnimatePresence, motion } from "motion/react";
import WaveSurfer from "wavesurfer.js";
import { Play, Pause, ArrowCounterClockwise, Microphone, VideoCamera, Lock, ArrowRight, CheckCircle, Waveform, Queue, Robot, FilmSlate, Warning, YoutubeLogo, ArrowSquareOut, PaperPlaneTilt } from "@phosphor-icons/react";
import { useStore, sections, sectionSeconds, fillOf, anchorOf, pickTake, revoice, sendToRender, toast, beatOf, remakeFinal, postDefaults, postVideo } from "@/data/store";
import type { Project, Section } from "@/data/types";
import { useProject } from "@/components/story";
import { RoughCutPlayer, buildCut, buildVoCut, PhonePlayer, type CutSeg, type VoSeg } from "@/components/player";
import { Button, Dialog, Input, Switch, Textarea, Tip, cx, istTime, mmss } from "@/components/ui";
import { Graphics, AnchorPicker, VoiceSample } from "./Script";
import { FinishedCard } from "./Render";

const RENDER_MIN_PER_SEC = 0.23; // render machine: about 14 s of GPU time per second of video

export default function ReviewPage() {
  const p = useProject()!;
  const queue = useStore((s) => s.queue);
  const defaults = useStore((s) => s.defaults);
  const nav = useNavigate();
  const [time, setTime] = useState<{ t: number; nonce: number }>();
  const [now, setNow] = useState(0);
  const [sel, setSel] = useState<string | null>(null);
  const [opts, setOpts] = useState({ captions: "none" as const, aiLabel: false, outro: defaults.outro })   // subtitles and the AI label: not built yet, hidden;
  const [confirm, setConfirm] = useState(false);
  const vo = p.format === "vo_only";
  const cut = useMemo(() => buildCut(p), [p]);
  const voCut = useMemo(() => (vo ? buildVoCut(p) : []), [p, vo]);
  const total = vo ? voCut.reduce((n, s) => n + s.dur, 0) : cut.reduce((n, s) => n + s.dur, 0);
  const list = sections(p);
  const locked = p.stage === "render" || p.stage === "done";
  const voicing = list.filter((s) => s.voice && s.voice.state !== "ready");
  const short = list.filter((s) => !fillOf(p, s).full);
  // VO only: short beats are allowed (Visuals said so); the edit must be checked
  const ready = !voicing.length && (vo ? p.edit?.state === "ready" : !short.length);
  const estMin = Math.max(4, Math.round(total * RENDER_MIN_PER_SEC));
  const ahead = queue.length;
  const done = p.stage === "done" && p.final?.state === "ready" && !!p.final.video;   // the final page: video + Post

  const seek = (t: number) => setTime({ t, nonce: Date.now() });
  function go() {
    sendToRender(p.id, { outro: !vo && opts.outro });
    toast(ahead ? `Queued. ${ahead} ${ahead === 1 ? "video" : "videos"} ahead of it.` : "Rendering now. You can start another story.", "ok");
    nav("/desk");
  }

  return (
    <div className="mx-auto max-w-[1440px] px-5 pt-5 pb-24 lg:px-8">
      <div className="grid grid-cols-1 gap-x-8 gap-y-10 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="min-w-0">
          {vo ? <VoPreview p={p} cut={voCut} total={total} time={time} now={now} onTime={setNow} sel={sel} onSeek={seek}
              onSelect={(sid, t) => { setSel(sid); seek(t); document.getElementById(`voice-${sid}`)?.scrollIntoView({ behavior: "smooth", block: "nearest" }); }} />
            : done ? <video src={p.final!.video} poster={p.final!.poster} controls playsInline preload="metadata" className="block aspect-video w-full rounded-md bg-black" aria-label="The final video" />
            : <>
              <RoughCutPlayer p={p} time={time} onTime={setNow} extras={opts} />
              <Timeline cut={cut} total={total} now={now} sel={sel} onSeek={seek} onSelect={(sid, t) => { setSel(sid); seek(t); document.getElementById(`voice-${sid}`)?.scrollIntoView({ behavior: "smooth", block: "nearest" }); }} p={p} />
            </>}

          <section aria-labelledby="voice-h" className="mt-10">
            <div className="mb-4 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
              <h2 id="voice-h" className="text-[17px] font-semibold">Listen to each {vo ? "beat" : "part"}</h2>
              <span className="text-[12.5px] text-g8">Pick the take you like, or say what should change and we make it again.</span>
            </div>
            <ol className="space-y-3">
              {list.map((s, i) => <VoicePart key={s.id} p={p} s={s} n={cut[i]?.n ?? i + 1} label={vo ? `Beat ${i + 1}` : undefined} active={sel === s.id} locked={locked}
                onFocus={() => { setSel(s.id); const c = vo ? voCut[i] : cut[i]; if (c) seek(c.start); }} />)}
            </ol>
          </section>
          {!vo && <Graphics p={p} locked={locked} />}
        </div>

        <aside className="space-y-8 xl:sticky xl:top-[72px] xl:self-start">
          {vo || done ? <PostCard p={p} voicing={voicing.length} short={short.length} total={total} />
            : <RenderCard p={p} ready={ready} locked={locked} voicing={voicing.length} short={short.length} estMin={estMin} ahead={ahead} total={total} onRender={() => setConfirm(true)} />}
          {p.stage === "done" && <FinishedCard p={p} />}
          <AnchorBox p={p} locked={locked} />
          {!vo && <section aria-labelledby="out-h">
            <h2 id="out-h" className="text-[15px] font-semibold">Extras on the final video</h2>
            <p className="mt-0.5 mb-3 text-[12.5px] text-g8">Shows in the preview on the left as you switch it.</p>
            <div className="divide-y divide-g4 rounded-md border border-g4 bg-g1">
              <div className="p-4"><Switch id="outro" on={opts.outro} set={(v) => setOpts({ ...opts, outro: v })} label="DNL outro" hint="The DNL outro (12 seconds) plays after the last part" /></div>
            </div>
          </section>}
        </aside>
      </div>

      <Dialog open={confirm} onOpenChange={setConfirm} title="Send to the render machine?">
        <div className="space-y-4 p-5 text-[14px]">
          <dl className="grid grid-cols-[120px_minmax(0,1fr)] gap-y-2 text-[13.5px]">
            <dt className="text-g8">Length</dt><dd className="edge">{mmss(total)}</dd>
            <dt className="text-g8">{vo ? "Voice" : "Anchor"}</dt><dd>{anchorOf(p.anchorId)?.name}</dd>
            {vo ? <><dt className="text-g8">Format</dt><dd>9:16, voice over footage, no anchor render</dd></>
              : <><dt className="text-g8">Takes about</dt><dd><span className="edge">{estMin} min</span> on the GPU</dd></>}
            <dt className="text-g8">Queue</dt><dd>{ahead ? `${ahead} ahead, starts when ${ahead === 1 ? "it finishes" : "they finish"}` : "Starts now"}</dd>
            {!vo && <><dt className="text-g8">Extras</dt><dd>{opts.outro ? "DNL outro" : "None"}</dd></>}
          </dl>
          <p className="text-[13px] text-g8">While it renders, the story is locked. You can cancel from the desk until it finishes.</p>
          <div className="flex justify-end gap-2">
            <Button kind="ghost" onClick={() => setConfirm(false)}>Not yet</Button>
            <Button kind="primary" onClick={go}>Render</Button>
          </div>
        </div>
      </Dialog>
    </div>
  );
}

// ------------------------------------------------------------------ timeline under the player

function Timeline({ cut, total, now, sel, onSeek, onSelect, p }: { cut: CutSeg[]; total: number; now: number; sel: string | null; onSeek: (t: number) => void; onSelect: (sid: string, t: number) => void; p: Project }) {
  const track = useRef<HTMLDivElement>(null);
  const pct = (t: number) => `${(t / Math.max(total, 0.01)) * 100}%`;
  const [drag, setDrag] = useState(false);
  const at = (x: number) => { const r = track.current!.getBoundingClientRect(); return Math.max(0, Math.min(1, (x - r.left) / r.width)) * total; };
  useEffect(() => {
    if (!drag) return;
    const mv = (e: PointerEvent) => onSeek(at(e.clientX));
    const up = () => setDrag(false);
    window.addEventListener("pointermove", mv); window.addEventListener("pointerup", up);
    return () => { window.removeEventListener("pointermove", mv); window.removeEventListener("pointerup", up); };
  }, [drag]); // eslint-disable-line react-hooks/exhaustive-deps
  const ticks = Array.from({ length: Math.floor(total / 10) + 1 }, (_, i) => i * 10);
  const row = "relative h-9";
  return (
    <div className="mt-4 select-none rounded-md border border-g4 bg-g1 p-3 pl-0">
      <div className="grid grid-cols-[72px_minmax(0,1fr)] gap-y-1.5">
        <span />
        <div className="relative h-4 cursor-pointer" onPointerDown={(e) => { onSeek(at(e.clientX)); setDrag(true); }}>
          {ticks.map((t) => <span key={t} className="absolute top-0 font-mono text-[11px] text-edge" style={{ left: pct(t) }}><span className="absolute -bottom-1 left-0 h-1.5 w-px bg-g5" /><span className="pl-1">{mmss(t)}</span></span>)}
        </div>
        {(["Parts", "Pictures", "Graphics"] as const).map((r) => (
          <Row key={r} label={r}>
            <div className={row}>
              {r === "Parts" && cut.map((s) => (
                <button key={s.sid} onClick={() => onSelect(s.sid, s.start)} aria-label={`${s.kind === "anchor" ? "Anchor" : "VO"} ${s.n}, ${mmss(s.dur)}`}
                  className={cx("absolute inset-y-0 flex items-center gap-1 overflow-hidden rounded-[2px] border px-1.5 text-left text-[11px] font-semibold transition-[filter,border-color]",
                    s.kind === "anchor" ? "border-anchor/40 bg-anchor/18 text-anchor" : "border-vo/40 bg-vo/16 text-vo", sel === s.sid ? "border-g10 brightness-125" : "hover:brightness-125")}
                  style={{ left: pct(s.start), width: `calc(${pct(s.dur)} - 2px)` }}>
                  {s.kind === "anchor" ? <VideoCamera size={11} weight="fill" className="shrink-0" /> : <Microphone size={11} weight="fill" className="shrink-0" />}
                  <span className="truncate">{s.kind === "anchor" ? "A" : "VO"}{s.n}</span>
                </button>
              ))}
              {r === "Pictures" && cut.flatMap((s) => (s.kind === "anchor" ? (s.behind ? [{ ...s.behind, start: s.start, dur: s.dur }] : []) : s.items).map((it, i) => (
                <Tip key={`${s.sid}-${i}`} label={<span><span className="edge">{it.code}</span> {it.label}</span>}>
                  <button onClick={() => onSeek(it.start)} className="absolute inset-y-0 overflow-hidden rounded-[2px] bg-g3 ring-1 ring-g5 hover:ring-g8" style={{ left: pct(it.start), width: `calc(${pct(it.dur)} - 2px)` }} aria-label={`Picture ${it.code}`}>
                    {it.kind === "image" ? <img src={it.src} alt="" className="size-full object-cover opacity-80" /> : <video src={it.src} muted preload="metadata" className="size-full object-cover opacity-80" />}
                    <span className="absolute bottom-0 left-0 bg-black/70 px-1 font-mono text-[11px] text-edge">{it.code}</span>
                  </button>
                </Tip>
              )))}
              {r === "Graphics" && <>
                {cut.filter((s) => s.kind === "anchor" && s.lt?.headline).map((s) => (
                  <Tip key={s.sid} label={`${s.lt!.kicker} · ${s.lt!.headline}`}>
                    <button onClick={() => onSeek(s.start + 0.5)} className="absolute top-0 h-[18px] overflow-hidden rounded-[2px] bg-marker/85 px-1.5 text-left text-[11px] font-bold whitespace-nowrap text-white uppercase" style={{ left: pct(s.start + 0.5), width: `calc(${pct(Math.max(1, s.dur - 1))} - 2px)` }}>
                      {s.lt!.headline || "Lower third"}
                    </button>
                  </Tip>
                ))}
                {p.ticker.length > 0 && <span className="absolute inset-x-0 bottom-0 flex h-[16px] items-center overflow-hidden rounded-[2px] bg-g10/12 px-1.5 text-[11px] font-semibold whitespace-nowrap text-g9 uppercase">Ticker · {p.ticker.join("  ·  ")}</span>}
              </>}
            </div>
          </Row>
        ))}
      </div>
      <div className="pointer-events-none relative ml-[72px] -mt-[134px] h-[134px]">
        <motion.span className="absolute top-0 bottom-0 w-px bg-marker" style={{ left: pct(now) }}>
          <span className="absolute -top-0.5 -left-[4px] size-[9px] rotate-45 bg-marker" />
        </motion.span>
      </div>
    </div>
  );
}
function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return <><span className="flex items-center justify-end pr-3 text-[11.5px] text-g8">{label}</span><div className="pr-3">{children}</div></>;
}

// ------------------------------------------------------------------ voice per part

const ASKS = ["Slower", "Faster", "More serious", "Less flat", "Fix a name", "Pause before the last line"];

function VoicePart({ p, s, n, label, active, locked, onFocus }: { p: Project; s: Section; n: number; label?: string; active: boolean; locked: boolean; onFocus: () => void }) {
  const name = label ?? `${s.kind === "anchor" ? "Anchor" : "VO"} ${n}`;
  const v = s.voice;
  const take = v?.takes.find((t) => t.id === v.pick);
  const [ask, setAsk] = useState(false);
  const [note, setNote] = useState("");
  const [chips, setChips] = useState<string[]>([]);
  const busy = !v || v.state === "making" || v.state === "redoing" || v.state === "waiting";
  const sec = sectionSeconds(s, p.anchorId);
  function send() {
    const text = [...chips, note.trim()].filter(Boolean).join(". ");
    if (!text) return;
    revoice(p.id, s.id, text); setAsk(false); setNote(""); setChips([]);
    toast(`Making a new take for ${name}`);
  }
  return (
    <motion.li id={`voice-${s.id}`} layout className={cx("scroll-mt-20 rounded-md border bg-g1 transition-colors", active ? "border-g7" : "border-g4")}>
      <div className="grid grid-cols-1 gap-4 p-4 md:grid-cols-[230px_minmax(0,1fr)]">
        <button onClick={onFocus} className="text-left">
          <span className={cx("flex items-center gap-1.5 text-[13.5px] font-semibold", s.kind === "anchor" ? "text-anchor" : "text-vo")}>
            {s.kind === "anchor" ? <VideoCamera size={14} weight="fill" /> : <Microphone size={14} weight="fill" />}{name}
            <span className="edge ml-1 text-[12px] font-normal">{mmss(sec.sec)}</span>
          </span>
          <span className="mt-1.5 line-clamp-5 block text-[12.5px] leading-relaxed text-g8">{s.text}</span>
        </button>
        <div className="min-w-0">
          {busy ? (
            <div className="flex h-[52px] items-center gap-3 rounded-sm border border-dashed border-g5 px-3">
              <span className="flex h-5 items-end gap-[3px]">{[0, 1, 2, 3, 4].map((i) => <motion.span key={i} className="w-[3px] rounded-full bg-vo" animate={{ height: ["20%", "100%", "35%"] }} transition={{ duration: 0.8, repeat: Infinity, delay: i * 0.1 }} />)}</span>
              <span className="text-[13px] text-g9">{v?.state === "redoing" ? `Making a new take: “${v.note}”` : "Making the voice on the GPU"}</span>
            </div>
          ) : take ? <Wave src={take.src} key={take.id} /> : null}
          {v && v.takes.length > 0 && (
            <div className="mt-3 flex flex-wrap items-center gap-1.5" role="radiogroup" aria-label="Takes">
              {v.takes.map((t, i) => (
                <button key={t.id} role="radio" aria-checked={v.pick === t.id} disabled={locked} onClick={() => pickTake(p.id, s.id, t.id)}
                  className={cx("flex h-7 items-center gap-1.5 rounded-full border px-2.5 text-[12px] transition-colors", v.pick === t.id ? "border-marker bg-marker/12 text-g10" : "border-g5 text-g8 hover:border-g7 hover:text-g10")}>
                  {v.pick === t.id && <CheckCircle size={12} weight="fill" className="text-marker" />}Take {i + 1}<span className="edge text-[11px]">{mmss(t.seconds, true)}</span>
                </button>
              ))}
              {!locked && !busy && <Button kind="ghost" size="sm" className="ml-auto" icon={<ArrowCounterClockwise size={13} />} onClick={() => setAsk((a) => !a)} aria-expanded={ask}>What should change?</Button>}
            </div>
          )}
          <AnimatePresence>
            {ask && (
              <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }} className="overflow-hidden">
                <div className="mt-3 space-y-2.5 rounded-sm border border-g5 bg-g2 p-3">
                  <div className="flex flex-wrap gap-1.5">
                    {ASKS.map((c) => (
                      <button key={c} onClick={() => setChips((x) => x.includes(c) ? x.filter((y) => y !== c) : [...x, c])} aria-pressed={chips.includes(c)}
                        className={cx("h-7 rounded-full border px-2.5 text-[12px] transition-colors", chips.includes(c) ? "border-g9 bg-g9 text-g0" : "border-g5 text-g9 hover:border-g7")}>{c}</button>
                    ))}
                  </div>
                  <Textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2} placeholder="Say it in your words, e.g. “Lipetsk is LEE-petsk”" aria-label="What should change" />
                  <div className="flex justify-end gap-2">
                    <Button kind="ghost" size="sm" onClick={() => setAsk(false)}>Cancel</Button>
                    <Button kind="primary" size="sm" disabled={!chips.length && !note.trim()} onClick={send}>Make a new take</Button>
                  </div>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>
    </motion.li>
  );
}

function Wave({ src }: { src: string }) {
  const box = useRef<HTMLDivElement>(null);
  const ws = useRef<WaveSurfer | null>(null);
  const [playing, setPlaying] = useState(false);
  const [state, setState] = useState<"loading" | "ok" | "bad">("loading");
  const [t, setT] = useState(0); const [d, setD] = useState(0);
  useEffect(() => {
    const css = getComputedStyle(document.documentElement);
    const w = WaveSurfer.create({
      container: box.current!, url: src, height: 40, barWidth: 2, barGap: 1.5, barRadius: 2, cursorWidth: 1,
      waveColor: css.getPropertyValue("--color-g6").trim() || "#4a4f58", progressColor: css.getPropertyValue("--color-marker").trim() || "#e31b23", cursorColor: css.getPropertyValue("--color-g10").trim() || "#fff",
    });
    w.on("ready", (dur) => { setState("ok"); setD(dur); });
    w.on("error", () => setState("bad"));
    w.on("play", () => setPlaying(true)); w.on("pause", () => setPlaying(false)); w.on("finish", () => setPlaying(false));
    w.on("timeupdate", setT);
    ws.current = w;
    return () => w.destroy();
  }, [src]);
  return (
    <div className="flex items-center gap-3">
      <button onClick={() => void ws.current?.playPause()} disabled={state !== "ok"} aria-label={playing ? "Pause" : "Play this take"}
        className="grid size-9 shrink-0 place-items-center rounded-full bg-g10 text-g0 transition-transform hover:scale-105 active:scale-95 disabled:opacity-40">
        {playing ? <Pause size={14} weight="fill" /> : <Play size={14} weight="fill" />}
      </button>
      <div className="relative h-10 min-w-0 flex-1">
        <div ref={box} className={cx("transition-opacity", state === "ok" ? "opacity-100" : "opacity-0")} />
        {state === "loading" && <div className="skeleton absolute inset-x-0 top-3 h-4 rounded-full" />}
        {state === "bad" && <div className="absolute inset-0 flex items-center gap-2 text-[12.5px] text-bad"><Waveform size={16} />This take didn't load. Make a new one.</div>}
      </div>
      <span className="edge w-[86px] text-right text-[12px]">{mmss(t)} / {mmss(d)}</span>
    </div>
  );
}

// ------------------------------------------------------------------ right side

function AnchorBox({ p, locked }: { p: Project; locked: boolean }) {
  const a = anchorOf(p.anchorId);
  const [open, setOpen] = useState(false);
  if (!a) return null;
  const vo = p.format === "vo_only";
  return (
    <section aria-labelledby="anc-h">
      <h2 id="anc-h" className="mb-2.5 text-[13px] font-semibold text-g8">{vo ? "Voice" : "Anchor"}</h2>
      <div className="flex items-center gap-3 rounded-md border border-g4 bg-g1 p-3">
        {vo ? <img src={a.face} alt="" className="size-14 rounded-sm object-cover" /> : <img src={a.frame} alt="" className="h-14 w-24 rounded-sm object-cover" />}
        <div className="min-w-0 flex-1"><div className="font-semibold">{a.name}</div><VoiceSample a={a} /></div>
        {!locked && <Button kind="ghost" size="sm" onClick={() => setOpen(true)}>Change</Button>}
      </div>
      <AnchorPicker open={open} onOpenChange={setOpen} p={p} />
    </section>
  );
}

function RenderCard({ p, ready, locked, voicing, short, estMin, ahead, total, onRender }: { p: Project; ready: boolean; locked: boolean; voicing: number; short: number; estMin: number; ahead: number; total: number; onRender: () => void }) {
  const nav = useNavigate();
  const startAt = new Date(Date.now() + ahead * estMin * 60_000);
  const doneAt = new Date(startAt.getTime() + estMin * 60_000);
  const vo = p.format === "vo_only";
  return (
    <div className="rounded-md border border-g4 bg-g1 p-5">
      <div className="flex items-baseline justify-between"><h2 className="text-[15px] font-semibold">Render</h2><span className="edge text-[13px]">{mmss(total)}</span></div>
      {locked ? (
        <div className="mt-4 space-y-3 text-[13.5px]">
          <p className="flex items-center gap-2 text-g9"><Lock size={15} />{p.stage === "done" ? "Rendered. Post it, make it again or discard it on the Render page." : p.render?.waitNote ? `Queued for tonight's render. ${p.render.waitNote}.` : `On the render machine, ${p.render?.percent ?? 0}% done.`}</p>
          <Button kind="secondary" className="w-full" onClick={() => nav(p.stage === "done" ? `/story/${p.id}/render` : "/desk")}>{p.stage === "done" ? "Open the Render page" : "Back to the desk"}</Button>
        </div>
      ) : (
        <>
          {(p.render?.state === "held" || p.render?.state === "failed") && <p className="mt-3 flex gap-2 rounded-sm border border-warn/40 bg-warn/10 p-2.5 text-[12.5px]"><Warning size={15} className="mt-px shrink-0 text-warn" />{p.render.heldReason ?? "The last render stopped. Send it again."}</p>}
          <dl className="mt-4 space-y-2 text-[13px]">
            {vo ? <div className="flex justify-between gap-3"><dt className="flex items-center gap-1.5 text-g8"><FilmSlate size={14} />Format</dt><dd>9:16, no anchor render</dd></div> : <>
              <div className="flex justify-between gap-3"><dt className="flex items-center gap-1.5 text-g8"><FilmSlate size={14} />Takes about</dt><dd className="edge">{estMin} min</dd></div>
              <div className="flex justify-between gap-3"><dt className="flex items-center gap-1.5 text-g8"><Queue size={14} />In the queue</dt><dd>{ahead ? `${ahead} ahead` : <span className="text-ok">Free now</span>}</dd></div>
              <div className="flex justify-between gap-3"><dt className="flex items-center gap-1.5 text-g8"><Robot size={14} />Ready at</dt><dd className="edge">{istTime(doneAt.toISOString())} IST</dd></div>
            </>}
          </dl>
          <ul className="mt-4 space-y-1.5 border-t border-g4 pt-4 text-[12.5px]">
            <Check ok={!voicing}>{voicing ? `${voicing} ${voicing === 1 ? "voice is" : "voices are"} still being made` : "Every voice is made"}</Check>
            {vo ? <>
              <Check ok={p.edit?.state === "ready"}>{p.edit?.state === "ready" ? "The edit is checked" : "The edit is still being checked"}</Check>
              <Check ok={!short}>{short ? `${short} ${short === 1 ? "beat is" : "beats are"} short; ${short === 1 ? "its" : "their"} pictures run out early` : "Every beat is filled"}</Check>
            </> : <>
              <Check ok={!short}>{short ? `${short} ${short === 1 ? "part needs" : "parts need"} pictures` : "Every part has its pictures"}</Check>
              <Check ok>Lip check runs by itself during the render</Check>
            </>}
          </ul>
          {short > 0 && !vo ? (
            <Button kind="secondary" className="mt-5 w-full" onClick={() => nav(`/story/${p.id}/visuals`)}>Fill the pictures <ArrowRight size={14} /></Button>
          ) : (
            <Tip label={ready ? "Send to the render machine" : voicing ? "Waiting for the voices" : "Waiting for the edit"}>
              <span className="mt-5 block"><Button kind="primary" size="lg" className="w-full" disabled={!ready} onClick={onRender}>{ready ? "Render this video" : <><Lock size={14} />{voicing ? "Waiting for the voices" : "Waiting for the edit"}</>}</Button></span>
            </Tip>
          )}
        </>
      )}
    </div>
  );
}
function Check({ ok, children }: { ok: boolean; children: React.ReactNode }) {
  return <li className={cx("flex items-start gap-2", ok ? "text-g9" : "text-warn")}>{ok ? <CheckCircle size={14} weight="fill" className="mt-px shrink-0 text-ok" /> : <span className="mt-[5px] size-1.5 shrink-0 rounded-full bg-warn" />}{children}</li>;
}


// ------------------------------------------------------------------ VO only: the final video and posting it

export function FinalPlayer({ src, poster, time, onTime, width = 300 }: { src: string; poster?: string; time?: { t: number; nonce: number }; onTime?: (t: number) => void; width?: number }) {
  const v = useRef<HTMLVideoElement>(null);
  useEffect(() => { if (time && v.current) v.current.currentTime = time.t; }, [time?.nonce]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="w-full rounded-[26px] bg-g2 p-[7px] ring-1 ring-g5 shadow-[0_30px_80px_-30px_rgba(0,0,0,0.9)]" style={{ width: `min(${width + 14}px, 100%)` }}>
      <video ref={v} src={src} poster={poster} controls playsInline preload="metadata" onTimeUpdate={(e) => onTime?.(e.currentTarget.currentTime)}
        className="block aspect-[9/16] w-full rounded-[19px] bg-black object-contain" aria-label="The final 9:16 video" />
    </div>
  );
}

const ACCOUNTS: { id: string; name: string }[] = [{ id: "instagram", name: "Instagram" }, { id: "facebook", name: "Facebook" }, { id: "x", name: "X" }];

export function PostCard({ p, voicing, short, total }: { p: Project; voicing: number; short: number; total: number }) {
  const [open, setOpen] = useState(false);
  const f = p.final;
  const yt = p.posts?.youtube;
  const vo = p.format === "vo_only";
  const current = f?.state === "ready" && !f.stale;
  const queued = p.stage === "render" && p.render?.state === "queued";
  const making = !current && (f?.state === "building" || p.render?.state === "rendering");
  const pct = Math.round((f?.progress ?? 0) * 100);
  const canPost = current && !["posting", "posted", "uploading"].includes(yt?.state ?? "");
  const open_ = yt?.url && <> <a href={yt.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-0.5 underline underline-offset-2">Open <ArrowSquareOut size={11} /></a></>;
  const hhmm = (iso: string) => new Date(iso).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Kolkata" });
  return (
    <div className="rounded-md border border-g4 bg-g1 p-5">
      <div className="flex items-baseline justify-between"><h2 className="text-[15px] font-semibold">Post</h2><span className="edge text-[13px]">{mmss(current && f.seconds ? f.seconds : total)}</span></div>

      <div className="mt-4 text-[13px]" aria-live="polite">
        {current ? (
          <p className="flex items-center gap-2 text-g9"><FilmSlate size={15} className="text-ok" />Final video ready{vo ? ` · ${f.cuts ?? ""} shots, 9:16` : ""}</p>
        ) : making ? (
          <div>
            <p className="flex items-center justify-between gap-3 text-g9"><span>Making the final video</span><span className="edge">{pct}%</span></p>
            <div className="mt-2 h-1 overflow-hidden rounded-full bg-g3"><motion.div className="h-full bg-vo" animate={{ width: `${Math.max(3, pct)}%` }} transition={{ duration: 0.4 }} /></div>
            {f?.note && <p className="mt-1.5 text-[12px] text-g8">{f.note}</p>}
          </div>
        ) : f?.state === "failed" ? (
          <div className="flex gap-2 rounded-sm border border-warn/40 bg-warn/10 p-2.5 text-[12.5px]"><Warning size={15} className="mt-px shrink-0 text-warn" />
            <div className="min-w-0 flex-1">{f.note || "The final video could not be made."}
              <Button kind="secondary" size="sm" className="mt-2" icon={<ArrowCounterClockwise size={13} />} onClick={() => remakeFinal(p.id)}>Make it again</Button></div></div>
        ) : queued ? (
          <p className="text-g9">Queued for tonight's render.{p.render?.waitNote ? ` ${p.render.waitNote}.` : " Starting soon."}</p>
        ) : (
          <p className="text-g8">The final video is made in the night render (00:00–07:00 IST) after you press Continue on the footage page.</p>
        )}
        {current && !!f.low && (
          <div className="mt-3 flex gap-2 rounded-sm border border-warn/40 bg-warn/10 p-2.5 text-[12.5px]"><Warning size={15} className="mt-px shrink-0 text-warn" />
            <div className="min-w-0 flex-1">{f.low} of {f.cuts} shots are from a lower-quality copy: YouTube refused the full-quality download.
              <Button kind="secondary" size="sm" className="mt-2" icon={<ArrowCounterClockwise size={13} />} onClick={() => remakeFinal(p.id)}>Try full quality again</Button></div></div>
        )}
      </div>

      {vo && <ul className="mt-4 space-y-1.5 border-t border-g4 pt-4 text-[12.5px]">
        <Check ok={!voicing}>{voicing ? `${voicing} ${voicing === 1 ? "voice is" : "voices are"} still being made` : "Every voice is made"}</Check>
        <Check ok={p.edit?.state === "ready"}>{p.edit?.state === "ready" ? "The edit is checked" : "The edit is still being checked"}</Check>
        <Check ok={!short}>{short ? `${short} ${short === 1 ? "beat is" : "beats are"} short; ${short === 1 ? "its" : "their"} pictures run out early` : "Every beat is filled"}</Check>
      </ul>}

      <h3 className="mt-5 mb-2 text-[12.5px] font-semibold text-g8">Accounts</h3>
      <ul className="divide-y divide-g4 rounded-sm border border-g4 text-[13px]">
        <li className="flex items-start gap-2.5 p-2.5">
          <YoutubeLogo size={18} weight="fill" className="mt-px shrink-0 text-[#ff0033]" />
          <div className="min-w-0 flex-1">
            <div className="flex items-baseline justify-between gap-2"><span className="font-medium">YouTube</span><span className="text-[12px] text-g8">DNL channel</span></div>
            {yt?.state === "posted" ? <p className="mt-0.5 text-[12px] text-ok">Public{yt.auto ? ", posted by itself an hour after the render" : ""}.{open_}</p>
              : yt?.state === "awaiting" ? <p className="mt-0.5 text-[12px] text-g9">Unlisted, awaiting approval.{yt.autoAt ? ` Goes public by itself at ${hhmm(yt.autoAt)} IST.` : " Post makes it public."}{open_}</p>
              : yt?.state === "uploading" ? <p className="mt-0.5 text-[12px] text-g9">Uploading, unlisted…</p>
              : yt?.state === "posting" ? <p className="mt-0.5 text-[12px] text-g9">Making it public…</p>
              : yt?.state === "failed" ? <p className="mt-0.5 text-[12px] text-warn">{yt.error || "Posting stopped."}</p>
              : <p className="mt-0.5 text-[12px] text-g8">Connected</p>}
          </div>
        </li>
        {ACCOUNTS.map((a) => <li key={a.id} className="flex items-center justify-between gap-2 p-2.5 text-g8"><span>{a.name}</span><span className="text-[12px]">Not connected yet</span></li>)}
      </ul>

      <Tip label={canPost ? "Choose where it goes, then confirm" : yt?.state === "posted" ? "Already posted" : "Waiting for the final video"}>
        <span className="mt-5 block"><Button kind="primary" size="lg" className="w-full" disabled={!canPost} onClick={() => setOpen(true)}>
          {yt?.state === "posted" ? <><CheckCircle size={15} weight="fill" />Posted</> : canPost ? <><PaperPlaneTilt size={15} weight="fill" />{yt?.state === "failed" ? "Post again" : "Post"}</> : <><Lock size={14} />Waiting for the final video</>}
        </Button></span>
      </Tip>
      {open && <PostDialog p={p} onClose={() => setOpen(false)} />}
    </div>
  );
}

function PostDialog({ p, onClose }: { p: Project; onClose: () => void }) {
  const [text, setText] = useState<{ title: string; description: string } | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    const yt = p.posts?.youtube;
    if (yt?.title) { setText({ title: yt.title, description: yt.description }); return; }
    postDefaults(p.id).then((d) => setText({ title: d.title, description: d.description })).catch((e) => setErr(String(e?.message ?? e)));
  }, [p.id]); // eslint-disable-line react-hooks/exhaustive-deps
  function go() {
    if (!text?.title.trim()) return;
    postVideo(p.id, "youtube", text.title.trim(), text.description.trim());
    toast("Posting to YouTube. It is public in a minute or two.", "ok");
    onClose();
  }
  return (
    <Dialog open onOpenChange={(v) => !v && onClose()} title="Post this video?">
      <div className="space-y-4 p-5 text-[14px]">
        <div className="flex items-start gap-2.5 rounded-sm border border-g4 bg-g2 p-3 text-[13px]">
          <YoutubeLogo size={18} weight="fill" className="mt-px shrink-0 text-[#ff0033]" />
          <p>YouTube, DNL channel. It becomes <b>public</b> on the channel and in the DNL site's Video Bulletin, as when an editor approves it in the CMS.</p>
        </div>
        {err ? <p className="text-[13px] text-bad">{err}</p> : !text ? <div className="skeleton h-40 rounded-sm" /> : <>
          <label className="block"><span className="mb-1 flex justify-between text-[12.5px] text-g8"><span>Title</span><span className="edge">{text.title.length}/100</span></span>
            <Input value={text.title} maxLength={100} onChange={(e) => setText({ ...text, title: e.target.value })} /></label>
          <label className="block"><span className="mb-1 block text-[12.5px] text-g8">Description</span>
            <Textarea value={text.description} rows={8} onChange={(e) => setText({ ...text, description: e.target.value })} /></label>
        </>}
        <div className="flex justify-end gap-2">
          <Button kind="ghost" onClick={onClose}>Not yet</Button>
          <Button kind="primary" disabled={!text?.title.trim()} onClick={go}><YoutubeLogo size={15} weight="fill" />Post to YouTube</Button>
        </div>
      </div>
    </Dialog>
  );
}

// ------------------------------------------------------------------ VO only: the 9:16 preview and a compact timeline of beats and cuts

function VoPreview({ p, cut, total, time, now, onTime, sel, onSeek, onSelect }: {
  p: Project; cut: VoSeg[]; total: number; time?: { t: number; nonce: number }; now: number; onTime: (t: number) => void;
  sel: string | null; onSeek: (t: number) => void; onSelect: (sid: string, t: number) => void;
}) {
  const seg = cut.find((s) => now >= s.start && now < s.start + s.dur) ?? cut[0];
  const k = seg ? seg.cuts.findIndex((c) => now >= c.start && now < c.start + c.dur) : -1;
  const c = seg && k >= 0 ? beatOf(p, seg.sid)?.cuts[k] : undefined;
  const voiced = cut.some((s) => s.audio);
  const f = p.final;
  const final = f?.state === "ready" && !f.stale && f.video ? f : undefined;
  return (
    <div>
      <div className="flex flex-col items-center gap-6 sm:flex-row sm:items-start sm:gap-8">
        <div className="flex w-full flex-col items-center gap-2 sm:w-auto">
          {final ? <FinalPlayer src={final.video!} poster={final.poster} time={time} onTime={onTime} /> : <PhonePlayer p={p} time={time} onTime={onTime} />}
          <span className={cx("text-[12px]", final ? "text-ok" : "text-g8")}>{final ? "Final video" : "Preview"}</span>
        </div>
        <div className="w-full min-w-0 flex-1 sm:pt-2">
          {seg && (
            <div aria-live="polite">
              <div className="flex items-center gap-2"><Microphone size={14} weight="fill" className="text-vo" /><span className="narrow text-[13.5px] font-semibold">Beat {seg.n}</span>
                <span className="edge text-[11.5px]">{mmss(seg.start, true)}–{mmss(seg.start + seg.dur, true)}</span></div>
              <p className="mt-2 max-w-[60ch] text-[15px] leading-relaxed text-g10">{seg.text}</p>
              <p className="mt-3 text-[12.5px] text-g8">
                {c ? <>Cut {k + 1} of {seg.cuts.length} · <span className="text-g9">{c.shows}</span> · <span className="edge">{c.secs.toFixed(1)} s</span></>
                  : seg.gap > 0.25 ? <span className="text-warn">No picture: this beat is {seg.gap.toFixed(1)} s short</span> : null}
              </p>
            </div>
          )}
          <ul className="mt-6 space-y-1.5 border-t border-g4 pt-4 text-[12.5px] text-g8">
            {final ? <>
              <li>This is the finished video: each shot framed for 9:16, text shots kept whole, with the voice.</li>
              {p.stage !== "done" && <li>Change a take or a cut, then press Continue again: tonight's render remakes it.</li>}
            </> : <>
              <li>{f?.state === "building" || (f?.state === "ready" && f.stale) || (!f && p.edit?.state === "ready")
                ? "The final video is being made. Meanwhile each clip is centre-cropped here."
                : "Each clip is centre-cropped here. The final video frames each shot properly."}</li>
              <li>{voiced ? "The voice plays as it is now; change a take below." : "No voice yet: the preview plays silent, timed to the beats."}</li>
            </>}
          </ul>
        </div>
      </div>
      <VoTimeline cut={cut} total={total} now={now} sel={sel} onSeek={onSeek} onSelect={onSelect} />
    </div>
  );
}

function VoTimeline({ cut, total, now, sel, onSeek, onSelect }: { cut: VoSeg[]; total: number; now: number; sel: string | null; onSeek: (t: number) => void; onSelect: (sid: string, t: number) => void }) {
  const track = useRef<HTMLDivElement>(null);
  const pct = (t: number) => `${(t / Math.max(total, 0.01)) * 100}%`;
  const ticks = Array.from({ length: Math.floor(total / 5) + 1 }, (_, i) => i * 5).filter((t) => t < total - 2);   // the last label would run off the end
  const at = (x: number) => { const r = track.current!.getBoundingClientRect(); return Math.max(0, Math.min(1, (x - r.left) / r.width)) * total; };
  const rows = "grid grid-rows-[16px_28px_44px] gap-y-1.5";
  return (
    <div className="mt-6 flex select-none rounded-md border border-g4 bg-g1 py-3 pr-3">
      <div className={cx(rows, "w-[60px] shrink-0 pr-3 text-right text-[11.5px] text-g8")} aria-hidden><span /><span className="self-center">Beats</span><span className="self-center">Cuts</span></div>
      <div ref={track} className={cx(rows, "relative min-w-0 flex-1")}>
        <div className="relative cursor-pointer" onPointerDown={(e) => onSeek(at(e.clientX))}>
          {ticks.map((t) => <span key={t} className="absolute top-0 font-mono text-[11px] text-edge" style={{ left: pct(t) }}><span className="absolute -bottom-1 left-0 h-1.5 w-px bg-g5" /><span className="pl-1">{mmss(t)}</span></span>)}
        </div>
        <div className="relative">
          {cut.map((s) => (
            <button key={s.sid} onClick={() => onSelect(s.sid, s.start)} aria-label={`Beat ${s.n}, ${mmss(s.dur)}`}
              className={cx("absolute inset-y-0 flex items-center overflow-hidden rounded-[2px] border border-vo/40 bg-vo/16 px-1.5 text-[11px] font-semibold text-vo transition-[filter,border-color]",
                sel === s.sid ? "border-g10 brightness-125" : "hover:brightness-125")}
              style={{ left: pct(s.start), width: `calc(${pct(s.dur)} - 2px)` }}>
              <span className="truncate">B{s.n}</span>
            </button>
          ))}
        </div>
        <div className="relative">
          {cut.flatMap((s) => [
            ...s.cuts.map((c, i) => (
              <Tip key={`${s.sid}-${i}`} label={<span><span className="edge">{c.code}</span> {c.label}</span>}>
                <button onClick={() => onSeek(c.start)} className="absolute inset-y-0 overflow-hidden rounded-[2px] bg-g3 ring-1 ring-g5 hover:ring-g8" aria-label={`Cut ${c.code}: ${c.label}`}
                  style={{ left: pct(c.start), width: `calc(${pct(Math.min(c.dur, s.start + s.dur - c.start))} - 2px)` }}>
                  <img src={c.poster ?? c.src} alt="" className="size-full object-cover opacity-85" />
                </button>
              </Tip>
            )),
            ...(s.gap > 0.25 ? [<span key={`${s.sid}-gap`} title={`${s.gap.toFixed(1)} s short`} className="absolute inset-y-0 rounded-[2px] border border-dashed border-warn/60 bg-[repeating-linear-gradient(135deg,transparent_0_5px,color-mix(in_srgb,var(--color-warn)_12%,transparent)_5px_10px)]"
              style={{ left: pct(s.start + s.dur - s.gap), width: `calc(${pct(s.gap)} - 2px)` }} />] : []),
          ])}
        </div>
        <span className="pointer-events-none absolute top-0 bottom-0 w-px bg-marker" style={{ left: pct(now) }}><span className="absolute -top-0.5 -left-[4px] size-[9px] rotate-45 bg-marker" /></span>
      </div>
    </div>
  );
}
