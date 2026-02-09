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
This will run all scenarios defined in `run_test_suite.py` and generate `results.csv` and `ttfb_comparison.png`.
```bash
python run_test_suite.py
```

### 3. Manual Testing
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
