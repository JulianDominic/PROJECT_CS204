# Product Requirements Document (PRD)
## Gopher vs HTTP Protocol Performance Comparison

---

## 1. Executive Summary

This project conducts a **systematic performance comparison** between the Gopher protocol and HTTP under various network conditions. The goal is to determine the trade-offs between protocol simplicity (Gopher) and feature richness (HTTP), providing evidence-based recommendations for protocol selection in different use cases.

---

## 2. Problem Statement

### 2.1 Background
- **Gopher**: A lightweight, text-based protocol from 1991, designed for simplicity
- **HTTP**: The dominant web protocol, feature-rich but with more overhead

### 2.2 Research Questions
1. How does Gopher compare to HTTP in terms of **speed and overhead** under identical conditions?
2. Under what network conditions (latency, packet loss, bandwidth) does each protocol perform better?
3. What are the **practical trade-offs** between protocol simplicity and functionality?

### 2.3 Hypothesis
Gopher's minimal overhead should outperform HTTP in high-latency or low-bandwidth environments, while HTTP's optimizations may prove superior in stable network conditions.

---

## 3. Goals & Success Criteria

### 3.1 Primary Goals
| Goal | Success Metric |
|------|----------------|
| Measure performance difference | Quantified TTFB and transfer time comparison |
| Identify optimal use cases | Clear recommendations per network condition |
| Demonstrate findings | Visualizations and live demo |

### 3.2 Rubrics Alignment

| Rubric Category | Weight | How We Address It |
|-----------------|--------|-------------------|
| **Presentation - Inquiry** | 20% | Evidence-based research, data interpretation |
| **Presentation - Central Message** | 20% | Clear "which protocol for which scenario" takeaway |
| **Presentation - Organisation** | 20% | Logical flow from problem → method → results → conclusion |
| **Presentation - Visual Aids** | 20% | Charts, graphs, live demo |
| **Presentation Requirements** | 10% | Clear problem statement + methodology |
| **Presentation Technical Details** | 10% | Protocol analysis + performance insights |
| **Report** | 10% | Context, content, citations, project management |

---

## 4. Scope

### 4.1 In Scope
- Gopher protocol (RFC 1436) performance testing
- HTTP/1.1 performance testing
- Network condition simulation (latency, packet loss, bandwidth)
- Metrics: TTFB, total transfer time, bytes transferred, throughput
- Python-based implementation
- Statistical analysis and visualization
- Written report and presentation

### 4.2 Out of Scope
- HTTP/2 or HTTP/3 comparison (future work)
- Security analysis (TLS overhead)
- Real-world deployment testing
- Mobile network testing

---

## 5. Functional Requirements

### 5.1 Server Requirements

| ID | Requirement | Priority |
|----|-------------|----------|
| SR-1 | Gopher server must serve identical content as HTTP server | Must Have |
| SR-2 | Both servers must run on same hardware/VM | Must Have |
| SR-3 | Servers must log request timestamps | Should Have |
| SR-4 | Content must include text files of varying sizes (1KB, 10KB, 100KB) | Must Have |

### 5.2 Client Requirements

| ID | Requirement | Priority |
|----|-------------|----------|
| CR-1 | Gopher client must measure TTFB accurately | Must Have |
| CR-2 | HTTP client must measure TTFB accurately | Must Have |
| CR-3 | Clients must log all metrics to persistent storage | Must Have |
| CR-4 | Clients must support automated batch testing | Should Have |
| CR-5 | Clients must handle connection failures gracefully | Should Have |

### 5.3 Testing Requirements

| ID | Requirement | Priority |
|----|-------------|----------|
| TR-1 | Simulate latency: 0ms, 50ms, 100ms, 200ms | Must Have |
| TR-2 | Simulate packet loss: 0%, 1%, 5%, 10% | Must Have |
| TR-3 | Simulate bandwidth: unlimited, 1Mbps, 100Kbps | Should Have |
| TR-4 | Minimum 30 runs per test scenario | Must Have |
| TR-5 | Capture packet data with Wireshark/Scapy | Should Have |

---

## 6. Non-Functional Requirements

| ID | Requirement | Target |
|----|-------------|--------|
| NFR-1 | Measurement precision | ±1ms accuracy |
| NFR-2 | Test reproducibility | Results within 5% variance on repeat |
| NFR-3 | Code quality | Documented, modular Python code |
| NFR-4 | Data integrity | All raw data preserved and versioned |

---

## 7. Technical Architecture

### 7.1 System Diagram

```
┌─────────────────────────────────────────────────────────┐
│                    Test Environment                      │
│  ┌─────────────┐    ┌──────────────┐    ┌────────────┐  │
│  │   Gopher    │    │   Network    │    │   Test     │  │
│  │   Server    │◄───│   Simulator  │◄───│   Client   │  │
│  │  (port 70)  │    │  (tc/netem)  │    │  (Python)  │  │
│  └─────────────┘    └──────────────┘    └────────────┘  │
│                                                          │
│  ┌─────────────┐                        ┌────────────┐  │
│  │    HTTP     │◄───────────────────────│   Metrics  │  │
│  │   Server    │                        │   Logger   │  │
│  │  (port 80)  │                        │  (CSV/JSON)│  │
│  └─────────────┘                        └────────────┘  │
└─────────────────────────────────────────────────────────┘
```

### 7.2 Technology Stack

| Component | Technology | Justification |
|-----------|------------|---------------|
| Language | Python 3.10+ | Course requirement, rich ecosystem |
| Gopher Server | Pygopherd / Custom | Simple, well-documented |
| HTTP Server | Flask | Lightweight, easy instrumentation |
| Network Sim | `tc`/`netem` | Standard Linux traffic control |
| Packet Capture | Scapy | Python-native packet analysis |
| Data Storage | CSV/JSON | Simple, portable formats |
| Analysis | Pandas | Industry-standard data analysis |
| Visualization | Matplotlib/Seaborn | Publication-quality charts |

---

## 8. Data Model

### 8.1 Test Result Schema

```python
{
    "test_id": "uuid",
    "timestamp": "ISO-8601",
    "protocol": "gopher" | "http",
    "content_size_bytes": int,
    "network_conditions": {
        "latency_ms": int,
        "packet_loss_percent": float,
        "bandwidth_kbps": int | null
    },
    "metrics": {
        "ttfb_ms": float,
        "total_time_ms": float,
        "bytes_transferred": int,
        "throughput_kbps": float
    },
    "success": bool,
    "error": str | null
}
```

---

## 9. Metrics & KPIs

### 9.1 Performance Metrics

| Metric | Definition | Unit |
|--------|------------|------|
| TTFB (Time to First Byte) | Time from request sent to first response byte | ms |
| Total Transfer Time | Time to complete full content download | ms |
| Bytes Transferred | Total bytes including protocol overhead | bytes |
| Throughput | Effective data transfer rate | Kbps |
| Overhead Ratio | (Total bytes - Content bytes) / Content bytes | % |

### 9.2 Project KPIs

| KPI | Target |
|-----|--------|
| Test scenarios completed | 100% |
| Statistical confidence | p < 0.05 |
| Visualization clarity | All key findings visualized |
| Documentation completeness | All rubric categories addressed |

---

## 10. Deliverables

| Deliverable | Format | Description |
|-------------|--------|-------------|
| Source Code | Python (.py) | All server, client, and analysis code |
| Raw Data | CSV/JSON | All test results |
| Analysis Notebook | Jupyter (.ipynb) | Data processing and visualization |
| Report | PDF/Word | Written findings (10% of grade) |
| Presentation | PowerPoint/PDF | Slides for presentation (20% of grade) |
| Demo | Live | Real-time protocol comparison |

---

## 11. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Gopher server setup issues | Medium | High | Use well-documented Pygopherd; have backup custom implementation |
| Inconsistent network simulation | Medium | High | Validate conditions before each test batch |
| Insufficient statistical power | Low | Medium | Ensure 30+ runs per scenario |
| Time overrun | Medium | Medium | Prioritize core metrics; drop nice-to-haves |
| Environment differences | Low | Medium | Document and control all environment variables |

---

## 12. Assumptions & Dependencies

### 12.1 Assumptions
- Tests will run on a controlled Linux environment
- Network simulation tools (`tc`/`netem`) are available
- Both protocols will be tested sequentially to avoid interference

### 12.2 Dependencies
- Python 3.10+
- Linux kernel with `tc` support (or alternative simulation)
- Network access for library installation

---

## 13. Appendix

### 13.1 References
- RFC 1436: The Internet Gopher Protocol
- RFC 2616: HTTP/1.1
- Pygopherd Documentation

### 13.2 Glossary
| Term | Definition |
|------|------------|
| Gopher | Text-based internet protocol, predecessor to HTTP |
| TTFB | Time to First Byte — latency until first response data arrives |
| `tc` | Traffic Control — Linux utility for network simulation |
| `netem` | Network Emulator — kernel module for delay/loss simulation |
