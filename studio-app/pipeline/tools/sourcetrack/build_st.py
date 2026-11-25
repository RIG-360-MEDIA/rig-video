"""source_track jobs (TEST, separate from the daily pipeline): the anchor lip-syncs to a TTS voice master instead of H3
inventing the voice. Builds two ComfyUI API jobs from the UNCHANGED daily builder (build_main.build, variant t8k), so the
look, prompts, identity pin, seeds and speed settings are exactly the daily ones; only the audio route changes:

  <run>_st_seed.json   the daily seed (20 steps, res_multistep/simple, FBC + sparse, plate + face pictures) run through
                       the chain nodes as ONE scene, so its audio can be locked to master_seed.wav
  <run>_st_chain.json  the daily chain (8 steps lcm/beta + Acc LoRA, Soft AV boundaries, continues from the seed video)
                       with its shots sized to the master and locked to master_chain.wav

Lock = pack 0.5.11 Chain Policy final_audio=source + lock_source_audio=on: each scene's exact source window is VAE-encoded
into H3's target audio latent with a zero denoise mask; the video is generated against it (lip sync), and assembly
uses the source track itself. The pack starts the chain's source at 0 right after the imported seed, and fills the
39-frame overlap from the seed video's own (locked) audio.

usage: build_st.py story.json master_dir out_dir [--turbo-seed]   (story.json as for build_main: run, anchor, beats)
  --turbo-seed: the seed also uses the chain's speed path (Acc-8Step LoRA, 8 steps lcm/beta) instead of 20 steps
                res_multistep -- about half the seed time (user allowed it for speed, 2026-10-26).
"""
import copy, json, os, re, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", ".."))
import build_main as bm                                   # read-only use of the daily builder

LOCK = {"final_audio": "source", "lock_source_audio": True, "source_reference": "off", "generated_continuity": "off"}


def timeline(g, wav):
    """LoadAudio -> Source Timeline (audio only), wired into Plan Studio and Loop Start as in the pack's example."""
    g["1951a"] = {"class_type": "LoadAudio", "inputs": {"audio": wav}}
    g["1955"] = {"class_type": "MiniMaxH3SourceTimeline",
                 "inputs": {"video_path": "", "audio_path": "", "embedded_audio": "ignore", "skip_first_frames": 0,
                            "source_audio": ["1951a", 0]}}
    g["1930"]["inputs"]["source_timeline"] = ["1955", 0]
    g["1701"]["inputs"]["source_timeline"] = ["1955", 0]


def build(story, master_dir, out_dir, turbo_seed=False):
    shots = json.load(open(os.path.join(master_dir, "shots.json")))["shots"]
    beats, run = story["beats"], story["run"] + "_st"
    assert len(beats) == len(shots), "one master window per beat"
    os.makedirs(out_dir, exist_ok=True)
    # The daily lock asserts the anchor alone fills 60 s; in a hybrid the anchor shares the time with voiceover. Relaxed
    # in this process only (build_main.py itself is not touched).
    bm.OUTRO_S = max(bm.OUTRO_S, 60.0)
    with tempfile.TemporaryDirectory() as tmp:
        bm.build(dict(story, run=story["run"]), tmp, "t8k")
        seed = json.load(open(os.path.join(tmp, f"{story['run']}_t8k_seed.json")))
        chain = json.load(open(os.path.join(tmp, f"{story['run']}_t8k_chain.json")))
    seed, chain = seed.get("prompt", seed), chain.get("prompt", chain)
    sp = seed["136"]["inputs"]

    # ---------- seed: daily seed settings, through the chain nodes as one locked scene ----------
    g = copy.deepcopy(chain)
    for k in ("1950", "1951"):                                  # no imported video
        g.pop(k)
    steps = chain["1700"]["inputs"]["default_steps"] if turbo_seed else seed["124"]["inputs"]["steps"]
    if not turbo_seed:                                          # daily seed path: no LoRA / extra sigma shift, 20 steps
        g.pop("1635"); g.pop("5")
        g["9700"]["inputs"]["model"] = ["1941", 0]              # UNET -> attention -> sparse -> FBC, as the daily seed
        g["122"]["inputs"]["sampler_name"] = seed["123"]["inputs"]["sampler_name"]      # res_multistep
        g["123"]["inputs"]["scheduler"] = seed["124"]["inputs"]["scheduler"]            # simple
    g["137"], g["138"] = seed["137"], seed["138"]                                       # plate = Picture 1, face = Picture 2
    g["110"]["inputs"].update({"ref_images.ref_image_0": ["137", 0], "ref_images.ref_image_1": ["138", 0],
                               "ref_image_size": sp["ref_image_size"]})
    g["1701"]["inputs"].pop("external_context")
    g["1949"]["inputs"].pop("asset_1"); g["1949"]["inputs"]["asset_bindings_json"] = "[]"
    pj = json.loads(g["1700"]["inputs"]["plan_json"])
    prompt, k = re.subn(r"<Audio 1> is the voice reference for the anchor \(S1\):.*?<Audio 1>\. ", "", sp["prompt"], flags=re.S)
    assert k == 1 and "<Audio" not in prompt, "the seed's <Audio 1> voice-reference sentence must go: there is no audio reference"
    pj["shots"] = [{"id": "seed", "prompt": prompt, "length": shots[0]["raw_frames"], "steps": steps,
                    "seed": seed["129"]["inputs"]["noise_seed"]}]
    g["1700"]["inputs"].update(plan_json=json.dumps(pj, indent=2), run_name=f"{run}_seed",
                               default_steps=steps, video_blend_frames=0)   # one fresh scene: no context
    g["132"]["inputs"]["retain_overlap_frames"] = 0
    g["1954"]["inputs"].update(LOCK, incoming_transition="cut")
    g["1706"]["inputs"]["filename"] = f"{run}_seed"
    timeline(g, f"{run}_master_seed.wav")
    assert "ref_audios.ref_audio_0" not in g["110"]["inputs"], "no voice reference: the voice is the locked master"
    json.dump(g, open(os.path.join(out_dir, f"{run}_seed.json"), "w"), indent=1)

    # ---------- chain: daily chain, shots sized to the master, locked ----------
    c = copy.deepcopy(chain)
    pj = json.loads(c["1700"]["inputs"]["plan_json"])
    assert len(pj["shots"]) == len(shots) - 1
    for sh, m in zip(pj["shots"], shots[1:]):
        sh["length"] = m["raw_frames"]
    c["1700"]["inputs"].update(plan_json=json.dumps(pj, indent=2), run_name=run)
    c["1950"]["inputs"]["video"] = f"{run}_seed.mp4"
    c["1954"]["inputs"].update(LOCK)                           # incoming boundary stays the daily Soft AV
    c["1706"]["inputs"]["filename"] = run
    timeline(c, f"{run}_master_chain.wav")
    json.dump(c, open(os.path.join(out_dir, f"{run}_chain.json"), "w"), indent=1)

    total = shots[0]["raw_frames"] + sum(m["raw_frames"] - 39 for m in shots[1:])
    print(f"{run}: seed {shots[0]['raw_frames']} + chain {[m['raw_frames'] for m in shots[1:]]} = {total} frames "
          f"({total / 24:.2f} s) = master {sum(m['delivered_frames'] for m in shots) / 24:.2f} s")


if __name__ == "__main__":
    build(json.load(open(sys.argv[1])), sys.argv[2], sys.argv[3], turbo_seed="--turbo-seed" in sys.argv)
