"""Check: the YouTube upload goes in pieces with Content-Range, a dropped piece is sent again from where the server says
it stopped, and the finished video comes back. A local fake of YouTube's resumable upload. python test_upload.py"""
import http.server, json, os, sys, tempfile, threading
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../studio-app/pipeline"))
from orchestrator import publish

publish.CHUNK = 256 * 1024
publish.time.sleep = lambda s: None
data = os.urandom(publish.CHUNK * 3 + 1000)
got, seen = bytearray(), {"drop": True, "puts": 0}


class Fake(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_PUT(self):
        seen["puts"] += 1
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        rng = self.headers["Content-Range"]
        if rng.startswith("bytes */"):                                  # "how much do you have?"
            pass
        else:
            start = int(rng.split()[1].split("-")[0])
            if start == publish.CHUNK and seen["drop"]:                 # the second piece is lost once
                seen["drop"] = False
                self.connection.close()
                return
            assert start == len(got), (start, len(got))
            got.extend(body)
        if len(got) == len(data):
            out = json.dumps({"id": "vid123", "status": {"privacyStatus": "unlisted"}}).encode()
            self.send_response(200); self.send_header("Content-Length", str(len(out))); self.end_headers(); self.wfile.write(out)
        else:
            self.send_response(308)
            if got:
                self.send_header("Range", f"bytes=0-{len(got) - 1}")
            self.send_header("Content-Length", "0"); self.end_headers()


srv = http.server.HTTPServer(("127.0.0.1", 0), Fake)
threading.Thread(target=srv.serve_forever, daemon=True).start()
f = tempfile.NamedTemporaryFile(delete=False); f.write(data); f.close()
v = publish._send_chunks(f"http://127.0.0.1:{srv.server_port}/up", f.name, len(data), "tok", lambda m: None)
assert v["id"] == "vid123" and bytes(got) == data and not seen["drop"], (v, len(got))
print("ok")
