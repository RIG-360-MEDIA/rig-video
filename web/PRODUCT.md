# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

React 19 + Vite + TypeScript + Tailwind CSS 4 + shadcn/ui (Radix). Chosen by the user (2026-11-10). Planned building blocks: dnd-kit (drag reorder), wavesurfer.js (voice takes), Video.js 10 or media-chrome (player). The backend is a separate FastAPI service; this frontend runs on seed fixtures (`public/seed/`, shapes in `src/data/types.ts`) until the user says to connect it.

## Users

Changed 2026-11-11: an external audience. Two groups: small newsrooms (local and digital publishers who want video versions of their stories without a studio or presenter) and the broad public (anyone with a story to tell: creators, organisations, individuals). Most visitors arrive knowing nothing about broadcast production. They work at a desktop to make videos; they may first meet the product on a phone. DNL itself is one customer among many.

## Product Purpose

RIG-Video takes a story (a link, an uploaded document or PDF, or typed text) and produces a finished news video: an AI anchor on camera reading a script, voiceover over real footage and photos, lower thirds, ticker and logo. The maker stays in control of every decision that matters (script, anchor, pictures, voice) while the slow work (writing, footage search, voice, rendering) runs in the background. Success: a correct, broadcast-quality video with the least of the maker's time.

## Positioning

An end-to-end newsroom tool, not a general video editor: source in, script out, timed to the second against the chosen anchor's real speaking pace; footage found per script section by a newsroom footage search that returns timestamped moments with fit scores; the voice made and approved before any GPU render; a shared render queue with automatic lip-sync checks.

## Operating Context

- Flow: Desk → Script → Visuals → Review → Render queue → Library.
- Script: "anchor only" or "anchor + VO" (both versions kept), sections reorderable, live duration per section and total vs target length, lower third under each anchor part and ticker lines written with the script, facts from the source editable, AI rewrite (whole or one section) asking what to change, the anchor chosen here.
- After the script is approved the full voice is made on the GPU and the footage search runs, in parallel.
- Visuals: per section the keywords (editable, re-search), found videos with fit scores and timestamped moments, photos, the user's uploads, our own maps; mosaic and by-source views; drag to set play order; trims; clips with a logo, text, presenter or portrait video are shown original next to the one treatment we would apply. Continue is locked until every section is filled.
- Review: playable rough preview (real voice over the chosen pictures, no GPU), per part listen and say what to change (only that part is re-voiced), last edit of lower thirds and ticker, then Render.
- One shared GPU render queue; the Desk shows progress rings with percent and ETA (IST). Automatic lip check; a story is held for the editor only when it still fails.
- Library: every finished video (studio and the daily automated system), mosaic player for now; a full editor view and natural sound (foley) come later.
- Times are shown in IST.

## Capabilities and Constraints

- Desktop first (1280 px and up); phones only need the Desk and Library.
- Length is free text (default 1:00), confirm above 5 minutes, no cap.
- Local LLM is the primary language model, not Groq.
- Footage search is RIG's footage repo (social_verifier), run from our own code.
- Video rules apply to the output (no image shake, never drop vertical/logo clips, join then graphics).
- Development uses one admin account created for development; public sign-up is the landing page's action. Roles: admin and editor; workspaces (DNL gets the daily picks feed).
- Undecided: pricing.

## Brand Commitments

- Name: "RIG-Video" (from RIG 360 Media), decided 2026-11-11; it replaces "Anchor Studio by DNL".
- Landing palette the user chose: ink black ground, ice blue, coral.
- Anchors are a fixed roster with fixed voices (anchor registry).
- Dark interface is the user's binding choice.
- Landing page: sign-up first is the primary action. No invented customers, testimonials or usage numbers.

## Evidence on Hand

Real seed material in `~/studio-seed/raw` (from t8 `~/ndc-archive`): the footage repo database with 30 projects, 430 scored videos with moments and 48 cut clips (Moscow drone attack, Russia 616 drones); two studio projects (Moscow, Lipetsk) with scripts, lower thirds, facts, shots and voice takes; the DNL daily selection of 27 Oct 2026; 11 anchors with faces, studio frames and voices; finished videos (SGE 2 Global Strategic Assessment). No testimonials, customers or usage numbers exist; none may be invented.

## Product Principles

1. The editor decides, the system does the slow work: every long step runs in the background while the editor keeps working.
2. Time is the unit: every part shows its seconds, and the whole always shows how it compares with the target.
3. Nothing is hidden: footage with logos, text or portrait framing is shown with how it will be treated; the editor can keep the original.
4. Check before spending GPU: script, pictures and voice are all approved before a render starts.
5. One clear next step per screen; what needs the editor is always visible on the Desk.

## Accessibility & Inclusion

WCAG 2.1 AA contrast on the dark theme, full keyboard operation (timeline, drag reorder alternatives), visible focus, reduced-motion support.
