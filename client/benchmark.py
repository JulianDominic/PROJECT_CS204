"""
Unified Protocol Benchmark Client

Measures performance across five protocol implementations:

  ┌────────────────────┬───────────────┬─────────────────────────────────┐
  │ Protocol           │ Transport     │ Connection Model                │
  ├────────────────────┼───────────────┼─────────────────────────────────┤
  │ gopher-original    │ TCP           │ 1 connection per request        │
  │ gopher-modern      │ TCP           │ Persistent (keep-alive)         │
  │ http/1.1           │ TCP           │ Persistent (keep-alive)         │
  │ http/2             │ TCP + TLS     │ Multiplexed streams             │
  │ http/3             │ QUIC (UDP)    │ Multiplexed streams, no HOL     │
  └────────────────────┴───────────────┴─────────────────────────────────┘

Test types:
  single — Fetch one file    (measures handshake + TTFB + transfer)
  multi  — Fetch N files     (measures connection reuse / multiplexing)

Metrics collected:
  TTFB           Time to first byte (includes connection setup)
  total_time     Total transfer time
  bytes          Total bytes received
  throughput     Effective throughput (kbps)
"""

import socket
import time
import os
import csv
import ssl
import asyncio
import argparse
import warnings
from datetime import datetime

import requests
import urllib3
import httpx

# Suppress self-signed cert warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
warnings.filterwarnings("ignore", message="Unverified HTTPS request")

# Optional: HTTP/3 support (requires aioquic)
try:
    from aioquic.asyncio import connect as quic_connect
    from aioquic.asyncio.protocol import QuicConnectionProtocol
    from aioquic.h3.connection import H3_ALPN, H3Connection
    from aioquic.h3.events import HeadersReceived, DataReceived
    from aioquic.quic.configuration import QuicConfiguration
    from aioquic.quic.events import ProtocolNegotiated

    HAS_HTTP3 = True
except ImportError:
    HAS_HTTP3 = False
    print("Warning: aioquic not installed — HTTP/3 benchmarks will be skipped")


# ═══════════════════════════════════════════════════════════════════════
#  GOPHER — ORIGINAL (RFC 1436)
#  New TCP connection for every single request.
#  TCP always starts in Slow Start → bad for large / many files.
# ═══════════════════════════════════════════════════════════════════════


def measure_gopher_original(host, port, filename):
    """Original Gopher: connect → send selector → read all → close."""
    start = time.time()

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(30.0)
    s.connect((host, port))
    s.sendall(f"{filename}\r\n".encode("utf-8"))

    chunks = []
    ttfb = None
    while True:
        chunk = s.recv(4096)
        if not chunk:
            break
        if ttfb is None:
            ttfb = (time.time() - start) * 1000
        chunks.append(chunk)

    total_time = (time.time() - start) * 1000
    s.close()

    data = b"".join(chunks)
    return {"ttfb": ttfb or 0, "total_time": total_time, "bytes": len(data)}


def measure_gopher_original_multi(host, port, filenames):
    """Original Gopher waterfall: one NEW TCP connection per file."""
    start = time.time()
    total_bytes = 0
    first_ttfb = None

    for f in filenames:
        r = measure_gopher_original(host, port, f)
        total_bytes += r["bytes"]
        if first_ttfb is None:
            first_ttfb = r["ttfb"]

    total_time = (time.time() - start) * 1000
    return {
        "ttfb": first_ttfb or 0,
        "total_time": total_time,
        "bytes": total_bytes,
        "num_files": len(filenames),
    }


# ═══════════════════════════════════════════════════════════════════════
#  GOPHER — MODERN (Persistent TCP)
#  One connection serves many requests. TCP congestion window grows
#  over time → exits Slow Start → faster for subsequent requests.
# ═══════════════════════════════════════════════════════════════════════


class _GopherModernConn:
    """Helper: persistent Gopher connection with length-prefixed framing."""

    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.sock = None
        self.buffer = b""

    def connect(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(30.0)
        self.sock.connect((self.host, self.port))
        self.buffer = b""

    def fetch(self, selector):
        """Send selector, read length-prefixed response, return raw bytes."""
        self.sock.sendall(f"{selector}\r\n".encode("utf-8"))

        # Read length header: "<digits>\r\n"
        while b"\r\n" not in self.buffer:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("Server closed connection")
            self.buffer += chunk

        header_end = self.buffer.index(b"\r\n")
        length = int(self.buffer[:header_end])
        self.buffer = self.buffer[header_end + 2 :]

        # Read exactly `length` bytes of body
        while len(self.buffer) < length:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("Server closed connection")
            self.buffer += chunk

        data = self.buffer[:length]
        self.buffer = self.buffer[length:]
        return data

    def close(self):
        try:
            self.sock.sendall(b"QUIT\r\n")
        except Exception:
            pass
        self.sock.close()


def measure_gopher_modern(host, port, filename):
    """Modern Gopher: one persistent connection, single file."""
    start = time.time()

    conn = _GopherModernConn(host, port)
    conn.connect()
    data = conn.fetch(filename)

    ttfb = (time.time() - start) * 1000  # Includes connect + first response
    total_time = ttfb  # Single fetch — TTFB ≈ total time
    conn.close()

    return {"ttfb": ttfb, "total_time": total_time, "bytes": len(data)}


def measure_gopher_modern_multi(host, port, filenames):
    """Modern Gopher waterfall: ONE persistent connection for ALL files."""
    start = time.time()
    total_bytes = 0
    first_ttfb = None

    conn = _GopherModernConn(host, port)
    conn.connect()

    for f in filenames:
        req_start = time.time()
        data = conn.fetch(f)
        if first_ttfb is None:
            first_ttfb = (time.time() - req_start) * 1000
        total_bytes += len(data)

    total_time = (time.time() - start) * 1000
    conn.close()

    return {
        "ttfb": first_ttfb or 0,
        "total_time": total_time,
        "bytes": total_bytes,
        "num_files": len(filenames),
    }


# ═══════════════════════════════════════════════════════════════════════
#  HTTP/1.1 (via requests library)
#  Uses Session for keep-alive (persistent TCP connection).
#  Still limited to sequential request-response on each connection.
# ═══════════════════════════════════════════════════════════════════════


def measure_http11(host, port, filename, session=None):
    """HTTP/1.1 single file request."""
    url = f"http://{host}:{port}/{filename}"
    own_session = session is None
    if own_session:
        session = requests.Session()

    start = time.time()
    with session.get(url, stream=True, timeout=30.0) as r:
        ttfb = (time.time() - start) * 1000  # Headers received
        chunks = []
        for chunk in r.iter_content(chunk_size=4096):
            chunks.append(chunk)
    total_time = (time.time() - start) * 1000

    if own_session:
        session.close()

    data = b"".join(chunks)
    return {"ttfb": ttfb, "total_time": total_time, "bytes": len(data)}


def measure_http11_multi(host, port, filenames):
    """HTTP/1.1 waterfall: Session keep-alive reuses TCP connection."""
    start = time.time()
    total_bytes = 0
    first_ttfb = None

    with requests.Session() as session:
        for f in filenames:
            r = measure_http11(host, port, f, session=session)
            total_bytes += r["bytes"]
            if first_ttfb is None:
                first_ttfb = r["ttfb"]

    total_time = (time.time() - start) * 1000
    return {
        "ttfb": first_ttfb or 0,
        "total_time": total_time,
        "bytes": total_bytes,
        "num_files": len(filenames),
    }


# ═══════════════════════════════════════════════════════════════════════
#  HTTP/2 (via httpx with h2)
#  Single TCP + TLS connection. Multiplexing allows concurrent streams.
#  Still subject to TCP-level head-of-line blocking on packet loss.
# ═══════════════════════════════════════════════════════════════════════


def measure_http2(host, port, filename):
    """HTTP/2 single file over TLS."""
    url = f"https://{host}:{port}/{filename}"
    start = time.time()

    with httpx.Client(http2=True, verify=False, timeout=30.0) as client:
        with client.stream("GET", url) as response:
            ttfb = (time.time() - start) * 1000
            data = response.read()

    total_time = (time.time() - start) * 1000
    return {"ttfb": ttfb, "total_time": total_time, "bytes": len(data)}


def measure_http2_multi(host, port, filenames):
    """HTTP/2 waterfall: sequential requests over one multiplexed connection."""
    start = time.time()
    total_bytes = 0
    first_ttfb = None

    with httpx.Client(http2=True, verify=False, timeout=30.0) as client:
        for f in filenames:
            req_start = time.time()
            url = f"https://{host}:{port}/{f}"
            r = client.get(url)
            if first_ttfb is None:
                first_ttfb = (time.time() - req_start) * 1000
            total_bytes += len(r.content)

    total_time = (time.time() - start) * 1000
    return {
        "ttfb": first_ttfb or 0,
        "total_time": total_time,
        "bytes": total_bytes,
        "num_files": len(filenames),
    }


async def _measure_http2_multi_mux(host, port, filenames):
    """HTTP/2 TRUE multiplexing: fire all requests concurrently."""
    start = time.time()

    async with httpx.AsyncClient(http2=True, verify=False, timeout=30.0) as client:
        tasks = [client.get(f"https://{host}:{port}/{f}") for f in filenames]
        responses = await asyncio.gather(*tasks)

    total_bytes = sum(len(r.content) for r in responses)
    total_time = (time.time() - start) * 1000

    return {
        "ttfb": 0,  # Not meaningful for truly concurrent requests
        "total_time": total_time,
        "bytes": total_bytes,
        "num_files": len(filenames),
    }


def measure_http2_multi_multiplexed(host, port, filenames):
    """Wrapper: run async HTTP/2 multiplexed benchmark."""
    return asyncio.run(_measure_http2_multi_mux(host, port, filenames))


# ═══════════════════════════════════════════════════════════════════════
#  HTTP/3 (via aioquic — QUIC + UDP)
#  1-RTT handshake, no HOL blocking, connection migration.
#  The "Dirty Network" champion.
# ═══════════════════════════════════════════════════════════════════════

if HAS_HTTP3:

    class _H3Client(QuicConnectionProtocol):
        """HTTP/3 client protocol for benchmarking."""

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._h3 = None
            self._request_events = {}
            self._request_waiters = {}
            self._first_byte_times = {}
            self._request_start_times = {}

        def quic_event_received(self, event):
            if isinstance(event, ProtocolNegotiated):
                self._h3 = H3Connection(self._quic)

            if self._h3 is None:
                return

            for h3_event in self._h3.handle_event(event):
                if isinstance(h3_event, (HeadersReceived, DataReceived)):
                    sid = h3_event.stream_id
                    if sid not in self._request_events:
                        self._request_events[sid] = []
                    self._request_events[sid].append(h3_event)

                    # Record TTFB on first event for this stream
                    if (
                        sid not in self._first_byte_times
                        and sid in self._request_start_times
                    ):
                        self._first_byte_times[sid] = (
                            time.time() - self._request_start_times[sid]
                        ) * 1000

                    if h3_event.stream_ended:
                        waiter = self._request_waiters.pop(sid, None)
                        if waiter and not waiter.done():
                            waiter.set_result(
                                self._request_events.pop(sid, [])
                            )

        async def get(self, authority, path):
            """Send HTTP/3 GET request, return (data_bytes, ttfb_ms)."""
            stream_id = self._quic.get_next_available_stream_id()
            self._request_events[stream_id] = []

            loop = asyncio.get_running_loop()
            waiter = loop.create_future()
            self._request_waiters[stream_id] = waiter
            self._request_start_times[stream_id] = time.time()

            self._h3.send_headers(
                stream_id=stream_id,
                headers=[
                    (b":method", b"GET"),
                    (b":scheme", b"https"),
                    (b":authority", authority.encode()),
                    (b":path", path.encode()),
                ],
                end_stream=True,
            )
            self.transmit()

            events = await asyncio.wait_for(waiter, timeout=30.0)

            data = b"".join(
                ev.data for ev in events if isinstance(ev, DataReceived)
            )
            ttfb = self._first_byte_times.get(stream_id, 0)
            return data, ttfb

    async def _measure_http3_single(host, port, filename):
        """HTTP/3 single file over QUIC."""
        config = QuicConfiguration(alpn_protocols=H3_ALPN, is_client=True)
        config.verify_mode = ssl.CERT_NONE

        start = time.time()
        async with quic_connect(
            host, port, configuration=config, create_protocol=_H3Client
        ) as client:
            data, ttfb = await client.get(f"{host}:{port}", f"/{filename}")

        total_time = (time.time() - start) * 1000
        return {"ttfb": ttfb, "total_time": total_time, "bytes": len(data)}

    async def _measure_http3_multi(host, port, filenames):
        """HTTP/3 multi-file: one QUIC connection, multiplexed streams."""
        config = QuicConfiguration(alpn_protocols=H3_ALPN, is_client=True)
        config.verify_mode = ssl.CERT_NONE

        start = time.time()
        async with quic_connect(
            host, port, configuration=config, create_protocol=_H3Client
        ) as client:
            authority = f"{host}:{port}"
            # Fire all requests concurrently — QUIC multiplexes them
            tasks = [client.get(authority, f"/{f}") for f in filenames]
            results = await asyncio.gather(*tasks)

        total_bytes = sum(len(data) for data, _ in results)
        first_ttfb = results[0][1] if results else 0
        total_time = (time.time() - start) * 1000

        return {
            "ttfb": first_ttfb,
            "total_time": total_time,
            "bytes": total_bytes,
            "num_files": len(filenames),
        }

    def measure_http3(host, port, filename):
        return asyncio.run(_measure_http3_single(host, port, filename))

    def measure_http3_multi(host, port, filenames):
        return asyncio.run(_measure_http3_multi(host, port, filenames))


# ═══════════════════════════════════════════════════════════════════════
#  PROTOCOL REGISTRY
# ═══════════════════════════════════════════════════════════════════════

PROTOCOL_MAP = {
    "gopher-original": {
        "single": measure_gopher_original,
        "multi": measure_gopher_original_multi,
    },
    "gopher-modern": {
        "single": measure_gopher_modern,
        "multi": measure_gopher_modern_multi,
    },
    "http/1.1": {
        "single": measure_http11,
        "multi": measure_http11_multi,
    },
    "http/2": {
        "single": measure_http2,
        "multi": measure_http2_multi,
    },
}

if HAS_HTTP3:
    PROTOCOL_MAP["http/3"] = {
        "single": measure_http3,
        "multi": measure_http3_multi,
    }


# ═══════════════════════════════════════════════════════════════════════
#  BENCHMARK RUNNER
# ═══════════════════════════════════════════════════════════════════════

FIELDNAMES = [
    "timestamp",
    "protocol",
    "test_type",
    "file",
    "scenario",
    "ttfb",
    "total_time",
    "bytes",
    "throughput",
    "num_files",
]


class BenchmarkRunner:
    def __init__(self, output_file="results.csv"):
        self.output_file = output_file
        self.results = []

    def run_single(self, protocol, host, port, filename, runs=10, scenario="Baseline"):
        """Benchmark: fetch a single file `runs` times."""
        funcs = PROTOCOL_MAP.get(protocol)
        if not funcs:
            print(f"  Unknown protocol: {protocol}")
            return

        measure = funcs["single"]
        print(f"  {protocol} | {filename} | single | {runs} runs ", end="", flush=True)

        for i in range(runs):
            try:
                result = measure(host, port, filename)
                result.update(
                    {
                        "timestamp": datetime.now().isoformat(),
                        "protocol": protocol,
                        "test_type": "single",
                        "file": filename,
                        "scenario": scenario,
                        "num_files": 1,
                        "throughput": (
                            (result["bytes"] * 8 / result["total_time"])
                            if result["total_time"] > 0
                            else 0
                        ),
                    }
                )
                self.results.append(result)
                print(".", end="", flush=True)
            except Exception as e:
                print(f"x({e})", end="", flush=True)

        print()  # newline

    def run_multi(self, protocol, host, port, filenames, runs=10, scenario="Baseline"):
        """Benchmark: fetch multiple files `runs` times."""
        funcs = PROTOCOL_MAP.get(protocol)
        if not funcs:
            print(f"  Unknown protocol: {protocol}")
            return

        measure = funcs["multi"]
        print(
            f"  {protocol} | {len(filenames)} files | multi | {runs} runs ",
            end="",
            flush=True,
        )

        for i in range(runs):
            try:
                result = measure(host, port, filenames)
                result.update(
                    {
                        "timestamp": datetime.now().isoformat(),
                        "protocol": protocol,
                        "test_type": "multi",
                        "file": f"{len(filenames)}_files",
                        "scenario": scenario,
                        "throughput": (
                            (result["bytes"] * 8 / result["total_time"])
                            if result["total_time"] > 0
                            else 0
                        ),
                    }
                )
                self.results.append(result)
                print(".", end="", flush=True)
            except Exception as e:
                print(f"x({e})", end="", flush=True)

        print()

    def save(self):
        """Append results to CSV file."""
        if not self.results:
            return

        file_exists = os.path.isfile(self.output_file)
        with open(self.output_file, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
            if not file_exists:
                writer.writeheader()
            writer.writerows(self.results)

        count = len(self.results)
        print(f"  -> Saved {count} results to {self.output_file}")
        self.results = []


# ═══════════════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Protocol Benchmark Client")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument(
        "--protocol",
        required=True,
        choices=list(PROTOCOL_MAP.keys()),
    )
    parser.add_argument(
        "--file",
        required=True,
        help="Filename for single test; comma-separated for multi test",
    )
    parser.add_argument("--test", choices=["single", "multi"], default="single")
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--scenario", default="Baseline")
    parser.add_argument("--output", default="results.csv")
    args = parser.parse_args()

    runner = BenchmarkRunner(args.output)

    if args.test == "single":
        runner.run_single(
            args.protocol, args.host, args.port, args.file, args.runs, args.scenario
        )
    else:
        filenames = [f.strip() for f in args.file.split(",")]
        runner.run_multi(
            args.protocol, args.host, args.port, filenames, args.runs, args.scenario
        )

    runner.save()
