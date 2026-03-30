# Gopher vs HTTP Protocol Comparison

Benchmarks 5 network protocols under 6 simulated network conditions to compare connection overhead, throughput, and resilience.

**Protocols:** Gopher-Original · Gopher-Modern · HTTP/1.1 · HTTP/2 · HTTP/3
**Scenarios:** Baseline · High Latency · Packet Loss · Mixed · Bandwidth Limited · Realistic WAN

## Quickstart (Docker — recommended)

```bash
# Launch the interactive dashboard
docker compose up
# Open http://localhost:8501 in your browser
```

From the dashboard you can select a preset, click **Run**, and watch results appear in real time.

```bash
# Or run tests directly from the command line
docker compose run benchmark python run_test_suite.py --preset demo_live
docker compose run benchmark python run_test_suite.py --preset full
```

Results are written to `results/` on your host via volume mount.

## Without Docker

```bash
pip install -r requirements.txt
streamlit run dashboard/app.py        # dashboard at http://localhost:8501
python run_test_suite.py --preset full
```

## Presets

| Preset | Scenarios | Protocols | Tests | Runs |
|---|---|---|---|---:|
| `full` | All 4 | All 5 | All 3 | 10 |
| `demo_live` | Baseline, Packet Loss, High Latency | All 5 | handshake, throughput, multi | 1 |
| `demo_baseline` | Baseline | gopher-original, http/1.1, http/3 | handshake, multi | 1 |
| `demo_packet_loss` | Packet Loss | gopher-original, http/1.1, http/3 | handshake, throughput | 1 |
| `demo_compare_all` | Baseline | All 5 | handshake | 1 |

```bash
python run_test_suite.py --preset demo_live
python run_test_suite.py --preset full
```

## Test Types

| Test | File | Purpose |
|---|---|---|
| `handshake` | 1 KB | Connection setup + TTFB |
| `throughput` | 1 MB | Bulk transfer speed |
| `multi` | 10 × small | Multi-object parallelism |

## Network Scenarios

| Scenario | Latency | Loss |
|---|---|---|
| Baseline | 0 ms | 0% |
| High Latency | 100 ms | 0% |
| Packet Loss | 0 ms | 5% |
| Mixed | 50 ms | 2% |

## Outputs

After a run, `results/` contains:
- Per-scenario CSV files with raw measurements
- `summary_statistics.csv` with medians/means/stddev per protocol × scenario × test
- PNG charts (TTFB, throughput, multi-object, scaling)
- Interactive `demo_dashboard.html` (open in browser)

## Diagnose Protocol Issues

```bash
python check_protocols.py
```

Starts each server, fetches a file, and reports `[OK]` or `[FAIL]` for all 5 protocols. Run this first if any protocol is not working.

## Manual Server Start

```bash
# Servers
python server/gopher/gopher_server.py --port 7070 --dir data/content
python server/gopher/gopher_modern_server.py --port 7071 --dir data/content
python server/http/http_server.py --port 8080 --dir data/content
python server/http/http2_server.py --port 8443 --certfile certs/cert.pem --keyfile certs/key.pem --dir data/content
python server/http/http3_server.py --port 4433 --certfile certs/cert.pem --keyfile certs/key.pem --dir data/content

# Network condition proxy (TCP)
python server/proxy.py --target_host localhost --target_port 7070 --listen_port 9070 --latency 100 --loss 5

# Network condition proxy (UDP — for HTTP/3)
python server/udp_proxy.py --target_host localhost --target_port 4433 --listen_port 9433 --latency 100 --loss 5

# Single benchmark run
python client/benchmark.py --host localhost --port 9070 --protocol gopher-original --file 1kb.txt
```

## Regenerate Test Content and Certificates

```bash
python generate_content.py
python certs/generate_certs.py
```
