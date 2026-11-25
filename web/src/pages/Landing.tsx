// RIG-Video landing. One news video, taken apart: five layers fanned out, and scrolling puts them back
// together into the finished frame. Layer order is the product's order: story, anchor, voice, footage, graphics.
// The story is an example (labelled); the anchor and her voice are our own; the flood aerial is generated.
import { useEffect, useRef, useState, type PointerEvent, type ReactNode } from "react";
import { Link } from "react-router";
import { AnimatePresence, motion, useInView, useMotionValue, useReducedMotion, useScroll, useSpring, useTransform, type MotionValue } from "motion/react";
import { ArrowRight, FilePdf, LinkSimple, Pause, Play, TextAa } from "@phosphor-icons/react";
import Lenis from "lenis";
import Snap from "lenis/snap";
import "lenis/dist/lenis.css";
import { useStore } from "@/data/store";
import type { Anchor } from "@/data/types";
import { Fog, Wordmark } from "@/components/brandmark";

const C = { ink: "#07070a", navy: "#141519", deep: "#2c2f36", ice: "#cfd3da", frost: "#e4e6ea", coral: "#ff6a4d", text: "#eceef1" };
const EASE = [0.16, 1, 0.3, 1] as const;
// black and silver throughout; coral is the only colour
const S = { bg: "#07070a", card: "#141519", edge: "#cfd3da", label: "#e4e6ea", glow: "rgba(205,210,220,.22)", fogA: "#1b1c21", fogB: "#33363d", fogC: "rgba(225,228,235,.10)" };

// Stage is drawn at 1240x600 design px and scaled to fit.
const W = 1240, H = 600;
const FW = 800, FH = 450, FX = (W - FW) / 2, FY = 70; // the assembled frame
type Pose = { x: number; y: number; w: number; h: number; z: number; r: number; o: number };
const FAN_X = [0, 290, 540, 795, 1045], FAN_W = [350, 285, 270, 262, 255];
const fan = (i: number): Pose => ({ x: FAN_X[i], y: 70 + i * 16, w: FAN_W[i], h: 470 - i * 30, z: -i * 30, r: 20, o: 1 });
const LAYERS: { key: string; label: string; end: Pose }[] = [
  { key: "story", label: "Story", end: { x: FX, y: FY, w: FW, h: FH, z: 0, r: 0, o: 0 } },
  { key: "anchor", label: "Anchor", end: { x: FX, y: FY, w: FW, h: FH, z: 0, r: 0, o: 1 } },
  { key: "voice", label: "Voice", end: { x: FX, y: FY + FH - 64, w: FW, h: 64, z: 0, r: 0, o: 1 } },
  { key: "footage", label: "Footage", end: { x: FX + FW - 272, y: FY + 22, w: 250, h: 150, z: 0, r: 0, o: 1 } },
  { key: "graphics", label: "Graphics", end: { x: FX, y: FY, w: FW, h: FH, z: 0, r: 0, o: 1 } },
];

const STORY = "Severe flooding across the valley has forced around 4,000 people from their homes, officials said on Tuesday. Rescue crews worked through the night as rain kept falling.";
const TICKER = ["Rivers still rising across the valley", "4,000 people moved to shelters", "Rail lines closed until Friday", "More rain expected overnight"];

export default function Landing() {
  const signedIn = useStore((s) => s.signedIn);
  const mine = useStore((s) => s.anchors).filter((a) => a.offered);
  const [shown, setShown] = useState<Anchor[]>([]);
  useEffect(() => {                                                 // signed out: the desk has no anchors, ask the public list
    if (mine.length) return;
    fetch("/api/anchors").then((r) => (r.ok ? r.json() : [])).then(setShown).catch(() => {});
  }, [mine.length]);
  const anchors = mine.length ? mine : shown;
  const go = signedIn ? "/desk" : "/signin?new=1";
  useSmoothSections();

  return (
    <div className="min-h-[100dvh] overflow-x-clip" style={{ background: C.ink, color: C.text }}>
      <Nav go={go} signedIn={signedIn} />
      <Fan go={go} />
      <Sheet z={20} id="start" lift><StartAnything /></Sheet>
      <Sheet z={21} id="anchors"><Anchors anchors={anchors} /></Sheet>
      <Sheet z={22} id="try"><Finale go={go} /></Sheet>
      <footer className="relative z-[25] border-t" style={{ borderColor: "rgba(207,211,218,.12)", background: C.ink }}>
        <div className="mx-auto flex max-w-[1240px] flex-wrap items-center justify-between gap-4 px-5 py-8 text-[13px]" style={{ color: "rgba(236,238,241,.6)" }}>
          <Wordmark small />
          <span>Example story and footage on this page are illustrations.</span>
        </div>
      </footer>
    </div>
  );
}

/** Smooth scrolling, and every scroll gesture travels to the next stop and rests there:
 *  the fan, the finished frame, then each sheet (and the centre of anything marked data-stop). */
function useSmoothSections() {
  const reduce = useReducedMotion();
  useEffect(() => {
    if (reduce) return;
    const lenis = new Lenis({ autoRaf: true, lerp: 0.09, anchors: true });
    const snap = new Snap(lenis, { type: "lock", duration: 1.1, easing: easeInOut, debounce: 50, distanceThreshold: Number.POSITIVE_INFINITY });
    let removers: (() => void)[] = [];
    const build = () => {
      removers.forEach((r) => r()); removers = [];
      const vh = innerHeight, max = document.documentElement.scrollHeight - vh;
      const at = (el: Element) => el.getBoundingClientRect().top + scrollY;
      const pts = new Set<number>([0]);
      const hero = document.getElementById("layers");
      if (hero) pts.add(Math.round((hero.offsetHeight * 260) / 360 - vh)); // the five layers have just come together
      document.querySelectorAll<HTMLElement>("[data-sheet]").forEach((el) => pts.add(Math.round(at(el))));
      document.querySelectorAll<HTMLElement>("[data-stop]").forEach((el) => pts.add(Math.round(at(el) + el.offsetHeight / 2 - vh / 2)));
      pts.add(max);
      [...pts].filter((v) => v >= 0 && v <= max).sort((a, b) => a - b).forEach((v) => removers.push(snap.add(v)));
    };
    build();
    const ro = new ResizeObserver(build); ro.observe(document.body);
    return () => { ro.disconnect(); snap.destroy(); lenis.destroy(); };
  }, [reduce]);
}

function Nav({ go, signedIn }: { go: string; signedIn: boolean }) {
  return (
    <motion.header className="absolute inset-x-0 top-0 z-30" initial={{ opacity: 0, y: -16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.9, delay: 0.1, ease: EASE }}>
      <div className="mx-auto flex h-[92px] max-w-[1240px] items-center gap-8 px-5">
        <Link to="/" aria-label="RIG-Video home"><Wordmark /></Link>
        <Link to={signedIn ? go : "/signin"} className="ml-auto inline-flex h-12 items-center rounded-[12px] border px-6 text-[17px] font-medium transition-colors hover:bg-white/5"
          style={{ borderColor: "rgba(236,238,241,.35)" }}>{signedIn ? "Open the desk" : "Sign in"}</Link>
      </div>
    </motion.header>
  );
}

function useStageScale() {
  const ref = useRef<HTMLDivElement>(null);
  const [d, setD] = useState({ s: 1, bw: W });
  useEffect(() => {
    const el = ref.current; if (!el) return;
    // Wide screens fit the whole fan. Narrow ones fit the finished frame instead and let the fan bleed right.
    const ro = new ResizeObserver(([e]) => {
      const { width: bw } = e.contentRect;
      const room = innerHeight - 104 - 250; // nav above, tagline + button below
      const s = Math.min(1, room / H, Math.max(bw / W, Math.min(0.6, bw / (FW + 40))));
      setD({ s, bw });
    });
    ro.observe(el); return () => ro.disconnect();
  }, []);
  return [ref, d.s, d.bw] as const;
}

function Fan({ go }: { go: string }) {
  const reduce = useReducedMotion();
  const sec = useRef<HTMLDivElement>(null);
  const whole = useRef<HTMLElement>(null);
  const { scrollYProgress } = useScroll({ target: sec, offset: ["start start", "end end"] });
  const { scrollYProgress: q } = useScroll({ target: whole, offset: ["start start", "end end"] });
  const covered = useTransform(q, (v) => ramp(v, 0.6, 1, 0, 1));
  const dim = useTransform(covered, (v) => v * 0.65);
  const sink = useTransform(covered, (v) => 1 - v * 0.06);
  const [box, s, bw] = useStageScale();
  const bleed = Math.max(0, (W * s - bw) / 2); // how far the scaled stage overhangs each side
  const shift = useTransform(scrollYProgress, (v) => (reduce ? bleed : ramp(v, 0.12, 0.7, bleed, 0)));

  return (
    <section ref={whole} id="layers" className={reduce ? "relative" : "relative h-[360vh]"}>
      <div ref={sec} aria-hidden className="pointer-events-none absolute inset-x-0 top-0 h-[260vh]" />
      <motion.div className={reduce ? "relative" : "sticky top-0 flex h-[100dvh] flex-col justify-center"} style={{ minHeight: 640, scale: reduce ? 1 : sink, background: S.bg }}>
        <Fog />
        <h1 className="sr-only">A news video, taken apart. Paste a story, pick an anchor; we write it, voice it, find the footage and add the graphics.</h1>

        <div ref={box} className="relative mx-auto mt-[80px] w-full max-w-[1240px] px-5" style={{ height: H * s }}>
          <motion.div className="absolute left-1/2 top-0" style={{ x: shift }} aria-hidden>
          <div className="absolute top-0 origin-top" style={{ width: W, height: H, left: -W / 2, transform: `scale(${s})` }}>
            <div className="absolute inset-0" style={{ perspective: 1500, perspectiveOrigin: "60% 40%" }}>
              {LAYERS.map((l, i) => (
                <Layer key={l.key} i={i} label={l.label} end={l.end} p={reduce ? null : scrollYProgress}>
                  {l.key === "story" && <StoryLayer />}
                  {l.key === "anchor" && <img src="/landing/anchor.jpg" alt="" className="size-full object-cover object-[50%_30%]" />}
                  {l.key === "voice" && <VoiceLayer tone={S.edge} />}
                  {l.key === "footage" && <img src="/landing/footage.jpg" alt="" className="size-full object-cover" />}
                  {l.key === "graphics" && <GraphicsLayer chip={S.edge} />}
                </Layer>
              ))}
            </div>
            {!reduce && <Markers p={scrollYProgress} labels={bleed === 0} />}
          </div>
          </motion.div>
        </div>

        <div className="relative z-10 mx-auto mt-2 flex flex-col items-center px-5 text-center">
          <Words className="max-w-[30ch] text-[clamp(20px,2.6vw,34px)] font-semibold leading-[1.15] tracking-[-0.02em]" delay={1.05}
            text="Paste a story. Pick who tells it. We do the voice, the footage and the graphics." />
          <motion.div initial={{ opacity: 0, y: 14, scale: 0.94 }} animate={{ opacity: 1, y: 0, scale: 1 }} transition={{ duration: 0.9, delay: 1.55, ease: EASE }} className="mt-6">
            <Cta to={go} pulse />
          </motion.div>
        </div>
        {!reduce && <motion.div aria-hidden className="pointer-events-none absolute inset-0 z-20" style={{ background: C.ink, opacity: dim }} />}
      </motion.div>
    </section>
  );
}

/* Once the five layers are one frame, thin lines name its parts. Stage coordinates; frame at (FX, FY). */
const MARKS = [
  { label: "AI anchor label", side: "l" as const, y: FY + 16, tx: FX + 14, ty: FY + 29 },
  { label: "Anchor", side: "l" as const, y: FY + 150, tx: FX + 330, ty: FY + 170 },
  { label: "Subtitles", side: "l" as const, y: FY + 252, tx: FX + 184, ty: FY + 264 },
  { label: "Footage", side: "r" as const, y: FY + 80, tx: FX + FW - 22, ty: FY + 97 },
  { label: "Headline", side: "r" as const, y: FY + 306, tx: FX + FW - 18, ty: FY + 322 },
  { label: "Ticker", side: "r" as const, y: FY + 352, tx: FX + FW - 18, ty: FY + 368 },
  { label: "Voice", side: "r" as const, y: FY + 402, tx: FX + FW - 60, ty: FY + 418 },
];

function Markers({ p, labels }: { p: MotionValue<number>; labels: boolean }) {
  const on = useTransform(p, (v) => ramp(v, 0.8, 0.92, 0, 1));
  const [c, setC] = useState(0);
  useEffect(() => { const t = setInterval(() => setC((v) => (v + 1) % CAPTIONS.length), 2200); return () => clearInterval(t); }, []);
  return (
    <motion.div className="pointer-events-none absolute inset-0" style={{ opacity: on, zIndex: 10 }} aria-hidden>
      {/* the two parts only the finished frame has */}
      <span className="absolute rounded-[6px] px-2.5 py-1 text-[13px] font-semibold" style={{ left: FX + 16, top: FY + 16, background: "rgba(7,7,10,.72)", color: S.label }}>AI anchor</span>
      <div className="absolute flex justify-center" style={{ left: FX, width: FW, top: FY + 248 }}>
        <span className="rounded-[6px] px-3 py-1 text-[20px] font-semibold text-white" style={{ background: "rgba(0,0,0,.62)" }}>{CAPTIONS[c]}</span>
      </div>
      {labels && <>
      <svg className="absolute inset-0" width={W} height={H}>
        {MARKS.map((m) => <line key={m.label} x1={m.side === "l" ? FX - 18 : FX + FW + 18} y1={m.y + 12} x2={m.tx} y2={m.ty} stroke={S.edge} strokeWidth={1.4} strokeOpacity={0.85} />)}
        {MARKS.map((m) => <circle key={m.label + "d"} cx={m.tx} cy={m.ty} r={4} fill={S.edge} />)}
      </svg>
      {MARKS.map((m) => (
        <span key={m.label} className={`absolute whitespace-nowrap text-[17px] font-semibold leading-6 ${m.side === "l" ? "text-right" : ""}`}
          style={{ top: m.y, left: m.side === "l" ? FX - 200 : FX + FW + 24, width: 176, color: S.label }}>{m.label}</span>
      ))}
      </>}
    </motion.div>
  );
}

function Layer({ i, label, end, p, children }: { i: number; label: string; end: Pose; p: MotionValue<number> | null; children: ReactNode }) {
  const a = fan(i);
  // each layer closes a little after the one before it
  const t0 = 0.12 + i * 0.05, t1 = 0.58 + i * 0.04;
  const k = <K extends keyof Pose>(key: K) => (p ? useTransform(p, (v) => ramp(v, t0, t1, a[key], end[key], easeInOut)) : a[key]); // eslint-disable-line react-hooks/rules-of-hooks
  const x = k("x"), y = k("y"), w = k("w"), h = k("h"), z = k("z"), r = k("r"), o = k("o");
  const tag = p ? useTransform(p, (v) => ramp(v, t0, t0 + 0.12, 1, 0)) : 1; // eslint-disable-line react-hooks/rules-of-hooks
  const glass = p ? useTransform(p, (v) => ramp(v, t1 - 0.05, t1, 1, 0)) : 1; // eslint-disable-line react-hooks/rules-of-hooks
  const bare = label === "Graphics" || label === "Voice";

  return (
    <motion.div className="absolute left-0 top-0" style={{ x, y, width: w, height: h, z, rotateY: r, opacity: o, zIndex: i + 1, transformOrigin: "0% 50%" }}>
     <motion.div className="relative size-full" initial={{ opacity: 0, y: 110, rotateX: 16, scale: 0.92, filter: "blur(10px)" }}
       animate={{ opacity: 1, y: 0, rotateX: 0, scale: 1, filter: "blur(0px)" }} transition={{ duration: 1.25, delay: 0.25 + i * 0.13, ease: EASE }}>
      <motion.div style={{ opacity: tag }} initial={{ y: 10, filter: "blur(4px)" }} animate={{ y: 0, filter: "blur(0px)" }} transition={{ duration: 0.7, delay: 0.85 + i * 0.13, ease: EASE }} className="absolute -top-11 left-3 flex items-center gap-2 text-[22px] font-semibold" >
        <span className="grid size-8 place-items-center rounded-[7px] text-[17px] font-bold" style={{ background: S.edge, color: S.bg }}>{i + 1}</span>
        <span style={{ color: S.label }}>{label}</span>
      </motion.div>
      <div className="relative size-full overflow-hidden rounded-[14px]" style={{ background: bare ? "transparent" : S.card }}>
        {children}
        <motion.div className="pointer-events-none absolute inset-0 rounded-[14px]" style={{
          opacity: glass,
          boxShadow: `inset 0 0 0 1.5px ${S.edge}aa, inset 0 0 40px rgba(220,224,232,.12), 0 0 46px ${S.glow}`,
          background: `linear-gradient(115deg, rgba(255,255,255,.16), transparent 38%)${bare ? ", rgba(20,21,25,.55)" : ""}`,
        }}>
          <motion.span className="absolute inset-y-0 w-1/2" style={{ background: "linear-gradient(100deg, transparent, rgba(220,223,229,.28), transparent)" }}
            initial={{ x: "-120%" }} animate={{ x: "260%" }} transition={{ duration: 1.4, delay: 1.1 + i * 0.13, ease: [0.45, 0, 0.2, 1] }} />
        </motion.div>
      </div>
     </motion.div>
    </motion.div>
  );
}

// Function transforms on purpose: Motion hands range-mapped scroll opacity to the browser's ScrollTimeline,
// which ignored this section's offsets and left the fades stuck at 1.
const ramp = (v: number, a: number, b: number, from: number, to: number, ease = (t: number) => t) =>
  from + (to - from) * ease(Math.min(1, Math.max(0, (v - a) / (b - a))));
const easeInOut = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);

/** Words rise out of a mask one after another. */
function Words({ text, className, delay = 0, as: Tag = "p", inView }: { text: string; className?: string; delay?: number; as?: "p" | "h2"; inView?: boolean }) {
  // the trigger watches the whole line: each word starts clipped out of view, so it can't watch itself
  const ref = useRef<HTMLParagraphElement>(null);
  const seen = useInView(ref, { once: true, margin: "-60px" });
  const go = !inView || seen;
  return (
    <Tag ref={ref} className={className} aria-label={text}>
      {text.split(" ").map((w, j) => (
        <span key={j} aria-hidden className="inline-block overflow-hidden pb-[0.08em] align-top">
          <motion.span className="inline-block" initial={{ y: "110%", opacity: 0 }} animate={go ? { y: 0, opacity: 1 } : undefined}
            transition={{ duration: 0.8, delay: delay + j * 0.035, ease: EASE }}>{w}&nbsp;</motion.span>
        </span>
      ))}
    </Tag>
  );
}


function StoryLayer() {
  return (
    <div className="flex size-full flex-col p-7" style={{ background: "#eeeff2", color: "#0c0d10" }}>
      <div className="flex items-center justify-between border-b pb-2 text-[13px] font-semibold" style={{ borderColor: "#c9ccd2" }}>
        <span>News</span><span className="rounded-[4px] px-1.5 py-0.5 text-[11px] uppercase tracking-[0.08em]" style={{ background: "#dfe1e5", color: "#4a4e56" }}>Example story</span>
      </div>
      <div className="mt-4 text-[46px] font-extrabold leading-[0.95] tracking-[-0.035em]" style={{ fontVariationSettings: '"wdth" 88' }}>
        {["A news video,", "taken apart."].map((l, j) => (
          <span key={j} className="block overflow-hidden pb-[0.06em]">
            <motion.span className="block" initial={{ y: "105%" }} animate={{ y: 0 }} transition={{ duration: 1, delay: 0.75 + j * 0.12, ease: EASE }}>{l}</motion.span>
          </span>
        ))}
      </div>
      <p className="mt-4 text-[16px] leading-[1.4]" style={{ color: "#33373e" }}>{STORY}</p>
      <div className="mt-auto space-y-2" aria-hidden>{[92, 100, 78, 96, 64].map((w, j) => <div key={j} className="h-[7px] rounded-full" style={{ width: `${w}%`, background: "#d3d6db" }} />)}</div>
    </div>
  );
}

function VoiceLayer({ tone = C.ice }: { tone?: string }) {
  const bars = Array.from({ length: 44 }, (_, j) => 0.25 + 0.75 * Math.abs(Math.sin(j * 1.7) * Math.cos(j * 0.43)));
  return (
    <div className="flex size-full items-center justify-center gap-[4px] px-6" style={{ background: "linear-gradient(180deg, transparent, rgba(7,7,10,.65))" }}>
      {bars.map((b, j) => (
        // CSS, not JS: these run on the compositor, there are ~90 of them on the page
        <span key={j} className="w-[4px] rounded-full [animation:bar_var(--d)_ease-in-out_infinite] motion-reduce:animate-none"
          style={{ background: tone, boxShadow: `0 0 10px ${tone}`, height: `${b * 46}%`, "--d": `${0.9 + (j % 7) * 0.08}s`, "--lo": 0.45 + (j % 5) * 0.12 } as React.CSSProperties} />
      ))}
    </div>
  );
}

function GraphicsLayer({ title = "Floods force 4,000 from homes", ticker = TICKER, bottom = 64, chip = C.ice }: { title?: string; ticker?: string[]; bottom?: number; chip?: string }) {
  return (
    <div className="absolute inset-x-0 flex flex-col" style={{ bottom }}>
      <div className="mx-6 flex items-stretch" style={{ filter: "drop-shadow(0 8px 20px rgba(0,0,0,.45))" }}>
        <span className="w-3" style={{ background: C.coral, clipPath: "polygon(40% 0,100% 0,60% 100%,0 100%)" }} />
        <div className="flex-1 px-4 py-2.5 text-[28px] font-bold leading-tight tracking-[-0.015em] text-white" style={{ background: C.coral }}>{title}</div>
      </div>
      <div className="mx-6 flex h-9 items-center overflow-hidden text-[14px]" style={{ background: "rgba(7,7,10,.92)" }}>
        <span className="flex h-full items-center px-3 font-bold" style={{ background: chip, color: C.ink }}>NEWS</span>
        <div className="relative flex-1 overflow-hidden">
          <div className="flex w-max animate-[ticker_26s_linear_infinite] gap-8 whitespace-nowrap pl-4" style={{ color: C.frost }}>
            {[...ticker, ...ticker].map((t, j) => <span key={j}>{t}</span>)}
          </div>
        </div>
      </div>
    </div>
  );
}

function Cta({ to, className = "", pulse, label = "Get started" }: { to: string; className?: string; pulse?: boolean; label?: string }) {
  return (
    <Link to={to} className={`group relative inline-flex h-14 items-center gap-2.5 rounded-full px-8 text-[18px] font-semibold text-white transition-[filter,transform] hover:brightness-110 active:translate-y-px ${className}`}
      style={{ background: C.coral, boxShadow: `0 10px 40px -8px ${C.coral}aa` }}>
      {pulse && <motion.span aria-hidden className="pointer-events-none absolute inset-0 rounded-full" style={{ boxShadow: `0 0 0 2px ${C.coral}` }}
        initial={{ opacity: 0.8, scale: 1 }} animate={{ opacity: 0, scale: 1.35 }} transition={{ duration: 1.4, delay: 2.2, ease: "easeOut", repeat: 2, repeatDelay: 2.6 }} />}
      {label} <ArrowRight size={19} weight="bold" className="transition-transform group-hover:translate-x-1" />
    </Link>
  );
}

/* ───────────────────────── sections below the hero ───────────────────────── */

/** Each section is the next sheet laid over the one before: rounded top, shadow, its own drifting light. */
function Sheet({ children, z, id, lift }: { children: ReactNode; z: number; id?: string; lift?: boolean }) {
  const reduce = useReducedMotion();
  return (
    <section id={id} data-sheet className={`relative rounded-t-[36px] ${lift && !reduce ? "-mt-[100vh]" : "-mt-9"}`}
      style={{ zIndex: z, background: `linear-gradient(180deg, #121318, ${C.ink} 420px)`, boxShadow: "0 -40px 90px -20px rgba(0,0,0,.75), inset 0 1px 0 rgba(207,211,218,.18)" }}>
      <div aria-hidden className="pointer-events-none absolute inset-0 overflow-hidden rounded-t-[36px]">
        <div className="absolute left-[10%] top-[-10%] h-[60%] w-[80%] rounded-full will-change-transform [animation:fog-b_24s_ease-in-out_infinite]" style={{ background: `radial-gradient(closest-side, ${C.deep}80, transparent)` }} />
      </div>
      <div className="relative">{children}</div>
    </section>
  );
}

/** Rises out of a blur when it scrolls into view. */
function Rise({ children, delay = 0, className, y = 40 }: { children: ReactNode; delay?: number; className?: string; y?: number }) {
  return (
    <motion.div className={className} initial={{ opacity: 0, y, filter: "blur(8px)" }} whileInView={{ opacity: 1, y: 0, filter: "blur(0px)" }}
      viewport={{ once: true, margin: "-80px" }} transition={{ duration: 1, delay, ease: EASE }}>{children}</motion.div>
  );
}

function Head({ title, line }: { title: string; line: string }) {
  return (
    <div className="flex flex-col items-center text-center">
      <Words as="h2" inView text={title} className="max-w-[20ch] text-[clamp(36px,5vw,68px)] font-bold leading-[1] tracking-[-0.035em]" />
      <Rise delay={0.25} y={16}><p className="mt-5 max-w-[46ch] text-[clamp(16px,1.4vw,19px)] leading-relaxed" style={{ color: "rgba(220,223,229,.8)" }}>{line}</p></Rise>
    </div>
  );
}

/** Renders children on a fixed design canvas and scales it to the available width. */
function Scaled({ w, h, children, className }: { w: number; h: number; children: ReactNode; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [s, setS] = useState(1);
  useEffect(() => {
    const el = ref.current; if (!el) return;
    const ro = new ResizeObserver(([e]) => setS(Math.min(1, e.contentRect.width / w)));
    ro.observe(el); return () => ro.disconnect();
  }, [w]);
  return (
    <div ref={ref} className={`relative w-full ${className ?? ""}`} style={{ height: h * s }}>
      <div className="absolute left-1/2 top-0 origin-top" style={{ width: w, height: h, marginLeft: -w / 2, transform: `scale(${s})` }}>{children}</div>
    </div>
  );
}

function useTyped(text: string, run: boolean, speed = 26) {
  const [n, setN] = useState(0);
  useEffect(() => {
    setN(0); if (!run) return;
    let i = 0;
    const t = setInterval(() => { i++; setN(i); if (i >= text.length) clearInterval(t); }, speed);
    return () => clearInterval(t);
  }, [text, run, speed]);
  return text.slice(0, n);
}

/* ── 2. Start with anything ── */
const INPUTS = [
  { icon: LinkSimple, label: "Link", text: "https://citypost.example/council-votes-to-close-old-bridge" },
  { icon: FilePdf, label: "PDF", text: "council-meeting-minutes.pdf" },
  { icon: TextAa, label: "Your words", text: "The council voted 7 to 2 tonight to close the old bridge for repairs." },
];
const SCRIPT = [
  "Good evening. The old bridge is closing.",
  "Tonight the council voted seven to two to shut it for repairs.",
  "Work starts next month and should take about a year.",
  "Drivers will be sent round by the ring road.",
];

function StartAnything() {
  const box = useRef<HTMLDivElement>(null);
  const seen = useInView(box, { margin: "-120px" });
  const [k, setK] = useState(0);
  const cur = INPUTS[k];
  const typed = useTyped(cur.text, seen, cur.label === "PDF" ? 18 : 24);
  const done = typed.length === cur.text.length;
  useEffect(() => {
    if (!seen || !done) return;
    const t = setTimeout(() => setK((v) => (v + 1) % INPUTS.length), 3600);
    return () => clearTimeout(t);
  }, [seen, done]);

  return (
    <div className="mx-auto flex min-h-[100dvh] w-full max-w-[1240px] flex-col justify-center px-5 py-24">
      <Head title="Start with anything." line="A link, a PDF or your own words. We turn it into a script for your anchor to read." />
      <div ref={box} className="mx-auto mt-14 w-full max-w-[820px]">
        <Rise delay={0.15}>
          <div className="flex justify-center gap-2" role="tablist" aria-label="What you start from">
            {INPUTS.map((t, j) => (
              <button key={t.label} role="tab" aria-selected={j === k} onClick={() => setK(j)}
                className="relative inline-flex h-10 items-center gap-2 rounded-full px-4 text-[14.5px] font-medium transition-colors"
                style={{ color: j === k ? C.ink : C.frost }}>
                {j === k && <motion.span layoutId="start-tab" className="absolute inset-0 rounded-full" style={{ background: C.ice }} transition={{ type: "spring", stiffness: 380, damping: 32 }} />}
                <t.icon size={16} weight="bold" className="relative" /><span className="relative">{t.label}</span>
              </button>
            ))}
          </div>
          <div className="mt-5 flex h-16 items-center gap-3 rounded-[18px] px-5 text-[clamp(14px,1.5vw,18px)]"
            style={{ background: "rgba(20,21,25,.55)", boxShadow: `inset 0 0 0 1.5px ${C.ice}66, 0 20px 60px -20px rgba(200,205,215,.35)` }}>
            <cur.icon size={22} style={{ color: C.ice }} className="shrink-0" />
            <span className="min-w-0 flex-1 truncate" style={{ color: C.text }}>{typed}<span className="ml-px inline-block h-[1.1em] w-[2px] translate-y-[3px] animate-pulse" style={{ background: C.ice }} /></span>
          </div>
        </Rise>
        {/* the script card is always there: it "writes" while the input types, then the lines land */}
        <Rise delay={0.3} className="mt-8" y={30}>
          <div className="rounded-[18px] p-7" style={{ background: "#eeeff2", color: "#0c0d10", boxShadow: "0 40px 80px -30px rgba(0,0,0,.8)" }}>
            <div className="flex items-center justify-between border-b pb-3 text-[13px] font-semibold" style={{ borderColor: "#cfd2d8" }}>
              <span className="flex items-center gap-2">Script
                {!done && <span className="inline-flex items-center gap-1.5 font-medium" style={{ color: "#555a63" }}><span className="size-1.5 animate-pulse rounded-full" style={{ background: C.coral }} />writing</span>}
              </span>
              <span style={{ color: "#555a63" }}>about 0:20 · read by your anchor</span>
            </div>
            <div className="relative mt-4 min-h-[148px] space-y-2.5 text-[clamp(15px,1.6vw,19px)] font-medium leading-snug max-sm:min-h-[260px]">
              <AnimatePresence mode="wait" initial={false}>
                {done ? (
                  <motion.div key={`s${k}`} exit={{ opacity: 0, transition: { duration: 0.25 } }} className="space-y-2.5">
                    {SCRIPT.map((l, j) => (
                      <motion.p key={j} initial={{ opacity: 0, x: -12, filter: "blur(4px)" }} animate={{ opacity: 1, x: 0, filter: "blur(0px)" }} transition={{ duration: 0.6, delay: 0.1 + j * 0.18, ease: EASE }}>{l}</motion.p>
                    ))}
                  </motion.div>
                ) : (
                  <motion.div key="w" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0, transition: { duration: 0.2 } }} className="space-y-4 pt-1" aria-hidden>
                    {[92, 78, 86, 54].map((w, j) => (
                      <span key={j} className="block h-[14px] animate-pulse rounded-full" style={{ width: `${w}%`, background: "#d9dbe0", animationDelay: `${j * 0.15}s` }} />
                    ))}
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          </div>
        </Rise>
      </div>
    </div>
  );
}

/* ── 3. Choose who tells it ── */
function Anchors({ anchors }: { anchors: Anchor[] }) {
  const row = anchors.slice(0, 10);
  return (
    <div className="flex min-h-[100dvh] flex-col justify-center py-24">
      <div className="px-5"><Head title="Choose who tells it." line="Every video starts with a presenter. Tap one to hear their voice." /></div>
      <Rise delay={0.2} className="mt-16">
        <div className="overflow-hidden py-6 [mask-image:linear-gradient(90deg,transparent,#000_8%,#000_92%,transparent)]">
          <ul className="flex w-max gap-6 px-3 animate-[ticker_70s_linear_infinite] hover:[animation-play-state:paused] motion-reduce:animate-none">
            {[...row, ...row].map((a, i) => <AnchorCard key={`${a.id}-${i}`} a={a} copy={i >= row.length} />)}
          </ul>
        </div>
      </Rise>
    </div>
  );
}

// Real anchor, cut out of the studio frame, upscaled, on green screen (scratchpad greenify.py made these).
function AnchorCard({ a, copy }: { a: Anchor; copy: boolean }) {
  const [on, setOn] = useState(false);
  const el = useRef<HTMLAudioElement | null>(null);
  const rx = useSpring(useMotionValue(0), { stiffness: 200, damping: 18 }), ry = useSpring(useMotionValue(0), { stiffness: 200, damping: 18 });
  useEffect(() => () => el.current?.pause(), []);
  function toggle() {
    if (!el.current) { el.current = new Audio(a.voiceSample); el.current.onended = () => setOn(false); }
    if (on) { el.current.pause(); setOn(false); } else { el.current.currentTime = 0; void el.current.play(); setOn(true); }
  }
  function tilt(e: PointerEvent<HTMLButtonElement>) {
    const r = e.currentTarget.getBoundingClientRect();
    ry.set(((e.clientX - r.left) / r.width - 0.5) * 16); rx.set(-((e.clientY - r.top) / r.height - 0.5) * 12);
  }
  return (
    <li className="w-[320px] shrink-0 max-sm:w-[230px]" aria-hidden={copy || undefined}>
      <motion.button onClick={toggle} onPointerMove={tilt} onPointerLeave={() => { rx.set(0); ry.set(0); }} tabIndex={copy ? -1 : 0}
        aria-pressed={on} aria-label={`${on ? "Stop" : "Hear"} ${a.name}`} className="group block w-full text-left"
        style={{ rotateX: rx, rotateY: ry, transformPerspective: 800 }}>
        <div className="relative aspect-[640/736] overflow-hidden rounded-[18px] transition-shadow duration-300"
          style={{ boxShadow: on ? `inset 0 0 0 2px ${C.ice}, 0 0 50px rgba(210,214,222,.45)` : `inset 0 0 0 1.5px ${C.ice}40, 0 30px 60px -30px rgba(0,0,0,.9)` }}>
          <img src={`/landing/anchors/${a.id}.jpg`} onError={(e) => { e.currentTarget.src = a.face; }} alt="" loading="lazy" decoding="async"
            className="size-full object-cover object-top transition-transform duration-700 group-hover:scale-[1.05]" />
          <span className="pointer-events-none absolute inset-0" style={{ background: `linear-gradient(115deg, rgba(255,255,255,.14), transparent 40%), linear-gradient(transparent 50%, ${C.ink}f0)` }} />
          <span className="absolute bottom-4 left-4 right-4 flex items-center gap-3">
            <span className="grid size-10 shrink-0 place-items-center rounded-full transition-transform group-hover:scale-110" style={{ background: on ? C.coral : "rgba(236,238,241,.94)", color: on ? "#fff" : C.ink }}>
              {on ? <Pause size={16} weight="fill" /> : <Play size={16} weight="fill" />}
            </span>
            <span className="min-w-0">
              <span className="block truncate text-[16px] font-semibold">{a.name}</span>
              {on && <span className="mt-1 flex h-3 items-end gap-[3px]" aria-hidden>{[0, 1, 2, 3, 4, 5].map((j) => <motion.span key={j} className="w-[3px] rounded-full" style={{ background: C.ice }} animate={{ height: ["30%", "100%", "45%"] }} transition={{ duration: 0.55, repeat: Infinity, delay: j * 0.08 }} />)}</span>}
            </span>
          </span>
        </div>
      </motion.button>
    </li>
  );
}

/* ── 4. Finale: one frame that straightens as it arrives, takes any headline you type, and ends on the sign-up ── */
const CAPTIONS = ["Severe flooding has forced", "around 4,000 people from their homes,", "officials said on Tuesday."];

function Frame({ title, ticker, captions }: { title: string; ticker?: string[]; captions?: boolean }) {
  const [c, setC] = useState(0);
  useEffect(() => { if (!captions) return; const t = setInterval(() => setC((v) => (v + 1) % CAPTIONS.length), 2200); return () => clearInterval(t); }, [captions]);
  return (
    <div className="relative size-full overflow-hidden rounded-[18px]" style={{ background: C.navy }}>
      <img src="/landing/anchor.jpg" alt="" className="absolute inset-0 size-full object-cover object-[50%_30%]" />
      <div className="absolute right-6 top-6 h-[170px] w-[300px] overflow-hidden rounded-[10px]" style={{ boxShadow: "0 12px 30px rgba(0,0,0,.45)" }}>
        <img src="/landing/footage.jpg" alt="" className="size-full object-cover will-change-transform [animation:kenburns_14s_ease-in-out_infinite_alternate]" />
      </div>
      <span className="absolute left-6 top-6 rounded-[6px] px-2.5 py-1 text-[13px] font-semibold" style={{ background: "rgba(7,7,10,.7)", color: C.frost }}>AI anchor</span>
      {captions && (
        <div className="absolute inset-x-0 bottom-[178px] flex justify-center">
          <AnimatePresence mode="wait">
            <motion.span key={c} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} transition={{ duration: 0.35 }}
              className="rounded-[6px] px-3 py-1 text-[24px] font-semibold text-white" style={{ background: "rgba(0,0,0,.62)" }}>{CAPTIONS[c]}</motion.span>
          </AnimatePresence>
        </div>
      )}
      <GraphicsLayer title={title} ticker={ticker} bottom={60} />
      <div className="absolute inset-x-0 bottom-0 h-[60px]"><VoiceLayer /></div>
    </div>
  );
}

const EXAMPLES = [
  "Local bakery wins best croissant in town",
  "Grandma turns 90, family celebrates",
  "Class 7B takes the science fair",
  "Our startup launches today",
  "City council votes to close the old bridge",
];

function Finale({ go }: { go: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const reduce = useReducedMotion();
  const seen = useInView(ref, { margin: "-160px" });
  const { scrollYProgress: p } = useScroll({ target: ref, offset: ["start end", "center center"] });
  const rotateX = useTransform(p, (v) => (reduce ? 0 : ramp(v, 0, 0.85, 30, 0, easeInOut)));
  const scale = useTransform(p, (v) => (reduce ? 1 : ramp(v, 0, 0.85, 0.84, 1, easeInOut)));

  const [mine, setMine] = useState("");
  const [k, setK] = useState(0);
  const demo = useTyped(EXAMPLES[k], seen && !mine, 34);
  useEffect(() => {
    if (mine || !seen || demo.length < EXAMPLES[k].length) return;
    const t = setTimeout(() => setK((v) => (v + 1) % EXAMPLES.length), 2400);
    return () => clearTimeout(t);
  }, [mine, seen, demo, k]);
  const title = mine.trim() || demo || " ";
  const ticker = mine.trim() ? [mine.trim(), "Made with RIG-Video", "Your story, on camera"] : ["A birthday, a match, a shop opening", "Any story can be the news", "Made with RIG-Video"];
  const frame = <Frame title={title} ticker={ticker} captions />;

  return (
    <div className="mx-auto max-w-[1240px] px-5 pb-28 pt-28">
      <Head title="Make the news about anything." line="A birthday, a match, a shop opening, a school result. Type a headline and watch it go on air." />
      <div ref={ref} data-stop className="mx-auto mt-12 max-w-[960px]" style={{ perspective: 1600 }}>
        <motion.div style={{ rotateX, scale, transformOrigin: "50% 100%" }} className="will-change-transform">
          <Scaled w={960} h={540}>
            <div className="absolute inset-0" style={{ boxShadow: `0 0 0 1.5px ${C.ice}55, 0 50px 120px -40px rgba(200,205,215,.5)`, borderRadius: 18 }}>{frame}</div>
          </Scaled>
        </motion.div>
      </div>
      <Rise delay={0.1} className="mx-auto mt-10 max-w-[720px]">
        <form className="flex flex-col gap-3 sm:flex-row" onSubmit={(e) => e.preventDefault()}>
          <label className="sr-only" htmlFor="any-headline">Your headline</label>
          <input id="any-headline" value={mine} onChange={(e) => setMine(e.target.value.slice(0, 60))} placeholder="Type any headline…" autoComplete="off"
            className="h-14 w-full min-w-0 shrink-0 rounded-full px-6 text-[17px] outline-none placeholder:text-[#8d9199] focus-visible:shadow-[inset_0_0_0_2px_#cfd3da] sm:w-auto sm:flex-1"
            style={{ background: "rgba(20,21,25,.6)", color: C.text, boxShadow: `inset 0 0 0 1.5px ${C.ice}55` }} />
          <Cta to={go} label="Make it a video" className="justify-center" />
        </form>
      </Rise>
      <Words as="h2" inView delay={0.2} text="Your story, told on camera." className="mx-auto mt-28 max-w-[16ch] text-center text-[clamp(36px,5vw,64px)] font-bold leading-[1] tracking-[-0.035em]" />
      <Rise delay={0.5} y={16} className="mt-9 flex justify-center"><Cta to={go} /></Rise>
    </div>
  );
}
