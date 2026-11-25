import { useMemo, useRef, useState, type DragEvent } from "react";
import { useNavigate, Link } from "react-router";
import { AnimatePresence, motion } from "motion/react";
import { FileText, LinkSimple, UploadSimple, X, ArrowRight, Eye, Play, FilmStrip, Warning, Waveform, ImagesSquare, PencilSimpleLine, Clock, CaretUp, Trash, YoutubeLogo, PaperPlaneTilt } from "@phosphor-icons/react";
import {
  useStore, createProject, parseLength, hidePick, showHiddenPicks, sections, fillOf, voiceProgress, anchorOf, cancelRender, moveUp, totalSeconds, mediaOf, archiveProject, awaitingPost, postAll,
} from "@/data/store";
import type { Format, Pick, Project } from "@/data/types";
import { Button, Dialog, Ring, Segmented, Tag, Tip, cx, istTime, mmss, istDate, IconButton, useFormatOptions } from "@/components/ui";
import { PhonePlayer, RoughCutPlayer, VideoPlayer } from "@/components/player";

const TYPE: Record<string, string> = { war_conflict: "War", death_disaster: "Disaster", democracy: "Democracy", turmoil_unrest: "Unrest" };
const MIN_PER_OUTPUT_MIN = 23;

export default function Desk() {
  const user = useStore((s) => s.user);
  const defaults = useStore((s) => s.defaults);
  const [format, setFormat] = useState<Format>(defaults.format);   // the composer's format and length also start a pick
  const [len, setLen] = useState("1:00");
  const today = new Date().toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long", timeZone: "Asia/Kolkata" });
  return (
    <div className="mx-auto max-w-[1680px] px-5 pt-8 pb-20">
      <div className="mb-7 flex items-end justify-between gap-6">
        <div>
          <h1 className="text-[26px] font-semibold tracking-[-0.02em]">Good {greeting()}, {user?.name.split(" ")[0]}</h1>
          <p className="mt-1 text-g8">{today}</p>
        </div>
      </div>
      <div className="grid grid-cols-1 gap-x-8 gap-y-10 xl:grid-cols-[minmax(0,1fr)_380px]">
        <div className="min-w-0 space-y-10">
          <Composer format={format} setFormat={setFormat} len={len} setLen={setLen} />
          <Picks format={format} seconds={parseLength(len)} />
          <Stories />
        </div>
        <aside className="space-y-8 xl:sticky xl:top-[76px] xl:self-start">
          <ReadyToPost />
          <Rendering />
          <NeedsYou />
          <JustFinished />
        </aside>
      </div>
    </div>
  );
}
const greeting = () => { const h = +new Date().toLocaleString("en-GB", { hour: "numeric", hour12: false, timeZone: "Asia/Kolkata" }); return h < 12 ? "morning" : h < 17 ? "afternoon" : "evening"; };

// ------------------------------------------------------------------ new video

function Composer({ format, setFormat, len, setLen }: { format: Format; setFormat: (f: Format) => void; len: string; setLen: (v: string) => void }) {
  const nav = useNavigate();
  const formatOptions = useFormatOptions();
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [over, setOver] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [err, setErr] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const seconds = parseLength(len);
  const isLink = /^https?:\/\/\S+$/.test(text.trim());

  function pickFile(f: File | undefined) {
    if (!f) return;
    if (!/\.(pdf|docx|txt|md)$/i.test(f.name)) { setErr("Use a PDF, Word (.docx) or text file. Old .doc files: save as .docx first."); return; }
    setErr(""); setFile(f);
    if (/\.(txt|md)$/i.test(f.name)) f.text().then((t) => setText((x) => x || t.slice(0, 20000)));
  }
  function drop(e: DragEvent) { e.preventDefault(); setOver(false); pickFile(e.dataTransfer.files[0]); }
  async function go(force = false) {
    if (!text.trim() && !file) { setErr("Paste a link or the story, or drop a file."); return; }
    if (!seconds) { setErr("Length: try 45s, 1:30 or 3 min."); return; }
    if (seconds > 300 && !force) { setConfirm(true); return; }
    const id = await createProject(file ? { kind: "file", name: file.name, text, seconds, format, file } : isLink ? { kind: "link", url: text.trim(), text: "", seconds, format } : { kind: "text", text, seconds, format });
    if (id) nav(`/story/${id}/script`);
  }

  return (
    <section aria-labelledby="new-video">
      <h2 id="new-video" className="sr-only">New video</h2>
      <div onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)} onDrop={drop}
        className={cx("relative overflow-hidden rounded-md border bg-g1 transition-[border-color,box-shadow] duration-200",
          over ? "border-marker bg-marker/5" : "border-g5 focus-within:border-g7")}>
        <div className="p-5 pb-4">
          <label htmlFor="story-in" className="mb-2 block text-[17px] font-semibold">Start a new video</label>
          <AnimatePresence>
            {file && (
              <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }} exit={{ opacity: 0, height: 0 }}>
                <div className="mb-3 inline-flex items-center gap-2 rounded-sm border border-g5 bg-g3 py-1.5 pr-1.5 pl-2.5 text-[13px]">
                  <FileText size={16} className="text-edge" /> <span className="max-w-[40ch] truncate">{file.name}</span>
                  <span className="edge text-[11.5px]">{Math.max(1, Math.round(file.size / 1024))} KB</span>
                  <IconButton label="Remove file" size="sm" onClick={() => setFile(null)}><X size={13} /></IconButton>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
          <textarea id="story-in" value={text} onChange={(e) => { setText(e.target.value); setErr(""); }} rows={4}
            placeholder="Paste a link, paste or write the story, or drop a PDF or Word file here."
            className="w-full resize-none bg-transparent text-[15px] leading-relaxed text-g10 outline-none focus-visible:outline-none" />
          <AnimatePresence>
            {isLink && (
              <motion.div initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="mt-1 flex items-center gap-2 text-[13px] text-g8">
                <LinkSimple size={14} className="text-vo" /> Link from <span className="text-g10">{hostOf(text)}</span>. The article is read when you start.
              </motion.div>
            )}
          </AnimatePresence>
        </div>
        <div className="flex flex-wrap items-center gap-x-5 gap-y-3 border-t border-g4 bg-g2/60 px-5 py-3">
          <Button kind="ghost" size="sm" icon={<UploadSimple size={15} />} onClick={() => input.current?.click()}>Upload file</Button>
          <input ref={input} type="file" accept=".pdf,.docx,.txt,.md" className="hidden" onChange={(e) => pickFile(e.target.files?.[0])} />
          <div className="flex items-center gap-2">
            <label htmlFor="len" className="text-[13px] text-g8">Length</label>
            <input id="len" value={len} onChange={(e) => { setLen(e.target.value); setErr(""); }} aria-invalid={!seconds}
              className="h-8 w-[72px] rounded-sm border border-g5 bg-g1 px-2 text-center font-mono text-[13px] text-edge outline-none focus:border-g8 aria-invalid:border-bad" />
          </div>
          <Segmented size="sm" label="Format" value={format} set={setFormat} options={formatOptions} />
          <span className="edge text-[12px] text-g8">
            {!seconds ? <span className="text-bad">Try 45s, 1:30 or 3 min</span>
              : format === "vo_only" ? <>~{Math.round(seconds * 2.5)} words · no anchor render</>
              : <>~{Math.round(seconds * 2.5)} words · renders in ~{Math.max(5, Math.round((seconds / 60) * MIN_PER_OUTPUT_MIN))} min</>}
          </span>
          <div className="ml-auto flex items-center gap-3">
            {err && <span role="alert" className="text-[13px] text-bad">{err}</span>}
            <Button kind="primary" onClick={() => go()} icon={null}>Write the script <ArrowRight size={15} weight="bold" /></Button>
          </div>
        </div>
      </div>
      <Dialog open={confirm} onOpenChange={setConfirm} title="A long video">
        <div className="space-y-3 p-5 text-[14px] text-g9">
          <p>{mmss(seconds ?? 0)} is about {Math.round(((seconds ?? 0) / 60) * MIN_PER_OUTPUT_MIN / 60 * 10) / 10} hours on the render machine, and other stories wait behind it.</p>
          <div className="flex justify-end gap-2 pt-2">
            <Button kind="ghost" onClick={() => setConfirm(false)}>Change length</Button>
            <Button kind="primary" onClick={() => { setConfirm(false); go(true); }}>Keep {mmss(seconds ?? 0)}</Button>
          </div>
        </div>
      </Dialog>
    </section>
  );
}
const hostOf = (u: string) => { try { return new URL(u.trim()).hostname.replace(/^www\./, ""); } catch { return u; } };

// ------------------------------------------------------------------ picks

function Picks({ format, seconds }: { format: Format; seconds: number | null }) {
  const ws = useStore((s) => s.workspace);
  const picks = useStore((s) => s.picks);
  const hidden = useStore((s) => s.hiddenPicks);
  const visible = picks.filter((p) => !hidden.includes(p.id));
  if (ws?.kind !== "dnl") return null;
  return (
    <section aria-labelledby="picks-h">
      <div className="mb-3 flex items-baseline justify-between">
        <h2 id="picks-h" className="text-[17px] font-semibold">Today's picks <span className="ml-1.5 edge text-[13px]">{visible.length}</span></h2>
        <div className="flex items-center gap-4 text-[12.5px] text-g8">
          <span>DNL selection · hard news</span>
          {hidden.length > 0 && <button onClick={showHiddenPicks} className="flex items-center gap-1 hover:text-g10"><Eye size={14} />Bring back {hidden.length} removed</button>}
        </div>
      </div>
      {visible.length === 0 ? (
        <div className="rounded-md border border-dashed border-g5 px-5 py-8 text-center text-[13.5px] text-g8">{picks.length ? "Every pick is in use or removed. New picks arrive with the next selection." : "Today's picks are still being chosen. They appear here when ready."}</div>
      ) : (
        <div className="grid gap-3 md:grid-cols-2 2xl:grid-cols-3">
          <AnimatePresence initial={false}>{visible.map((p, i) => <PickCard key={p.id} p={p} i={i} format={format} seconds={seconds} />)}</AnimatePresence>
        </div>
      )}
    </section>
  );
}

function PickCard({ p, i, format, seconds }: { p: Pick; i: number; format: Format; seconds: number | null }) {
  const nav = useNavigate();
  const [busy, setBusy] = useState(false);   // one story per click, however fast the clicks come
  const formats = useStore((s) => s.formats);
  async function use(fmt: Format = format) {
    if (busy || !seconds) return;
    setBusy(true);
    const id = await createProject({ kind: "pick", pickId: p.id, text: "", seconds, format: fmt });
    setBusy(false);
    if (id) nav(`/story/${id}/script`);
  }
  return (
    <motion.article layout initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0, transition: { delay: i * 0.04 } }} exit={{ opacity: 0, scale: 0.97, transition: { duration: 0.18 } }}
      className="group flex min-w-0 flex-col rounded-md border border-g4 bg-g1 p-4 transition-colors hover:border-g6">
      <h3 className="text-[15px] leading-snug font-semibold text-g10">{p.headline}</h3>
      <p className="mt-1.5 line-clamp-3 text-[13px] text-g8">{p.deck}</p>
      <div className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px] text-g8">
        <Tag tone="marker">{TYPE[p.type] ?? "News"}</Tag>
        {p.place && <span className="font-mono">{p.place}</span>}
        <span className="text-g6">·</span><span className="edge">{istDate(p.publishedAt)}, {istTime(p.publishedAt)} IST</span>
        <span className="text-g6">·</span><span className="edge">{p.source}</span>
      </div>
      <div className="mt-auto flex items-center gap-2 pt-4">
        <Button kind="secondary" size="sm" disabled={busy || !seconds} onClick={() => use()}>{busy ? "Starting…" : "Use this story"}</Button>
        {format !== "vo_only" && formats.includes("vo_only") && <Button kind="secondary" size="sm" disabled={busy || !seconds} onClick={() => use("vo_only")}>Make 9:16</Button>}
        <Button kind="quiet" size="sm" icon={<X size={14} />} onClick={() => hidePick(p.id)}>Remove</Button>
      </div>
    </motion.article>
  );
}

// ------------------------------------------------------------------ stories in progress

function statusOf(p: Project, job?: { kind: string }) {
  if (job?.kind === "write") return { tone: "neutral" as const, text: "Writing the script", step: "script" };
  if (p.stage === "script") return { tone: "neutral" as const, text: "Script to check", step: "script" };
  if (p.stage === "visuals") {
    const l = sections(p); const full = l.filter((s) => fillOf(p, s).full).length;
    return { tone: full === l.length ? ("ok" as const) : ("warn" as const), text: `Pictures · ${full} of ${l.length} filled`, step: "visuals" };
  }
  if (p.stage === "review") return { tone: "vo" as const, text: voiceProgress(p)?.busy ? "Voice in progress" : "Ready to review", step: "review" };
  return { tone: "neutral" as const, text: p.stage, step: "review" };
}

function Stories() {
  const projects = useStore((s) => s.projects);
  const order = useStore((s) => s.order);
  const jobs = useStore((s) => s.jobs);
  const list = order.map((id) => projects[id]).filter((p) => p && (p.stage === "script" || p.stage === "visuals" || p.stage === "review"));
  return (
    <section aria-labelledby="stories-h">
      <h2 id="stories-h" className="mb-3 text-[17px] font-semibold">In progress <span className="ml-1.5 edge text-[13px]">{list.length}</span></h2>
      {list.length === 0 ? (
        <div className="rounded-md border border-dashed border-g5 px-5 py-8 text-center text-[13.5px] text-g8">Nothing in progress. Start a video above or use one of today's picks.</div>
      ) : (
        <ul className="divide-y divide-g4 overflow-hidden rounded-md border border-g4 bg-g1">
          <AnimatePresence initial={false}>
            {list.map((p) => <StoryRow key={p.id} p={p} job={jobs[p.id]} />)}
          </AnimatePresence>
        </ul>
      )}
    </section>
  );
}

function StoryRow({ p, job }: { p: Project; job?: { kind: string; progress: number } }) {
  const st = statusOf(p, job);
  const a = anchorOf(p.anchorId);
  const strip = useMemo(() => {
    const out: string[] = [];
    if (p.edit) return p.edit.beats.flatMap((b) => b.cuts.map((c) => c.poster)).slice(0, 4);   // VO only: the edit's cuts
    for (const s of sections(p)) for (const x of p.visuals[s.id]?.placed ?? []) {
      const m = mediaOf(p, s.id, x); const src = m?.poster ?? (m?.kind === "image" ? m.src : undefined); if (src) out.push(src);
    }
    return out.slice(0, 4);
  }, [p]);
  const [ask, setAsk] = useState(false);
  return (
    <motion.li layout initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="flex items-center hover:bg-g2">
      <Link to={`/story/${p.id}/${st.step}`} className="group grid min-w-0 flex-1 grid-cols-[minmax(0,1fr)_auto] items-center gap-6 py-3.5 pl-4 transition-colors md:grid-cols-[minmax(0,1fr)_220px_auto]">
        <div className="min-w-0">
          <div className="truncate text-[14.5px] font-semibold text-g10">{p.headline}</div>
          <div className="mt-1 flex items-center gap-2.5 text-[12.5px] text-g8">
            {a && <img src={a.face} alt="" className="size-4 rounded-full object-cover" />}
            <span>{a?.name}</span><span className="text-g6">·</span>
            <span className="edge">{mmss(totalSeconds(p))}</span><span className="text-g8">/ {mmss(p.targetSeconds)}</span><span className="text-g6">·</span>
            <span>edited {istTime(p.updatedAt)}</span>
          </div>
        </div>
        <div className="hidden h-[34px] items-center gap-[3px] overflow-hidden md:flex" aria-hidden>
          {strip.length ? strip.map((src, i) => <img key={i} src={src} alt="" className="h-full w-[52px] rounded-xs object-cover opacity-80 transition-opacity group-hover:opacity-100" />)
            : <span className="text-[12px] text-g8">No pictures yet</span>}
        </div>
        <div className="flex items-center gap-3">
          {job?.kind === "write" ? <span className="flex items-center gap-2 text-[12.5px] text-g9"><Ring pct={job.progress * 100} size={22} label={<span />} />{st.text}</span>
            : <Tag tone={st.tone}>{st.text}</Tag>}
          <ArrowRight size={16} className="text-g6 transition-transform group-hover:translate-x-0.5 group-hover:text-g10" />
        </div>
      </Link>
      <IconButton label={`Delete ${p.headline}`} size="sm" className="mx-2 shrink-0" onClick={() => setAsk(true)}><Trash size={15} /></IconButton>
      <Dialog open={ask} onOpenChange={setAsk} title="Delete this story?">
        <div className="space-y-4 p-5 text-[14px]">
          <p><span className="font-semibold">{p.headline}</span> leaves your desk, with its script, voices and pictures.</p>
          <div className="flex justify-end gap-2">
            <Button kind="ghost" onClick={() => setAsk(false)}>Keep it</Button>
            <Button kind="primary" onClick={() => { setAsk(false); archiveProject(p.id); }}>Delete</Button>
          </div>
        </div>
      </Dialog>
    </motion.li>
  );
}

// ------------------------------------------------------------------ right rail

function Rendering() {
  const queue = useStore((s) => s.queue);
  const projects = useStore((s) => s.projects);
  return (
    <section aria-labelledby="render-h" className="rounded-md border border-g4 bg-g1">
      <div className="flex items-center justify-between border-b border-g4 px-4 py-3">
        <h2 id="render-h" className="flex items-center gap-2 text-[14px] font-semibold">
          {queue.length > 0 && <span className="size-2 animate-pulse rounded-full bg-marker" />}Render queue
        </h2>
        <span className="edge text-[12px]">{queue.length ? `${queue.length} ${queue.length === 1 ? "job" : "jobs"}` : "idle"}</span>
      </div>
      {queue.length === 0 ? (
        <p className="px-4 py-6 text-[13px] text-g8">Nothing queued. Renders run 00:00–07:00 IST.</p>
      ) : (
        <ul className="divide-y divide-g4">
          <AnimatePresence initial={false}>
            {queue.map((j, i) => {
              const p = projects[j.projectId]; if (!p) return null;
              const a = anchorOf(p.anchorId);
              return (
                <motion.li key={j.projectId} layout initial={{ opacity: 0, x: 12 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, height: 0 }} className="flex items-center gap-3.5 px-4 py-3.5">
                  {i === 0 ? <Ring pct={j.percent} size={46} /> : <div className="grid size-[46px] shrink-0 place-items-center rounded-full border border-dashed border-g6 font-mono text-[12px] text-g8">#{i + 1}</div>}
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-[13.5px] font-semibold">{p.headline}</div>
                    <div className="mt-0.5 text-[12px] text-g8">
                      {a?.name.split(" ")[0]} · <span className="edge">{mmss(totalSeconds(p))}</span> ·{" "}
                      {j.waitNote ? j.waitNote : i === 0 ? (j.state === "assembling" ? "putting it together" : j.etaIso ? <>done ~<span className="edge">{istTime(j.etaIso)}</span> IST</> : "working out the time") : `waits for ${i} ${i === 1 ? "job" : "jobs"}`}
                    </div>
                  </div>
                  {i > 1 && <IconButton label="Move up" size="sm" onClick={() => moveUp(p.id)}><CaretUp size={14} /></IconButton>}
                  {j.state === "queued" && <Tip label="Take it out of the queue"><button onClick={() => cancelRender(p.id)} className="text-[12px] text-g8 hover:text-bad">Cancel</button></Tip>}
                </motion.li>
              );
            })}
          </AnimatePresence>
        </ul>
      )}
    </section>
  );
}

function ReadyToPost() {
  const projects = useStore((s) => s.projects);
  const order = useStore((s) => s.order);
  const [open, setOpen] = useState(false);
  const items = order.map((id) => projects[id]).filter((p) => p && awaitingPost(p));
  if (!items.length) return null;
  return (
    <section aria-labelledby="post-h" className="rounded-md border border-g4 bg-g1">
      <div className="flex items-center justify-between border-b border-g4 px-4 py-3">
        <h2 id="post-h" className="text-[14px] font-semibold">Ready to post <span className="ml-1 edge text-[12px]">{items.length}</span></h2>
        <Button kind="primary" size="sm" icon={<PaperPlaneTilt size={13} weight="fill" />} onClick={() => setOpen(true)}>Post all ({items.length})</Button>
      </div>
      <ul className="divide-y divide-g4">
        {items.map((p) => (
          <li key={p.id}><Link to={`/story/${p.id}/review`} className="flex items-center justify-between gap-3 px-4 py-2.5 text-[13px] hover:bg-g2">
            <span className="min-w-0 truncate">{p.headline}</span>
            <span className="shrink-0 text-[12px] text-g8">{p.format === "vo_only" ? "No anchor" : "Anchor"}{p.posts?.youtube?.state === "failed" ? " · post failed" : ""}</span>
          </Link></li>
        ))}
      </ul>
      <Dialog open={open} onOpenChange={setOpen} title={`Post ${items.length} ${items.length === 1 ? "video" : "videos"}?`}>
        <div className="space-y-4 p-5 text-[14px]">
          <div className="flex items-start gap-2.5 rounded-sm border border-g4 bg-g2 p-3 text-[13px]">
            <YoutubeLogo size={18} weight="fill" className="mt-px shrink-0 text-[#ff0033]" />
            <p>Each becomes <b>public</b> on the DNL YouTube channel with its title and description, as when an editor approves it in the CMS.</p>
          </div>
          <ol className="list-decimal space-y-1 pl-5 text-[13px]">{items.map((p) => <li key={p.id}>{p.headline}</li>)}</ol>
          <div className="flex justify-end gap-2">
            <Button kind="ghost" onClick={() => setOpen(false)}>Not yet</Button>
            <Button kind="primary" onClick={() => { setOpen(false); void postAll(items.map((p) => p.id)); }}><YoutubeLogo size={15} weight="fill" />Post all to YouTube</Button>
          </div>
        </div>
      </Dialog>
    </section>
  );
}

function NeedsYou() {
  const projects = useStore((s) => s.projects);
  const order = useStore((s) => s.order);
  const items = order.map((id) => projects[id]).filter(Boolean).flatMap((p) => {
    const out: { p: Project; icon: React.ReactNode; text: string; to: string }[] = [];
    const stopped = p.stage === "review" && (p.render?.state === "held" || p.render?.state === "failed");
    if (stopped) out.push({ p, icon: <Warning size={16} className="text-warn" />, text: p.render!.heldReason ?? "The render stopped. Send it again.", to: `/story/${p.id}/review` });
    else if (p.stage === "review" && !voiceProgress(p)?.busy) out.push({ p, icon: <Waveform size={16} className="text-vo" />, text: "Voice ready. Listen before rendering.", to: `/story/${p.id}/review` });
    if (p.stage === "visuals") {
      const short = sections(p).filter((s) => !fillOf(p, s).full);
      if (short.length) out.push({ p, icon: <ImagesSquare size={16} className="text-warn" />, text: `${short.length} ${short.length === 1 ? "part needs" : "parts need"} pictures`, to: `/story/${p.id}/visuals` });
    }
    if (p.stage === "script" && sections(p).length) out.push({ p, icon: <PencilSimpleLine size={16} className="text-g9" />, text: "Script written. Check and approve it.", to: `/story/${p.id}/script` });
    return out;
  });
  return (
    <section aria-labelledby="needs-h">
      <h2 id="needs-h" className="mb-3 text-[14px] font-semibold">Needs you <span className="ml-1 edge text-[12px]">{items.length}</span></h2>
      {items.length === 0 ? <p className="text-[13px] text-g8">Nothing is waiting on you.</p> : (
        <ul className="space-y-1.5">
          {items.map((it, i) => (
            <li key={i}>
              <Link to={it.to} className="flex items-start gap-3 rounded-sm border border-g4 bg-g1 px-3 py-2.5 transition-colors hover:border-g6 hover:bg-g2">
                <span className="mt-0.5">{it.icon}</span>
                <span className="min-w-0">
                  <span className="block text-[13px] text-g10">{it.text}</span>
                  <span className="block truncate text-[12px] text-g8">{it.p.headline}</span>
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function JustFinished() {
  const lib = useStore((s) => s.library);
  const projects = useStore((s) => s.projects);
  const [open, setOpen] = useState<string | null>(null);
  const items = lib.slice(0, 3);
  const it = lib.find((x) => x.id === open);
  return (
    <section aria-labelledby="fin-h">
      <div className="mb-3 flex items-baseline justify-between">
        <h2 id="fin-h" className="text-[14px] font-semibold">Just finished</h2>
        <Link to="/library" className="text-[12.5px] text-g8 hover:text-g10">Library</Link>
      </div>
      <ul className="space-y-2">
        {items.map((x) => (
          <li key={x.id}>
            <button onClick={() => setOpen(x.id)} className="group flex w-full items-center gap-3 rounded-sm text-left">
              <span className="relative block aspect-video w-[104px] shrink-0 overflow-hidden rounded-xs bg-g3">
                {x.poster && <img src={x.poster} alt="" className="size-full object-cover transition-transform duration-300 group-hover:scale-105" />}
                <span className="absolute inset-0 grid place-items-center bg-black/30 opacity-0 transition-opacity group-hover:opacity-100"><Play size={18} weight="fill" /></span>
                <span className="absolute right-1 bottom-1 rounded-xs bg-black/70 px-1 font-mono text-[11px] text-edge">{mmss(x.seconds)}</span>
              </span>
              <span className="min-w-0">
                <span className="line-clamp-2 text-[13px] leading-snug text-g10 group-hover:underline">{x.headline}</span>
                <span className="mt-0.5 flex items-center gap-1 text-[12px] text-g8"><Clock size={12} />{istDate(x.madeAt)}</span>
              </span>
            </button>
          </li>
        ))}
        {items.length === 0 && <li className="flex items-center gap-2 text-[13px] text-g8"><FilmStrip size={16} />Finished videos show up here.</li>}
      </ul>
      <Dialog open={!!it} onOpenChange={(v) => !v && setOpen(null)} title={it?.headline ?? ""} wide>
        {it && (it.video ? <VideoPlayer src={it.video} poster={it.poster} autoPlay />
          : it.projectId && projects[it.projectId] ? (projects[it.projectId].format === "vo_only"
            ? <div className="flex justify-center bg-g0 py-5"><PhonePlayer p={projects[it.projectId]} autoPlay width={280} /></div>
            : <div className="mx-auto w-full max-w-[calc(66dvh*16/9)]"><RoughCutPlayer p={projects[it.projectId]} autoPlay /></div>) : null)}
      </Dialog>
    </section>
  );
}

