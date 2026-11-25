"""Voice lab (TEST ONLY): Arjun's original voice cloned with Chatterbox (MIT) over an exaggeration x cfg_weight grid, urgent scripts.
usage (chatterbox venv on trijya-8): chatterbox_takes.py <config.json> <out_dir>"""
import json, pathlib, re, sys, time, torch, torchaudio
from chatterbox.tts import ChatterboxTTS

cfg, out = json.load(open(sys.argv[1])), pathlib.Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
m = ChatterboxTTS.from_local(cfg["ckpt_dir"], "cuda")
MAX_WORDS, GAP_S = 40, 0.30                                   # one generate() holds ~40 s; longer lines go by sentence groups


def groups(text):
    out = []
    for sent in re.split(r"(?<=[.!?])\s+", text.strip()):
        if out and len(out[-1].split()) + len(sent.split()) <= MAX_WORDS:
            out[-1] += " " + sent
        else:
            out.append(sent)
    return out


def say(text, ex, cw, seed):
    """One take; a long line = its sentence groups, each voiced from the same reference/seed/settings, joined by a pause."""
    parts = []
    for g in groups(text) if len(text.split()) > MAX_WORDS else [text]:
        torch.manual_seed(seed)
        parts += [m.generate(g, audio_prompt_path=cfg["ref_audio"], exaggeration=ex, cfg_weight=cw), torch.zeros(1, int(GAP_S * m.sr))]
    return torch.cat(parts[:-1], dim=-1)


takes = []
for ex in cfg["exaggeration"]:
    for cw in cfg["cfg_weight"]:
        for sl, text in cfg["scripts"].items():
            for seed in cfg["seeds"]:
                t0 = time.time()
                wav = say(text, ex, cw, seed)
                name = f"{cfg['anchor']}_ex{ex}_cfg{cw}_{sl}_s{seed}.wav"
                torchaudio.save(str(out / name), wav.cpu(), m.sr)
                takes.append({"take": name, "anchor": cfg["anchor"], "exaggeration": ex, "cfg_weight": cw, "script_label": sl, "script": text,
                              "seed": seed, "secs_audio": round(wav.shape[-1] / m.sr, 2), "secs": round(time.time() - t0, 1)})
                print(takes[-1], flush=True)
json.dump({"config": cfg, "takes": takes}, open(out / "takes.json", "w"), indent=1)
print("TAKES DONE", flush=True)
