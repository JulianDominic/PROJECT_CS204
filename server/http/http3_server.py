"""
HTTP/3 File Server - aioquic.

Uses aioquic directly for the benchmark path. This avoids the Hypercorn QUIC
server instability that showed up under delayed proxy traffic.
"""

import argparse
import asyncio
import os

from aioquic.asyncio import serve
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.h3.connection import H3_ALPN, H3Connection
from aioquic.h3.events import HeadersReceived
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import ProtocolNegotiated, QuicEvent

CONTENT_DIR = "../../data/content"


class Http3Server(QuicConnectionProtocol):
    """QUIC connection handler that speaks HTTP/3."""

    ROOT_DIR = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._h3 = None

    def quic_event_received(self, event: QuicEvent):
        if isinstance(event, ProtocolNegotiated):
            self._h3 = H3Connection(self._quic)

        if self._h3 is None:
            return

        for h3_event in self._h3.handle_event(event):
            if isinstance(h3_event, HeadersReceived):
                self._handle_request(h3_event)

    def _handle_request(self, event: HeadersReceived):
        headers = dict(event.headers)
        path = headers.get(b":path", b"/").decode()
        stream_id = event.stream_id
        root = self.__class__.ROOT_DIR

        if path == "/" or not path:
            self._send_index(stream_id, root)
        else:
            filename = path.lstrip("/")
            filepath = os.path.normpath(os.path.join(root, filename))
            if not filepath.startswith(root):
                self._send_error(stream_id, 403, "Forbidden")
            elif os.path.isfile(filepath):
                self._send_file(stream_id, filepath)
            else:
                self._send_error(stream_id, 404, "Not Found")

        self.transmit()

    def _send_headers(self, stream_id, status, content_type, content_length):
        self._h3.send_headers(
            stream_id=stream_id,
            headers=[
                (b":status", str(status).encode()),
                (b"content-type", content_type.encode()),
                (b"content-length", str(content_length).encode()),
            ],
        )

    def _send_file(self, stream_id, filepath):
        with open(filepath, "rb") as handle:
            data = handle.read()
        self._send_headers(stream_id, 200, "application/octet-stream", len(data))
        self._h3.send_data(stream_id=stream_id, data=data, end_stream=True)

    def _send_index(self, stream_id, root):
        files = sorted(os.listdir(root))
        html = "<html><body><h1>Files (HTTP/3)</h1><ul>"
        for name in files:
            html += f'<li><a href="/{name}">{name}</a></li>'
        html += "</ul></body></html>"
        data = html.encode()
        self._send_headers(stream_id, 200, "text/html", len(data))
        self._h3.send_data(stream_id=stream_id, data=data, end_stream=True)

    def _send_error(self, stream_id, status, message):
        data = message.encode()
        self._send_headers(stream_id, status, "text/plain", len(data))
        self._h3.send_data(stream_id=stream_id, data=data, end_stream=True)


async def main(host, port, certfile, keyfile, content_dir):
    configuration = QuicConfiguration(
        alpn_protocols=H3_ALPN,
        is_client=False,
        max_datagram_frame_size=65536,
    )
    configuration.load_cert_chain(certfile, keyfile)

    Http3Server.ROOT_DIR = os.path.abspath(content_dir)

    print(f"HTTP/3 server on {host}:{port} (QUIC / TLS 1.3)")
    print(f"Serving: {Http3Server.ROOT_DIR}")

    await serve(
        host,
        port,
        configuration=configuration,
        create_protocol=Http3Server,
    )
    await asyncio.Future()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HTTP/3 Server (Hypercorn + Quart + QUIC)")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=4433)
    parser.add_argument("--dir", default=CONTENT_DIR)
    parser.add_argument("--certfile", default="../../certs/cert.pem")
    parser.add_argument("--keyfile", default="../../certs/key.pem")
    args = parser.parse_args()

    asyncio.run(main(args.host, args.port, args.certfile, args.keyfile, args.dir))
