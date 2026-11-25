import type { ReactNode } from "react";
import { Link, NavLink, useLocation, useNavigate } from "react-router";
import { motion } from "motion/react";
import { SignOut, GearSix } from "@phosphor-icons/react";
import { useStore, signOut } from "@/data/store";
import { Menu, Ring, cx } from "./ui";
import { Wordmark } from "./brandmark";

export function Mark({ className }: { className?: string }) {
  return (
    <span className={cx("inline-flex h-[22px] items-center rounded-xs bg-marker px-1.5 font-sans text-[11px] font-black tracking-[0.06em] text-white", className)}
      style={{ fontVariationSettings: '"wdth" 112' }}>DNL</span>
  );
}

export function Brand({ to = "/desk" }: { to?: string }) {
  return (
    <Link to={to} className="flex items-center gap-2.5 rounded-xs">
      <span className="whitespace-nowrap text-g10"><Wordmark small /></span>
    </Link>
  );
}

const NAV = [["/desk", "Desk"], ["/library", "Library"], ["/anchors", "Anchors"], ["/settings", "Settings"]] as const;

export function AppShell({ children }: { children: ReactNode }) {
  const loc = useLocation();
  if (loc.pathname.startsWith("/story/")) return <>{children}</>;
  return (
    <div className="flex min-h-full flex-col">
      <TopBar>
        <nav aria-label="Main" className="flex h-full min-w-0 items-stretch gap-0.5 overflow-x-auto [scrollbar-width:none] sm:gap-1">
          {NAV.map(([to, label]) => (
            <NavLink key={to} to={to} className={({ isActive }) => cx("relative flex shrink-0 items-center px-2.5 text-[13.5px] font-medium transition-colors sm:px-3", isActive ? "text-g10" : "text-g8 hover:text-g10")}>
              {({ isActive }) => <>{label}{isActive && <motion.span layoutId="nav-ul" className="absolute right-3 bottom-0 left-3 h-[2px] bg-marker" transition={{ type: "spring", duration: 0.35, bounce: 0.1 }} />}</>}
            </NavLink>
          ))}
        </nav>
      </TopBar>
      <main className="flex-1">{children}</main>
    </div>
  );
}

export function TopBar({ children, right }: { children?: ReactNode; right?: ReactNode }) {
  return (
    <header className="sticky top-0 z-30 border-b border-g4 bg-g0/90 backdrop-blur-md">
      <div className="mx-auto flex h-13 max-w-[1680px] items-stretch gap-3 px-4 sm:gap-6 sm:px-5">
        <div className="flex items-center"><Brand /></div>
        <div className="flex min-w-0 flex-1 items-stretch">{children}</div>
        <div className="flex shrink-0 items-center gap-2 sm:gap-3">{right}<QueueBadge /><UserMenu /></div>
      </div>
    </header>
  );
}

function QueueBadge() {
  const queue = useStore((s) => s.queue);
  const projects = useStore((s) => s.projects);
  const nav = useNavigate();
  const now = queue[0];
  if (!now) return null;
  return (
    <button onClick={() => nav("/desk")} className="hidden items-center gap-2 sm:flex rounded-sm py-1 pr-2.5 pl-1 text-left transition-colors hover:bg-g3"
      aria-label={`Rendering ${projects[now.projectId]?.headline}, ${now.percent}%`}>
      <Ring pct={now.percent} size={34} label={<span className="text-[11px]">{now.percent}</span>} />
      <span className="hidden text-[12.5px] leading-tight lg:block">
        <span className="flex items-center gap-1.5 font-semibold text-g10"><span className="size-1.5 animate-pulse rounded-full bg-marker" />Rendering</span>
        <span className="text-g8">{queue.length > 1 ? `${queue.length - 1} waiting` : "Queue clear after this"}</span>
      </span>
    </button>
  );
}

function UserMenu() {
  const user = useStore((s) => s.user);
  const nav = useNavigate();
  const initials = (user?.name ?? "?").split(" ").map((x) => x[0]).join("").slice(0, 2);
  return (
    <Menu trigger={
      <button aria-label="Account" className="grid size-8 place-items-center rounded-full bg-g4 text-[12px] font-semibold text-g10 ring-1 ring-g5 transition hover:ring-g7">{initials}</button>
    } items={[
      { label: user?.name ?? "Account", icon: null, onSelect: () => nav("/settings"), disabled: true },
      { label: "Settings", icon: <GearSix size={15} />, onSelect: () => nav("/settings") },
      "sep",
      { label: "Sign out", icon: <SignOut size={15} />, onSelect: () => { signOut(); nav("/"); } },
    ]} />
  );
}
