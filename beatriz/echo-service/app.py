import os, socket, time
from http.server import BaseHTTPRequestHandler, HTTPServer

NAME = os.environ.get("SERVICE_NAME", "echo")

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = f"{NAME} on {socket.gethostname()} at {time.time():.3f}\n"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode())

    def log_message(self, *a):
        pass

HTTPServer(("0.0.0.0", 8000), Handler).serve_forever()

