---
name: RIG-Video (formerly Anchor Studio by DNL)
description: Contact Sheet. A newsroom video desk where every story is a roll of film, picks are marked in red china marker and every measurement is edge print.
colors:
  g0: "#0a0b0d"
  g1: "#0f1115"
  g2: "#14171c"
  g3: "#1a1e24"
  g4: "#22272f"
  g5: "#2c323b"
  g6: "#3b424d"
  g7: "#58606c"
  g8: "#848c98"
  g9: "#b3b9c2"
  g10: "#e8eaee"
  sheet: "#060607"
  marker: "#e31b23"
  marker-hover: "#f0262e"
  marker-press: "#c8141b"
  marker-ink: "#ff5b61"
  edge: "#df9a4c"
  anchor: "#ab9cff"
  vo: "#5fb3ea"
  ok: "#4dc48c"
  warn: "#f2c14e"
  bad: "#ff5b61"
typography:
  display:
    fontFamily: "Archivo Variable, Helvetica Neue, Arial, sans-serif"
    fontSize: "64px"
    fontWeight: 700
    lineHeight: 1.02
    letterSpacing: "-0.035em"
    fontVariation: "\"wdth\" 92"
  headline:
    fontFamily: "Archivo Variable, Helvetica Neue, Arial, sans-serif"
    fontSize: "26px"
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: "-0.02em"
  subhead:
    fontFamily: "Archivo Variable, Helvetica Neue, Arial, sans-serif"
    fontSize: "19px"
    fontWeight: 600
    lineHeight: 1.3
    letterSpacing: "-0.01em"
  section:
    fontFamily: "Archivo Variable, Helvetica Neue, Arial, sans-serif"
    fontSize: "17px"
    fontWeight: 600
    lineHeight: 1.3
    letterSpacing: "-0.01em"
  title:
    fontFamily: "Archivo Variable, Helvetica Neue, Arial, sans-serif"
    fontSize: "15px"
    fontWeight: 600
    lineHeight: 1.35
    letterSpacing: "-0.01em"
  lede:
    fontFamily: "Archivo Variable, Helvetica Neue, Arial, sans-serif"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.5
  body:
    fontFamily: "Archivo Variable, Helvetica Neue, Arial, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.45
    fontVariation: "\"wdth\" 100"
  body-sm:
    fontFamily: "Archivo Variable, Helvetica Neue, Arial, sans-serif"
    fontSize: "12.5px"
    fontWeight: 400
    lineHeight: 1.4
  label-narrow:
    fontFamily: "Archivo Variable, Helvetica Neue, Arial, sans-serif"
    fontSize: "13px"
    fontWeight: 600
    lineHeight: 1.2
    fontVariation: "\"wdth\" 84"
  edge-print:
    fontFamily: "JetBrains Mono Variable, ui-monospace, Menlo, monospace"
    fontSize: "11.5px"
    fontWeight: 400
    lineHeight: 1.2
    letterSpacing: "0.02em"
    fontFeature: "\"tnum\" 1"
  tag:
    fontFamily: "JetBrains Mono Variable, ui-monospace, Menlo, monospace"
    fontSize: "10.5px"
    fontWeight: 500
    lineHeight: 1
    letterSpacing: "0.025em"
  marker-numeral:
    fontFamily: "Caveat Brush, Marker Felt, cursive"
    fontSize: "42px"
    fontWeight: 400
    lineHeight: 1
rounded:
  xs: "2px"
  sm: "3px"
  md: "5px"
  full: "9999px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "20px"
  2xl: "32px"
components:
  button-primary:
    backgroundColor: "{colors.marker}"
    textColor: "#ffffff"
    typography: "{typography.label-narrow}"
    rounded: "{rounded.sm}"
    padding: "0 14px"
    height: "36px"
  button-primary-hover:
    backgroundColor: "{colors.marker-hover}"
  button-primary-active:
    backgroundColor: "{colors.marker-press}"
  button-secondary:
    backgroundColor: "{colors.g3}"
    textColor: "{colors.g10}"
    rounded: "{rounded.sm}"
    padding: "0 14px"
    height: "36px"
  button-secondary-hover:
    backgroundColor: "{colors.g4}"
  button-ghost:
    textColor: "{colors.g9}"
    rounded: "{rounded.sm}"
    padding: "0 14px"
    height: "36px"
  button-ghost-hover:
    backgroundColor: "{colors.g3}"
    textColor: "{colors.g10}"
  input:
    backgroundColor: "{colors.g1}"
    textColor: "{colors.g10}"
    typography: "{typography.body}"
    rounded: "{rounded.sm}"
    padding: "0 12px"
    height: "36px"
  card:
    backgroundColor: "{colors.g1}"
    rounded: "{rounded.md}"
    padding: "16px"
  contact-sheet:
    backgroundColor: "{colors.sheet}"
    rounded: "{rounded.md}"
    padding: "16px"
  frame:
    backgroundColor: "{colors.g3}"
    rounded: "{rounded.xs}"
  tag-neutral:
    backgroundColor: "{colors.g4}"
    textColor: "{colors.g9}"
    typography: "{typography.tag}"
    rounded: "{rounded.xs}"
    padding: "0 6px"
    height: "20px"
  tag-marker:
    backgroundColor: "{colors.marker}"
    textColor: "#ffffff"
    typography: "{typography.tag}"
    rounded: "{rounded.xs}"
    padding: "0 6px"
    height: "20px"
  segmented-on:
    backgroundColor: "{colors.g10}"
    textColor: "{colors.g0}"
    typography: "{typography.label-narrow}"
    rounded: "{rounded.xs}"
    height: "32px"
---

# Design System: RIG-Video (formerly Anchor Studio by DNL)

## Overview

**Creative North Star: "The Contact Sheet"**

Every story is a roll of film. The editor works on film-rebate black, looks at found footage laid out as frames on a darker sheet, marks the ones to use with a red china-marker loop and a hand-written play-order numeral, and reads every time, code and count as amber edge print. The interface is dense and desktop-first (1280 px and up), a working instrument for several stories a day, not a showcase.

One graphite ramp of eleven slightly blue steps carries every neutral: grounds, surfaces, hairline seams and text. Colour is spent on meaning only. DNL red is selection, the primary action and on-air; amber is measurement; violet and steel blue tell anchor parts from voiceover parts; green, yellow and red-pink report state. One workhorse sans (Archivo) does everything, using its width axis for condensed labels, and JetBrains Mono prints the edge numbers.

The world borrows the contact sheet's logic, not its costume: no sprocket holes, film grain or imitation stock. Depth comes from tonal steps and hairlines; shadows are neutral and only lift floating layers. Motion is short expo ease-out, and the signature loop draws in 220 ms.

**Key Characteristics:**
- Film-rebate black ground with an eleven-step graphite ramp.
- Amber mono edge print for every measurement: frame codes (R02·F01a), timecodes, durations, counts.
- DNL red as the china marker: picked frames, primary action, on-air, active nav.
- Hairline seams and tight 2 to 5 px corners.
- Archivo for words (width axis for condensed labels), JetBrains Mono for numbers, Caveat Brush only for picked numerals.
- Expo ease-out motion; the signature loop has no spring.

## Colors

A near-black graphite world where colour always means something: red marks, amber measures, violet and blue tell part kinds apart.

### Primary
- **China-Marker Red** (marker): DNL's own red. The primary button, the selected-frame loop and numerals, the active nav underline, on-air and rendering dots, the caret, focus outlines, progress rings and category tags. Hover and press steps (marker-hover, marker-press) exist only for the primary button.
- **Marker Ink** (marker-ink): a lighter red for small red text on black, where full marker red fails contrast.

### Secondary
- **Edge-Print Amber** (edge): every measurement. Frame codes, timecodes, durations against target, counts beside headings and tabs, the contact-sheet count line, trim fields. Also the moment marks inside a source-video strip.

### Tertiary
- **Anchor Violet** (anchor): on-camera anchor parts (kind tags, part icons).
- **Voiceover Blue** (vo): voiceover parts (kind tags, mic icons, unmuted clip sound).

### Neutral
- **Rebate Black** (g0): the page ground, top bars at 90% over a blur, and the stroke around marker numerals.
- **Sheet Black** (sheet): the contact-sheet panel only, one step darker than the ground so the frames read as laid on a lightbox's opposite.
- **Graphite 1 to 3** (g1, g2, g3): surfaces. Cards, inputs, dialogs and sheets sit on g1; menus, tooltips and toasts on g2; secondary buttons and empty frames on g3.
- **Graphite 4 to 6** (g4, g5, g6): seams. g4 is the hairline between regions and the default card border; g5 is the control border; g6 is the hover border and scrollbar thumb.
- **Graphite 7** (g7): placeholders, disabled and unreached states, neutral rings. Never readable text.
- **Graphite 8** (g8): the lowest text step. Secondary text, hints, inactive nav, captions.
- **Graphite 9 and 10** (g9, g10): body-secondary and primary text. g10 is also the fill of the "on" segment in segmented controls and the step track.
- **State** (ok, warn, bad): filled section bars are ok, short sections warn, errors and destructive actions bad. Tags use them at 15% fill with full-strength text.

### Named Rules
**The Meaning-Only Rule.** No colour is decorative. If a hue appears, it is marking a pick, a measurement, a part kind or a state.

**The g8 Floor Rule.** Graphite 8 is the lowest step that may carry text; every text must meet WCAG AA. Graphite 7 and darker are for borders, placeholders and disabled states only.

**The Edge-Print Rule.** Every measurement (time, code, count, percent of a target) is set in mono, tabular, in edge-print amber.

## Typography

**Display Font:** Archivo Variable (with Helvetica Neue, Arial)
**Body Font:** Archivo Variable (with Helvetica Neue, Arial)
**Label/Mono Font:** JetBrains Mono Variable (with ui-monospace, Menlo)
**Marker Font:** Caveat Brush (with Marker Felt), picked numerals only

**Character:** One grotesque does all the talking and stretches or squeezes on its width axis instead of changing family; the mono is the film's edge print, never prose.

### Hierarchy
- **Display** (700, width 92, tight negative tracking): landing only, stepping with the viewport. The hero runs 44 px, 56 px at sm and 64 px at lg; the closing heading 40 px, 52 px at sm; landing section heads 34 px, 40 px at sm.
- **Headline** (600, 26 px, tracking -0.02em): page titles (Desk, Library, Anchors, Settings); the Sign in heading runs at 28 px.
- **Subhead** (600, 19 px): the current part title in Visuals and the anchor name in the Anchors detail. The Script total runtime prints at the same size as edge print.
- **Section** (600, 17 px): section headings inside a page (Today's picks, In progress, Start a new video, Listen to each part); the landing hero lede also sits at 17 px.
- **Title** (600, 15 px): dialog, sheet, panel and empty-state titles.
- **Lede** (400, 16 px): landing section body under a section head, capped at 60 ch.
- **Body** (400, 14 px, 1.45): the default. Script text and hints cap near 60 ch.
- **Body small** (400, 12.5 to 13.5 px): list rows, captions, meta. 12 px is the floor for any running text.
- **Label narrow** (600, 13 to 13.5 px, width 84): condensed labels in the step track, segmented controls, source tabs and rail titles.
- **Edge print** (mono, 11 to 12.5 px, tabular, +0.02em, amber): measurements, including ring percentages and frame durations over pictures (on a 70% black chip).
- **Tag** (mono 500, 10.5 px, uppercase, wide tracking): status and category chips.

### Named Rules
**The Narrow Rule.** The condensed width (84%) is for labels that sit in tracks and rails: step track, segmented controls, tabs, rail titles. Body and headings stay at normal width.

**The Bare Numeral Rule.** Caveat Brush appears only as play-order numerals on picked frames and in the picked list. It is written bare in marker red with a ground-coloured stroke (6 px of g0, painted under the fill), never inside a disc or badge.

**The No-Kicker Rule.** Nothing sits above a heading: no eyebrow, no kicker. Category and status tags go in a meta row below the title.

## Layout

A full-bleed working desk, centred at a 1680 px maximum with 20 px side padding (16 px on phones). Pages open 32 px below the bar. The top bar is 52 px, sticky, with the DNL mark and product name at left, nav or breadcrumb plus step track in the middle and right, and the render-queue ring and account at the far right.

The Visuals step is the canonical three-column workspace at 1024 px and up: a 232 px parts rail, a fluid centre, a 340 px picked list, each column scrolling independently inside the viewport height. Below 1024 px the columns stack. The Desk uses a two-column grid of pick cards (three at 1536 px) beside a right column for the queue and "needs you" list.

Spacing runs on a 4 px base: 12 px between cards in a grid, 16 px inside cards, 14 px vertical in list rows, 20 px on panel headers and footers.

**The Proportional Rail Rule.** In the parts rail, each part's height is its seconds: 7 px per second, with a 44 px floor. Short parts drop their text snippet rather than break the proportion.

**The Contact Sheet Rule.** Found frames sit on the sheet-black panel (5 px corners, a g4 hairline ring, 16 px inside) headed by one mono amber, uppercase count line: roll, videos, frames, picked, seconds of target.

## Elevation & Depth

The system is flat and tonal at rest: depth is the graphite step a surface sits on plus its hairline. Shadows appear only on layers that float above the page (dialogs, sheets, menus, tooltips, toasts, a dragged pick) and are always black, long and soft, with negative spread so they read as a lift rather than a halo. The primary button carries a 1 px inner highlight and a tight dark under-shadow.

### Shadow Vocabulary
- **Tooltip** (`0 8px 24px -8px rgba(0,0,0,0.8)`): tooltips.
- **Float** (`0 16px 40px -12px rgba(0,0,0,0.9)`): menus and toasts.
- **Dialog** (`0 30px 80px -20px rgba(0,0,0,0.9)`): centred dialogs, over a 70% black backdrop with a 3 px blur.
- **Sheet** (`-30px 0 60px -20px rgba(0,0,0,0.8)`): the right-edge sheet, over a 50% black backdrop.
- **Primary press** (`0 1px 0 rgba(255,255,255,0.12) inset, 0 6px 16px -8px rgba(0,0,0,0.8)`): the primary button only.

### Named Rules
**The Neutral Shadow Rule.** Shadows are black. No coloured glows.

**The Tonal-First Rule.** A surface earns separation by stepping up the graphite ramp and taking a hairline, not by casting a shadow.

## Shapes

Corners are tight, like trimmed prints: 2 px on frames, tags, segments and keys; 3 px on buttons, inputs, menus and tooltips; 5 px on cards, panels, dialogs and the contact sheet. Fully round is reserved for things that are round by nature: switches, progress rings and fill bars, avatar, the hover "use" button on a frame, keyword pills. Borders are 1 px hairlines; dashed borders mark drop zones, empty states, add-keyword fields and locked gates. A drop zone with a file over it turns its border marker red over a 5% red tint, with no halo. Frames are 16:9.

**The No-Costume Rule.** No imitation film material: no sprocket holes, perforations, grain, light leaks or rebate lettering. The contact sheet is a layout idea, not a texture.

## Components

### Buttons
Compact and solid, with a 1 px press-down on active.
- **Shape:** gently squared (3 px). Heights 28, 36 and 44 px; 600 weight.
- **Primary:** marker red with white text. One per view, for the move forward (Write the script, Continue, Render).
- **Secondary:** g3 with a g5 border, lifting to g4 and g6 on hover. The default.
- **Ghost / Quiet:** text only (g9 / g8), gaining g3 or full text on hover.
- **Danger:** bad-coloured text on a g5 border, the border turning bad on hover.
- **Icon button:** 28 or 36 px square, g8 icon, g4 fill when hovered or active; always carries a tooltip with its label.
- **Disabled:** 40% opacity. A locked gate (Continue in Visuals) is a dashed box that names what is still missing.

### Chips (Tags)
- **Style:** 20 px high, 2 px corners, mono uppercase 10.5 px. Tones: neutral (g4 / g9), anchor, vo, ok, warn, bad and edge at a 12 to 15% tint with full-strength text; marker is solid red with white text and is used for news categories (WAR, DEMOCRACY).
- **Over pictures:** tags on a frame sit on 70 to 75% black.

### Cards / Containers
- **Corner Style:** 5 px.
- **Background:** g1 on the g0 ground; footer strips on g2 at 60%.
- **Shadow Strategy:** none at rest (see Elevation).
- **Border:** g4 hairline, g6 on hover for clickable cards.
- **Internal Padding:** 16 px; list rows 16 by 14 px.

### Inputs / Fields
- **Style:** 36 px, g1 fill, g5 hairline, 3 px corners, 14 px text, red caret.
- **Focus:** the border steps to g8; no glow. Keyboard focus elsewhere is a 2 px marker-red outline offset 2 px.
- **Error / Disabled:** border turns bad; disabled at 40%. Trim fields print their numbers in edge amber on g0.

### Navigation
- **Top bar:** 13.5 px medium links, g8 at rest, g10 when active, with a 2 px marker-red underline that slides between links.
- **Step track:** inside a g1 well with a g4 hairline; condensed 13 px labels with a mono step number; the current step is a g10 fill with g0 text, finished steps show a green check, unreached steps are g6 and explain their lock in a tooltip.
- **Mobile:** nav scrolls horizontally; step labels collapse to numbers.

### Segmented Control
A g1 well with a g5 hairline and 2 px padding; condensed labels; the selected segment is a g10 fill with g0 text that slides to the new choice.

### Frame (signature)
The tile for every found moment, photo, upload and map: a 16:9 picture on g3 with a 2 px corner and a g4 ring (g7 on hover), a bottom scrim, fit score and warnings as tags on the picture, and below it an amber frame code beside a g9 caption. Hover reveals a round red "use" button. Unusable frames are dimmed to 35% and greyscale.

### Marker Loop (signature)
Picking a frame draws a hand-drawn red loop (3.2 px stroke, slightly different per frame) around it in 220 ms on expo ease-out, then writes the play-order numeral at the top-right corner, tilted -8 degrees. Reordering rewrites the numerals. No spring.

### Fill Bar and Ring
Fill bars are 4 px, round, g4 track; green when the part is full, yellow while short. Rings are 3.5 px strokes on g4, marker red for live work, g7 for neutral, with the percent in 11 px amber edge print at the centre. Both animate on expo ease-out (0.5 s and 0.8 s).

### Dialog, Sheet, Menu, Tooltip, Toast
Dialogs (520, 920 or 1320 px wide) scale up from 97% in 240 ms; sheets slide in from the right edge in 320 ms; menus drop 4 px in 140 ms; tooltips fade in 120 ms after a 350 ms delay; toasts rise from the bottom centre. All on expo ease-out.

## Do's and Don'ts

### Do:
- **Do** set every measurement (times, codes, counts, durations against target) in mono, tabular, edge-print amber.
- **Do** reserve marker red for picks, the primary action, on-air and live progress, keyboard focus and news-category tags.
- **Do** keep text at g8 or brighter and every text pair at AA; keep running text at 12 px or larger.
- **Do** use the condensed width only for labels in tracks and rails: step track, segmented controls, tabs, rail titles.
- **Do** put category and status tags in a meta row below the heading.
- **Do** size parts-rail entries at 7 px per second with a 44 px floor.
- **Do** lay found frames on the sheet-black panel under a mono amber count line.
- **Do** animate on expo ease-out (cubic-bezier(0.16, 1, 0.3, 1)); 150 ms for hover, 220 ms for the marker loop, 240 to 320 ms for dialogs, sheets and page changes.

### Don't:
- **Don't** use Caveat Brush anywhere but play-order numerals on picked frames and in the picked list, and never put the numeral in a disc.
- **Don't** put an eyebrow or kicker above a heading.
- **Don't** imitate film material: no sprocket holes, perforations or grain.
- **Don't** use coloured glow shadows; shadows are black.
- **Don't** use g7 or darker for readable text.
- **Don't** put a spring on the marker loop.
