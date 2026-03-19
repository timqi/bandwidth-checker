# AWS EC2 Bandwidth Checker — Usage Guide

A one-shot tool that measures your EC2 instance's actual bandwidth limits, burst credit behavior, and throttling impact. Designed for latency-sensitive workloads like blockchain nodes.

## Prerequisites

**Local machine (the EC2 instance you want to test):**
- Python 3.10+
- iperf3 installed (`sudo apt install iperf3` or `sudo yum install iperf3`)
- `ss` command available (part of `iproute2`, pre-installed on most Linux)
- `ping` command available

**Remote target (a second EC2 instance in a different region):**
- iperf3 installed
- SSH access from local machine
- Security group allows inbound TCP on ports 5201-5202 (or your chosen ports)

**Install dependencies:**

```bash
uv sync
```

## Quick Start

```bash
uv run python run_test.py --host 13.56.xx.xx --user ec2-user --key ~/.ssh/my-key.pem
```

This runs all 3 phases (~45-60 min total) and generates an HTML report in `data/report/`.

## CLI Options

```
--host HOST          Remote iperf3 target IP (required)
--user USER          SSH user on remote (default: ec2-user)
--key KEY            SSH private key path (omit if using ssh-agent)
--port PORT          iperf3 base port (default: 5201, uses port and port+1)
--data-dir DIR       Output directory for CSV data and reports (default: data)
--skip-phase1        Skip the step-up pressure test
--skip-phase2        Skip the sustained load / depletion test
--skip-phase3        Skip the throttled state observation
```

## What It Tests

### Phase 1: Step-Up Pressure Test (~20 min)

Gradually increases bandwidth from 50 Mbps to 5 Gbps in 7 levels. At each level, runs TCP and UDP tests in various directions (egress, ingress, bidirectional). Measures:

- Actual achievable throughput vs target
- TCP retransmissions at each level
- UDP packet loss and jitter
- Ping RTT under load (reveals queueing delay)
- Small-packet UDP at 256 Mbps (simulates blockchain P2P traffic)

Bandwidth levels: 50, 128, 256, 512, 1000, 2000, 5000 Mbps

After Phase 1, an intermediate HTML report is generated so you can review results even if later phases fail.

### Phase 2: Sustained Full-Load (~5-35 min)

Runs TCP + UDP bidirectional traffic at 5 Gbps until network credits deplete. Detects depletion when TCP throughput drops below 300 Mbps for 10 consecutive seconds. Measures:

- Time to credit depletion (typically 10-30 min on t3.medium)
- Throughput timeline showing the burst-to-baseline transition
- Latency and retransmission changes during the transition

Hard timeout: 35 minutes. If credits don't deplete, the test moves on.

### Phase 3: Throttled State Observation (~10 min)

Runs immediately after credit depletion to characterize throttled behavior:

1. **Steady-state observation (3 min):** TCP + UDP at max rate to see baseline-limited behavior
2. **Mini step-up replay (4 min):** Re-tests at 50, 128, 256, 384 Mbps to see how traffic shaping affects different load levels

## Output

All data is saved to `--data-dir` (default: `data/`):

```
data/
  step_up_iperf_tcp.csv      # Phase 1 TCP results
  step_up_iperf_udp.csv      # Phase 1 UDP results
  step_up_ping.csv            # Phase 1 latency
  step_up_ss.csv              # Phase 1 TCP socket stats
  sustained_iperf_tcp.csv     # Phase 2 TCP timeline
  sustained_iperf_udp.csv     # Phase 2 UDP timeline
  sustained_ping.csv          # Phase 2 latency
  sustained_ss.csv            # Phase 2 TCP socket stats
  throttled_iperf_tcp.csv     # Phase 3 TCP results
  throttled_iperf_udp.csv     # Phase 3 UDP results
  throttled_ping.csv          # Phase 3 latency
  throttled_ss.csv            # Phase 3 TCP socket stats
  report/
    step_up_report.html       # Intermediate report after Phase 1
    final_report.html         # Full report with all phases
    charts/                   # PNG charts embedded in reports
```

CSV files are written incrementally — if the test is interrupted (Ctrl+C), you keep all data collected up to that point.

## Interruption & Cleanup

Press Ctrl+C at any time. The tool will:
1. Kill all local iperf3, ping, and ss processes
2. Kill remote iperf3 servers via SSH
3. Attempt to generate a partial report from collected CSV data
4. Exit cleanly

## Running Individual Phases

Skip phases you don't need:

```bash
# Only run step-up (quick bandwidth profiling)
uv run python run_test.py --host 13.56.xx.xx --key ~/.ssh/key.pem --skip-phase2 --skip-phase3

# Only run sustained load (test credit depletion)
uv run python run_test.py --host 13.56.xx.xx --key ~/.ssh/key.pem --skip-phase1 --skip-phase3

# Skip step-up, run sustained + throttled
uv run python run_test.py --host 13.56.xx.xx --key ~/.ssh/key.pem --skip-phase1
```

## Remote Target Setup

1. Launch a second EC2 instance in a different region (e.g., us-west-1 if your node is in us-east-1)
2. Install iperf3: `sudo yum install -y iperf3` (Amazon Linux) or `sudo apt install -y iperf3` (Ubuntu)
3. Open security group: allow inbound TCP on ports 5201-5202 from your node's IP
4. Ensure SSH access works: `ssh -i key.pem ec2-user@remote-ip "echo ok"`

The tool handles starting/stopping iperf3 servers on the remote automatically via SSH.

## Interpreting Results

Key things to look for in the HTML report:

- **Bandwidth ceiling:** the throughput level where actual throughput stops increasing with target. On t3.medium, burst ceiling is ~5 Gbps, baseline is ~256 Mbps
- **Retransmission spike:** a jump in TCP retransmissions indicates packet drops at the bandwidth limit
- **RTT under load:** if ping RTT increases significantly under load, AWS is using token-bucket queueing (delay before drop)
- **Depletion time:** how long burst credits last under sustained full load
- **Throttled behavior:** whether your workload fits within baseline bandwidth, and the cost of exceeding it

## Troubleshooting

**"Cannot SSH to remote host"** — verify SSH key, security group allows port 22, and the user is correct (ec2-user for Amazon Linux, ubuntu for Ubuntu)

**"Cannot reach iperf3 on port 5201"** — security group on the remote must allow inbound TCP 5201-5202 from your IP

**"Burst credits may be depleted"** — your instance has been under network load recently. Wait 30+ minutes for credits to recover, or continue to test throttled-state behavior

**iperf3 crashes during Phase 2** — normal under extreme load. The tool automatically restarts the remote server and retries
