"""Serve every fake behavior over HTTP: POST http://127.0.0.1:8811/<behavior>. Run it from the suite root."""
import json, os, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "agents"))
from fake import BEHAVIORS  # noqa: E402

PORT = 8811


class H(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("content-length") or 0))
        name = self.path.strip("/")
        if name not in BEHAVIORS:
            self.send_response(404); self.end_headers(); return
        out = json.dumps(BEHAVIORS[name](json.loads(body or b"{}"))).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
