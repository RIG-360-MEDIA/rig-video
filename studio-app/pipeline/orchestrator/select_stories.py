"""SELECT: decide today's 5 video stories + 10 reserves from DNL, with no human involved.

Pipeline: candidates (DNL eligibility rule) -> event grouping (fragment fix) -> hard-news filter (user rule) ->
event score -> pick with diversity caps -> selection.json (full audit trail).

Sources:
  db   RIG Hetzner box Postgres (the source DNL is fed from), read-only role over Tailscale (ANALYTICS_DB_URL).
       Production path: full fields incl. momentum, tier-1, follow-ups. Editor kills = story page no longer public.
  api  public https://global.democracynewslive.com/api/worldwide + story pages. Dry-run path until DB access
       exists; momentum / tier-1 / follow-up terms are 0 there (logged).
usage: python -m orchestrator.select_stories [--source api|db] [--out selection.json]
"""
import argparse
import datetime as dt
import html
import json
import math
import os
import re
import urllib.error
import urllib.request

from . import llm

SITE = "https://global.democracynewslive.com"
N_PICKS, N_RESERVES = 10, 10                                # 10 picks a day (user 2026-11-24; was 5)
# Mix caps: (per country, per story type, political types in total). Picks are 10 slots; reserves 10 slots get their own
# caps so they cannot fill up with one country or one type either. A swapped-in reserve must also fit the PICK caps.
PICK_CAPS = (3, 4, 4)                                       # for 10 picks (was 2, 2, 2 for 5)
RESERVE_CAPS = (3, 3, 4)
MIN_OUTLETS = {"pick": 8, "reserve": 3}                     # distinct outlets: a video slot needs real coverage
# Story-type weight (multiplies the coverage score). Proposed 2026-10-10 after the user found 3 of 5 picks were Indian
# politics while a hurricane and an airport-attack plot sat in reserve. Tune here.
TYPE_WEIGHT = {"war_conflict": 1.3, "terrorism_security": 1.25, "death_disaster": 1.2,
               "turmoil_unrest": 1.0, "democracy": 0.9, "corruption_crackdown": 0.8}
POLITICAL = {"turmoil_unrest", "democracy", "corruption_crackdown"}
MIN_BODY = 800

HARD_CATEGORIES = ["war_conflict", "death_disaster", "democracy", "turmoil_unrest", "terrorism_security", "corruption_crackdown"]
RUBRIC = """You decide which news events are worth a 60-second TV news-anchor video for a serious global news channel.
KEEP only hard news in exactly one of these categories:
- war_conflict: wars, military strikes, armed clashes, ceasefires, troop moves
- death_disaster: deaths, disasters, accidents or attacks with casualties, floods, quakes, crashes, collapses
- democracy: elections, voting rights, press freedom, rule of law, courts vs government, censorship
- turmoil_unrest: political crises, protests, riots, coups, resignations under pressure
- terrorism_security: terrorism, plots, hijackings, mass violence, major security threats
- corruption_crackdown: major corruption, fraud or legal crackdowns by the state
REJECT: sports (even finals and medals), entertainment, celebrity, lifestyle, business/markets, technology launches,
soft human-interest, routine announcements, individual suicides or private crimes with no public significance,
FREAK ACCIDENTS of one or two people (animal attacks, zoo or park accidents, a celebrity's accidental death) - a death is
hard news here only as part of a disaster, conflict, attack or mass-casualty event, or through a state failure;
ROUNDUPS, digests, explainers and opinion pieces, or any headline that bundles unrelated stories; cyber incidents,
hacks or pranks with no casualties and no threat to critical infrastructure or national security; and
POLITICAL RHETORIC: accusations, allegations, speeches, statements, campaign claims or threats with no concrete event
(no arrest, vote, violence, ruling, resignation, strike or casualty).
Examples: "Asian Games final: India beats Japan" -> reject (sports). "Co-pilot attacks captain in cockpit, UAE calls it
terrorism" -> keep terrorism_security. "Russia launches largest drone strike on Ukraine's grid" -> keep war_conflict.
"Floods collapse government building in Nepal" -> keep death_disaster. "New smartphone sales record" -> reject.
"Youth leaps to death from apartment tower" -> reject (private tragedy). "Ruling party accuses opposition of a
foreign-backed plot" -> reject (rhetoric). "Opposition leader detained before a protest march" -> keep turmoil_unrest.
"Former child actor killed by a tiger at a wildlife park" -> reject (freak accident). "A day of tragedy and controversy:
two stories on the same date" -> reject (roundup). "Hackers turn up supermarket fridges to 50 degrees" -> reject (no
casualties, not national security). "Hackers shut down a national power grid" -> keep terrorism_security."""

HARD_RX = re.compile(r"\b(kill|dead|death|die[sd]?|attack|strike|war|missile|drone|bomb|terror|militant|protest|clash|flood|"
                     r"earthquake|cyclone|crash|collapse|election|vote|coup|arrest|crackdown|fraud|corruption|court|sanction|"
                     r"hostage|shoot|stabb|riot|ceasefire|troops|army|military|rebel|insurg|refugee|famine|disaster|explosion|"
                     r"impeach|resign|democra|censor|hijack|massacre|invasion|seafarer|rescue)", re.I)
PRIVATE_RX = re.compile(r"\b(leaps? to death|suicide|jumps? to death|dowry|honou?r killing)\b", re.I)
# No-LLM fallback keeps only unmistakable hard news (casualties, violence, disasters): the broad HARD_RX also matches
# "election", "court", "resign" and let political rhetoric through when the LLM budget ran out (2026-10-10).
FALLBACK_RX = re.compile(r"\b(kill|dead|death|attack|strike|missile|drone|bomb|terror|flood|earthquake|quake|cyclone|"
                         r"hurricane|typhoon|crash|collapse|explosion|massacre|invasion|hostage|shoot|wildfire|landslide)", re.I)
SOFT_RX = re.compile(r"\b(cricket|football|match|tournament|league|olympic|asian games|film|movie|actor|actress|box office|"
                     r"celebrity|album|fashion|recipe|ipl|world cup|medal|grand prix|bollywood|hollywood)\b", re.I)


# ---------------------------------------------------------------- candidates
def _ts(v):
    if isinstance(v, dt.datetime):
        return v if v.tzinfo else v.replace(tzinfo=dt.timezone.utc)
    return dt.datetime.fromisoformat(str(v).replace("Z", "+00:00"))


def _get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "anchor-studio/1.0 (+video desk)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def load_api():
    d = json.loads(_get(f"{SITE}/api/worldwide?scope=world"))["data"]
    cards = []
    for key in ("topStories", "aroundTheWorld", "democracy"):
        cards += d.get(key) or []
    for sec in d.get("sections") or []:
        cards += sec.get("stories") or []
    flat = []
    for c in cards:
        flat += c["members"] if "members" in c else [c]          # event hubs carry their member cards
    out, seen = [], set()
    for c in flat:
        if c["id"] in seen or not c.get("hasArticle", True):
            continue
        seen.add(c["id"])
        out.append({"id": c["id"], "title": c["title"], "deck": c.get("deck") or "", "body": None,
                    "topic": c.get("topic") or "OTHER", "country": c.get("country") or "XX",
                    "sources": int(c.get("independentSources") or 1), "articles": int(c.get("articleCount") or 1),
                    "last_seen": _ts(c["lastSeenAt"]), "first_seen": None,
                    "entity": c.get("dominantEntity"), "entities": [c["dominantEntity"]] if c.get("dominantEntity") else [],
                    "members": set(), "images": [u for u in [c.get("image")] + (c.get("imageAlts") or []) if u],
                    "recent3h": 0, "prior3h": 0, "tier1_share": 0.0, "followup": False, "editor": None, "src": set()})
    return out


def fetch_body_api(sid):
    """Story body from the server-rendered long-read page (api mode only)."""
    s = _get(f"{SITE}/long-read/{sid}")
    ps = [html.unescape(re.sub(r"<[^>]+>", "", p)).strip() for p in re.findall(r"<p[^>]*>(.*?)</p>", s, re.S)]
    ps = [p for p in ps if len(p) > 80 and not p.startswith("←")]
    return "\n\n".join(ps)


# Source (user decision 2026-10-10): the RIG Hetzner box's Postgres, read-only role, over Tailscale. That box is
# overloaded (load ~8, swap full): the query starts from the ~3k generated stories and touches only their members.
POOL_SQL = """
WITH cand AS (
  SELECT sc.story_id, coalesce(nullif(g.headline, ''), sc.representative_title) AS title, g.deck, g.body,
         coalesce(nullif(g.topic, ''), nullif(sc.topic, ''), 'OTHER') AS topic, coalesce(nullif(sc.subject_country, ''), 'XX') AS country,
         sc.independent_source_count AS sources, sc.article_count AS articles, sc.last_seen_at, sc.first_seen_at,
         sc.primary_entities, g.generated_image->>'url' AS gen_image
  FROM analytics.story_generated_v8 g JOIN analytics.story_clusters_v8 sc USING (story_id)
  WHERE sc.suppression_reason IS NULL AND sc.redirected_to IS NULL
    AND NOT EXISTS (SELECT 1 FROM analytics.story_dedup dd WHERE dd.story_id = sc.story_id)
    AND sc.last_seen_at >= now() - interval '7 days'
    AND g.body IS NOT NULL AND g.headline NOT ILIKE '%%(parse-fail)%%' AND left(btrim(g.body), 1) <> '{'
    AND g.body !~ '(^|\\n)\\s*[\\[{]\\s*[''"\\[{]'      -- a section str()'d as a Python dict/list; DNL hides these (body-guard.ts)
    AND g.status LIKE 'PUBLISHABLE%%' AND g.strategy <> 'stub' AND length(g.body) >= 800
    AND g.updated_at <= now() - interval '15 minutes'
  ORDER BY sc.last_seen_at DESC LIMIT 1500),
mem AS (SELECT m.story_id, array_agg(m.article_id::text) AS members,
               count(*) FILTER (WHERE coalesce(a.published_at, a.collected_at) >= now() - interval '3 hours') AS recent3h,
               count(*) FILTER (WHERE coalesce(a.published_at, a.collected_at) <  now() - interval '3 hours'
                                  AND coalesce(a.published_at, a.collected_at) >= now() - interval '6 hours') AS prior3h,
               avg((coalesce(a.source_tier, 9) = 1)::int)::float AS tier1_share,
               (array_agg(a.thumbnail_url ORDER BY coalesce(a.source_tier, 9), a.published_at DESC NULLS LAST)
                  FILTER (WHERE a.thumbnail_url <> ''))[1:8] AS thumbs,
               array_agg(DISTINCT a.source_id::text || ':' || coalesce(nullif(a.source_country, ''), 'XX'))
                  FILTER (WHERE a.source_id IS NOT NULL) AS src
        FROM analytics.story_cluster_members_v8 m JOIN articles a ON a.id = m.article_id
        WHERE m.story_id IN (SELECT story_id FROM cand) GROUP BY 1)
SELECT c.story_id::text AS id, c.title, c.deck, c.body, c.topic, c.country, c.sources, c.articles, c.last_seen_at, c.first_seen_at,
       (SELECT array_agg(k) FROM (SELECT e.key AS k FROM jsonb_each_text(c.primary_entities) e
                                   ORDER BY (e.value)::int DESC LIMIT 3) t) AS entities,
       c.gen_image, mem.members, mem.recent3h, mem.prior3h, mem.tier1_share, mem.thumbs, mem.src
FROM cand c LEFT JOIN mem USING (story_id)
"""


def _connect():
    import psycopg                                                 # tools venv; only needed in db mode
    con = psycopg.connect(os.environ["ANALYTICS_DB_URL"], autocommit=True, connect_timeout=20)
    con.execute("SET default_transaction_read_only = on")
    con.execute("SET statement_timeout = '120s'")                  # never hold a long query on the shared prod box
    return con


def site_live(sid):
    """Is the story public on DNL right now? Editor kills/holds live on DNL's Neon, which we cannot read, so the story
    page is the veto: 404/410 = killed, held, merged or aged out -> no video. None = site unreachable (unknown)."""
    try:
        _get(f"{SITE}/long-read/{sid}", timeout=20)
        return True
    except urllib.error.HTTPError as e:
        return False if e.code in (404, 410) else None
    except Exception:  # noqa: BLE001
        return None


def load_db(log=print):
    import psycopg
    follow = set()
    with _connect() as con:
        cur = con.cursor(row_factory=psycopg.rows.dict_row)
        cur.execute(POOL_SQL)
        rows = cur.fetchall()
        try:                                                       # scheduled follow-ups in the next 12 h
            cur.execute("SELECT DISTINCT m.story_id::text AS id FROM article_events ev "
                        "JOIN analytics.story_cluster_members_v8 m ON m.article_id = ev.article_id "
                        "WHERE ev.is_future AND ev.effective_event_date BETWEEN now() AND now() + interval '12 hours'")
            follow = {r["id"] for r in cur.fetchall()}
        except Exception as e:  # noqa: BLE001
            log(f"WARNING: follow-up query failed ({type(e).__name__}); follow-up term = 0")
    return [{"id": r["id"], "title": r["title"], "deck": r["deck"] or "", "body": r["body"],
             "topic": r["topic"], "country": r["country"], "sources": r["sources"] or 1, "articles": r["articles"] or 1,
             "last_seen": _ts(r["last_seen_at"]), "first_seen": r["first_seen_at"] and _ts(r["first_seen_at"]),
             "entity": (r["entities"] or [None])[0], "entities": r["entities"] or [], "members": set(r["members"] or []),
             "images": [u for u in [r["gen_image"]] + (r["thumbs"] or []) if u],
             "recent3h": r["recent3h"] or 0, "prior3h": r["prior3h"] or 0, "tier1_share": r["tier1_share"] or 0.0,
             "followup": r["id"] in follow, "editor": None, "src": set(r["src"] or [])} for r in rows]


def refresh(fragment_ids, lead_id):
    """(article count now across the event's fragments, lead's current body, lead's current headline) — db mode."""
    with _connect() as con:
        n = con.execute("SELECT coalesce(sum(article_count), 0) FROM analytics.story_clusters_v8 WHERE story_id::text = ANY(%s)",
                        (list(fragment_ids),)).fetchone()[0]
        row = con.execute("SELECT body, headline FROM analytics.story_generated_v8 WHERE story_id::text = %s "
                          "ORDER BY updated_at DESC LIMIT 1", (lead_id,)).fetchone()
    return int(n), (row or (None, None))[0], (row or (None, None))[1]


def editor_status(ids):
    """Fresh kill/hold check right before a story renders. Returns {id: 'killed'} for stories no longer public."""
    return {i: "killed" for i in ids if site_live(i) is False}


# ---------------------------------------------------------------- events
STOP = set("year old claim life live death dead kill the and for with from over amid after into says said new its his her their that this are was were has have "
           "will who what how why than more most first last one two three inside behind within against between".split())


def _sig(t):
    t = re.sub(r"[^a-z0-9\s]", " ", t.lower().replace("’", "'").replace("'s", ""))
    return {w[:-1] if len(w) > 4 and w.endswith("s") else w for w in t.split() if (len(w) >= 3 or w.isdigit()) and w not in STOP}


def _jac(a, b):
    return len(a & b) / max(1, len(a | b))


def group_events(cands, log=print, generous=False):
    """Group fragments of the same real-world event (DNL fragments big stories into many clusters).

    Leader clustering, not union-find: a fragment joins a group only if it matches that group's LEAD (the strongest
    fragment), so unrelated stories can never chain together through intermediate fragments."""
    sig = {c["id"]: _sig(c["title"]) for c in cands}
    df = {}
    for t in sig.values():
        for w in t:
            df[w] = df.get(w, 0) + 1
    rare = max(3, int(0.03 * len(cands)))                          # a word only a few stories use ("flydubai", "fairford")

    def same(a, b):
        sa, sb = sig[a["id"]], sig[b["id"]]
        shared = sa & sb
        close = abs((a["last_seen"] - b["last_seen"]).total_seconds()) < 72 * 3600
        return bool((a["members"] & b["members"]) or
                    (a["entity"] and a["entity"] == b["entity"] and _jac(sa, sb) >= 0.3) or
                    (close and len(set(a["entities"][:3]) & set(b["entities"][:3])) >= 2) or
                    (close and _jac(sa, sb) >= 0.5) or
                    # generous candidate rule (a rare shared word, e.g. "flydubai") only when the LLM will confirm
                    # the merge: on headlines alone it cannot tell "mine collapse" A from B (measured 2026-10-03)
                    (generous and close and len(shared) >= 2 and any(df[w] <= rare and not w.isdigit() for w in shared)))

    groups = []
    for c in sorted(cands, key=lambda x: (-x["sources"], -x["last_seen"].timestamp())):
        g = next((g for g in groups if same(g[0], c)), None)
        if g:
            g.append(c)
        else:
            groups.append([c])
    return groups


def confirm_groups(events, log=print):
    """LLM yes/no per fragment so a false merge (e.g. three different mine accidents) is split again.
    Short ids ("3.1") instead of UUIDs and batches of <= 30 fragments keep each request inside Groq's 8k tokens/min.
    Raises llm.LLMUnavailable if the LLM cannot answer (the caller then falls back to strict-rule groups)."""
    multi = [g for g in events if len(g) > 1]
    sid = {f"{k}.{i}": c for k, g in enumerate(multi) for i, c in enumerate(g)}
    ask = [{"group": k, "fragments": [{"id": f"{k}.{i}", "title": c["title"], "deck": c["deck"][:120]} for i, c in enumerate(g)]}
           for k, g in enumerate(multi)]
    batches, cur = [], []
    for a in ask:
        if cur and sum(len(x["fragments"]) for x in cur) + len(a["fragments"]) > 30:
            batches.append(cur)
            cur = []
        cur.append(a)
    batches += [cur] if cur else []
    answers = {}
    for bt in batches:
        r = llm.chat_json("You group news reports by real-world event. Same event = the same incident or development "
                          "and its direct follow-ups, not merely the same country, topic or type of incident.",
                          "For each group, split the fragments into sets that describe the SAME real-world event. Reply "
                          'JSON {"groups":[{"group":0,"sets":[["0.0","0.1"],["0.2"]]}]}.\n' + json.dumps(bt, ensure_ascii=False),
                          max_tokens=3000, log=log)
        answers.update({x.get("group"): x.get("sets") for x in r.get("groups") or [] if isinstance(x, dict)})
    out = [g for g in events if len(g) == 1]
    for k, g in enumerate(multi):
        sets = answers.get(k)
        ids = {f"{k}.{i}" for i in range(len(g))}
        if (not isinstance(sets, list) or not all(isinstance(x, list) for x in sets)  # malformed answer:
                or {str(i) for x in sets for i in x} != ids):     # keep the rule-based grouping
            out.append(g)
            continue
        out += [[sid[str(i)] for i in x] for x in sets if x]
    return out


def classify(events, log=print):
    """Hard-news label per event: LLM with the user's rubric; keyword rules only if no LLM is reachable."""
    items = [{"id": e["lead"]["id"], "headline": e["lead"]["title"], "deck": e["lead"]["deck"][:300], "topic": e["lead"]["topic"]}
             for e in events]
    labels = {}
    if llm.available():
        try:
            for k in range(0, len(items), 10):
                res = llm.chat_json(RUBRIC, 'Label each item. Reply JSON {"labels":[{"id":"..","keep":true|false,'
                                    '"category":"one of the categories or reject","country":"ISO-3166 alpha-2 code of the '
                                    'country where the event happens, or XX","reason":"<=15 words"}]}.\n'
                                    + json.dumps(items[k:k + 10], ensure_ascii=False), max_tokens=2500, log=log)
                labels.update({x["id"]: x for x in res.get("labels") or [] if isinstance(x, dict) and x.get("id")})
        except llm.LLMUnavailable as e:
            log(f"classifier LLM unavailable ({e}); using keyword rules")
    for it in items:
        if it["id"] not in labels:
            text = it["headline"] + " " + it["deck"]
            keep = (it["topic"] != "SPORTS" and not SOFT_RX.search(text) and not PRIVATE_RX.search(text)
                    and bool(FALLBACK_RX.search(text)))
            labels[it["id"]] = {"keep": keep, "category": "rule", "reason": "keyword rule (no LLM)"}
        lb = labels[it["id"]]
        if it["topic"] == "SPORTS" or lb.get("category") not in HARD_CATEGORIES + ["rule"]:
            lb["keep"] = False                                     # user rule: never sports/entertainment
    for e in events:
        e["label"] = labels[e["lead"]["id"]]
        c = str(e["label"].get("country") or "").upper()
        if re.fullmatch(r"[A-Z]{2}", c) and c != "XX" and c != e["country"]:   # DNL's subject_country can be wrong
            e["label"]["dnl_country"], e["country"] = e["country"], c          # (a Panama quake tagged IR): casting
    return events


# ---------------------------------------------------------------- score + pick
def summarise(group, now):
    lead = max([c for c in group if c["sources"] >= 3] or group,
               key=lambda c: (c["last_seen"], c["sources"]) if c["sources"] >= 3 else (c["sources"], c["last_seen"]))
    newest = max(c["last_seen"] for c in group)
    first = min((c["first_seen"] or c["last_seen"]) for c in group)
    src = set().union(*(c["src"] for c in group))                # "<source_id>:<source country>" over all fragments
    return {"lead": lead, "fragments": group, "src": src,         # distinct outlets; api mode has none -> best fragment
            "sources": len({x.split(":")[0] for x in src}) or max(c["sources"] for c in group),
            "recent3h": sum(c["recent3h"] for c in group), "prior3h": sum(c["prior3h"] for c in group),
            "tier1_share": max(c["tier1_share"] for c in group),
            "followup": any(c["followup"] for c in group), "age_h": max(0.0, (now - newest).total_seconds() / 3600),
            "span_h": (newest - first).total_seconds() / 3600, "topic": lead["topic"], "country": lead["country"],
            "images": [u for c in [lead] + [x for x in group if x is not lead] for u in c["images"]]}


def score(e):
    """Coverage x freshness x stability x story-type weight. Foreign coverage (outlets outside the event's own country)
    counts extra: DNL's source pool is ~half Indian (812 of ~1,700), so raw source counts favour Indian domestic news."""
    foreign = len({x.split(":")[0] for x in e["src"] if x.split(":")[1] not in (e["country"], "XX")})
    base = (math.log1p(e["sources"]) + 0.8 * math.log1p(foreign) + 0.6 * math.log1p(e["recent3h"])
            - 0.3 * math.log1p(e["prior3h"]) + 0.4 * e["tier1_share"] + 0.5 * e["followup"])
    fresh = 0.03 + 0.97 * 2 ** (-e["age_h"] / 12)
    unstable = e["span_h"] < 3 and len(e["fragments"]) > 1          # very young multi-report event: facts still moving
    w = TYPE_WEIGHT.get((e.get("label") or {}).get("category"), 1.0)  # 1.0 until classified (and for keyword-rule labels)
    e["score_parts"] = {"base": round(base, 3), "foreign_outlets": foreign, "fresh": round(fresh, 3),
                        "stability": 0.5 if unstable else 1.0, "type": w}
    e["score"] = round(base * fresh * e["score_parts"]["stability"] * w, 4)
    return e


def _typ(e):
    cat = e["label"].get("category")
    return cat if cat in TYPE_WEIGHT else e["topic"]               # keyword-rule fallback: cap by DNL topic instead


def fits(chosen, e, caps=PICK_CAPS):
    """Would adding e to `chosen` keep the mix caps? Works on internal events and on published (_pub) dicts."""
    per_country, per_type, political = caps
    return (sum(c["country"] == e["country"] for c in chosen) < per_country
            and sum(_typ(c) == _typ(e) for c in chosen) < per_type
            and not (e["label"].get("category") in POLITICAL
                     and sum(c["label"].get("category") in POLITICAL for c in chosen) >= political))


def saga_index(events):
    """same(c, e): the two events are one story or saga under different headlines. Either their headlines share >= 2
    words one of which is rare, or their texts share >= 3 rare NAMES (Dipke/Jantar/Gyanesh, Abha/Houthi/Khalid). A name
    is a capitalised word never written in lower case anywhere in the pool ("Panama" yes, "Power"/"Things" no), and rare
    means it appears in only a handful of the events, so common names (India, Trump, Ukraine) never count.
    Returns (same, explain) where explain(c, e) lists the shared rare names for the log."""
    sig = {id(e): _sig(e["lead"]["title"]) for e in events}
    df = {}
    for t in sig.values():
        for w in t:
            df[w] = df.get(w, 0) + 1
    rare = max(2, int(0.05 * len(events)))
    text = {id(e): f"{e['lead']['deck']} {e['lead']['body'] or ''}" for e in events}
    lower = set(re.findall(r"\b[a-z]{4,}\b", " ".join(text.values())))
    names = {k: {w.lower() for w in re.findall(r"\b[A-Z][a-z]{3,}\b", t)} - lower for k, t in text.items()}
    ndf = {}
    for ns in names.values():
        for w in ns:
            ndf[w] = ndf.get(w, 0) + 1
    nrare = max(3, int(0.06 * len(events)))
    explain = lambda c, e: sorted(w for w in names[id(c)] & names[id(e)] if ndf[w] <= nrare)

    def same(c, e):
        sh = sig[id(c)] & sig[id(e)]
        return (len(sh) >= 2 and any(df[w] <= rare and not w.isdigit() for w in sh)) or len(explain(c, e)) >= 3
    return same, explain


def merge_sagas(events, now, log=print):
    """Deterministic last merge (after the LLM): fragments of one saga become one event, so its coverage is counted
    together. The strongest event leads: its headline, script article, label and country are kept."""
    same, explain = saga_index(events)
    groups = []
    for e in sorted(events, key=lambda x: -x["score"]):
        g = next((g for g in groups if e["label"]["keep"] and g[0]["label"]["keep"] and same(g[0], e)), None)
        g.append(e) if g else groups.append([e])                    # only hard-news events merge (a rejected rhetoric
    out = []                                                       # story must never swallow a real one)
    for g in groups:
        if len(g) == 1:
            out.append(g[0])
            continue
        lead = g[0]
        m = summarise([f for x in g for f in x["fragments"]], now)
        m.update(lead=lead["lead"], label=lead["label"], country=lead["country"], topic=lead["topic"])
        out.append(score(m))
        log(f"merged {len(g)} reports of one story {explain(lead, g[1])[:5]}: {lead['lead']['title'][:60]}")
    return out


def pick(events, body_fn=None, log=print, live_fn=None, exclude=frozenset()):
    """Two passes over the hard-news events, best score first: N_PICKS under PICK_CAPS, then N_RESERVES under
    RESERVE_CAPS (counted among the reserves) from everything not picked. Each needs a public page and a >=800-char body.
    Duplicate guard (saga_index): never two reports of the same story or saga."""
    same_story, explain = saga_index(events)
    made = lambda e: e["lead"]["id"] in exclude or any(c["id"] in exclude for c in e["fragments"])
    ranked = sorted([e for e in events if e["label"]["keep"] and not made(e)], key=lambda x: -x["score"])
    if exclude:                                                    # before the slots fill: picks + reserves stay full
        log(f"SELECT: {sum(made(e) for e in events if e['label']['keep'])} story(ies) already made or tried left out")
    picks, reserves, taken, bad = [], [], set(), set()             # bad: not public / no body (checked once)

    def usable(e):
        if id(e) in bad:
            return False
        if live_fn and live_fn(e["lead"]["id"]) is False:        # DNL does not publish it: no video (a sibling fragment
            log(f"skip, not public on DNL (killed/held/merged): {e['lead']['title'][:70]}")   # can be another angle)
            bad.add(id(e))
            return False
        if not e["lead"]["body"] and body_fn:
            try:
                e["lead"]["body"] = body_fn(e["lead"]["id"])
            except Exception as ex:  # noqa: BLE001
                log(f"body fetch failed for {e['lead']['id']}: {ex}")
        if len(e["lead"]["body"] or "") < MIN_BODY:
            bad.add(id(e))
            return False
        return True

    for out, n, caps, floor in ((picks, N_PICKS, PICK_CAPS, MIN_OUTLETS["pick"]),
                                (reserves, N_RESERVES, RESERVE_CAPS, MIN_OUTLETS["reserve"])):
        for e in ranked:
            if len(out) == n:
                break
            if id(e) in taken or e["sources"] < floor or not fits(out, e, caps):
                continue
            twin = next((c for c in picks + reserves if same_story(c, e)), None)
            if twin:
                log(f"skip same story as '{twin['lead']['title'][:40]}' {explain(twin, e)[:5]}: {e['lead']['title'][:60]}")
                continue
            if not usable(e):
                continue
            out.append(e)
            taken.add(id(e))
    for e in list(reserves):                                        # a thin day: fewer events with 8+ outlets - the best
        if len(picks) < N_PICKS and fits(picks, e, PICK_CAPS):      # reserves that fit the pick mix fill the 10
            picks.append(e)
            reserves.remove(e)
    return picks, reserves


def _pub(e):
    lead = e["lead"]
    return {"event_id": lead["id"], "headline": lead["title"], "deck": lead["deck"], "body": lead["body"],
            "topic": e["topic"], "country": e["country"], "score": e["score"], "score_parts": e["score_parts"],
            "label": e["label"], "sources": e["sources"], "foreign_outlets": e["score_parts"]["foreign_outlets"],
            "age_h": round(e["age_h"], 1),
            "fragments": [{"id": c["id"], "title": c["title"], "sources": c["sources"], "articles": c["articles"]}
                          for c in e["fragments"]],
            "supporting": [c["deck"] for c in e["fragments"] if c is not lead and c["deck"]][:6],
            "images": list(dict.fromkeys(e["images"]))[:24]}


def select(source="db", log=print, exclude=frozenset()):
    now = dt.datetime.now(dt.timezone.utc)
    cands = load_db(log) if source == "db" else load_api()
    log(f"SELECT[{source}]: {len(cands)} eligible fragments")
    events = [score(summarise(g, now)) for g in group_events(cands, log, generous=llm.available())]
    if llm.available():                                            # confirm merges only where a pick can come from
        events.sort(key=lambda x: -x["score"])
        head, rest = events[:50], events[50:]          # ponytail: unconfirmed generous merges below the head stay as-is
        try:
            events = [score(summarise(g, now)) for g in confirm_groups([e["fragments"] for e in head], log)] + rest
        except llm.LLMUnavailable as e:
            log(f"merge confirmation failed ({e}); using strict-rule groups only")
            events = [score(summarise(g, now)) for g in group_events(cands, log)]
    log(f"SELECT: {len(events)} events after grouping")
    top = sorted(events, key=lambda x: -x["score"])[:80]               # classify the plausible head only (15 slots)
    classify(top, log)
    for e in top:                                                  # re-score: type weight + corrected country
        score(e)
    top = merge_sagas(top, now, log)
    picks, reserves = pick(top, fetch_body_api if source == "api" else None, log, site_live if source == "db" else None, exclude)
    return {"generated_at": now.isoformat(), "source": source, "llm": llm.available(),
            "picks": [_pub(e) for e in picks], "reserves": [_pub(e) for e in reserves],
            "candidates": [{"event_id": e["lead"]["id"], "headline": e["lead"]["title"], "score": e["score"],
                            "parts": e["score_parts"], "keep": e["label"]["keep"], "category": e["label"].get("category"),
                            "country": e["country"], "sources": e["sources"], "why": e["label"].get("reason"),
                            "fragments": len(e["fragments"])} for e in sorted(top, key=lambda x: -x["score"])]}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="db" if os.environ.get("ANALYTICS_DB_URL") else "api")
    ap.add_argument("--out", default="selection.json")
    a = ap.parse_args()
    res = select(a.source)
    json.dump(res, open(a.out, "w"), indent=2, ensure_ascii=False, default=str)
    for k in ("picks", "reserves"):
        for e in res[k]:
            print(f"{k[:-1]:8s} {e['score']:.3f} [{e['topic']}/{e['country']}] {e['headline']}  ({len(e['fragments'])} frag)")
