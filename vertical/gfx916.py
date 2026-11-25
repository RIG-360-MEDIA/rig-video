"""Graphics on the final 9:16 video (user 2026-11-23, after CNN vertical references): word-synced captions, the
headline title card at the start, quote cards over a darkened frame. No credits. Rendered with libass (ffmpeg `ass`).
Used by assemble916.py: ass(work dir, project.json) writes work/gfx.ass from work/plan.json (cuts: beat, len, pre;
voices: beat -> wav); the final encode burns it in with ass=gfx.ass:fontsdir=FONTS.
"""
import json, pathlib, re, wave
import numpy as np
H = pathlib.Path.home()
FONTS = H / "anchor-studio/vertical/fonts"
RED = "&H00231BE3&"                                     # DNL red #E31B23 as ASS BGR
TITLE_S, CAP_MAX_CH, CAP_MAX_W = 3.5, 24, 4
QUOTE = re.compile(r"[\"“]([^\"”]{25,})[\"”]")
SAYS = r"(said|says|argued|stated|added|warned|told|wrote|noted)"


def words_of(wav):
    from faster_whisper import WhisperModel
    global _m
    if "_m" not in globals():
        _m = WhisperModel("small", device="cpu", compute_type="int8")
    r = wave.open(str(wav))
    a = np.frombuffer(r.readframes(r.getnframes()), np.int16).astype(np.float32) / 32768
    if r.getnchannels() == 2:
        a = a.reshape(-1, 2).mean(1)
    if r.getframerate() != 16000:
        a = np.interp(np.arange(0, len(a), r.getframerate() / 16000), np.arange(len(a)), a).astype(np.float32)
    segs, _ = _m.transcribe(a, language="en", word_timestamps=True)
    return [(w.word.strip(), w.start, w.end) for s in segs for w in s.words]


def script_words(text, heard):
    """The script's own words (its spelling: names, numbers) timed by what whisper heard. Matched words take whisper's
    times; the rest are spread evenly between their matched neighbours."""
    import difflib
    words = text.split()
    norm = lambda w: re.sub(r"[^\w]", "", w.lower())
    sm = difflib.SequenceMatcher(None, [norm(w) for w in words], [norm(h[0]) for h in heard], autojunk=False)
    at = [None] * len(words)
    for a, b, n in sm.get_matching_blocks():
        for i in range(n):
            at[a + i] = heard[b + i][1:]
    end = heard[-1][2] if heard else 0.0
    i = 0
    while i < len(words):
        if at[i] is None:
            j = i
            while j < len(words) and at[j] is None:
                j += 1
            lo = at[i - 1][1] if i else (heard[0][1] if heard else 0.0)
            hi = at[j][0] if j < len(words) else end
            step = max(0.05, (hi - lo) / (j - i))
            for k in range(i, j):
                at[k] = (lo + (k - i) * step, lo + (k - i + 1) * step)
            i = j
        else:
            i += 1
    return [(w, s, e) for w, (s, e) in zip(words, at)]


def ts(t):
    t = max(0, t)
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


def esc(s):
    return s.replace("\\", "").replace("{", "(").replace("}", ")")


def wrap(text, width):
    lines, cur = [], ""
    for w in text.split():
        if cur and len(cur) + 1 + len(w) > width:
            lines.append(cur); cur = w
        else:
            cur = f"{cur} {w}".strip()
    return lines + [cur] if cur else lines


def groups(words):
    """2-4 words a caption, broken after punctuation or at ~24 characters."""
    out, cur = [], []
    for w in words:
        cur.append(w)
        text = " ".join(x[0] for x in cur)
        if len(cur) >= CAP_MAX_W or len(text) >= CAP_MAX_CH or re.search(r"[.,;:!?]$", w[0]) and len(cur) >= 2:
            out.append(cur); cur = []
    return out + [cur] if cur else out


def quote_of(text):
    """(quote, who) when the beat quotes someone by name, else None."""
    m = QUOTE.search(text)
    if not m:
        return None
    before, after = text[:m.start()], text[m.end():]
    who = (re.search(rf"([A-Z][\w.'-]+(?: [A-Z][\w.'-]+){{0,3}})(?:,[^,]{{0,60}},)? {SAYS}\b[^\"“]*$", before)
           or re.search(rf"^\W*{SAYS} ([A-Z][\w.'-]+(?: [A-Z][\w.'-]+){{0,3}})", after))
    if not who:
        return None
    name = who.group(1) if who.re.pattern.startswith("([A-Z]") else who.group(2)
    return m.group(1).strip(), name


def ass(d, pj):
    pl = json.load(open(d / "plan.json"))
    p = json.load(open(pj))
    texts = {s["id"]: s["text"] for s in p["versions"]["vo_only"]}
    starts, t, seen = {}, 0.0, set()
    ends = {}
    for c in pl["cuts"]:
        if c["beat"] not in seen:
            seen.add(c["beat"]); starts[c["beat"]] = t + c["pre"]
        t += c["len"]; ends[c["beat"]] = t
    ev = []
    for b, t0 in starts.items():
        heard = words_of(d / pl["voices"][b])
        ws = script_words(texts.get(b, ""), heard) or heard
        gs = groups(ws)
        for i, g in enumerate(gs):
            a = t0 + g[0][1]
            z = t0 + (gs[i + 1][0][1] if i + 1 < len(gs) and gs[i + 1][0][1] - g[-1][2] < 0.6 else g[-1][2] + 0.25)
            ev.append(f"Dialogue: 2,{ts(a)},{ts(z)},Cap,,0,0,0,,{esc(' '.join(x[0] for x in g))}")
        q = quote_of(texts.get(b, ""))
        if q:
            a, z = t0, ends[b]
            body = "\\N".join(esc(x) for x in wrap(f"“{q[0]}”", 26))
            ev += [f"Dialogue: 0,{ts(a)},{ts(z)},Box,,0,0,0,,{{\\fad(200,200)\\p1}}m 0 0 l 1080 0 l 1080 1920 l 0 1920{{\\p0}}",
                   f"Dialogue: 1,{ts(a)},{ts(z)},Rule,,0,0,0,,{{\\fad(200,200)\\pos(80,620)\\p1}}m 0 0 l 90 0 l 90 10 l 0 10{{\\p0}}",
                   f"Dialogue: 1,{ts(a)},{ts(z)},Quote,,0,0,0,,{{\\fad(200,200)\\pos(80,660)}}{body}\\N{{\\rWho}}{esc(q[1])}"]
    title = "\\N".join(esc(x) for x in wrap(p["headline"], 20))
    ev += [f"Dialogue: 1,{ts(0)},{ts(TITLE_S)},Rule,,0,0,0,,{{\\fad(150,300)\\pos(80,300)\\p1}}m 0 0 l 90 0 l 90 10 l 0 10{{\\p0}}",
           f"Dialogue: 1,{ts(0)},{ts(TITLE_S)},Title,,0,0,0,,{{\\fad(150,300)\\pos(80,335)}}{title}"]
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,Plus Jakarta Sans ExtraBold,66,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,3.5,2,2,80,80,500,1
Style: Title,Plus Jakarta Sans ExtraBold,82,&H00FFFFFF,&H00FFFFFF,&H00000000,&H90000000,0,0,0,0,100,100,0,0,1,0,4,7,80,80,0,1
Style: Quote,Plus Jakarta Sans Bold,60,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,80,80,0,1
Style: Who,Plus Jakarta Sans ExtraBold,44,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,80,80,0,1
Style: Box,Arial,20,&H70000000,&H70000000,&H70000000,&H70000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1
Style: Rule,Arial,20,{RED},{RED},{RED},{RED},0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    (d / "gfx.ass").write_text(head + "\n".join(ev) + "\n")
    return d / "gfx.ass"


if __name__ == "__main__":
    assert quote_of('Meeks argued that the administration "has put our national security and technology edge at risk" today.') == \
        ("has put our national security and technology edge at risk", "Meeks")
    assert quote_of('"We have since stopped shipping H200s to China," a spokesperson said.') is None
    assert [len(g) for g in groups([(w, 0, 0) for w in "Russia has launched a massive aerial assault, on Ukraine today".split()])] == [4, 3, 3]
    w = script_words("Strikes hit lines critical to Zaporizhzhia's plant.", [("Strikes", 0, .3), ("hip", .3, .5), ("lines", .5, .8),
                     ("critical", .8, 1.2), ("to", 1.2, 1.3), ("Zaporizhia's", 1.3, 1.9), ("plant.", 1.9, 2.2)])
    assert [x[0] for x in w][1] == "hit" and w[1][1] >= 0.3 and w[5][0] == "Zaporizhzhia's"
    print("ok")
