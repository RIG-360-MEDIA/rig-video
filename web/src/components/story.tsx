import { useEffect, useState, Suspense } from "react";
import { Link, Navigate, Outlet, useLocation, useNavigate, useParams } from "react-router";
import { AnimatePresence, motion } from "motion/react";
import { CaretRight, Check, Lock, Waveform, MagnifyingGlass, PencilSimpleLine, FilmStrip, Microphone, VideoCamera } from "@phosphor-icons/react";
import { useStore, voiceProgress, retryJob, switchFormat } from "@/data/store";
import type { Project, Stage } from "@/data/types";
import { Brand } from "./shell";
import { Button, Dialog, Tag, Tip, cx, istTime, Ring } from "./ui";

export function useProject(): Project | undefined {
  const { id } = useParams();
  return useStore((s) => (id ? s.projects[id] : undefined));
}

const STEPS: { key: Stage; label: string; path?: string }[] = [
  { key: "script", label: "Script", path: "script" },
  { key: "visuals", label: "Visuals", path: "visuals" },
  { key: "review", label: "Review", path: "review" },
  { key: "render", label: "Render", path: "render" },
];
const RANK: Record<Stage, number> = { script: 0, visuals: 1, review: 2, render: 3, done: 4 };

export function StoryFrame() {
  const p = useProject();
  const loc = useLocation();
  const nav = useNavigate();
  const step = loc.pathname.split("/")[3];
  useEffect(() => { window.scrollTo(0, 0); }, [step]);
  if (!p) return <Navigate to="/desk" replace />;
  if (!step) return <Navigate to={p.stage === "visuals" ? "visuals" : p.stage === "script" ? "script" : p.stage === "done" ? "render" : "review"} replace />;
  const current = STEPS.findIndex((s) => s.path === step);
  return (
    <div className="flex min-h-full flex-col">
      <header className="sticky top-0 z-30 border-b border-g4 bg-g0/92 backdrop-blur-md">
        <div className="mx-auto flex h-13 max-w-[1680px] items-center gap-3 px-4 sm:gap-4 sm:px-5">
          <Brand />
          <CaretRight size={12} className="hidden text-g6 md:block" />
          <Link to="/desk" className="hidden text-[13.5px] text-g8 transition-colors hover:text-g10 md:block">Desk</Link>
          <CaretRight size={12} className="hidden text-g6 md:block" />
          <h1 className="hidden min-w-0 truncate text-[13.5px] font-semibold text-g10 md:block" title={p.headline}>{p.headline}</h1>
          <div className="ml-auto flex min-w-0 items-center gap-4">
            <span className="hidden lg:contents"><JobStatus p={p} /></span>
            <nav aria-label="Steps" className="flex items-center rounded-sm border border-g4 bg-g1 p-0.5">
              {STEPS.map((s, i) => {
                const reach = RANK[p.stage] >= RANK[s.key];
                const on = i === current;
                const done = RANK[p.stage] > RANK[s.key];
                const locked = RANK[p.stage] >= RANK.render && s.key !== "render";
                const body = (
                  <span className={cx("narrow relative flex h-7 items-center gap-1.5 rounded-xs px-2.5 text-[13px] sm:px-3 font-semibold transition-colors",
                    on ? "text-g0" : reach ? "text-g9 hover:text-g10" : "text-g6")}>
                    {on && <motion.span layoutId="step-on" className="absolute inset-0 rounded-xs bg-g10" transition={{ type: "spring", duration: 0.35, bounce: 0.1 }} />}
                    <span className="relative font-mono text-[10.5px] opacity-70">{i + 1}</span>
                    <span className="relative hidden sm:inline">{s.label}</span>
                    {done && !on && <Check size={12} weight="bold" className="relative text-ok" />}
                    {s.key === "render" && p.render && p.stage === "render" && <span className="relative edge text-[11px]">{p.render.percent}%</span>}
                  </span>
                );
                if (!s.path || !reach) return <Tip key={s.key} label={s.key === "render" ? "Send it from Review" : "Finish the step before this one"}><span>{body}</span></Tip>;
                return <button key={s.key} onClick={() => nav(`/story/${p.id}/${s.path}`)} aria-current={on ? "step" : undefined}>{locked && !on ? <Tip label="Read-only while it renders"><span>{body}</span></Tip> : body}</button>;
              })}
            </nav>
            <span className="hidden w-[92px] text-right text-[12px] text-g8 xl:block">Saved {istTime(p.updatedAt)}</span>
          </div>
        </div>
        {RANK[p.stage] >= RANK.render && (
          <div className="border-t border-g4 bg-g1">
            <div className="mx-auto flex min-h-9 max-w-[1680px] items-center gap-2.5 px-4 py-1.5 text-[12.5px] text-g8 sm:px-5">
              <Lock size={13} />
              {p.stage === "done" ? "Rendered. Post it, make it again or discard it on the Render page; the story is read-only." : `In the render queue${p.render?.waitNote ? ` (${p.render.waitNote})` : ""}. This story is read-only until it finishes or you take it out of the queue.`}
            </div>
          </div>
        )}
      </header>
      <AnimatePresence mode="wait" initial={false}>
        <motion.main key={step} className="flex-1" initial={{ opacity: 0, x: 10 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -10, transition: { duration: 0.12 } }}
          transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}>
          <Suspense fallback={<div className="skeleton mx-auto mt-10 h-1 w-40 rounded-full" />}><Outlet /></Suspense>
        </motion.main>
      </AnimatePresence>
    </div>
  );
}

function JobStatus({ p }: { p: Project }) {
  const job = useStore((s) => s.jobs[p.id]);
  const v = voiceProgress(p);
  if (job?.failed) return (
    <span className="hidden items-center gap-2 text-[12px] text-bad md:flex">
      {{ write: "The script could not be written", search: "The footage search stopped", voice: "The voices stopped", check: "The clip check stopped" }[job.kind]}
      <button className="underline underline-offset-2 hover:text-g10" onClick={() => retryJob(p.id, job.kind)}>Try again</button>
    </span>
  );
  const items: { icon: React.ReactNode; text: string; pct: number }[] = [];
  if (job?.kind === "write") items.push({ icon: <PencilSimpleLine size={13} />, text: job.note, pct: job.progress * 100 });
  if (job?.kind === "search") items.push({ icon: <MagnifyingGlass size={13} />, text: "Searching footage", pct: job.progress * 100 });
  if (job?.kind === "check") items.push({ icon: <FilmStrip size={13} />, text: job.parts ? "Checking a beat" : "Checking the clips", pct: job.progress * 100 });
  if (p.stage !== "script" && v?.busy) items.push({ icon: <Waveform size={13} />, text: `Voice ${v.done} of ${v.total}`, pct: (v.done / v.total) * 100 });
  return (
    <AnimatePresence>
      {items.map((it) => (
        <motion.div key={it.text.split(" ")[0]} initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
          className="hidden items-center gap-2 text-[12px] text-g9 md:flex">
          <Ring pct={it.pct} size={20} label={<span />} />
          <span className="flex items-center gap-1.5">{it.icon}{it.text}</span>
        </motion.div>
      ))}
    </AnimatePresence>
  );
}

// ------------------------------------------------------------------ footage page: which type the story is, and switching it

/** "With anchor" / "No anchor · 9:16", why (the daily run's decision or an editor's switch), and a switch to the other. */
export function FormatSwitch({ p, locked }: { p: Project; locked: boolean }) {
  const [ask, setAsk] = useState(false);
  const vo = p.format === "vo_only";
  const other = vo ? "anchor_vo" : "vo_only";
  const busy = p.stage === "script";
  return (
    <div className="rounded-sm border border-g4 bg-g2 p-2.5">
      <div className="flex items-center justify-between gap-2">
        <Tip label={p.formatWhy?.text ?? (vo ? "Voice over footage, 9:16, no anchor on screen" : "The anchor presents, with footage under the voice-over parts")}>
          <span className="inline-flex items-center gap-1.5 text-[13px] font-semibold">
            {vo ? <Microphone size={14} weight="fill" className="text-vo" /> : <VideoCamera size={14} weight="fill" className="text-anchor" />}
            {vo ? "No anchor · 9:16" : "With anchor"}
            {p.formatWhy?.by === "auto" && <Tag tone="edge">Auto</Tag>}
          </span>
        </Tip>
        {!locked && <button className="text-[12px] text-g8 underline underline-offset-2 hover:text-g10 disabled:opacity-40" disabled={busy} onClick={() => setAsk(true)}>
          {busy ? "Writing…" : vo ? "Switch to with anchor" : "Switch to no anchor"}</button>}
      </div>
      {p.formatWhy && <p className="mt-1 text-[11.5px] leading-snug text-g8">{p.formatWhy.text}</p>}
      <Dialog open={ask} onOpenChange={setAsk} title={vo ? "Give this story an anchor?" : "Make this story without an anchor?"}>
        <div className="space-y-4 p-5 text-[14px]">
          <p>{vo ? "The story becomes anchor + footage. " : "The story becomes a 9:16 voice-over on footage. "}
            {p.versions[other]?.length ? "Its script for that type is kept; voices and footage are made for it." : "A script for that type is written and approved by itself, then its voices and footage are made."}
            {" "}This page shows the new type when it is ready.</p>
          <div className="flex justify-end gap-2">
            <Button kind="ghost" onClick={() => setAsk(false)}>Not now</Button>
            <Button kind="primary" onClick={() => { setAsk(false); switchFormat(p.id, other); }}>{vo ? "Switch to with anchor" : "Switch to no anchor"}</Button>
          </div>
        </div>
      </Dialog>
    </div>
  );
}
