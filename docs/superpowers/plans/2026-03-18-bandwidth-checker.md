# Bandwidth Checker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a one-shot bandwidth testing tool that measures AWS t3.medium network limits (burst, throttling, latency, packet loss) and generates HTML reports assessing impact on a blockchain node.

**Architecture:** Python orchestrator drives iperf3 for traffic generation across 3 phases (step-up, sustained full-load, throttled observation). Collectors run in parallel (ping, ss) and write incremental CSV. Report generator reads CSV and produces HTML with matplotlib charts.

**Tech Stack:** Python 3.8+, iperf3 >= 3.7, matplotlib, subprocess, SSH

**Spec:** `docs/superpowers/specs/2026-03-18-bandwidth-checker-design.md`

---

## File Structure

```
bandwidth-checker/
├── pyproject.toml
├── run_test.py              # Main entry point, CLI args, signal handling
├── config.py                # TestConfig dataclass, validation, defaults
├── collectors/
│   ├── __init__.py
│   ├── iperf.py             # IperfRunner: start/stop/parse iperf3, write CSV
│   ├── latency.py           # LatencyCollector: ping loop, write CSV
│   └── tcp_stats.py         # TcpStatsCollector: ss polling, write CSV
├── phases/
│   ├── __init__.py
│   ├── step_up.py           # Phase 1: step-up pressure test
│   ├── sustained.py         # Phase 2: sustained full-load
│   └── throttled.py         # Phase 3: throttled observation
├── report/
│   ├── __init__.py
│   ├── charts.py            # Chart generation functions (matplotlib)
│   └── generator.py         # HTML report assembly
├── setup/
│   ├── __init__.py
│   └── remote.py            # SSH helpers, remote iperf3 server management
├── data/                    # Created at runtime, CSV output
└── tests/
    ├── __init__.py
    ├── test_config.py
    ├── test_iperf_parser.py
    ├── test_iperf_runner.py
    ├── test_latency_parser.py
    ├── test_tcp_stats_parser.py
    ├── test_csv_persistence.py
    ├── test_depletion_detector.py
    ├── test_charts.py
    └── test_report_generator.py
```

---

## Task 1: Project Scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `config.py`
- Create: `tests/__init__.py`, `collectors/__init__.py`, `phases/__init__.py`, `report/__init__.py`, `setup/__init__.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Create pyproject.toml**

```toml
[project]
name = "bandwidth-checker"
version = "0.1.0"
requires-python = ">=3.8"
dependencies = [
    "matplotlib>=3.5",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

- [ ] **Step 2: Create empty __init__.py files**

Create empty `__init__.py` in: `collectors/`, `phases/`, `report/`, `setup/`, `tests/`

- [ ] **Step 3: Create data directory**

```bash
mkdir -p data
```

- [ ] **Step 4: Write test for config**

```python
# tests/test_config.py
from config import TestConfig


def test_default_config():
    cfg = TestConfig(remote_host="10.0.0.1", remote_user="ec2-user")
    assert cfg.remote_host == "10.0.0.1"
    assert cfg.iperf_base_port == 5201
    assert cfg.test_duration == 60
    assert cfg.cooldown == 15
    assert cfg.phase2_timeout == 2100  # 35 min
    assert cfg.phase3_duration == 600  # 10 min
    assert cfg.depletion_threshold_mbps == 300
    assert cfg.depletion_window_sec == 10


def test_config_validation_missing_host():
    try:
        TestConfig(remote_host="", remote_user="ec2-user")
        assert False, "Should have raised"
    except ValueError:
        pass


def test_config_data_dir():
    cfg = TestConfig(remote_host="10.0.0.1", remote_user="ec2-user")
    assert cfg.data_dir == "data"


def test_step_up_levels():
    cfg = TestConfig(remote_host="10.0.0.1", remote_user="ec2-user")
    levels = cfg.step_up_levels
    assert levels[0]["bandwidth_mbps"] == 50
    assert levels[-1]["bandwidth_mbps"] == 5000
    # 256 Mbps level should have all directions
    level_256 = [l for l in levels if l["bandwidth_mbps"] == 256][0]
    assert "egress" in level_256["tcp_directions"]
    assert "ingress" in level_256["tcp_directions"]
    assert "bidir" in level_256["tcp_directions"]
```

- [ ] **Step 5: Run test to verify it fails**

```bash
cd /home/qiqi/code/fish/bandwidth-checker && uv run pytest tests/test_config.py -v
```

Expected: FAIL — `config` module not found

- [ ] **Step 6: Write config.py**

```python
# config.py
from dataclasses import dataclass, field
from typing import List, Dict, Any


@dataclass
class TestConfig:
    remote_host: str
    remote_user: str
    ssh_key: str = ""
    iperf_base_port: int = 5201
    test_duration: int = 60          # seconds per individual test
    cooldown: int = 15               # seconds between tests
    phase2_timeout: int = 2100       # 35 min hard cap
    phase3_duration: int = 600       # 10 min
    depletion_threshold_mbps: int = 300
    depletion_window_sec: int = 10
    data_dir: str = "data"
    tcp_parallel_streams: int = 4    # -P flag for iperf3
    udp_target_rate: str = "5G"      # -b flag for iperf3 UDP

    def __post_init__(self):
        if not self.remote_host:
            raise ValueError("remote_host is required")
        if not self.remote_user:
            raise ValueError("remote_user is required")

    @property
    def step_up_levels(self) -> List[Dict[str, Any]]:
        return [
            {
                "bandwidth_mbps": 50,
                "tcp_directions": ["egress"],
                "udp_directions": ["egress"],
            },
            {
                "bandwidth_mbps": 128,
                "tcp_directions": ["egress"],
                "udp_directions": ["egress"],
            },
            {
                "bandwidth_mbps": 256,
                "tcp_directions": ["egress", "ingress", "bidir"],
                "udp_directions": ["egress", "ingress", "bidir"],
                "small_packet_udp": True,
            },
            {
                "bandwidth_mbps": 512,
                "tcp_directions": ["egress", "bidir"],
                "udp_directions": ["egress", "bidir"],
            },
            {
                "bandwidth_mbps": 1000,
                "tcp_directions": ["bidir"],
                "udp_directions": ["bidir"],
            },
            {
                "bandwidth_mbps": 2000,
                "tcp_directions": ["bidir"],
                "udp_directions": ["bidir"],
            },
            {
                "bandwidth_mbps": 5000,
                "tcp_directions": ["bidir"],
                "udp_directions": ["bidir"],
            },
        ]
```

- [ ] **Step 7: Run tests and verify they pass**

```bash
cd /home/qiqi/code/fish/bandwidth-checker && uv run pytest tests/test_config.py -v
```

Expected: all 4 tests PASS

- [ ] **Step 8: Initialize git repo and commit**

```bash
cd /home/qiqi/code/fish/bandwidth-checker
git init
echo "__pycache__/\n*.pyc\ndata/\n.venv/" > .gitignore
git add pyproject.toml config.py .gitignore tests/test_config.py tests/__init__.py collectors/__init__.py phases/__init__.py report/__init__.py setup/__init__.py
git commit -m "feat: project scaffolding with config and test matrix"
```

---

## Task 2: iperf3 JSON Parser

**Files:**
- Create: `collectors/iperf.py`
- Test: `tests/test_iperf_parser.py`

This task builds the iperf3 output parser. Process management comes in Task 5.

- [ ] **Step 1: Write failing test for TCP JSON parsing**

```python
# tests/test_iperf_parser.py
import json
from collectors.iperf import parse_iperf_tcp_json, parse_iperf_udp_json

# Minimal iperf3 TCP JSON structure
SAMPLE_TCP_JSON = {
    "intervals": [
        {
            "sum": {
                "start": 0,
                "end": 1,
                "seconds": 1,
                "bytes": 32000000,
                "bits_per_second": 256000000,
                "retransmits": 2,
            }
        },
        {
            "sum": {
                "start": 1,
                "end": 2,
                "seconds": 1,
                "bytes": 31000000,
                "bits_per_second": 248000000,
                "retransmits": 5,
            }
        },
    ],
    "end": {
        "sum_sent": {
            "bytes": 63000000,
            "bits_per_second": 252000000,
        },
        "sum_received": {
            "bytes": 62000000,
            "bits_per_second": 248000000,
        },
    },
}

SAMPLE_TCP_BIDIR_JSON = {
    "intervals": [
        {
            "sum_sent": {
                "start": 0, "end": 1, "seconds": 1,
                "bytes": 32000000, "bits_per_second": 256000000, "retransmits": 1,
            },
            "sum_received": {
                "start": 0, "end": 1, "seconds": 1,
                "bytes": 30000000, "bits_per_second": 240000000,
            },
        },
    ],
}

SAMPLE_UDP_JSON = {
    "intervals": [
        {
            "sum": {
                "start": 0,
                "end": 1,
                "seconds": 1,
                "bytes": 32000000,
                "bits_per_second": 256000000,
                "lost_packets": 10,
                "packets": 1000,
                "lost_percent": 1.0,
                "jitter_ms": 0.5,
            }
        },
        {
            "sum": {
                "start": 1,
                "end": 2,
                "seconds": 1,
                "bytes": 30000000,
                "bits_per_second": 240000000,
                "lost_packets": 50,
                "packets": 1000,
                "lost_percent": 5.0,
                "jitter_ms": 1.2,
            }
        },
    ],
}


def test_parse_tcp_intervals():
    rows = parse_iperf_tcp_json(SAMPLE_TCP_JSON)
    assert len(rows) == 2
    assert rows[0]["bits_per_second"] == 256000000
    assert rows[0]["retransmits"] == 2
    assert rows[1]["retransmits"] == 5


def test_parse_tcp_bidir():
    """--bidir output uses sum_sent/sum_received instead of sum."""
    rows = parse_iperf_tcp_json(SAMPLE_TCP_BIDIR_JSON)
    assert len(rows) == 1
    # Should combine sent+received throughput
    assert rows[0]["bits_per_second"] == 256000000 + 240000000
    assert rows[0]["retransmits"] == 1


def test_parse_udp_intervals():
    rows = parse_iperf_udp_json(SAMPLE_UDP_JSON)
    assert len(rows) == 2
    assert rows[0]["lost_percent"] == 1.0
    assert rows[0]["jitter_ms"] == 0.5
    assert rows[1]["lost_packets"] == 50


def test_parse_tcp_empty():
    rows = parse_iperf_tcp_json({"intervals": []})
    assert rows == []


def test_parse_udp_empty():
    rows = parse_iperf_udp_json({"intervals": []})
    assert rows == []
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/qiqi/code/fish/bandwidth-checker && uv run pytest tests/test_iperf_parser.py -v
```

Expected: FAIL — cannot import `parse_iperf_tcp_json`

- [ ] **Step 3: Implement parser functions**

```python
# collectors/iperf.py
"""iperf3 process management and JSON result parsing."""
import csv
import json
import os
from typing import Any, Dict, List


def parse_iperf_tcp_json(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Parse iperf3 TCP JSON output into per-interval rows.

    Handles both normal (sum) and --bidir (sum_sent/sum_received) formats.
    For bidir, combines sent+received throughput into a single row.
    """
    rows = []
    for interval in data.get("intervals", []):
        # --bidir format: sum_sent + sum_received (no "sum" key)
        if "sum_sent" in interval:
            sent = interval["sum_sent"]
            recv = interval.get("sum_received", {})
            rows.append({
                "start": sent.get("start", 0),
                "end": sent.get("end", 0),
                "seconds": sent.get("seconds", 0),
                "bytes": sent.get("bytes", 0) + recv.get("bytes", 0),
                "bits_per_second": sent.get("bits_per_second", 0) + recv.get("bits_per_second", 0),
                "retransmits": sent.get("retransmits", 0) + recv.get("retransmits", 0),
            })
        else:
            # Normal format: single "sum" key
            s = interval.get("sum", {})
            rows.append({
                "start": s.get("start", 0),
                "end": s.get("end", 0),
                "seconds": s.get("seconds", 0),
                "bytes": s.get("bytes", 0),
                "bits_per_second": s.get("bits_per_second", 0),
                "retransmits": s.get("retransmits", 0),
            })
    return rows


def parse_iperf_udp_json(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Parse iperf3 UDP JSON output into per-interval rows.

    Handles both normal (sum) and --bidir (sum_sent/sum_received) formats.
    """
    rows = []
    for interval in data.get("intervals", []):
        # --bidir format
        if "sum_sent" in interval:
            sent = interval["sum_sent"]
            recv = interval.get("sum_received", {})
            rows.append({
                "start": sent.get("start", 0),
                "end": sent.get("end", 0),
                "seconds": sent.get("seconds", 0),
                "bytes": sent.get("bytes", 0) + recv.get("bytes", 0),
                "bits_per_second": sent.get("bits_per_second", 0) + recv.get("bits_per_second", 0),
                "lost_packets": sent.get("lost_packets", 0) + recv.get("lost_packets", 0),
                "packets": sent.get("packets", 0) + recv.get("packets", 0),
                "lost_percent": (
                    (sent.get("lost_packets", 0) + recv.get("lost_packets", 0))
                    / max(sent.get("packets", 0) + recv.get("packets", 0), 1) * 100
                ),
                "jitter_ms": max(sent.get("jitter_ms", 0), recv.get("jitter_ms", 0)),
            })
        else:
            # Normal format
            s = interval.get("sum", {})
            rows.append({
                "start": s.get("start", 0),
                "end": s.get("end", 0),
                "seconds": s.get("seconds", 0),
                "bytes": s.get("bytes", 0),
                "bits_per_second": s.get("bits_per_second", 0),
                "lost_packets": s.get("lost_packets", 0),
                "packets": s.get("packets", 0),
                "lost_percent": s.get("lost_percent", 0),
                "jitter_ms": s.get("jitter_ms", 0),
            })
    return rows


def write_iperf_csv(rows: List[Dict[str, Any]], filepath: str) -> None:
    """Append iperf3 parsed rows to CSV file. Creates file with header if new."""
    if not rows:
        return
    file_exists = os.path.exists(filepath)
    with open(filepath, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        if not file_exists:
            writer.writeheader()
        writer.writerows(rows)
```

- [ ] **Step 4: Run tests and verify they pass**

```bash
cd /home/qiqi/code/fish/bandwidth-checker && uv run pytest tests/test_iperf_parser.py -v
```

Expected: all 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add collectors/iperf.py tests/test_iperf_parser.py
git commit -m "feat: iperf3 TCP/UDP JSON parser with CSV output"
```

---

## Task 3: CSV Persistence Tests

**Files:**
- Modify: `collectors/iperf.py` (already has `write_iperf_csv`)
- Test: `tests/test_csv_persistence.py`

- [ ] **Step 1: Write failing test for CSV write/read**

```python
# tests/test_csv_persistence.py
import csv
import os
import tempfile
from collectors.iperf import write_iperf_csv


def test_write_csv_creates_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "test.csv")
        rows = [
            {"start": 0, "end": 1, "bits_per_second": 256000000, "retransmits": 2},
            {"start": 1, "end": 2, "bits_per_second": 248000000, "retransmits": 5},
        ]
        write_iperf_csv(rows, path)
        assert os.path.exists(path)
        with open(path) as f:
            reader = csv.DictReader(f)
            read_rows = list(reader)
        assert len(read_rows) == 2
        assert read_rows[0]["retransmits"] == "2"


def test_write_csv_appends():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "test.csv")
        rows1 = [{"start": 0, "end": 1, "bits_per_second": 256000000}]
        rows2 = [{"start": 1, "end": 2, "bits_per_second": 248000000}]
        write_iperf_csv(rows1, path)
        write_iperf_csv(rows2, path)
        with open(path) as f:
            reader = csv.DictReader(f)
            read_rows = list(reader)
        assert len(read_rows) == 2


def test_write_csv_empty_rows():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "test.csv")
        write_iperf_csv([], path)
        assert not os.path.exists(path)
```

- [ ] **Step 2: Run test to verify it passes (implementation already exists)**

```bash
cd /home/qiqi/code/fish/bandwidth-checker && uv run pytest tests/test_csv_persistence.py -v
```

Expected: PASS (write_iperf_csv already implemented in Task 2)

- [ ] **Step 3: Commit**

```bash
git add tests/test_csv_persistence.py
git commit -m "test: CSV persistence tests for iperf data"
```

---

## Task 4: Ping Latency Parser

**Files:**
- Create: `collectors/latency.py`
- Test: `tests/test_latency_parser.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_latency_parser.py
from collectors.latency import parse_ping_line, parse_ping_summary


def test_parse_ping_reply():
    line = "64 bytes from 10.0.0.1: icmp_seq=1 ttl=64 time=25.3 ms"
    result = parse_ping_line(line)
    assert result == {"icmp_seq": 1, "ttl": 64, "time_ms": 25.3}


def test_parse_ping_timeout():
    line = "Request timeout for icmp_seq 5"
    result = parse_ping_line(line)
    assert result is None


def test_parse_ping_summary():
    lines = [
        "--- 10.0.0.1 ping statistics ---",
        "10 packets transmitted, 9 received, 10% packet loss, time 9012ms",
        "rtt min/avg/max/mdev = 20.1/25.3/35.7/4.2 ms",
    ]
    result = parse_ping_summary(lines)
    assert result["packets_sent"] == 10
    assert result["packets_received"] == 9
    assert result["loss_percent"] == 10.0
    assert result["rtt_min"] == 20.1
    assert result["rtt_avg"] == 25.3
    assert result["rtt_max"] == 35.7


def test_parse_ping_line_garbage():
    result = parse_ping_line("PING 10.0.0.1 (10.0.0.1) 56(84) bytes of data.")
    assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/qiqi/code/fish/bandwidth-checker && uv run pytest tests/test_latency_parser.py -v
```

Expected: FAIL — cannot import

- [ ] **Step 3: Implement latency parser**

```python
# collectors/latency.py
"""Ping latency collection and parsing."""
import csv
import os
import re
from typing import Any, Dict, List, Optional

# Match: 64 bytes from X: icmp_seq=N ttl=N time=N.N ms
_REPLY_RE = re.compile(
    r"icmp_seq=(\d+)\s+ttl=(\d+)\s+time=([\d.]+)\s*ms"
)
# Match: rtt min/avg/max/mdev = N/N/N/N ms
_SUMMARY_RTT_RE = re.compile(
    r"rtt min/avg/max/mdev = ([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+)"
)
# Match: N packets transmitted, N received, N% packet loss
_SUMMARY_LOSS_RE = re.compile(
    r"(\d+) packets transmitted, (\d+) received, ([\d.]+)% packet loss"
)


def parse_ping_line(line: str) -> Optional[Dict[str, Any]]:
    """Parse a single ping reply line. Returns None if not a reply."""
    m = _REPLY_RE.search(line)
    if not m:
        return None
    return {
        "icmp_seq": int(m.group(1)),
        "ttl": int(m.group(2)),
        "time_ms": float(m.group(3)),
    }


def parse_ping_summary(lines: List[str]) -> Dict[str, Any]:
    """Parse ping summary lines into a dict."""
    result: Dict[str, Any] = {}
    for line in lines:
        m = _SUMMARY_LOSS_RE.search(line)
        if m:
            result["packets_sent"] = int(m.group(1))
            result["packets_received"] = int(m.group(2))
            result["loss_percent"] = float(m.group(3))
        m = _SUMMARY_RTT_RE.search(line)
        if m:
            result["rtt_min"] = float(m.group(1))
            result["rtt_avg"] = float(m.group(2))
            result["rtt_max"] = float(m.group(3))
            result["rtt_mdev"] = float(m.group(4))
    return result


def write_ping_csv(rows: List[Dict[str, Any]], filepath: str) -> None:
    """Append ping rows to CSV."""
    if not rows:
        return
    file_exists = os.path.exists(filepath)
    with open(filepath, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        if not file_exists:
            writer.writeheader()
        writer.writerows(rows)
```

- [ ] **Step 4: Run tests and verify they pass**

```bash
cd /home/qiqi/code/fish/bandwidth-checker && uv run pytest tests/test_latency_parser.py -v
```

Expected: all 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add collectors/latency.py tests/test_latency_parser.py
git commit -m "feat: ping latency parser with CSV output"
```

---

## Task 5: TCP Stats (ss) Parser

**Files:**
- Create: `collectors/tcp_stats.py`
- Test: `tests/test_tcp_stats_parser.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_tcp_stats_parser.py
from collectors.tcp_stats import parse_ss_output


def test_parse_ss_single_socket():
    # Real ss -tin output format
    ss_output = """ESTAB 0 0 10.0.0.1:5201 10.0.0.2:43210
\t cubic wscale:7,7 rto:204 rtt:25.5/3.2 ato:40 mss:1448 pmtu:9001 rcvmss:1448 advmss:8949 cwnd:10 bytes_sent:1234567 bytes_received:7654321 segs_out:1000 segs_in:900 data_segs_out:800 data_segs_in:700 send 4.5Mbps pacing_rate 9.0Mbps delivery_rate 4.2Mbps delivered:800 busy:5000ms retrans:0/5 reordering:3"""
    results = parse_ss_output(ss_output)
    assert len(results) == 1
    assert results[0]["rtt_ms"] == 25.5
    assert results[0]["rttvar_ms"] == 3.2
    assert results[0]["cwnd"] == 10
    assert results[0]["retrans_total"] == 5
    assert results[0]["local_port"] == 5201


def test_parse_ss_multiple_sockets():
    ss_output = """ESTAB 0 0 10.0.0.1:5201 10.0.0.2:43210
\t cubic rtt:25.5/3.2 cwnd:10 retrans:0/5
ESTAB 0 0 10.0.0.1:5201 10.0.0.2:43211
\t cubic rtt:30.1/4.0 cwnd:8 retrans:1/10"""
    results = parse_ss_output(ss_output)
    assert len(results) == 2
    assert results[0]["rtt_ms"] == 25.5
    assert results[1]["rtt_ms"] == 30.1


def test_parse_ss_empty():
    results = parse_ss_output("")
    assert results == []
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/qiqi/code/fish/bandwidth-checker && uv run pytest tests/test_tcp_stats_parser.py -v
```

Expected: FAIL

- [ ] **Step 3: Implement ss parser**

```python
# collectors/tcp_stats.py
"""TCP socket statistics collection via ss."""
import csv
import os
import re
from typing import Any, Dict, List


_RTT_RE = re.compile(r"rtt:([\d.]+)/([\d.]+)")
_CWND_RE = re.compile(r"cwnd:(\d+)")
_RETRANS_RE = re.compile(r"retrans:(\d+)/(\d+)")
_ESTAB_RE = re.compile(
    r"ESTAB\s+\d+\s+\d+\s+([\d.]+):(\d+)\s+([\d.]+):(\d+)"
)


def parse_ss_output(output: str) -> List[Dict[str, Any]]:
    """Parse ss -tin output into a list of per-socket dicts."""
    if not output.strip():
        return []

    results = []
    lines = output.strip().split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        m = _ESTAB_RE.match(line)
        if m:
            entry: Dict[str, Any] = {
                "local_addr": m.group(1),
                "local_port": int(m.group(2)),
                "remote_addr": m.group(3),
                "remote_port": int(m.group(4)),
                "rtt_ms": 0.0,
                "rttvar_ms": 0.0,
                "cwnd": 0,
                "retrans_current": 0,
                "retrans_total": 0,
            }
            # Look at next line(s) for socket details
            detail = ""
            while i + 1 < len(lines) and not _ESTAB_RE.match(lines[i + 1]):
                i += 1
                detail += " " + lines[i]

            m2 = _RTT_RE.search(detail)
            if m2:
                entry["rtt_ms"] = float(m2.group(1))
                entry["rttvar_ms"] = float(m2.group(2))

            m2 = _CWND_RE.search(detail)
            if m2:
                entry["cwnd"] = int(m2.group(1))

            m2 = _RETRANS_RE.search(detail)
            if m2:
                entry["retrans_current"] = int(m2.group(1))
                entry["retrans_total"] = int(m2.group(2))

            results.append(entry)
        i += 1
    return results


def write_ss_csv(rows: List[Dict[str, Any]], filepath: str) -> None:
    """Append ss stats rows to CSV."""
    if not rows:
        return
    file_exists = os.path.exists(filepath)
    with open(filepath, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        if not file_exists:
            writer.writeheader()
        writer.writerows(rows)
```

- [ ] **Step 4: Run tests and verify they pass**

```bash
cd /home/qiqi/code/fish/bandwidth-checker && uv run pytest tests/test_tcp_stats_parser.py -v
```

Expected: all 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add collectors/tcp_stats.py tests/test_tcp_stats_parser.py
git commit -m "feat: ss TCP stats parser with CSV output"
```

---

## Task 6: Credit Depletion Detector

**Files:**
- Create: logic inside `phases/sustained.py` (just the detector function for now)
- Test: `tests/test_depletion_detector.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_depletion_detector.py
from phases.sustained import DepletionDetector


def test_not_depleted_above_threshold():
    d = DepletionDetector(threshold_mbps=300, window_sec=10)
    for _ in range(15):
        d.add_sample(350_000_000)  # 350 Mbps in bps
    assert not d.is_depleted


def test_depleted_below_threshold():
    d = DepletionDetector(threshold_mbps=300, window_sec=10)
    for _ in range(10):
        d.add_sample(250_000_000)  # 250 Mbps
    assert d.is_depleted


def test_not_depleted_short_window():
    d = DepletionDetector(threshold_mbps=300, window_sec=10)
    for _ in range(9):  # only 9 samples, need 10
        d.add_sample(250_000_000)
    assert not d.is_depleted


def test_recovery_resets():
    d = DepletionDetector(threshold_mbps=300, window_sec=10)
    for _ in range(8):
        d.add_sample(250_000_000)
    d.add_sample(500_000_000)  # spike above threshold
    for _ in range(5):
        d.add_sample(250_000_000)
    assert not d.is_depleted  # window reset by the spike


def test_stays_depleted_once_detected():
    d = DepletionDetector(threshold_mbps=300, window_sec=10)
    for _ in range(10):
        d.add_sample(250_000_000)
    assert d.is_depleted
    d.add_sample(500_000_000)  # spike doesn't undo depletion
    assert d.is_depleted
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/qiqi/code/fish/bandwidth-checker && uv run pytest tests/test_depletion_detector.py -v
```

Expected: FAIL

- [ ] **Step 3: Implement detector**

```python
# phases/sustained.py
"""Phase 2: Sustained full-load until credit depletion."""


class DepletionDetector:
    """Detect network credit depletion from throughput samples."""

    def __init__(self, threshold_mbps: int = 300, window_sec: int = 10):
        self._threshold_bps = threshold_mbps * 1_000_000
        self._window = window_sec
        self._consecutive_below = 0
        self._detected = False

    def add_sample(self, bits_per_second: float) -> None:
        """Add a 1-second throughput sample."""
        if self._detected:
            return
        if bits_per_second < self._threshold_bps:
            self._consecutive_below += 1
        else:
            self._consecutive_below = 0
        if self._consecutive_below >= self._window:
            self._detected = True

    @property
    def is_depleted(self) -> bool:
        return self._detected
```

- [ ] **Step 4: Run tests and verify they pass**

```bash
cd /home/qiqi/code/fish/bandwidth-checker && uv run pytest tests/test_depletion_detector.py -v
```

Expected: all 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add phases/sustained.py tests/test_depletion_detector.py
git commit -m "feat: credit depletion detector with sliding window"
```

---

## Task 7: Remote Setup (SSH Helpers)

**Files:**
- Create: `setup/remote.py`
- No unit tests (SSH interaction) — tested manually during integration

- [ ] **Step 1: Implement remote.py**

```python
# setup/remote.py
"""Remote iperf3 server management via SSH."""
import subprocess
import sys
from typing import Optional

from config import TestConfig


def _ssh_cmd(cfg: TestConfig) -> list:
    """Build base SSH command."""
    cmd = ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=5"]
    if cfg.ssh_key:
        cmd.extend(["-i", cfg.ssh_key])
    cmd.append(f"{cfg.remote_user}@{cfg.remote_host}")
    return cmd


def run_ssh(cfg: TestConfig, remote_cmd: str, timeout: int = 30) -> subprocess.CompletedProcess:
    """Run a command on the remote host via SSH."""
    cmd = _ssh_cmd(cfg) + [remote_cmd]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def check_ssh(cfg: TestConfig) -> bool:
    """Verify SSH connectivity."""
    try:
        result = run_ssh(cfg, "echo ok", timeout=10)
        return result.returncode == 0 and "ok" in result.stdout
    except (subprocess.TimeoutExpired, OSError):
        return False


def check_iperf3(cfg: TestConfig) -> bool:
    """Verify iperf3 is installed on remote."""
    try:
        result = run_ssh(cfg, "iperf3 --version", timeout=10)
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def kill_remote_iperf3(cfg: TestConfig) -> None:
    """Kill any existing iperf3 processes on remote."""
    run_ssh(cfg, "pkill -f iperf3 || true", timeout=10)


def start_remote_iperf3(cfg: TestConfig, port: int) -> bool:
    """Start iperf3 server on remote at given port."""
    run_ssh(cfg, f"nohup iperf3 -s -p {port} > /dev/null 2>&1 &", timeout=10)
    import time
    time.sleep(1)  # Give it a moment to start
    # Verify it's running
    result = run_ssh(cfg, f"ss -tln | grep :{port}", timeout=10)
    return result.returncode == 0


def setup_remote_servers(cfg: TestConfig, ports: Optional[list] = None) -> bool:
    """Full remote setup: kill stale, start fresh servers, verify reachability."""
    if ports is None:
        ports = [cfg.iperf_base_port, cfg.iperf_base_port + 1]

    print("Pre-flight: checking SSH connectivity...", flush=True)
    if not check_ssh(cfg):
        print("ERROR: Cannot SSH to remote host", file=sys.stderr)
        return False

    print("Pre-flight: checking iperf3 on remote...", flush=True)
    if not check_iperf3(cfg):
        print("ERROR: iperf3 not found on remote", file=sys.stderr)
        return False

    print("Pre-flight: killing stale iperf3 processes...", flush=True)
    kill_remote_iperf3(cfg)

    for port in ports:
        print(f"Pre-flight: starting iperf3 server on port {port}...", flush=True)
        if not start_remote_iperf3(cfg, port):
            print(f"ERROR: Failed to start iperf3 on port {port}", file=sys.stderr)
            return False

    # Verify ports are reachable through security group (actual iperf3 handshake)
    print("Pre-flight: verifying port reachability (iperf3 handshake)...", flush=True)
    for port in ports:
        try:
            result = subprocess.run(
                ["iperf3", "-c", cfg.remote_host, "-p", str(port), "-t", "1"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                print(f"ERROR: Cannot reach iperf3 on port {port} — check security group", file=sys.stderr)
                return False
        except subprocess.TimeoutExpired:
            print(f"ERROR: iperf3 handshake timeout on port {port} — check security group", file=sys.stderr)
            return False

    print("Pre-flight: all checks passed.", flush=True)
    return True


def burst_credit_probe(cfg: TestConfig) -> Optional[float]:
    """Run a 10-second TCP test to check current burst credit state.

    Returns average throughput in Mbps, or None on failure.
    """
    import json
    cmd = [
        "iperf3", "-c", cfg.remote_host,
        "-p", str(cfg.iperf_base_port),
        "-t", "30", "-J",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
        if result.returncode != 0:
            return None
        data = json.loads(result.stdout)
        bps = data["end"]["sum_received"]["bits_per_second"]
        return bps / 1_000_000
    except (subprocess.TimeoutExpired, json.JSONDecodeError, KeyError):
        return None
```

- [ ] **Step 2: Commit**

```bash
git add setup/remote.py
git commit -m "feat: remote SSH helpers and iperf3 server management"
```

---

## Task 8: iperf3 Process Runner

**Files:**
- Modify: `collectors/iperf.py` — add `IperfRunner` class

- [ ] **Step 1: Add IperfRunner to iperf.py**

```python
# Add to collectors/iperf.py after existing functions:

import subprocess
import time
from config import TestConfig


class IperfRunner:
    """Manage an iperf3 client process and collect results."""

    def __init__(self, cfg: TestConfig, protocol: str, direction: str,
                 bandwidth_mbps: int, port: int, duration: int = 60,
                 small_packet: bool = False):
        """
        Args:
            protocol: "tcp" or "udp"
            direction: "egress", "ingress", or "bidir"
            bandwidth_mbps: target bandwidth in Mbps
            port: iperf3 server port
            duration: test duration in seconds
            small_packet: if True, use -l 512 for UDP
        """
        self.cfg = cfg
        self.protocol = protocol
        self.direction = direction
        self.bandwidth_mbps = bandwidth_mbps
        self.port = port
        self.duration = duration
        self.small_packet = small_packet
        self._process: subprocess.Popen = None

    def build_command(self) -> list:
        """Build iperf3 command line."""
        cmd = [
            "iperf3", "-c", self.cfg.remote_host,
            "-p", str(self.port),
            "-t", str(self.duration),
            "-J",  # JSON output
        ]
        if self.protocol == "udp":
            cmd.extend(["-u", "-b", f"{self.bandwidth_mbps}M"])
            if self.small_packet:
                cmd.extend(["-l", "512"])
        else:
            # TCP: use parallel streams for high bandwidth
            if self.bandwidth_mbps >= 1000:
                cmd.extend(["-P", str(self.cfg.tcp_parallel_streams)])

        if self.direction == "ingress":
            cmd.append("-R")
        elif self.direction == "bidir":
            cmd.append("--bidir")

        return cmd

    def run(self) -> dict:
        """Run iperf3 and return parsed JSON. Blocking."""
        cmd = self.build_command()
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=self.duration + 30,
            )
            if result.returncode != 0:
                return {"error": result.stderr, "intervals": []}
            return json.loads(result.stdout)
        except subprocess.TimeoutExpired:
            return {"error": "timeout", "intervals": []}
        except json.JSONDecodeError:
            return {"error": "invalid json", "intervals": []}

    def run_background(self) -> None:
        """Start iperf3 in background (non-blocking). Use wait() to get result."""
        cmd = self.build_command()
        self._process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )

    def wait(self, timeout: int = None) -> dict:
        """Wait for background process and return parsed JSON."""
        if not self._process:
            return {"error": "no process", "intervals": []}
        try:
            stdout, stderr = self._process.communicate(timeout=timeout)
            if self._process.returncode != 0:
                return {"error": stderr, "intervals": []}
            return json.loads(stdout)
        except subprocess.TimeoutExpired:
            self._process.kill()
            return {"error": "timeout", "intervals": []}
        except json.JSONDecodeError:
            return {"error": "invalid json", "intervals": []}

    def kill(self) -> None:
        """Kill the background process if running."""
        if self._process and self._process.poll() is None:
            self._process.kill()
            self._process.wait(timeout=5)
```

- [ ] **Step 2: Commit**

```bash
git add collectors/iperf.py
git commit -m "feat: IperfRunner for iperf3 process lifecycle management"
```

---

## Task 8b: IperfRunner.build_command() Tests

**Files:**
- Test: `tests/test_iperf_runner.py`

- [ ] **Step 1: Write tests for command building**

```python
# tests/test_iperf_runner.py
from config import TestConfig
from collectors.iperf import IperfRunner


def _cfg():
    return TestConfig(remote_host="10.0.0.1", remote_user="ec2-user")


def test_tcp_egress_command():
    r = IperfRunner(_cfg(), "tcp", "egress", 256, 5201, duration=60)
    cmd = r.build_command()
    assert "iperf3" in cmd
    assert "-c" in cmd and "10.0.0.1" in cmd
    assert "-p" in cmd and "5201" in cmd
    assert "-t" in cmd and "60" in cmd
    assert "-J" in cmd
    assert "-R" not in cmd
    assert "--bidir" not in cmd
    assert "-u" not in cmd


def test_tcp_ingress_uses_reverse():
    r = IperfRunner(_cfg(), "tcp", "ingress", 256, 5201)
    cmd = r.build_command()
    assert "-R" in cmd
    assert "--bidir" not in cmd


def test_tcp_bidir():
    r = IperfRunner(_cfg(), "tcp", "bidir", 256, 5201)
    cmd = r.build_command()
    assert "--bidir" in cmd
    assert "-R" not in cmd


def test_udp_flags():
    r = IperfRunner(_cfg(), "udp", "egress", 500, 5201)
    cmd = r.build_command()
    assert "-u" in cmd
    assert "-b" in cmd
    assert "500M" in cmd


def test_udp_small_packet():
    r = IperfRunner(_cfg(), "udp", "egress", 256, 5201, small_packet=True)
    cmd = r.build_command()
    assert "-l" in cmd
    assert "512" in cmd


def test_tcp_high_bandwidth_uses_parallel():
    r = IperfRunner(_cfg(), "tcp", "bidir", 1000, 5201)
    cmd = r.build_command()
    assert "-P" in cmd
    assert "4" in cmd


def test_tcp_low_bandwidth_no_parallel():
    r = IperfRunner(_cfg(), "tcp", "egress", 256, 5201)
    cmd = r.build_command()
    assert "-P" not in cmd
```

- [ ] **Step 2: Run tests to verify they pass (implementation from Task 8)**

```bash
cd /home/qiqi/code/fish/bandwidth-checker && uv run pytest tests/test_iperf_runner.py -v
```

Expected: all 7 tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_iperf_runner.py
git commit -m "test: IperfRunner.build_command() flag correctness tests"
```

---

## Task 9: Latency and TCP Stats Collectors (Process Wrappers)

**Files:**
- Modify: `collectors/latency.py` — add `LatencyCollector` class
- Modify: `collectors/tcp_stats.py` — add `TcpStatsCollector` class

- [ ] **Step 1: Add LatencyCollector to latency.py**

```python
# Add to collectors/latency.py after existing functions:

import subprocess
import threading
import time


class LatencyCollector:
    """Run ping in background and collect RTT data to CSV."""

    def __init__(self, remote_host: str, csv_path: str, interval: float = 1.0):
        self.remote_host = remote_host
        self.csv_path = csv_path
        self.interval = interval
        self._process: subprocess.Popen = None
        self._thread: threading.Thread = None
        self._stop = threading.Event()
        self.samples: list = []

    def start(self) -> None:
        """Start ping process and reader thread."""
        self._stop.clear()
        self._process = subprocess.Popen(
            ["ping", "-i", str(self.interval), self.remote_host],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()

    def _reader(self) -> None:
        """Read ping output line by line."""
        for line in self._process.stdout:
            if self._stop.is_set():
                break
            parsed = parse_ping_line(line.strip())
            if parsed:
                parsed["timestamp"] = time.time()
                self.samples.append(parsed)
                write_ping_csv([parsed], self.csv_path)

    def stop(self) -> None:
        """Stop ping process and reader thread."""
        self._stop.set()
        if self._process and self._process.poll() is None:
            self._process.kill()
            self._process.wait(timeout=5)
        if self._thread:
            self._thread.join(timeout=5)

    def get_recent_avg_rtt(self, last_n: int = 5) -> float:
        """Return average RTT of last N samples."""
        recent = self.samples[-last_n:]
        if not recent:
            return 0.0
        return sum(s["time_ms"] for s in recent) / len(recent)
```

- [ ] **Step 2: Add TcpStatsCollector to tcp_stats.py**

```python
# Add to collectors/tcp_stats.py after existing functions:

import subprocess
import threading
import time


class TcpStatsCollector:
    """Poll ss for TCP stats at regular intervals."""

    def __init__(self, remote_host: str, csv_path: str, interval: float = 1.0):
        self.remote_host = remote_host
        self.csv_path = csv_path
        self.interval = interval
        self._thread: threading.Thread = None
        self._stop = threading.Event()
        self.samples: list = []

    def start(self) -> None:
        """Start polling thread."""
        self._stop.clear()
        self._thread = threading.Thread(target=self._poller, daemon=True)
        self._thread.start()

    def _poller(self) -> None:
        """Poll ss every interval."""
        while not self._stop.is_set():
            try:
                result = subprocess.run(
                    ["ss", "-tin", "dst", self.remote_host],
                    capture_output=True, text=True, timeout=5,
                )
                if result.returncode == 0:
                    entries = parse_ss_output(result.stdout)
                    ts = time.time()
                    for entry in entries:
                        entry["timestamp"] = ts
                    self.samples.extend(entries)
                    write_ss_csv(entries, self.csv_path)
            except (subprocess.TimeoutExpired, OSError):
                pass
            self._stop.wait(self.interval)

    def stop(self) -> None:
        """Stop polling thread."""
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def get_aggregate(self, last_n_polls: int = 5) -> dict:
        """Return aggregate stats from last N polling rounds.

        Groups samples by timestamp (each poll produces multiple socket entries),
        then aggregates across the last N polls.
        """
        if not self.samples:
            return {"rtt_ms": 0, "cwnd": 0, "retrans_total": 0}

        # Group by timestamp to get per-poll aggregates
        from collections import defaultdict
        polls = defaultdict(list)
        for s in self.samples:
            polls[s["timestamp"]].append(s)

        sorted_polls = sorted(polls.items(), key=lambda x: x[0])
        recent_polls = sorted_polls[-last_n_polls:]

        if not recent_polls:
            return {"rtt_ms": 0, "cwnd": 0, "retrans_total": 0}

        # Per-poll: average RTT across sockets, sum cwnd, max retrans
        poll_rtts = []
        poll_cwnds = []
        poll_retrans = []
        for _ts, entries in recent_polls:
            if entries:
                poll_rtts.append(sum(e["rtt_ms"] for e in entries) / len(entries))
                poll_cwnds.append(sum(e["cwnd"] for e in entries))
                poll_retrans.append(sum(e["retrans_total"] for e in entries))

        return {
            "rtt_ms": sum(poll_rtts) / len(poll_rtts) if poll_rtts else 0,
            "cwnd": sum(poll_cwnds) / len(poll_cwnds) if poll_cwnds else 0,
            "retrans_total": max(poll_retrans) if poll_retrans else 0,
        }
```

- [ ] **Step 3: Commit**

```bash
git add collectors/latency.py collectors/tcp_stats.py
git commit -m "feat: latency and TCP stats background collectors"
```

---

## Task 10: Phase 1 — Step-Up Pressure Test

**Files:**
- Create: `phases/step_up.py`

- [ ] **Step 1: Implement step_up.py**

```python
# phases/step_up.py
"""Phase 1: Step-up pressure test."""
import os
import time
from typing import Callable, Optional

from config import TestConfig
from collectors.iperf import IperfRunner, parse_iperf_tcp_json, parse_iperf_udp_json, write_iperf_csv
from collectors.latency import LatencyCollector
from collectors.tcp_stats import TcpStatsCollector


def run_single_test(
    cfg: TestConfig,
    level: dict,
    protocol: str,
    direction: str,
    port: int,
    data_dir: str,
    small_packet: bool = False,
) -> dict:
    """Run one iperf3 test with parallel ping and ss collection.

    Returns dict with parsed iperf results and collector summaries.
    """
    bw = level["bandwidth_mbps"]
    label = f"{bw}M_{protocol}_{direction}"
    if small_packet:
        label += "_small"
    print(f"  Running: {label} ...", flush=True)

    # Start parallel collectors
    ping_path = os.path.join(data_dir, "step_up_ping.csv")
    ss_path = os.path.join(data_dir, "step_up_ss.csv")

    ping_collector = LatencyCollector(cfg.remote_host, ping_path)
    ss_collector = TcpStatsCollector(cfg.remote_host, ss_path) if protocol == "tcp" else None

    ping_collector.start()
    if ss_collector:
        ss_collector.start()

    # Run iperf3
    runner = IperfRunner(
        cfg, protocol=protocol, direction=direction,
        bandwidth_mbps=bw, port=port,
        duration=cfg.test_duration, small_packet=small_packet,
    )
    iperf_data = runner.run()

    # Stop collectors
    ping_collector.stop()
    if ss_collector:
        ss_collector.stop()

    # Parse and persist iperf results
    if protocol == "tcp":
        rows = parse_iperf_tcp_json(iperf_data)
        csv_path = os.path.join(data_dir, "step_up_iperf_tcp.csv")
    else:
        rows = parse_iperf_udp_json(iperf_data)
        csv_path = os.path.join(data_dir, "step_up_iperf_udp.csv")

    # Add metadata to each row
    for row in rows:
        row["level_mbps"] = bw
        row["direction"] = direction
        row["protocol"] = protocol
        row["small_packet"] = small_packet

    write_iperf_csv(rows, csv_path)

    return {
        "label": label,
        "level_mbps": bw,
        "protocol": protocol,
        "direction": direction,
        "small_packet": small_packet,
        "iperf_rows": rows,
        "avg_rtt": ping_collector.get_recent_avg_rtt(last_n=10),
        "ping_samples": len(ping_collector.samples),
        "ss_aggregate": ss_collector.get_aggregate() if ss_collector else {},
    }


def run_step_up(cfg: TestConfig, on_progress: Optional[Callable] = None) -> list:
    """Run Phase 1: step-up pressure test.

    Returns list of per-test result dicts.
    """
    data_dir = cfg.data_dir
    os.makedirs(data_dir, exist_ok=True)
    port = cfg.iperf_base_port
    all_results = []

    for level in cfg.step_up_levels:
        bw = level["bandwidth_mbps"]
        print(f"\n=== Level: {bw} Mbps ===", flush=True)

        # Build list of all tests for this level
        tests = []
        for direction in level["tcp_directions"]:
            tests.append(("tcp", direction, False))
        for direction in level["udp_directions"]:
            tests.append(("udp", direction, False))
        if level.get("small_packet_udp"):
            for direction in level["udp_directions"]:
                tests.append(("udp", direction, True))

        for i, (proto, direction, small_pkt) in enumerate(tests):
            result = run_single_test(cfg, level, proto, direction, port, data_dir, small_pkt)
            all_results.append(result)
            if on_progress:
                on_progress(result)
            # Cooldown between tests, but not after the very last test of the last level
            is_last = (level == cfg.step_up_levels[-1] and i == len(tests) - 1)
            if not is_last:
                time.sleep(cfg.cooldown)

    return all_results
```

- [ ] **Step 2: Commit**

```bash
git add phases/step_up.py
git commit -m "feat: Phase 1 step-up pressure test orchestration"
```

---

## Task 11: Phase 2 — Sustained Full-Load

**Files:**
- Modify: `phases/sustained.py` — add `run_sustained` function

- [ ] **Step 1: Add run_sustained to sustained.py**

```python
# Add to phases/sustained.py after DepletionDetector class:

import json
import os
import subprocess
import time
from typing import Optional

from config import TestConfig
from collectors.iperf import IperfRunner, parse_iperf_tcp_json, parse_iperf_udp_json, write_iperf_csv
from collectors.latency import LatencyCollector
from collectors.tcp_stats import TcpStatsCollector


def run_sustained(cfg: TestConfig) -> dict:
    """Run Phase 2: sustained full-load until credit depletion.

    Returns dict with depletion time and collected data summary.
    """
    data_dir = cfg.data_dir
    os.makedirs(data_dir, exist_ok=True)

    port_tcp = cfg.iperf_base_port
    port_udp = cfg.iperf_base_port + 1

    print("\n=== Phase 2: Sustained Full-Load ===", flush=True)

    # Start parallel collectors
    ping_collector = LatencyCollector(
        cfg.remote_host,
        os.path.join(data_dir, "sustained_ping.csv"),
    )
    ss_collector = TcpStatsCollector(
        cfg.remote_host,
        os.path.join(data_dir, "sustained_ss.csv"),
    )
    ping_collector.start()
    ss_collector.start()

    detector = DepletionDetector(
        threshold_mbps=cfg.depletion_threshold_mbps,
        window_sec=cfg.depletion_window_sec,
    )

    start_time = time.time()
    depletion_time: Optional[float] = None
    tcp_csv = os.path.join(data_dir, "sustained_iperf_tcp.csv")
    udp_csv = os.path.join(data_dir, "sustained_iperf_udp.csv")

    # Use 10-second iperf intervals for fine-grained depletion detection
    # (iperf3 JSON is only available after each run completes)
    interval_duration = 10
    elapsed = 0

    while elapsed < cfg.phase2_timeout:
        remaining = min(interval_duration, cfg.phase2_timeout - int(elapsed))
        if remaining <= 0:
            break

        if int(elapsed) % 60 == 0:
            print(f"  Sustained: {int(elapsed)}s elapsed...", flush=True)

        # Run TCP and UDP in parallel
        tcp_runner = IperfRunner(
            cfg, protocol="tcp", direction="bidir",
            bandwidth_mbps=5000, port=port_tcp,
            duration=remaining,
        )
        udp_runner = IperfRunner(
            cfg, protocol="udp", direction="bidir",
            bandwidth_mbps=5000, port=port_udp,
            duration=remaining,
        )

        tcp_runner.run_background()
        udp_runner.run_background()

        tcp_data = tcp_runner.wait(timeout=remaining + 30)
        udp_data = udp_runner.wait(timeout=remaining + 30)

        # Check for iperf3 crash (not depletion) — retry the interval
        tcp_crashed = tcp_data.get("error") and "timeout" not in str(tcp_data["error"])
        if tcp_crashed:
            print(f"  WARNING: iperf3 TCP crashed, restarting server...", flush=True)
            from setup.remote import start_remote_iperf3
            start_remote_iperf3(cfg, port_tcp)
            time.sleep(2)
            elapsed = time.time() - start_time
            continue  # Retry this interval, don't parse error data

        udp_crashed = udp_data.get("error") and "timeout" not in str(udp_data["error"])
        if udp_crashed:
            from setup.remote import start_remote_iperf3
            start_remote_iperf3(cfg, port_udp)
            time.sleep(2)

        # Parse and persist
        tcp_rows = parse_iperf_tcp_json(tcp_data)
        udp_rows = parse_iperf_udp_json(udp_data) if not udp_crashed else []

        for row in tcp_rows:
            row["phase_elapsed_sec"] = elapsed + row.get("start", 0)
        for row in udp_rows:
            row["phase_elapsed_sec"] = elapsed + row.get("start", 0)

        write_iperf_csv(tcp_rows, tcp_csv)
        write_iperf_csv(udp_rows, udp_csv)

        # Feed throughput samples to depletion detector
        for row in tcp_rows:
            detector.add_sample(row.get("bits_per_second", 0))
            if detector.is_depleted and depletion_time is None:
                depletion_time = elapsed + row.get("start", 0)
                print(f"  *** Credit depletion detected at {depletion_time:.0f}s ***", flush=True)

        elapsed = time.time() - start_time

        if detector.is_depleted:
            break

    # Stop collectors
    ping_collector.stop()
    ss_collector.stop()

    return {
        "depletion_time_sec": depletion_time,
        "total_elapsed_sec": time.time() - start_time,
        "depleted": detector.is_depleted,
    }
```

- [ ] **Step 2: Commit**

```bash
git add phases/sustained.py
git commit -m "feat: Phase 2 sustained full-load with depletion detection"
```

---

## Task 12: Phase 3 — Throttled Observation

**Files:**
- Create: `phases/throttled.py`

- [ ] **Step 1: Implement throttled.py**

```python
# phases/throttled.py
"""Phase 3: Throttled state observation."""
import os
import time
from typing import Optional

from config import TestConfig
from collectors.iperf import IperfRunner, parse_iperf_tcp_json, parse_iperf_udp_json, write_iperf_csv
from collectors.latency import LatencyCollector
from collectors.tcp_stats import TcpStatsCollector


def run_throttled(cfg: TestConfig) -> dict:
    """Run Phase 3: observe throttled state behavior.

    Returns dict with steady-state metrics.
    """
    data_dir = cfg.data_dir
    os.makedirs(data_dir, exist_ok=True)

    port = cfg.iperf_base_port
    print("\n=== Phase 3: Throttled State Observation ===", flush=True)

    # Start parallel collectors
    ping_collector = LatencyCollector(
        cfg.remote_host,
        os.path.join(data_dir, "throttled_ping.csv"),
    )
    ss_collector = TcpStatsCollector(
        cfg.remote_host,
        os.path.join(data_dir, "throttled_ss.csv"),
    )
    ping_collector.start()
    ss_collector.start()

    tcp_csv = os.path.join(data_dir, "throttled_iperf_tcp.csv")
    udp_csv = os.path.join(data_dir, "throttled_iperf_udp.csv")

    # Part 1: Steady-state observation (~6 min)
    print("  Observing steady-state throttled behavior (6 min)...", flush=True)

    # TCP bidir
    tcp_runner = IperfRunner(
        cfg, protocol="tcp", direction="bidir",
        bandwidth_mbps=5000, port=port, duration=180,
    )
    udp_runner = IperfRunner(
        cfg, protocol="udp", direction="bidir",
        bandwidth_mbps=5000, port=port + 1, duration=180,
    )
    tcp_runner.run_background()
    udp_runner.run_background()
    tcp_data = tcp_runner.wait(timeout=210)
    udp_data = udp_runner.wait(timeout=210)

    tcp_rows = parse_iperf_tcp_json(tcp_data)
    udp_rows = parse_iperf_udp_json(udp_data)
    for row in tcp_rows:
        row["sub_phase"] = "steady"
    for row in udp_rows:
        row["sub_phase"] = "steady"
    write_iperf_csv(tcp_rows, tcp_csv)
    write_iperf_csv(udp_rows, udp_csv)

    # Part 2: Mini step-up replay (~4 min)
    print("  Mini step-up replay in throttled state...", flush=True)
    mini_levels = [50, 128, 256, 384]

    for bw in mini_levels:
        print(f"    Mini step-up: {bw} Mbps TCP+UDP...", flush=True)

        tcp_r = IperfRunner(
            cfg, protocol="tcp", direction="bidir",
            bandwidth_mbps=bw, port=port, duration=30,
        )
        udp_r = IperfRunner(
            cfg, protocol="udp", direction="bidir",
            bandwidth_mbps=bw, port=port + 1, duration=30,
        )
        tcp_d = tcp_r.run()
        udp_d = udp_r.run()

        tcp_mini = parse_iperf_tcp_json(tcp_d)
        udp_mini = parse_iperf_udp_json(udp_d)
        for row in tcp_mini:
            row["sub_phase"] = f"mini_{bw}"
        for row in udp_mini:
            row["sub_phase"] = f"mini_{bw}"
        write_iperf_csv(tcp_mini, tcp_csv)
        write_iperf_csv(udp_mini, udp_csv)

        time.sleep(cfg.cooldown)

    # Stop collectors
    ping_collector.stop()
    ss_collector.stop()

    return {
        "steady_tcp_rows": len(tcp_rows),
        "steady_udp_rows": len(udp_rows),
        "mini_levels_tested": mini_levels,
    }
```

- [ ] **Step 2: Commit**

```bash
git add phases/throttled.py
git commit -m "feat: Phase 3 throttled state observation with mini step-up"
```

---

## Task 13: Chart Generation

**Files:**
- Create: `report/charts.py`
- Test: `tests/test_charts.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_charts.py
import os
import tempfile
from report.charts import generate_step_up_charts


def test_generate_step_up_charts_creates_files():
    """Test that chart generation creates PNG files from sample data."""
    tcp_data = [
        {"level_mbps": 50, "bits_per_second": 50000000, "retransmits": 0, "direction": "egress"},
        {"level_mbps": 256, "bits_per_second": 256000000, "retransmits": 5, "direction": "egress"},
        {"level_mbps": 1000, "bits_per_second": 900000000, "retransmits": 20, "direction": "bidir"},
    ]
    udp_data = [
        {"level_mbps": 50, "lost_percent": 0, "jitter_ms": 0.1, "direction": "egress"},
        {"level_mbps": 256, "lost_percent": 1.5, "jitter_ms": 0.8, "direction": "egress"},
        {"level_mbps": 1000, "lost_percent": 10, "jitter_ms": 2.5, "direction": "bidir"},
    ]
    ping_data = [
        {"level_mbps": 50, "rtt_avg": 25.0},
        {"level_mbps": 256, "rtt_avg": 28.0},
        {"level_mbps": 1000, "rtt_avg": 45.0},
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        paths = generate_step_up_charts(tcp_data, udp_data, ping_data, tmpdir)
        assert len(paths) == 5
        for p in paths:
            assert os.path.exists(p)
            assert p.endswith(".png")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/qiqi/code/fish/bandwidth-checker && uv run pytest tests/test_charts.py -v
```

Expected: FAIL

- [ ] **Step 3: Implement charts.py**

```python
# report/charts.py
"""Matplotlib chart generation for bandwidth test reports."""
import os
from typing import Any, Dict, List

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def _save(fig, path: str) -> str:
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def generate_step_up_charts(
    tcp_data: List[Dict],
    udp_data: List[Dict],
    ping_data: List[Dict],
    output_dir: str,
) -> List[str]:
    """Generate Phase 1 step-up charts. Returns list of PNG paths."""
    os.makedirs(output_dir, exist_ok=True)
    paths = []

    # 1. TCP throughput across levels
    fig, ax = plt.subplots(figsize=(10, 5))
    levels = [d["level_mbps"] for d in tcp_data]
    throughput = [d["bits_per_second"] / 1e6 for d in tcp_data]
    ax.plot(levels, throughput, "o-", color="tab:blue")
    ax.set_xlabel("Target Bandwidth (Mbps)")
    ax.set_ylabel("Actual Throughput (Mbps)")
    ax.set_title("TCP Throughput vs Target Bandwidth")
    ax.axhline(y=256, color="red", linestyle="--", label="Baseline (256 Mbps)")
    ax.legend()
    ax.grid(True, alpha=0.3)
    paths.append(_save(fig, os.path.join(output_dir, "step_up_tcp_throughput.png")))

    # 2. UDP packet loss rate
    fig, ax = plt.subplots(figsize=(10, 5))
    levels = [d["level_mbps"] for d in udp_data]
    loss = [d["lost_percent"] for d in udp_data]
    ax.plot(levels, loss, "o-", color="tab:red")
    ax.set_xlabel("Target Bandwidth (Mbps)")
    ax.set_ylabel("Packet Loss (%)")
    ax.set_title("UDP Packet Loss vs Target Bandwidth")
    ax.grid(True, alpha=0.3)
    paths.append(_save(fig, os.path.join(output_dir, "step_up_udp_loss.png")))

    # 3. RTT across levels
    fig, ax = plt.subplots(figsize=(10, 5))
    levels = [d["level_mbps"] for d in ping_data]
    rtt = [d["rtt_avg"] for d in ping_data]
    ax.plot(levels, rtt, "o-", color="tab:green")
    ax.set_xlabel("Target Bandwidth (Mbps)")
    ax.set_ylabel("Average RTT (ms)")
    ax.set_title("RTT (Queueing Delay) vs Target Bandwidth")
    ax.grid(True, alpha=0.3)
    paths.append(_save(fig, os.path.join(output_dir, "step_up_rtt.png")))

    # 4. TCP retransmission rate
    fig, ax = plt.subplots(figsize=(10, 5))
    levels = [d["level_mbps"] for d in tcp_data]
    retrans = [d["retransmits"] for d in tcp_data]
    ax.bar(levels, retrans, width=30, color="tab:orange")
    ax.set_xlabel("Target Bandwidth (Mbps)")
    ax.set_ylabel("Retransmissions")
    ax.set_title("TCP Retransmissions vs Target Bandwidth")
    ax.grid(True, alpha=0.3)
    paths.append(_save(fig, os.path.join(output_dir, "step_up_tcp_retrans.png")))

    # 5. UDP jitter
    fig, ax = plt.subplots(figsize=(10, 5))
    levels = [d["level_mbps"] for d in udp_data]
    jitter = [d["jitter_ms"] for d in udp_data]
    ax.plot(levels, jitter, "o-", color="tab:purple")
    ax.set_xlabel("Target Bandwidth (Mbps)")
    ax.set_ylabel("Jitter (ms)")
    ax.set_title("UDP Jitter vs Target Bandwidth")
    ax.grid(True, alpha=0.3)
    paths.append(_save(fig, os.path.join(output_dir, "step_up_udp_jitter.png")))

    return paths


def generate_timeline_charts(
    tcp_csv: str,
    udp_csv: str,
    ping_csv: str,
    output_dir: str,
    phase_boundaries: List[Dict] = None,
) -> List[str]:
    """Generate full-test timeline charts from CSV data. Returns list of PNG paths."""
    import csv

    os.makedirs(output_dir, exist_ok=True)
    paths = []

    # Read CSV data
    def read_csv(path):
        if not os.path.exists(path):
            return []
        with open(path) as f:
            return list(csv.DictReader(f))

    tcp_rows = read_csv(tcp_csv)
    udp_rows = read_csv(udp_csv)
    ping_rows = read_csv(ping_csv)

    # 1. Throughput timeline
    if tcp_rows:
        fig, ax = plt.subplots(figsize=(14, 5))
        x = [float(r.get("phase_elapsed_sec", r.get("start", 0))) for r in tcp_rows]
        y = [float(r["bits_per_second"]) / 1e6 for r in tcp_rows]
        ax.plot(x, y, linewidth=0.5, color="tab:blue")
        ax.set_xlabel("Time (seconds)")
        ax.set_ylabel("Throughput (Mbps)")
        ax.set_title("TCP Throughput Timeline")
        ax.axhline(y=256, color="red", linestyle="--", alpha=0.5, label="Baseline")
        if phase_boundaries:
            for pb in phase_boundaries:
                ax.axvline(x=pb["time"], color="gray", linestyle=":", alpha=0.5)
                ax.text(pb["time"], ax.get_ylim()[1] * 0.95, pb["label"], fontsize=8)
        ax.legend()
        ax.grid(True, alpha=0.3)
        paths.append(_save(fig, os.path.join(output_dir, "timeline_throughput.png")))

    # 2. RTT timeline
    if ping_rows:
        fig, ax = plt.subplots(figsize=(14, 5))
        x = [float(r.get("timestamp", 0)) for r in ping_rows]
        if x and x[0] > 0:
            x0 = x[0]
            x = [t - x0 for t in x]
        y = [float(r["time_ms"]) for r in ping_rows]
        ax.plot(x, y, linewidth=0.5, color="tab:green")
        ax.set_xlabel("Time (seconds)")
        ax.set_ylabel("RTT (ms)")
        ax.set_title("RTT Timeline")
        ax.grid(True, alpha=0.3)
        paths.append(_save(fig, os.path.join(output_dir, "timeline_rtt.png")))

    # 3. Packet loss timeline
    if udp_rows:
        fig, ax = plt.subplots(figsize=(14, 5))
        x = [float(r.get("phase_elapsed_sec", r.get("start", 0))) for r in udp_rows]
        y = [float(r["lost_percent"]) for r in udp_rows]
        ax.plot(x, y, linewidth=0.5, color="tab:red")
        ax.set_xlabel("Time (seconds)")
        ax.set_ylabel("Packet Loss (%)")
        ax.set_title("UDP Packet Loss Timeline")
        ax.grid(True, alpha=0.3)
        paths.append(_save(fig, os.path.join(output_dir, "timeline_loss.png")))

    # 4. TCP retransmission timeline
    if tcp_rows:
        fig, ax = plt.subplots(figsize=(14, 5))
        x = [float(r.get("phase_elapsed_sec", r.get("start", 0))) for r in tcp_rows]
        y = [int(r.get("retransmits", 0)) for r in tcp_rows]
        ax.plot(x, y, linewidth=0.5, color="tab:orange")
        ax.set_xlabel("Time (seconds)")
        ax.set_ylabel("Retransmissions / sec")
        ax.set_title("TCP Retransmission Timeline")
        ax.grid(True, alpha=0.3)
        paths.append(_save(fig, os.path.join(output_dir, "timeline_retrans.png")))

    return paths


def generate_comparison_chart(
    pre_throttle: Dict[str, float],
    post_throttle: Dict[str, float],
    output_dir: str,
) -> str:
    """Generate pre/post throttle comparison bar chart."""
    os.makedirs(output_dir, exist_ok=True)

    fig, axes = plt.subplots(1, 4, figsize=(16, 5))
    metrics = [
        ("Throughput (Mbps)", "throughput_mbps"),
        ("RTT (ms)", "rtt_ms"),
        ("Packet Loss (%)", "loss_percent"),
        ("Retransmissions/s", "retransmits"),
    ]

    for ax, (title, key) in zip(axes, metrics):
        pre = pre_throttle.get(key, 0)
        post = post_throttle.get(key, 0)
        bars = ax.bar(["Pre-throttle", "Post-throttle"], [pre, post],
                       color=["tab:blue", "tab:red"])
        ax.set_title(title)
        ax.bar_label(bars, fmt="%.1f")

    fig.suptitle("Pre/Post Throttle Comparison", fontsize=14)
    fig.tight_layout()
    path = os.path.join(output_dir, "comparison.png")
    return _save(fig, path)
```

- [ ] **Step 4: Run tests and verify they pass**

```bash
cd /home/qiqi/code/fish/bandwidth-checker && uv run pytest tests/test_charts.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add report/charts.py tests/test_charts.py
git commit -m "feat: matplotlib chart generation for all report types"
```

---

## Task 14: HTML Report Generator

**Files:**
- Create: `report/generator.py`
- Test: `tests/test_report_generator.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_report_generator.py
import os
import tempfile
from report.generator import generate_step_up_report


def test_generate_step_up_report_creates_html():
    step_up_results = [
        {
            "label": "50M_tcp_egress",
            "iperf_rows": [{"bits_per_second": 50000000, "retransmits": 0}],
            "avg_rtt": 25.0,
            "ping_samples": 60,
            "ss_aggregate": {"rtt_ms": 25.0, "cwnd": 10, "retrans_total": 0},
        },
        {
            "label": "256M_tcp_egress",
            "iperf_rows": [{"bits_per_second": 256000000, "retransmits": 5}],
            "avg_rtt": 30.0,
            "ping_samples": 60,
            "ss_aggregate": {"rtt_ms": 30.0, "cwnd": 8, "retrans_total": 5},
        },
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        path = generate_step_up_report(step_up_results, tmpdir)
        assert os.path.exists(path)
        assert path.endswith(".html")
        with open(path) as f:
            html = f.read()
        assert "50M_tcp_egress" in html
        assert "256M_tcp_egress" in html
        assert "<table" in html
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/qiqi/code/fish/bandwidth-checker && uv run pytest tests/test_report_generator.py -v
```

Expected: FAIL

- [ ] **Step 3: Implement report generator**

```python
# report/generator.py
"""HTML report generation."""
import os
from typing import Any, Dict, List, Optional


def _html_header(title: str) -> str:
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; margin: 40px; background: #f8f9fa; }}
h1 {{ color: #333; border-bottom: 2px solid #007bff; padding-bottom: 10px; }}
h2 {{ color: #555; margin-top: 30px; }}
table {{ border-collapse: collapse; width: 100%; margin: 15px 0; background: white; }}
th, td {{ border: 1px solid #ddd; padding: 8px 12px; text-align: right; }}
th {{ background: #007bff; color: white; }}
tr:nth-child(even) {{ background: #f2f2f2; }}
.metric-good {{ color: #28a745; }}
.metric-warn {{ color: #ffc107; }}
.metric-bad {{ color: #dc3545; }}
img {{ max-width: 100%; margin: 10px 0; border: 1px solid #ddd; }}
.summary {{ background: white; padding: 20px; border-radius: 8px; border-left: 4px solid #007bff; margin: 20px 0; }}
</style>
</head>
<body>
"""


def _html_footer() -> str:
    return "</body></html>"


def _results_table(results: List[Dict]) -> str:
    """Generate HTML table from step-up results."""
    rows = ""
    for r in results:
        iperf = r.get("iperf_rows", [{}])
        avg_bps = sum(row.get("bits_per_second", 0) for row in iperf) / max(len(iperf), 1)
        avg_retrans = sum(row.get("retransmits", 0) for row in iperf) / max(len(iperf), 1)
        avg_loss = sum(row.get("lost_percent", 0) for row in iperf) / max(len(iperf), 1)

        rows += f"""<tr>
<td style="text-align:left">{r['label']}</td>
<td>{avg_bps/1e6:.1f}</td>
<td>{r.get('avg_rtt', 0):.1f}</td>
<td>{avg_retrans:.0f}</td>
<td>{avg_loss:.1f}</td>
<td>{r.get('ping_samples', 0)}</td>
</tr>"""

    return f"""<table>
<tr><th>Test</th><th>Throughput (Mbps)</th><th>Avg RTT (ms)</th><th>Retransmits</th><th>Loss %</th><th>Ping Samples</th></tr>
{rows}
</table>"""


def generate_step_up_report(
    results: List[Dict],
    output_dir: str,
    chart_paths: Optional[List[str]] = None,
) -> str:
    """Generate Phase 1 intermediate HTML report."""
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "step_up_report.html")

    html = _html_header("Bandwidth Checker — Step-Up Report")
    html += "<h1>Phase 1: Step-Up Pressure Test Report</h1>\n"

    html += '<div class="summary">\n'
    html += "<h2>Test Summary</h2>\n"
    html += f"<p>Total tests run: {len(results)}</p>\n"
    html += "</div>\n"

    html += "<h2>Per-Test Results</h2>\n"
    html += _results_table(results)

    if chart_paths:
        html += "<h2>Charts</h2>\n"
        for cp in chart_paths:
            name = os.path.basename(cp)
            html += f'<h3>{name.replace(".png", "").replace("_", " ").title()}</h3>\n'
            rel_path = os.path.relpath(cp, output_dir)
            html += f'<img src="{rel_path}" alt="{name}">\n'

    html += _html_footer()

    with open(path, "w") as f:
        f.write(html)
    return path


def generate_final_report(
    step_up_results: List[Dict],
    sustained_results: Dict,
    throttled_results: Dict,
    output_dir: str,
    chart_paths: Optional[List[str]] = None,
) -> str:
    """Generate final comprehensive HTML report."""
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "final_report.html")

    html = _html_header("Bandwidth Checker — Final Report")
    html += "<h1>AWS EC2 Bandwidth Test — Final Report</h1>\n"

    # Phase 1 summary
    html += "<h2>Phase 1: Step-Up Pressure Test</h2>\n"
    html += _results_table(step_up_results)

    # Phase 2 summary
    html += "<h2>Phase 2: Sustained Full-Load</h2>\n"
    html += '<div class="summary">\n'
    depl_time = sustained_results.get("depletion_time_sec")
    if depl_time:
        html += f"<p><strong>Credit depletion detected at:</strong> {depl_time:.0f} seconds</p>\n"
    else:
        html += "<p>Credit depletion was not detected during the test window.</p>\n"
    html += f"<p>Total elapsed: {sustained_results.get('total_elapsed_sec', 0):.0f} seconds</p>\n"
    html += "</div>\n"

    # Phase 3 summary
    html += "<h2>Phase 3: Throttled State Observation</h2>\n"
    html += '<div class="summary">\n'
    html += f"<p>Steady-state TCP samples: {throttled_results.get('steady_tcp_rows', 0)}</p>\n"
    html += f"<p>Steady-state UDP samples: {throttled_results.get('steady_udp_rows', 0)}</p>\n"
    mini = throttled_results.get("mini_levels_tested", [])
    if mini:
        html += f"<p>Mini step-up levels tested: {', '.join(str(m) for m in mini)} Mbps</p>\n"
    html += "</div>\n"

    # Business impact
    html += "<h2>Business Impact Assessment</h2>\n"
    html += '<div class="summary">\n'
    html += "<p><em>Based on test data — review with network and blockchain domain knowledge.</em></p>\n"
    if depl_time:
        html += f"<p>Network burst credits last approximately <strong>{depl_time/60:.0f} minutes</strong> under full load.</p>\n"
    html += "</div>\n"

    # Charts
    if chart_paths:
        html += "<h2>Charts</h2>\n"
        for cp in chart_paths:
            name = os.path.basename(cp)
            html += f'<h3>{name.replace(".png", "").replace("_", " ").title()}</h3>\n'
            rel_path = os.path.relpath(cp, output_dir)
            html += f'<img src="{rel_path}" alt="{name}">\n'

    html += _html_footer()

    with open(path, "w") as f:
        f.write(html)
    return path
```

- [ ] **Step 4: Run tests and verify they pass**

```bash
cd /home/qiqi/code/fish/bandwidth-checker && uv run pytest tests/test_report_generator.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add report/generator.py tests/test_report_generator.py
git commit -m "feat: HTML report generator with step-up and final reports"
```

---

## Task 15: Main Entry Point (run_test.py)

**Files:**
- Create: `run_test.py`

- [ ] **Step 1: Implement run_test.py**

```python
#!/usr/bin/env python3
"""AWS EC2 Bandwidth Checker — Main Entry Point."""
import argparse
import os
import signal
import sys
import time

from config import TestConfig
from setup.remote import setup_remote_servers, burst_credit_probe, kill_remote_iperf3
from phases.step_up import run_step_up
from phases.sustained import run_sustained
from phases.throttled import run_throttled
from report.generator import generate_step_up_report, generate_final_report
from report.charts import generate_step_up_charts, generate_timeline_charts, generate_comparison_chart


# Global state for signal handler cleanup
_cleanup_registry: list = []  # list of objects with .stop() or .kill() methods
_cfg: TestConfig = None


def register_for_cleanup(obj):
    """Register a process/collector for cleanup on SIGINT."""
    _cleanup_registry.append(obj)


def unregister_for_cleanup(obj):
    """Remove a process/collector from cleanup registry."""
    try:
        _cleanup_registry.remove(obj)
    except ValueError:
        pass


def _cleanup(signum=None, frame=None):
    """Graceful shutdown: kill processes, flush data, generate partial report."""
    print("\n\nInterrupted! Cleaning up...", flush=True)

    # Kill all registered local processes and collectors
    for obj in _cleanup_registry:
        try:
            if hasattr(obj, "stop"):
                obj.stop()
            elif hasattr(obj, "kill"):
                obj.kill()
        except Exception:
            pass

    # Kill remote iperf3
    if _cfg:
        try:
            kill_remote_iperf3(_cfg)
        except Exception:
            pass

    # Generate partial report from CSV data on disk
    if _cfg:
        try:
            report_dir = os.path.join(_cfg.data_dir, "report")
            os.makedirs(report_dir, exist_ok=True)
            from report.generator import generate_step_up_report
            # Read whatever step_up results exist in CSV
            print("Generating partial report from collected data...", flush=True)
            generate_step_up_report([], report_dir)  # empty results, charts from CSV
        except Exception:
            pass

    print("Cleanup done. Partial data saved in data/.", flush=True)
    sys.exit(1)


def main():
    global _cfg

    parser = argparse.ArgumentParser(description="AWS EC2 Bandwidth Checker")
    parser.add_argument("--host", required=True, help="Remote host IP or hostname")
    parser.add_argument("--user", default="ec2-user", help="SSH user (default: ec2-user)")
    parser.add_argument("--key", default="", help="SSH private key path")
    parser.add_argument("--port", type=int, default=5201, help="iperf3 base port (default: 5201)")
    parser.add_argument("--data-dir", default="data", help="Data output directory")
    parser.add_argument("--skip-phase1", action="store_true", help="Skip Phase 1 (step-up)")
    parser.add_argument("--skip-phase2", action="store_true", help="Skip Phase 2 (sustained)")
    parser.add_argument("--skip-phase3", action="store_true", help="Skip Phase 3 (throttled)")
    args = parser.parse_args()

    cfg = TestConfig(
        remote_host=args.host,
        remote_user=args.user,
        ssh_key=args.key,
        iperf_base_port=args.port,
        data_dir=args.data_dir,
    )
    _cfg = cfg

    # Register signal handlers
    signal.signal(signal.SIGINT, _cleanup)
    signal.signal(signal.SIGTERM, _cleanup)

    # Pre-flight
    print("=" * 60)
    print("AWS EC2 Bandwidth Checker")
    print("=" * 60)

    ports = [cfg.iperf_base_port, cfg.iperf_base_port + 1]
    if not setup_remote_servers(cfg, ports):
        print("Pre-flight checks failed. Exiting.", file=sys.stderr)
        sys.exit(1)

    # Burst credit probe
    print("\nProbing burst credit state (10 seconds)...", flush=True)
    probe_mbps = burst_credit_probe(cfg)
    if probe_mbps is not None:
        print(f"  Current throughput: {probe_mbps:.0f} Mbps")
        if probe_mbps < 500:
            print("  WARNING: Burst credits may be depleted.")
            print("  Phase 2 may not show the full burst-to-throttle transition.")
            resp = input("  Continue anyway? [y/N] ").strip().lower()
            if resp != "y":
                print("Exiting.")
                sys.exit(0)
    else:
        print("  WARNING: Could not probe burst credits. Continuing anyway.")

    os.makedirs(cfg.data_dir, exist_ok=True)
    report_dir = os.path.join(cfg.data_dir, "report")
    chart_dir = os.path.join(report_dir, "charts")

    step_up_results = []
    sustained_results = {}
    throttled_results = {}

    # Phase 1
    if not args.skip_phase1:
        step_up_results = run_step_up(cfg)

        # Generate intermediate report
        print("\nGenerating intermediate report...", flush=True)
        # Prepare chart data from results
        tcp_chart_data = []
        udp_chart_data = []
        ping_chart_data = []
        for r in step_up_results:
            iperf = r.get("iperf_rows", [])
            if not iperf:
                continue
            avg_bps = sum(row.get("bits_per_second", 0) for row in iperf) / len(iperf)
            label = r["label"]
            if "tcp" in label:
                avg_retrans = sum(row.get("retransmits", 0) for row in iperf) / len(iperf)
                level = int(label.split("M")[0])
                tcp_chart_data.append({
                    "level_mbps": level, "bits_per_second": avg_bps,
                    "retransmits": avg_retrans, "direction": r.get("direction", ""),
                })
            else:
                avg_loss = sum(row.get("lost_percent", 0) for row in iperf) / len(iperf)
                avg_jitter = sum(row.get("jitter_ms", 0) for row in iperf) / len(iperf)
                level = int(label.split("M")[0])
                udp_chart_data.append({
                    "level_mbps": level, "lost_percent": avg_loss,
                    "jitter_ms": avg_jitter, "direction": r.get("direction", ""),
                })
            if r.get("avg_rtt"):
                level = int(label.split("M")[0])
                ping_chart_data.append({"level_mbps": level, "rtt_avg": r["avg_rtt"]})

        chart_paths = generate_step_up_charts(tcp_chart_data, udp_chart_data, ping_chart_data, chart_dir)
        report_path = generate_step_up_report(step_up_results, report_dir, chart_paths)
        print(f"  Intermediate report: {report_path}")

    # Phase 2
    if not args.skip_phase2:
        sustained_results = run_sustained(cfg)

    # Phase 3
    if not args.skip_phase3:
        throttled_results = run_throttled(cfg)

    # Final report
    print("\nGenerating final report...", flush=True)
    all_chart_paths = []

    # Timeline charts from Phase 2+3 CSV
    tcp_csvs = [
        os.path.join(cfg.data_dir, f"{p}_iperf_tcp.csv")
        for p in ["sustained", "throttled"]
    ]
    tcp_csv_combined = [c for c in tcp_csvs if os.path.exists(c)]
    if tcp_csv_combined:
        timeline_paths = generate_timeline_charts(
            tcp_csv_combined[0],
            os.path.join(cfg.data_dir, "sustained_iperf_udp.csv"),
            os.path.join(cfg.data_dir, "sustained_ping.csv"),
            chart_dir,
        )
        all_chart_paths.extend(timeline_paths)

    final_path = generate_final_report(
        step_up_results, sustained_results, throttled_results,
        report_dir, all_chart_paths,
    )
    print(f"  Final report: {final_path}")

    # Cleanup remote
    print("\nCleaning up remote iperf3 servers...", flush=True)
    kill_remote_iperf3(cfg)

    print("\nDone!")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Commit**

```bash
git add run_test.py
git commit -m "feat: main entry point with CLI args, signal handling, and full test flow"
```

---

## Task 16: Run All Tests

- [ ] **Step 1: Run full test suite**

```bash
cd /home/qiqi/code/fish/bandwidth-checker && uv run pytest tests/ -v
```

Expected: all tests PASS

- [ ] **Step 2: Fix any failures found**

- [ ] **Step 3: Final commit if any fixes were needed**

```bash
git add -A
git commit -m "fix: test suite cleanup"
```

---

## Task Summary

| Task | Component | Est. Time |
|------|-----------|-----------|
| 1 | Project scaffolding + config | 5 min |
| 2 | iperf3 JSON parser (incl. bidir) | 5 min |
| 3 | CSV persistence tests | 3 min |
| 4 | Ping latency parser | 5 min |
| 5 | TCP stats (ss) parser | 5 min |
| 6 | Credit depletion detector | 5 min |
| 7 | Remote setup (SSH + port verification) | 5 min |
| 8 | iperf3 process runner | 5 min |
| 8b | IperfRunner.build_command() tests | 3 min |
| 9 | Latency + TCP stats collectors | 5 min |
| 10 | Phase 1: step-up | 5 min |
| 11 | Phase 2: sustained (10s intervals) | 5 min |
| 12 | Phase 3: throttled | 5 min |
| 13 | Chart generation | 5 min |
| 14 | HTML report generator | 5 min |
| 15 | Main entry point (signal handling + cleanup registry) | 5 min |
| 16 | Run all tests | 3 min |
