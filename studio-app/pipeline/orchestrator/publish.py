"""YouTube for RIG-Video (worker.step_post): upload() a finished video UNLISTED, add_to_playlist() puts it in "Awaiting
approval" (the queue DNL's CMS shows), set_text() updates title/description, approve() makes it public and moves it to
"Video Bulletin". Needs ~/.config/anchor-studio/youtube.env (YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN,
YT_PENDING_PLAYLIST_ID, YT_BULLETIN_PLAYLIST_ID), made once with orchestrator/youtube_auth.py
(human steps: docs/design/YOUTUBE_UPLOAD_ACCESS.md)."""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

NEEDS = ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN", "YT_PENDING_PLAYLIST_ID")
SITE = os.environ.get("DNL_SITE", "https://global.democracynewslive.com")
API = "https://www.googleapis.com/youtube/v3"


def _token():
    body = urllib.parse.urlencode({"client_id": os.environ["YT_CLIENT_ID"], "client_secret": os.environ["YT_CLIENT_SECRET"],
                                   "refresh_token": os.environ["YT_REFRESH_TOKEN"], "grant_type": "refresh_token"}).encode()
    return json.load(urllib.request.urlopen("https://oauth2.googleapis.com/token", body, timeout=30))["access_token"]


def upload(path, title, description, tags, token, privacy=None, log=print):
    """Resumable upload; returns the video resource. Flags altered/synthetic content (realistic AI presenters)."""
    meta = {"snippet": {"title": title, "description": description, "tags": tags, "categoryId": "25",   # News & Politics
                        "defaultLanguage": "en", "defaultAudioLanguage": "en"},
            "status": {"privacyStatus": privacy or "unlisted", "embeddable": True,
                       "selfDeclaredMadeForKids": False, "containsSyntheticMedia": True}}
    size = os.path.getsize(path)
    start = urllib.request.Request(f"https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
                                   json.dumps(meta).encode(), {"Authorization": "Bearer " + token, "Content-Type": "application/json",
                                                               "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(size)})
    session = urllib.request.urlopen(start, timeout=60).headers["Location"]
    video = _send_chunks(session, path, size, token, log)
    got = video.get("status", {}).get("privacyStatus")
    if got != meta["status"]["privacyStatus"]:
        log(f"publish: YouTube set the video to '{got}' (asked '{meta['status']['privacyStatus']}') - check the channel's upload "
            f"defaults / API project (docs/design/YOUTUBE_UPLOAD_ACCESS.md)")
    return video


CHUNK = 4 * 1024 * 1024                                                # a multiple of 256 KiB, as YouTube asks


def _sent_so_far(session, size, token):
    """Ask YouTube how much of a resumable upload it has: the next byte to send, or the video when it is complete."""
    req = urllib.request.Request(session, b"", {"Authorization": "Bearer " + token, "Content-Range": f"bytes */{size}"}, method="PUT")
    try:
        return json.load(urllib.request.urlopen(req, timeout=60))
    except urllib.error.HTTPError as e:
        if e.code != 308:
            raise
        got = e.headers.get("Range")                                    # "bytes=0-N" or none yet
        return int(got.split("-")[1]) + 1 if got else 0


def _send_chunks(session, path, size, token, log, tries=8):
    """The file in CHUNK pieces, each with its own time limit; a piece that fails is sent again from where YouTube says
    it stopped. One PUT of the whole file timed out on a slow office line (2026-11-26: ~120 KB/s, Python's socket
    timeout covers the whole send, so 20 MB > 900 s failed every time)."""
    pos, fails = 0, 0
    with open(path, "rb") as f:
        while True:
            f.seek(pos)
            data = f.read(CHUNK)
            end = pos + len(data) - 1
            req = urllib.request.Request(session, data, {"Authorization": "Bearer " + token, "Content-Type": "video/mp4",
                                                         "Content-Range": f"bytes {pos}-{end}/{size}"}, method="PUT")
            try:
                return json.load(urllib.request.urlopen(req, timeout=300))        # 200/201: the last piece, the video
            except urllib.error.HTTPError as e:
                if e.code != 308:
                    raise
                got = e.headers.get("Range")
                pos, fails = (int(got.split("-")[1]) + 1 if got else 0), 0
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
                fails += 1
                if fails > tries:
                    raise
                log(f"publish: upload piece at {pos} failed ({e}); asking YouTube where it stopped ({fails}/{tries})")
                time.sleep(min(60, 5 * fails))
                got = _sent_so_far(session, size, token)
                if isinstance(got, dict):
                    return got
                pos = got
            log(f"publish: uploaded {pos * 100 // size}%")


def add_to_playlist(video_id, token, playlist=None):
    body = {"snippet": {"playlistId": playlist or os.environ["YT_PENDING_PLAYLIST_ID"],
                        "resourceId": {"kind": "youtube#video", "videoId": video_id}}}
    req = urllib.request.Request(f"{API}/playlistItems?part=snippet", json.dumps(body).encode(),
                                 {"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=60))


def _call(url, token, method="GET", body=None):
    req = urllib.request.Request(url, None if body is None else json.dumps(body).encode(),
                                 {"Authorization": "Bearer " + token, **({} if body is None else {"Content-Type": "application/json"})},
                                 method=method)
    raw = urllib.request.urlopen(req, timeout=60).read()
    return json.loads(raw) if raw else {}


def _items_of(playlist, video_id, token):
    q = urllib.parse.urlencode({"part": "id", "maxResults": 50, "playlistId": playlist, "videoId": video_id})
    return [it["id"] for it in _call(f"{API}/playlistItems?{q}", token).get("items", [])]


STATUS_KEYS = ("embeddable", "license", "publicStatsViewable", "selfDeclaredMadeForKids")   # videos.update drops what it is not sent


def set_text(video_id, title, description, token):
    """A title / description changed after the upload (the Post dialog): videos.update needs the whole snippet."""
    sn = _call(f"{API}/videos?part=snippet&id={urllib.parse.quote(video_id)}", token)["items"][0]["snippet"]
    keep = {k: sn[k] for k in ("tags", "categoryId", "defaultLanguage", "defaultAudioLanguage") if k in sn}
    _call(f"{API}/videos?part=snippet", token, "PUT", {"id": video_id, "snippet": {**keep, "title": title, "description": description}})


def approve(video_id, token, privacy="public"):
    """The CMS's Approve (dnl-anchor-video src/lib/youtube/client.ts approveVideo), from the studio site: into "Video
    Bulletin" first (the DNL site lists only its public videos, so this is invisible), then public, then out of
    "Awaiting approval". Each step is skipped when done, so a retry after any failure is safe. `privacy` other than
    public is for tests only."""
    v = _call(f"{API}/videos?part=status&id={urllib.parse.quote(video_id)}", token).get("items", [])
    if not v:
        raise RuntimeError(f"video {video_id} not found on YouTube")
    st = v[0]["status"]
    pending = _items_of(os.environ["YT_PENDING_PLAYLIST_ID"], video_id, token)
    if not _items_of(os.environ["YT_BULLETIN_PLAYLIST_ID"], video_id, token):
        add_to_playlist(video_id, token, os.environ["YT_BULLETIN_PLAYLIST_ID"])
    if st.get("privacyStatus") != privacy:
        _call(f"{API}/videos?part=status", token, "PUT", {"id": video_id, "status": {
            "privacyStatus": privacy, "containsSyntheticMedia": True, **{k: st[k] for k in STATUS_KEYS if k in st}}})
    for i in pending:
        _call(f"{API}/playlistItems?id={urllib.parse.quote(i)}", token, "DELETE")


