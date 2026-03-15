import subprocess
import time
import os
import sys
import pandas as pd
import matplotlib
matplotlib.use("Agg")  # Non-interactive backend for CI/headless
import matplotlib.pyplot as plt
import seaborn as sns

# ── Import benchmark runner in-process (avoids subprocess overhead) ───
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from client.benchmark import BenchmarkRunner


# ═══════════════════════════════════════════════════════════════════════
#  CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════

# Server → Proxy port mapping
PORTS = {
    "gopher-original": {"server": 7070, "proxy": 9070},
    "gopher-modern":   {"server": 7071, "proxy": 9071},
    "http/1.1":        {"server": 7072, "proxy": 9080},
    "http/2":          {"server": 7073, "proxy": 9443},
    "http/3":          {"server": 7074, "proxy": 9433},
}

ALL_PROTOCOLS = ["gopher-original", "gopher-modern", "http/1.1", "http/2", "http/3"]

SCENARIOS = [
    {"name": "Baseline",     "latency": 0,   "loss": 0},
    {"name": "High_Latency", "latency": 100, "loss": 0},
    {"name": "Packet_Loss",  "latency": 0,   "loss": 5},
    {"name": "Mixed",        "latency": 50,  "loss": 2},
]

# 10 small files for the multi-object (waterfall) test
MULTI_FILES = [f"small_{i:02d}.txt" for i in range(10)]

RUNS_PER_TEST = 3
RESULTS_DIR = "results"
CERTS_DIR = "certs"


# ═══════════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════════

def bg(cmd):
    """Start a background subprocess (stdout/stderr suppressed)."""
    return subprocess.Popen(
        cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )


def stop(processes):
    """Terminate and wait for a dict of Popen objects."""
    for proc in processes.values():
        proc.terminate()
    for proc in processes.values():
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def ensure_certs():
    """Generate TLS certs if they don't already exist."""
    cert = os.path.join(CERTS_DIR, "cert.pem")
    key = os.path.join(CERTS_DIR, "key.pem")
    if not os.path.isfile(cert) or not os.path.isfile(key):
        print("  Generating TLS certificates...")
        subprocess.run([sys.executable, os.path.join(CERTS_DIR, "generate_certs.py")])
    return os.path.abspath(cert), os.path.abspath(key)


def ensure_content():
    """Generate test content (including small files for multi-object test)."""
    print("  Generating test content...")
    subprocess.run([sys.executable, "generate_content.py"])


# ═══════════════════════════════════════════════════════════════════════
#  SERVER MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════

def start_servers(content_dir, cert, key):
    """Start all five protocol servers in the background."""
    servers = {}

    # Original Gopher (closes connection after each request)
    servers["gopher-original"] = bg([
        sys.executable, "server/gopher/gopher_server.py",
        "--port", str(PORTS["gopher-original"]["server"]),
        "--dir", content_dir,
    ])

    # Modern Gopher (persistent TCP connections)
    servers["gopher-modern"] = bg([
        sys.executable, "server/gopher/gopher_modern_server.py",
        "--port", str(PORTS["gopher-modern"]["server"]),
        "--dir", content_dir,
    ])

    # HTTP/1.1 (Flask)
    servers["http/1.1"] = bg([
        sys.executable, "server/http/http_server.py",
        "--port", str(PORTS["http/1.1"]["server"]),
        "--dir", content_dir,
    ])

    # HTTP/2 (Hypercorn + Quart + TLS)
    servers["http/2"] = bg([
        sys.executable, "server/http/http2_server.py",
        "--port", str(PORTS["http/2"]["server"]),
        "--dir", content_dir,
        "--certfile", cert,
        "--keyfile", key,
    ])

    # HTTP/3 (aioquic + QUIC + TLS 1.3)
    servers["http/3"] = bg([
        sys.executable, "server/http/http3_server.py",
        "--port", str(PORTS["http/3"]["server"]),
        "--dir", content_dir,
        "--certfile", cert,
        "--keyfile", key,
    ])

    return servers


def run_suite():
    """Main entry point: run the full benchmark suite."""
    os.makedirs(RESULTS_DIR, exist_ok=True)
    content_dir = os.path.abspath("data/content")

    print("=" * 64)
    print("  CS204 Protocol Benchmark Suite")
    print("  Original Gopher | Modern Gopher | HTTP/1.1 | HTTP/2 | HTTP/3")
    print(f"  Runs per test: {RUNS_PER_TEST}  |  Multi files: {len(MULTI_FILES)}")
    print("=" * 64)

    # Prerequisites
    ensure_content()
    cert, key = ensure_certs()

    # Start all servers
    print("\n  Starting servers...")
    servers = start_servers(content_dir, cert, key)
    time.sleep(3)  # Allow servers to bind






# ═══════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    run_suite()