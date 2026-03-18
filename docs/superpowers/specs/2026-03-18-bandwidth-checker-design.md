# AWS EC2 Bandwidth Checker - Design Spec

## Background

A t3.medium EC2 instance runs a blockchain node (P2P, bidirectional traffic, latency-sensitive, directly impacts revenue). We need to measure the actual bandwidth limits and understand how AWS throttling affects latency, packet loss, and TCP behavior — then assess the impact on the blockchain node.

### t3.medium Network Characteristics

- Baseline bandwidth: ~256 Mbps (sustained)
- Burst bandwidth: up to 5 Gbps (credit-based)
- Credit pool: when full, supports ~30 min of burst
- Throttling mechanism: token bucket shaping (queuing delay + packet drop)

### Questions to Answer

1. What is the actual burst bandwidth peak?
2. How long can burst last before credit depletion?
3. What happens at the limit — queuing delay, packet drop, or both?
4. What are the packet loss characteristics (rate, pattern)?
5. What is the latency degradation curve from normal to throttled?
6. What is the TCP retransmission cost (rate, delay)?
7. Does bidirectional traffic behave worse than unidirectional?

## Architecture

```
bandwidth-checker/
├── run_test.py          # Main entry, orchestrates entire test flow
├── config.py            # Test parameter configuration
├── phases/
│   ├── step_up.py       # Phase 1: Step-up pressure test
│   ├── sustained.py     # Phase 2: Sustained full-load until credit depletion
│   └── throttled.py     # Phase 3: Throttled state observation
├── collectors/
│   ├── iperf.py         # iperf3 process management + result parsing
│   ├── latency.py       # Parallel ping/latency collection
│   └── tcp_stats.py     # ss TCP retransmission/cwnd collection
├── report/
│   ├── generator.py     # Report generation (including intermediate report)
│   └── charts.py        # matplotlib charts
├── setup/
│   └── remote.py        # Remote iperf3 server setup/health check
└── data/                # Raw test data (incremental CSV per collector per phase)
```

### Tech Stack

- **Traffic generation**: iperf3 (TCP + UDP)
- **Orchestration/monitoring/reporting**: Python
- **Latency measurement**: ping (ICMP)
- **TCP stats**: ss (socket statistics)
- **Charts**: matplotlib
- **Report format**: HTML

### Data Persistence

Each collector writes data incrementally to CSV files under `data/`:
- `data/<phase>_iperf_tcp.csv`
- `data/<phase>_iperf_udp.csv`
- `data/<phase>_ping.csv`
- `data/<phase>_ss.csv`

This ensures crash recovery — if the test is interrupted, collected data is preserved and the report can be generated from partial data.

### Process Management

iperf3 processes are managed via `subprocess.Popen`:
- Non-blocking stdout reads for real-time monitoring
- Health check: if iperf3 client detects connection failure (exit code != 0), attempt to restart remote iperf3 server via SSH and retry
- Remote iperf3 server started with `nohup iperf3 -s -p <port> &` to survive SSH disconnection
- Pre-test cleanup: kill any existing iperf3 processes on remote before starting

### Signal Handling

`run_test.py` registers SIGINT/SIGTERM handlers that:
1. Stop all running iperf3 client processes
2. SSH to remote and kill iperf3 server processes
3. Flush all in-memory data to CSV files
4. Generate a partial report from data collected so far

### Pre-flight Checks (`setup/remote.py`)

Before any test phase runs:
1. Verify SSH connectivity to remote
2. Verify iperf3 is installed on remote
3. Kill any stale iperf3 processes on remote
4. Verify security group ports are open (quick iperf3 handshake test)
5. **Burst credit probe**: run a 30-second TCP test at full speed. If throughput < 500 Mbps, credits are likely depleted — warn user and offer to skip to Phase 3 or wait for credit recovery.

## Test Design

### Phase 1: Step-Up Pressure Test (~25 min)

Gradually increase bandwidth, measure latency/loss at each level to find the "inflection point."

#### Bandwidth Levels and Test Matrix

| Level | TCP Directions | UDP Directions | Duration per test | Cooldown | Subtotal |
|-------|---------------|----------------|-------------------|----------|----------|
| 50 Mbps | egress | egress | 1 min | 15 s between tests | ~2.5 min |
| 128 Mbps | egress | egress | 1 min | 15 s | ~2.5 min |
| 256 Mbps | egress, ingress, bidir | egress, ingress, bidir | 1 min | 15 s | ~7.5 min |
| 512 Mbps | egress, bidir | egress, bidir | 1 min | 15 s | ~5 min |
| 1000 Mbps | bidir | bidir | 1 min | 15 s | ~2.5 min |
| 2000 Mbps | bidir | bidir | 1 min | 15 s | ~2.5 min |
| 5000 Mbps | bidir | bidir | 1 min | 15 s | ~2.5 min |

Notes:
- 15-second cooldown between every individual test run (not just between levels)
- Low levels (50/128) serve as baseline reference
- 256 Mbps (near baseline bandwidth) gets full direction coverage — the inflection zone
- High levels focus on bidirectional (matching P2P pattern)
- **bidir at target rate X means X Mbps each direction (2X total)** — this is intentional as it saturates baseline capacity earlier, revealing throttling behavior
- Phase 1 consumes ~3 min of burst credits at 2G/5G levels, reducing Phase 2 available burst time accordingly
- Small-packet UDP test (`-l 512`) added at 256 Mbps level to simulate blockchain-typical packet sizes

#### Per-Test Data Collection (every second)

- **iperf3 JSON output (`-J`)**: throughput, retransmissions (TCP), lost packets/rate (UDP), jitter (UDP)
  - Note: JSON is emitted at end of test, not streamed. Collector reads after iperf3 process completes.
- **Parallel ping**: RTT min/avg/max
  - Note: RTT under load reflects queueing delay, not propagation latency change. This is the intended measurement — it shows what the blockchain node actually experiences.
- **ss stats** (`ss -tin dst <remote_ip>`): TCP cwnd, retrans, rtt, rttvar, per socket, aggregated across all iperf3 streams

#### Intermediate Report (generated after Phase 1)

- Per-level metrics summary table
- Inflection point analysis: the bandwidth at which latency/loss starts degrading significantly
- TCP vs UDP behavior comparison
- Direction asymmetry analysis (egress vs ingress vs bidir)
- UDP jitter analysis across levels
- Charts:
  1. TCP throughput across levels
  2. UDP packet loss rate across levels
  3. RTT across levels (queueing delay)
  4. TCP retransmission rate across levels
  5. UDP jitter across levels

### Phase 2: Sustained Full-Load (~35 min max)

Exhaust network credits by running at full bandwidth, observe the entire burst-to-throttle transition.

#### Test Configuration

Two concurrent iperf3 processes:
- **Process 1**: `iperf3 -c <target> --bidir -P 4 -p 5201` — TCP bidirectional, 4 parallel streams per direction
- **Process 2**: `iperf3 -c <target> --bidir -u -b 5G -p 5202` — UDP bidirectional

Note: `-b 5G` is a target rate; actual generation may be CPU-bound on t3.medium (2 vCPU). Treat as "request maximum bandwidth and measure what gets through," not as guaranteed 5 Gbps generation.

Parallel ping and ss collection run throughout.

#### Credit Depletion Detection

- Monitor **total TCP throughput across all streams** (not per-stream)
- Credits depleted when: total TCP throughput < 300 Mbps for 10 consecutive seconds
- **Crash guard**: if iperf3 process exits unexpectedly (exit code != 0), this is a process crash, NOT credit depletion. Restart the process and continue monitoring.
- ~35 min is a hard cap. If credits haven't depleted by then (unlikely), transition to Phase 3 anyway.

#### Key Observations

- Exact time-to-depletion
- Transition behavior: sudden drop vs gradual decline
- RTT before vs after depletion

### Phase 3: Throttled State Observation (~10 min)

Continue traffic after credit depletion to characterize the throttled state.

#### Measurements

1. **Steady-state bandwidth**: verify it stabilizes at ~256 Mbps
2. **Latency characteristics**: RTT increase compared to idle state
3. **Packet loss pattern**: uniform vs bursty (analyze UDP loss intervals)
4. **TCP behavior**: retransmission rate, cwnd size, RTO values
5. **UDP jitter**: jitter under throttled conditions
6. **Mini step-up replay**: run a small step-up in throttled state (50 → 128 → 256 → 384 Mbps, TCP + UDP) to see latency behavior under throttled conditions

## Report Design

### Intermediate Report (`report/step_up_report.html`)

Generated after Phase 1 completes.

Contents:
- Per-level metrics summary (table)
- Inflection point analysis conclusion
- 5 charts:
  1. TCP throughput across levels
  2. UDP packet loss rate across levels
  3. RTT across levels
  4. TCP retransmission rate across levels
  5. UDP jitter across levels

### Final Report (`report/final_report.html`)

Generated after all phases complete.

Contents:
- Everything from intermediate report, plus:
- Credit depletion timeline
- Pre/post-throttle comparison analysis
- Business impact assessment for blockchain node:
  - Expected latency under normal conditions
  - Latency degradation magnitude when bandwidth hits baseline
  - Recommendation: whether to upgrade instance

Charts (9 total):
1. Full-test throughput timeline (with phase boundaries marked)
2. Full-test RTT timeline
3. Full-test packet loss rate timeline
4. TCP retransmission rate timeline
5. Step-up: bandwidth vs RTT (inflection point)
6. Step-up: bandwidth vs loss rate
7. TCP vs UDP behavior comparison
8. Pre/post-throttle metrics comparison (bar chart)
9. UDP jitter timeline

### Report Data Source

All charts and tables are generated from the CSV files in `data/`. The report generator reads from disk, not from in-memory data. This means reports can be regenerated after the test completes, or generated from partial data if the test was interrupted.

## Test Environment

- **Source**: t3.medium in one AWS region
- **Target**: EC2 instance in a different AWS region (cross-region)
- **Cross-region RTT note**: cross-region baseline RTT is typically 20–100 ms. AWS throttling adds 1–10 ms of queueing delay — a 5–20% change. This is detectable in charts but noisy. If higher signal fidelity is needed, consider adding a same-region target for comparison.
- **Prerequisites**: iperf3 (>= 3.7 for `--bidir` support) installed on both instances, SSH access to target, security group allows iperf3 ports (5201-5210)
- **Blockchain node**: left running during the test for realistic conditions. Its traffic competes with iperf3, which reflects real-world behavior. The `ss` collector captures per-socket stats to distinguish iperf3 traffic from node traffic where possible.

## Dependencies

- Python 3.8+
- iperf3 >= 3.7
- matplotlib
- ping (system)
- ss (system, iproute2)
- SSH access to remote instance
