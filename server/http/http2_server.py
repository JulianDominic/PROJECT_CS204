"""
HTTP/2 File Server — Hypercorn + Quart

HTTP/2 key improvements over HTTP/1.1 (CS204 concepts):
  ┌─────────────────────────────────────────────────────────────────┐
  │  HTTP/1.1                          HTTP/2                       │
  │  ─────────                         ──────                       │
  │  Text-based protocol               Binary framing layer         │
  │  One request at a time per conn    Multiplexing (many streams)  │
  │  No header compression             HPACK header compression     │
  │  6 parallel TCP connections         Single TCP connection        │
  │  Head-of-line blocking             Stream-level prioritisation  │
  └─────────────────────────────────────────────────────────────────┘

  Multiplexing is the killer feature: 20 requests can fly over ONE
  TCP connection simultaneously, unlike HTTP/1.1 which needs separate
  connections or pipelining (which nobody implements properly).

  Requires TLS in practice (browsers enforce it via ALPN negotiation).

Dependencies: quart, hypercorn
"""

from quart import Quart, send_from_directory
import os
import argparse
import asyncio
from hypercorn.config import Config
from hypercorn.asyncio import serve

app = Quart(__name__)
CONTENT_DIR = "../../data/content"


@app.route("/")
async def index():
    try:
        content_dir = app.config["CONTENT_DIR"]
        files = sorted(os.listdir(content_dir))
        html = "<html><body><h1>Files (HTTP/2)</h1><ul>"
        for f in files:
            html += f'<li><a href="/{f}">{f}</a></li>'
        html += "</ul></body></html>"
        return html
    except Exception as e:
        return f"Error: {e}", 500


@app.route("/<path:filename>")
async def serve_file(filename):
    return await send_from_directory(app.config["CONTENT_DIR"], filename)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HTTP/2 Server (Hypercorn + Quart)")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8443)
    parser.add_argument("--dir", default=CONTENT_DIR)
    parser.add_argument("--certfile", default="../../certs/cert.pem")
    parser.add_argument("--keyfile", default="../../certs/key.pem")
    args = parser.parse_args()

    app.config["CONTENT_DIR"] = os.path.abspath(args.dir)

    config = Config()
    config.bind = [f"{args.host}:{args.port}"]
    config.certfile = os.path.abspath(args.certfile)
    config.keyfile = os.path.abspath(args.keyfile)
    config.accesslog = None  # Suppress access logs during benchmarks
    config.errorlog = "-"

    print(f"HTTP/2 server on {args.host}:{args.port} (TLS)")
    print(f"Serving: {app.config['CONTENT_DIR']}")

    asyncio.run(serve(app, config))
