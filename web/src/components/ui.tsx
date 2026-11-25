import { useLocation } from "react-router";
import { forwardRef, type ButtonHTMLAttributes, type ReactNode, type InputHTMLAttributes, type TextareaHTMLAttributes } from "react";
import * as RDialog from "@radix-ui/react-dialog";
import * as RMenu from "@radix-ui/react-dropdown-menu";
import * as RTip from "@radix-ui/react-tooltip";
import * as RSwitch from "@radix-ui/react-switch";
import { AnimatePresence, motion } from "motion/react";
import { X, CheckCircle, WarningCircle } from "@phosphor-icons/react";
import { clsx } from "clsx";
import { twMerge } from "tailwind-merge";
import { useStore } from "@/data/store";

export const cx = (...a: Parameters<typeof clsx>) => twMerge(clsx(...a));

export function mmss(sec: number, tenths = false) {
  const s = Math.max(0, sec);
  const m = Math.floor(s / 60);
  const r = s - m * 60;
  return tenths ? `${m}:${r.toFixed(1).padStart(4, "0")}` : `${m}:${Math.round(r).toString().padStart(2, "0")}`;
}
export const istTime = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: "Asia/Kolkata" }) : "";
export const istDate = (iso: string) =>
  new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "Asia/Kolkata" });

// ------------------------------------------------------------------ buttons

type Kind = "primary" | "secondary" | "ghost" | "quiet" | "danger";
const KIND: Record<Kind, string> = {
  primary: "bg-marker text-white hover:bg-[#f0262e] active:bg-[#c8141b] shadow-[0_1px_0_rgba(255,255,255,0.12)_inset,0_6px_16px_-8px_rgba(0,0,0,0.8)]",
  secondary: "bg-g3 text-g10 border border-g5 hover:bg-g4 hover:border-g6",
  ghost: "text-g9 hover:text-g10 hover:bg-g3",
  quiet: "text-g8 hover:text-g10",
  danger: "text-bad border border-g5 hover:border-bad hover:bg-[#2a1214]",
};
export const Button = forwardRef<HTMLButtonElement, ButtonHTMLAttributes<HTMLButtonElement> & { kind?: Kind; size?: "sm" | "md" | "lg"; icon?: ReactNode }>(
  ({ kind = "secondary", size = "md", icon, className, children, ...rest }, ref) => (
    <button ref={ref} {...rest}
      className={cx(
        "inline-flex select-none items-center justify-center gap-2 rounded-sm font-semibold whitespace-nowrap transition-[background,color,border,transform,box-shadow] duration-150 ease-out active:translate-y-px disabled:pointer-events-none disabled:opacity-40",
        size === "sm" && "h-7 px-2.5 text-[12.5px]", size === "md" && "h-9 px-3.5 text-[13.5px]", size === "lg" && "h-11 px-5 text-[15px]",
        KIND[kind], className)}>
      {icon}{children}
    </button>
  ));

export const IconButton = forwardRef<HTMLButtonElement, ButtonHTMLAttributes<HTMLButtonElement> & { label: string; size?: "sm" | "md"; active?: boolean }>(
  ({ label, size = "md", active, className, children, ...rest }, ref) => (
    <Tip label={label}>
      <button ref={ref} aria-label={label} aria-pressed={active} {...rest}
        className={cx("inline-flex items-center justify-center rounded-sm text-g8 transition-colors duration-150 hover:bg-g4 hover:text-g10 disabled:opacity-40",
          size === "sm" ? "size-7" : "size-9", active && "bg-g4 text-g10", className)}>
        {children}
      </button>
    </Tip>
  ));

// ------------------------------------------------------------------ tooltip

export function Tip({ label, children, side = "top" }: { label: ReactNode; children: ReactNode; side?: "top" | "bottom" | "left" | "right" }) {
  return (
    <RTip.Root delayDuration={350}>
      <RTip.Trigger asChild>{children}</RTip.Trigger>
      <RTip.Portal>
        <RTip.Content side={side} sideOffset={6}
          className="z-50 max-w-[280px] rounded-sm border border-g5 bg-g2 px-2 py-1 text-[12px] text-g10 shadow-[0_8px_24px_-8px_rgba(0,0,0,0.8)] data-[state=delayed-open]:animate-[fadein_120ms_ease-out]">
          {label}
        </RTip.Content>
      </RTip.Portal>
    </RTip.Root>
  );
}
export const TipProvider = RTip.Provider;

// ------------------------------------------------------------------ inputs

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(({ className, ...rest }, ref) => (
  <input ref={ref} {...rest}
    className={cx("h-9 w-full rounded-sm border border-g5 bg-g1 px-3 text-[14px] text-g10 transition-colors duration-150 hover:border-g6 focus:border-g8 focus:outline-none focus-visible:outline-none aria-invalid:border-bad", className)} />
));
export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(({ className, ...rest }, ref) => (
  <textarea ref={ref} {...rest}
    className={cx("w-full resize-none rounded-sm border border-g5 bg-g1 px-3 py-2.5 text-[14px] leading-relaxed text-g10 transition-colors duration-150 hover:border-g6 focus:border-g8 focus:outline-none focus-visible:outline-none", className)} />
));

export function Switch({ on, set, label, hint, id }: { on: boolean; set: (v: boolean) => void; label: string; hint?: string; id: string }) {
  return (
    <div className="flex items-start justify-between gap-6 py-3.5">
      <label htmlFor={id} className="min-w-0 cursor-pointer">
        <div className="font-medium text-g10">{label}</div>
        {hint && <div className="mt-0.5 max-w-[60ch] text-[13px] text-g8">{hint}</div>}
      </label>
      <RSwitch.Root id={id} checked={on} onCheckedChange={set}
        className="relative mt-0.5 h-5 w-9 shrink-0 rounded-full bg-g5 transition-colors duration-200 data-[state=checked]:bg-marker">
        <RSwitch.Thumb className="block size-4 translate-x-0.5 rounded-full bg-g10 shadow transition-transform duration-200 ease-out data-[state=checked]:translate-x-[18px]" />
      </RSwitch.Root>
    </div>
  );
}

/** `off` disables an option and says why in its tooltip. */
export function Segmented<T extends string>({ value, set, options, label, size = "md" }:
  { value: T; set: (v: T) => void; options: { v: T; l: ReactNode; off?: string }[]; label: string; size?: "sm" | "md" }) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex rounded-sm border border-g5 bg-g1 p-0.5">
      {options.map((o) => {
        const on = o.v === value;
        const b = (
          <button key={o.v} role="radio" aria-checked={on} onClick={() => set(o.v)} disabled={!!o.off}
            className={cx("narrow relative shrink-0 rounded-xs font-semibold whitespace-nowrap transition-colors duration-150 disabled:pointer-events-none disabled:opacity-40", size === "sm" ? "h-7 px-2.5 text-[12.5px]" : "h-8 px-3.5 text-[13px]",
              on ? "text-g0" : "text-g8 hover:text-g10")}>
            {on && <motion.span layoutId={`seg-${label}`} className="absolute inset-0 rounded-xs bg-g10" transition={{ type: "spring", duration: 0.32, bounce: 0.12 }} />}
            <span className="relative">{o.l}</span>
          </button>
        );
        return o.off ? <Tip key={o.v} label={o.off}><span className="inline-flex">{b}</span></Tip> : b;
      })}
    </div>
  );
}

/** The three formats as a choice; VO only is portrait, so it says 9:16. A format the server cannot make yet is shown, switched off. */
export const FORMAT_OPTIONS = [
  { v: "anchor_vo" as const, l: "Anchor + VO" },
  { v: "anchor_only" as const, l: "Anchor only" },
  { v: "vo_only" as const, l: <>VO only <span className="ml-0.5 font-mono text-[10.5px] font-medium opacity-70">9:16</span></> },
];
export function useFormatOptions() {
  const can = useStore((s) => s.formats);
  return FORMAT_OPTIONS.map((o) => (can.includes(o.v) ? o : { ...o, off: "VO only opens once the server can write and build it." }));
}

// ------------------------------------------------------------------ chips, tags

export function Tag({ tone = "neutral", children, className }: { tone?: "neutral" | "anchor" | "vo" | "marker" | "ok" | "warn" | "bad" | "edge"; children: ReactNode; className?: string }) {
  const t = {
    neutral: "bg-g4 text-g9", anchor: "bg-anchor/15 text-anchor", vo: "bg-vo/15 text-vo", marker: "bg-marker text-white",
    ok: "bg-ok/15 text-ok", warn: "bg-warn/15 text-warn", bad: "bg-bad/15 text-bad", edge: "bg-edge/12 text-edge",
  }[tone];
  return <span className={cx("inline-flex h-5 shrink-0 items-center gap-1 rounded-xs px-1.5 font-mono text-[10.5px] font-medium tracking-wide whitespace-nowrap uppercase", t, className)}>{children}</span>;
}
export function KindTag({ kind, n }: { kind: "anchor" | "vo"; n?: number }) {
  return <Tag tone={kind}>{kind === "anchor" ? "Anchor" : "VO"}{n ? ` ${n}` : ""}</Tag>;
}

// ------------------------------------------------------------------ measures

export function Ring({ pct, size = 44, label, tone = "marker" }: { pct: number; size?: number; label?: ReactNode; tone?: "marker" | "neutral" }) {
  const r = size / 2 - 3.5; const c = 2 * Math.PI * r;
  return (
    <div className="relative grid shrink-0 place-items-center" style={{ width: size, height: size }} role="progressbar" aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--color-g4)" strokeWidth="3.5" />
        <motion.circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={tone === "marker" ? "var(--color-marker)" : "var(--color-g7)"} strokeWidth="3.5" strokeLinecap="round"
          strokeDasharray={c} initial={false} animate={{ strokeDashoffset: c * (1 - pct / 100) }} transition={{ duration: 0.8, ease: [0.16, 1, 0.3, 1] }} />
      </svg>
      <span className="absolute font-mono text-[11px] font-medium text-edge tabular-nums">{label ?? `${Math.round(pct)}%`}</span>
    </div>
  );
}

export function FillBar({ have, need, className }: { have: number; need: number; className?: string }) {
  const pct = need > 0 ? Math.min(100, (have / need) * 100) : 0;
  const full = have >= need - 0.25;
  return (
    <div className={cx("h-1 overflow-hidden rounded-full bg-g4", className)}>
      <motion.div className={cx("h-full rounded-full", full ? "bg-ok" : "bg-warn")} initial={false} animate={{ width: `${pct}%` }} transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }} />
    </div>
  );
}

/** A duration that flashes its direction for a moment when it changes. */
export function LiveSeconds({ sec, measured, className }: { sec: number; measured?: boolean; className?: string }) {
  return (
    <motion.span key={Math.round(sec * 2)} initial={{ color: "var(--color-g10)" }} animate={{ color: "var(--color-edge)" }} transition={{ duration: 0.9 }}
      className={cx("edge text-[13px]", className)} title={measured ? "Measured from the voice" : "Estimated from the anchor's pace"}>
      {mmss(sec)}{measured ? "" : ""}
    </motion.span>
  );
}

// ------------------------------------------------------------------ dialogs and sheets

export function Dialog({ open, onOpenChange, title, children, wide, bare }:
  { open: boolean; onOpenChange: (v: boolean) => void; title: string; children: ReactNode; wide?: boolean | "full"; bare?: boolean }) {
  return (
    <RDialog.Root open={open} onOpenChange={onOpenChange}>
      <AnimatePresence>
        {open && (
          <RDialog.Portal forceMount>
            <RDialog.Overlay asChild forceMount>
              <motion.div className="fixed inset-0 z-40 bg-black/70 backdrop-blur-[3px]" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.18 }} />
            </RDialog.Overlay>
            <RDialog.Content asChild forceMount aria-describedby={undefined} tabIndex={-1} onOpenAutoFocus={(e) => { e.preventDefault(); (e.currentTarget as HTMLElement).focus(); }}>
              <motion.div
                className={cx("fixed top-1/2 left-1/2 z-50 flex outline-none max-h-[92vh] w-[calc(100vw-32px)] flex-col overflow-hidden rounded-md border border-g5 bg-g1 shadow-[0_30px_80px_-20px_rgba(0,0,0,0.9)]",
                  wide === "full" ? "max-w-[1320px]" : wide ? "max-w-[920px]" : "max-w-[520px]")}
                initial={{ opacity: 0, scale: 0.97, y: "-48%", x: "-50%" }} animate={{ opacity: 1, scale: 1, y: "-50%", x: "-50%" }} exit={{ opacity: 0, scale: 0.98, y: "-49%", x: "-50%" }}
                transition={{ duration: 0.24, ease: [0.16, 1, 0.3, 1] }}>
                {bare ? <RDialog.Title className="sr-only">{title}</RDialog.Title> : (
                  <div className="flex items-center justify-between gap-4 border-b border-g4 px-5 py-3.5">
                    <RDialog.Title className="truncate text-[15px] font-semibold">{title}</RDialog.Title>
                    <RDialog.Close asChild><IconButton label="Close" size="sm"><X size={16} weight="bold" /></IconButton></RDialog.Close>
                  </div>
                )}
                <div className="min-h-0 flex-1 overflow-auto">{children}</div>
              </motion.div>
            </RDialog.Content>
          </RDialog.Portal>
        )}
      </AnimatePresence>
    </RDialog.Root>
  );
}
export const DialogClose = RDialog.Close;

/** Slides in from the right edge; for side work that keeps the page in view. */
export function Sheet({ open, onOpenChange, title, children, width = 440 }: { open: boolean; onOpenChange: (v: boolean) => void; title: string; children: ReactNode; width?: number }) {
  return (
    <RDialog.Root open={open} onOpenChange={onOpenChange}>
      <AnimatePresence>
        {open && (
          <RDialog.Portal forceMount>
            <RDialog.Overlay asChild forceMount>
              <motion.div className="fixed inset-0 z-40 bg-black/50" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.2 }} />
            </RDialog.Overlay>
            <RDialog.Content asChild forceMount aria-describedby={undefined} tabIndex={-1} onOpenAutoFocus={(e) => { e.preventDefault(); (e.currentTarget as HTMLElement).focus(); }}>
              <motion.div className="fixed top-0 right-0 bottom-0 z-50 flex flex-col outline-none border-l border-g5 bg-g1 shadow-[-30px_0_60px_-20px_rgba(0,0,0,0.8)]"
                style={{ width: `min(${width}px, 100vw)` }}
                initial={{ x: "100%" }} animate={{ x: 0 }} exit={{ x: "100%" }} transition={{ duration: 0.32, ease: [0.16, 1, 0.3, 1] }}>
                <div className="flex items-center justify-between gap-4 border-b border-g4 px-5 py-3.5">
                  <RDialog.Title className="text-[15px] font-semibold">{title}</RDialog.Title>
                  <RDialog.Close asChild><IconButton label="Close" size="sm"><X size={16} weight="bold" /></IconButton></RDialog.Close>
                </div>
                <div className="min-h-0 flex-1 overflow-auto">{children}</div>
              </motion.div>
            </RDialog.Content>
          </RDialog.Portal>
        )}
      </AnimatePresence>
    </RDialog.Root>
  );
}

// ------------------------------------------------------------------ menu

export function Menu({ trigger, items, align = "end" }: { trigger: ReactNode; items: ({ label: string; icon?: ReactNode; onSelect: () => void; danger?: boolean; disabled?: boolean } | "sep")[]; align?: "start" | "end" }) {
  return (
    <RMenu.Root>
      <RMenu.Trigger asChild>{trigger}</RMenu.Trigger>
      <RMenu.Portal>
        <RMenu.Content align={align} sideOffset={4}
          className="z-50 min-w-[200px] rounded-sm border border-g5 bg-g2 p-1 shadow-[0_16px_40px_-12px_rgba(0,0,0,0.9)] data-[state=open]:animate-[menuin_140ms_cubic-bezier(0.16,1,0.3,1)]">
          {items.map((it, i) => it === "sep" ? <RMenu.Separator key={i} className="my-1 h-px bg-g4" /> : (
            <RMenu.Item key={it.label} disabled={it.disabled} onSelect={it.onSelect}
              className={cx("flex h-8 cursor-pointer items-center gap-2.5 rounded-xs px-2 text-[13px] outline-none select-none data-disabled:opacity-40 data-highlighted:bg-g4",
                it.danger ? "text-bad" : "text-g10")}>
              <span className="w-4 text-g8">{it.icon}</span>{it.label}
            </RMenu.Item>
          ))}
        </RMenu.Content>
      </RMenu.Portal>
    </RMenu.Root>
  );
}

// ------------------------------------------------------------------ misc

export function Kbd({ children }: { children: ReactNode }) {
  return <kbd className="inline-flex h-5 min-w-5 items-center justify-center rounded-xs border border-g5 bg-g2 px-1 font-mono text-[10.5px] text-g9">{children}</kbd>;
}
export function Skeleton({ className }: { className?: string }) { return <div className={cx("skeleton rounded-sm", className)} />; }

export function Empty({ icon, title, children, action }: { icon: ReactNode; title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center px-6 py-14 text-center">
      <div className="mb-4 text-g8">{icon}</div>
      <div className="text-[15px] font-semibold text-g10">{title}</div>
      {children && <div className="mt-1.5 max-w-[46ch] text-[13.5px] text-g8">{children}</div>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function Toaster() {
  const toasts = useStore((s) => s.toasts);
  // the public landing page never shows app notices (render done, etc.)
  if (useLocation().pathname === "/") return null;
  return (
    <div className="pointer-events-none fixed bottom-5 left-1/2 z-[60] flex -translate-x-1/2 flex-col items-center gap-2" aria-live="polite">
      <AnimatePresence>
        {toasts.map((t) => (
          <motion.div key={t.id} layout initial={{ opacity: 0, y: 14, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 6 }} transition={{ duration: 0.25, ease: [0.16, 1, 0.3, 1] }}
            className="pointer-events-auto flex items-center gap-2.5 rounded-sm border border-g5 bg-g2 py-2.5 pr-4 pl-3 text-[13.5px] shadow-[0_16px_40px_-12px_rgba(0,0,0,0.9)]">
            {t.tone === "bad" ? <WarningCircle size={18} weight="fill" className="text-bad" /> : <CheckCircle size={18} weight="fill" className="text-ok" />}
            {t.text}
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
}
