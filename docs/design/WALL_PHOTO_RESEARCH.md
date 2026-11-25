# Wall photo: research and recommended method (2026-10-11)

**Goal:** for each story, find ONE photo for the studio screen behind the anchor. It must show THIS story: the scene of
this event, its named subject (a person, or a film's poster), or the specific place or object involved. It must be
high-resolution, with no burned-in text, and not a file photo. Its source and credit must be auditable.

## 1. Why our five attempts failed

| Attempt | Result | Root cause |
|---|---|---|
| The story's 12 og:image thumbnails | Mixed: stock, Commons maps, text cards | No relevance signal, and the pool is too small |
| Vision LLM judging pixels | Called a Pexels model "Abhijeet Dipke" | Vision models can't verify identity or event |
| Bing scraping + LLM queries + title words | Titles matched, images often generic, graphics or file photos | The title says what the page is about, not what the photo shows. The Bing API was also retired on 11 Aug 2025, and scraping breaks Microsoft's terms |
| GDELT image API | Rejected with "one request every 5 s" | Throttled; no captions or credit |
| "Photo most outlets used" (pHash consensus) | Good for 3 of 5; Dipke and Panama got file photos | File photos are the most reused images |

**The key research finding (NewsCLIPpings, EDIS):** image-text models such as CLIP match random news image/caption
pairs 97% of the time. They drop to ~67-70% when the wrong image shows the same kind of scene, the same person or
similar meaning. **Pixels can't tell "this quake's rubble" from "a quake's rubble". Only text evidence can: the
photo's caption, its date and its place.** This is also how wire agencies and newsrooms work: captioned, dated,
credited photos, which editors choose.

## 2. Recommended pipeline

### Step A: understand the story (keywords done properly)
1. **Entities.** The LLM extracts the named entities from the headline, deck and first paragraphs. Each one is linked
   to **Wikidata** (`wbsearchentities`, free, no key). That gives us:
   - its type: person, place, event, film/work, ship/aircraft or organisation;
   - official labels and aliases, **including the local-language name** (P1559 native name, labels in the
     country's languages);
   - its **P18 image** (a reference portrait, or a film poster);
   - its **Commons category** (P373);
   - its **country** (P17), which tells us the local language(s).
2. **Visual words only.** Keep concrete, picturable nouns (rubble, collapsed, airport, missile, poster). Drop
   abstract ones (citizenship, moves, strip). Source: the Brysbaert concreteness norms, or simply ask the LLM to keep
   only "what a camera could see".
3. **8-12 queries, not 3, in four types:**
   - **scene**: place + event + visual noun;
   - **person**: the exact name in quotes (+ role);
   - **place or landmark**;
   - **object or work**: "NAZA" documentary poster.

   Every query follows these rules:
   - exact names in **quotes**, so search engines don't "correct" NAZA to NASA;
   - written in **English and the local language** (Spanish for Panama, Arabic for Saudi Arabia, Hindi/Marathi for
     India), with names taken from Wikidata rather than translated by the LLM;
   - some restricted to **2-3 local outlets** with `site:` (prensa.com, tvn-2.com …);
   - **recency** filter (past 24 h / past week).
4. **Feedback round.** Mine new words from the captions of the first good results (local spellings, place names) and
   run one more round.

Example (Panama): `"Santa Catalina" Veraguas terremoto daños edificios` · `sismo 7.7 Veraguas casas colapsadas` ·
`"Santa Catalina" Veraguas earthquake damage` · `site:prensa.com sismo Veraguas` · Commons "2026 Veraguas earthquake".

Example (NAZA): `"NAZA" documentary poster` · `"NAZA" film` · `"Yuval Abraham" "Rachel Szor"` · the Hebrew/Arabic
title (taken from local coverage) · `site:haaretz.com "NAZA"`.

### Step B: harvest candidates WITH their captions (sources, best first)
1. **Our own coverage (no key, available today).** Each merged story has **50-150 member articles** in our
   database. From each page we fetch:
   - og:image + **og:image:alt**;
   - **JSON-LD `ImageObject.caption` / `datePublished`**;
   - **`<figure>` image + `<figcaption>`**;
   - the **IPTC/XMP caption, date and city** embedded in the JPEG itself, which wire photos usually keep (readable
     with Pillow, no install).

   Measured today: **32 of 59** Panama pages and **93 of 149** Dipke pages expose captions. An example: franceinfo's
   "A damaged building in Santa Catalina, Veraguas province, Panama, 9 October 2026 (AFP)".
2. **A legal search API, replacing Bing scraping.** Results are captioned by their page, then gated by Step C.
   - **Brave Search API** (images and news, its own index): about $5 per 1,000 queries, with a small free credit.
   - and/or **Serper.dev** (Google results): 2,500 free queries, then about $1 per 1,000.
   - At about 5 stories × 12 queries a day, that is under $2 a month.
3. **Wikidata P18 / Wikimedia Commons**: free, licensed, with artist and licence. Use it for named people,
   places and buildings, and for films (their P18 is usually the poster). Commons also has same-day uploads of big
   events.
4. **Optional, NewsAPI.ai / Event Registry** (free 2,000 searches a month): more same-event articles and their
   images, from outside our own database.

### Step C: hard gates (text evidence, deterministic)
- The caption, alt text or page title must name a **linked entity** (any alias, any language) **and** the event or
  place.
- **File-photo rejection, three ways:**
  - the caption says "FILE PHOTO", "FILE -", "archivo", "imagen de archivo", "representational" or "file image";
  - the IPTC/page date is before the event;
  - **the same image (perceptual hash) already appears in our database before the story started**. This is the
    pHash work turned around: reuse now means "file photo", not "best photo".
- Quality: at least 1000 px wide, landscape, no collage or duplicated halves, less than 4% burned-in text, not from a
  stock site, no watermark.

### Step D: rank (the LLM reads text, never judges pixels)
- The text LLM ranks the remaining candidates from their **caption + page title + date + outlet** (multilingual).
  It picks the photo whose caption describes the event scene or subject on the right date.
- Optional (needs a model download on trijya, about 1-3 GB; ask first):
  - **SigLIP-2 / OpenCLIP** rerank against the scene prompt, with negatives: "a map", "an infographic", "a logo",
    "a screenshot of text", "a collage", "a TV graphic", "a seismograph chart". This catches graphics that slip past
    the caption check.
  - **Qwen3-VL-Reranker** (Apache-2.0) as a second-stage score (the CERTH MediaEval-2025 pattern).
- Optional, person stories only: a **face check** against the person's Wikidata P18 portrait. **facenet-pytorch**
  (MIT) is licence-safe; InsightFace models are non-commercial.

### Step E: fallbacks
The subject's Wikidata P18 / Commons image (portrait, poster, landmark), then the DNL logo card.

### Provenance (for rights later)
For each pick, save to `meta.json`: the image URL, the page URL, the outlet, the caption, the credit (the IPTC
by-line/credit) and the fetch time.

## 2b. FREE-ONLY STRATEGY (user decision 2026-10-11: no paid options)

**Our usage:** about 6 stories a day (5 picks plus reserve swaps), capped at 8 searches each. That is about 50 a day,
or about 1,500 a month. Every source below is free; the quotas were checked on the vendors' pages on 11 Oct 2026.

**Layer 0: free, no key, unlimited. Most candidates come from here.**
1. **Our own coverage.** 50-150 member articles per story, from our database. For each page we take og:image,
   og:image:alt, the JSON-LD caption and date, the figcaption, and the caption, date and city embedded in the image
   file (IPTC/XMP).
2. **Wider coverage in the local language, from free news RSS:**
   - **Bing News RSS** (`bing.com/news/search?q=…&format=rss`, a published feed, not the retired API). Tested
     11 Oct: "terremoto Panamá" returned 12 Spanish articles, each with the real article URL inside the link.
   - **Local outlets' own RSS feeds.**
   - Google News RSS returned nothing in a test from the Mac; retest from trijya.

   These give more article pages, which are then harvested exactly as in item 1.
3. **Wikidata + Wikipedia + Wikimedia Commons APIs** (free, needs only a User-Agent):
   - entity linking;
   - local-language names;
   - P18 portraits, posters and landmarks;
   - the Commons category of the event (same-day uploads, with licence and artist).
4. **GDELT DOC API.** Free, but no faster than 1 request per 5 s, so it is used sparingly as an extra article and
   image finder.

**Layer 1: free monthly tiers, with keys. Used only when layer 0 is thin.** Rotated by remaining quota:
- **Brave Search API**: $5 free credit every month, about 1,000 image/news searches. It may need a card on file;
  nothing is charged under $5.
- **Tavily**: 1,000 credits a month, renews on the 1st, no card, can return images.
- **SerpAPI**: 250 searches a month (Google Images/News).
- **Reserve, probably one-time**: Serper.dev (2,500 free queries) and NewsAPI.ai/Event Registry (2,000 searches).

The renewing tiers add up to about 2,250 a month, against our need of about 1,500. A local counter tracks each
provider's monthly usage and never goes past its free amount. If every quota is used up, layer 0 alone continues.

**Free models (optional, open weights, downloaded once to trijya with the user's go):**
- SigLIP-2 / OpenCLIP: rejects maps, graphics and collages;
- facenet-pytorch (MIT): face check against the Wikidata portrait.

**Not usable for free:** the wire APIs (AP, Reuters, AFP). Getty's free API is search and embed only, and an embed
can't go into a video. Bing's API is retired, and scraping it breaks its terms, so it is removed.

## 3. Best quality: a wire subscription (needs a RIG/DNL contract; NOT used, free-only decision)
**AP Media API**, **Reuters Connect**, or **Getty editorial with a download licence** (which includes AFP). These give
searchable, captioned, dated, high-resolution and **rights-cleared** event photos: quality and rights solved together.
This is how Lumen5, Pictory, Wibbitz and the wires' own video tools solve it: licensed captioned libraries, not the
open web.

## 4. What it needs
- **No key needed:** Step A (Wikidata), B1 (our own coverage, captions, IPTC), B3 (Commons), C, D (text LLM) and E.
  **This alone can run tomorrow.**
- **A key, which you sign up for:** a Brave Search API key and/or a Serper key (B2), and optionally Event Registry
  (B4).
- **A model download, with your go:** SigLIP-2/OpenCLIP (and optionally Qwen3-VL-Reranker, facenet-pytorch) on trijya.
- **A RIG decision:** a wire subscription (section 3).

## 5. Links
- NewsCLIPpings (why pixels can't confirm the event): https://github.com/g-luo/news_clippings · https://arxiv.org/pdf/2104.05893
- EDIS, entity-driven news image search: https://aclanthology.org/2023.emnlp-main.297
- MediaEval NewsImages: https://ceur-ws.org/Vol-3658/ · CERTH 2025 two-stage pipeline: https://github.com/IDT-ITI/NewsImages-MediaEval2025
- TIB cross-modal entity consistency (Wikidata linking + reference images + face check): https://github.com/TIBHannover/cross-modal_entity_consistency
- Qwen3-VL-Reranker: https://github.com/QwenLM/Qwen3-VL-Embedding · OpenCLIP: https://github.com/mlfoundations/open_clip
- extruct (JSON-LD/microdata): https://github.com/scrapinghub/extruct · newspaper4k: https://github.com/AndyTheFactory/newspaper4k
- facenet-pytorch: https://github.com/timesler/facenet-pytorch · text visualness: https://aclanthology.org/2023.emnlp-main.147
- Bing Search API retirement: https://learn.microsoft.com/en-us/lifecycle/announcements/bing-search-api-retirement
- Brave Search API: https://brave.com/search/api/ · Serper: https://serper.dev · Event Registry: https://newsapi.ai/plans
- AP Media API: https://developer.ap.org · Getty API: https://developers.gettyimages.com
