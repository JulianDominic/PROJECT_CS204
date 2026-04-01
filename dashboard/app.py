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
    "multi",
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
        color: white !important;
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
        import html as _html
        log_id = "live-log-box"
        escaped = _html.escape("\n".join(st.session_state.log_lines))
        st.markdown(
            f'<div id="{log_id}" style="height:280px; overflow-y:auto; background:#1e1e1e; color:#d4d4d4; '
            f'font-family:monospace; font-size:12px; padding:12px; border-radius:8px; '
            f'white-space:pre-wrap; word-break:break-all;">{escaped}</div>'
            f'<script>var el=document.getElementById("{log_id}");if(el)el.scrollTop=el.scrollHeight;</script>',
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
    tab_overview, tab_winners, tab_hypotheses, tab_raw = st.tabs(["Overview", "Winners", "Hypotheses", "Raw Data"])

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

    # ==================================================================
    # TAB 2: Winners
    # ==================================================================
    with tab_winners:
        st.subheader("Best Protocol per Test × Scenario")

        winner_tests = [
            ("Handshake (TTFB)", ttfb_df, "ttfb", "min", "{:.2f} ms"),
            ("Throughput 1 MB", tp_df, "throughput", "max", "{:,.0f} kbps"),
            ("Multi-Object", multi_df, "total_time", "min", "{:.2f} ms"),
        ]

        cards_html = []
        for test_label, test_df, metric, best_fn, fmt in winner_tests:
            if test_df.empty:
                continue
            scenario_values = [str(s).strip() for s in test_df["scenario"].dropna().unique()]
            preferred_order = [s for s in ALL_SCENARIOS if s in scenario_values]
            extra_scenarios = sorted([s for s in scenario_values if s not in preferred_order])
            scenarios_present = preferred_order + extra_scenarios
            if not scenarios_present:
                continue
            med = test_df.groupby(["scenario", "protocol"])[metric].median()

            cells = ""
            for scenario in scenarios_present:
                label = scenario.replace("_", " ")
                if scenario not in med.index.get_level_values("scenario"):
                    cells += (
                        f"<div style='flex:1;min-width:100px;padding:12px 14px;"
                        f"border-left:1px solid #333'>"
                        f"<div style='font-size:0.75em;color:#888;margin-bottom:6px'>{label}</div>"
                        f"<div style='font-size:1em;font-weight:bold'>N/A</div></div>"
                    )
                else:
                    scenario_data = med[scenario]
                    winner_proto = scenario_data.idxmin() if best_fn == "min" else scenario_data.idxmax()
                    winner_val = scenario_data[winner_proto]
                    cells += (
                        f"<div style='flex:1;min-width:100px;padding:12px 14px;"
                        f"border-left:1px solid #333'>"
                        f"<div style='font-size:0.75em;color:#888;margin-bottom:6px'>{label}</div>"
                        f"<div style='font-size:1.05em;font-weight:bold;margin-bottom:8px'>{winner_proto}</div>"
                        f"<span style='background:#1a7a3f;color:#fff;padding:2px 8px;"
                        f"border-radius:12px;font-size:0.75em'>{fmt.format(winner_val)}</span>"
                        f"</div>"
                    )

            cards_html.append(
                f"<div style='border:1px solid #444;border-radius:8px;margin-bottom:16px;overflow:hidden'>"
                f"<div style='padding:10px 14px;background:#1e2530;font-weight:bold;font-size:0.95em'>{test_label}</div>"
                f"<div style='display:flex;flex-wrap:wrap'>{cells}</div>"
                f"</div>"
            )

        st.markdown("".join(cards_html), unsafe_allow_html=True)

    # ==================================================================
    # TAB 3: Hypotheses
    # ==================================================================
    with tab_hypotheses:
        st.subheader("Hypotheses vs Actual Results")
        st.caption("Each hypothesis is checked against collected data. Verdicts update as more data is added.")

        # --- helper: safe median lookup ---
        def _med(frame, scenario, protocol, metric):
            if frame.empty:
                return None
            try:
                g = frame[
                    (frame["scenario"] == scenario) & (frame["protocol"] == protocol)
                ][metric].median()
                return float(g) if pd.notna(g) else None
            except Exception:
                return None

        def _winner(frame, scenario, metric, fn):
            """Return (protocol, value) for best protocol in a scenario."""
            if frame.empty:
                return None, None
            try:
                g = frame[frame["scenario"] == scenario].groupby("protocol")[metric].median()
                if g.empty:
                    return None, None
                proto = g.idxmin() if fn == "min" else g.idxmax()
                return proto, float(g[proto])
            except Exception:
                return None, None

        VERDICT_STYLE = {
            "Supported":          ("background:#1a7a3f;color:#fff", "Supported"),
            "Strongly Supported": ("background:#155e2e;color:#fff", "Strongly Supported"),
            "Partially Supported":("background:#7a5a1a;color:#fff", "Partially Supported"),
            "Refuted":            ("background:#7a1a1a;color:#fff", "Refuted"),
            "No Data":            ("background:#444;color:#aaa",    "No Data"),
        }

        def _badge(verdict):
            style, label = VERDICT_STYLE.get(verdict, VERDICT_STYLE["No Data"])
            return f"<span style='{style};padding:3px 12px;border-radius:12px;font-size:0.8em;font-weight:bold'>{label}</span>"

        def _card(number, title, rationale, expected, actual_html, verdict):
            return (
                f"<div style='border:1px solid #444;border-radius:8px;margin-bottom:14px;overflow:hidden'>"
                f"<div style='background:#1e2530;padding:10px 16px;display:flex;align-items:center;gap:12px'>"
                f"<span style='font-size:0.85em;color:#888;font-weight:bold'>{number}</span>"
                f"<span style='font-weight:bold;font-size:1em;flex:1'>{title}</span>"
                f"{_badge(verdict)}"
                f"</div>"
                f"<div style='padding:14px 16px;display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px'>"
                f"<div><div style='font-size:0.75em;color:#888;margin-bottom:4px'>RATIONALE</div>"
                f"<div style='font-size:0.85em'>{rationale}</div></div>"
                f"<div><div style='font-size:0.75em;color:#888;margin-bottom:4px'>EXPECTED</div>"
                f"<div style='font-size:0.85em'>{expected}</div></div>"
                f"<div><div style='font-size:0.75em;color:#888;margin-bottom:4px'>ACTUAL (from data)</div>"
                f"<div style='font-size:0.85em'>{actual_html}</div></div>"
                f"</div>"
                f"</div>"
            )

        cards = []

        # H1 — Simpler protocols have lower TTFB on baseline
        h1_winner, h1_val = _winner(ttfb_df, "Baseline", "ttfb", "min")
        if h1_winner is None:
            h1_actual = "No data"
            h1_verdict = "No Data"
        else:
            h1_actual = f"Winner: <b>{h1_winner}</b> ({h1_val:.2f} ms TTFB)"
            h1_verdict = "Supported" if h1_winner in ("gopher-modern", "gopher-original") else "Partially Supported"
        cards.append(_card(
            "H1", "Simpler protocols have lower TTFB under ideal conditions",
            "Gopher has no TLS, no headers, no content negotiation — fewer bytes before first data byte.",
            "Gopher-modern wins on Baseline TTFB",
            h1_actual, h1_verdict,
        ))

        # H2 — HTTP/1.1 highest throughput on baseline 1MB
        h2_winner, h2_val = _winner(tp_df, "Baseline", "throughput", "max")
        if h2_winner is None:
            h2_actual = "No data"
            h2_verdict = "No Data"
        else:
            h2_actual = f"Winner: <b>{h2_winner}</b> ({h2_val:,.0f} kbps)"
            h2_verdict = "Supported" if h2_winner == "http/1.1" else "Refuted"
        cards.append(_card(
            "H2", "HTTP/1.1 achieves the highest throughput for large single-file transfers",
            "Decades of kernel-level TCP optimisation (sendfile, TSO/GRO) vs QUIC userspace overhead.",
            "HTTP/1.1 wins on Baseline 1 MB throughput",
            h2_actual, h2_verdict,
        ))

        # H3 — HTTP/2 most penalised by latency (highest TTFB in High_Latency)
        h3_winner_low, _ = _winner(ttfb_df, "Baseline", "ttfb", "min")
        h3_worst, h3_worst_val = _winner(ttfb_df, "High_Latency", "ttfb", "max")
        if h3_worst is None:
            h3_actual = "No data"
            h3_verdict = "No Data"
        else:
            # compare multiplier: HTTP/2 baseline vs high latency
            h3_base = _med(ttfb_df, "Baseline", "http/2", "ttfb")
            h3_hl   = _med(ttfb_df, "High_Latency", "http/2", "ttfb")
            if h3_base and h3_hl:
                mult = h3_hl / h3_base
                h3_actual = f"HTTP/2 High_Latency TTFB: <b>{h3_hl:.0f} ms</b> ({mult:.1f}× baseline). Worst: <b>{h3_worst}</b>"
            else:
                h3_actual = f"Worst under high latency: <b>{h3_worst}</b> ({h3_worst_val:.0f} ms)"
            h3_verdict = "Strongly Supported" if h3_worst == "http/2" else "Refuted"
        cards.append(_card(
            "H3", "HTTP/2 is most penalised by high latency due to extra TLS round trips",
            "HTTP/2 needs TCP handshake + TLS/ALPN = 2 RTTs before any data, vs 1 RTT for others.",
            "HTTP/2 has highest TTFB under High_Latency; ~4× more than Baseline",
            h3_actual, h3_verdict,
        ))

        # H4 — HTTP/3 most resilient to packet loss (multi-file)
        h4_winner, h4_val = _winner(multi_df, "Packet_Loss", "total_time", "min")
        if h4_winner is None:
            h4_actual = "No data"
            h4_verdict = "No Data"
        else:
            h4_actual = f"Winner: <b>{h4_winner}</b> ({h4_val:.0f} ms total for multi-file)"
            h4_verdict = "Strongly Supported" if h4_winner == "http/3" else "Refuted"
        cards.append(_card(
            "H4", "HTTP/3 (QUIC) is the most resilient protocol under packet loss",
            "QUIC eliminates TCP head-of-line blocking — a lost packet on one stream doesn't stall others.",
            "HTTP/3 wins multi-object total time under Packet_Loss",
            h4_actual, h4_verdict,
        ))

        # H5 — Gopher-original worst at multi-file baseline
        h5_worst, h5_val = _winner(multi_df, "Baseline", "total_time", "max")
        h5_go = _med(multi_df, "Baseline", "gopher-original", "total_time")
        h5_gm = _med(multi_df, "Baseline", "gopher-modern",   "total_time")
        if h5_worst is None:
            h5_actual = "No data"
            h5_verdict = "No Data"
        else:
            if h5_go and h5_gm:
                h5_actual = (
                    f"Gopher-original: <b>{h5_go:.1f} ms</b> vs Gopher-modern: <b>{h5_gm:.1f} ms</b>. "
                    f"Slowest overall: <b>{h5_worst}</b>"
                )
            else:
                h5_actual = f"Slowest: <b>{h5_worst}</b> ({h5_val:.1f} ms)"
            h5_verdict = "Partially Supported" if (h5_go and h5_gm and h5_go > h5_gm) else ("Refuted" if h5_go and h5_gm else "No Data")
        cards.append(_card(
            "H5", "Gopher-original performs worst on multi-file tests due to connection-per-request overhead",
            "RFC 1436 Gopher closes TCP after every response — 10 files = 10 TCP handshakes + Slow Start.",
            "Gopher-original slowest in Baseline multi-file; faster than HTTP in some adverse conditions",
            h5_actual, h5_verdict,
        ))

        # H6 — Gopher-modern faster than Gopher-original on multi baseline
        h6_go = _med(multi_df, "Baseline", "gopher-original", "total_time")
        h6_gm = _med(multi_df, "Baseline", "gopher-modern",   "total_time")
        if h6_go is None or h6_gm is None:
            h6_actual = "No data"
            h6_verdict = "No Data"
        else:
            speedup = h6_go / h6_gm if h6_gm > 0 else 0
            h6_actual = f"Gopher-modern: <b>{h6_gm:.1f} ms</b>, Gopher-original: <b>{h6_go:.1f} ms</b> → <b>{speedup:.1f}× speedup</b>"
            h6_verdict = "Supported" if speedup >= 1.5 else ("Partially Supported" if speedup > 1.0 else "Refuted")
        cards.append(_card(
            "H6", "Persistent connections (Gopher-modern) significantly outperform Gopher-original on multi-file",
            "One TCP connection shared across all requests eliminates repeated handshake and Slow Start.",
            "Gopher-modern ≥2× faster than Gopher-original under Baseline multi-file",
            h6_actual, h6_verdict,
        ))

        st.markdown("".join(cards), unsafe_allow_html=True)

    # ==================================================================
    # TAB 4: Raw Data
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
