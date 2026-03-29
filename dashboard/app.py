"""
Streamlit Dashboard for CS204 Protocol Benchmarks.

Launch with:
    streamlit run dashboard/app.py
"""

import glob
import os
import subprocess
import sys
import time

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS_DIR = os.path.join(PROJECT_ROOT, "results")
RUN_SCRIPT = os.path.join(PROJECT_ROOT, "run_test_suite.py")

# ---------------------------------------------------------------------------
# Constants (must match run_test_suite.py)
# ---------------------------------------------------------------------------
ALL_PROTOCOLS = [
    "gopher-original",
    "gopher-modern",
    "http/1.1",
    "http/2",
    "http/3",
]
ALL_SCENARIOS = [
    "Baseline",
    "High_Latency",
    "Packet_Loss",
    "Mixed",
    "Bandwidth_Limited",
    "Realistic_WAN",
]
ALL_TESTS = [
    "handshake",
    "throughput",
    "throughput_10kb",
    "throughput_100kb",
    "throughput_5mb",
    "multi",
    "multi_5",
    "multi_20",
]
PRESETS = ["demo_live", "demo_baseline", "demo_packet_loss", "demo_compare_all", "full"]

PALETTE = {
    "gopher-original": "#e74c3c",
    "gopher-modern": "#e67e22",
    "http/1.1": "#3498db",
    "http/2": "#2ecc71",
    "http/3": "#9b59b6",
}

# Ordered list so Plotly uses it consistently
PALETTE_ORDER = list(PALETTE.keys())
PALETTE_COLORS = list(PALETTE.values())

# Map file names to a sortable size value (bytes) for the scaling chart
FILE_SIZE_MAP = {
    "1kb.txt": 1_024,
    "10kb.txt": 10_240,
    "100kb.txt": 102_400,
    "1mb.txt": 1_048_576,
    "5mb.txt": 5_242_880,
}
FILE_SIZE_LABELS = {
    "1kb.txt": "1 KB",
    "10kb.txt": "10 KB",
    "100kb.txt": "100 KB",
    "1mb.txt": "1 MB",
    "5mb.txt": "5 MB",
}

# ---------------------------------------------------------------------------
# Page config & CSS
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="CS204 Protocol Benchmark",
    page_icon="\U0001f4e1",
    layout="wide",
)

st.markdown(
    """
    <style>
    [data-testid="stSidebar"] {
        background-color: #f5efe6;
    }
    [data-testid="stSidebar"] p,
    [data-testid="stSidebar"] span,
    [data-testid="stSidebar"] label,
    [data-testid="stSidebar"] h1,
    [data-testid="stSidebar"] h2,
    [data-testid="stSidebar"] h3 {
        color: #1f2933 !important;
    }
    [data-testid="stSidebar"] [data-baseweb="select"] * {
        color: inherit !important;
    }
    [data-testid="stSidebar"] button {
        color: #1f2933 !important;
        border: 1px solid #ccc !important;
    }
    [data-testid="stSidebar"] button:disabled {
        color: #999 !important;
        background-color: #e8e0d4 !important;
        border: 1px solid #ccc !important;
        opacity: 1 !important;
    }
    [data-testid="stSidebar"] button[kind="primary"] {
        color: white !important;
        background-color: #c44536 !important;
        border: none !important;
    }
    [data-testid="stSidebar"] button[kind="primary"]:disabled {
        color: white !important;
        background-color: #d4a09a !important;
        opacity: 1 !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------
if "process" not in st.session_state:
    st.session_state.process = None
if "running" not in st.session_state:
    st.session_state.running = False
if "stop_requested" not in st.session_state:
    st.session_state.stop_requested = False
if "status" not in st.session_state:
    st.session_state.status = "idle"
if "log_lines" not in st.session_state:
    st.session_state.log_lines = []
if "step_current" not in st.session_state:
    st.session_state.step_current = 0
if "step_total" not in st.session_state:
    st.session_state.step_total = 0
if "current_label" not in st.session_state:
    st.session_state.current_label = ""


if "log_queue" not in st.session_state:
    import queue
    st.session_state.log_queue = queue.Queue()
if "reader_thread" not in st.session_state:
    st.session_state.reader_thread = None


def _start_log_reader(proc):
    """Spawn a daemon thread that reads subprocess stdout into a queue."""
    import queue
    import threading

    q = st.session_state.log_queue

    def _reader():
        try:
            for line in iter(proc.stdout.readline, b""):
                q.put(line.decode("utf-8", errors="replace").rstrip())
        except Exception:
            pass

    t = threading.Thread(target=_reader, daemon=True)
    t.start()
    st.session_state.reader_thread = t


def _drain_log_queue():
    """Pull all pending lines from the reader queue into session state."""
    q = st.session_state.log_queue
    while not q.empty():
        try:
            line = q.get_nowait()
        except Exception:
            break
        if line:
            st.session_state.log_lines.append(line)
            if len(st.session_state.log_lines) > 200:
                st.session_state.log_lines = st.session_state.log_lines[-200:]
            # Parse progress from "Step X/Y:" lines
            if "Step " in line and "/" in line:
                try:
                    part = line.split("Step ")[1]
                    nums, rest = part.split(":", 1)
                    current, total = nums.strip().split("/")
                    st.session_state.step_current = int(current)
                    st.session_state.step_total = int(total)
                    st.session_state.current_label = rest.strip()
                except (ValueError, IndexError):
                    pass

# ---------------------------------------------------------------------------
# Helper: load all result CSVs
# ---------------------------------------------------------------------------

def load_results() -> pd.DataFrame:
    """Read every results_*.csv in the results directory and return a combined DataFrame."""
    pattern = os.path.join(RESULTS_DIR, "results_*.csv")
    files = glob.glob(pattern)
    if not files:
        return pd.DataFrame()
    frames = []
    for f in files:
        try:
            df = pd.read_csv(f)
            if not df.empty:
                frames.append(df)
        except Exception:
            continue
    if not frames:
        return pd.DataFrame()
    combined = pd.concat(frames, ignore_index=True)
    # Normalise protocol names to lowercase for palette matching
    if "protocol" in combined.columns:
        combined["protocol"] = combined["protocol"].str.lower().str.strip()
    return combined


def _color_sequence(protocols):
    """Return a colour list matching the protocol order."""
    return [PALETTE.get(p, "#888888") for p in protocols]


# ---------------------------------------------------------------------------
# Sidebar: Test controls
# ---------------------------------------------------------------------------
st.sidebar.title("Test Controls")

mode = st.sidebar.radio("Configuration mode", ["Preset", "Manual"], horizontal=True)

if mode == "Preset":
    preset = st.sidebar.selectbox("Preset", PRESETS, index=0)
    cmd_args = ["--preset", preset, "--incremental-save"]
else:
    sel_scenarios = st.sidebar.multiselect("Scenarios", ALL_SCENARIOS, default=["Baseline"])
    sel_protocols = st.sidebar.multiselect("Protocols", ALL_PROTOCOLS, default=ALL_PROTOCOLS)
    sel_tests = st.sidebar.multiselect("Test types", ALL_TESTS, default=["handshake", "throughput", "multi"])
    sel_runs = st.sidebar.number_input("Runs per test", min_value=1, max_value=10, value=1)
    cmd_args = ["--incremental-save"]
    for s in sel_scenarios:
        cmd_args += ["--scenario", s]
    for p in sel_protocols:
        cmd_args += ["--protocol", p]
    for t in sel_tests:
        cmd_args += ["--test", t]
    cmd_args += ["--runs", str(sel_runs)]

st.sidebar.markdown("---")

col_run, col_stop = st.sidebar.columns(2)

run_clicked = col_run.button(
    "Run Benchmark",
    disabled=st.session_state.running,
    type="primary",
    use_container_width=True,
)

stop_clicked = col_stop.button(
    "Stop",
    disabled=not st.session_state.running,
    use_container_width=True,
)

# Status indicator
status_label = st.session_state.status.upper()
status_colors = {"idle": "\U0001f7e1", "running": "\U0001f7e2", "complete": "\u2705", "stopped": "\U0001f534"}
st.sidebar.markdown(f"**Status:** {status_colors.get(st.session_state.status, '')} {status_label}")

# ---------------------------------------------------------------------------
# Handle button clicks
# ---------------------------------------------------------------------------

if run_clicked:
    full_cmd = [sys.executable, RUN_SCRIPT] + cmd_args
    st.session_state.log_lines = []
    st.session_state.step_current = 0
    st.session_state.step_total = 0
    st.session_state.current_label = ""
    # Clear the queue
    while not st.session_state.log_queue.empty():
        try:
            st.session_state.log_queue.get_nowait()
        except Exception:
            break
    proc = subprocess.Popen(
        full_cmd,
        cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    st.session_state.process = proc
    _start_log_reader(proc)
    st.session_state.running = True
    st.session_state.stop_requested = False
    st.session_state.status = "running"
    st.rerun()

if stop_clicked and st.session_state.process is not None:
    st.session_state.stop_requested = True
    try:
        st.session_state.process.terminate()
    except Exception:
        pass
    st.session_state.running = False
    st.session_state.process = None
    st.session_state.status = "stopped"
    st.rerun()

# Check if process finished + drain logs
if st.session_state.running and st.session_state.process is not None:
    _drain_log_queue()
    ret = st.session_state.process.poll()
    if ret is not None:
        _drain_log_queue()  # final drain
        st.session_state.running = False
        st.session_state.process = None
        st.session_state.reader_thread = None
        st.session_state.status = "complete"
elif not st.session_state.running:
    _drain_log_queue()  # drain any remaining

# ---------------------------------------------------------------------------
# Main area
# ---------------------------------------------------------------------------
st.title("CS204 Protocol Benchmark Dashboard")

# Progress bar + current step + live log
if st.session_state.running or st.session_state.log_lines:
    if st.session_state.step_total > 0:
        progress = st.session_state.step_current / st.session_state.step_total
        st.progress(progress, text=f"Step {st.session_state.step_current}/{st.session_state.step_total}")
    if st.session_state.current_label:
        st.caption(f"Current: **{st.session_state.current_label}**")
    if st.session_state.running:
        st.info("Benchmark is running. Results update automatically every 2 seconds.")
    with st.expander("Live Log", expanded=st.session_state.running):
        log_text = "\n".join(st.session_state.log_lines[-100:])
        st.markdown(
            f'<div style="height:250px; overflow-y:auto; background:#1e1e1e; color:#d4d4d4; '
            f'font-family:monospace; font-size:13px; padding:12px; border-radius:8px; '
            f'white-space:pre-wrap; word-break:break-all;">{log_text}</div>',
            unsafe_allow_html=True,
        )

# Load data
df = load_results()

if df.empty:
    st.markdown(
        """
        ### Welcome!

        No benchmark results found yet. Use the sidebar to configure and run a benchmark,
        or place CSV result files in the `results/` directory.

        **Quick start:**
        1. Select a preset (e.g. *demo_live*) in the sidebar.
        2. Click **Run Benchmark**.
        3. Watch the charts populate in real time!
        """
    )
else:
    # Show row count as a simple progress indicator
    st.caption(f"Loaded **{len(df)}** result rows from {len(glob.glob(os.path.join(RESULTS_DIR, 'results_*.csv')))} file(s).")

    # ------------------------------------------------------------------
    # Tabs
    # ------------------------------------------------------------------
    tab_overview, tab_scaling, tab_raw = st.tabs(["Overview", "Scaling", "Raw Data"])

    # ==================================================================
    # TAB 1: Overview
    # ==================================================================
    with tab_overview:
        # --- TTFB by scenario (handshake / 1kb.txt) ---
        ttfb_df = df[df["file"].str.contains("1kb", case=False, na=False)].copy()
        if not ttfb_df.empty:
            ttfb_med = (
                ttfb_df.groupby(["scenario", "protocol"], as_index=False)["ttfb"]
                .median()
            )
            fig_ttfb = px.bar(
                ttfb_med,
                x="scenario",
                y="ttfb",
                color="protocol",
                barmode="group",
                title="TTFB by Scenario (Handshake / 1 KB)",
                labels={"ttfb": "TTFB (ms)", "scenario": "Scenario"},
                color_discrete_map=PALETTE,
                category_orders={"protocol": PALETTE_ORDER},
            )
            fig_ttfb.update_layout(legend_title_text="Protocol")
            st.plotly_chart(fig_ttfb, use_container_width=True)
        else:
            st.info("No handshake (1 KB) results available yet for the TTFB chart.")

        # --- Throughput by scenario (1mb.txt) ---
        tp_df = df[df["file"].str.contains("1mb", case=False, na=False)].copy()
        if not tp_df.empty:
            tp_med = (
                tp_df.groupby(["scenario", "protocol"], as_index=False)["throughput"]
                .median()
            )
            fig_tp = px.bar(
                tp_med,
                x="scenario",
                y="throughput",
                color="protocol",
                barmode="group",
                title="Throughput by Scenario (1 MB file)",
                labels={"throughput": "Throughput (bytes/s)", "scenario": "Scenario"},
                color_discrete_map=PALETTE,
                category_orders={"protocol": PALETTE_ORDER},
            )
            fig_tp.update_layout(legend_title_text="Protocol")
            st.plotly_chart(fig_tp, use_container_width=True)
        else:
            st.info("No throughput (1 MB) results available yet.")

        # --- Multi-Object total time by scenario ---
        multi_df = df[df["test_type"].str.contains("multi", case=False, na=False)].copy()
        if not multi_df.empty:
            multi_med = (
                multi_df.groupby(["scenario", "protocol"], as_index=False)["total_time"]
                .median()
            )
            fig_multi = px.bar(
                multi_med,
                x="scenario",
                y="total_time",
                color="protocol",
                barmode="group",
                title="Multi-Object Total Time by Scenario",
                labels={"total_time": "Total Time (ms)", "scenario": "Scenario"},
                color_discrete_map=PALETTE,
                category_orders={"protocol": PALETTE_ORDER},
            )
            fig_multi.update_layout(legend_title_text="Protocol")
            st.plotly_chart(fig_multi, use_container_width=True)
        else:
            st.info("No multi-object results available yet.")

        # --- Winner cards ---
        st.subheader("Best Protocol per Category")
        card_cols = st.columns(3)

        if not ttfb_df.empty:
            best_ttfb = ttfb_med.loc[ttfb_med["ttfb"].idxmin()]
            card_cols[0].metric(
                label="Lowest TTFB",
                value=best_ttfb["protocol"],
                delta=f"{best_ttfb['ttfb']:.2f} ms",
                delta_color="inverse",
            )
        else:
            card_cols[0].metric(label="Lowest TTFB", value="N/A")

        if not tp_df.empty:
            best_tp = tp_med.loc[tp_med["throughput"].idxmax()]
            card_cols[1].metric(
                label="Highest Throughput",
                value=best_tp["protocol"],
                delta=f"{best_tp['throughput']:,.0f} B/s",
            )
        else:
            card_cols[1].metric(label="Highest Throughput", value="N/A")

        if not multi_df.empty:
            best_multi = multi_med.loc[multi_med["total_time"].idxmin()]
            card_cols[2].metric(
                label="Fastest Multi-Object",
                value=best_multi["protocol"],
                delta=f"{best_multi['total_time']:.2f} ms",
                delta_color="inverse",
            )
        else:
            card_cols[2].metric(label="Fastest Multi-Object", value="N/A")

    # ==================================================================
    # TAB 2: Scaling
    # ==================================================================
    with tab_scaling:
        # --- Throughput vs File Size ---
        single_df = df[df["test_type"] == "single"].copy()
        known_files = list(FILE_SIZE_MAP.keys())
        scaling_df = single_df[single_df["file"].isin(known_files)].copy()

        if not scaling_df.empty:
            scaling_df["file_bytes"] = scaling_df["file"].map(FILE_SIZE_MAP)
            scaling_df["file_label"] = scaling_df["file"].map(FILE_SIZE_LABELS)
            scaling_med = (
                scaling_df.groupby(["file_bytes", "file_label", "protocol"], as_index=False)["throughput"]
                .median()
                .sort_values("file_bytes")
            )
            fig_scale = px.line(
                scaling_med,
                x="file_label",
                y="throughput",
                color="protocol",
                markers=True,
                title="Throughput vs File Size",
                labels={"throughput": "Throughput (bytes/s)", "file_label": "File Size"},
                color_discrete_map=PALETTE,
                category_orders={
                    "protocol": PALETTE_ORDER,
                    "file_label": [FILE_SIZE_LABELS[k] for k in known_files],
                },
            )
            fig_scale.update_layout(legend_title_text="Protocol")
            st.plotly_chart(fig_scale, use_container_width=True)
        else:
            st.info("No single-file results with varying sizes available yet for the scaling chart.")

        # --- Multi-Object Scaling (file count vs total_time) ---
        if not multi_df.empty and "num_files" in multi_df.columns:
            mo_scale = multi_df.copy()
            mo_scale["num_files"] = pd.to_numeric(mo_scale["num_files"], errors="coerce")
            mo_scale = mo_scale.dropna(subset=["num_files"])
            if not mo_scale.empty:
                mo_med = (
                    mo_scale.groupby(["num_files", "protocol"], as_index=False)["total_time"]
                    .median()
                    .sort_values("num_files")
                )
                fig_mo = px.line(
                    mo_med,
                    x="num_files",
                    y="total_time",
                    color="protocol",
                    markers=True,
                    title="Multi-Object Scaling (File Count vs Total Time)",
                    labels={"total_time": "Total Time (ms)", "num_files": "Number of Files"},
                    color_discrete_map=PALETTE,
                    category_orders={"protocol": PALETTE_ORDER},
                )
                fig_mo.update_layout(legend_title_text="Protocol")
                st.plotly_chart(fig_mo, use_container_width=True)
            else:
                st.info("No multi-object scaling data available yet.")
        else:
            st.info("No multi-object results available yet for the scaling chart.")

    # ==================================================================
    # TAB 3: Raw Data
    # ==================================================================
    with tab_raw:
        st.dataframe(
            df.sort_values(by=["scenario", "protocol", "test_type", "file"] if {"scenario", "protocol", "test_type", "file"}.issubset(df.columns) else df.columns[:1].tolist()),
            use_container_width=True,
            height=600,
        )

# ---------------------------------------------------------------------------
# Auto-refresh while benchmark is running
# ---------------------------------------------------------------------------
if st.session_state.running:
    time.sleep(2)
    st.rerun()
