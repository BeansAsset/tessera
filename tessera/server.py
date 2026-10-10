"""The small web service the phone's shortcuts talk to, on the local network.

    GET  /start    plain text: the address of the page to open, with a challenge
    POST /answer   the signed answer (raw, JSON {"answer": ...} or form answer=...);
                   plain text back: a message to show on the phone

It never unlocks anything by itself: every answer goes through Gate, which
checks the Face ID signature. Requests are small and short-lived.
"""

import json
import socket
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .webauthn import Refused

MAX_BODY = 16 * 1024


def read_answer(body, content_type=None):
    """The answer, however the shortcut sent it. Labels can't be trusted to
    match the contents, so anything that isn't a JSON or form field named
    "answer" is taken as the answer itself."""
    text = body.decode("utf-8", "replace").strip()
    if text.startswith("{"):
        try:
            data = json.loads(text)
        except ValueError:
            data = None
        if isinstance(data, dict) and "answer" in data:
            return str(data["answer"])
    if text.startswith("answer="):
        return urllib.parse.parse_qs(text).get("answer", [""])[0]
    return text


def make_handler(gate, laptop_name, log):
    class Handler(BaseHTTPRequestHandler):
        server_version = "Tessera"
        sys_version = ""
        timeout = 10

        def _reply(self, code, text):
            body = text.encode()
            self.send_response(code)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path.split("?")[0] == "/start":
                self._reply(200, gate.start(laptop_name))
            else:
                self._reply(404, "Not found")

        def do_POST(self):
            if self.path.split("?")[0] != "/answer":
                self._reply(404, "Not found")
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = -1
            if not 0 < length <= MAX_BODY:
                self._reply(400, "That answer is too big or empty.")
                return
            answer = read_answer(self.rfile.read(length), self.headers.get("Content-Type"))
            try:
                self._reply(200, gate.answer(answer))
            except Refused as e:
                log(f"refused an answer from {self.client_address[0]}: {e}")
                self._reply(403, "Not accepted. Run the Tessera shortcut again.")

        def log_message(self, fmt, *args):
            log(f"{self.client_address[0]} {fmt % args}")

    return Handler


class DualStackServer(ThreadingHTTPServer):
    """Listens on IPv6 and IPv4 at once: a phone looking up name.local may
    get either address first."""
    address_family = socket.AF_INET6

    def server_bind(self):
        self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        super().server_bind()


class Server:
    def __init__(self, gate, port, laptop_name, log=print):
        try:
            self.httpd = DualStackServer(("::", port), make_handler(gate, laptop_name, log))
        except OSError:
            self.httpd = ThreadingHTTPServer(("", port), make_handler(gate, laptop_name, log))
        self.httpd.daemon_threads = True
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()
