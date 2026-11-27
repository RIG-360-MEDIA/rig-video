"""Every API route, checked automatically from the app's own route table:
- a route nobody listed here fails the suite, so a new endpoint cannot ship without being thought about;
- every route needs sign-in, except the few public ones;
- a story is invisible to anyone outside its workspace, on every route that takes a story id."""
import os
import re

import pytest

import app as api
from conftest import at_stage

PUBLIC = {("POST", "/api/login"), ("POST", "/api/logout"), ("GET", "/api/health"), ("GET", "/api/anchors"),
          ("GET", "/anchor-media/{aid}/{name}")}
SIGNED_IN = {
    ("GET", "/api/desk"), ("PUT", "/api/prefs"), ("POST", "/api/projects"), ("POST", "/api/daily/start"),
    ("POST", "/api/projects/file"), ("PUT", "/api/projects/{pid}"), ("POST", "/api/projects/{pid}/approve"),
    ("POST", "/api/projects/{pid}/switch"), ("POST", "/api/projects/{pid}/retry"), ("POST", "/api/projects/{pid}/revoice"),
    ("POST", "/api/projects/{pid}/rewrite"), ("GET", "/api/places"), ("POST", "/api/projects/{pid}/keywords"),
    ("POST", "/api/projects/{pid}/keywords/{kid}/research"), ("POST", "/api/projects/{pid}/moments"),
    ("POST", "/api/projects/{pid}/uploads"), ("POST", "/api/projects/{pid}/maps"), ("POST", "/api/projects/{pid}/render"),
    ("POST", "/api/projects/{pid}/final"), ("GET", "/api/projects/{pid}/post"), ("POST", "/api/projects/{pid}/post"),
    ("POST", "/api/post-all"), ("POST", "/api/projects/{pid}/cancel"), ("POST", "/api/projects/{pid}/moveup"),
    ("POST", "/api/projects/{pid}/remake"), ("POST", "/api/projects/{pid}/archive"), ("POST", "/api/library/{item}/duplicate"),
    ("GET", "/files/{pid}/{rel:path}"),
}
SITE = {("GET", "/{path:path}")}                                    # the built site (only when web/dist was built)
DOCS = {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}


def routes():
    out = set()
    for r in api.app.routes:
        if getattr(r, "path", None) in DOCS or not hasattr(r, "methods"):
            continue
        for m in r.methods - {"HEAD", "OPTIONS"}:
            out.add((m, r.path))
    return out


def test_every_route_is_listed():
    """A new route must be added to PUBLIC or SIGNED_IN here (and get its own tests) before it can merge."""
    unknown = routes() - PUBLIC - SIGNED_IN - SITE
    if os.environ.get("RV_REGRESSION"):                             # main's copy of this file judging a PR: a NEW route is
        unknown = set()                                             # checked by the PR's own copy (job "PR's own tests")
    assert not unknown, f"new API route(s) with no tests: {sorted(unknown)}. Add them to tests/test_routes.py and test them."
    gone = (PUBLIC | SIGNED_IN) - routes()
    assert not gone, f"route(s) the site relies on are gone: {sorted(gone)}"


def fill(path, pid="floods-hit-kathmandu-1234"):
    return re.sub(r"\{[^}]+\}", lambda m: {"{pid}": pid, "{item}": "lib-" + pid, "{rel:path}": "final.mp4"}.get(m.group(0), "x1"), path)


def call(c, method, path, **kw):
    if path.endswith(("/uploads", "/maps", "/projects/file")):
        return c.request(method, path, data={"sid": "b1", "seconds": "60"}, files={"file": ("a.jpg", b"x", "image/jpeg")})
    return c.request(method, path, json={}, **kw) if method in ("POST", "PUT") else c.request(method, path)


@pytest.mark.parametrize("method,path", sorted(SIGNED_IN))
def test_signed_out_is_refused(client, method, path):
    assert call(client, method, fill(path)).status_code == 401


def test_anchor_frame_needs_sign_in(client):
    assert client.get("/anchor-media/maren_ashcroft/frame.jpg").status_code == 401


@pytest.mark.parametrize("method,path", sorted(r for r in SIGNED_IN if "{pid}" in r[1] or "{item}" in r[1]))
def test_other_workspace_never_sees_a_story(outsider, method, path):
    p = at_stage("done")
    r = call(outsider, method, fill(path, p["id"]))
    assert r.status_code == 404, (r.status_code, r.text)


def test_bad_story_ids_are_404_not_errors(ed):
    for pid in ("UPPER", "a", "x" * 61, "a b c"):
        assert ed.get(f"/api/projects/{pid}/post").status_code in (404, 405)
