"""
Automated Test Suite — Protocol Performance Comparison

Orchestrates the full benchmark:
  1. Starts all servers (Original Gopher, Modern Gopher, HTTP/1.1, HTTP/2, HTTP/3)
  2. For each network scenario, starts TCP/UDP proxies
  3. Runs benchmarks for every protocol × test type combination
  4. Collects CSV results and generates visualisations

Comparison groups:
  Group A:  Original Gopher  vs  HTTP/1.1  vs  HTTP/2  vs  HTTP/3
  Group B:  Modern Gopher    vs  HTTP/1.1  vs  HTTP/2  vs  HTTP/3

Test types (inspired by real-world scenarios):
  1. Handshake Test     — single small file  (1 KB)
  2. Throughput Test    — single large file   (1 MB)
  3. Multi-Object Test  — 10 small files      (waterfall)
"""

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
    "http/1.1":        {"server": 8080, "proxy": 9080},
    "http/2":          {"server": 8443, "proxy": 9443},
    "http/3":          {"server": 4433, "proxy": 9433},
}

ALL_PROTOCOLS = ["gopher-original", "gopher-modern", "http/1.1", "http/2", "http/3"]
LOOPBACK_HOST = "127.0.0.1"

SCENARIOS = [
    {"name": "Baseline",     "latency": 0,   "loss": 0},
    {"name": "High_Latency", "latency": 100, "loss": 0},
    {"name": "Packet_Loss",  "latency": 0,   "loss": 5},
    {"name": "Mixed",        "latency": 50,  "loss": 2},
]

# 10 small files for the multi-object (waterfall) test
MULTI_FILES = [f"small_{i:02d}.txt" for i in range(10)]

RUNS_PER_TEST = 3


def _quantile_interval(values):
    q1 = values.quantile(0.25)
    q3 = values.quantile(0.75)
    median = values.quantile(0.5)
    return median, q1, q3


def _median_estimator(values):
    return values.quantile(0.5)


def _apply_iqr_errorbars(ax, df, category_col, value_col, hue_col=None, order=None, hue_order=None):
    from matplotlib.lines import Line2D

    if order is None:
        order = list(dict.fromkeys(df[category_col]))
    if hue_col is not None and hue_order is None:
        hue_order = list(dict.fromkeys(df[hue_col]))

    bars = [patch for patch in ax.patches if patch.get_height() == patch.get_height()]
    bar_idx = 0

    for category in order:
        if hue_col is None:
            subset = df[df[category_col] == category][value_col]
            if subset.empty:
                continue
            median, q1, q3 = _quantile_interval(subset)
            patch = bars[bar_idx]
            x = patch.get_x() + patch.get_width() / 2
            ax.add_line(Line2D([x, x], [q1, q3], color="black", linewidth=1.2, zorder=5))
            ax.add_line(Line2D([x - patch.get_width() * 0.18, x + patch.get_width() * 0.18], [q1, q1], color="black", linewidth=1.2, zorder=5))
            ax.add_line(Line2D([x - patch.get_width() * 0.18, x + patch.get_width() * 0.18], [q3, q3], color="black", linewidth=1.2, zorder=5))
            bar_idx += 1
        else:
            for hue in hue_order:
                subset = df[(df[category_col] == category) & (df[hue_col] == hue)][value_col]
                if subset.empty:
                    continue
                median, q1, q3 = _quantile_interval(subset)
                patch = bars[bar_idx]
                x = patch.get_x() + patch.get_width() / 2
                ax.add_line(Line2D([x, x], [q1, q3], color="black", linewidth=1.0, zorder=5))
                ax.add_line(Line2D([x - patch.get_width() * 0.18, x + patch.get_width() * 0.18], [q1, q1], color="black", linewidth=1.0, zorder=5))
                ax.add_line(Line2D([x - patch.get_width() * 0.18, x + patch.get_width() * 0.18], [q3, q3], color="black", linewidth=1.0, zorder=5))
                bar_idx += 1

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


def ensure_started(processes, label, delay=1.0):
    """Fail fast if any background process exits during startup."""
    time.sleep(delay)
    failed = [name for name, proc in processes.items() if proc.poll() is not None]
    if failed:
        stop({name: proc for name, proc in processes.items() if proc.poll() is None})
        joined = ", ".join(failed)
        raise RuntimeError(f"{label} failed to start: {joined}")


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
        subprocess.run([sys.executable, os.path.join(CERTS_DIR, "generate_certs.py")], check=True)
    return os.path.abspath(cert), os.path.abspath(key)


def ensure_content():
    """Generate test content (including small files for multi-object test)."""
    print("  Generating test content...")
    subprocess.run([sys.executable, "generate_content.py"], check=True)


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


def start_proxies(scenario):
    """Start TCP proxies (Gopher + HTTP/1.1 + HTTP/2) and UDP proxy (HTTP/3)."""
    proxies = {}
    lat = str(scenario["latency"])
    loss = str(scenario["loss"])

    # TCP proxies for all TCP-based protocols
    for proto in ["gopher-original", "gopher-modern", "http/1.1", "http/2"]:
        proxies[proto] = bg([
            sys.executable, "server/proxy.py",
            "--target_host", LOOPBACK_HOST,
            "--target_port", str(PORTS[proto]["server"]),
            "--listen_port", str(PORTS[proto]["proxy"]),
            "--latency", lat,
            "--loss", loss,
        ])

    # UDP proxy for QUIC / HTTP/3
    proxies["http/3"] = bg([
        sys.executable, "server/udp_proxy.py",
        "--target_host", LOOPBACK_HOST,
        "--target_port", str(PORTS["http/3"]["server"]),
        "--listen_port", str(PORTS["http/3"]["proxy"]),
        "--latency", lat,
        "--loss", loss,
    ])

    return proxies


# ═══════════════════════════════════════════════════════════════════════
#  BENCHMARK EXECUTION
# ═══════════════════════════════════════════════════════════════════════

def run_bench(runner, protocol, host, port, test_type, files, runs, scenario):
    """Run benchmark in-process (no subprocess overhead)."""
    if test_type == "single":
        runner.run_single(protocol, host, port, files, runs, scenario)
    else:
        filenames = files if isinstance(files, list) else [f.strip() for f in files.split(",")]
        runner.run_multi(protocol, host, port, filenames, runs, scenario)


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
    ensure_started(servers, "Server startup", delay=3.0)

    try:
        for scenario in SCENARIOS:
            name = scenario["name"]
            print(f"\n{'='*64}")
            print(f"  SCENARIO: {name}")
            print(f"  Latency: {scenario['latency']} ms   Packet Loss: {scenario['loss']}%")
            print(f"{'='*64}")

            output_file = os.path.join(RESULTS_DIR, f"results_{name}.csv")

            # Clear old results for this scenario
            if os.path.exists(output_file):
                os.remove(output_file)

            # Start proxies with network conditions
            proxies = start_proxies(scenario)
            ensure_started(proxies, f"Proxy startup for {name}")

            # Create a single in-process runner for this scenario
            runner = BenchmarkRunner(output_file)

            for protocol in ALL_PROTOCOLS:
                port = PORTS[protocol]["proxy"]

                print(f"\n  --- {protocol} (via proxy :{port}) ---")

                # 1. Handshake Test — small file (connection setup dominated)
                print("  [Handshake Test]")
                run_bench(runner, protocol, LOOPBACK_HOST, port,
                          "single", "1kb.txt", RUNS_PER_TEST, name)

                # 2. Throughput Test — large file (transfer dominated)
                print("  [Throughput Test]")
                run_bench(runner, protocol, LOOPBACK_HOST, port,
                          "single", "1mb.txt", RUNS_PER_TEST, name)

                # 3. Multi-Object Test — waterfall
                print("  [Multi-Object Test]")
                run_bench(runner, protocol, LOOPBACK_HOST, port,
                          "multi", MULTI_FILES, RUNS_PER_TEST, name)

            # Save all results for this scenario at once
            runner.save()

            # Tear down proxies
            stop(proxies)
            time.sleep(1)

    finally:
        print("\n  Stopping servers...")
        stop(servers)

    print(f"\n{'='*64}")
    print("  Benchmarks complete — generating analysis")
    print(f"{'='*64}\n")
    analyze_results()


# ═══════════════════════════════════════════════════════════════════════
#  ANALYSIS & VISUALISATION
# ═══════════════════════════════════════════════════════════════════════

def analyze_results():
    """Load all CSV results, compute statistics, and generate charts."""
    all_dfs = []
    for scenario in SCENARIOS:
        path = os.path.join(RESULTS_DIR, f"results_{scenario['name']}.csv")
        if os.path.exists(path):
            df = pd.read_csv(path)
            all_dfs.append(df)

    if not all_dfs:
        print("  No results found to analyse.")
        return

    combined = pd.concat(all_dfs, ignore_index=True)

    # ── Summary Statistics ────────────────────────────────────────────
    summary = (
        combined
        .groupby(["scenario", "protocol", "test_type", "file"])
        [["ttfb", "total_time", "bytes", "throughput"]]
        .agg(["mean", "std", "median", ("q1", lambda s: s.quantile(0.25)), ("q3", lambda s: s.quantile(0.75))])
    )
    summary_path = os.path.join(RESULTS_DIR, "summary_statistics.csv")
    summary.to_csv(summary_path)
    print(f"  Summary saved to {summary_path}")

    # ── Charts ────────────────────────────────────────────────────────
    sns.set_theme(style="whitegrid", font_scale=1.1)
    palette = {
        "gopher-original": "#e74c3c",
        "gopher-modern":   "#e67e22",
        "http/1.1":        "#3498db",
        "http/2":          "#2ecc71",
        "http/3":          "#9b59b6",
    }

    single = combined[combined["test_type"] == "single"]
    multi  = combined[combined["test_type"] == "multi"]

    # 1. TTFB bar chart per scenario (single tests)
    for scenario in SCENARIOS:
        scn = scenario["name"]
        data = single[single["scenario"] == scn]
        if data.empty:
            continue

        fig, ax = plt.subplots(figsize=(12, 6))
        sns.barplot(data=data, x="file", y="ttfb", hue="protocol",
                    palette=palette, ax=ax, estimator=_median_estimator, errorbar=None)
        _apply_iqr_errorbars(ax, data, "file", "ttfb", hue_col="protocol")
        ax.set_title(f"Time to First Byte (TTFB) — {scn}", fontsize=14)
        ax.set_ylabel("TTFB (ms)")
        ax.set_xlabel("File")
        ax.legend(title="Protocol", loc="upper left")
        fig.savefig(os.path.join(RESULTS_DIR, f"ttfb_{scn}.png"),
                    dpi=150, bbox_inches="tight")
        plt.close(fig)

    # 2. Multi-Object total time per scenario
    for scenario in SCENARIOS:
        scn = scenario["name"]
        data = multi[multi["scenario"] == scn]
        if data.empty:
            continue

        fig, ax = plt.subplots(figsize=(10, 6))
        sns.barplot(data=data, x="protocol", y="total_time",
                    palette=palette, ax=ax, estimator=_median_estimator, errorbar=None,
                    order=ALL_PROTOCOLS)
        _apply_iqr_errorbars(ax, data, "protocol", "total_time", order=ALL_PROTOCOLS)
        ax.set_title(f"Multi-Object Total Time ({len(MULTI_FILES)} files) — {scn}", fontsize=14)
        ax.set_ylabel("Total Time (ms)")
        ax.set_xlabel("Protocol")
        fig.savefig(os.path.join(RESULTS_DIR, f"multi_{scn}.png"),
                    dpi=150, bbox_inches="tight")
        plt.close(fig)

    # 3. Throughput comparison for large file
    large = single[single["file"] == "1mb.txt"]
    if not large.empty:
        fig, ax = plt.subplots(figsize=(12, 6))
        sns.barplot(data=large, x="scenario", y="throughput", hue="protocol",
                    palette=palette, ax=ax, estimator=_median_estimator, errorbar=None)
        _apply_iqr_errorbars(ax, large, "scenario", "throughput", hue_col="protocol")
        ax.set_title("Throughput — 1 MB File Transfer", fontsize=14)
        ax.set_ylabel("Throughput (kbps)")
        ax.set_xlabel("Network Scenario")
        ax.legend(title="Protocol")
        fig.savefig(os.path.join(RESULTS_DIR, "throughput_1mb.png"),
                    dpi=150, bbox_inches="tight")
        plt.close(fig)

    # 4. Overview: 2×2 grid of scenarios (total time, single tests)
    fig, axes = plt.subplots(2, 2, figsize=(18, 12))
    for idx, scenario in enumerate(SCENARIOS):
        ax = axes[idx // 2][idx % 2]
        scn = scenario["name"]
        data = single[single["scenario"] == scn]
        if not data.empty:
            sns.barplot(data=data, x="file", y="total_time", hue="protocol",
                        palette=palette, ax=ax, estimator=_median_estimator, errorbar=None)
            _apply_iqr_errorbars(ax, data, "file", "total_time", hue_col="protocol")
            ax.set_title(f"Total Transfer Time — {scn}")
            ax.set_ylabel("Time (ms)")
            ax.set_xlabel("File")
            ax.legend(title="Protocol", fontsize=8)
    fig.suptitle("Single-File Performance Across All Scenarios", fontsize=16)
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    fig.savefig(os.path.join(RESULTS_DIR, "comparison_overview.png"),
                dpi=150)
    plt.close(fig)

    # 5. Group comparison charts (Original Gopher vs HTTP, Modern Gopher vs HTTP)
    http_protos = ["http/1.1", "http/2", "http/3"]

    for group_name, gopher_variant in [("Original_Gopher", "gopher-original"),
                                        ("Modern_Gopher", "gopher-modern")]:
        group_protos = [gopher_variant] + http_protos
        group_data = combined[combined["protocol"].isin(group_protos)]
        if group_data.empty:
            continue

        group_single = group_data[group_data["test_type"] == "single"]
        group_multi  = group_data[group_data["test_type"] == "multi"]

        # TTFB comparison grid
        fig, axes = plt.subplots(2, 2, figsize=(18, 12))
        for idx, scenario in enumerate(SCENARIOS):
            ax = axes[idx // 2][idx % 2]
            scn = scenario["name"]
            data = group_single[group_single["scenario"] == scn]
            if not data.empty:
                sns.barplot(data=data, x="file", y="ttfb", hue="protocol",
                            palette=palette, ax=ax, estimator=_median_estimator, errorbar=None,
                            hue_order=group_protos)
                _apply_iqr_errorbars(ax, data, "file", "ttfb", hue_col="protocol", hue_order=group_protos)
                ax.set_title(f"TTFB — {scn}")
                ax.set_ylabel("TTFB (ms)")
                ax.legend(title="Protocol", fontsize=8)
        fig.suptitle(f"Group: {group_name.replace('_', ' ')} vs HTTP/*", fontsize=16)
        fig.tight_layout(rect=[0, 0, 1, 0.96])
        fig.savefig(os.path.join(RESULTS_DIR, f"group_{group_name}_ttfb.png"),
                    dpi=150)
        plt.close(fig)

        # Multi-object comparison
        fig, axes = plt.subplots(2, 2, figsize=(18, 12))
        for idx, scenario in enumerate(SCENARIOS):
            ax = axes[idx // 2][idx % 2]
            scn = scenario["name"]
            data = group_multi[group_multi["scenario"] == scn]
            if not data.empty:
                sns.barplot(data=data, x="protocol", y="total_time",
                            palette=palette, ax=ax, estimator=_median_estimator, errorbar=None,
                            order=group_protos)
                _apply_iqr_errorbars(ax, data, "protocol", "total_time", order=group_protos)
                ax.set_title(f"Multi-Object — {scn}")
                ax.set_ylabel("Total Time (ms)")
        fig.suptitle(f"Group: {group_name.replace('_', ' ')} vs HTTP/* — Multi-Object",
                     fontsize=16)
        fig.tight_layout(rect=[0, 0, 1, 0.96])
        fig.savefig(os.path.join(RESULTS_DIR, f"group_{group_name}_multi.png"),
                    dpi=150)
        plt.close(fig)

    print(f"  Charts saved to {RESULTS_DIR}/")


# ═══════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    run_suite()
