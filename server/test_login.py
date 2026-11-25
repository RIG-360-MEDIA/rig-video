"""Check: 5 wrong passwords lock that email (and that address) for 15 min; the right password then still waits; the
cookie is Secure on the public HTTPS link and not on the office http address. python test_login.py (API venv)"""
import os, sys, tempfile, time
os.environ["STUDIO_DATA"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fastapi import HTTPException, Response
from starlette.requests import Request
import app, store

store.adduser("ed@x.y", "Ed", "admin", "dnl", "right one")
app.time.sleep = lambda s: None                                  # no 1 s wait per wrong try in the test
req = lambda ip, proto="http": Request({"type": "http", "headers": [(b"cf-connecting-ip", ip.encode()), (b"x-forwarded-proto", proto.encode())],
                                        "client": ("127.0.0.1", 1)})


def login(pw, ip="1.1.1.1", proto="http", email="ed@x.y"):
    r = Response()
    try:
        app.login(req(ip, proto), r, {"email": email, "password": pw})
        return 200, r.headers.get("set-cookie", "")
    except HTTPException as e:
        return e.status_code, ""


code, ck = login("right one", proto="https")
assert code == 200 and "secure" in ck.lower(), ck
code, ck = login("right one")
assert code == 200 and "secure" not in ck.lower(), ck
for _ in range(5):
    assert login("wrong")[0] == 401
assert login("right one")[0] == 429                               # email locked
assert login("right one", ip="2.2.2.2")[0] == 429                 # from anywhere
assert login("x", ip="1.1.1.1", email="other@x.y")[0] == 429      # and that address, for any email
app.FAILS.clear()
assert login("right one", ip="3.3.3.3")[0] == 200
t = time.time
app.time.time = lambda: t() + 1000                                 # old failures age out after 15 min
for _ in range(4):
    login("wrong", ip="4.4.4.4")
assert login("right one", ip="4.4.4.4")[0] == 200
print("ok")
