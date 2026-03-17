"""
HTTP/3 File Server - Hypercorn + Quart over QUIC.

Uses Hypercorn's QUIC support instead of a hand-rolled aioquic server so the
HTTP/3 benchmark path behaves consistently across machines.
"""

import argparse
import asyncio
import os

from hypercorn.asyncio import serve
from hypercorn.config import Config
from quart import Quart, send_from_directory

app = Quart(__name__)
CONTENT_DIR = "../../data/content"


@app.route("/")
async def index():
    try:
        content_dir = app.config["CONTENT_DIR"]
        files = sorted(os.listdir(content_dir))
        html = "<html><body><h1>Files (HTTP/3)</h1><ul>"
        for name in files:
            html += f'<li><a href="/{name}">{name}</a></li>'
        html += "</ul></body></html>"
        return html
    except Exception as exc:
        return f"Error: {exc}", 500


@app.route("/<path:filename>")
async def serve_file(filename):
    return await send_from_directory(app.config["CONTENT_DIR"], filename)


async def main(host, port, certfile, keyfile, content_dir):
    app.config["CONTENT_DIR"] = os.path.abspath(content_dir)

    config = Config()
    config.bind = []
    config.quic_bind = [f"{host}:{port}"]
    config.certfile = os.path.abspath(certfile)
    config.keyfile = os.path.abspath(keyfile)
    config.accesslog = None
    config.errorlog = "-"

    print(f"HTTP/3 server on {host}:{port} (QUIC / TLS 1.3)")
    print(f"Serving: {app.config['CONTENT_DIR']}")

    await serve(app, config)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HTTP/3 Server (Hypercorn + Quart + QUIC)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4433)
    parser.add_argument("--dir", default=CONTENT_DIR)
    parser.add_argument("--certfile", default="../../certs/cert.pem")
    parser.add_argument("--keyfile", default="../../certs/key.pem")
    args = parser.parse_args()

    asyncio.run(main(args.host, args.port, args.certfile, args.keyfile, args.dir))
