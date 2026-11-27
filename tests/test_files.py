"""Story files (/files/<id>/...): only that story's own files; never outside its folder; raw footage, render work and
unpicked voice files stay private (takes are shown); other workspaces get nothing."""
import store
from conftest import at_stage


def put(pid, rel, data=b"x"):
    f = store.pdir(pid) / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(data)


def test_own_files_are_served(ed):
    p = at_stage("done")
    put(p["id"], "final.mp4", b"video")
    put(p["id"], "voice/b1/takes/t1.wav", b"take")
    assert ed.get(f"/files/{p['id']}/final.mp4").content == b"video"
    assert ed.get(f"/files/{p['id']}/voice/b1/takes/t1.wav").content == b"take"


def test_private_folders_are_hidden(ed):
    p = at_stage("done")
    for rel in ("footage/src.mp4", "render/work.mp4", "voice/b1/raw.wav"):
        put(p["id"], rel)
        assert ed.get(f"/files/{p['id']}/{rel}").status_code == 404, rel


def test_no_way_out_of_the_story_folder(ed):
    """Raw paths straight to the handler (an HTTP client would tidy the dots away before sending)."""
    import pytest
    from fastapi import HTTPException
    import app as api
    p = at_stage("done")
    u = {"id": "u", "workspaceId": "dnl"}
    put(p["id"], "final.mp4")
    (store.DATA / "secret.txt").write_text("secret")
    for rel in ("../../users.json", "../../secret.txt", "../x/final.mp4", "/etc/passwd", "final.mp4/../../../secret.txt",
                "media/../../../secret.txt"):
        with pytest.raises(HTTPException) as e:
            api.files(p["id"], rel, u)
        assert e.value.status_code == 404, rel
    assert ed.get(f"/files/{p['id']}/..%2F..%2Fsecret.txt").status_code == 404


def test_missing_file_is_404(ed):
    assert ed.get(f"/files/{at_stage('done')['id']}/nothing.mp4").status_code == 404
