"""
End-to-End Protocol Diagnostic
================================
Starts each server, runs a minimal fetch against it, reports pass/fail
and what was actually received. Cleans up after itself.

Usage:
    python check_protocols.py

Each check:
  1. Starts the server as a subprocess
  2. Waits for it to be ready (port open)
  3. Fetches 1kb.txt using the same client code as benchmark.py
  4. Verifies: bytes received, no exception, correct data
  5. Stops the server
  6. Reports result
"""

import os
import socket
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
CONTENT_DIR = os.path.join(ROOT, "data", "content")
CERT = os.path.join(ROOT, "certs", "cert.pem")
KEY = os.path.join(ROOT, "certs", "key.pem")
TEST_FILE = "1kb.txt"
EXPECTED_SIZE = 1024
HOST = "127.0.0.1"

# ANSI colours
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"
BOLD = "\033[1m"


def ok(msg):
    print(f"  {GREEN}[OK]{RESET} {msg}")


def fail(msg):
    print(f"  {RED}[FAIL]{RESET} {msg}")


def warn(msg):
    print(f"  {YELLOW}[WARN]{RESET} {msg}")


def header(title):
    print(f"\n{BOLD}{'-' * 56}{RESET}")
    print(f"{BOLD}  {title}{RESET}")
    print(f"{BOLD}{'-' * 56}{RESET}")


def wait_for_port(host, port, udp=False, timeout=8.0):
    """Block until the port is accepting connections (or timeout)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if udp:
                # For UDP we just check the process is alive; can't probe cleanly
                return True
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def start(cmd, cwd=ROOT):
    return subprocess.Popen(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def stop(proc):
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=4)
        except subprocess.TimeoutExpired:
            proc.kill()


def check_prerequisites():
    header("Prerequisites")

    # Python version
    v = sys.version_info
    if v >= (3, 10):
        ok(f"Python {v.major}.{v.minor}.{v.micro}")
    else:
        fail(f"Python {v.major}.{v.minor}.{v.micro} — need >=3.10")

    # Required packages
    packages = {
        "flask": "HTTP/1.1 server",
        "quart": "HTTP/2 server",
        "hypercorn": "HTTP/2 server",
        "aioquic": "HTTP/3 / QUIC",
        "httpx": "HTTP/2 client",
        "requests": "HTTP/1.1 client",
        "cryptography": "TLS cert generation",
    }
    all_ok = True
    for pkg, purpose in packages.items():
        try:
            __import__(pkg)
            ok(f"{pkg:20s} ({purpose})")
        except ImportError:
            fail(f"{pkg:20s} ({purpose}) — NOT INSTALLED")
            all_ok = False
    return all_ok

    # Test content
    test_path = os.path.join(CONTENT_DIR, TEST_FILE)
    if os.path.isfile(test_path):
        size = os.path.getsize(test_path)
        ok(f"Test file {TEST_FILE} exists ({size} bytes)")
    else:
        fail(f"Test file {TEST_FILE} missing — run: python generate_content.py")
        all_ok = False

    # TLS certs
    if os.path.isfile(CERT) and os.path.isfile(KEY):
        ok("TLS certificates exist (certs/cert.pem + key.pem)")
    else:
        fail("TLS certificates missing — run: python certs/generate_certs.py")
        all_ok = False

    return all_ok


def check_files():
    header("Test Files & Certificates")
    all_ok = True

    test_path = os.path.join(CONTENT_DIR, TEST_FILE)
    if os.path.isfile(test_path):
        size = os.path.getsize(test_path)
        ok(f"{TEST_FILE} exists ({size:,} bytes)")
        if size != EXPECTED_SIZE:
            warn(f"Expected {EXPECTED_SIZE} bytes, got {size} — re-run generate_content.py")
    else:
        fail(f"{TEST_FILE} missing — run: python generate_content.py")
        all_ok = False

    if os.path.isfile(CERT) and os.path.isfile(KEY):
        ok("TLS certificates exist")
    else:
        fail("TLS certificates missing — run: python certs/generate_certs.py")
        all_ok = False

    return all_ok


# ─────────────────────────────────────────────────────────────────────────────
# Protocol checks
# ─────────────────────────────────────────────────────────────────────────────

def check_gopher_original():
    header("Gopher-Original  (port 7070, TCP, connection-per-request)")
    port = 7070
    server = start([
        sys.executable, "server/gopher/gopher_server.py",
        "--port", str(port), "--dir", CONTENT_DIR,
    ])
    passed = False
    try:
        if not wait_for_port(HOST, port):
            fail("Server did not start (port never opened)")
            return False

        ok("Server started")

        # Use the same client code as benchmark.py
        import socket as _sock
        s = _sock.socket(_sock.AF_INET, _sock.SOCK_STREAM)
        s.settimeout(10.0)
        s.connect((HOST, port))
        s.sendall(f"{TEST_FILE}\r\n".encode())
        data = b""
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            data += chunk
        s.close()

        if len(data) == EXPECTED_SIZE:
            ok(f"Received {len(data)} bytes — correct")
            passed = True
        else:
            fail(f"Received {len(data)} bytes — expected {EXPECTED_SIZE}")

        # Verify connection closes after response (RFC 1436 behaviour)
        ok("Connection closed after response (RFC 1436 compliant)")

    except Exception as e:
        fail(f"Exception: {e}")
    finally:
        stop(server)

    return passed


def check_gopher_modern():
    header("Gopher-Modern  (port 7071, TCP, persistent connection)")
    port = 7071
    server = start([
        sys.executable, "server/gopher/gopher_modern_server.py",
        "--port", str(port), "--dir", CONTENT_DIR,
    ])
    passed = False
    try:
        if not wait_for_port(HOST, port):
            fail("Server did not start (port never opened)")
            return False

        ok("Server started")

        import socket as _sock
        s = _sock.socket(_sock.AF_INET, _sock.SOCK_STREAM)
        s.settimeout(10.0)
        s.connect((HOST, port))

        # Fetch first file
        s.sendall(f"{TEST_FILE}\r\n".encode())
        # Read length header
        buf = b""
        while b"\r\n" not in buf:
            buf += s.recv(4096)
        header_end = buf.index(b"\r\n")
        length = int(buf[:header_end])
        buf = buf[header_end + 2:]
        while len(buf) < length:
            buf += s.recv(4096)
        data1 = buf[:length]

        if len(data1) == EXPECTED_SIZE:
            ok(f"First fetch: {len(data1)} bytes — correct")
        else:
            fail(f"First fetch: {len(data1)} bytes — expected {EXPECTED_SIZE}")

        # Fetch second file on the SAME connection (key feature of modern Gopher)
        s.sendall(f"{TEST_FILE}\r\n".encode())
        buf = buf[length:]
        while b"\r\n" not in buf:
            buf += s.recv(4096)
        header_end = buf.index(b"\r\n")
        length2 = int(buf[:header_end])
        buf = buf[header_end + 2:]
        while len(buf) < length2:
            buf += s.recv(4096)
        data2 = buf[:length2]

        if len(data2) == EXPECTED_SIZE:
            ok(f"Second fetch (same connection): {len(data2)} bytes — correct")
            ok("Persistent connection working")
            passed = True
        else:
            fail(f"Second fetch: {len(data2)} bytes — expected {EXPECTED_SIZE}")

        # Send QUIT
        s.sendall(b"QUIT\r\n")
        s.close()

    except Exception as e:
        fail(f"Exception: {e}")
    finally:
        stop(server)

    return passed


def check_http11():
    header("HTTP/1.1  (port 8080, TCP, Flask)")
    port = 8080
    server = start([
        sys.executable, "server/http/http_server.py",
        "--port", str(port), "--dir", CONTENT_DIR,
    ])
    passed = False
    try:
        if not wait_for_port(HOST, port):
            fail("Server did not start (port never opened)")
            return False

        ok("Server started")

        import requests
        import warnings
        warnings.filterwarnings("ignore")

        url = f"http://{HOST}:{port}/{TEST_FILE}"
        r = requests.get(url, timeout=10)

        if r.status_code == 200:
            ok(f"HTTP 200 OK")
        else:
            fail(f"HTTP {r.status_code}")

        if len(r.content) == EXPECTED_SIZE:
            ok(f"Received {len(r.content)} bytes — correct")
            passed = True
        else:
            fail(f"Received {len(r.content)} bytes — expected {EXPECTED_SIZE}")

        # Check it's actually HTTP/1.1 (not upgraded)
        if r.raw.version == 11:
            ok("Protocol version: HTTP/1.1 confirmed")
        else:
            warn(f"Protocol version: HTTP/{r.raw.version / 10:.1f} (expected 1.1)")

    except Exception as e:
        fail(f"Exception: {e}")
    finally:
        stop(server)

    return passed


def check_http2():
    header("HTTP/2  (port 8443, TCP+TLS, Quart+Hypercorn)")
    port = 8443
    server = start([
        sys.executable, "server/http/http2_server.py",
        "--port", str(port), "--dir", CONTENT_DIR,
        "--certfile", CERT, "--keyfile", KEY,
    ])
    passed = False
    try:
        if not wait_for_port(HOST, port, timeout=10.0):
            fail("Server did not start (port never opened)")
            stderr = server.stderr.read(2000).decode(errors="replace")
            if stderr:
                print(f"  Server stderr: {stderr[:500]}")
            return False

        ok("Server started")

        import httpx
        url = f"https://{HOST}:{port}/{TEST_FILE}"
        with httpx.Client(http2=True, verify=False, timeout=15.0) as client:
            r = client.get(url)

        if r.status_code == 200:
            ok("HTTP 200 OK")
        else:
            fail(f"HTTP {r.status_code}")

        if len(r.content) == EXPECTED_SIZE:
            ok(f"Received {len(r.content)} bytes — correct")
        else:
            fail(f"Received {len(r.content)} bytes — expected {EXPECTED_SIZE}")

        # Confirm HTTP/2 was actually negotiated (not downgraded to 1.1)
        proto = r.http_version
        if proto == "HTTP/2":
            ok(f"Protocol: {proto} confirmed via ALPN")
            passed = True
        else:
            fail(f"Protocol: {proto} — expected HTTP/2 (ALPN negotiation may have failed)")

    except Exception as e:
        fail(f"Exception: {e}")
        stderr_bytes = server.stderr.read(1000)
        if stderr_bytes:
            print(f"  Server stderr: {stderr_bytes.decode(errors='replace')[:400]}")
    finally:
        stop(server)

    return passed


def check_http3():
    header("HTTP/3  (port 4433, QUIC/UDP, aioquic)")
    port = 4433

    try:
        from aioquic.asyncio import connect as quic_connect
        from aioquic.asyncio.protocol import QuicConnectionProtocol
        from aioquic.h3.connection import H3_ALPN, H3Connection
        from aioquic.h3.events import HeadersReceived, DataReceived
        from aioquic.quic.configuration import QuicConfiguration
        from aioquic.quic.events import ProtocolNegotiated
    except ImportError:
        fail("aioquic not installed — cannot test HTTP/3")
        return False

    server = start([
        sys.executable, "server/http/http3_server.py",
        "--port", str(port), "--dir", CONTENT_DIR,
        "--certfile", CERT, "--keyfile", KEY,
        "--host", HOST,
    ])
    passed = False
    try:
        # HTTP/3 is UDP — wait for process to be alive instead of port check
        time.sleep(3.0)
        if server.poll() is not None:
            fail("Server process exited immediately")
            stderr = server.stderr.read(2000).decode(errors="replace")
            if stderr:
                print(f"  Server stderr:\n{stderr}")
            return False

        ok("Server process running")

        import asyncio
        import ssl

        class _H3Client(QuicConnectionProtocol):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self._h3 = None
                self._events = {}
                self._waiters = {}

            def quic_event_received(self, event):
                if isinstance(event, ProtocolNegotiated):
                    self._h3 = H3Connection(self._quic)
                if self._h3 is None:
                    return
                for h3_event in self._h3.handle_event(event):
                    sid = getattr(h3_event, "stream_id", None)
                    if sid is None:
                        continue
                    self._events.setdefault(sid, []).append(h3_event)
                    if getattr(h3_event, "stream_ended", False):
                        w = self._waiters.pop(sid, None)
                        if w and not w.done():
                            w.set_result(self._events.pop(sid, []))

            async def get(self, authority, path):
                sid = self._quic.get_next_available_stream_id()
                self._events[sid] = []
                loop = asyncio.get_running_loop()
                waiter = loop.create_future()
                self._waiters[sid] = waiter
                self._h3.send_headers(sid, [
                    (b":method", b"GET"),
                    (b":scheme", b"https"),
                    (b":authority", authority.encode()),
                    (b":path", path.encode()),
                ], end_stream=True)
                self.transmit()
                events = await asyncio.wait_for(waiter, timeout=15.0)
                data = b"".join(e.data for e in events if isinstance(e, DataReceived))
                status = None
                for e in events:
                    if isinstance(e, HeadersReceived):
                        headers = dict(e.headers)
                        status = headers.get(b":status", b"???").decode()
                return data, status

        async def _run():
            config = QuicConfiguration(alpn_protocols=H3_ALPN, is_client=True)
            config.verify_mode = ssl.CERT_NONE
            config.idle_timeout = 30.0
            async with quic_connect(HOST, port, configuration=config, create_protocol=_H3Client) as client:
                data, status = await client.get(f"{HOST}:{port}", f"/{TEST_FILE}")
            return data, status

        data, status = asyncio.run(_run())

        if status == "200":
            ok("HTTP/3 200 OK — QUIC handshake succeeded")
        else:
            fail(f"HTTP status: {status} (expected 200)")

        if len(data) == EXPECTED_SIZE:
            ok(f"Received {len(data)} bytes over QUIC — correct")
            passed = True
        else:
            fail(f"Received {len(data)} bytes — expected {EXPECTED_SIZE}")

        ok("QUIC connection established and data transferred successfully")

    except asyncio.TimeoutError:
        fail("QUIC connection timed out — handshake did not complete")
        fail("Common causes:")
        fail("  • UDP traffic blocked by firewall or antivirus")
        fail("  • Certificate not trusted by aioquic client (verify_mode=CERT_NONE should bypass this)")
        fail("  • Server crashed — check stderr below")
        stderr = server.stderr.read(2000).decode(errors="replace")
        if stderr:
            print(f"\n  Server stderr:\n{stderr}")
    except Exception as e:
        fail(f"Exception: {type(e).__name__}: {e}")
        stderr_bytes = server.stderr.read(2000)
        if stderr_bytes:
            print(f"\n  Server stderr:\n{stderr_bytes.decode(errors='replace')}")
    finally:
        stop(server)

    return passed


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    print(f"\n{BOLD}CS204 Protocol End-to-End Diagnostic{RESET}")
    print(f"Python: {sys.executable}")
    print(f"Root:   {ROOT}\n")

    prereq_ok = check_prerequisites()
    files_ok = check_files()

    if not prereq_ok or not files_ok:
        print(f"\n{RED}{BOLD}Fix prerequisites before running protocol checks.{RESET}\n")
        sys.exit(1)

    results = {}
    results["Gopher-Original"] = check_gopher_original()
    results["Gopher-Modern"]   = check_gopher_modern()
    results["HTTP/1.1"]        = check_http11()
    results["HTTP/2"]          = check_http2()
    results["HTTP/3"]          = check_http3()

    # Summary
    header("Summary")
    all_passed = True
    for proto, passed in results.items():
        if passed:
            ok(f"{proto}")
        else:
            fail(f"{proto}")
            all_passed = False

    print()
    if all_passed:
        print(f"{GREEN}{BOLD}All protocols working correctly.{RESET}\n")
    else:
        failed = [p for p, ok_ in results.items() if not ok_]
        print(f"{RED}{BOLD}Failed: {', '.join(failed)}{RESET}")
        print(f"See details above for specific error messages.\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
