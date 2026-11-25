"""gpt-oss-120b through the same OpenAI-compatible provider pool DNL's generator uses (user decision 2026-10-03).

Providers are tried in order; each gets 3 attempts with backoff on 429/5xx/timeouts. Keys come from env
(~/.config/anchor-studio/llm.env); a provider's key variable may list several keys, comma-separated. Override the pool with LLM_PROVIDERS='[{"name":..,"base_url":..,"key_env":..,"model":..}]'.
"""
import http.client
import json
import os
import re
import time
import urllib.error
import urllib.request

DEFAULT_POOL = [
    {"name": "cerebras", "base_url": "https://api.cerebras.ai/v1", "key_env": "CEREBRAS_API_KEY", "model": "gpt-oss-120b"},   # no key set
    {"name": "groq", "base_url": "https://api.groq.com/openai/v1", "key_env": "GROQ_API_KEY", "model": "openai/gpt-oss-120b",
     "max_budget": 5000},                                           # free tier: 8k tokens/min per key, prompt + max_tokens count
    # Fallback 1 (user decision 2026-10-14): trijya's own Ollama (ollama-robin, ROBIN's service on the same box), its
    # strongest text model. Up at 17:30 (select/cast/script); paused with the other GPU tenants during renders, when a
    # refused connection simply falls through to the next provider. No key: Ollama ignores it.
    {"name": "local", "base_url": "http://127.0.0.1:11434/v1", "key_env": "OLLAMA_LOCAL_KEY", "key": "local",
     "model": "qwen3.8:27b"},
    # Fallback 2 (last resort): RIG's LiteLLM gateway (Hetzner box, over Tailscale) with DNL's virtual key; `rig-quality` is the alias
    # DNL's own generator uses and routes over many providers (Groq/Cloudflare gpt-oss-120b, Gemini Flash, Cohere, ...).
    {"name": "rig", "base_url": "http://100.83.67.1:4000/v1", "key_env": "RIG_GATEWAY_KEY", "model": "rig-quality",
     "timeout": 90},                                               # its slow routes returned empty after 100 s (24 Oct)
]
SHORT_WAIT_S = 30        # Groq's per-minute window: "try again in 7.2s" -> wait for it instead of the slow fallbacks


class LLMUnavailable(RuntimeError):
    pass


def pool():
    """One entry per key: a key_env may hold several comma-separated keys (e.g. GROQ_API_KEY=k1,k2,...), tried in order."""
    p = json.loads(os.environ["LLM_PROVIDERS"]) if os.environ.get("LLM_PROVIDERS") else DEFAULT_POOL
    return [dict(x, name=f"{x['name']}#{i + 1}", key=k, tier=t) for t, x in enumerate(p)
            for i, k in enumerate(k.strip() for k in os.environ.get(x["key_env"], x.get("key", "")).split(",") if k.strip())]


def available():
    """A provider with a configured key (the local Ollama needs none, so it alone does not count)."""
    return any(os.environ.get(p["key_env"]) for p in pool())


def _extract_json(text):
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    a, b = text.find("{"), text.rfind("}")
    return json.loads(text[a:b + 1])


_turn = 0                                                          # round-robin start, spreads load over the keys


def chat_json(system, user, temperature=0.2, max_tokens=4000, log=print):
    """Return the model's reply parsed as a JSON object. Raises LLMUnavailable when every provider fails.

    Each call starts at the next key; a rate-limited (429) or failing key hands over to the next one at once, and only
    a full pass with no success sleeps (Groq free tier: 8k tokens/min per key, and max_tokens counts against it)."""
    global _turn
    keys, errors = pool(), []
    if not keys:                                                    # nothing configured: fail now, not after 90 s of retries
        raise LLMUnavailable("no LLM provider key configured")
    first = [k for k in keys if k["tier"] == min((k["tier"] for k in keys), default=0)]
    order = lambda: [first[(_turn + j) % len(first)] for j in range(len(first))] + [k for k in keys if k not in first]
    short_waits = 0
    attempt = 0
    while attempt < 3:
        waits = []                                                  # seconds until a rate-limited primary key frees up
        for p in order():                                           # primary keys round-robin, then the fallbacks
            if p not in first and waits and len(waits) == len(first) and min(waits) <= SHORT_WAIT_S and short_waits < 6:
                break                                               # every primary only busy for seconds: wait, retry them
            budget, cap = max_tokens, max(max_tokens, p.get("max_budget", 16000))
            try:
                while True:
                    body = {"model": p["model"], "temperature": temperature, "max_tokens": budget,
                            "response_format": {"type": "json_object"},
                            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
                    req = urllib.request.Request(p["base_url"].rstrip("/") + "/chat/completions", json.dumps(body).encode(),
                                                 {"Content-Type": "application/json", "Authorization": "Bearer " + p["key"],
                                                  "User-Agent": "anchor-studio/1.0"})
                    with urllib.request.urlopen(req, timeout=p.get("timeout", 180)) as r:
                        ch = json.loads(r.read())["choices"][0]          # empty/null choices -> IndexError/TypeError below
                    try:
                        res = _extract_json(ch["message"]["content"])
                        break
                    except (ValueError, TypeError, AttributeError, KeyError, IndexError):
                        # empty (a reasoning model spent the budget thinking) or cut-off JSON (some gateway routes stop
                        # early while still reporting "stop"); the gateway caches identical requests, so the retry
                        # must differ: a bigger budget
                        if budget >= cap:
                            raise
                        budget = min(budget * 2, cap)
                _turn = (_turn + 1) % len(first)
                return res
            except urllib.error.HTTPError as e:
                try:                                                # provider's reason (rate window, bad JSON, ...)
                    full = json.loads(e.read()).get("error", {}).get("message", "")
                except Exception:  # noqa: BLE001
                    full = ""
                errors.append(f"{p['name']} HTTP {e.code} {full[:160]}".strip())
                m = re.search(r"try again in (?:(\d+)h)?(?:(\d+)m)?([\d.]+)s", full)
                if e.code == 429 and p in first and m:
                    waits.append(int(m.group(1) or 0) * 3600 + int(m.group(2) or 0) * 60 + float(m.group(3)))
            except (OSError, http.client.HTTPException, ValueError, KeyError, AttributeError, TypeError, IndexError) as e:
                # OSError covers URLError/timeouts/resets; HTTPException covers a dropped connection (RemoteDisconnected
                # crashed a run 2026-10-12); AttributeError = empty reply
                errors.append(f"{p['name']} {type(e).__name__}: {str(e)[:120]}")
        if waits and len(waits) == len(first) and min(waits) <= SHORT_WAIT_S and short_waits < 6:
            short_waits += 1
            time.sleep(min(waits) + 1)                              # not a failed pass: the window reopens in seconds
            continue
        attempt += 1
        log(f"LLM: every key failed on pass {attempt}: {errors[-len(keys):]}")
        time.sleep(15 * attempt)                                    # let the per-minute token windows refill
    raise LLMUnavailable("; ".join(errors[-6:]) or "no LLM provider key configured")
