import { useState } from "react";
import { Navigate, useNavigate } from "react-router";
import { ArrowCounterClockwise, Trash, FilmSlate } from "@phosphor-icons/react";
import { archiveProject, remakeStory, toast } from "@/data/store";
import type { Project } from "@/data/types";
import { useProject } from "@/components/story";
import { Button, Dialog, Tip } from "@/components/ui";
import { FinalPlayer, PostCard } from "./Review";

/** The Render step: the finished video, posting it, and making it again or throwing it away. */
export default function RenderPage() {
  const p = useProject()!;
  if (p.stage !== "render" && p.stage !== "done") return <Navigate to="../review" replace />;
  const f = p.final;
  const vo = p.format === "vo_only";
  const ready = p.stage === "done" && f?.state === "ready" && !!f.video;
  return (
    <div className="mx-auto max-w-[1440px] px-5 pt-5 pb-24 lg:px-8">
      <div className="grid grid-cols-1 gap-x-8 gap-y-10 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="min-w-0">
          {ready ? (vo ? <div className="flex justify-center"><FinalPlayer src={f.video!} poster={f.poster} width={340} /></div>
            : <video src={f.video} poster={f.poster} controls playsInline preload="metadata" className="block aspect-video w-full rounded-md bg-black" aria-label="The final video" />)
            : <div className={vo ? "mx-auto grid aspect-[9/16] w-[340px] max-w-full place-items-center rounded-md border border-dashed border-g5" : "grid aspect-video w-full place-items-center rounded-md border border-dashed border-g5"}>
              <p className="flex items-center gap-2 px-6 text-center text-[13.5px] text-g8"><FilmSlate size={16} />
                {p.render?.state === "queued" ? `In the render queue${p.render.waitNote ? `. ${p.render.waitNote}` : ""}.` : `Rendering, ${p.render?.percent ?? 0}% done.`}</p>
            </div>}
        </div>
        <aside className="space-y-8 xl:sticky xl:top-[72px] xl:self-start">
          <PostCard p={p} voicing={0} short={0} total={f?.seconds ?? 0} />
          {p.stage === "done" && <FinishedCard p={p} />}
        </aside>
      </div>
    </div>
  );
}

export function FinishedCard({ p }: { p: Project }) {
  return (
    <section aria-labelledby="redo-h" className="rounded-md border border-g4 bg-g1 p-5">
      <h2 id="redo-h" className="text-[15px] font-semibold">Not right?</h2>
      <p className="mt-1 mb-4 text-[12.5px] text-g8">Make it again, with changes or as it is, or discard it.</p>
      <FinishedActions p={p} />
    </section>
  );
}

/** Remake / Discard for a rendered story (the Render page, Review, the Desk's ready-to-post list). */
export function FinishedActions({ p, compact }: { p: Project; compact?: boolean }) {
  const nav = useNavigate();
  const [ask, setAsk] = useState<"remake" | "discard" | null>(null);
  const yt = p.posts?.youtube?.state;
  const why = yt === "posted" || yt === "posting" ? "It is public on YouTube. Take it down there first."
    : yt === "uploading" ? "It is being uploaded right now." : "";
  const unlisted = yt === "awaiting" || !!p.posts?.youtube?.videoId;
  const note = unlisted && <p className="text-[13px] text-g8">Its unlisted upload stays in "Awaiting approval" on YouTube; remove it there if no one should approve it.</p>;
  async function remake(now: boolean) {
    setAsk(null);
    if (!(await remakeStory(p.id, now))) return;
    toast(now ? "Back in the render queue." : "Opened again. Change what you need, then render it.", "ok");
    nav(now ? "/desk" : `/story/${p.id}/review`);
  }
  const size = compact ? "sm" : undefined;
  return (
    <>
      <Tip label={why || "Make it again"}><span className={compact ? "" : "block"}>
        <Button kind="secondary" size={size} className={compact ? "" : "w-full"} icon={<ArrowCounterClockwise size={13} />} disabled={!!why} onClick={() => setAsk("remake")}>Remake</Button>
      </span></Tip>
      <Tip label={why || "Throw this video away"}><span className={compact ? "" : "mt-2 block"}>
        <Button kind="ghost" size={size} className={compact ? "" : "w-full"} icon={<Trash size={13} />} disabled={!!why} onClick={() => setAsk("discard")}>Discard</Button>
      </span></Tip>
      <Dialog open={ask === "remake"} onOpenChange={(v) => !v && setAsk(null)} title="Make this video again?">
        <div className="space-y-4 p-5 text-[14px]">
          <p>This video is dropped and the story opens again. Change it on Script, Visuals or Review and render it, or send it back to the render queue as it is.</p>
          {note}
          <div className="flex flex-wrap justify-end gap-2">
            <Button kind="ghost" onClick={() => setAsk(null)}>Not now</Button>
            <Button kind="secondary" onClick={() => remake(true)}>Render again as it is</Button>
            <Button kind="primary" onClick={() => remake(false)}>Open it to change</Button>
          </div>
        </div>
      </Dialog>
      <Dialog open={ask === "discard"} onOpenChange={(v) => !v && setAsk(null)} title="Discard this video?">
        <div className="space-y-4 p-5 text-[14px]">
          <p>The video and its story leave the desk and the library.</p>
          {note}
          <div className="flex justify-end gap-2">
            <Button kind="ghost" onClick={() => setAsk(null)}>Keep it</Button>
            <Button kind="primary" onClick={() => { setAsk(null); archiveProject(p.id); toast("Discarded.", "ok"); nav("/desk"); }}>Discard</Button>
          </div>
        </div>
      </Dialog>
    </>
  );
}
