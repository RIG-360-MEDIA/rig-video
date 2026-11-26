# Reference: the website (`web/`)

> `file:line` references point at the code as of 2026-11-25; after later changes, search by the name given next to them.

> This chapter is the reference for the site editors use. It assumes you have read
> [section 7, The website](../HANDOFF.md#7-the-website-what-editors-use) of the handoff, which lists the pages and
> what each is for. The story pipeline behind the buttons is in
> [section 4, The life of one story](../HANDOFF.md#4-the-life-of-one-story-step-by-step). Times are IST.
>
> All paths below are relative to `web/` unless they start with `server/` or `deploy/`. `file:line` references
> point at the code as it is on `main` at the time of writing.

---

## 1. Stack and files

| Piece | What |
|---|---|
| Language | TypeScript 5.8, strict (`tsconfig.json`: `strict`, `noUnusedLocals`, `noUnusedParameters`) |
| UI | React 19, React Router 7 (`react-router`, `BrowserRouter`) |
| Build | Vite 6 with `@vitejs/plugin-react` and `@tailwindcss/vite` (Tailwind CSS 4) |
| State | One hand-written store (`src/data/store.ts`) on `useSyncExternalStore` + `immer` |
| Widgets | Radix (dialog, dropdown menu, tooltip, switch; popover/tabs/slot are installed but not imported) |
| Motion | `motion` (Framer Motion), `lenis` (smooth scroll, landing page only) |
| Drag and drop | `@dnd-kit/core` + `sortable` |
| Audio waveform | `wavesurfer.js` (Review page voice takes) |
| Maps | `d3-geo` + `public/geo/countries.geojson` (1.4 MB) |
| Icons | `@phosphor-icons/react` |
| Fonts | Self-hosted from npm: Archivo Variable, JetBrains Mono Variable, Caveat Brush (`@fontsource*`) |



```
web/
├── index.html            the one HTML page (title "RIG-Video", favicon)
├── vite.config.ts        dev server + proxy
├── package.json          scripts and dependencies (package name is still "anchor-studio-web")
├── src/
│   ├── main.tsx          mounts <App/> inside <BrowserRouter> and <StrictMode>
│   ├── App.tsx           routes and the sign-in guard
│   ├── index.css         design tokens (Tailwind @theme) and a few global classes
│   ├── data/types.ts     the Project contract with the server
│   ├── data/store.ts     all state and every API call
│   ├── pages/            Landing, SignIn, Desk, Script, Visuals, VoEdit, Review, Library, Anchors, Settings
│   └── components/       shell, story, ui, player, clipviewer, frames, mapmaker, brandmark
├── public/               favicon, landing images, countries.geojson
└── DESIGN.md             design system
```

The `@/` import prefix means `src/` (`vite.config.ts:8`, `tsconfig.json` `paths`).

---

## 2. Build, dev run and production serving

### npm scripts (`package.json:6-11`)

| Script | Does |
|---|---|
| `npm run dev` | Vite dev server on **http://127.0.0.1:5180** |
| `npm run build` | `tsc -b && vite build` into `web/dist/`. A type error **or an unused variable/import** fails the build. |
| `npm run preview` | Serves the built `dist/` with Vite |

### Dev run

```bash
cd web
npm ci
npm run dev                                         # proxies to the live API on t7
RIGVIDEO_API=http://<host>:<port> npm run dev        # proxies to another API instance
```

- **The proxy** (`vite.config.ts:10`): `/api`, `/files` and `/anchor-media` go to `RIGVIDEO_API`, default
  `http://100.72.225.89:8770`. That default is the **production** API on t7, so you need Tailscale, a real account, and
  every edit you make in dev changes real stories.
- The browser talks only to `127.0.0.1:5180`, so the API's session cookie is set for that origin and sign-in works
  unchanged.
- **Prefilled sign-in:** in dev only, the sign-in form is prefilled from `VITE_DEV_EMAIL` and `VITE_DEV_PASSWORD` in
  `web/.env.development.local` (gitignored; `pages/SignIn.tsx:14-15`). The server still checks the password.

### Production

1. CI (`deploy/check.sh:33`) runs `npm ci && npm run build` in `web/` with Node 22.
2. `deploy/deploy.sh:50` copies `web/dist/` to t7 `~/anchor-studio/rigvideo/dist/` (with `--delete`).
3. The API serves it (`server/app.py:26`, `:1023-1027`): `DIST = server/../dist`. A catch-all `GET /{path}` returns the
   file if it exists inside `dist/`, otherwise `index.html`, so client-side routes survive a reload. The catch-all
   is registered only if `dist/` exists when the API starts.
4. Same origin as the API, so no CORS. URL: http://100.72.225.89:8770 (Tailscale only).

---

## 3. Routing, sign-in guard and the shell

### Routes (`App.tsx:47-62`)

| Path | Element | Guard |
|---|---|---|
| `/` | `Landing` | none |
| `/signin` | `SignIn` | none |
| `/desk` | `Desk` | `Signed` |
| `/story/:id` | `StoryFrame` (header + step track) with children `script`, `visuals`, `review`; any other child → `script` | `Signed` |
| `/library`, `/anchors`, `/settings` | the page | `Signed` |
| anything else | redirect to `/` | |

All pages are `lazy()` imports, so each is its own chunk.

**Boot gate** (`App.tsx:38-41`): nothing but a thin loading bar renders until `state.ready` is true. `boot()` sets it
after the first `/api/desk` call, whether it succeeds or fails.

**Sign-in guard** `Signed` (`App.tsx:27-33`): if `state.signedIn` is false, it
redirects to `/signin` with `state.from` = the wanted path. Sign-in sends the user back there, default `/desk`. Inside
the guard, pages render inside `AppShell`.

**Page transitions:** routes are keyed by the first path segment (the first two for `/story/<id>`), so moving between
Script, Visuals and Review does not re-animate the whole page; `StoryFrame` animates its own child instead
(`story.tsx:82-87`). `MotionConfig reducedMotion="user"` honours the OS setting.

### Shell (`components/shell.tsx`)

- `AppShell`: for every signed-in page except `/story/*` it adds the sticky `TopBar` with nav links **Desk, Library,
  Anchors, Settings** (`shell.tsx:24`). Story pages draw their own header (`StoryFrame`).
- `TopBar`: wordmark (links to `/desk`), nav, `QueueBadge`, `UserMenu`.
- `QueueBadge` (`shell.tsx:57-73`): when the render queue is not empty, a progress ring for `queue[0]` with "Rendering"
  and "N waiting"; click goes to the Desk.
- `UserMenu`: initials button; menu shows the name (disabled), **Settings**, **Sign out** (`signOut()` then go to `/`).

### Story header (`components/story.tsx`, `StoryFrame`)

- Breadcrumb: wordmark › Desk › headline.
- `JobStatus` (wide screens): the running job's progress ring and line (writing, searching footage, checking clips,
  "Voice n of m"). A failed job shows its message and **Try again** (`retryJob(id, kind)`).
- **Step track**: 1 Script, 2 Visuals, 3 Review, 4 Render. VO-only stories have no Render step (they post from Review).
  A step is clickable once the story's stage has reached it; unreached steps explain why in a tooltip.
  At stage `render` or `done`, steps say "Read-only while it renders".
- "Saved hh:mm" from `updatedAt` (IST).
- **Lock strip** at stage `render`/`done`: "In the render queue (Starts at 00:00 IST)…" or "Rendered. Post it from this
  page…".
- `/story/<id>` with no step goes to the step matching the stage (a rendered story: `render`, the finished video with Post, Remake and Discard; also for 9:16). An unknown or archived id goes to `/desk`.

---

## 4. `data/store.ts`: state and every API call

One module-level `state` object. `set(fn)` replaces it with `produce(state, fn)` (immer) and notifies subscribers.
Components read it with `useStore(selector)` (`store.ts:43-51`). There is no Redux, context or React Query.

### 4.1 State shape (`store.ts:14-39`)

| Field | Meaning | Comes from |
|---|---|---|
| `ready` | First load finished (ok or not) | `boot()` |
| `signedIn` | Session is valid | `/api/desk` ok → true; any 401 → false |
| `user`, `workspace` | Who is signed in, their workspace | `/api/desk` |
| `picks` | Today's picks still on offer | `/api/desk` |
| `hiddenPicks` | Pick ids this user removed | `/api/desk`, `/api/prefs` |
| `anchors` | The anchor roster | `/api/desk` |
| `projects`, `order` | Stories by id, and the server's order | `/api/desk` (+ local edits) |
| `queue` | Render jobs in queue order, `[0]` is next/now | `/api/desk` |
| `library` | Finished videos | `/api/desk` |
| `defaults` | The user's new-video defaults: `format, length, captions, aiLabel, outro` | `/api/desk`, `/api/prefs` |
| `formats` | Formats this server can make; before the first load `["anchor_vo","anchor_only"]` | `/api/desk` |
| `jobs` | Story id → its one visible job: `{kind: write\|search\|voice\|check, progress 0..1, note, failed?, parts?}` | `/api/desk` |
| `toasts` | Notices at the bottom of the screen | local |

`jobs` holds at most one job per story. The server (`server/app.py:206-213`, `job_view`) picks the first of write,
search, check, then voice only if voice failed. Voice progress is read from each section's `voice.state` instead.

### 4.2 The `api()` helper and error handling (`store.ts:61-84`)

- Every call is `fetch(path, {credentials: "same-origin"})`. JSON bodies go through `{json: ...}`; files go as
  `FormData`.
- **401** on any path except `/api/login`: sets `signedIn = false` and throws "Sign in again." The `Signed` guard then
  redirects to `/signin` on the next render, and polling stops (it only reschedules while signed in).
- **Other non-2xx**: throws the server's `detail` string if the body is JSON with one, else
  "Something went wrong (status). Try again."
- `act(promise)`: runs an action; on error it shows the message as a red toast and returns `null`. Almost every action
  goes through it, so server refusals (for example 409 "Wait until every part has its voice.") appear as toasts.
- Auth itself is the API's `rv_session` cookie: httpOnly, 30 days, `SameSite=Lax`, `Secure` only when
  `RIGVIDEO_HTTPS=1` (`server/app.py:54-62`). The site never sees the token.

### 4.3 Loading and polling

| When | Call | What happens |
|---|---|---|
| App start (`boot`, `store.ts:199-211`) | `GET /api/desk` | Ok: `apply()`, start polling. Fail (incl. 401): `ready = true, signedIn = false`. |
| Every **3 s** while signed in **and the tab is visible** (`poll`, `store.ts:190-196`) | `GET /api/desk` | `apply()`. Errors are ignored; the next tick retries. |
| Tab becomes visible again (`store.ts:197`) | `GET /api/desk` | Immediate poll. |
| After render, post, switch, cancel, move-up, post-all, hide pick | `GET /api/desk` | Immediate poll so the queue updates at once. |

`apply(desk)` (`store.ts:170-187`):
- replaces every field above with the server's copy;
- **projects with unsaved local edits are merged** with `overlay()` instead of replaced (4.4);
- shows each **failed job** once as a red toast (keyed on id + kind + note);
- `notifyRendered`: after the first load, each new library item shows a toast "Rendered: headline" and, if the
  browser already allows notifications, a system notification. The site never asks for that permission.

### 4.4 Optimistic edits and saving

Every local edit goes through `mutate(id, fn)` (`store.ts:279-286`): it changes the project in memory at once (the
screen updates immediately) and calls `scheduleSave(id)`.

- **Debounce:** `scheduleSave` (`store.ts:139-145`) marks the story dirty, bumps an edit counter, and saves
  **600 ms** after the last edit.
- **Save:** `saveNow` (`store.ts:147-160`) sends `PUT /api/projects/<id>` with `body(p)` (`store.ts:128-137`):
  `headline, targetSeconds, anchorId, tone, format, facts, ticker, lt, stage, versions`, and per section
  `visuals[sid] = {placed, keywords:[{id}], uploads:[{id}], maps:[{id}]}`, plus `edit.beats[].{sectionId, cuts}` for
  VO only. The id lists let the server drop removed keywords/uploads/maps; the server only lets those lists shrink
  (adding goes through their own endpoints, `server/app.py:395-399`).
- **Reply:** the server returns the whole project. If no edit happened while the save was in flight, it replaces the
  local copy and the story is clean again. If edits did happen, it is `overlay()`-merged and stays dirty.
- **Failure:** red toast "Not saved: <reason>" and a retry every **5 s** until it works. The server refuses saves while
  the script is being written (409); the Script page locks its fields then so this should not occur.
- `flush(id)` (`store.ts:163-167`) saves now. Actions that read the story on the server (approve, revoice, rewrite,
  keyword add, render, switch) flush first.

**`overlay(server, mine)`** (`store.ts:100-126`) decides who wins while a story is dirty:

| The site keeps its own | The server's copy wins |
|---|---|
| headline, targetSeconds, anchorId, tone, format, facts, ticker, lt | voice takes and voice state |
| stage, but only within script/visuals/review | stage `render`/`done` |
| section list, order and text (`versions`) | found videos, photos, keyword state |
| picked voice take (if that take still exists) | anything the server added to keywords/uploads/maps |
| `placed` per section; removals of keywords/uploads/maps (`removed` set) | |
| VO edit's cuts, only while both sides' edit is `ready` | the edit's state, flow, candidates, notes; a new check |

A section whose text or kind differs from the server's is shown as voice "making" (it will be re-voiced).

### 4.5 Every action and its API call

| Store function | Used by | Local effect first | API call |
|---|---|---|---|
| `signIn(email, pw)` | SignIn | | `POST /api/login {email, password}`, then `GET /api/desk`, start polling |
| `signOut()` | UserMenu | signedIn false; clears projects, order, library, queue, picks | `POST /api/logout` (not awaited) |
| `createProject(input)` | Desk composer, pick cards | adds the story at the top, job "write · Starting"; drops a used pick | text/link/pick: `POST /api/projects {kind, text, url?, name?, pickId?, seconds, format}`; file with an empty text box: `POST /api/projects/file` (multipart `file, seconds, format`) |
| `setFormat`, `setTarget`, `setAnchor`, `setFact`, `setTicker`, `setLT`, `editSection`, `addSection`, `deleteSection`, `turnInto`, `mergeNext`, `splitAt`, `reorderSections`, `pickTake` | Script, Review | the edit | debounced `PUT /api/projects/<id>` |
| `setAnchor` after approval | Script, Review | every voiced section → voice "making", no takes | `PUT` (the server re-voices) |
| `proposeRewrite(id, {scope, chips, note})` | Script rewrite sheet | | flush, `POST /api/projects/<id>/rewrite` → `{sectionId: newText}` |
| `approveScript(id)` | Script | stage `visuals`; VO gets `edit = {state: waiting}`; every section voice "making"; empty visuals | flush, `POST /api/projects/<id>/approve` |
| `revoice(id, sid, note)` | Review | that section voice "redoing" with the note | flush, `POST /api/projects/<id>/revoice {sid, note}` |
| `retryJob(id, job, sid?)` | Try again, Write the VO-only version, Check again | job "Starting again"; whole check → edit "checking" | `POST /api/projects/<id>/retry {job, sid?}` |
| `checkAgain(id, sid?)` | VoEdit | = `retryJob(id, "check", sid)` | as above |
| `removeCut`, `moveCuts`, `swapCut`, `addCut`, `setCutSound` | VoEdit | edit the beat, re-time, re-stamp times | debounced `PUT` (edit beats) |
| `addKeyword(id, sid, text)` | Visuals | duplicate → toast, no call | flush, `POST /api/projects/<id>/keywords {sid, text}` |
| `researchKeyword(id, sid, kid)` | Visuals | keyword "queued · Searching again" | `POST /api/projects/<id>/keywords/<kid>/research {sid}` |
| `removeKeyword` | Visuals | removes it and its found videos | debounced `PUT` |
| `addMoment(id, videoId, start, end)` | Clip viewer | | `POST /api/projects/<id>/moments {videoId, start, end}` → `{moment, project}` |
| `place`, `unplace`, `updatePlaced`, `reorderPlaced` | Visuals | the placed list | debounced `PUT` |
| `addUpload(id, sid, file)` | Visuals uploads | appends the returned item | `POST /api/projects/<id>/uploads` (multipart `sid, file`) |
| `removeUpload`, `removeMap` | Visuals | removes it and any placement of it | debounced `PUT` |
| `addMap(id, sid, {src, title})` | Map maker | appends the returned item | `POST /api/projects/<id>/maps` (multipart `sid, title, file=map.jpg`) |
| `findPlaces({q} or {text})` | Map maker | | `GET /api/places?q=…` or `?text=…` (errors → empty list) |
| `sendToRender(id, {outro})` | Review Render | | flush, `POST /api/projects/<id>/render {outro}`, poll |
| `queueRender(id)` | Visuals/VoEdit Continue | toast "Queued for tonight's render (00:00–07:00 IST)" | = `sendToRender` with `outro = defaults.outro` (false for VO) |
| `cancelRender(id)` | Desk queue | | `POST /api/projects/<id>/cancel`, poll |
| `moveUp(id)` | Desk queue | | `POST /api/projects/<id>/moveup`, poll |
| `remakeFinal(id)` | Review Post card | final "building · Starting" | `POST /api/projects/<id>/final` |
| `postDefaults(id)` | Post dialog | | `GET /api/projects/<id>/post` → `{platforms, title, description}` |
| `postVideo(id, platform, title, description)` | Post dialog | `posts.youtube = {state: posting}` | `POST /api/projects/<id>/post {platform, title, description}`, poll |
| `postAll(ids)` | Desk Ready to post | | `POST /api/post-all {ids}` → `{posted, skipped}`; toast counts; poll |
| `switchFormat(id, "vo_only"\|"anchor_vo")` | FormatSwitch | | flush, `POST /api/projects/<id>/switch {format}`, poll |
| `remakeStory(id, now)` | Render page / Review / Desk ready-to-post "Remake" | the returned project; resolves true on success | `POST /api/projects/<id>/remake` |
| `archiveProject(id)` | Desk delete, "Discard" of a rendered video | removes it from `order` when the call succeeds | `POST /api/projects/<id>/archive` |
| `duplicateFromLibrary(itemId)` | Library | adds the new story | `POST /api/library/<itemId>/duplicate` |
| `hidePick`, `showHiddenPicks`, `setDefaults` | Desk, Settings | the list/defaults | `PUT /api/prefs {defaults, hiddenPicks}` (picks: then poll) |

Media URLs come ready-made from the server: `/files/<projectId>/<path>` for a story's files and
`/anchor-media/<anchorId>/{face.jpg, frame.jpg, voice.mp3}` for anchors.

### 4.6 Helpers other files rely on

| Helper | Does |
|---|---|
| `sections(p)` | `p.versions[p.format]` (the sections of the current format) |
| `sectionSeconds(s, anchorId)` | The picked take's length if the voice is ready ("measured"); else words ÷ the anchor's `wordsPerSecond` (2.5 if unknown) |
| `totalSeconds(p)` | Sum of the above |
| `wordsOf(text)` | Word count |
| `parseLength(raw)` | Accepts `1:30`, `90`, `90s`, `1.5 min`, `1m 30s`; returns seconds or `null` |
| `fillOf(p, s)` | `{need, have, full}`. VO only: the beat's cut seconds against its length, full within 0.25 s. Anchor formats: placed seconds (failed cuts ignored) against the section's seconds; an **anchor** part is full as soon as it has one picture. |
| `beatOf`, `cutsSecs`, `shortBy(b)` | The VO beat for a section; its cut seconds; how many seconds short (0 if within 0.25 s) |
| `retime(b)` (`store.ts:418-429`) | Stretches/shrinks cuts in proportion to fill the beat, never past a video cut's `shotEnd` ("water-fill") |
| `usedAs(b, cand)` | Index of a cut already playing the same stretch of the same video (or same picture), or −1 |
| `storyPool(p, sid)` | All found videos and photos of the story, this part's first, de-duplicated. Anchor parts pick from it. |
| `mediaOf(p, sid, placed)` | Resolves a placed item to `{kind, src, poster, label, code}`; uses the treated clip when `useTreated` |
| `frameCode(roll, frame)` | `R02·F05` style codes |
| `voiceProgress(p)` | `{done, total, busy}` over sections that have a voice |
| `awaitingPost(p)` | Stage `done`, final ready and not stale, YouTube not posted/posting/uploading |
| `toast(text, tone)` | Shows a notice for 3.6 s |

Exported but unused by any page: `setStage`, `continueToReview`, `setHeadline`, `posterOf`, `getState`.

---

## 5. `data/types.ts`: the Project contract

The server sends exactly these shapes; `project.json` keys that start with `_` are server-only and never reach the site
(see [section 8, Data](../HANDOFF.md#8-data-where-everything-is-stored)). The header comment's path
"web/server/app.py" is out of date; the API is `server/app.py`.

### People, anchors, picks

| Type | Fields |
|---|---|
| `Workspace` | `id`, `name`, `kind` (`dnl` or `own`), `picksFeed` (whether it gets the daily picks) |
| `User` | `id`, `name`, `email`, `role` (`admin` or `editor`), `workspaceId` |
| `Anchor` | `id`, `name`, `gender`, `face` (portrait URL), `frame` (anchor at the studio desk), `voiceSample` (audio URL), `wordsPerSecond` (measured pace, drives all timing estimates), `regions` (region keys), `offered` (shown in pickers) |
| `Pick` | A story the daily selection chose: `id`, `headline`, `deck` (summary), `type` (`StoryType`), `place`, `source` (outlet), `url`, `publishedAt` |
| `StoryType` | `war_conflict`, `death_disaster`, `democracy`, `turmoil_unrest` |

### The story

| Type | Fields |
|---|---|
| `Format` | `anchor_vo`, `anchor_only`, `vo_only` (9:16, no anchor on screen) |
| `Stage` | `script` → `visuals` → `review` → `render` (in the queue) → `done` |
| `LowerThird` | `kicker` (place, red box), `headline`, `subline` |
| `VoiceTake` | `id`, `src` (audio URL), `seconds` |
| `SectionVoice` | `state` (`waiting`, `making`, `ready`, `redoing`), `takes`, `pick` (take in use), `note` (what the editor asked to change) |
| `Section` | One part or beat: `id`, `kind` (`anchor` or `vo`), `text`, `voice` (exists after approval), `picture` (VO only: what should be on screen), `search` (VO only: the writer's footage search line) |
| `Fact` | `label`, `value` (facts from the source; editable) |
| `Project` | see below |

`Project` fields:

| Field | Meaning |
|---|---|
| `id`, `headline`, `createdAt`, `updatedAt` | Identity; `updatedAt` drives "Saved hh:mm" |
| `source` | `{kind: link\|file\|text, url?, name?, site?, text}`: the article |
| `targetSeconds` | Asked length |
| `anchorId`, `tone` | The anchor (also the VO voice) and the tone label |
| `stage`, `format` | As above |
| `versions` | Sections per format. `anchor_vo` and `anchor_only` always exist; `vo_only` exists (maybe empty) only when the server can write VO only. Switching format only changes which list is shown. |
| `lt`, `ticker`, `facts` | One lower third for the video; ticker lines (at least 5 to approve an anchor script); facts |
| `visuals` | Section id → `SectionVisuals` (anchor formats) |
| `render?` | `RenderJob` |
| `videoId?` | Library item, once done |
| `edit?` | `StoryEdit` (VO only) |
| `final?` | `FinalVideo` |
| `formatWhy?` | `{by: auto\|editor, text, at, decided?}`: why the story has its format |
| `posts?` | `{youtube?: Post}` |

### Final video and posting

| Type | Fields |
|---|---|
| `FinalVideo` | `state` (`building`, `ready`, `failed`), `progress`, `note`, `stale` (the edit or a voice changed since; a new one is coming), `video`, `poster`, `seconds`, `cuts` (shots), `low` (shots taken from the 480p copy because YouTube refused full quality), `whole`, `builtAt` |
| `Platform` | `youtube` only |
| `Post` | `state` (`uploading` → `awaiting` (unlisted) → `posting` → `posted` (public), or `failed`), `title`, `description`, `videoId`, `url`, `error`, `postedAt`, `at`, `autoAt` (anchor-only: goes public by itself at this time), `auto` (it did) |

### The VO edit

| Type | Fields |
|---|---|
| `EditSource` | Video: `{kind: video, youtubeId, title, start, end, shotEnd?}` (`shotEnd`: where the shot ends; re-timing never passes it). Picture: `{kind: picture, url, page, title}` |
| `EditCut` | One shot in a beat: `id`, `shot`, `at` (story time it starts), `secs` (how long it plays), `src`, `kind` (`footage`, `speech`, `photo`, `post_or_document`), `fit` (`exact` = filmed at the event, `subject`, `topic`), `shows` (what the checker saw), `sound` (scene-sound prompt; `""` = none; unset on edits before 2026-11-24), `poster`, `clip`, and marks `fill`, `swapped`, `review` (why the review flagged it, or what a swapped-in shot replaced), `repeat`, `byUser` |
| `EditCandidate` | Another shot the editor can swap in: `shot`, `src`, `kind`, `fit`, `shows`, `sound?`, `poster`, `clip?` |
| `BeatEdit` | `sectionId`, `secs` (the beat's voice length the cuts must fill), `cuts`, `candidates`, `notes` (checker notes like "story footage", "1.2 s short"), `why` |
| `StoryEdit` | `state` (`waiting`, `checking`, `ready`, `failed`), `progress` (0..1), `note`, `flow` (one sentence on how the edit reads), `beats` |

### Visuals (anchor formats)

| Type | Fields |
|---|---|
| `Keyword` | `id`, `text`, `reason`, `state` (`idle`, `queued`, `searching`, `done`, `error`), `progress` |
| `Flag` | `logo`, `text`, `vertical`, `presenter` |
| `Treatment` | `crop` (10% centre crop) or `blur_fill` (portrait video over a blurred copy) |
| `Moment` | A time range in a found video: `start`, `end`, `label`, `description`, `fit`, `score`, `estimated` (no captions, times guessed), `clip` (cut file), `cutFailed`, `poster`, `posterNear`, `flags`, `treat {kind, preview}`, `custom` (a range the editor marked) |
| `FoundVideo` | `id`, `keywordId`, `youtubeId`, `title`, `channel`, `publishedAt`, `duration`, `thumb`, `relevance` (0–100), `verdict`, `hasCaptions`, `moments`, `flags`, `source` (the whole video, once downloaded) |
| `Photo` | `id`, `src`, `caption`, `credit`, `source` |
| `Upload` | `id`, `src`, `kind` (`video`/`image`), `name`, `seconds?` |
| `MapItem` | `id`, `src`, `title` |
| `PlacedItem` | What plays: `id`, `ref` (`{kind: moment, videoId, moment}` or `{kind: photo\|upload\|map, id}`), `in`, `out` (for stills: 0..seconds shown), `muted`, `useTreated` |
| `SectionVisuals` | `keywords`, `found`, `photos`, `uploads`, `maps`, `placed` (play order) |

### Queue and library

| Type | Fields |
|---|---|
| `RenderJob` | `projectId`, `state` (`queued`, `rendering`, `assembling`, `held`, `done`, `failed`), `queuePosition` (0 = on the machine), `waitNote` ("Starts at 00:00 IST" outside the window), `percent`, `etaIso`, `heldReason` |
| `LibraryItem` | `id` (server uses `lib-<projectId>`), `projectId`, `headline`, `anchorId`, `madeAt`, `seconds`, `video`, `poster`, `origin` (`studio` or `daily`) |

Store-only types (`store.ts:10-12`): `Defaults {format, length, captions, aiLabel, outro}`, `Toast`, `Job`.

---

## 6. Pages

"Locked" below means the story is at stage `render` or `done`: fields are read-only and edit buttons are hidden.

### 6.1 Landing (`/`, `pages/Landing.tsx`)

The public marketing page. It makes no API calls of its own; it reads `signedIn` and `anchors` from the store.

- **Nav:** wordmark; **Sign in** (signed out) or **Open the desk** (signed in).
- **Hero "fan"** (`Fan`, `Landing.tsx:116-166`): five layers (Story, Anchor, Voice, Footage, Graphics) fanned out in 3D.
  Scrolling a 360vh section folds them into one finished frame, then labels its parts. Images are
  `public/landing/anchor.jpg` and `footage.jpg`; the story text is a labelled example.
- **Start with anything:** a typing demo cycling Link / PDF / Your words into a script card.
- **Choose who tells it:** an endless strip of offered anchors; click one to hear `voiceSample`. Pictures are
  `public/landing/anchors/<anchorId>.jpg`, falling back to the anchor's `face`.
- **Finale:** a frame that straightens on scroll; typing a headline (60 chars) shows it on the frame; **Make it a
  video** and **Get started** buttons.
- Every call-to-action goes to `/desk` when signed in, else `/signin?new=1`.
- Smooth scrolling with snap points (Lenis) unless the user prefers reduced motion; reduced motion also drops the 3D fan.
- Toasts are never shown on `/` (`ui.tsx:288`).
- Colours here are the landing's own constants (`C`, `S` at `Landing.tsx:15-18`: ink black, silver, coral), not the
  app tokens.

### 6.2 Sign in (`/signin`, `pages/SignIn.tsx`)

- Segmented **Sign in / Sign up** (`?new=1` opens on Sign up). **Sign up does nothing**: submitting shows
  "Sign-up is not open yet. For now, ask us for an account." Accounts are made on the server
  ([section 14, runbook](../HANDOFF.md#14-operating-it-runbook)).
- Email + password → `signIn()`; button shows "Signing in…". The error shown is the server's text (for example
  "That email and password don't match."; the server waits 1 s on a wrong password).
- Success → the page the user was sent away from, else `/desk`.
- "Forgot it? Ask your admin." is text only. Right half (wide screens): wordmark and tagline.

### 6.3 Desk (`/desk`, `pages/Desk.tsx`)

Greeting by IST time of day and the date. Left column: composer, picks, in progress. Right column: ready to post,
render queue, needs you, just finished.

**Composer "Start a new video"** (`Desk.tsx:49-137`)
- Text box: paste a link (a lone `http(s)://…` is treated as a link and shows its host), paste text, or drop a file.
- **Upload file** / drag-drop: `.pdf`, `.docx`, `.txt`, `.md` only. `.txt`/`.md` content (first 20,000 chars) is
  copied into the text box if it is empty.
- **Length:** free text parsed by `parseLength`; invalid shows "Try 45s, 1:30 or 3 min".
- **Format:** Anchor + VO / Anchor only / VO only 9:16. A format not in `state.formats` is disabled with a tooltip.
  Starts at the user's default format.
- Hint: "~N words" (2.5 words/s) and, for anchor formats, "renders in ~M min" (23 min per minute of video, min 5).
- **Write the script:** validates, asks to confirm above 5 minutes ("A long video" dialog), calls `createProject`,
  then opens the new story's Script page.

**Today's picks** (only if the workspace kind is `dnl`)
- Cards: headline, deck, category tag, place, published time (IST), outlet.
- **Use this story** → `createProject({kind: "pick", pickId, seconds, format})` with the composer's length and format,
  then opens Script. A per-card busy flag stops double clicks.
- **Make 9:16** (when the composer format is not VO only and the server offers VO only): same with `vo_only`.
- **Remove** → `hidePick`; the server refills the list from the day's reserves. **Bring back N removed** →
  `showHiddenPicks`.
- Empty states: "still being chosen" (no picks) or "every pick is in use or removed".

**In progress**: stories at stage script/visuals/review, in server order. Each row: headline, anchor face and name,
estimated length / target, last edit time, up to 4 thumbnails (VO: first cuts' posters), a status tag
("Writing the script" with a ring, "Script to check", "Pictures · n of m filled", "Ready to review" /
"Voice in progress"). The row links to the matching step. The trash icon opens "Delete this story?" → **Delete** →
`archiveProject` (a soft delete; the server refuses with 409 while a job runs).

**Ready to post** (only when some story passes `awaitingPost`): list linking to Review, with "post failed" marks.
**Post all (n)** → dialog listing them → **Post all to YouTube** → `postAll(ids)`.

**Render queue**: empty → "Nothing queued. Renders run 00:00–07:00 IST." Otherwise row 1 has a progress ring, the
others "#n". Line 2: `waitNote`, else "putting it together" (assembling), "done ~hh:mm IST" (`etaIso`), or
"waits for n jobs". **Move up** (caret) shows from the third row on → `moveUp`. **Cancel** shows on `queued` rows →
`cancelRender` (the story goes back to Review).

**Needs you**: links built from the stories: render held/failed (with `heldReason`), "Voice ready. Listen before
rendering." (stage review, no voice busy), "n parts need pictures" (visuals), "Script written. Check and approve it."

**Just finished**: the newest 3 library items; click opens a dialog playing `video`, or a rough cut / phone preview of
the project if there is no file.

### 6.4 Script (`/story/<id>/script`, `pages/Script.tsx`)

Locked while the script is being written (job `write` running) or at stage render/done (`Script.tsx:24`). Editing is
allowed at stages visuals and review: changed sections are re-voiced by the server.

**Top (sticky):** format choice and length.
- Format segmented → `setFormat` (saved). VO only is disabled when the story has no `vo_only` version. This control
  checks `p.versions`, not `state.formats` (`Script.tsx:38-39`).
- "Estimated/Measured m:ss of [target]": click the target to edit it (`setTarget`, Enter/blur saves, Esc cancels).
  The difference chip turns yellow when off by more than 10%. A bar shows total against target.

**Section list** (drag to reorder with `@dnd-kit`, keyboard sorting supported):
- Each card: drag handle, kind icon and name ("Anchor 1", "Voiceover 2", "Beat 3", or "Anchor, whole script" for
  anchor only), word count, live seconds (flashes the change), and a text area → `editSection`.
- VO only: an "On screen" line under each beat → `editSection({picture})`; its tooltip shows the writer's search line.
- **⋯ menu:** Rewrite this part/beat (opens the rewrite sheet on it), Split at the cursor (`splitAt`), Merge with the
  next (`mergeNext`), Make it a voiceover / an anchor part (`turnInto`, not in VO), Move up / Move down, Delete
  (disabled when only one section is left).
- Anchor only: no drag, and split, merge, turn-into and move are disabled.
- Add buttons: **+ Anchor part / + Voiceover part** (anchor + VO), **+ Beat** (VO, once beats exist).
- While writing: a skeleton with the job note. VO only with no beats: "No VO-only version yet" and
  **Write the VO-only version** → `retryJob(id, "write")`.

**On-screen graphics** (anchor formats only, `Graphics`): a live 16:9 preview on the anchor's studio frame, the lower
third editor (Place/kicker 14, Headline 48, Line below 70 characters; counters turn red over the limit but do not
block) and the ticker editor (one input per line, 90-character counter, remove per line, "Add a ticker line and press
Enter"). Fewer than 5 non-empty lines shows "n more needed".

**Right panel:**
- **Anchor / Voice** card: face, name, pace, **Hear the voice**, **Change** → `AnchorPicker` (offered anchors with
  regions and voice samples) → `setAnchor`. After approval it warns that every part is re-voiced (about 3 min GPU).
- **From the source**: facts, each editable → `setFact`.
- **Rewrite with AI** → rewrite sheet for the whole script.
- **Source**: link (opens the article), file name or "Pasted text", and the first lines of the text.

**Rewrite sheet** (`RewriteSheet`): scope Whole script / one part (with a part picker), chips ("Too long", "Too
short", "More context", "Simpler", "Stronger opening", "Change the tone"), free note → **Rewrite** →
`proposeRewrite`. Results show per section: old vs new with a word diff and both durations; **Use new** →
`editSection`, **Keep mine** drops it. **Ask again** returns to the form, **Done** closes.

**Bottom bar:** at stage script, **Approve script** (disabled while writing, with no sections, with any empty
section, or for anchor formats with fewer than 5 ticker lines) → `approveScript`, then go to Visuals. After approval:
**Go to visuals**.

### 6.5 Visuals (`/story/<id>/visuals`, `pages/Visuals.tsx`)

`VisualsPage` shows `VoEdit` (6.6) for VO only and `AnchorVisuals` for the anchor formats (`Visuals.tsx:26-29`).

**Anchor formats: three columns (stacked under 1024 px)**

1. **Parts rail** (`SectionRail`): one button per part, height 7 px per second (44 px minimum), name, seconds, the
   first line of text, a fill bar, and status: per-part search status from `job.parts`, "Searching", "Filled" /
   "Picture set", or "n s short" / "Needs a picture". Opens on the first part that is not full.
2. **Centre** (`Center`) for the selected part:
   - Title and text. An anchor part is "the screen behind <anchor>" and picks from the **whole story's** footage and
     photos (`storyPool`); a VO part shows its own.
   - **Keywords:** chips with state icons (idle, queued, searching, done, error) and tooltips; hover shows
     **Search this/again** (`researchKeyword`) and **Remove** (`removeKeyword`). "Add a keyword" + Enter →
     `addKeyword`.
   - **Source tabs:** Found footage, Photos, Your uploads, Maps, with counts.
   - **Found footage:** filter All / Strong fit (relevance ≥ 70) / No logos or text (no flags). A dark "contact
     sheet" with a count line (roll, videos, frames, picked, seconds of need) and one `Frame` per moment, coded
     `R02·F03b`. Tiles show score, "≈ time", flags, "Downloading" or "Can't cut", and a red loop + number when
     picked. Click opens the **clip viewer**; the hover **+** places the moment straight away (5 s, or the part's
     full length for an anchor part). Empty: skeletons while searching, else "No footage found for this part".
   - **Photos:** click or **+** places the photo (4 s; full length for anchor parts).
   - **Your uploads:** drop zone / **Choose files** (video or image only) → `addUpload`; tiles place on click;
     trash → `removeUpload`.
   - **Maps:** the map maker (component, section 7) → **Add this map** → `addMap` then places it (4 s, or full
     length) and toasts "Map added and placed". Saved maps are listed with a delete button (`removeMap`).
   - Placing anything on an **anchor** part first removes what was there: an anchor part has one picture.
   - A moment that failed to cut is refused with a toast. Placing a moment that has no cut clip yet toasts "Cutting
     the clip from the video…".
3. **Picked** (`Picked`): play order with fill bar and "n s still to fill". Rows: drag handle, red numeral,
   thumbnail (hover plays video), "T" when the treated clip is used, label, code, length, remove (`unplace`).
   Clicking a row opens In/Out number fields (`updatePlaced`, at least 0.5 s apart). **Fill the rest from the edit
   plan** (VO parts not yet full, with cut clips available) places unused cut moments, up to 5 s each, until full.
   - **Footer:** the `FormatSwitch` card, then either a dashed button naming the first gap ("VO 2 needs 4 s more",
     "+n more"; click selects that part) or **Continue** → `queueRender`, go to the Desk. Locked shows "Queued for
     tonight's render" or "Rendered".

**Clip viewer** (component, section 7) opens over the centre with Use / prev / next.

### 6.6 VO edit (VO-only Visuals, `pages/VoEdit.tsx`)

"The edit": which shots play under each beat. Two columns at 1024 px and up (beats, inspector); below that the
inspector opens as a right-hand sheet when a cut is selected.

**Header** (`EditHead`): state tag (Waiting / Checking the clips n% / Check failed / Ready), counts (beats, cuts,
distinct videos, seconds filled of needed), the edit's `flow` sentence, and **Check the whole story again**
(`checkAgain(id)`, disabled while checking). Waiting explains that the check runs after the voice and the search.
Failed shows the note and **Check again**.

**Beat rows** (`BeatRow`): "Beat n", its time range, "n s short" tag, the line, the "On screen" hint, and a warning
when the measured voice differs from the beat length by more than 0.5 s ("Check again to re-time this beat").
- **Cut bar** (`CutBar`): each cut is a tile whose width is its seconds, with its number, fit tag, kind icon, one mark
  (Swapped, Review, Repeat, Fill, Yours) and seconds. Drag to reorder (`moveCuts`). Click selects it. A short beat
  ends with a striped "+ n s" gap tile; click it to fill. The bar dims while that beat is being checked.
- Under the bar: the checker's notes, review flags, and **Check again** for this beat (`checkAgain(id, sid)`).
- A beat added after the check shows "Not checked yet" with **Check this beat**.

**Inspector** (`Inspector`), for the selected cut or gap:
- A 9:16 clip preview with a **9:16 / Original** toggle (centre crop vs whole frame; the real reframing happens in the
  final render).
- What the shot shows; **Sound** field: the scene-sound prompt for this cut (`setCutSound`, 80 chars; empty = none).
- Facts: YouTube link at the start time (or picture page), range in the source, start in the story, fit, kind.
- Marks explained (review, swapped, repeat, fill, yours).
- **Earlier / Later** (`moveCuts`) and **Remove** (`removeCut`; the others stretch to fill).
- **Swap with / Shots to add:** the beat's candidates. Click previews one in the inspector; **Swap into cut n**
  (`swapCut`: same slot, same seconds as far as the shot runs) or, for the gap, **Add to the beat** (`addCut`: at
  least 2 s, then all cuts re-timed). The hover **+** does the same without preview. Candidates already in use are
  dimmed and cannot be added.
- "Why the check chose these shots": `b.why`.
- With nothing selected: a legend of fits and kinds.

**Footer** (`ContinueGate`): `FormatSwitch`, then: until the edit is `ready`, a dashed "Continue opens once the edit is
checked" (or "Check the edit again to continue"). When ready, short beats are listed as links (select the gap) and
the button reads **Continue anyway**; otherwise **Continue**. Both → `queueRender`, go to the Desk.

### 6.7 Review (`/story/<id>/review`, `pages/Review.tsx`)

**Left, player:**
- Anchor formats before the final: `RoughCutPlayer` (section 7) plus a **timeline** with rows Parts (click jumps and
  selects the part), Pictures (click seeks), Graphics (lower third over anchor parts, the ticker). At stage `done` with
  a final video: a plain `<video>` of it.
- VO only (`VoPreview`): the final 9:16 video if ready and not stale, else the `PhonePlayer` preview; beside it the
  current beat's text and cut; a beats/cuts timeline (`VoTimeline`) with short gaps striped.

**"Listen to each part/beat"** (`VoicePart`): per section, a waveform player of the picked take (`Wave`,
wavesurfer), take chips **Take n · m:ss** (`pickTake`), and **What should change?** → chips ("Slower", "Faster",
"More serious", "Less flat", "Fix a name", "Pause before the last line") + free text → **Make a new take** →
`revoice`. While making: an animated "Making the voice on the GPU" / "Making a new take: …". A take that fails to
load says so.

Anchor formats also get the on-screen graphics editor (same as Script).

**Right:**
- **RenderCard** (anchor formats before `done`): length, estimated GPU minutes (`RENDER_MIN_PER_SEC = 0.23`, at least
  4), queue position, "Ready at" (estimated in the browser), and checks: every voice made, every part has pictures,
  "Lip check runs by itself". A held or failed render shows its reason. Parts short → **Fill the pictures** (to
  Visuals). Else **Render this video** (disabled until ready) → confirm dialog → **Render** → `sendToRender(outro)`,
  toast, go to the Desk. Locked: status line and **Back to the desk** / **Open the library**.
- **PostCard** (VO only always; anchor formats at `done`):
  - final state: ready ("n shots, 9:16"), making (progress and note), failed (**Make it again** → `remakeFinal`),
    queued, or "made in the night render after you press Continue";
  - `low > 0`: warning and **Try full quality again** → `remakeFinal`;
  - VO checks (voices, edit checked, beats filled);
  - accounts: YouTube with its post state (public, unlisted awaiting approval with the auto-publish time, uploading,
    posting, failed + error) and an **Open** link; Instagram, Facebook and X are listed as "Not connected yet" (static);
  - **Post** / **Post again** / **Posted** / "Waiting for the final video". Post opens the **Post dialog**: loads the
    title and description (the saved ones, else `postDefaults`), title up to 100 chars, description → **Post to
    YouTube** → `postVideo`, toast.
- **Anchor / Voice** box with **Change** (anchor picker, as on Script).
- **Extras** (anchor formats): **DNL outro** switch; it changes the preview and is sent with Render. It starts from the
  user's default. Captions and the AI label exist in the player but are forced off here (`Review.tsx:23`).

### 6.8 Library (`/library`, `pages/Library.tsx`)

Every `LibraryItem` of the workspace. Count of videos and minutes; **Search headlines**; sort Newest / Oldest /
Longest; anchor filter chips (only anchors with videos). Cards: poster, hover plays the video muted from a third in,
length, "New" for under 6 h, "Rough cut" when there is no file. Empty: "No videos yet" or "Nothing matches" with
**Clear filters**.

Click opens the player dialog: `VideoPlayer` for a file, else a rough cut / phone preview of the project, else "This
video's file is no longer kept." Footer: anchor, length, date; **Download** (a plain `download` link; disabled
without a file); **Make another from this** → `duplicateFromLibrary`, toast "Copied into a new story", open its Script.

### 6.9 Anchors (`/anchors`, `pages/Anchors.tsx`)

Read-only. Grid of offered anchors ("on air") and, below, "Not offered right now" (greyed). Each card shows the story
count (library items + open stories with that anchor). The detail panel: studio frame, name, **Hear the voice**, On
air/Resting, pace, regions, words per minute, and links to that anchor's open stories (`/story/<id>`) and library
videos (`/library`).

### 6.10 Settings (`/settings`, `pages/Settings.tsx`)

Three tabs:
- **New videos:** default **Format** (`setDefaults({format})`, saved at once), default **Length** (saved on blur if it
  parses, toast "Default length saved"; else reverts), **DNL outro** switch. All go to `PUT /api/prefs`.
- **Machines:** static text about the script writer (local model primary, Groq fallback) and the footage search; the
  render machine block lists the live queue with a ring for the first job.
- **Members:** only the current user with their role; **Invite** is disabled ("Inviting people opens when sign-up
  does").

---

## 7. Components (`src/components/`)

| File | Export | Purpose | Props | Used by |
|---|---|---|---|---|
| `shell.tsx` | `Mark` | Red "DNL" bug | `className?` | players, Script preview |
| | `Brand` | Wordmark link | `to = "/desk"` | TopBar, StoryFrame, SignIn |
| | `AppShell` | Top bar + main for non-story pages | `children` | `App.tsx` |
| | `TopBar` | Sticky bar with nav, queue badge, user menu | `children?, right?` | AppShell |
| `story.tsx` | `useProject()` | The project for `:id` from the store | | Script, Visuals, Review |
| | `StoryFrame` | Story header, step track, lock strip, `<Outlet/>` | | `App.tsx` |
| | `FormatSwitch` | "With anchor" / "No anchor · 9:16" card, `formatWhy`, **Switch to…** with a confirm dialog → `switchFormat` (disabled while at stage script) | `p, locked` | Visuals, VoEdit |
| `ui.tsx` | `cx` | `clsx` + `tailwind-merge` | | everywhere |
| | `mmss`, `istTime`, `istDate` | `m:ss` (optionally tenths); time and date in **Asia/Kolkata** | | everywhere |
| | `Button` | `kind`: primary, secondary, ghost, quiet, danger; `size`: sm, md, lg; `icon` | | everywhere |
| | `IconButton` | Square icon button with a tooltip | `label, size?, active?` | everywhere |
| | `Tip`, `TipProvider` | Radix tooltip (350 ms delay) | `label, side?` | everywhere |
| | `Input`, `Textarea` | Styled fields | native props | forms |
| | `Switch` | Labelled Radix switch | `on, set, label, hint?, id` | Review, Settings |
| | `Segmented` | Radio group with a sliding pill; `off` disables an option with a reason | `value, set, options, label, size?` | everywhere |
| | `FORMAT_OPTIONS`, `useFormatOptions()` | The three formats; the hook disables those not in `state.formats` | | Desk, Settings, Script |
| | `Tag`, `KindTag` | Mono chips in tones neutral/anchor/vo/marker/ok/warn/bad/edge | | everywhere |
| | `Ring` | Circular progress | `pct, size?, label?, tone?` | queue, jobs |
| | `FillBar` | Thin bar, green when full (±0.25 s) | `have, need` | Visuals |
| | `LiveSeconds` | Duration that flashes when it changes | `sec, measured?` | Script |
| | `Dialog` | Centred modal (520 / 920 / 1320 px) | `open, onOpenChange, title, wide?, bare?` | everywhere |
| | `Sheet` | Right-edge panel | `open, onOpenChange, title, width?` | Script rewrite, VoEdit on phones |
| | `Menu` | Dropdown of `{label, icon, onSelect, danger?, disabled?}` or `"sep"` | `trigger, items, align?` | Script, UserMenu |
| | `Kbd`, `Skeleton`, `Empty` | Key cap, shimmer box, empty state | | various |
| | `Toaster` | Renders `state.toasts` (hidden on `/`) | | `App.tsx` |
| `player.tsx` | `buildCut(p)` | Anchor formats: the story as segments (one per section) with their placed pictures, audio and lower third | | RoughCutPlayer, Review timeline |
| | `RoughCutPlayer` | Browser-only preview: the real voice takes over the placed pictures, anchor frame with the "behind" picture, lower third, ticker, optional captions, AI label, DNL outro (11.84 s). Keys: Space/K, arrows (Shift ×5), J/L, F | `p, autoPlay?, time?, onTime?, compact?, extras?` | Review, Desk, Library |
| | `VideoPlayer` | Player for a rendered file with the same controls; M mutes | `src, poster?, autoPlay?` | Desk, Library |
| | `ClipPlayer` | One clip with in/out handles on the seek bar; with `treated`, original and treated play in sync behind a draggable wipe. Keys: I/O or [ ], `,` `.` frame step, F, M | `src, treated?, kind?, poster?, inT, outT, setIn, setOut, muted, setMuted, cue?` | ClipViewer |
| | `useFull()` | Full screen with a pinned-overlay fallback where the API is blocked | | players |
| | `buildVoCut(p)`, `PhonePlayer` | VO only: beats on one clock from the edit, cuts centre-cropped in a phone frame, the beat line as a caption, the beat's voice | `p, time?, onTime?, autoPlay?, width?` | Review, Desk, Library |
| `clipviewer.tsx` | `ClipViewer` | Dialog for a found moment. If the whole video is downloaded (`video.source`): plays it in full, moments are jump buttons, any marked range can be used (new range → `addMoment`). Otherwise the moment's own cut clip with Treated/Original. Side panel: title, channel, date, relevance, captions, description, fit, treatment, presenter/text warning, **Use**, prev/next (also arrow keys). | `pid, target, onClose, onUse, useLabel, next?, prev?, placedAs?` | Visuals |
| `frames.tsx` | `Frame` | The 16:9 tile for every moment, photo, upload, map and VO candidate: score, flags, "≈ time", "Downloading", "Can't cut", code, caption, hover **+**, `dim` | `src, code, label, sub?, seconds?, score?, estimated?, flags?, kind?, noClip?, cutFailed?, picked?, seed?, onOpen?, onAdd?, dim?` | Visuals, VoEdit |
| | `MarkerLoop` | The hand-drawn red loop and play-order numeral on a picked tile | `n?, seed?` | Frame, uploads |
| | `flagLabel` | Flag → label | | Frame |
| `mapmaker.tsx` | `MapMaker` | Draws a map in SVG: the first place's country highlighted, red markers with labels, **no lines** (a project rule). Places start from `findPlaces({text: suggest})`; "Add a place" searches `findPlaces({q})`. **Add this map** renders the SVG to a 1280×720 JPEG data URL and calls `onAdd`. Loads `/geo/countries.geojson` once. | `suggest, onAdd` | Visuals |
| | `labels()` | Places label boxes so they do not overlap | | MapMaker |
| `brandmark.tsx` | `Wordmark` | Coral double-slash + "RIG-Video" | `small?, big?` | Brand, SignIn, Landing |
| | `Fog` | Drifting background light | | Landing |

Page files also export shared pieces: `Script.tsx` exports `Graphics`, `GraphicsPreview`, `LTEditor`, `Ticker`,
`VoiceSample`, `AnchorPicker`, `regionName`, `tickerOk` (used by Review and Anchors); `Visuals.tsx` renders
`VoEdit.tsx`'s default export.

---

## 8. Format differences at a glance

| | `anchor_vo` | `anchor_only` | `vo_only` |
|---|---|---|---|
| Script sections | Anchor and Voiceover parts, add/split/merge/turn-into/reorder | One "Anchor, whole script"; no reorder/split/merge | Beats with an "On screen" line; add Beat |
| Approve needs | ≥ 5 ticker lines, no empty section | same | no empty beat (no ticker) |
| Graphics editor | yes (Script, Review) | yes | no |
| Anchor picker title | "Choose the anchor" | same | "Choose the voice" (not on camera) |
| Visuals | Parts rail + footage/photos/uploads/maps + picked | same (one part) | The edit (`VoEdit`) |
| Continue needs | every part full | same | edit `ready` (short beats allowed) |
| Outro on render | `defaults.outro` (Visuals) or the switch (Review) | same | never |
| Step track | 4 steps | 4 steps | 3 steps (no Render) |
| Review player | Rough cut + timeline; final video at done | same | Phone preview / final 9:16 + beat timeline |
| Review right card | RenderCard, PostCard at done | same | PostCard always |
| Format switch on Visuals | to "no anchor" | to "no anchor" | to "with anchor" (`anchor_vo`) |

---

## 9. Design system (brief)

Full spec: `web/DESIGN.md` ("The Contact Sheet": every story is a roll of film). Tokens live in `src/index.css:8-45`
as Tailwind 4 `@theme` variables, so each becomes utility classes (`bg-g3`, `text-edge`, `border-marker`, …).

| Token | Value | Use |
|---|---|---|
| `g0` … `g10` | `#0a0b0d` … `#e8eaee` | One 11-step graphite ramp: ground (g0), surfaces (g1–g3), borders (g4–g6), placeholders (g7), text (g8 is the lowest text step, g10 primary) |
| `marker` / `marker-ink` | `#e31b23` / `#ff5b61` | DNL red: primary button, picks, focus, live progress; ink for small red text |
| `edge` | `#df9a4c` | Amber "edge print" for every measurement (times, codes, counts) |
| `anchor` / `vo` | `#ab9cff` / `#5fb3ea` | On-camera parts / voice-over parts |
| `ok`, `warn`, `bad` | `#4dc48c`, `#f2c14e`, `#ff5b61` | State |
| Fonts | Archivo Variable (sans), JetBrains Mono Variable (`.edge` numbers), Caveat Brush (picked numerals only) | |
| Radii | 2 / 3 / 5 px (`xs`, `sm`, `md`) | |
| Ease | `cubic-bezier(0.16, 1, 0.3, 1)` | Most motion |

Global classes: `.edge` (mono amber tabular), `.label`, `.tabular`, `.skeleton` (shimmer), `.narrow` (condensed
Archivo for tracks, tabs, segmented controls). Base: dark `color-scheme`, 14 px body, red caret and 2 px red focus
outline, thin scrollbars; `prefers-reduced-motion` cuts all CSS animation. Keyframes for the landing fog, Ken Burns,
ticker and voice bars are also in `index.css`. The site is dark only; there is no light theme.

The landing and sign-in use the brand palette from `brandmark.tsx` and `Landing.tsx` (ink, silver, coral `#ff6a4d`),
which is separate from the app tokens.

---

## 10. Gotchas

1. **Dev hits production.** `npm run dev` proxies to the live API by default. Set `RIGVIDEO_API` to work against
   another instance.
2. **Unused code fails the build.** `noUnusedLocals`/`noUnusedParameters` are on and CI runs `tsc -b`. There is no
   ESLint setup; the `eslint-disable` comments in the code have no effect.
3. **File plus text in the composer.** If a file is chosen *and* the text box has text, the file is **not uploaded**:
   the story is created from the text with `kind: "file"` and the file's name (`store.ts:291-299`). For `.txt`/`.md`
   this is by design (their text was copied in); for a PDF or `.docx` with typed text, the document is dropped.
4. **One visible job per story.** `jobs[id]` is the server's first of write/search/check (voice only when failed). A
   running search hides a running check, for example.
5. **Optimistic state can be overwritten.** Only dirty stories are merged; a clean story is replaced by each poll.
   Local-only changes outside `mutate`/`set` (for example the optimistic `approveScript` state) last until the next
   poll or the action's reply.
6. **Edits made right as a check finishes.** The editor's VO cuts survive a poll only while both the local and server
   edit are `ready` (`store.ts:124`). A new check replaces the beats.
7. **Queue badge wording.** `QueueBadge` says "Rendering" for `queue[0]` even when it is only queued and waiting for
   the 00:00 window (`shell.tsx:57-73`). The Desk's queue panel shows the `waitNote` correctly.
8. **Move up** is offered only from the third queue row (`Desk.tsx:312`); the server only reorders queued jobs.
9. **Render time estimates disagree.** The composer uses 23 min per minute of video (`Desk.tsx:13`), Review uses
   0.23 min per second, about 14 min per minute (`Review.tsx:13`). Review's "Ready at" ignores the render window.
   Both are rough browser guesses; the queue's `etaIso` comes from the server.
10. **Landing anchors are empty when signed out.** The anchor strip reads `state.anchors`, which only `/api/desk`
    fills, and that needs a session. Signed-out visitors see an empty strip.
11. **Sign-up is a stub** (SignIn shows a message). Invite (Settings) is disabled. Instagram/Facebook/X are static
    labels.
12. **Browser notifications** for finished renders only fire if permission was already granted; nothing asks for it.
13. **Script's format control** checks `p.versions`, while the Desk and Settings check `state.formats`.
14. **"Delete" is archive.** `/archive` sets `_archived` on the server; the story is hidden, not removed. The server
    refuses while a job is running.
15. **Times** are formatted with `timeZone: "Asia/Kolkata"` everywhere (`ui.tsx:21-24`, Desk greeting, Post card), so
    they read IST whatever the browser's zone.
16. **React StrictMode** is on (`main.tsx`): in dev, effects run twice. `boot()` only returns early once `ready` is
    true, so in dev the first `/api/desk` load can run twice.
19. **The SPA fallback** route is registered only if `dist/` exists when the API process starts
    (`server/app.py:1023`).
