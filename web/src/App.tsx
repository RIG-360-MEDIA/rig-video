import { lazy, Suspense, useEffect, type ReactNode } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router";
import { AnimatePresence, motion, MotionConfig } from "motion/react";
import { boot, useStore } from "@/data/store";
import { TipProvider, Toaster } from "@/components/ui";
import { AppShell } from "@/components/shell";
const Landing = lazy(() => import("@/pages/Landing"));
const SignIn = lazy(() => import("@/pages/SignIn"));
const Desk = lazy(() => import("@/pages/Desk"));
const ScriptPage = lazy(() => import("@/pages/Script"));
const VisualsPage = lazy(() => import("@/pages/Visuals"));
const ReviewPage = lazy(() => import("@/pages/Review"));
const Library = lazy(() => import("@/pages/Library"));
const Anchors = lazy(() => import("@/pages/Anchors"));
const Settings = lazy(() => import("@/pages/Settings"));
import { StoryFrame } from "@/components/story";

function Page({ children }: { children: ReactNode }) {
  return (
    <motion.div className="min-h-full" initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, transition: { duration: 0.1 } }}
      transition={{ duration: 0.28, ease: [0.16, 1, 0.3, 1] }}>
      {children}
    </motion.div>
  );
}

function Signed({ children }: { children: ReactNode }) {
  const signedIn = useStore((s) => s.signedIn);
  const loc = useLocation();
  if (!signedIn) return <Navigate to="/signin" replace state={{ from: loc.pathname }} />;
  return <AppShell><Suspense fallback={<div className="skeleton mx-auto mt-10 h-1 w-40 rounded-full" />}>{children}</Suspense></AppShell>;
}

export default function App() {
  const ready = useStore((s) => s.ready);
  const loc = useLocation();
  useEffect(() => { void boot(); }, []);
  const top = loc.pathname.split("/").slice(0, loc.pathname.startsWith("/story/") ? 3 : 2).join("/");

  if (!ready) return <div className="grid h-full place-items-center"><div className="skeleton h-1 w-40 rounded-full" /></div>;
  return (
    <MotionConfig reducedMotion="user">
      <TipProvider>
        <Suspense fallback={<div className="grid h-full place-items-center"><div className="skeleton h-1 w-40 rounded-full" /></div>}>
        <AnimatePresence mode="wait">
          <Routes location={loc} key={top}>
            <Route path="/" element={<Page><Landing /></Page>} />
            <Route path="/signin" element={<Page><SignIn /></Page>} />
            <Route path="/desk" element={<Signed><Page><Desk /></Page></Signed>} />
            <Route path="/story/:id" element={<Signed><StoryFrame /></Signed>}>
              <Route path="script" element={<ScriptPage />} />
              <Route path="visuals" element={<VisualsPage />} />
              <Route path="review" element={<ReviewPage />} />
              <Route path="*" element={<Navigate to="script" replace />} />
            </Route>
            <Route path="/library" element={<Signed><Page><Library /></Page></Signed>} />
            <Route path="/anchors" element={<Signed><Page><Anchors /></Page></Signed>} />
            <Route path="/settings" element={<Signed><Page><Settings /></Page></Signed>} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </AnimatePresence>
        </Suspense>
        <Toaster />
      </TipProvider>
    </MotionConfig>
  );
}
