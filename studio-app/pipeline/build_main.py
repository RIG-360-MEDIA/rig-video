#!/usr/bin/env python3
"""Main pipeline job builder: seed + chain. Production recipe = "t8k" (baseline/RECIPE_CURRENT.md, locked 2026-10-06):
seed = v7 (FirstBlockCache 0.10 + sparse attention, 20 steps), chain = 8 steps + Kijai Acc-8Step LoRA at 1.0.

usage: python3 pipeline/build_main.py story.json out_dir/ [t8k|safe|v4|v7]
story.json = {"run": "naza_v2", "beats": ["seed line", "shot 2", "shot 3", "shot 4"], "voice": "mirac.wav"}
           optional "anchor": "<registry id>" -> identity-pinned seed (anchor frame as <Picture 2>), the anchor's
           locked voice, descriptor and pronouns everywhere. Without "anchor" the validated legacy Emre text is used.

Targets the ComfyUI v0.38.1 test install (~/anchor-studio/repos/ComfyUI-v038): FirstBlockCache is a custom
node there. Seed = validated image-7 tall-room template (templates/seed_set7_fbc.json): only the spoken line,
length, voice file and output name change. Chain = canon anchor_60s_prod_v2 + ONE FirstBlockCache node
between SigmaShift(5) and the guider/scheduler — no ref_audio, prepend_original=True (locks).
STATUS: seed+FBC validated (1.41x, quality equal). Chain+FBC on v0.38 NOT yet validated for seams /
voice carry — run a 2-shot chain and measure before trusting it for production.
"""
import copy, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
VALID = [5 + 17 * k for k in range(30)]                    # H3 valid lengths: L % 17 == 5
SHOT = 328                                                 # the production shot (13.67 s)


# Seeds are not neutral noise: one seed makes H3 cut to a close-up or pan the camera whatever the story. Measured on every
# chain 3-24 Oct: seed shot 1042 cut to a close-up at 5-7 s in 3 of 3; chain seed 52206 panned 5 of 14 clips (it sat on
# EVERY video's last clip: the "last shot always drifts" pattern), 54000 panned 3 of 3; 52000 and 52103 never panned in
# ~22 clips each, 53000/53103/53206/54103/54206 never in 1-3. Attempt k (= noise_offset // 1000: seed re-roll / remake)
# takes row k; rows past the table fall back to fresh seeds that skip the known-bad ones.
SEED_SHOTS = [42, 2042, 3042, 4042, 5042]
CHAIN_SEEDS = [[52000, 52103, 54206], [53000, 53103, 53206], [54103, 52000, 52103]]
BAD_SEEDS = {1042, 52206, 54000}
PROVEN_CHAIN_SEEDS = [52000, 52103]


def seeds(off, n_clips):
    """(seed-shot seed, [chain clip seeds]) for noise_offset `off`."""
    k = int(off) // 1000
    shot = SEED_SHOTS[k] if k < len(SEED_SHOTS) else 42 + 1000 * k
    row = list(CHAIN_SEEDS[k]) if k < len(CHAIN_SEEDS) else []
    if row:                                                       # long chains (NDC anchor-only sections): only proven seeds,
        while len(row) < n_clips:                                 # 52000/52103 never panned in ~22 clips each
            row.append(PROVEN_CHAIN_SEEDS[len(row) % len(PROVEN_CHAIN_SEEDS)])
    i = 0
    while len(row) < n_clips:                                     # longer chains / later attempts: fresh, never a bad one
        cand = 52000 + len(row) * 103 + 1000 * k + i
        if cand in BAD_SEEDS or cand in row:
            i += 7
            continue
        row.append(cand)
    while shot in BAD_SEEDS:
        shot += 1000
    return shot, row[:n_clips]


def snap(words, target=33):
    """Frames for a line of `words` SPOKEN words read by an anchor whose pace fills one SHOT with `target` words
    (registry `words_per_shot`). target +-1 -> SHOT. H3 copies each anchor's pace from their locked voice (2.3-3.0 words/s
    measured), so a fixed count leaves fast anchors a silent tail H3 fills with music (Yuna, 2.6 s) and gives slow-text
    lines filler or gibberish ("Good evening, Yomuemori", 2026-10-11)."""
    if abs(words - target) <= 1:
        return SHOT
    return min(VALID, key=lambda L: abs(L - round(words * SHOT / target)))


def _said(n, year=False):
    """How many words a number takes to say: 60 -> 1, 120 -> 3 ("one hundred twenty"), 2026 as a year -> 2."""
    if year and 1100 <= n <= 2099:
        return 2
    if n < 100:
        return 1
    for unit, w in ((10 ** 9, 1), (10 ** 6, 1), (1000, 1), (100, 1)):
        if n >= unit:
            return _said(n // unit) + w + (_said(n % unit) if n % unit else 0)


def spoken(text):
    """Words the anchor actually says: breath dashes (" - ", "–", "—") are pauses, not words; numbers count as said
    (a beat of digits looked short on paper, ran long on air and H3 skipped a clause, 2026-10-14)."""
    n = 0
    for w in text.split():
        if not w.strip("-–—"):
            continue
        w = w.strip(".,;:!?\"'()")                                  # "2026," is still a year
        m = re.fullmatch(r"(\D*?)(\d[\d,]*)(?:[.:](\d+))?(\D*)", w)
        if not m:
            n += 1
            continue
        pre, whole, frac, post = m.groups()
        n += _said(int(whole.replace(",", "")), year="," not in whole and len(whole) == 4 and not frac)
        if frac:                                                    # "9:45" -> nine forty-five; "2.1" -> two point one
            n += _said(int(frac)) if ":" in w else 1 + len(frac)
        n += bool(re.search(r"[a-z]", pre, re.I))                   # "F-16", "COVID-19", "AI-2030"
        n += bool(re.search(r"[a-z]", re.sub(r"^(st|nd|rd|th|s)$", "", post, flags=re.I), re.I))   # "$4.3bn" -> billion
    return n
OUTRO_S = 11.84
FBC = {"class_type": "ApplyMiniMaxH3FirstBlockCache",
       "inputs": {"mode": "H3 Safe — 0.08 / max 2", "threshold": 0.08, "start_percent": 0.10,
                  "end_percent": 0.95, "max_consecutive_hits": 2, "temporal_guard": False}}
SPARSE = {"class_type": "H3SparseAttentionOverride",   # pipeline/comfy_nodes/h3_sparse_override (FBC-compatible)
          "inputs": {"tau": 1.0, "start_percent": 0.40, "end_percent": 1.0, "dense_blocks": "0-2, 47-49",
                     "min_tokens": 12288, "extra_tokens": 256, "sink_conditioning": "exact_kv_and_rows", "verbose": True}}
# Speed variants (2026-10-02 seed A/B, image-7 set, seed 42; FBC-Safe baseline = 13.1 min sampling/shot):
#   safe  FBC Safe                          13.1 min
#   v4    FBC Fast                          12.1 min  face sharpness 333 vs 338 (passes)
#   v7    FBC Fast + sparse(0.40-1.0, t1.0)  9.6 min  face sharpness 293 vs 338 (pending long-shot review)
VARIANTS = {
    "safe": {"fbc": ("H3 Safe — 0.08 / max 2", 0.08), "sparse": None},
    "v4": {"fbc": ("H3 Fast — 0.10 / max 2", 0.10), "sparse": None},
    "v7": {"fbc": ("H3 Fast — 0.10 / max 2", 0.10), "sparse": {}},
    # PRODUCTION (baseline/RECIPE_CURRENT.md, user-approved 2026-10-06): seed = v7; chain = 8 steps + Kijai Ref2VA
    # 8-step accelerator LoRA at 1.0 (lcm/beta unchanged). ~35 min per full video vs ~61 for v7.
    "t8k": {"fbc": ("H3 Fast — 0.10 / max 2", 0.10), "sparse": {}, "chain_lora": "MiniMax-H3-Ref2VA-Acc-8Step_pruned_comfy.safetensors",
            "chain_steps": 8},
}

# Chain continuation prompt for the image-7 tall-room set (6-section Ref2VA format, official guide).
SET = ("the tall premium evening news studio: the anchor sits at true human scale behind the long glossy dark desk with a black "
       "coffee mug, sheets of paper and a closed laptop; behind {him}, high ceiling lights, floor-to-ceiling city windows, a dark "
       "pillar of three plain round clock dials and a softly out-of-focus newsroom of staff seated at glowing monitors; on the "
       "right a large video wall, fully visible, with no readable text, maps or logos")
MOTION = ("The seated newsroom staff stay in their chairs and move where they sit - typing, shifting; nobody walks, stands, "
          "enters or crosses the frame, and there are no cars or moving vehicles in the windows.")
DELIVERY = ("{He} reads like a lead news anchor breaking a major story live on air: {he} hammers and stresses the key words hard, then "
            "takes sharp, deliberate pauses and clear breaths between sentences and at the most dramatic beats - punchy, driven "
            "bursts of speech separated by real silence, with strong dynamic contrast between the hammered emphasis words and the "
            "quieter connecting words, urgent and commanding, never flat.")
SOUND = ("A quiet, controlled broadcast studio room tone with a faint low air-conditioning hum, the close presence of a lapel mic "
         "on the anchor's voice, and a soft, distant newsroom murmur with occasional faint keyboard clicks well in the background. "
         "No audience, no applause.")
MUSIC = ("A subtle, low-key television news broadcast underscore plays continuously beneath {his} voice - a steady, understated "
         "instrumental bed with soft synth pads and a light rhythmic pulse, mixed well below the dialogue, never swelling, never "
         "overpowering.")


REG = os.path.join(HERE, "..", "anchor_registry", "registry.json")
LEGACY = {"id": None, "gender": "M", "pronoun": "he", "noun": "male",
          "descriptor": None}


def anchor_entry(aid):
    """Registry row for `aid`, with the voice/identity file names as they sit in ComfyUI's input/ folder."""
    a = next(x for x in json.load(open(REG))["anchors"] if x["id"] == aid)
    return dict(a, noun="male" if a["gender"] == "M" else "female")


def pr(text, a):
    """Fill {he}/{his}/{him}/{He}/{His}/{noun} for the anchor's gender."""
    she = a["pronoun"] == "she"
    return text.format(he="she" if she else "he", his="her" if she else "his", him="her" if she else "him",
                       He="She" if she else "He", His="Her" if she else "His", noun=a["noun"])


def id_input_name(a):
    """File name of the anchor's identity image inside ComfyUI input/ (deploy uploads it under this name). The pin is the
    FACE-ONLY cut-out: the full registry frame (anchor centred and large) made H3 copy its framing (2026-10-10)."""
    return f"anchor_face_{a['id']}.png" if a.get("identity_face") else f"anchor_id_{a['id']}.png"


def identity_block(a):
    """Seed text that defines the anchor: Picture 2 pins the face; descriptor pins hair/wardrobe in words."""
    return pr("{He} is the real {noun} television news anchor (S1) shown in <Picture 2>. <Picture 2> is the identity reference "
              "for the anchor only - keep exactly that person's face, skin tone, hair, build and age; ignore the background, desk, "
              "lighting and framing of <Picture 2>, which come from <Picture 1> only. ", a) + a["descriptor"]


def cont(line, a=LEGACY):
    who = (pr("{his} identity, face, hair, voice and wardrobe", a) if a["id"] else
           "his identity, face, hair, beard, voice, charcoal suit, white collar and burgundy tie")
    return pr("subject_definitions:\n<Subject 1> is the same real {noun} television news anchor established by the incoming protected "
              "video prefix - ", a) + who + (" continue exactly as "
            "carried forward by that prefix.\n\n"
            "summary:\nThe same anchor continues the same live broadcast from the same static shot, without a seam.\n\n"
            "retention_analysis:\n<Subject 1> (appears in every shot): fully_preserved - carried forward unchanged from the incoming "
            + pr("protected video prefix, together with {his} exact speaking voice, {his} natural size in frame, and ", a)
            + pr(SET, a) + "; the warm amber-and-cool lighting and the exact colour grading, white balance and exposure, with zero drift.\n\n"
            "detailed_description:\nStatic Shot. The camera stays locked in the same framing with no zoom, push, pan or tilt; the "
            f"anchor keeps the same position and size in frame. {MOTION} " + pr(DELIVERY, a) + pr(" {He} continues the read across "
            "the boundary in the same voice, the anchor (S1) saying, ", a) + f"<d>[English]{line}</d>\n\n"
            f"overall_soundscape:\nContinue the same studio room tone across the boundary without a seam: {SOUND}\n\n"
            "non_diegetic_music:\n" + pr(MUSIC, a))


def _speed(nodes, upstream, variant):
    """Insert [sparse override ->] FBC after `upstream`; returns the node id the sampler must read."""
    v = VARIANTS[variant]
    src = upstream
    if v["sparse"] is not None:
        nodes["9700"] = copy.deepcopy(SPARSE); nodes["9700"]["inputs"].update(v["sparse"]); nodes["9700"]["inputs"]["model"] = upstream
        src = ["9700", 0]
    nodes["9300"] = copy.deepcopy(FBC)
    nodes["9300"]["inputs"].update({"mode": v["fbc"][0], "threshold": v["fbc"][1], "model": src})
    return ["9300", 0]


def build(story, out_dir, variant="safe"):
    run, beats = story["run"] + ("" if variant == "safe" else f"_{variant}"), story["beats"]
    a = anchor_entry(story["anchor"]) if story.get("anchor") else LEGACY
    voice = os.path.basename(a["voice_file"]) if a["id"] else story.get("voice", "mirac.wav")
    assert not (a["id"] and story.get("voice") and story["voice"] != voice), "an anchor's voice is locked; do not override it"
    os.makedirs(out_dir, exist_ok=True)

    # ---- seed: validated template, swap only line / length / voice / name ----
    sg = json.load(open(f"{HERE}/templates/seed_set7_fbc.json")); s = sg.get("prompt", sg)
    n = s["136"]["inputs"]
    n["prompt"], k = re.subn(r"<d>\[English\].*?</d>", lambda _: f"<d>[English]{beats[0]}</d>", n["prompt"], flags=re.S)
    assert k == 1, "seed template must have exactly one <d> line"
    if a["id"]:   # identity pin: anchor frame as <Picture 2>, registry descriptor replaces the legacy Emre text
        n["prompt"], k = re.subn(r"He is a real male television news anchor \(S1\).*?below the knot\.", lambda _: identity_block(a),
                                 n["prompt"], flags=re.S)
        assert k == 1, "seed template must contain exactly one legacy anchor description"
        if a["pronoun"] == "she":
            sw = {"he": "she", "He": "She", "his": "her", "His": "Her", "him": "her"}
            n["prompt"] = re.sub(r"\b(he|He|his|His|him)\b", lambda m: sw[m.group(1)], n["prompt"])
        s["138"] = {"class_type": "LoadImage", "inputs": {"image": id_input_name(a)}}
        n["ref_images.ref_image_1"] = ["138", 0]
    target = a.get("words_per_shot", 33)
    n["length"] = seed_len = snap(spoken(beats[0]), target)
    s["250"]["inputs"]["audio"] = voice
    s["92"]["inputs"]["filename_prefix"] = f"video/{run}_seed"
    off = int(story.get("noise_offset", 0))                     # re-render after a failed QC gate: new noise, same everything else
    shot_seed, chain_seeds = seeds(off, len(beats) - 1)
    s["129"]["inputs"]["noise_seed"] = shot_seed
    s.pop("9700", None)
    out = _speed(s, ["9100", 0], variant)
    for k0 in ("124", "126"):
        s[k0]["inputs"]["model"] = out
    assert n["ref_audios.ref_audio_0"] == ["250", 0] and "ref_audios" not in n, "voice must use the flat dotted key"
    assert s["250"]["inputs"]["audio"] == voice and (("ref_images.ref_image_1" in n) == bool(a["id"])), "anchor voice/identity lock"
    assert s["124"]["inputs"]["model"] == ["9300", 0] and s["9300"]["class_type"] == FBC["class_type"], "seed must run FBC"
    json.dump(sg, open(f"{out_dir}/{run}_seed.json", "w"))

    # ---- chain: canon prod_v2 + one FBC node before the sampler ----
    canon = json.load(open(f"{HERE}/templates/chain_prod_v2_canon.json")); canon = canon.get("prompt", canon)
    cg = copy.deepcopy(canon); c = cg
    c["1950"]["inputs"]["video"] = f"{run}_seed_00001_.mp4"
    pj = json.loads(c["1700"]["inputs"]["plan_json"])
    pj["shots"] = [{"id": f"story_{i + 2}", "prompt": cont(b, a), "length": snap(spoken(b), target), "steps": VARIANTS[variant].get("chain_steps", 20),
                    "seed": chain_seeds[i]} for i, b in enumerate(beats[1:])]
    c["1700"]["inputs"]["plan_json"] = json.dumps(pj, indent=2); c["1700"]["inputs"]["run_name"] = run
    c["1706"]["inputs"]["filename"] = f"{run}_%date:yyyy-MM-dd%"
    if VARIANTS[variant].get("chain_lora"):                     # accelerator LoRA on the chain only (seed stays 20 steps)
        c["1635"]["inputs"].update(lora_name=VARIANTS[variant]["chain_lora"], strength_model=1.0)
        c["1700"]["inputs"]["default_steps"] = VARIANTS[variant]["chain_steps"]
    out = _speed(c, ["5", 0], variant)
    for k2 in ("121", "123"):
        c[k2]["inputs"]["model"] = out
    json.dump(cg, open(f"{out_dir}/{run}_chain.json", "w"))

    # ---- locks ----
    diff = {(k3, a) for k3 in canon for a in canon[k3]["inputs"] if canon[k3]["inputs"][a] != c[k3]["inputs"][a]}
    allowed = {"9300"} | ({"9700"} if VARIANTS[variant]["sparse"] is not None else set())
    assert set(c) - set(canon) == allowed and set(canon) <= set(c), "only the speed nodes may be added"
    turbo = {("1635", "lora_name"), ("1635", "strength_model"), ("1700", "default_steps")} if VARIANTS[variant].get("chain_lora") else set()
    assert diff == {("1950", "video"), ("1700", "plan_json"), ("1700", "run_name"), ("1706", "filename"),
                    ("121", "model"), ("123", "model")} | turbo, diff
    assert not any("ref_audio" in a for nd in c.values() for a in nd["inputs"]), "no ref_audio on the chain"
    assert c["1951"]["inputs"]["prepend_original"] is True
    lens = [sh["length"] for sh in pj["shots"]]
    secs = (seed_len + sum(L - 39 for L in lens)) / 24
    assert secs + OUTRO_S >= 60, f"anchor {secs:.1f}s + outro must reach 60s"
    print(f"LOCK OK {run}: seed {seed_len} + shots {lens} -> {secs:.1f}s + outro {OUTRO_S} = {secs + OUTRO_S:.1f}s, "
          f"{len(lens)} seams, variant {variant} on seed+chain")
    for b in beats:
        w = spoken(b); L = snap(w, target); print(f"  {w} spoken words -> {L} ({L / 24:.1f}s) {w / (L / 24):.2f} wps")


if __name__ == "__main__":
    build(json.load(open(sys.argv[1])), sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "safe")
