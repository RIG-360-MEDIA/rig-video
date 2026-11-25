import glob
import html
import json
import logging
import os
import re
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from xml.etree import ElementTree

import httpx

from app.core import db
from app.core.config import settings
from app.core.ytdlp_cookies import cookies_args

logger = logging.getLogger(__name__)

LINE_SECONDS = 15.0  # caption cues are merged into lines of roughly this length
# Captions are the main path (fastest, YouTube's own text). YouTube blocks an IP's caption downloads for hours once it
# sees bursts of them, so: one request at a time, at least CAPTION_MIN_INTERVAL s apart, fetched like a browser (PO token
# in the URL via the bgutil provider + Chrome TLS via curl_cffi, when installed), and on the first 429 no retries -- the
# caption path pauses for CAPTION_COOLDOWN s and videos go to speech-to-text instead.
CAPTION_MIN_INTERVAL = float(os.environ.get("FOOTAGE_CAPTION_MIN_INTERVAL_S", "3"))
CAPTION_COOLDOWN = float(os.environ.get("FOOTAGE_CAPTION_COOLDOWN_S", "1800"))
_caption_lock = threading.Lock()
_caption_state = {"last": 0.0, "blocked_until": 0.0}
# Speech-to-text fallback (no English captions, or captions refused): faster-whisper on the GPU when available (~60x
# real time), else CPU. The whole video is transcribed (FOOTAGE_WHISPER_MAX_SECONDS > 0 caps it). Empty model turns it off.
WHISPER_MODEL = os.environ.get("FOOTAGE_WHISPER_MODEL", "small")
WHISPER_MAX_SECONDS = int(os.environ.get("FOOTAGE_WHISPER_MAX_SECONDS", "0"))
WHISPER_DEVICE = os.environ.get("FOOTAGE_WHISPER_DEVICE", "auto")      # auto | cuda | cpu
_whisper = None
_whisper_lock = threading.Lock()


@dataclass
class VideoTranscript:
    duration_seconds: float | None = None
    channel: str = ""
    chapters: list[dict] = field(default_factory=list)  # [{start, end, title}]
    lines: list[dict] = field(default_factory=list)  # [{start, end, text}]
    # True when the video *has* a caption track but downloading it failed
    # (e.g. YouTube rate-limiting) -- as opposed to a video with none.
    incomplete: bool = False


def get_transcript(video_id: str) -> VideoTranscript:
    """Caption text plus duration/chapters for one YouTube video, cached in
    footage_transcripts -- the same video often turns up under several
    keywords of one project (and across projects), and captions never change
    once published, so it's only ever fetched once. A video with no captions
    at all is cached too (with empty lines), so it isn't retried every time."""
    row = db.fetch_one("SELECT * FROM footage_transcripts WHERE video_id=?", (video_id,))
    if row:
        return VideoTranscript(
            duration_seconds=row["duration_seconds"],
            channel=row["channel"],
            chapters=json.loads(row["chapters_json"]),
            lines=json.loads(row["lines_json"]),
        )

    transcript = _fetch(video_id)
    # A failed fetch (no metadata, or a caption track that wouldn't
    # download) is most likely a transient block (429/bot check), not a
    # captionless video -- don't cache that, so a later run can try again.
    if transcript.duration_seconds is not None and not transcript.incomplete:
        db.execute(
            "INSERT INTO footage_transcripts "
            "(video_id, duration_seconds, channel, chapters_json, lines_json) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(video_id) DO NOTHING",
            (
                video_id, transcript.duration_seconds, transcript.channel,
                json.dumps(transcript.chapters), json.dumps(transcript.lines),
            ),
        )
    return transcript


def _fetch(video_id: str) -> VideoTranscript:
    info = _fetch_info(video_id)
    if info is None:
        return VideoTranscript()
    transcript = VideoTranscript(
        duration_seconds=info.get("duration"),
        channel=info.get("channel") or info.get("uploader") or "",
        chapters=[
            {"start": c.get("start_time", 0), "end": c.get("end_time", 0), "title": c.get("title", "")}
            for c in info.get("chapters") or []
        ],
    )
    caption_url = _pick_caption_url(info)
    if caption_url:
        try:
            transcript.lines = _srv1_to_lines(_download_caption(caption_url))
        except (CaptionsBlocked, httpx.HTTPError, ElementTree.ParseError) as e:
            logger.warning("Caption download failed for %s: %s", video_id, e)
            lines = _alt_caption_lines(video_id)
            if lines:
                transcript.lines = lines
            else:
                transcript.incomplete = True
    if not transcript.lines and WHISPER_MODEL:
        lines = _whisper_lines(video_id, transcript.duration_seconds or 0)
        if lines:
            transcript.lines, transcript.incomplete = lines, False
    return transcript


def _load_whisper():
    from faster_whisper import WhisperModel
    if WHISPER_DEVICE in ("auto", "cuda"):
        try:
            m = WhisperModel(WHISPER_MODEL, device="cuda", compute_type="int8_float16")
            logger.info("Speech-to-text: %s on the GPU", WHISPER_MODEL)
            return m
        except Exception as e:  # noqa: BLE001 -- no GPU / CUDA libraries / memory: use the CPU
            if WHISPER_DEVICE == "cuda":
                raise
            logger.warning("Speech-to-text: GPU unavailable (%s), using the CPU", e)
    return WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8", cpu_threads=max(4, (os.cpu_count() or 8) - 4))


def _whisper_lines(video_id: str, duration: float) -> list[dict]:
    """Transcribe (and translate to English) the video's own audio with faster-whisper on the CPU, as ~LINE_SECONDS lines
    with real timestamps -- the same shape as caption lines, so matching works unchanged. One model, one transcription
    at a time (it already uses many CPU threads)."""
    global _whisper
    with tempfile.TemporaryDirectory() as tmp:
        cmd = [settings.ytdlp_bin, "-q", "--no-warnings", "--no-playlist", "-f", "bestaudio[ext=m4a]/bestaudio",
               "-o", f"{tmp}/audio.%(ext)s"]
        if WHISPER_MAX_SECONDS and duration > WHISPER_MAX_SECONDS:
            cmd += ["--download-sections", f"*0-{WHISPER_MAX_SECONDS}"]
        with cookies_args(settings.ytdlp_youtube_cookies_file) as cookie_args:
            try:
                r = subprocess.run([*cmd, *cookie_args, f"https://www.youtube.com/watch?v={video_id}"],
                                   capture_output=True, text=True, timeout=120)  # a few-MB audio file: a stalled download (YouTube throttling a 429ed IP) gives up in 2 min, not 15
            except subprocess.TimeoutExpired:
                logger.warning("Timed out downloading audio for %s", video_id)
                return []
        files = glob.glob(f"{tmp}/audio.*")
        if r.returncode != 0 or not files:
            logger.warning("Audio download failed for %s: %s", video_id, r.stderr.strip()[-300:])
            return []
        try:
            with _whisper_lock:
                if _whisper is None:
                    from faster_whisper import WhisperModel
                    _whisper = _load_whisper()
                # decode with ffmpeg ourselves: faster-whisper's own PyAV decoder breaks on some PyAV versions
                cap = ["-t", str(WHISPER_MAX_SECONDS)] if WHISPER_MAX_SECONDS else []
                pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", files[0], *cap, "-ac", "1",
                                      "-ar", "16000", "-f", "f32le", "-"], capture_output=True, check=True, timeout=1800).stdout
                import numpy as np
                segments, _ = _whisper.transcribe(np.frombuffer(pcm, np.float32), task="translate", vad_filter=True, beam_size=1)
                segments = [(s.start, s.end, s.text) for s in segments]
        except Exception as e:  # noqa: BLE001 -- a broken audio file must not fail the keyword
            logger.warning("Speech-to-text failed for %s: %s", video_id, e)
            return []
    lines: list[dict] = []
    for start, end, text in segments:
        text = " ".join(text.split())
        if not text:
            continue
        if not lines or start - lines[-1]["start"] >= LINE_SECONDS:
            lines.append({"start": round(start, 1), "end": round(end, 1), "text": text})
        else:
            lines[-1]["text"] += " " + text
            lines[-1]["end"] = round(end, 1)
    logger.info("Speech-to-text for %s: %d lines", video_id, len(lines))
    return lines


class CaptionsBlocked(Exception):
    pass


# Free fallback when YouTube refuses captions to this machine's IP (shared with other tenants' scrapers, blocked for
# days at a time): public Invidious servers (open-source YouTube front-ends; they fetch from their own IP), paced
# through the same caption lock. FOOTAGE_INVIDIOUS="" turns it off. Speech-to-text is the dependable last step.
INVIDIOUS = os.environ.get("FOOTAGE_INVIDIOUS", "auto")   # auto = healthy API servers from api.invidious.io
_inv = {"list": [], "at": 0.0, "bad": {}}


def _invidious_servers() -> list[str]:
    if INVIDIOUS != "auto":
        return [u.strip().rstrip("/") for u in INVIDIOUS.split(",") if u.strip()]
    if time.time() - _inv["at"] > 6 * 3600:
        try:
            data = httpx.get("https://api.invidious.io/instances.json?sort_by=health", timeout=20).json()
            _inv["list"] = [d["uri"].rstrip("/") for _, d in data if d.get("type") == "https" and d.get("api")]
        except Exception as e:  # noqa: BLE001 -- keep the last list
            logger.warning("Invidious server list unavailable: %s", e)
        _inv["at"] = time.time()
    return [u for u in _inv["list"] if _inv["bad"].get(u, 0) < time.time()]


def _alt_caption_lines(video_id: str) -> list[dict]:
    for fn in (_invidious_lines,):
        try:
            with _caption_lock:
                lines = fn(video_id)
        except Exception as e:  # noqa: BLE001 -- a fallback failing must not fail the keyword
            logger.warning("%s failed for %s: %s", fn.__name__, video_id, e)
            continue
        if lines:
            logger.info("Captions for %s via %s: %d lines", video_id, fn.__name__.strip("_").split("_")[0], len(lines))
            return lines
    return []


def _invidious_lines(video_id: str) -> list[dict]:
    """English track, auto-generated first: Invidious can't tell real subtitles from lagging TV captions (both
    "English"), and the speech track's timing is what clip matching needs."""
    for base in _invidious_servers()[:3]:
        try:
            tracks = httpx.get(f"{base}/api/v1/captions/{video_id}", timeout=30).json().get("captions") or []
            en = [t for t in tracks if (t.get("languageCode") or "").startswith("en")]
            en.sort(key=lambda t: "auto" not in (t.get("label") or ""))
            if not en:
                return []                                   # the video has no English captions
        except Exception as e:  # noqa: BLE001 -- server down: try the next one; rest this one for 30 min
            logger.warning("Invidious %s: %s", base, e)
            _inv["bad"][base] = time.time() + 1800
            continue
        for t in en:                                        # some listed tracks 404 (e.g. CC1 duplicates): next one
            try:
                r = httpx.get(base + t["url"], timeout=60)
                r.raise_for_status()
                lines = _vtt_to_lines(r.text)
            except Exception as e:  # noqa: BLE001
                logger.info("Invidious %s track %r: %s", base, t.get("label"), e)
                continue
            if lines:
                return lines
    return []


def _download_caption(url: str) -> str:
    """One paced, browser-like caption request; a 429 pauses all caption requests for CAPTION_COOLDOWN (retrying is what
    turns YouTube's warning into an hours-long block)."""
    with _caption_lock:
        now = time.time()
        if now < _caption_state["blocked_until"]:
            raise CaptionsBlocked(f"caption downloads paused for {_caption_state['blocked_until'] - now:.0f} s after a 429")
        time.sleep(max(0.0, _caption_state["last"] + CAPTION_MIN_INTERVAL - now))
        try:
            try:
                from curl_cffi import requests as browser
                resp = browser.get(url, impersonate="chrome", timeout=90)
            except ImportError:
                resp = httpx.get(url, timeout=90)
        except Exception as e:  # noqa: BLE001 -- network errors of either client count as a failed download
            raise httpx.HTTPError(str(e)) from e
        finally:
            _caption_state["last"] = time.time()
        if resp.status_code == 429 and "tlang=" in url:
            # YouTube's machine translation (a video in another language) is rate-limited on its own: 3 of 10 of the
            # day's videos got 429 for it while their original captions and every other video's came back 200, from the
            # office IP and from WARP alike (2026-11-25). Only this video goes to speech-to-text; others keep captions.
            logger.info("YouTube refused a translated caption (429): this video goes to speech-to-text")
            raise CaptionsBlocked("429 from YouTube for a translated caption")
        if resp.status_code == 429:
            _caption_state["blocked_until"] = time.time() + CAPTION_COOLDOWN
            logger.warning("YouTube refused captions (429): pausing caption downloads for %.0f s", CAPTION_COOLDOWN)
            raise CaptionsBlocked("429 from YouTube")
        if resp.status_code >= 400:
            raise httpx.HTTPError(f"HTTP {resp.status_code}")
        return resp.text


def _fetch_info(video_id: str) -> dict | None:
    cmd = [
        settings.ytdlp_bin, "-J", "--skip-download", "--ignore-no-formats-error",
        "--no-warnings", "--no-playlist",
        # yt-dlp's default clients: their caption URLs need no PO token. Forcing the web client (2026-10-25) made every
        # caption URL need a subs PO token that YouTube then answered with an empty body -- captions never came.
    ]
    with cookies_args(settings.ytdlp_youtube_cookies_file) as cookie_args:
        try:
            result = subprocess.run(
                [*cmd, *cookie_args, f"https://www.youtube.com/watch?v={video_id}"],
                capture_output=True, text=True, timeout=60,
            )
        except subprocess.TimeoutExpired:
            logger.warning("Timed out fetching info for %s", video_id)
            return None
    if result.returncode != 0:
        logger.warning("yt-dlp failed for %s: %s", video_id, result.stderr.strip()[-500:])
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def _pick_caption_url(info: dict) -> str | None:
    """One English track, best first: YouTube's own speech recognition of
    English speech ("en-orig", or regional ones like "en-US-orig"), then
    human-written captions, then its machine translation of a non-English video
    ("en" in automatic_captions is a translation whenever no English
    original exists) -- still good enough to match against an English
    script, but YouTube rate-limits translation requests far harder, so it's
    strictly the last resort. srv1 is by far the smallest format
    (~9x smaller than json3), which matters because YouTube streams a
    track's first fetch slowly (~13KB/s observed)."""
    manual = info.get("subtitles") or {}
    auto = info.get("automatic_captions") or {}
    manual_en = sorted(lang for lang in manual if lang == "en" or lang.startswith("en-"))
    # YouTube's own speech track first: "manual" tracks on news uploads are often TV closed captions (CC1, DTVCC1)
    # that lag the picture by 4-6 s and open with the previous programme's words; clip matching needs the timing.
    auto_orig = sorted(
        (lang for lang in auto if lang.startswith("en") and lang.endswith("-orig")),
        key=lambda lang: lang != "en-orig",
    )
    candidates = [auto[lang] for lang in auto_orig] + [manual[lang] for lang in manual_en]
    if "en" in auto:
        candidates.append(auto["en"])
    for formats in candidates:
        for fmt in formats:
            if fmt.get("ext") == "srv1" and fmt.get("url"):
                return fmt["url"]
    return None


def _srv1_to_lines(xml_text: str) -> list[dict]:
    """Flattens srv1 caption cues (<text start=".." dur="..">) into
    ~LINE_SECONDS-long lines. Raw auto-caption cues are a few words each,
    which would make the transcript far longer (in tokens) than its actual
    content without telling the matcher anything more."""
    cues = []
    for node in ElementTree.fromstring(xml_text).iter("text"):
        start = float(node.get("start", 0))
        cues.append((start, start + float(node.get("dur", 0)), html.unescape(node.text or "")))
    return _cues_to_lines(cues)


def _ts(s: str) -> float:
    h, m, sec = ("0:" + s if s.count(":") == 1 else s).split(":")
    return int(h) * 3600 + int(m) * 60 + float(sec)


def _vtt_to_lines(vtt: str) -> list[dict]:
    """WebVTT (Invidious) to the same lines. Auto captions roll: each cue repeats the previous line and adds the new
    words (marked with <c> word timings), and 10 ms cues hold the finished line -- keep only the new words."""
    cues, prev = [], None
    for block in vtt.replace("\r", "").split("\n\n"):
        rows = block.strip("\n").split("\n")
        i = next((k for k, r in enumerate(rows) if "-->" in r), None)
        if i is None:
            continue
        a, b = rows[i].split("-->")
        start, end = _ts(a.strip()), _ts(b.split()[0])
        body = [r for r in rows[i + 1:] if r.strip()]
        if any("<c>" in r for r in body):
            body = [r for r in body if "<c>" in r][-1:]
        elif end - start < 0.05:
            continue
        text = html.unescape(re.sub(r"<[^>]+>", "", " ".join(body)))
        if text.strip() and text != prev:
            cues.append((start, end, text))
            prev = text
    return _cues_to_lines(cues)


def _cues_to_lines(cues) -> list[dict]:
    lines: list[dict] = []
    current: dict | None = None
    for start, end, text in cues:
        text = " ".join(text.split())
        if not text:
            continue
        if current is None or start - current["start"] >= LINE_SECONDS:
            current = {"start": round(start, 1), "end": round(end, 1), "text": text}
            lines.append(current)
        else:
            current["text"] = f"{current['text']} {text}"
            current["end"] = round(max(current["end"], end), 1)
    return lines
