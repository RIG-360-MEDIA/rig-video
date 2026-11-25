# Anchor Registry — AUTHORITATIVE (10 anchors, seeds + locked voices)

**This is the single source of truth for the finalized roster.** It consolidates the anchor↔video↔voice
mapping that was previously scattered across `ANCHOR_ROSTER_SEEDS.md` (planning), `ANCHOR_VOICE_LOCK.md`
(partial), `SESSION_HANDOFF.md`, and the trijya box. Built 2026-09-15 by identifying each Downloads video
frame-by-frame against the roster and pulling the locked voice files from the trijya box (`trijya-7`,
`100.72.225.89`, `~/anchor-studio/repos/ComfyUI/input/`).

All assets live in this folder:
- `videos/<name>.mp4` — the anchor's seed/identity clip (renamed from Downloads `male1-5.mp4` / `female1-5.mp4`)
- `voices/<name>__<voiceid>.wav` — the anchor's **permanently locked** voice reference
- `frames/<name>.png` — a representative frame (for `ref_images.ref_image_0` in standalone jobs)

> **VOICE LOCK RULE (unchanged):** once locked, an anchor's voice is theirs forever. Never reassign, even
> for a "better" reference, without an explicit user instruction to replace it.

---

## The roster

| # | Anchor | Gender | Ethnicity | Desk | Seed video | Ref frame | **Locked voice** |
|---|---|---|---|---|---|---|---|
| 1 | **Maren Ashcroft** | M | White / light-skinned | World | `videos/maren_ashcroft.mp4` (17.9s) | `frames/maren_ashcroft.png` | `voices/maren_ashcroft__newsanchor_ref.wav` |
| 2 | **Desmond Okafor** | M | Black / West African | National | `videos/desmond_okafor.mp4` (9.4s) | `frames/desmond_okafor.png` | `voices/desmond_okafor__connery.wav` |
| 3 | **Emre Yildiz** | M | Turkish | (Middle East/foreign) | `videos/emre_yildiz.mp4` (9.4s) | `frames/emre_yildiz.png` | `voices/emre_yildiz__mirac.wav` |
| 4 | **Mateo Reyes** | M | Latino / Mexican-American | Weekend | `videos/mateo_reyes.mp4` | `frames/mateo_reyes.png` | `voices/mateo_reyes__jones.wav` |
| 5 | **Arjun Malhotra** | M | South Asian / Indian | Business | `videos/arjun_malhotra.mp4` | `frames/arjun_malhotra.png` | `voices/arjun_malhotra__ishaan.wav` |
| 6 | **Simone Baptiste** | F | Black / Caribbean-American | Breaking News | `videos/simone_baptiste.mp4` | `frames/simone_baptiste.png` | `voices/simone_baptiste__h3default.wav` (extracted 2026-10-03 from her approved clip `female1.mp4` = `videos/simone_baptiste.mp4`, same SHA) |
| 7 | **Priya Nair** | F | South Asian / Indian | Health | `videos/priya_nair.mp4` (15.1s) | `frames/priya_nair.png` | `voices/priya_nair__tara.wav` (`priya_ref_padded.wav`) |
| 8 | **Chloe Whitfield** | F | White | (general) | `videos/chloe_whitfield.mp4` | `frames/chloe_whitfield.png` | `voices/chloe_whitfield__milly.wav` (`milly_original.wav`) |
| 9 | **Eleanor Marsh** | F | White | (foreign affairs) | `videos/eleanor_marsh.mp4` (9.4s) | `frames/eleanor_marsh.png` | `voices/eleanor_marsh__lia.wav` (`lia_ref_padded.wav`) |
| 10 | **Yuna Cho** | F | East Asian / Korean | Morning | `videos/yuna_cho.mp4` | `frames/yuna_cho.png` | `voices/yuna_cho__sarah.wav` (`sarah_report_padded.wav`) |

**Not in the final roster:** *Layla Haddad (Middle Eastern/Lebanese)* and *Camila Torres (Latina/Colombian)*
appear in `ANCHOR_ROSTER_SEEDS.md` as **planning-only** entries — they were never generated and have no
video or voice. Do not assign stories to them. For a Middle-East-region story, **Emre Yildiz (Turkish)** is
the closest available fit.

## How each video maps to the Downloads originals
`male1`=Maren, `male2`=Desmond, `male3`=Emre, `male4`=Mateo, `male5`=Arjun;
`female1`=Simone, `female2`=Priya, `female3`=Chloe, `female4`=Eleanor, `female5`=Yuna.
(Identified by frame — tie/wardrobe/skin-tone matched to each roster prompt; White females disambiguated
against trijya's named `chloe_ref_frame.png` / `eleanor_ref_frame.png` / `yuna_ref_frame.png`.)

## Voice mechanism notes
- Production carries the voice with `generated_audio` + the locked wav as `ref_audios.ref_audio_0` (flat dotted key; a
  nested dict is silently dropped) on the **seed only**; the chain inherits it with no `ref_audio` (seam lock).
  `source_track` is not used in production (see `baseline/HANDOFF.md` §7).
- Simone's voice was H3's own default voice; on 2026-10-03 (user instruction) it was locked by extracting the audio of her
  approved clip (`female1.mp4`, mono 44.1 kHz s16). Resemblyzer vs other roster voices: max 0.767 (Chloe) — distinct.
- `registry.json` = machine-readable roster with SHA-256 of every voice + frame (used by the daily system's hash check).
- The `__<voiceid>` suffix on each wav names the original source voice (connery, ishaan, mirac, jones, tara,
  milly, lia, sarah). The un-suffixed copies (`connery.wav`, etc.) are kept alongside for direct pipeline use.

## Building a job for an anchor
1. Pick the anchor's row → use `videos/<name>.mp4` as the chain seed (or extract from it) and
   `voices/<name>__*.wav` as the locked voice (`ref_audios.ref_audio_0` / `source_track`).
2. Physical-description prompt blocks (if regenerating an identity from scratch) are in
   `baseline/ANCHOR_ROSTER_SEEDS.md`.
3. Full pipeline + graph: `baseline/PIPELINE_ARCHITECTURE.md`; box setup: `baseline/VAST_BOX_SETUP.md`.

## Verification 2026-10-03 (anchor ↔ voice ↔ face)
- **Voice files are a clean bijection.** 10 distinct files, and the closest pair (Simone vs Chloe) scores 0.767 on
  Resemblyzer. All 9 older files on trijya `input/` match the registry SHA-256 exactly. All 10 are uploaded under
  their registry names, with identity frames as `anchor_id_<id>.png`.
- **Each identity video's audio was compared with all 10 voice files.** 8 of the 10 match their own locked voice
  best (0.88–0.95). Two do not:
  - *Maren:* the video audio is closest to Desmond/connery (0.76; own 0.71).
  - *Priya:* the video audio is closest to Simone's H3-default voice (0.90; own 0.79).

  Those two clips were rendered without their reference voice taking effect (the dropped `ref_audios` key bug).
  The **locked voice files remain the authority.** The clips are used only for face identity.
- **Faces (OpenCV SFace).** The same anchor across their own video scores 0.78–0.96. Different anchors score at
  most 0.64 (Mateo vs Arjun). The QC identity gate is set at 0.72, and it also requires the closest roster face to be
  the anchor's own.
- **The anchor in our image-7 renders is NOT registry Emre** (0.34–0.49 vs his frame). The text-only seed invents a
  similar man. This is why every anchor now gets an identity-pinned seed (`<Picture 2>` = their frame) and a
  one-time onboarding approval before the daily system may cast them (`status: ready`).
