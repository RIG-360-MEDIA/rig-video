import { useState, type ReactNode } from "react";
import { motion } from "motion/react";
import { Cpu, Brain, UsersThree, SlidersHorizontal } from "@phosphor-icons/react";
import { useStore, setDefaults, parseLength, toast } from "@/data/store";
import { Button, Input, Ring, Segmented, Switch, Tag, Tip, cx, mmss, useFormatOptions } from "@/components/ui";

const TABS = [["defaults", "New videos", SlidersHorizontal], ["machines", "Machines", Cpu], ["members", "Members", UsersThree]] as const;
type Tab = (typeof TABS)[number][0];

export default function Settings() {
  const [tab, setTab] = useState<Tab>("defaults");
  return (
    <div className="mx-auto max-w-[1120px] px-5 pt-8 pb-20">
      <h1 className="mb-7 text-[26px] font-semibold tracking-[-0.02em]">Settings</h1>
      <div className="grid grid-cols-1 gap-8 md:grid-cols-[200px_minmax(0,1fr)]">
        <nav aria-label="Settings" className="flex gap-1 overflow-x-auto md:flex-col">
          {TABS.map(([k, l, I]) => (
            <button key={k} onClick={() => setTab(k)} aria-current={tab === k ? "page" : undefined}
              className={cx("relative flex h-9 shrink-0 items-center gap-2.5 rounded-sm px-3 text-left text-[13.5px] font-medium transition-colors", tab === k ? "text-g10" : "text-g8 hover:text-g10")}>
              {tab === k && <motion.span layoutId="set-tab" className="absolute inset-0 rounded-sm bg-g3" transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }} />}
              <I size={16} className="relative" /><span className="relative">{l}</span>
            </button>
          ))}
        </nav>
        <motion.div key={tab} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.24, ease: [0.16, 1, 0.3, 1] }} className="min-w-0 space-y-8">
          {tab === "defaults" && <Defaults />}
          {tab === "machines" && <Machines />}
          {tab === "members" && <Members />}
        </motion.div>
      </div>
    </div>
  );
}

function Group({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  return (
    <section>
      <h2 className="text-[15px] font-semibold">{title}</h2>
      {hint && <p className="mt-0.5 text-[13px] text-g8">{hint}</p>}
      <div className="mt-3 divide-y divide-g4 rounded-md border border-g4 bg-g1">{children}</div>
    </section>
  );
}
function Line({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3.5">
      <div className="min-w-0"><div className="text-[13.5px]">{label}</div>{hint && <div className="text-[12.5px] text-g8">{hint}</div>}</div>
      {children}
    </div>
  );
}

function Defaults() {
  const d = useStore((s) => s.defaults);
  const formatOptions = useFormatOptions();
  const [len, setLen] = useState(mmss(d.length));
  const parsed = parseLength(len);
  return (
    <>
      <Group title="New videos" hint="What a new story starts with. You can change any of it per story.">
        <Line label="Format" hint={d.format === "vo_only" ? "Portrait 9:16. The voice over real footage, no anchor on screen." : undefined}><Segmented size="sm" label="Default format" value={d.format} set={(v) => setDefaults({ format: v })} options={formatOptions} /></Line>
        <Line label="Length" hint="Free length. Over 5 minutes asks before writing.">
          <span className="flex items-center gap-2">
            <Input value={len} onChange={(e) => setLen(e.target.value)} onBlur={() => { if (parsed) { setDefaults({ length: parsed }); setLen(mmss(parsed)); toast("Default length saved"); } else setLen(mmss(d.length)); }}
              aria-label="Default length" aria-invalid={!parsed} className={cx("h-8 w-[96px] font-mono text-edge", !parsed && "border-bad")} />
          </span>
        </Line>
        <div className="px-4 py-3.5"><Switch id="d-outro" on={d.outro} set={(v) => setDefaults({ outro: v })} label="DNL outro" hint="The DNL outro (12 seconds) plays after the last part" /></div>
      </Group>
    </>
  );
}

function Machines() {
  const queue = useStore((s) => s.queue);
  const projects = useStore((s) => s.projects);
  return (
    <>
      <Group title="Script writer" hint="Writes the first script and every rewrite.">
        <Line label="Local model" hint="Runs on our own machine. The first choice for every script."><span className="flex items-center gap-2"><Brain size={16} className="text-g8" /><Tag tone="ok">Primary</Tag></span></Line>
        <Line label="Groq" hint="Used only when the local model is down."><Tag>Fallback</Tag></Line>
      </Group>
      <Group title="Render machine" hint="One video renders at a time. The rest wait in order.">
        {queue.length === 0 ? <Line label="Idle" hint="Nothing is rendering."><Tag tone="ok">Free</Tag></Line> : queue.map((j, i) => (
          <Line key={j.projectId} label={projects[j.projectId]?.headline ?? j.projectId} hint={i === 0 ? `${j.state === "assembling" ? "Putting it together" : "Rendering"}` : `Waiting, ${i} ahead`}>
            {i === 0 ? <Ring pct={j.percent} size={40} label={<span className="text-[11px]">{j.percent}</span>} /> : <span className="edge text-[12.5px]">#{i + 1}</span>}
          </Line>
        ))}
      </Group>
      <Group title="Footage search" hint="Our footage repo, called over its API.">
        <Line label="Search service" hint="Finds and cuts news footage for each part."><Tag tone="ok">Connected</Tag></Line>
      </Group>
    </>
  );
}

function Members() {
  const user = useStore((s) => s.user);
  const ws = useStore((s) => s.workspace);
  return (
    <Group title={`${ws?.name ?? "Workspace"} members`} hint="Everyone here sees the same picks, stories and library.">
      {user && (
        <Line label={user.name} hint={user.email}><Tag tone="marker">{user.role}</Tag></Line>
      )}
      <div className="flex items-center justify-between gap-3 px-4 py-3.5">
        <span className="text-[13px] text-g8">Inviting people opens when sign-up does.</span>
        <Tip label="Not open yet"><span><Button kind="secondary" size="sm" disabled>Invite</Button></span></Tip>
      </div>
    </Group>
  );
}
