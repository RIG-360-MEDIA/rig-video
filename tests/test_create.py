"""New stories: from text, a link, an uploaded file or one of today's picks; the length, format and source are checked
before anything is made; a made story starts its script job; nothing is made from a refused request."""
import io
import zipfile

import pytest

import store
from conftest import ARTICLE, jobs, write_selection


def made():
    return store.all_projects()


def test_from_text(ed, spawned):
    r = ed.post("/api/projects", json={"kind": "text", "text": ARTICLE, "seconds": 60, "format": "vo_only"})
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["stage"] == "script" and p["format"] == "vo_only" and p["targetSeconds"] == 60 and p["source"]["kind"] == "text"
    assert p["headline"].startswith("Floods hit the Kathmandu valley")
    assert jobs(spawned) == ["write"] and spawned[0][0] == p["id"]
    q = store.read(p["id"])
    assert q["_workspace"] == "dnl" and q["_by"].startswith("u") and q["anchorId"]


def test_from_link(ed, spawned):
    p = ed.post("/api/projects", json={"kind": "link", "url": "https://www.example.com/news/big-flood-in-nepal"}).json()
    assert p["source"]["site"] == "example.com" and p["headline"] == "big flood in nepal" and jobs(spawned) == ["write"]


def test_from_a_pick_uses_the_article_and_leaves_the_picks(ed, spawned):
    picks, _ = write_selection(["Floods in Nepal", "Other"])
    p = ed.post("/api/projects", json={"kind": "pick", "pickId": picks[0], "seconds": 60}).json()
    assert p["headline"] == "Floods in Nepal" and p["source"]["site"] == "DNL selection" and p["source"]["text"] == ARTICLE
    assert store.read(p["id"])["_pick"] == picks[0]
    assert [x["headline"] for x in ed.get("/api/desk").json()["picks"]] == ["Other"]


@pytest.mark.parametrize("body,code,msg", [
    ({"kind": "text", "text": "Too short."}, 400, "too short"),
    ({"kind": "link", "url": "not a link"}, 400, "not a link"),
    ({"kind": "pick", "pickId": "nope"}, 404, "no longer"),
    ({"kind": "magic", "text": ARTICLE}, 400, "Unknown source"),
    ({"kind": "text", "text": ARTICLE, "seconds": 10}, 400, "length"),
    ({"kind": "text", "text": ARTICLE, "seconds": 601}, 400, "length"),
    ({"kind": "text", "text": ARTICLE, "format": "hologram"}, 400, "Unknown format"),
])
def test_refused_requests_make_nothing(ed, spawned, body, code, msg):
    r = ed.post("/api/projects", json=body)
    assert r.status_code == code and msg.lower() in r.json()["detail"].lower(), r.text
    assert made() == [] and spawned == []


def test_picks_are_dnl_only(outsider, spawned):
    picks, _ = write_selection(["A"])
    assert outsider.post("/api/projects", json={"kind": "pick", "pickId": picks[0]}).status_code == 404 and made() == []


def test_new_stories_belong_to_the_makers_workspace(outsider):
    p = outsider.post("/api/projects", json={"kind": "text", "text": ARTICLE}).json()
    assert store.read(p["id"])["_workspace"] == "other"


def docx(text):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                   f'<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>')
    return buf.getvalue()


@pytest.mark.parametrize("name,data", [("story.txt", ARTICLE.encode()), ("story.md", ARTICLE.encode()), ("My_story.docx", docx(ARTICLE))])
def test_from_file(ed, spawned, name, data):
    r = ed.post("/api/projects/file", data={"seconds": "90", "format": "anchor_vo"}, files={"file": (name, data)})
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["source"]["kind"] == "file" and p["targetSeconds"] == 90 and "Kathmandu" in p["source"]["text"]
    assert jobs(spawned) == ["write"]


def test_file_title_comes_from_its_name(ed):
    p = ed.post("/api/projects/file", files={"file": ("Nepal_floods.docx", docx(ARTICLE))}).json()
    assert p["headline"] == "Nepal floods"


@pytest.mark.parametrize("name,data,code", [("a.exe", b"x" * 100, 400), ("bad.docx", b"not a zip", 400), ("bad.pdf", b"%PDF-broken", 400),
                                            ("short.txt", b"Too short.", 400)])
def test_bad_files_are_refused(ed, spawned, name, data, code):
    assert ed.post("/api/projects/file", files={"file": (name, data)}).status_code == code and made() == [] and spawned == []


def test_file_over_20mb_is_refused(ed):
    assert ed.post("/api/projects/file", files={"file": ("big.txt", b"a " * (10 * 2 ** 20 + 1))}).status_code == 413
