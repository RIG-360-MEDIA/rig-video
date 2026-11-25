"""PUBLISH: a finished video that PASSED QC -> YouTube, UNLISTED, in the "Awaiting approval" playlist -> an editor reviews it
in the CMS (/studio/videos). Approve there = public + "Video Bulletin" playlist = on the site; Reject = deleted.

Nothing reaches the public before an editor approves: unlisted videos are not on the channel page, in search or in
subscriber feeds, and the site only reads the public "Video Bulletin" playlist. Each description carries the kicker on
line 1 and the story link, which is how the CMS and the site map a video to its story. Held videos never reach this.
Every delivered video also gets upload.txt (title + description) next to final.mp4 for a hand upload. Off until
~/.config/anchor-studio/youtube.env (mode 600) has YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN, YT_PENDING_PLAYLIST_ID
and PUBLISH_ENABLED=1 (orchestrator/youtube_auth.py; human steps in baseline/YOUTUBE_UPLOAD_ACCESS.md).
"""
import json
import os
import urllib.parse
import urllib.request

NEEDS = ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN", "YT_PENDING_PLAYLIST_ID")
PENDING_MAX_H = 36                                                  # unreviewed after this = stale news: deleted
SITE = os.environ.get("DNL_SITE", "https://global.democracynewslive.com")
API = "https://www.googleapis.com/youtube/v3"


def configured():
    """'' when publishing can run, else why not (logged; the video stays delivered on disk with upload.txt either way)."""
    if os.environ.get("PUBLISH_ENABLED") != "1":
        return "PUBLISH_ENABLED is not 1"
    missing = [k for k in NEEDS if not os.environ.get(k)]
    return f"missing {missing}" if missing else ""


def youtube_text(story_id, meta):
    """(title, description, tags). Line 1 of the description is the site's kicker; the story link maps video -> story."""
    kicker = " · ".join(x for x in ((meta.get("kicker") or "").capitalize(), (meta.get("location") or "").title()) if x)
    lines = [kicker or "Video Bulletin", "", meta.get("summary") or "", "",
             f"Read the full story: {SITE}/long-read/{story_id}", "",
             f"Presented by {meta['anchor_name']}, an AI-generated news anchor. The script is written from Democracy News "
             f"Live's reporting and fact-checked against it."]
    if meta.get("photo_page"):
        lines += ["", f"Background photo: {meta.get('photo_outlet') or ''} {meta['photo_page']}".replace("  ", " ")]
    title = meta["headline"] if len(meta["headline"]) <= 100 else meta["headline"][:97].rsplit(" ", 1)[0] + "..."
    tags = [t for t in ("Democracy News Live", "news", "world news", (meta.get("location") or "").title()) if t]
    return title, "\n".join(lines).replace("\n\n\n", "\n\n").strip(), tags


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
    with open(path, "rb") as f:
        req = urllib.request.Request(session, f.read(), {"Authorization": "Bearer " + token, "Content-Type": "video/mp4"}, method="PUT")
    video = json.load(urllib.request.urlopen(req, timeout=900))
    got = video.get("status", {}).get("privacyStatus")
    if got != meta["status"]["privacyStatus"]:
        log(f"publish: YouTube set the video to '{got}' (asked '{meta['status']['privacyStatus']}') - check the channel's upload "
            f"defaults / API project (baseline/YOUTUBE_UPLOAD_ACCESS.md)")
    return video


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


def publish(date, story_id, folder, meta, log=print):
    """folder holds final.mp4 (anchor_daily.do_post, QC passed). Returns the YouTube URL, or None if not published."""
    title, description, tags = youtube_text(story_id, meta)
    (folder / "upload.txt").write_text(f"TITLE:\n{title}\n\nDESCRIPTION:\n{description}\n\nTAGS: {', '.join(tags)}\n"
                                       f"Category: News & Politics | Altered or synthetic content: YES | Made for kids: NO\n"
                                       f"Playlist: Awaiting approval (an editor approves it in the CMS; approval moves it to Video Bulletin)\n")
    why = configured()
    if why:
        log(f"publish: skipped ({why}) - upload by hand from {folder} (final.mp4 + upload.txt)")
        return None
    mark = folder / "youtube.json"                                 # written right after the upload: a crash or a retry
    done = json.loads(mark.read_text()) if mark.exists() else {}    # never uploads the same video twice
    if not done:
        from . import select_stories
        if select_stories.editor_status([story_id]).get(story_id) in ("killed", "held"):
            log(f"publish: {story_id} is no longer public on the site (editor kill/hold) - not uploaded")
            return None
    token = _token()
    if not done:
        video = upload(folder / "final.mp4", title, description, tags, token, log=log)
        done = {"id": video["id"], "privacy": video.get("status", {}).get("privacyStatus"), "pending": False}
        mark.write_text(json.dumps(done))
    if not done["pending"]:                                         # a failed playlist add is completed on retry
        add_to_playlist(done["id"], token)
        done["pending"] = True
        mark.write_text(json.dumps(done))
    url = f"https://www.youtube.com/watch?v={done['id']}"
    log(f"publish: {story_id} -> {url} ({done.get('privacy')}) - awaiting approval in the CMS")
    return url


def expire_pending(log=print, max_h=PENDING_MAX_H):
    """Delete videos still awaiting approval after max_h hours (stale news). Run nightly; returns the deleted ids."""
    import datetime
    if configured():
        return []
    token, gone = _token(), []
    items = json.load(urllib.request.urlopen(urllib.request.Request(
        f"{API}/playlistItems?part=snippet,contentDetails&maxResults=50&playlistId={os.environ['YT_PENDING_PLAYLIST_ID']}",
        headers={"Authorization": "Bearer " + token}), timeout=60)).get("items", [])
    now = datetime.datetime.now(datetime.timezone.utc)
    for it in items:
        added = datetime.datetime.fromisoformat(it["snippet"]["publishedAt"].replace("Z", "+00:00"))   # when it joined the playlist
        if (now - added).total_seconds() > max_h * 3600:
            vid = it["contentDetails"]["videoId"]
            urllib.request.urlopen(urllib.request.Request(f"{API}/videos?id={vid}", headers={"Authorization": "Bearer " + token},
                                                          method="DELETE"), timeout=60).read()
            gone.append(vid)
            log(f"publish: deleted {vid} - not reviewed within {max_h} h")
    return gone


if __name__ == "__main__":                                         # self-check of the text the site parses
    import re
    t, d, tags = youtube_text("475794d0-1004-417f-8f52-0e26ebc7effb", {
        "headline": "A Powerful Quake Shakes Panama, Leaving Dozens Injured", "anchor_name": "Maren Ashcroft",
        "kicker": "BREAKING NEWS", "location": "PANAMA CITY", "summary": "A 7.7 quake damaged hundreds of buildings.",
        "photo_outlet": "cbsnews.com", "photo_page": "https://www.cbsnews.com/x"})
    assert d.split("\n")[0] == "Breaking news · Panama City", d          # the site's kicker = line 1 (<= 60 chars, no link)
    assert re.search(r"long-read/475794d0-1004-417f-8f52-0e26ebc7effb", d)  # the site maps video -> story with this
    assert "AI-generated" in d and "\n\n\n" not in d and len(t) <= 100
    assert configured() in ("PUBLISH_ENABLED is not 1",) or not configured()
    print("publish self-check OK")
