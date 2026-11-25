"""Sound for the final 9:16 video (user 2026-11-23, after reference clips): a shot that shows something making a sound
(firing, launches, missiles, tanks, ships sailing, fire, damage) gets its own scene sound from our foley model
(HunyuanVideo-Foley XL, ~/foley on this box); nothing from the source clips, no music. Which shots and what sound: the
cut's "sound", suggested by the clip checker and edited on the footage page ("" = none; user 2026-11-24: static scenes
like power lines and substations get none).
  - under the voice: loud scenes (blasts, launches, fire, sirens, crowds) about 12 dB below the voice, quieter ones 24 dB
  - lead-in: the first shot starts up to LEAD s early with its sound up; the voice starts by 2 s
  - sound-ups: up to MAX_UPS times the voice pauses ~UP s at a beat boundary next to a loud shot, which is lengthened into
    the pause (from the spare footage around it) and its sound comes up to about the voice's level
  - the mix is normalised to -14 LUFS (social platforms never raise a quiet video)
Used by assemble916.py: loud() / place() decide, foley() makes the sounds, mix() lays voice and sound."""
import csv, json, pathlib, re, subprocess
H = pathlib.Path.home()
FF = str(H / "anchor-studio/repos/ffmpeg-shared/current/bin/ffmpeg")
FOLEY = H / "foley" / "HunyuanVideo-Foley"
NEG = "speech, talking, human voice, narration, music, singing"
LEAD, UP, MAX_UPS, SPACING = 1.5, 3.0, 2, 20.0
SPEAKING = r"speak|speech|podium|interview|press conference|addresses|talking|statement"
LOUD = [(3, r"explo|blast|missile|rocket|launch|strike|bomb|shell|gunfire|firing|artillery|drone attack"),
        (2, r"fire|burn|flame|siren|ambulance|firefight|police car|helicopter|jet|aircraft|crowd|protest|chant|rally|riot|clash|concert|tank|armou?r"),
        (1, r"traffic|street|port|ship|train|storm|rain|flood|wave|waterfall|engine|crane")]
UNDER = {3: -12.0, 2: -12.0, 1: -24.0, 0: -24.0}       # foley vs voice, dB, while the voice speaks
UP_DB = -3.0                                            # foley vs voice in a sound-up / the lead-in
EXTRA_S = LEAD + MAX_UPS * (UP - 0.35)                  # picture time the sound adds to a story (for the writer's length)


def run(*a, **k):
    return subprocess.run([str(x) for x in a], check=True, **k)


def loud(c):
    """-1 = no foley, else 1..3 by how loud the sound is. c: the cut (sound, kind, shows). An edit from before 2026-11-24
    has no "sound": then only clearly loud action it shows (level 2+) gets sound, never text or someone speaking."""
    s = c.get("sound")
    if s is None:
        if c.get("kind") in ("post_or_document", "speech") or re.search(SPEAKING, c.get("shows") or "", re.I):
            return -1
        lv = next((p for p, rx in LOUD if re.search(rx, c.get("shows") or "", re.I)), 0)
        return lv if lv >= 2 else -1
    return next((p for p, rx in LOUD if re.search(rx, s, re.I)), 1) if s.strip() else -1


def prompt(c):
    return c.get("sound") or c.get("shows") or " "


def place(cuts):
    """Sets pre/post (seconds a cut is lengthened at its start/end) for the lead-in and the sound-ups. Each cut needs
    beat, secs, loud, before, after (spare footage around it). Returns the indices of the sound-up cuts."""
    for c in cuts:
        c["pre"] = c["post"] = 0.0
    if not cuts:
        return []
    if cuts[0]["loud"] >= 0:                            # a lead-in only with a sound of its own: never silence
        cuts[0]["pre"] = round(min(LEAD, cuts[0]["before"]), 2)
    bounds, t = [], 0.0
    for i in range(len(cuts) - 1):
        t += cuts[i]["secs"]
        if cuts[i + 1]["beat"] != cuts[i]["beat"]:
            for j, side in ((i, "post"), (i + 1, "pre")):
                if cuts[j]["loud"] >= 2:
                    bounds.append((cuts[j]["loud"], t, j, side, i))
    ups = []
    for lv, t, j, side, i in sorted(bounds, key=lambda x: (-x[0], x[1])):
        if len(ups) == MAX_UPS or t < SPACING or any(abs(t - u[1]) < SPACING for u in ups) or j in [u[0] for u in ups]:
            continue
        other, oside = (i + 1, "pre") if side == "post" else (i, "post")
        got = min(UP, cuts[j]["after" if side == "post" else "before"])
        # a shot with no sound of its own (speech, text, quiet) is never lengthened into a sound-up: a silent hole
        more = min(UP - got, cuts[other]["after" if oside == "post" else "before"]) if cuts[other]["loud"] >= 1 else 0.0
        if got + more < 1.5:
            continue
        cuts[j][side] = round(cuts[j][side] + got, 2)
        cuts[other][oside] = round(cuts[other][oside] + more, 2)
        ups.append((j, t))
    return [u[0] for u in ups]


def foley(work, items):
    """items: [(clip path, prompt)] -> {clip path: wav}. One prompt per shot, the shot itself as the video; never music or
    speech. Cached per clip and prompt, so a rebuild only makes the new shots' sound."""
    import hashlib                                      # by clip and prompt: an edited sound is made again
    out = {x: work / f"fx_{pathlib.Path(x).stem}_{hashlib.sha1(p.encode()).hexdigest()[:8]}.wav" for x, p in items}
    todo = [(x, p) for x, p in items if not out[x].exists()]
    if todo:
        tmp = work / "foley_run"
        subprocess.run(["rm", "-rf", str(tmp)])
        tmp.mkdir()
        with open(tmp / "in.csv", "w", newline="") as f:
            w = csv.writer(f); w.writerow(["index", "video", "prompt"])
            for i, (x, p) in enumerate(todo):
                w.writerow([i, str(pathlib.Path(x).resolve()), p or " "])
        cmd = [FOLEY / ".venv/bin/python", "infer.py", "--model_path", H / "foley/weights/HunyuanVideo-Foley", "--model_size", "xl",
               "--csv_path", (tmp / "in.csv").resolve(), "--output_dir", (tmp / "out").resolve(), "--neg_prompt", NEG]
        free = int(subprocess.run(["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"], capture_output=True,
                                  text=True).stdout.split()[0])
        # Offload moves the model on and off the GPU for every shot (~18 s a shot, ~9 GB) so it can share the GPU; with the
        # GPU to itself (the night render hold) it runs whole (~6-8 s a shot), and falls back to offload on OOM.
        if free < 20000 or subprocess.run([str(c) for c in cmd], cwd=FOLEY).returncode != 0:
            run(*cmd, "--enable_offload", cwd=FOLEY)
        for i, (x, _) in enumerate(todo):
            f = tmp / "out" / f"{i:04d}.wav"
            if f.exists():
                f.rename(out[x])
    return {x: w for x, w in out.items() if w.exists()}


def mix(work, cuts, voices):
    """cuts: [{beat, len, pre, loud, fx?}] in order; voices: {beat: wav}. Each beat's voice starts at its first cut + that
    cut's lengthening; foley under/over it by the rules above. Writes work/mix.wav, returns the two-pass loudnorm filter."""
    import numpy as np, soundfile as sf
    SR = 48000
    n = int(sum(c["len"] for c in cuts) * SR) + SR
    voice, fol, under = np.zeros(n), np.zeros(n), np.zeros(n)
    t, seen = 0.0, set()
    for c in cuts:
        s, m = int(t * SR), int(c["len"] * SR)
        if c["beat"] not in seen:
            seen.add(c["beat"])
            v, sr = sf.read(voices[c["beat"]], always_2d=True)
            v = v.mean(1)
            if sr != SR:
                v = np.interp(np.arange(int(len(v) * SR / sr)) * sr / SR, np.arange(len(v)), v)
            o = s + int(c["pre"] * SR)
            voice[o:o + len(v)] += v[:max(0, n - o)]
        if c.get("fx"):
            a, sr = sf.read(c["fx"], always_2d=True)
            a = a.mean(1)
            if sr != SR:
                a = np.interp(np.arange(int(len(a) * SR / sr)) * sr / SR, np.arange(len(a)), a)
            a = np.pad(a, (0, max(0, m - len(a))))[:m]
            a = a / (np.sqrt(np.mean(a ** 2)) + 1e-9) * 10 ** (-24 / 20)   # every shot's sound to one level, then by class
            fol[s:s + m] += a * np.minimum(1, np.minimum(np.arange(m), m - np.arange(m)) / (0.04 * SR))
        under[s:s + m] = UNDER[max(0, c["loud"])]
        t += c["len"]
    hop = SR // 20                                      # voice activity: 50 ms frames over -40 dBFS; gaps < 0.8 s = speech
    fr = np.array([np.sqrt(np.mean(voice[i:i + hop] ** 2)) for i in range(0, n, hop)])
    act = 20 * np.log10(fr + 1e-9) > -40
    vlev = 20 * np.log10(np.median(fr[act]) + 1e-9) if act.any() else -20.0
    gap = 0
    for i in range(len(act)):
        if not act[i]:
            gap += 1
        else:
            if 0 < gap * 0.05 < 0.8:
                act[i - gap:i] = True
            gap = 0
    rel = np.where(np.repeat(act, hop)[:n], under, UP_DB)
    k = int(0.25 * SR)
    rel = np.convolve(rel, np.ones(k) / k, mode="same")  # 0.25 s ramps
    sf.write(work / "mix.wav", np.clip(voice + fol * 10 ** ((vlev + rel + 24) / 20), -1, 1), SR)
    m = subprocess.run([FF, "-hide_banner", "-i", str(work / "mix.wav"), "-af", "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json",
                        "-f", "null", "-"], capture_output=True, text=True).stderr
    j = json.loads(m[m.rindex("{"):m.rindex("}") + 1])
    return (f"loudnorm=I=-14:TP=-1.5:LRA=11:measured_I={j['input_i']}:measured_TP={j['input_tp']}:measured_LRA={j['input_lra']}:"
            f"measured_thresh={j['input_thresh']}:offset={j['target_offset']}:linear=true")

if __name__ == "__main__":                              # self-check of the placement rules
    cs = [{"beat": b, "secs": 5.0, "loud": l, "before": 4.0, "after": 4.0} for b, l in
          [("b1", 3), ("b1", 0), ("b2", 0), ("b2", -1), ("b3", 0), ("b3", 0), ("b4", 3), ("b4", 0), ("b5", 0), ("b5", 2), ("b6", 1)]]
    ups = place(cs)
    assert cs[0]["pre"] == LEAD and ups == [6, 9], ups
    assert cs[6]["pre"] == UP and cs[5]["post"] == 0.0              # the quiet neighbour of the launch is not lengthened
    assert cs[9]["post"] == UP and cs[10]["pre"] == 0.0
    cs[0]["loud"] = -1
    place(cs)
    assert cs[0]["pre"] == 0.0                                           # no sound on the first shot: the voice starts at once
    assert loud({"kind": "footage", "shows": "President speaking at a podium"}) == -1
    assert loud({"kind": "footage", "shows": "Missile launch at night"}) == 3                   # old edit: from what it shows
    assert loud({"kind": "footage", "shows": "Power lines at dusk"}) == -1
    assert loud({"sound": "", "shows": "Missile launch at night"}) == -1                      # the editor said none
    assert loud({"sound": "ship engine and waves"}) == 1 and loud({"sound": "tank tracks clanking"}) == 2
    print("ok")
