import html
import re
import json
import logging
import subprocess

import httpx

from app.core.config import settings
from app.search import youtube

logger = logging.getLogger(__name__)


AFTER = re.compile(r"\s*\bafter:(\d{4}-\d{2}-\d{2})\b")
LIMIT = re.compile(r"\s*\blimit:(\d{1,2})\b")      # a caller asking for more (or fewer) videos than the default


async def search_videos(query: str, limit: int) -> list[dict]:
    """A query may carry "after:YYYY-MM-DD": only videos uploaded from that day (the story's event window), so years of
    older uploads of the same place don't crowd out this event's. The yt-dlp fallback asks YouTube's own results page
    for the smallest upload-date window that holds that day (this week / month / year).
    YouTube Data API first; yt-dlp's own ytsearch as a fallback. The API's
    search call costs 100 of the default 10,000 daily quota units (so ~100
    keywords a day), and a batched script project burns through that fast --
    when the key is missing or the quota is spent, scraping the results page
    via yt-dlp still works, just slower."""
    m = AFTER.search(query)
    after = m.group(1) if m else None
    query = AFTER.sub("", query).strip()
    n = LIMIT.search(query)
    if n:
        limit = max(1, min(25, int(n.group(1))))
        query = LIMIT.sub("", query).strip()
    if settings.youtube_api_key:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                items = await youtube.search(client, query, limit, settings.youtube_api_key, after)
            return [
                {
                    "video_id": item["video_id"],
                    "title": html.unescape(item["title"]),
                    "channel": html.unescape(item.get("channel", "")),
                    "description": html.unescape(item.get("description", "")),
                    "thumbnail_url": item.get("thumbnail_url"),
                    "published_at": item.get("published_at"),
                    "duration_seconds": None,
                }
                for item in items
            ]
        except Exception as e:
            logger.warning("YouTube API search failed for %r, falling back to yt-dlp: %s", query, e)
    return _ytdlp_search(query, limit, after)


# YouTube results-page upload-date filters (the "sp" parameter): this week, this month, this year
_SP = ((7, "EgIIAw%253D%253D"), (31, "EgIIBA%253D%253D"), (365, "EgIIBQ%253D%253D"))


def _ytdlp_search(query: str, limit: int, after: str | None = None) -> list[dict]:
    target = f"ytsearch{limit}:{query}"
    if after:
        import datetime as dt
        import urllib.parse
        age = (dt.date.today() - dt.date.fromisoformat(after)).days
        sp = next((code for days, code in _SP if age <= days), None)
        if sp:
            target = f"https://www.youtube.com/results?search_query={urllib.parse.quote_plus(query)}&sp={sp}"
    result = subprocess.run(
        [settings.ytdlp_bin, "--flat-playlist", "-J", "--no-warnings", "--playlist-end", str(limit), target],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"YouTube search failed: {result.stderr.strip()[-300:]}")
    entries = json.loads(result.stdout).get("entries") or []
    videos = []
    for e in entries:
        if not e.get("id"):
            continue
        thumbs = e.get("thumbnails") or []
        videos.append({
            "video_id": e["id"],
            "title": e.get("title") or "",
            "channel": e.get("channel") or e.get("uploader") or "",
            "description": e.get("description") or "",
            "thumbnail_url": thumbs[-1]["url"] if thumbs else f"https://i.ytimg.com/vi/{e['id']}/mqdefault.jpg",
            "published_at": None,
            "duration_seconds": e.get("duration"),
        })
    return videos
