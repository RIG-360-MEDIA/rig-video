"""One-time YouTube authorization for the publish step (docs/design/YOUTUBE_UPLOAD_ACCESS.md, step 7). Run on the Mac.

  python -m orchestrator.youtube_auth ~/Downloads/client_secret_XXXX.json      # the channel owner signs in in the browser
  python -m orchestrator.youtube_auth --playlists                              # create "Awaiting approval" + "Video Bulletin"
  python -m orchestrator.youtube_auth --test path/to/short.mp4                 # private test upload: right channel? locked?

Google's installed-app flow (loopback redirect + PKCE), stdlib only. The tokens go to
~/.config/anchor-studio/youtube.env (mode 600); copy that file to trijya-7 (deploy does not). Nothing is printed except
the channel the token belongs to.
"""
import base64
import hashlib
import http.server
import json
import os
import pathlib
import secrets
import sys
import urllib.parse
import urllib.request
import webbrowser

ENV = pathlib.Path.home() / ".config" / "anchor-studio" / "youtube.env"
SCOPES = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube"


def _env():
    return dict(l.split("=", 1) for l in ENV.read_text().split("\n") if "=" in l) if ENV.exists() else {}


def _save(values):
    ENV.parent.mkdir(parents=True, exist_ok=True)
    cur = _env() | values
    ENV.write_text("".join(f"{k}={v}\n" for k, v in cur.items()))
    ENV.chmod(0o600)


def authorize(client_json):
    c = json.load(open(client_json))
    c = c.get("installed") or c.get("web") or c
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    got = {}

    class Catch(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            got.update(urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Authorized - you can close this tab and return to Claude.")

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), Catch)
    redirect = f"http://127.0.0.1:{srv.server_port}"
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "client_id": c["client_id"], "redirect_uri": redirect, "response_type": "code", "scope": SCOPES,
        "access_type": "offline", "prompt": "consent", "code_challenge": challenge, "code_challenge_method": "S256"})
    print("Opening Google sign-in. Sign in as the DNL channel Owner/Manager and pick the DNL channel.\n", url)
    webbrowser.open(url)
    srv.handle_request()
    if "code" not in got:
        sys.exit(f"no authorization code: {got.get('error')}")
    tok = json.load(urllib.request.urlopen("https://oauth2.googleapis.com/token", urllib.parse.urlencode({
        "code": got["code"][0], "client_id": c["client_id"], "client_secret": c["client_secret"], "redirect_uri": redirect,
        "grant_type": "authorization_code", "code_verifier": verifier}).encode(), timeout=30))
    if "refresh_token" not in tok:
        sys.exit("Google returned no refresh token - remove the app's access at myaccount.google.com/permissions and retry")
    _save({"YT_CLIENT_ID": c["client_id"], "YT_CLIENT_SECRET": c["client_secret"], "YT_REFRESH_TOKEN": tok["refresh_token"]})
    me = _api("GET", "channels?part=snippet&mine=true", token=tok["access_token"])
    print("Authorized for channel:", [(i["id"], i["snippet"]["title"]) for i in me.get("items", [])], "->", ENV)


def _token():
    e = _env()
    return json.load(urllib.request.urlopen("https://oauth2.googleapis.com/token", urllib.parse.urlencode({
        "client_id": e["YT_CLIENT_ID"], "client_secret": e["YT_CLIENT_SECRET"], "refresh_token": e["YT_REFRESH_TOKEN"],
        "grant_type": "refresh_token"}).encode(), timeout=30))["access_token"]


def _api(method, path, body=None, token=None):
    req = urllib.request.Request(f"https://www.googleapis.com/youtube/v3/{path}", json.dumps(body).encode() if body else None,
                                 {"Authorization": "Bearer " + (token or _token()), "Content-Type": "application/json"}, method=method)
    raw = urllib.request.urlopen(req, timeout=60).read()
    return json.loads(raw) if raw else {}                           # DELETE answers 204 with no body


def make_playlists():
    """The two playlists the flow needs: 'Awaiting approval' (private; the CMS lists it) and 'Video Bulletin' (public; the
    site shows it). Re-running reuses playlists that already exist with these titles."""
    have = {p["snippet"]["title"]: p["id"] for p in _api("GET", "playlists?part=snippet&mine=true&maxResults=50").get("items", [])}
    for title, privacy, var, desc in (
            ("Awaiting approval", "private", "YT_PENDING_PLAYLIST_ID", "Anchor Studio videos waiting for an editor's approval in the CMS."),
            ("Video Bulletin", "public", "YT_BULLETIN_PLAYLIST_ID", "Democracy News Live's daily 60-second news bulletins, presented by "
             "AI-generated anchors. Full stories: https://global.democracynewslive.com")):
        pid = have.get(title) or _api("POST", "playlists?part=snippet,status", {
            "snippet": {"title": title, "description": desc, "defaultLanguage": "en"}, "status": {"privacyStatus": privacy}})["id"]
        _save({var: pid})
        print(f"{title} ({privacy}): https://www.youtube.com/playlist?list={pid}")


def test_upload(path):
    from . import publish
    v = publish.upload(path, "Anchor Studio test upload (private)", "Test of the automated upload. Not for publication.",
                       ["test"], _token(), privacy="private")
    print("Uploaded:", f"https://www.youtube.com/watch?v={v['id']}", "status:", v.get("status"))


if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "--playlists":
        make_playlists()
    elif a[:1] == ["--test"] and len(a) == 2:
        test_upload(a[1])
    elif len(a) == 1:
        authorize(os.path.expanduser(a[0]))
    else:
        sys.exit(__doc__)
