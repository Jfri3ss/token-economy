# Serves this folder and saves PNGs posted to /save?name=x.png (rendering helper for the README graphics).
import http.server, os, re, sys
ROOT = os.path.dirname(os.path.abspath(__file__))
class H(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k): super().__init__(*a, directory=ROOT, **k)
    def do_POST(self):
        name = self.path.split("name=")[-1]
        if not re.fullmatch(r"[\w.-]+\.png", name):
            self.send_response(400); self.end_headers(); return
        data = self.rfile.read(int(self.headers["Content-Length"]))
        open(os.path.join(ROOT, "out", name), "wb").write(data)
        self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
os.makedirs(os.path.join(ROOT, "out"), exist_ok=True)
http.server.ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
