"""
HTTP/3 File Server — aioquic (QUIC + HTTP/3)

HTTP/3 key advantages (CS204 concepts):
  ┌─────────────────────────────────────────────────────────────────┐
  │  HTTP/2 (TCP)                      HTTP/3 (QUIC / UDP)         │
  │  ──────────────                    ─────────────────────        │
  │  TCP + TLS = 2-3 RTT handshake     QUIC = 1 RTT (0-RTT recon) │
  │  TCP head-of-line blocking         No HOL blocking (streams    │
  │  (lost packet stalls ALL streams)  are independent in QUIC)    │
  │  OS-level TCP stack                Userspace protocol (QUIC)   │
  │  Connection tied to IP             Connection migration         │
  └─────────────────────────────────────────────────────────────────┘

  The "Dirty Network" test is where HTTP/3 shines: when a packet is
  lost, only the specific QUIC stream (e.g., one image) is delayed.
  All other streams keep flowing. With TCP (HTTP/1.1 & HTTP/2), a
  single lost packet stalls ALL data until it's retransmitted.

Dependencies: aioquic
"""

import asyncio
import os
import argparse

from aioquic.asyncio import serve
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.h3.connection import H3_ALPN, H3Connection
from aioquic.h3.events import HeadersReceived, DataReceived
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import ProtocolNegotiated, QuicEvent

CONTENT_DIR = "../../data/content"


class Http3Server(QuicConnectionProtocol):
    """QUIC connection handler that speaks HTTP/3."""

    # Set at module level before starting the server
    ROOT_DIR = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._h3 = None

    def quic_event_received(self, event: QuicEvent):
        # Create H3 connection once ALPN negotiation completes
        if isinstance(event, ProtocolNegotiated):
            self._h3 = H3Connection(self._quic)

        if self._h3 is None:
            return

        # Process HTTP/3 events
        for h3_event in self._h3.handle_event(event):
            if isinstance(h3_event, HeadersReceived):
                self._handle_request(h3_event)

    def _handle_request(self, event: HeadersReceived):
        """Handle an incoming HTTP/3 GET request."""
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

        # Flush all pending data
        self.transmit()

    def _send_file(self, stream_id, filepath):
        with open(filepath, "rb") as f:
            data = f.read()
        self._h3.send_headers(
            stream_id=stream_id,
            headers=[
                (b":status", b"200"),
                (b"content-type", b"application/octet-stream"),
                (b"content-length", str(len(data)).encode()),
            ],
        )
        self._h3.send_data(stream_id=stream_id, data=data, end_stream=True)

    def _send_index(self, stream_id, root):
        files = sorted(os.listdir(root))
        html = "<html><body><h1>Files (HTTP/3)</h1><ul>"
        for f in files:
            html += f'<li><a href="/{f}">{f}</a></li>'
        html += "</ul></body></html>"
        data = html.encode()
        self._h3.send_headers(
            stream_id=stream_id,
            headers=[
                (b":status", b"200"),
                (b"content-type", b"text/html"),
                (b"content-length", str(len(data)).encode()),
            ],
        )
        self._h3.send_data(stream_id=stream_id, data=data, end_stream=True)

    def _send_error(self, stream_id, status, message):
        data = message.encode()
        self._h3.send_headers(
            stream_id=stream_id,
            headers=[
                (b":status", str(status).encode()),
                (b"content-length", str(len(data)).encode()),
            ],
        )
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

    # Keep running forever
    await asyncio.Future()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HTTP/3 Server (QUIC + aioquic)")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=4433)
    parser.add_argument("--dir", default=CONTENT_DIR)
    parser.add_argument("--certfile", default="../../certs/cert.pem")
    parser.add_argument("--keyfile", default="../../certs/key.pem")
    args = parser.parse_args()

    asyncio.run(main(args.host, args.port, args.certfile, args.keyfile, args.dir))
