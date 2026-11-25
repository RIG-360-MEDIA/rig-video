import { useState, type FormEvent } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router";
import { AnimatePresence, motion } from "motion/react";
import { WarningCircle } from "@phosphor-icons/react";
import { signIn } from "@/data/store";
import { Brand } from "@/components/shell";
import { Wordmark } from "@/components/brandmark";
import { Button, Input, Segmented } from "@/components/ui";

export default function SignIn() {
  const [params] = useSearchParams();
  const [mode, setMode] = useState<"in" | "up">(params.get("new") ? "up" : "in");
  // dev only: the development account from .env.development.local (never in a production build)
  const [email, setEmail] = useState<string>(import.meta.env.DEV ? import.meta.env.VITE_DEV_EMAIL ?? "" : "");
  const [password, setPassword] = useState<string>(import.meta.env.DEV ? import.meta.env.VITE_DEV_PASSWORD ?? "" : "");
  const [name, setName] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const nav = useNavigate();
  const loc = useLocation();
  const from = (loc.state as { from?: string } | null)?.from ?? "/desk";

  function submit(e: FormEvent) {
    e.preventDefault();
    setErr(null);
    if (mode === "up") { setErr("Sign-up is not open yet. For now, ask us for an account."); return; }
    if (!email.trim() || !password) { setErr("Enter your email and password."); return; }
    setBusy(true);
    void signIn(email, password).then((bad) => {
      setBusy(false);
      if (bad) setErr(bad); else nav(from, { replace: true });
    });
  }

  return (
    <div className="grid grid-cols-1 min-h-[100dvh] lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
      <div className="flex flex-col px-6 py-6 sm:px-10">
        <Brand to="/" />
        <div className="mx-auto flex w-full max-w-[380px] flex-1 flex-col justify-center py-12">
          <h1 className="text-[28px] font-semibold tracking-[-0.02em]">{mode === "in" ? "Sign in" : "Make an account"}</h1>
          <p className="mt-1.5 text-g8">{mode === "in" ? "Pick up where you left off." : "Anyone can sign up once the studio goes live."}</p>
          <div className="mt-6"><Segmented label="Account" value={mode} set={(v) => { setMode(v); setErr(null); }} options={[{ v: "in", l: "Sign in" }, { v: "up", l: "Sign up" }]} /></div>
          <form onSubmit={submit} className="mt-6 space-y-4" noValidate>
            <AnimatePresence initial={false}>
              {mode === "up" && (
                <motion.label key="name" initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="block overflow-hidden">
                  <span className="mb-1.5 block text-[13px] font-medium text-g9">Name</span>
                  <Input value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" />
                </motion.label>
              )}
            </AnimatePresence>
            <label className="block">
              <span className="mb-1.5 block text-[13px] font-medium text-g9">Email</span>
              <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" aria-invalid={!!err} autoFocus />
            </label>
            <label className="block">
              <span className="mb-1.5 flex justify-between text-[13px] font-medium text-g9">Password{mode === "in" && <span className="font-normal text-g8">Forgot it? Ask your admin.</span>}</span>
              <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete={mode === "in" ? "current-password" : "new-password"} aria-invalid={!!err} />
            </label>
            <AnimatePresence>
              {err && (
                <motion.p role="alert" initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="flex items-start gap-2 text-[13px] text-bad">
                  <WarningCircle size={16} weight="fill" className="mt-px shrink-0" />{err}
                </motion.p>
              )}
            </AnimatePresence>
            <Button kind="primary" size="lg" type="submit" className="w-full" disabled={busy}>{busy ? "Signing in…" : mode === "in" ? "Sign in" : "Make my account"}</Button>
          </form>
        </div>
        <Link to="/" className="text-[12.5px] text-g8 hover:text-g10">Back to the start</Link>
      </div>
      <BrandPanel />
    </div>
  );
}

/** The brand, plain: wordmark and caption on the page background. */
function BrandPanel() {
  return (
    <div className="hidden lg:flex lg:flex-col lg:items-center lg:justify-center">
      <Wordmark big />
      <p className="mt-9 text-[26px] leading-tight font-semibold tracking-[-0.02em] text-[#eceef1]">One story in. A news video out.</p>
    </div>
  );
}
