"""Sign-in: the right password works; wrong ones lock the email and the address for 15 minutes; cookies are Secure
on the public HTTPS link only; sessions cannot be forged or outlive 30 days; sign-out works."""
import time

import app as api
import store
from conftest import PASSWORD, make_user


def login(c, pw=PASSWORD, email="ed@rig.test", ip="1.1.1.1", proto="http"):
    return c.post("/api/login", json={"email": email, "password": pw}, headers={"cf-connecting-ip": ip, "x-forwarded-proto": proto})


def test_right_password_signs_in_and_desk_opens(client):
    make_user()
    r = login(client)
    assert r.status_code == 200 and "rv_session" in r.headers["set-cookie"] and "httponly" in r.headers["set-cookie"].lower()
    assert client.get("/api/desk").json()["user"]["email"] == "ed@rig.test"


def test_email_is_case_and_space_insensitive(client):
    make_user()
    assert login(client, email="  ED@Rig.Test ").status_code == 200


def test_wrong_password_and_unknown_email(client):
    make_user()
    assert login(client, "nope").status_code == 401
    assert login(client, email="who@rig.test").status_code == 401
    assert client.get("/api/desk").status_code == 401


def test_cookie_secure_only_on_https(client):
    make_user()
    assert "secure" in login(client, proto="https").headers["set-cookie"].lower()
    assert "secure" not in login(client).headers["set-cookie"].lower()


def test_five_wrong_tries_lock_email_and_address(client):
    make_user()
    for _ in range(5):
        assert login(client, "wrong").status_code == 401
    assert login(client).status_code == 429                                   # the email, even with the right password
    assert login(client, ip="2.2.2.2").status_code == 429                     # from anywhere
    assert login(client, "x", email="other@rig.test").status_code == 429      # and that address, for any email
    api.FAILS.clear()
    assert login(client, ip="3.3.3.3").status_code == 200


def test_lock_ends_after_15_minutes(client, monkeypatch):
    make_user()
    for _ in range(5):
        login(client, "wrong", ip="4.4.4.4")
    t = time.time
    monkeypatch.setattr(api.time, "time", lambda: t() + 901)
    assert login(client, ip="4.4.4.4").status_code == 200


def test_right_password_clears_the_email_count(client):
    make_user()
    for _ in range(4):
        login(client, "wrong", ip=f"9.9.9.{_}")
    assert login(client, ip="8.8.8.8").status_code == 200
    for _ in range(4):
        login(client, "wrong", ip=f"7.7.7.{_}")
    assert login(client, ip="6.6.6.6").status_code == 200                     # 4 + 4 spread over two sign-ins: no lock


def test_logout(client):
    make_user()
    login(client)
    assert client.post("/api/logout").status_code == 200
    assert client.get("/api/desk").status_code == 401


def test_forged_or_expired_sessions_are_refused(client, monkeypatch):
    u = make_user()
    tok = store.session_token(u["id"])
    uid, exp, sig = tok.rsplit(".", 2)
    for bad in (f"{uid}.{exp}.{'0' * 64}", f"someone-else.{exp}.{sig}", f"{uid}.{int(exp) + 9}.{sig}", "x", ""):
        client.cookies.set("rv_session", bad)
        assert client.get("/api/desk").status_code == 401, bad
    client.cookies.set("rv_session", tok)
    assert client.get("/api/desk").status_code == 200
    later = store.now() + store.dt.timedelta(days=31)
    monkeypatch.setattr(store, "now", lambda: later)
    assert client.get("/api/desk").status_code == 401                         # 30-day session ran out


def test_a_deleted_account_is_signed_out(client):
    make_user()
    login(client)
    (store.DATA / "users.json").write_text("[]")
    assert client.get("/api/desk").status_code == 401


def test_password_hashes_never_leave_the_server(client):
    make_user()
    login(client)
    body = client.get("/api/desk").text
    assert "salt" not in body and "hash" not in body
