"""Check: writer.ask reports a slow (contended) t3 as Busy and returns a fast one's JSON. python test_writer_busy.py"""
import http.server, json, os, sys, threading, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../studio-app/pipeline"))
import writer

class H(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        if self.server.fast is None: time.sleep(3)   # never sends a first token in time
        self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.end_headers()
        for ch in ['{"a"', ': 1', '}'] * (1 if self.server.fast else 40):
            self.wfile.write(b"data: " + json.dumps({"choices": [{"delta": {"content": ch}}]}).encode() + b"\n\n"); self.wfile.flush()
            time.sleep(0 if self.server.fast else 0.5)
        self.wfile.write(b"data: [DONE]\n\n")
    def log_message(self, *a): pass

def serve(fast):
    s = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H); s.fast = fast
    threading.Thread(target=s.serve_forever, daemon=True).start()
    os.environ["LLM_PROVIDERS"] = json.dumps([{"name": "t3", "base_url": f"http://127.0.0.1:{s.server_port}/v1", "key_env": "K", "model": "w"}])
    os.environ["K"] = "x"

writer.CHECK_AFTER_S, writer.MIN_TPS = 2, 6
serve(True); assert writer.ask("s", "u", {}, 10) == {"a": 1}
serve(False)
try:
    writer.ask("s", "u", {}, 10); raise SystemExit("slow writer not caught")
except writer.Busy as e:
    assert "busy" in str(e)
writer.FIRST_TOKEN_S = 1
serve(None)
try:
    writer.ask("s", "u", {}, 10); raise SystemExit("silent writer not caught")
except writer.Busy:
    pass
print("ok")
