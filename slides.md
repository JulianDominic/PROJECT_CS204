# CS204 — Gopher vs HTTP: Protocol Performance Under Adversity

---

<!-- Slide 1: Title -->
## Gopher vs HTTP
### A Five-Protocol Performance Comparison Under Simulated Network Conditions

**CS204 — Computer Networks**

Team Members: *(fill in)*
Date: February 2026

> *"Does protocol simplicity still matter in the age of HTTP/3?"*

---

<!-- Slide 2: The Problem -->
## The Problem

HTTP dominates the web — but at what cost?

| | Gopher (1991) | HTTP/1.1+ |
|---|---|---|
| Request | `filename\r\n` | `GET /file HTTP/1.1\r\nHost: …\r\nAccept: …\r\n…` |
| Response | Raw bytes | Status line + headers + body |
| Handshake | TCP 3-way | TCP 3-way (+TLS for HTTP/2, +QUIC for HTTP/3) |

**Research Question:** Under what network conditions does protocol simplicity outperform feature-richness — and when do HTTP's optimisations justify the overhead?

---

<!-- Slide 3: Central Message -->
## Central Message

> Gopher's minimal overhead delivers the **lowest latency** in every scenario
> — but HTTP/3's QUIC transport is the **only protocol that survives packet loss** for large transfers.
> Protocol choice is a **trade-off between simplicity and resilience**.

| Scenario | Winner (Small Files) | Winner (Large Files) |
|---|---|---|
| Baseline | Gopher-Modern | Gopher-Original ≈ HTTP/1.1 |
| High Latency | Gopher (lowest TTFB) | All TCP ≈ equal |
| Packet Loss | HTTP/1.1 | **HTTP/3 (10x faster)** |
| Mixed | Gopher (lowest TTFB) | Variable / high variance |

---

<!-- Slide 4: Methodology — Architecture -->
## Methodology: System Architecture

```
 ┌──────────┐         ┌──────────────────┐         ┌────────────────────────┐
 │  Client   │ ──────▶ │  TCP/UDP Proxy    │ ──────▶ │  Protocol Server       │
 │ benchmark │         │  (traffic shaper) │         │                        │
 │  .py      │         │                   │         │  • Gopher Original :7070│
 │           │ ◀────── │  Adds:            │ ◀────── │  • Gopher Modern  :7071│
 └──────────┘         │  - Latency        │         │  • HTTP/1.1       :8080│
                       │  - Packet loss    │         │  • HTTP/2 (TLS)   :8443│
                       │  - Bandwidth cap  │         │  • HTTP/3 (QUIC)  :4433│
                       └──────────────────┘         └────────────────────────┘
```

**Key Technical Detail:** We built two custom proxies:
- **TCP proxy** (`select`-based, non-blocking) — shapes Gopher & HTTP/1.1 & HTTP/2 traffic
- **UDP proxy** (threaded, non-blocking delayed sends) — shapes QUIC/HTTP/3 traffic

Both apply latency **per direction change** (not per chunk), accurately modelling real RTT behaviour.

---

<!-- Slide 5: Methodology — Protocols -->
## Five Protocols Tested

| Protocol | Transport | Connection Model | Key Characteristic |
|---|---|---|---|
| **Gopher-Original** | TCP | New connection per request | RFC 1436 — simplest possible |
| **Gopher-Modern** | TCP | Persistent (keep-alive) | Gopher + connection reuse |
| **HTTP/1.1** | TCP | Persistent (keep-alive) | Standard web protocol |
| **HTTP/2** | TCP + TLS | Multiplexed streams | Header compression (HPACK) |
| **HTTP/3** | QUIC (UDP) | Multiplexed, no HOL blocking | Per-stream loss recovery |

**Three test types per protocol:**
1. **Handshake Test** — single 1 KB file (connection-setup dominated)
2. **Throughput Test** — single 1 MB file (transfer dominated)
3. **Multi-Object Test** — 10 small files sequentially (connection reuse)

3 runs per test × 5 protocols × 4 scenarios = **180 measurements**

---

<!-- Slide 6: Methodology — Network Scenarios -->
## Four Network Scenarios

| Scenario | Added Latency | Packet Loss | Real-World Analogy |
|---|---|---|---|
| **Baseline** | 0 ms | 0% | Localhost / LAN |
| **High Latency** | 100 ms RTT | 0% | Satellite link / intercontinental |
| **Packet Loss** | 0 ms | 5% | Congested WiFi / lossy link |
| **Mixed** | 50 ms RTT | 2% | Typical mobile network |

Controlled via `run_test_suite.py` — fully automated orchestration that:
1. Starts all 5 servers
2. Spins up TCP + UDP proxies per scenario
3. Runs all benchmarks
4. Tears down and generates charts

---

<!-- Slide 7: Demo -->
## Live Demo / Recorded Video

**What you'll see:**
- `run_test_suite.py` executing the full benchmark suite
- Proxies being configured on-the-fly per scenario
- Real-time CSV output and chart generation

```
═══════════════════════════════════════════════════
  CS204 Protocol Benchmark Suite
  Original Gopher | Modern Gopher | HTTP/1.1 | HTTP/2 | HTTP/3
  Runs per test: 3  |  Multi files: 10
═══════════════════════════════════════════════════

  SCENARIO: Baseline
  Latency: 0 ms   Packet Loss: 0%
  --- gopher-original (via proxy :9070) ---
  [Handshake Test]  ✓
  [Throughput Test]  ✓
  [Multi-Object Test]  ✓
  ...
```

---

<!-- Slide 8: Results — Baseline -->
## Results: Baseline Performance

| Protocol | TTFB 1KB (median) | 1MB Throughput (median) | Multi-File Total (mean) |
|---|---|---|---|
| Gopher-Modern | **0.79 ms** | 1.40 MB/s | **2.4 ms** |
| Gopher-Original | 1.97 ms | **2.21 MB/s** | 8.6 ms |
| HTTP/1.1 | 2.42 ms | 2.07 MB/s | 17.3 ms |
| HTTP/2 | 3.42 ms | 0.39 MB/s | 14.2 ms |
| HTTP/3 | 1.14 ms | 0.06 MB/s | 109.0 ms |

### Key Observations
- **Gopher-Modern TTFB is 3× faster** than HTTP/1.1 — zero header overhead
- Gopher-Original & HTTP/1.1 are **nearly tied** on raw 1 MB throughput
- **HTTP/3 is 36× slower** than Gopher for 1 MB — QUIC stack overhead dominates on localhost
- HTTP/2's TLS handshake adds measurable TTFB cost even locally

📊 *See: `results/ttfb_Baseline.png`, `results/multi_Baseline.png`*

---

<!-- Slide 9: Results — High Latency -->
## Results: High Latency (100 ms added)

| Protocol | TTFB 1KB (median) | 1MB Throughput | Multi-File Total |
|---|---|---|---|
| Gopher-Modern | 209 ms | 37,903 B/s | 2,080 ms |
| Gopher-Original | 210 ms | 38,962 B/s | 2,095 ms |
| HTTP/1.1 | 215 ms | 38,566 B/s | 2,137 ms |
| **HTTP/2** | **426 ms** | 13,119 B/s | 2,329 ms |
| HTTP/3 | 212 ms* | 426 B/s | 1,976 ms |

### Key Observations
- All simple protocols converge to **~1 RTT** (≈210 ms) — as expected
- **HTTP/2 doubles TTFB to 426 ms** — extra round-trips for TLS negotiation + protocol upgrade
- HTTP/3's median TTFB looks OK (212 ms) but **mean is 583 ms** with std=651 ms — highly unstable
- HTTP/3 1 MB throughput collapses to **426 B/s** (vs 38,566 for HTTP/1.1) — 90× slower
- Multi-file: HTTP/3 is surprisingly competitive (1,976 ms) — QUIC's 0-RTT helps subsequent requests

---

<!-- Slide 10: Results — Packet Loss (The Revealing Scenario) -->
## Results: Packet Loss (5%) — The Most Revealing Scenario

| Protocol | 1KB TTFB (median) | 1MB Throughput (median) | Multi-File Total (median) |
|---|---|---|---|
| Gopher-Modern | 0.72 ms | 682 B/s | 906 ms |
| Gopher-Original | 776 ms | 1,128 B/s | 7.8 ms |
| HTTP/1.1 | 4.3 ms | 979 B/s | 19.5 ms |
| HTTP/2 | 404 ms | 1,298 B/s | 1,536 ms |
| **HTTP/3** | 210 ms | **10,683 B/s** | 119 ms |

### Why HTTP/3 Wins Here
TCP guarantees **in-order delivery** — one lost packet blocks ALL subsequent data (**head-of-line blocking**). QUIC (HTTP/3) runs over UDP with **per-stream loss recovery**: a lost packet in stream A doesn't block stream B.

| Factor | TCP (Gopher / HTTP/1.1 / HTTP/2) | QUIC (HTTP/3) |
|---|---|---|
| Lost packet blocks… | Entire connection | Only that one stream |
| Retransmission | Slow exponential backoff | Faster detection |
| Congestion response | Halves send rate | More granular |

**HTTP/3 achieves 10× the throughput** of any TCP protocol for 1 MB under 5% loss.

📊 *See: `results/ttfb_Packet_Loss.png`, `results/throughput_1mb.png`*

---

<!-- Slide 11: Results — Mixed -->
## Results: Mixed Conditions (50 ms latency + 2% loss)

| Protocol | TTFB 1KB (median) | 1MB Throughput (median) | Multi-File Total (mean) |
|---|---|---|---|
| Gopher-Modern | 112 ms | 3,946 B/s | 1,480 ms |
| Gopher-Original | 111 ms | 3,057 B/s | 1,246 ms |
| HTTP/1.1 | 117 ms | 3,608 B/s | 1,404 ms |
| HTTP/2 | 224 ms | 2,625 B/s | 1,598 ms |
| HTTP/3 | 523 ms | 587 B/s | 1,015 ms |

### Key Observations
- Gopher & HTTP/1.1: similar TTFB (~110-117 ms ≈ 1 RTT)
- **HTTP/2 again doubles TTFB** (224 ms) due to TLS handshake cost
- **HTTP/3 collapses** under combined conditions: TTFB 523 ms, 1 MB throughput only 587 B/s
- **Massive variance everywhere** — std ≈ mean for most TCP protocols, confirming unpredictable retransmission cascades
- HTTP/3's multi-file total (1,015 ms) is actually the **best** — QUIC's per-stream independence helps with many small transfers

---

<!-- Slide 12: Insights & Trade-offs -->
## Insights: The Simplicity vs Resilience Trade-off

### The 2×2 Matrix

|  | **Small Payloads (1 KB)** | **Large Payloads (1 MB)** |
|---|---|---|
| **Good Network** | ✅ Gopher wins (0.79 ms vs 2.42 ms TTFB) | ≈ Tied (Gopher-Original ≈ HTTP/1.1) |
| **Bad Network** | ≈ All similar (dominated by RTT) | ✅ **HTTP/3 wins under packet loss** (10× throughput) |

### Protocol Overhead Math
- HTTP/1.1 response headers for 1 KB file ≈ **~300 bytes** → **30% byte bloat**
- HTTP/1.1 response headers for 1 MB file ≈ **~300 bytes** → **0.03% byte bloat**
- Gopher: **0 bytes** overhead — always

### When to Use What
| Use Case | Best Protocol | Why |
|---|---|---|
| IoT / Embedded / Minimal | Gopher | Lowest overhead, fastest TTFB |
| General web | HTTP/1.1 | Good balance, wide compatibility |
| Multiplexed APIs | HTTP/2 | Stream multiplexing (but watch TLS cost) |
| Lossy networks, large files | HTTP/3 | QUIC's per-stream loss recovery |

---

<!-- Slide 13: Technical Deep Dive — Why These Results? -->
## Technical Deep Dive: Why These Results?

### Why HTTP/2 Always Has Higher TTFB
```
HTTP/1.1:  TCP SYN → SYN-ACK → GET → 200 OK     (1 RTT to data)
HTTP/2:    TCP SYN → SYN-ACK → TLS Hello → TLS Finish → HTTP/2 → Data  (2-3 RTTs)
```
Each extra round-trip adds ~100 ms under high latency → **doubles TTFB**.

### Why TCP-Based Protocols Collapse Under Packet Loss
1. **Head-of-line blocking** — ALL data stalls behind one lost packet
2. **Exponential backoff** — TCP waits 200ms → 400ms → 800ms per retransmission
3. **Congestion window collapse** — TCP interprets loss as congestion, halves send rate

### Why HTTP/3 (QUIC) Excels Under Packet Loss
- Runs over **UDP** with its own reliability layer
- **Per-stream recovery** — lost packet only blocks that stream
- **No congestion window collapse** on single loss
- This is exactly the problem QUIC was invented to solve (Google, 2012)

---

<!-- Slide 14: Conclusion & Limitations -->
## Conclusion

### Findings
1. **Gopher's simplicity = lowest latency** across all scenarios (0.79 ms TTFB baseline)
2. **Protocol complexity has measurable cost** — HTTP/2's TLS handshake doubles TTFB under latency
3. **QUIC is the only transport that handles packet loss well** for large transfers (10× throughput)
4. **HTTP/3 is counterproductive** in most other scenarios — QUIC overhead hurts small files and localhost
5. **No single protocol wins everywhere** — the choice depends on network conditions and payload size

### Limitations
- **Localhost testing** — real-world WAN conditions may differ
- **3 runs per test** — more runs would reduce variance (especially under packet loss)
- **Python implementations** — server performance is I/O-bound by Python, not the protocol itself
- **HTTP/3 via aioquic** — a production QUIC stack (e.g., Chromium's) may perform differently
- **No bandwidth throttling tested** — only latency and loss scenarios

### Hypothesis Verdict
> *"Gopher's minimal overhead should outperform HTTP in high-latency or low-bandwidth environments"*
>
> **Partially confirmed.** Gopher wins on TTFB everywhere, but HTTP/3's QUIC transport is uniquely resilient under packet loss — a scenario we didn't initially anticipate would diverge so dramatically.

---

<!-- Slide 15: Q&A -->
## Thank You — Questions?

**Repository:** `PROJECT_CS204`

### Likely Questions & Answers

**Q: Why build custom servers instead of using Apache/Nginx?**
A: We needed identical content paths, fine-grained timing control, and the ability to instrument TTFB measurement at the socket level.

**Q: How does the proxy simulate packet loss on TCP?**
A: Since we can't truly drop TCP packets (TCP guarantees delivery), our proxy **delays forwarding** random chunks by 200-1000 ms to mimic the throughput impact of TCP retransmission.

**Q: Why is HTTP/3 so slow on localhost?**
A: QUIC's benefits (0-RTT, per-stream recovery) require an actual network. On localhost with 0 ms RTT, the QUIC handshake and crypto overhead is pure cost with no latency to amortise.

**Q: Is Gopher actually used today?**
A: Yes — in the "small internet" community (gopher://gopherproject.org), IoT research, and as a teaching tool for understanding protocol design trade-offs.
