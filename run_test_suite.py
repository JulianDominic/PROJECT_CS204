"""
Automated Test Suite — Protocol Performance Comparison

Orchestrates the benchmark suite and supports a shorter demo path.

Modes:
  - Full benchmark runs for report-quality data collection
  - Demo presets for a short live benchmark
  - Static analysis charts and an interactive HTML dashboard
"""

import argparse
import concurrent.futures
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, replace

import matplotlib
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import seaborn as sns
from plotly.subplots import make_subplots

matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from client.benchmark import BenchmarkRunner


PORTS = {
    "gopher-original": {"server": 7070, "proxy": 9070},
    "gopher-modern": {"server": 7071, "proxy": 9071},
    "http/1.1": {"server": 8080, "proxy": 9080},
    "http/2": {"server": 8443, "proxy": 9443},
    "http/3": {"server": 4433, "proxy": 9433},
}

ALL_PROTOCOLS = ["gopher-original", "gopher-modern", "http/1.1", "http/2", "http/3"]
DEFAULT_SCENARIOS = [
    {"name": "Baseline", "latency": 0, "loss": 0, "bandwidth": 0},
    {"name": "High_Latency", "latency": 100, "loss": 0, "bandwidth": 0},
    {"name": "Packet_Loss", "latency": 0, "loss": 5, "bandwidth": 0},
    {"name": "Mixed", "latency": 50, "loss": 2, "bandwidth": 0},
    {"name": "Bandwidth_Limited", "latency": 20, "loss": 0, "bandwidth": 125000},
    {"name": "Realistic_WAN", "latency": 30, "loss": 1, "bandwidth": 500000},
]
TEST_DEFINITIONS = {
    "handshake": {"kind": "single", "files": "1kb.txt", "label": "Handshake Test"},
    "throughput": {"kind": "single", "files": "1mb.txt", "label": "Throughput Test"},
    "throughput_10kb": {"kind": "single", "files": "10kb.txt", "label": "Throughput 10KB"},
    "throughput_100kb": {"kind": "single", "files": "100kb.txt", "label": "Throughput 100KB"},
    "throughput_5mb": {"kind": "single", "files": "5mb.txt", "label": "Throughput 5MB"},
    "multi": {"kind": "multi", "files": None, "label": "Multi-Object Test"},
    "multi_5": {"kind": "multi", "files": None, "label": "Multi-Object (5 files)", "multi_count": 5},
    "multi_20": {"kind": "multi", "files": None, "label": "Multi-Object (20 files)", "multi_count": 20},
}
DEFAULT_TEST_ORDER = ["handshake", "throughput", "throughput_10kb", "throughput_100kb", "throughput_5mb", "multi", "multi_5", "multi_20"]
LOOPBACK_HOST = "127.0.0.1"
DEFAULT_MULTI_FILE_COUNT = 10
DEFAULT_RUNS_PER_TEST = 10
RESULTS_DIR = "results"
CERTS_DIR = "certs"
DASHBOARD_FILENAME = "demo_dashboard.html"
PALETTE = {
    "gopher-original": "#e74c3c",
    "gopher-modern": "#e67e22",
    "http/1.1": "#3498db",
    "http/2": "#2ecc71",
    "http/3": "#9b59b6",
}


@dataclass(frozen=True)
class SuiteConfig:
    name: str
    scenarios: tuple[str, ...]
    protocols: tuple[str, ...]
    tests: tuple[str, ...]
    runs_per_test: int
    multi_file_count: int
    output_suffix: str | None = None
    incremental_save: bool = False
    include_static_analysis: bool = True
    include_dashboard: bool = True


PRESET_CONFIGS = {
    "full": SuiteConfig(
        name="full",
        scenarios=tuple(scenario["name"] for scenario in DEFAULT_SCENARIOS),
        protocols=tuple(ALL_PROTOCOLS),
        tests=tuple(DEFAULT_TEST_ORDER),
        runs_per_test=DEFAULT_RUNS_PER_TEST,
        multi_file_count=DEFAULT_MULTI_FILE_COUNT,
    ),
    "demo_live": SuiteConfig(
        name="demo_live",
        scenarios=("Baseline", "Packet_Loss", "Realistic_WAN"),
        protocols=tuple(ALL_PROTOCOLS),
        tests=("handshake", "throughput", "multi"),
        runs_per_test=1,
        multi_file_count=10,
        output_suffix="demo_live",
        incremental_save=True,
    ),
    "demo_baseline": SuiteConfig(
        name="demo_baseline",
        scenarios=("Baseline",),
        protocols=("gopher-original", "http/1.1", "http/3"),
        tests=("handshake", "multi"),
        runs_per_test=1,
        multi_file_count=5,
        output_suffix="demo_baseline",
        incremental_save=True,
    ),
    "demo_packet_loss": SuiteConfig(
        name="demo_packet_loss",
        scenarios=("Packet_Loss",),
        protocols=("gopher-original", "http/1.1", "http/3"),
        tests=("handshake", "throughput"),
        runs_per_test=1,
        multi_file_count=5,
        output_suffix="demo_packet_loss",
        incremental_save=True,
    ),
    "demo_compare_all": SuiteConfig(
        name="demo_compare_all",
        scenarios=("Baseline",),
        protocols=tuple(ALL_PROTOCOLS),
        tests=("handshake",),
        runs_per_test=1,
        multi_file_count=5,
        output_suffix="demo_compare_all",
        incremental_save=True,
    ),
}
SCENARIO_MAP = {scenario["name"]: scenario for scenario in DEFAULT_SCENARIOS}


def build_multi_files(count):
    return [f"small_{i:02d}.txt" for i in range(count)]


def output_filename_for(config, scenario_name):
    if config.output_suffix:
        return os.path.join(RESULTS_DIR, f"results_{scenario_name}_{config.output_suffix}.csv")
    return os.path.join(RESULTS_DIR, f"results_{scenario_name}.csv")


def available_output_files(config):
    return [output_filename_for(config, scenario_name) for scenario_name in config.scenarios]


def selected_scenarios(config):
    return [SCENARIO_MAP[name] for name in config.scenarios]


def planned_steps(config):
    steps = []
    for scenario_name in config.scenarios:
        for protocol in config.protocols:
            for test_name in config.tests:
                steps.append((scenario_name, protocol, test_name))
    return steps


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
            _, q1, q3 = _quantile_interval(subset)
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
                _, q1, q3 = _quantile_interval(subset)
                patch = bars[bar_idx]
                x = patch.get_x() + patch.get_width() / 2
                ax.add_line(Line2D([x, x], [q1, q3], color="black", linewidth=1.0, zorder=5))
                ax.add_line(Line2D([x - patch.get_width() * 0.18, x + patch.get_width() * 0.18], [q1, q1], color="black", linewidth=1.0, zorder=5))
                ax.add_line(Line2D([x - patch.get_width() * 0.18, x + patch.get_width() * 0.18], [q3, q3], color="black", linewidth=1.0, zorder=5))
                bar_idx += 1


def bg(cmd):
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def ensure_started(processes, label, delay=1.0):
    time.sleep(delay)
    failed = [name for name, proc in processes.items() if proc.poll() is not None]
    if failed:
        stop({name: proc for name, proc in processes.items() if proc.poll() is None})
        raise RuntimeError(f"{label} failed to start: {', '.join(failed)}")


def stop(processes):
    for proc in processes.values():
        proc.terminate()
    for proc in processes.values():
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def ensure_certs():
    cert = os.path.join(CERTS_DIR, "cert.pem")
    key = os.path.join(CERTS_DIR, "key.pem")
    if not os.path.isfile(cert) or not os.path.isfile(key):
        print("  Generating TLS certificates...")
        subprocess.run([sys.executable, os.path.join(CERTS_DIR, "generate_certs.py")], check=True)
    return os.path.abspath(cert), os.path.abspath(key)


def ensure_content():
    print("  Generating test content...")
    subprocess.run([sys.executable, "generate_content.py"], check=True)


def start_servers(content_dir, cert, key):
    servers = {}
    servers["gopher-original"] = bg([sys.executable, "server/gopher/gopher_server.py", "--port", str(PORTS["gopher-original"]["server"]), "--dir", content_dir])
    servers["gopher-modern"] = bg([sys.executable, "server/gopher/gopher_modern_server.py", "--port", str(PORTS["gopher-modern"]["server"]), "--dir", content_dir])
    servers["http/1.1"] = bg([sys.executable, "server/http/http_server.py", "--port", str(PORTS["http/1.1"]["server"]), "--dir", content_dir])
    servers["http/2"] = bg([sys.executable, "server/http/http2_server.py", "--port", str(PORTS["http/2"]["server"]), "--dir", content_dir, "--certfile", cert, "--keyfile", key])
    servers["http/3"] = bg([sys.executable, "server/http/http3_server.py", "--port", str(PORTS["http/3"]["server"]), "--dir", content_dir, "--certfile", cert, "--keyfile", key])
    return servers


def start_proxies(scenario, protocols):
    proxies = {}
    lat = str(scenario["latency"])
    loss = str(scenario["loss"])
    bw = str(scenario.get("bandwidth", 0))
    for proto in [proto for proto in protocols if proto != "http/3"]:
        proxies[proto] = bg([sys.executable, "server/proxy.py", "--target_host", LOOPBACK_HOST, "--target_port", str(PORTS[proto]["server"]), "--listen_port", str(PORTS[proto]["proxy"]), "--latency", lat, "--loss", loss, "--bandwidth", bw])
    if "http/3" in protocols:
        proxies["http/3"] = bg([sys.executable, "server/udp_proxy.py", "--target_host", LOOPBACK_HOST, "--target_port", str(PORTS["http/3"]["server"]), "--listen_port", str(PORTS["http/3"]["proxy"]), "--latency", lat, "--loss", loss, "--bandwidth", bw])
    return proxies


def run_bench(runner, protocol, host, port, test_type, files, runs, scenario):
    if test_type == "single":
        runner.run_single(protocol, host, port, files, runs, scenario)
    else:
        filenames = files if isinstance(files, list) else [f.strip() for f in files.split(",")]
        runner.run_multi(protocol, host, port, filenames, runs, scenario)


def execute_test(runner, protocol, port, test_name, config, scenario_name):
    test_def = TEST_DEFINITIONS[test_name]
    if test_def["kind"] == "multi":
        count = test_def.get("multi_count", config.multi_file_count)
        files = build_multi_files(count)
    else:
        files = test_def["files"]
    print(f"  [{test_def['label']}]")
    run_bench(runner, protocol, LOOPBACK_HOST, port, test_def["kind"], files, config.runs_per_test, scenario_name)
    if config.incremental_save:
        runner.save()


def load_results(config):
    dataframes = []
    for scenario_name in config.scenarios:
        path = output_filename_for(config, scenario_name)
        if os.path.exists(path):
            dataframes.append(pd.read_csv(path))
    if not dataframes:
        return None
    return pd.concat(dataframes, ignore_index=True)


def summarize_results(combined):
    return combined.groupby(["scenario", "protocol", "test_type", "file"])[["ttfb", "total_time", "bytes", "throughput"]].agg(["mean", "std", "median", ("q1", lambda s: s.quantile(0.25)), ("q3", lambda s: s.quantile(0.75))])


def analyze_results(config):
    combined = load_results(config)
    if combined is None or combined.empty:
        print("  No results found to analyse.")
        return None

    summary = summarize_results(combined)
    suffix = f"_{config.output_suffix}" if config.output_suffix else ""
    summary_path = os.path.join(RESULTS_DIR, f"summary_statistics{suffix}.csv")
    summary.to_csv(summary_path)
    print(f"  Summary saved to {summary_path}")

    sns.set_theme(style="whitegrid", font_scale=1.1)
    single = combined[combined["test_type"] == "single"]
    multi = combined[combined["test_type"] == "multi"]
    protocol_order = [proto for proto in ALL_PROTOCOLS if proto in config.protocols]

    for scenario_name in config.scenarios:
        data = single[single["scenario"] == scenario_name]
        if not data.empty:
            fig, ax = plt.subplots(figsize=(12, 6))
            sns.barplot(data=data, x="file", y="ttfb", hue="protocol", palette=PALETTE, ax=ax, estimator=_median_estimator, errorbar=None, hue_order=protocol_order)
            _apply_iqr_errorbars(ax, data, "file", "ttfb", hue_col="protocol", hue_order=protocol_order)
            ax.set_title(f"Time to First Byte (TTFB) — {scenario_name}", fontsize=14)
            ax.set_ylabel("TTFB (ms)")
            ax.set_xlabel("File")
            ax.legend(title="Protocol", loc="upper left")
            fig.savefig(os.path.join(RESULTS_DIR, f"ttfb_{scenario_name}{suffix}.png"), dpi=150, bbox_inches="tight")
            plt.close(fig)

        data = multi[multi["scenario"] == scenario_name]
        if not data.empty:
            fig, ax = plt.subplots(figsize=(10, 6))
            sns.barplot(data=data, x="protocol", y="total_time", palette=PALETTE, ax=ax, estimator=_median_estimator, errorbar=None, order=protocol_order)
            _apply_iqr_errorbars(ax, data, "protocol", "total_time", order=protocol_order)
            ax.set_title(f"Multi-Object Total Time ({config.multi_file_count} files) — {scenario_name}", fontsize=14)
            ax.set_ylabel("Total Time (ms)")
            ax.set_xlabel("Protocol")
            fig.savefig(os.path.join(RESULTS_DIR, f"multi_{scenario_name}{suffix}.png"), dpi=150, bbox_inches="tight")
            plt.close(fig)

    large = single[single["file"] == "1mb.txt"]
    if not large.empty:
        fig, ax = plt.subplots(figsize=(12, 6))
        sns.barplot(data=large, x="scenario", y="throughput", hue="protocol", palette=PALETTE, ax=ax, estimator=_median_estimator, errorbar=None, hue_order=protocol_order)
        _apply_iqr_errorbars(ax, large, "scenario", "throughput", hue_col="protocol", hue_order=protocol_order)
        ax.set_title("Throughput — 1 MB File Transfer", fontsize=14)
        ax.set_ylabel("Throughput (kbps)")
        ax.set_xlabel("Network Scenario")
        ax.legend(title="Protocol")
        fig.savefig(os.path.join(RESULTS_DIR, f"throughput_1mb{suffix}.png"), dpi=150, bbox_inches="tight")
        plt.close(fig)

    # Throughput vs File Size chart
    file_size_order = ["1kb.txt", "10kb.txt", "100kb.txt", "1mb.txt", "5mb.txt"]
    file_size_labels = {"1kb.txt": "1 KB", "10kb.txt": "10 KB", "100kb.txt": "100 KB", "1mb.txt": "1 MB", "5mb.txt": "5 MB"}
    scaling_data = single[single["file"].isin(file_size_order)]
    if not scaling_data.empty:
        for scenario_name in config.scenarios:
            data = scaling_data[scaling_data["scenario"] == scenario_name]
            if data.empty:
                continue
            fig, ax = plt.subplots(figsize=(12, 6))
            for protocol in protocol_order:
                proto_data = data[data["protocol"] == protocol]
                if proto_data.empty:
                    continue
                medians = proto_data.groupby("file")["throughput"].median().reindex(file_size_order).dropna()
                ax.plot([file_size_labels.get(f, f) for f in medians.index], medians.values,
                        marker="o", label=protocol, color=PALETTE.get(protocol))
            ax.set_title(f"Throughput vs File Size — {scenario_name}", fontsize=14)
            ax.set_ylabel("Throughput (kbps)")
            ax.set_xlabel("File Size")
            ax.legend(title="Protocol")
            ax.set_yscale("log")
            fig.savefig(os.path.join(RESULTS_DIR, f"throughput_scaling_{scenario_name}{suffix}.png"), dpi=150, bbox_inches="tight")
            plt.close(fig)

    # Multi-Object Scaling chart
    multi_scaling = multi.copy()
    # Extract file count from the "file" column (e.g. "5_files" -> 5)
    multi_scaling["file_count"] = multi_scaling["file"].str.extract(r"(\d+)").astype(int)
    if not multi_scaling.empty:
        for scenario_name in config.scenarios:
            data = multi_scaling[multi_scaling["scenario"] == scenario_name]
            if data.empty:
                continue
            fig, ax = plt.subplots(figsize=(10, 6))
            for protocol in protocol_order:
                proto_data = data[data["protocol"] == protocol]
                if proto_data.empty:
                    continue
                medians = proto_data.groupby("file_count")["total_time"].median().sort_index()
                ax.plot(medians.index, medians.values, marker="s", label=protocol, color=PALETTE.get(protocol))
            ax.set_title(f"Multi-Object Scaling — {scenario_name}", fontsize=14)
            ax.set_ylabel("Total Time (ms)")
            ax.set_xlabel("Number of Files")
            ax.legend(title="Protocol")
            ax.set_xticks(sorted(data["file_count"].unique()))
            fig.savefig(os.path.join(RESULTS_DIR, f"multi_scaling_{scenario_name}{suffix}.png"), dpi=150, bbox_inches="tight")
            plt.close(fig)

    cols = 2
    rows = max(1, (len(config.scenarios) + cols - 1) // cols)
    fig, axes = plt.subplots(rows, cols, figsize=(18, 6 * rows), squeeze=False)
    for idx, scenario_name in enumerate(config.scenarios):
        ax = axes[idx // cols][idx % cols]
        data = single[single["scenario"] == scenario_name]
        if not data.empty:
            sns.barplot(data=data, x="file", y="total_time", hue="protocol", palette=PALETTE, ax=ax, estimator=_median_estimator, errorbar=None, hue_order=protocol_order)
            _apply_iqr_errorbars(ax, data, "file", "total_time", hue_col="protocol", hue_order=protocol_order)
            ax.set_title(f"Total Transfer Time — {scenario_name}")
            ax.set_ylabel("Time (ms)")
            ax.set_xlabel("File")
            ax.legend(title="Protocol", fontsize=8)
    for idx in range(len(config.scenarios), rows * cols):
        axes[idx // cols][idx % cols].axis("off")
    fig.suptitle("Single-File Performance Across Selected Scenarios", fontsize=16)
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    fig.savefig(os.path.join(RESULTS_DIR, f"comparison_overview{suffix}.png"), dpi=150)
    plt.close(fig)

    print(f"  Charts saved to {RESULTS_DIR}/")
    return {"combined": combined, "summary": summary, "summary_path": summary_path}


def _metric_label(metric):
    return {"ttfb": "TTFB (ms)", "total_time": "Total Time (ms)", "throughput": "Throughput (kbps)"}.get(metric, metric)


def create_overview_figure(aggregated, protocol_order):
    has_multi = not aggregated[aggregated["test_name"] == "multi"].empty
    col_count = 3 if has_multi else 2
    titles = ["Handshake Latency", "Large File Throughput"]
    if has_multi:
        titles.append("Multi-Object Total Time")
    fig = make_subplots(rows=1, cols=col_count, subplot_titles=tuple(titles))
    metric_frames = {
        "ttfb": aggregated[aggregated["test_name"] == "handshake"],
        "throughput": aggregated[aggregated["test_name"] == "throughput"],
        "total_time": aggregated[aggregated["test_name"] == "multi"],
    }
    active_metrics = ["ttfb", "throughput"] + (["total_time"] if has_multi else [])
    for col_index, metric in enumerate(active_metrics, start=1):
        metric_df = metric_frames[metric]
        for protocol in protocol_order:
            subset = metric_df[metric_df["protocol"] == protocol]
            if subset.empty:
                continue
            fig.add_trace(go.Bar(x=subset["scenario"], y=subset[metric], name=protocol, marker_color=PALETTE[protocol], showlegend=col_index == 1, hovertemplate="Scenario=%{x}<br>Protocol=" + protocol + f"<br>{_metric_label(metric)}=%{{y:.2f}}<extra></extra>"), row=1, col=col_index)
        fig.update_yaxes(title_text=_metric_label(metric), row=1, col=col_index)
    fig.update_layout(
        barmode="group",
        template="plotly_white",
        title="Protocol Comparison Overview",
        legend_title="Protocol",
        height=520,
    )
    return fig


def create_distribution_figure(combined, protocol_order):
    focus = combined[(combined["scenario"].isin(["Packet_Loss", "Mixed"])) & (combined["test_type"] == "single")]
    if focus.empty:
        focus = combined[combined["test_type"] == "single"]
    fig = px.box(focus, x="protocol", y="total_time", color="protocol", facet_col="scenario", points="all", color_discrete_map=PALETTE, category_orders={"protocol": protocol_order, "scenario": list(dict.fromkeys(focus["scenario"]))}, title="Variance View: Single-File Total Time", labels={"total_time": "Total Time (ms)", "protocol": "Protocol"})
    fig.update_layout(template="plotly_white", height=520, showlegend=False)
    return fig


def create_heatmap_figure(combined, protocol_order):
    throughput_data = combined[combined["test_name"] == "throughput"]
    if throughput_data.empty:
        throughput_data = combined[combined["test_type"] == "single"]
    pivot = throughput_data.groupby(["protocol", "scenario"])["throughput"].median().reindex(protocol_order, level="protocol").unstack(fill_value=0)
    fig = go.Figure(data=[go.Heatmap(z=pivot.values, x=list(pivot.columns), y=list(pivot.index), colorscale="YlGnBu", colorbar_title="Median kbps", hovertemplate="Protocol=%{y}<br>Scenario=%{x}<br>Median throughput=%{z:.2f} kbps<extra></extra>")])
    fig.update_layout(template="plotly_white", title="Large-File Throughput Heatmap", height=480)
    return fig


def build_winner_table(combined, metric, ascending):
    grouped = combined.groupby(["scenario", "protocol"])[metric].median().reset_index()
    winners = grouped.sort_values(metric, ascending=ascending).groupby("scenario", as_index=False).first()
    winners["ranked_value"] = winners[metric].round(2)
    return winners.sort_values("scenario")


def generate_dashboard(config, combined=None):
    combined = combined if combined is not None else load_results(config)
    if combined is None or combined.empty:
        print("  Skipping dashboard generation because no results are available.")
        return None

    combined = combined.copy()
    combined["test_name"] = combined.apply(
        lambda row: "multi"
        if row["test_type"] == "multi"
        else ("handshake" if row["file"] == "1kb.txt" else "throughput" if row["file"] == "1mb.txt" else row["file"]),
        axis=1,
    )
    protocol_order = [proto for proto in ALL_PROTOCOLS if proto in set(combined["protocol"])]
    aggregated = combined.groupby(["scenario", "protocol", "test_name"], as_index=False)[["ttfb", "total_time", "throughput"]].median()

    summary_cards = {
        "Fastest Handshake": (aggregated[aggregated["test_name"] == "handshake"].sort_values("ttfb").head(1), "ttfb"),
        "Best 1 MB Throughput": (aggregated[aggregated["test_name"] == "throughput"].sort_values("throughput", ascending=False).head(1), "throughput"),
        "Fastest Multi-Object": (aggregated[aggregated["test_name"] == "multi"].sort_values("total_time").head(1), "total_time"),
    }
    cards_html = []
    for label, (frame, metric) in summary_cards.items():
        if frame.empty:
            continue
        row = frame.iloc[0]
        cards_html.append(
            f"<div class=\"card\"><div class=\"card-label\">{label}</div><div class=\"card-value\">{row['protocol']}</div><div class=\"card-meta\">{row['scenario']} · {_metric_label(metric)}: {row[metric]:.2f}</div></div>"
        )

    throughput_winners = build_winner_table(
        combined[combined["test_name"] == "throughput"], "throughput", ascending=False
    )
    multi_winners = build_winner_table(
        combined[combined["test_name"] == "multi"], "total_time", ascending=True
    )
    throughput_winners_table = throughput_winners[["scenario", "protocol", "ranked_value"]].rename(
        columns={"scenario": "Scenario", "protocol": "Winner", "ranked_value": "Median Throughput (kbps)"}
    ).to_html(index=False, classes="winners-table")
    multi_winners_table = multi_winners[["scenario", "protocol", "ranked_value"]].rename(
        columns={"scenario": "Scenario", "protocol": "Winner", "ranked_value": "Median Total Time (ms)"}
    ).to_html(index=False, classes="winners-table") if not multi_winners.empty else ""

    has_multi = not aggregated[aggregated["test_name"] == "multi"].empty
    overview_fig = create_overview_figure(aggregated, protocol_order)
    heatmap_fig = create_heatmap_figure(combined, protocol_order)
    distribution_fig = create_distribution_figure(combined, protocol_order)
    title = f"CS204 Demo Dashboard — {config.name}"
    html = f"""<!DOCTYPE html>
<html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"><title>{title}</title><style>:root{{--bg:#f5efe6;--panel:#fffaf3;--ink:#1f2933;--muted:#52606d;--accent:#c44536;--border:#eadfce;}}body{{margin:0;font-family:Georgia,\"Segoe UI\",serif;background:radial-gradient(circle at top left, rgba(196,69,54,.16), transparent 32%),radial-gradient(circle at top right, rgba(31,122,140,.14), transparent 28%),var(--bg);color:var(--ink);}}.shell{{max-width:1280px;margin:0 auto;padding:32px 20px 48px;}}.hero{{display:grid;gap:14px;margin-bottom:28px;}}.eyebrow{{text-transform:uppercase;letter-spacing:.12em;color:var(--accent);font-size:.8rem;font-weight:700;}}h1{{margin:0;font-size:clamp(2rem,4vw,3.4rem);line-height:1.02;}}.hero p{{margin:0;color:var(--muted);font-size:1.02rem;max-width:72ch;}}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px;margin:22px 0 30px;}}.card,.panel{{background:var(--panel);border:1px solid var(--border);border-radius:18px;box-shadow:0 10px 30px rgba(31,41,51,.06);}}.card{{padding:18px;}}.card-label{{color:var(--muted);font-size:.84rem;text-transform:uppercase;letter-spacing:.08em;margin-bottom:10px;}}.card-value{{font-size:1.3rem;font-weight:700;}}.card-meta{{margin-top:6px;color:var(--muted);font-size:.95rem;}}.grid{{display:grid;gap:18px;}}.panel{{padding:18px;}}.panel h2{{margin:0 0 8px;font-size:1.2rem;}}.panel p{{margin:0 0 14px;color:var(--muted);}}.two-up{{display:grid;grid-template-columns:2fr 1fr;gap:18px;}}.winners-table{{width:100%;border-collapse:collapse;}}.winners-table th,.winners-table td{{border-bottom:1px solid var(--border);text-align:left;padding:10px 8px;}}.winners-table th{{font-size:.84rem;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);}}@media (max-width:900px){{.two-up{{grid-template-columns:1fr;}}}}</style></head><body><div class=\"shell\"><section class=\"hero\"><div class=\"eyebrow\">CS204 Protocol Comparison</div><h1>Gopher vs HTTP, tuned for a live demo</h1><p>This dashboard uses the selected benchmark output from the <strong>{config.name}</strong> run. Use it before the live run to show the full pattern, then validate one claim on stage with the short preset.</p></section><section class=\"cards\">{''.join(cards_html)}</section><section class=\"grid\"><div class=\"panel\"><h2>Overview</h2><p>{'Handshake latency, large-file throughput, and multi-object total time are shown together for a complete live-demo summary.' if has_multi else 'Handshake latency and large-file throughput are shown together for a complete live-demo summary.'}</p>{overview_fig.to_html(full_html=False, include_plotlyjs='cdn')}</div><div class=\"two-up\"><div class=\"panel\"><h2>Heatmap</h2><p>This view makes it obvious which protocol wins the 1 MB transfer in each selected scenario.</p>{heatmap_fig.to_html(full_html=False, include_plotlyjs=False)}</div><div class=\"panel\"><h2>Demo Narrative</h2><p>Suggested order:</p><ol><li>Show the overview bars to explain the core trade-off.</li><li>Use the heatmap to point out the packet-loss or baseline winner.</li>{'<li>Use the multi-object winner table to discuss batching/waterfall behavior.</li>' if has_multi else ''}<li>Run the short preset and compare the fresh CSV output against this dashboard.</li></ol><h2>Throughput Winners</h2>{throughput_winners_table}{'<h2>Multi-Object Winners</h2>' + multi_winners_table if multi_winners_table else ''}</div></div><div class=\"panel\"><h2>Variance View</h2><p>Loss-heavy scenarios are noisy. This chart helps explain why medians matter more than single observations.</p>{distribution_fig.to_html(full_html=False, include_plotlyjs=False)}</div></section></div></body></html>"""

    suffix = f"_{config.output_suffix}" if config.output_suffix else ""
    dashboard_path = os.path.join(RESULTS_DIR, f"{os.path.splitext(DASHBOARD_FILENAME)[0]}{suffix}.html")
    with open(dashboard_path, "w", encoding="utf-8") as handle:
        handle.write(html)
    return dashboard_path


def run_suite(config, live=False):
    os.makedirs(RESULTS_DIR, exist_ok=True)
    content_dir = os.path.abspath("data/content")
    steps = planned_steps(config)
    total_steps = len(steps)

    on_result = None
    if live:
        try:
            from dashboard.live_server import emit_result
            on_result = emit_result
        except ImportError:
            print("  Warning: live dashboard not available (flask-socketio not installed)")

    print("=" * 64)
    print("  CS204 Protocol Benchmark Suite")
    print(f"  Preset: {config.name}")
    print(f"  Protocols: {' | '.join(config.protocols)}")
    print(f"  Scenarios: {' | '.join(config.scenarios)}")
    print(f"  Runs per test: {config.runs_per_test}  |  Multi files: {config.multi_file_count}  |  Tests: {' | '.join(config.tests)}")
    print(f"  Planned benchmark steps: {total_steps}")
    print("=" * 64)

    ensure_content()
    cert, key = ensure_certs()
    for output_file in available_output_files(config):
        if os.path.exists(output_file):
            os.remove(output_file)

    print("\n  Starting servers...")
    servers = start_servers(content_dir, cert, key)
    ensure_started(servers, "Server startup", delay=3.0)
    print("  Servers started.")

    step_idx = 0
    try:
        for scenario in selected_scenarios(config):
            name = scenario["name"]
            print(f"\n{'=' * 64}")
            print(f"  SCENARIO: {name}")
            print(f"  Latency: {scenario['latency']} ms   Packet Loss: {scenario['loss']}%   Bandwidth: {scenario.get('bandwidth', 0)} B/s")
            print(f"{'=' * 64}")
            print("  Starting proxies...")
            proxies = start_proxies(scenario, config.protocols)
            ensure_started(proxies, f"Proxy startup for {name}")
            print("  Proxies started.")

            output_file = output_filename_for(config, name)
            step_lock = threading.Lock()

            def run_protocol(protocol):
                nonlocal step_idx
                port = PORTS[protocol]["proxy"]
                runner = BenchmarkRunner(output_file, on_result=on_result)
                print(f"\n  --- {protocol} (via proxy :{port}) ---")
                for test_name in config.tests:
                    with step_lock:
                        step_idx += 1
                        current_step = step_idx
                    print(f"  Step {current_step}/{total_steps}: {name} | {protocol} | {test_name}")
                    execute_test(runner, protocol, port, test_name, config, name)
                runner.save()

            with concurrent.futures.ThreadPoolExecutor(max_workers=len(config.protocols)) as executor:
                futures = [executor.submit(run_protocol, proto) for proto in config.protocols]
                concurrent.futures.wait(futures)
                for f in futures:
                    f.result()  # raise any exceptions

            print(f"  Scenario complete: {name}")
            stop(proxies)
            time.sleep(1)
    finally:
        print("\n  Stopping servers...")
        stop(servers)

    print(f"\n{'=' * 64}")
    print("  Benchmarks complete — generating analysis")
    print(f"{'=' * 64}\n")
    analysis = analyze_results(config) if config.include_static_analysis else None
    dashboard = generate_dashboard(config, analysis["combined"] if analysis else None) if config.include_dashboard else None
    if dashboard:
        print(f"  Interactive dashboard saved to {dashboard}")


def parse_args():
    parser = argparse.ArgumentParser(description="Run the CS204 protocol benchmark suite")
    parser.add_argument("--preset", choices=sorted(PRESET_CONFIGS.keys()), default="full")
    parser.add_argument("--scenario", action="append", dest="scenarios")
    parser.add_argument("--protocol", action="append", dest="protocols")
    parser.add_argument("--test", action="append", dest="tests", choices=sorted(TEST_DEFINITIONS.keys()))
    parser.add_argument("--runs", type=int)
    parser.add_argument("--multi-count", type=int)
    parser.add_argument("--suffix")
    parser.add_argument("--incremental-save", action="store_true")
    parser.add_argument("--skip-analysis", action="store_true")
    parser.add_argument("--skip-dashboard", action="store_true")
    parser.add_argument("--dashboard-only", action="store_true")
    parser.add_argument("--live", action="store_true", help="Enable live dashboard updates")
    return parser.parse_args()


def validate_overrides(values, allowed, label):
    if not values:
        return None
    unknown = sorted(set(values) - set(allowed))
    if unknown:
        raise ValueError(f"Unknown {label}: {', '.join(unknown)}")
    return tuple(dict.fromkeys(values))


def build_config(args):
    config = PRESET_CONFIGS[args.preset]
    scenarios = validate_overrides(args.scenarios, SCENARIO_MAP.keys(), "scenarios")
    protocols = validate_overrides(args.protocols, ALL_PROTOCOLS, "protocols")
    tests = validate_overrides(args.tests, TEST_DEFINITIONS.keys(), "tests")
    return replace(config, scenarios=scenarios or config.scenarios, protocols=protocols or config.protocols, tests=tests or config.tests, runs_per_test=args.runs if args.runs is not None else config.runs_per_test, multi_file_count=args.multi_count if args.multi_count is not None else config.multi_file_count, output_suffix=args.suffix if args.suffix is not None else config.output_suffix, incremental_save=args.incremental_save or config.incremental_save, include_static_analysis=not args.skip_analysis and config.include_static_analysis, include_dashboard=not args.skip_dashboard and config.include_dashboard)


if __name__ == "__main__":
    options = parse_args()
    suite_config = build_config(options)
    if options.dashboard_only:
        print(f"  Dashboard-only mode for preset: {suite_config.name}")
        print("  Loading existing result files...")
        analysis = analyze_results(suite_config) if suite_config.include_static_analysis else None
        if suite_config.include_static_analysis:
            print("  Static analysis complete.")
        dashboard = generate_dashboard(suite_config, analysis["combined"] if analysis else None) if suite_config.include_dashboard else None
        if dashboard:
            print(f"  Interactive dashboard saved to {dashboard}")
    else:
        run_suite(suite_config, live=options.live)
