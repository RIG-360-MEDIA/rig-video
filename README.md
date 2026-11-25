# RIG-Video

RIG-Video turns news articles into finished news videos every day:
- **VO only**: 9:16 footage with a voice-over;
- **anchor + VO**: 16:9, with an AI news anchor.

It writes the script, voices it, finds and checks the footage on YouTube, renders the video overnight and uploads it for an
editor to approve. It runs on three office GPU machines (trijya-3, trijya-7, trijya-8).

**Start with [docs/HANDOFF.md](docs/HANDOFF.md).** It explains the whole system: what runs where, a day in
production, every step of a story, the code map, the runtime, secrets (by name), restarts, CI/CD, the runbook, and the
rules.

| | |
|---|---|
| Ship a change | PR → `check` passes → merge → publish a GitHub Release `vX.Y.Z` → `release` installs it, and rolls back by itself if the health check fails |
| Is it healthy? | `python3 ops/doctor.py` on trijya-7 (also runs daily at 07:30 and 23:30 IST) |
| Secrets | Never in git; see [config/env.example.md](config/env.example.md) for names |
