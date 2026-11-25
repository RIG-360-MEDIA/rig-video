// RIG-Video brand pieces shared by the landing page and the sign-in page.
import { motion } from "motion/react";

const C = { coral: "#ff6a4d" };
const S = { fogA: "#1b1c21", fogB: "#33363d", fogC: "rgba(225,228,235,.10)" };

export function Wordmark({ small, big }: { small?: boolean; big?: boolean }) {
  return (
    <span className={`inline-flex items-center gap-2 font-bold tracking-[-0.02em] ${small ? "text-[15px]" : big ? "text-[clamp(44px,5.4vw,76px)]" : "text-[25px]"}`}>
      <svg viewBox="0 0 22 14" className={small ? "h-3" : big ? "h-[0.68em]" : "h-[18px]"} aria-hidden><path d="M6 0h5L5 14H0zM17 0h5l-6 14h-5z" fill={C.coral} /></svg>
      RIG-Video
    </span>
  );
}

/** Slow drifting light behind the layers: three blurred pools that never stop moving. */
export function Fog() {
  return (
    <motion.div aria-hidden className="pointer-events-none absolute inset-0 overflow-hidden" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 1.6, ease: "easeOut" }}>
      <div className="absolute left-1/2 top-[18%] h-[70vh] w-[90vw] -translate-x-1/2 rounded-full will-change-transform [animation:fog-a_22s_ease-in-out_infinite]" style={{ background: `radial-gradient(closest-side, ${S.fogA}, transparent)` }} />
      <div className="absolute left-[30%] top-[42%] h-[48vh] w-[60vw] rounded-full will-change-transform [animation:fog-b_17s_ease-in-out_infinite]" style={{ background: `radial-gradient(closest-side, ${S.fogB}cc, transparent)` }} />
      <div className="absolute left-[45%] top-[30%] h-[36vh] w-[40vw] rounded-full will-change-transform [animation:fog-c_26s_ease-in-out_infinite]" style={{ background: `radial-gradient(closest-side, ${S.fogC}, transparent)` }} />
      <div className="absolute inset-x-0 top-[62%] h-[30vh] will-change-transform [animation:fog-breathe_9s_ease-in-out_infinite]" style={{ background: `radial-gradient(50% 50% at 50% 50%, ${S.fogB}, transparent)` }} />
    </motion.div>
  );
}
