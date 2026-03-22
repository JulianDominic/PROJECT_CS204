# Gopher vs HTTP Protocol Comparison

This project compares the performance of Gopher and HTTP protocols under various network conditions.

## Project Structure

- `server/`: Server implementations
  - `gopher/gopher_server.py`: Python-based Gopher server
  - `http/http_server.py`: Flask-based HTTP server
  - `proxy.py`: Network condition simulator
- `client/`: Client implementations
  - `benchmark.py`: Unified benchmark client
- `data/content/`: Generated test content
- `run_test_suite.py`: Main orchestration script
- `generate_content.py`: Content generation utility

## Prerequisites

1. Python 3.10+
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Usage

### 1. Generate Content
Currently pre-generated, but you can regenerate:
```bash
python generate_content.py
```

### 2. Run Test Suite
This runs the full benchmark preset across all configured scenarios and generates CSV files, PNG charts, and an interactive HTML dashboard.
```bash
python run_test_suite.py
```

### 3. Run a Short Demo Preset
Use a preset when you want a fast live benchmark instead of the full study.

Preset summary:

| Preset | Scenarios | Protocols | Tests | Runs Per Test | Multi File Count | Typical Use |
|---|---|---|---|---:|---:|---|
| `full` | Baseline, High_Latency, Packet_Loss, Mixed | gopher-original, gopher-modern, http/1.1, http/2, http/3 | handshake, throughput, multi | 3 | 10 | Final report dataset |
| `demo_baseline` | Baseline | gopher-original, http/1.1, http/3 | handshake, multi | 1 | 5 | Fast low-risk live demo |
| `demo_packet_loss` | Packet_Loss | gopher-original, http/1.1, http/3 | handshake, throughput | 1 | 5 | Live packet-loss comparison |
| `demo_compare_all` | Baseline | gopher-original, gopher-modern, http/1.1, http/2, http/3 | handshake | 1 | 5 | Quick all-protocol handshake snapshot |

Test labels used by presets:

- `handshake`: single `1kb.txt` request (shows connection/setup and first-byte behavior)
- `throughput`: single `1mb.txt` request (shows large-transfer efficiency)
- `multi`: waterfall request of `small_*.txt` files (shows multi-object behavior)

Packet-loss demo for a short live run:
```bash
python run_test_suite.py --preset demo_packet_loss
```

What `demo_packet_loss` actually tests:

- Scenario: `Packet_Loss` (0 ms latency, 5% packet loss)
- Protocols: `gopher-original`, `http/1.1`, `http/3`
- Tests: `handshake` (`1kb.txt`) and `throughput` (`1mb.txt`)
- Repetitions: `1` run per test/protocol combination
- Output files include suffix `_demo_packet_loss`

Baseline demo with handshake + multi-object only:
```bash
python run_test_suite.py --preset demo_baseline
```

Compare all protocols on handshake only:
```bash
python run_test_suite.py --preset demo_compare_all
```

### 4. Override Specific Parts of a Run
You can narrow the run without editing the source file.

Example: one scenario, three protocols, two tests, one run:
```bash
python run_test_suite.py --preset full --scenario Packet_Loss --protocol gopher-original --protocol http/1.1 --protocol http/3 --test handshake --test throughput --runs 1
```

Example: create charts and dashboard from existing CSV files only:
```bash
python run_test_suite.py --preset demo_packet_loss --dashboard-only
```

### 5. Outputs
The suite now generates:

- Scenario CSV files in `results/`
- Summary statistics CSV in `results/`
- Static PNG charts in `results/`
- Interactive Plotly dashboard HTML in `results/`

The dashboard file is named `demo_dashboard*.html` and can be opened directly in a browser for a live presentation.

### 6. Manual Testing
You can run components individually:

**Start Gopher Server:**
```bash
python server/gopher/gopher_server.py --port 7070 --dir data/content
```

**Start HTTP Server:**
```bash
python server/http/http_server.py --port 8080 --dir data/content
```

**Start Proxy (e.g., for Gopher with 100ms latency):**
```bash
python server/proxy.py --target_host localhost --target_port 7070 --listen_port 7000 --latency 100
```

**Run Benchmark Client:**
```bash
python client/benchmark.py --host localhost --port 7000 --protocol gopher --file 1kb.txt
```


### 7. Remote Server Testing
A remote server has been set up, and can be tested by running the client testing suite on your own local machine.
```bash
python remote-clients.py
```
