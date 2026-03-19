# Auto-Discovery & Adaptive Bandwidth Testing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the bandwidth checker self-adapting — auto-discover burst ceiling, generate step-up levels dynamically, add early-stop on limitation, remove real-time depletion detection from Phase 2, and detect depletion from results in the report.

**Architecture:** Replace the hardcoded `step_up_levels` property with a `discover_burst_ceiling()` function that runs a short unbounded TCP test, then generates levels as percentages of the discovered ceiling. Phase 2 becomes a simple fixed-duration sustained load (no `DepletionDetector`). The report analyzes Phase 2 throughput data backward to find the stabilization point.

**Tech Stack:** Python 3.10+, iperf3, matplotlib

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `discovery.py` | **Create** | Burst ceiling discovery + level generation |
| `config.py` | **Modify** | Remove `depletion_threshold_mbps`, `depletion_window_sec`, `step_up_levels`; add `phase2_duration` |
| `phases/step_up.py` | **Modify** | Accept dynamic levels, add early-stop logic |
| `phases/sustained.py` | **Modify** | Remove `DepletionDetector`, run fixed duration |
| `report/generator.py` | **Modify** | Add depletion detection from CSV data |
| `report/charts.py` | **Modify** | Remove hardcoded 256 Mbps baseline line; use discovered ceiling |
| `run_test.py` | **Modify** | Wire discovery phase, update CLI args, pass ceiling to phases/report |
| `tests/test_discovery.py` | **Create** | Tests for level generation and early-stop logic |
| `tests/test_config.py` | **Modify** | Update for removed/changed fields |
| `tests/test_depletion_detector.py` | **Delete** | No longer needed |

---

### Task 1: Create discovery module with level generation

**Files:**
- Create: `discovery.py`
- Create: `tests/test_discovery.py`

- [ ] **Step 1: Write failing tests for `generate_step_up_levels()`**

```python
# tests/test_discovery.py
from discovery import generate_step_up_levels


def test_generate_levels_from_ceiling():
    """Levels are percentages of burst ceiling."""
    levels = generate_step_up_levels(10000)  # 10 Gbps
    bws = [l["bandwidth_mbps"] for l in levels]
    assert bws == [2000, 5000, 8000, 9000, 10000, 12000, 15000, 20000]


def test_generate_levels_small_ceiling():
    """Works with small ceiling values."""
    levels = generate_step_up_levels(500)
    bws = [l["bandwidth_mbps"] for l in levels]
    assert bws == [100, 250, 400, 450, 500, 600, 750, 1000]


def test_level_directions():
    """Lower levels test egress only, higher levels test bidir."""
    levels = generate_step_up_levels(10000)
    # First level (20%) — egress + ingress
    assert levels[0]["tcp_directions"] == ["egress", "ingress"]
    assert levels[0]["udp_directions"] == ["egress", "ingress"]
    # Middle levels (50%+) — add bidir
    assert "bidir" in levels[1]["tcp_directions"]
    # Top levels (100%+) — bidir only
    assert levels[4]["tcp_directions"] == ["bidir"]


def test_level_rounding():
    """Bandwidth values are rounded to integers."""
    levels = generate_step_up_levels(1234)
    for l in levels:
        assert isinstance(l["bandwidth_mbps"], int)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m pytest tests/test_discovery.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'discovery'`

- [ ] **Step 3: Implement `discovery.py`**

```python
"""Burst ceiling discovery and adaptive level generation."""
import json
import subprocess
from typing import List, Dict, Any, Optional

from config import TestConfig


# Step-up percentages of discovered burst ceiling
STEP_UP_PERCENTAGES = [0.20, 0.50, 0.80, 0.90, 1.00, 1.20, 1.50, 2.00]


def generate_step_up_levels(ceiling_mbps: int) -> List[Dict[str, Any]]:
    """Generate step-up test levels as percentages of burst ceiling.

    Lower levels test egress+ingress, mid levels add bidir, top levels bidir only.
    """
    levels = []
    for pct in STEP_UP_PERCENTAGES:
        bw = int(ceiling_mbps * pct)
        if bw < 1:
            continue

        if pct <= 0.20:
            tcp_dirs = ["egress", "ingress"]
            udp_dirs = ["egress", "ingress"]
        elif pct <= 0.80:
            tcp_dirs = ["egress", "ingress", "bidir"]
            udp_dirs = ["egress", "ingress", "bidir"]
        else:
            tcp_dirs = ["bidir"]
            udp_dirs = ["bidir"]

        levels.append({
            "bandwidth_mbps": bw,
            "tcp_directions": tcp_dirs,
            "udp_directions": udp_dirs,
        })
    return levels


def discover_burst_ceiling(cfg: TestConfig) -> Optional[int]:
    """Run a 10s unbounded TCP test to discover burst ceiling.

    Returns burst ceiling in Mbps, or None on failure.
    Uses iperf3 TCP without -b flag — sends as fast as possible.
    """
    print("Discovering burst ceiling (10 seconds)...", flush=True)
    cmd = [
        "iperf3", "-c", cfg.remote_host,
        "-p", str(cfg.iperf_base_port),
        "-t", "10", "-J",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
        if result.returncode != 0:
            return None
        data = json.loads(result.stdout)
        bps = data["end"]["sum_received"]["bits_per_second"]
        ceiling = int(bps / 1_000_000)
        print(f"  Burst ceiling: {ceiling} Mbps", flush=True)
        return ceiling
    except (subprocess.TimeoutExpired, json.JSONDecodeError, KeyError):
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run python -m pytest tests/test_discovery.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add discovery.py tests/test_discovery.py
git commit -m "feat: burst ceiling discovery and adaptive level generation"
```

---

### Task 2: Update config — remove depletion fields, add phase2_duration

**Files:**
- Modify: `config.py`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Update `config.py`**

Remove these fields from `TestConfig`:
- `depletion_threshold_mbps`
- `depletion_window_sec`

Remove the `step_up_levels` property entirely (levels now come from `discovery.py`).

Add:
- `phase2_duration: int = 2100` (35 min, replaces `phase2_timeout`)

Remove `phase2_timeout`.

Final `config.py`:

```python
from dataclasses import dataclass
from typing import List, Dict, Any


@dataclass
class TestConfig:
    remote_host: str
    remote_user: str
    ssh_key: str = ""
    iperf_base_port: int = 5201
    test_duration: int = 60          # seconds per individual test
    cooldown: int = 15               # seconds between tests
    phase2_duration: int = 2100      # 35 min
    phase3_duration: int = 600       # 10 min
    data_dir: str = "data"
    tcp_parallel_streams: int = 4    # -P flag for iperf3
    udp_target_rate: str = "5G"      # -b flag for iperf3 UDP

    def __post_init__(self):
        if not self.remote_host:
            raise ValueError("remote_host is required")
        if not self.remote_user:
            raise ValueError("remote_user is required")
```

- [ ] **Step 2: Update `tests/test_config.py`**

```python
from config import TestConfig


def test_default_config():
    cfg = TestConfig(remote_host="10.0.0.1", remote_user="ec2-user")
    assert cfg.remote_host == "10.0.0.1"
    assert cfg.iperf_base_port == 5201
    assert cfg.test_duration == 60
    assert cfg.cooldown == 15
    assert cfg.phase2_duration == 2100  # 35 min
    assert cfg.phase3_duration == 600  # 10 min


def test_config_validation_missing_host():
    try:
        TestConfig(remote_host="", remote_user="ec2-user")
        assert False, "Should have raised"
    except ValueError:
        pass


def test_config_data_dir():
    cfg = TestConfig(remote_host="10.0.0.1", remote_user="ec2-user")
    assert cfg.data_dir == "data"
```

- [ ] **Step 3: Delete `tests/test_depletion_detector.py`**

```bash
git rm tests/test_depletion_detector.py
```

- [ ] **Step 4: Run tests to check progress**

Run: `uv run python -m pytest tests/test_config.py tests/test_discovery.py -v`
Expected: PASS. Other tests may fail (they import old config fields) — that's expected and will be fixed in later tasks.

- [ ] **Step 5: Commit**

```bash
git add config.py tests/test_config.py
git commit -m "refactor: remove depletion detection config, add phase2_duration"
```

---

### Task 3: Update Phase 1 step_up.py — accept dynamic levels, add early stop

**Files:**
- Modify: `phases/step_up.py`

- [ ] **Step 1: Modify `run_step_up()` to accept levels parameter and add early-stop**

The function signature changes from `run_step_up(cfg)` to `run_step_up(cfg, levels)`.

Early-stop logic: after each level, check if actual TCP throughput < 50% of target for the level. Track consecutive failures. If 2 consecutive levels fail the check, log and stop.

```python
"""Phase 1: Step-up pressure test."""
import os
import time
from typing import Callable, List, Dict, Any, Optional

from config import TestConfig
from cleanup import register_for_cleanup, unregister_for_cleanup
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
    """Run one iperf3 test with parallel ping and ss collection."""
    bw = level["bandwidth_mbps"]
    label = f"{bw}M_{protocol}_{direction}"
    if small_packet:
        label += "_small"
    print(f"  Running: {label} ...", flush=True)

    ping_path = os.path.join(data_dir, "step_up_ping.csv")
    ss_path = os.path.join(data_dir, "step_up_ss.csv")

    ping_collector = LatencyCollector(cfg.remote_host, ping_path)
    ss_collector = TcpStatsCollector(cfg.remote_host, ss_path) if protocol == "tcp" else None

    ping_collector.start()
    register_for_cleanup(ping_collector)
    if ss_collector:
        ss_collector.start()
        register_for_cleanup(ss_collector)

    runner = IperfRunner(
        cfg, protocol=protocol, direction=direction,
        bandwidth_mbps=bw, port=port,
        duration=cfg.test_duration, small_packet=small_packet,
    )
    iperf_data = runner.run()

    ping_collector.stop()
    unregister_for_cleanup(ping_collector)
    if ss_collector:
        ss_collector.stop()
        unregister_for_cleanup(ss_collector)

    if protocol == "tcp":
        rows = parse_iperf_tcp_json(iperf_data)
        csv_path = os.path.join(data_dir, "step_up_iperf_tcp.csv")
    else:
        rows = parse_iperf_udp_json(iperf_data)
        csv_path = os.path.join(data_dir, "step_up_iperf_udp.csv")

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


def _check_limitation(results_at_level: list, target_mbps: int) -> bool:
    """Check if actual throughput is significantly below target.

    Returns True if limitation detected (actual < 50% of target).
    Only checks TCP results (TCP is the reliable throughput indicator).
    """
    tcp_results = [r for r in results_at_level if r["protocol"] == "tcp"]
    if not tcp_results:
        return False
    total_bps = 0
    count = 0
    for r in tcp_results:
        for row in r.get("iperf_rows", []):
            total_bps += row.get("bits_per_second", 0)
            count += 1
    if count == 0:
        return False
    avg_mbps = (total_bps / count) / 1_000_000
    return avg_mbps < target_mbps * 0.5


def run_step_up(
    cfg: TestConfig,
    levels: List[Dict[str, Any]],
    on_progress: Optional[Callable] = None,
) -> list:
    """Run Phase 1: step-up pressure test with early stop on limitation."""
    data_dir = cfg.data_dir
    os.makedirs(data_dir, exist_ok=True)
    port = cfg.iperf_base_port
    all_results = []
    consecutive_limited = 0

    for level_idx, level in enumerate(levels):
        bw = level["bandwidth_mbps"]
        print(f"\n=== Level: {bw} Mbps ===", flush=True)

        tests = []
        for direction in level["tcp_directions"]:
            tests.append(("tcp", direction, False))
        for direction in level["udp_directions"]:
            tests.append(("udp", direction, False))

        level_results = []
        for i, (proto, direction, small_pkt) in enumerate(tests):
            result = run_single_test(cfg, level, proto, direction, port, data_dir, small_pkt)
            all_results.append(result)
            level_results.append(result)
            if on_progress:
                on_progress(result)
            is_last = (level_idx == len(levels) - 1 and i == len(tests) - 1)
            if not is_last:
                time.sleep(cfg.cooldown)

        # Early stop: check if throughput is significantly limited
        if _check_limitation(level_results, bw):
            consecutive_limited += 1
            print(f"  WARNING: Throughput significantly below target "
                  f"({consecutive_limited} consecutive limited levels)", flush=True)
            if consecutive_limited >= 2:
                print(f"  STOPPING step-up: bandwidth ceiling reached at previous level.", flush=True)
                break
        else:
            consecutive_limited = 0

    return all_results
```

- [ ] **Step 2: Run all tests**

Run: `uv run python -m pytest tests/ -v`
Expected: Some tests may fail due to `step_up_levels` removal from config — note which ones.

- [ ] **Step 3: Commit**

```bash
git add phases/step_up.py
git commit -m "feat: dynamic step-up levels with early-stop on limitation"
```

---

### Task 4: Simplify Phase 2 — remove DepletionDetector, fixed duration

**Files:**
- Modify: `phases/sustained.py`

- [ ] **Step 1: Rewrite `phases/sustained.py`**

Remove `DepletionDetector` class entirely. Replace `run_sustained()` with a simple fixed-duration loop. Use `cfg.phase2_duration` instead of `cfg.phase2_timeout`.

```python
"""Phase 2: Sustained full-load for fixed duration."""
import json
import os
import subprocess
import time
from typing import Optional

from config import TestConfig
from cleanup import register_for_cleanup, unregister_for_cleanup
from collectors.iperf import IperfRunner, parse_iperf_tcp_json, parse_iperf_udp_json, write_iperf_csv
from collectors.latency import LatencyCollector
from collectors.tcp_stats import TcpStatsCollector


def run_sustained(cfg: TestConfig, ceiling_mbps: int = 5000) -> dict:
    """Run Phase 2: sustained full-load for fixed duration.

    Args:
        cfg: Test configuration.
        ceiling_mbps: Discovered burst ceiling, used as iperf target rate.
    """
    data_dir = cfg.data_dir
    os.makedirs(data_dir, exist_ok=True)

    port_tcp = cfg.iperf_base_port
    port_udp = cfg.iperf_base_port + 1

    print(f"\n=== Phase 2: Sustained Full-Load ({cfg.phase2_duration}s) ===", flush=True)

    ping_collector = LatencyCollector(
        cfg.remote_host, os.path.join(data_dir, "sustained_ping.csv"),
    )
    ss_collector = TcpStatsCollector(
        cfg.remote_host, os.path.join(data_dir, "sustained_ss.csv"),
    )
    ping_collector.start()
    register_for_cleanup(ping_collector)
    ss_collector.start()
    register_for_cleanup(ss_collector)

    start_time = time.time()
    tcp_csv = os.path.join(data_dir, "sustained_iperf_tcp.csv")
    udp_csv = os.path.join(data_dir, "sustained_iperf_udp.csv")

    # Use 10-second iperf intervals for fine-grained data
    interval_duration = 10
    elapsed = 0
    target_mbps = max(ceiling_mbps, 5000)  # at least 5 Gbps to saturate

    while elapsed < cfg.phase2_duration:
        remaining = min(interval_duration, cfg.phase2_duration - int(elapsed))
        if remaining <= 0:
            break

        if int(elapsed) % 60 == 0:
            print(f"  Sustained: {int(elapsed)}s / {cfg.phase2_duration}s elapsed...", flush=True)

        tcp_runner = IperfRunner(
            cfg, protocol="tcp", direction="bidir",
            bandwidth_mbps=target_mbps, port=port_tcp, duration=remaining,
        )
        udp_runner = IperfRunner(
            cfg, protocol="udp", direction="bidir",
            bandwidth_mbps=target_mbps, port=port_udp, duration=remaining,
        )

        tcp_runner.run_background()
        register_for_cleanup(tcp_runner)
        udp_runner.run_background()
        register_for_cleanup(udp_runner)

        tcp_data = tcp_runner.wait(timeout=remaining + 30)
        unregister_for_cleanup(tcp_runner)
        udp_data = udp_runner.wait(timeout=remaining + 30)
        unregister_for_cleanup(udp_runner)

        # Check for iperf3 crash — retry the interval
        tcp_crashed = tcp_data.get("error") and "timeout" not in str(tcp_data["error"])
        if tcp_crashed:
            print("  WARNING: iperf3 TCP crashed, restarting server...", flush=True)
            from setup.remote import start_remote_iperf3
            start_remote_iperf3(cfg, port_tcp)
            time.sleep(2)
            elapsed = time.time() - start_time
            continue

        udp_crashed = udp_data.get("error") and "timeout" not in str(udp_data["error"])
        if udp_crashed:
            from setup.remote import start_remote_iperf3
            start_remote_iperf3(cfg, port_udp)
            time.sleep(2)

        tcp_rows = parse_iperf_tcp_json(tcp_data)
        udp_rows = parse_iperf_udp_json(udp_data) if not udp_crashed else []

        for row in tcp_rows:
            row["phase_elapsed_sec"] = elapsed + row.get("start", 0)
        for row in udp_rows:
            row["phase_elapsed_sec"] = elapsed + row.get("start", 0)

        write_iperf_csv(tcp_rows, tcp_csv)
        write_iperf_csv(udp_rows, udp_csv)

        elapsed = time.time() - start_time

    ping_collector.stop()
    unregister_for_cleanup(ping_collector)
    ss_collector.stop()
    unregister_for_cleanup(ss_collector)

    return {
        "total_elapsed_sec": time.time() - start_time,
    }
```

- [ ] **Step 2: Run tests**

Run: `uv run python -m pytest tests/ -v`
Expected: `test_depletion_detector.py` should already be deleted from Task 2. Other tests pass.

- [ ] **Step 3: Commit**

```bash
git add phases/sustained.py
git commit -m "refactor: Phase 2 runs fixed duration, remove DepletionDetector"
```

---

### Task 5: Add depletion analysis to report generator

**Files:**
- Modify: `report/generator.py`

- [ ] **Step 1: Add `detect_depletion_from_csv()` function and update final report**

This function reads the Phase 2 TCP CSV, scans the throughput data, and finds where bandwidth stabilized (the depletion transition). Strategy: compute a rolling average, scan backward from end to find the stable region, then find where the drop began.

Add to `report/generator.py`:

```python
import csv

def detect_depletion_from_csv(tcp_csv_path: str) -> Dict:
    """Analyze Phase 2 TCP throughput data to find depletion point.

    Scans backward from end to find stable region, then finds the transition edge.
    Returns dict with depletion_time_sec, baseline_mbps, burst_mbps, or empty dict if no data.
    """
    if not os.path.exists(tcp_csv_path):
        return {}

    rows = []
    with open(tcp_csv_path) as f:
        for row in csv.DictReader(f):
            try:
                rows.append({
                    "time": float(row.get("phase_elapsed_sec", row.get("start", 0))),
                    "mbps": float(row["bits_per_second"]) / 1_000_000,
                })
            except (ValueError, KeyError):
                continue

    if len(rows) < 10:
        return {}

    # Find stable region: last 20% of data
    tail_start = int(len(rows) * 0.8)
    tail = rows[tail_start:]
    baseline_mbps = sum(r["mbps"] for r in tail) / len(tail)

    # Find burst region: first 10% of data
    head = rows[:max(int(len(rows) * 0.1), 5)]
    burst_mbps = sum(r["mbps"] for r in head) / len(head)

    # If burst and baseline are similar (within 2x), no depletion occurred
    if burst_mbps < baseline_mbps * 2:
        return {
            "depletion_detected": False,
            "baseline_mbps": baseline_mbps,
            "burst_mbps": burst_mbps,
        }

    # Find transition: first time throughput drops below midpoint for 5+ samples
    midpoint = (burst_mbps + baseline_mbps) / 2
    consecutive = 0
    depletion_time = None
    for r in rows:
        if r["mbps"] < midpoint:
            consecutive += 1
            if consecutive >= 5 and depletion_time is None:
                depletion_time = r["time"]
        else:
            consecutive = 0

    return {
        "depletion_detected": True,
        "depletion_time_sec": depletion_time,
        "baseline_mbps": baseline_mbps,
        "burst_mbps": burst_mbps,
    }
```

Update `generate_final_report()` to use this instead of `sustained_results.get("depletion_time_sec")`:

In the Phase 2 section, replace the depletion display logic:

```python
def generate_final_report(
    step_up_results: List[Dict],
    sustained_results: Dict,
    throttled_results: Dict,
    output_dir: str,
    chart_paths: Optional[List[str]] = None,
    tcp_csv_path: Optional[str] = None,
) -> str:
    """Generate final comprehensive HTML report."""
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "final_report.html")

    html = _html_header("Bandwidth Checker — Final Report")
    html += "<h1>AWS EC2 Bandwidth Test — Final Report</h1>\n"

    html += "<h2>Phase 1: Step-Up Pressure Test</h2>\n"
    html += _results_table(step_up_results)

    html += "<h2>Phase 2: Sustained Full-Load</h2>\n"
    html += '<div class="summary">\n'

    # Analyze depletion from CSV data
    depletion = {}
    if tcp_csv_path:
        depletion = detect_depletion_from_csv(tcp_csv_path)

    if depletion.get("depletion_detected"):
        depl_time = depletion.get("depletion_time_sec")
        if depl_time:
            html += f"<p><strong>Credit depletion detected at:</strong> {depl_time:.0f} seconds</p>\n"
        html += f"<p><strong>Burst throughput:</strong> {depletion.get('burst_mbps', 0):.0f} Mbps</p>\n"
        html += f"<p><strong>Baseline throughput:</strong> {depletion.get('baseline_mbps', 0):.0f} Mbps</p>\n"
    elif depletion:
        html += "<p>No significant depletion detected — throughput remained stable.</p>\n"
        html += f"<p><strong>Average throughput:</strong> {depletion.get('baseline_mbps', 0):.0f} Mbps</p>\n"
    else:
        html += "<p>No Phase 2 data available.</p>\n"

    html += f"<p>Total elapsed: {sustained_results.get('total_elapsed_sec', 0):.0f} seconds</p>\n"
    html += "</div>\n"

    html += "<h2>Phase 3: Throttled State Observation</h2>\n"
    html += '<div class="summary">\n'
    html += f"<p>Steady-state TCP samples: {throttled_results.get('steady_tcp_rows', 0)}</p>\n"
    html += f"<p>Steady-state UDP samples: {throttled_results.get('steady_udp_rows', 0)}</p>\n"
    mini = throttled_results.get("mini_levels_tested", [])
    if mini:
        html += f"<p>Mini step-up levels tested: {', '.join(str(m) for m in mini)} Mbps</p>\n"
    html += "</div>\n"

    html += "<h2>Business Impact Assessment</h2>\n"
    html += '<div class="summary">\n'
    html += "<p><em>Based on test data — review with network and blockchain domain knowledge.</em></p>\n"
    if depletion.get("depletion_detected") and depletion.get("depletion_time_sec"):
        depl_min = depletion["depletion_time_sec"] / 60
        html += f"<p>Network burst credits last approximately <strong>{depl_min:.0f} minutes</strong> under full load.</p>\n"
        html += f"<p>After depletion, bandwidth drops from ~{depletion['burst_mbps']:.0f} Mbps to ~{depletion['baseline_mbps']:.0f} Mbps.</p>\n"
    html += "</div>\n"

    if chart_paths:
        html += "<h2>Charts</h2>\n"
        for cp in chart_paths:
            name = os.path.basename(cp)
            rel_path = os.path.relpath(cp, output_dir)
            html += f'<h3>{name.replace(".png", "").replace("_", " ").title()}</h3>\n'
            html += f'<img src="{rel_path}" alt="{name}">\n'

    html += _html_footer()

    with open(path, "w") as f:
        f.write(html)
    return path
```

- [ ] **Step 2: Run tests**

Run: `uv run python -m pytest tests/test_report_generator.py -v`
Expected: PASS (existing test should still work — `generate_step_up_report` is unchanged)

- [ ] **Step 3: Commit**

```bash
git add report/generator.py
git commit -m "feat: detect depletion from Phase 2 CSV data in report"
```

---

### Task 6: Update charts — remove hardcoded baseline

**Files:**
- Modify: `report/charts.py`

- [ ] **Step 1: Update `generate_step_up_charts()` and `generate_timeline_charts()` to accept `ceiling_mbps`**

Replace the hardcoded `ax.axhline(y=256, ...)` with a dynamic baseline line based on the discovered ceiling.

In `generate_step_up_charts()`:
```python
def generate_step_up_charts(
    tcp_data: List[Dict],
    udp_data: List[Dict],
    ping_data: List[Dict],
    output_dir: str,
    ceiling_mbps: int = 0,
) -> List[str]:
```

Replace line 34:
```python
    # Old: ax.axhline(y=256, color="red", linestyle="--", label="Baseline (256 Mbps)")
    if ceiling_mbps > 0:
        ax.axhline(y=ceiling_mbps, color="red", linestyle="--", label=f"Burst ceiling ({ceiling_mbps} Mbps)")
```

In `generate_timeline_charts()`:
```python
def generate_timeline_charts(
    tcp_csv: str,
    udp_csv: str,
    ping_csv: str,
    output_dir: str,
    phase_boundaries: List[Dict] = None,
    ceiling_mbps: int = 0,
) -> List[str]:
```

Replace line 117:
```python
    # Old: ax.axhline(y=256, color="red", linestyle="--", alpha=0.5, label="Baseline")
    if ceiling_mbps > 0:
        ax.axhline(y=ceiling_mbps, color="red", linestyle="--", alpha=0.5, label=f"Ceiling ({ceiling_mbps} Mbps)")
```

- [ ] **Step 2: Run chart test**

Run: `uv run python -m pytest tests/test_charts.py -v`
Expected: PASS (test doesn't check chart content, just file creation)

- [ ] **Step 3: Commit**

```bash
git add report/charts.py
git commit -m "refactor: charts use discovered ceiling instead of hardcoded baseline"
```

---

### Task 7: Wire everything in run_test.py

**Files:**
- Modify: `run_test.py`

- [ ] **Step 1: Update `run_test.py`**

Key changes:
1. Import `discover_burst_ceiling` and `generate_step_up_levels` from `discovery`
2. Add `--ceiling` CLI arg (optional manual override)
3. Add `--phase2-duration` CLI arg
4. Replace burst credit probe with discovery phase (discovery subsumes the probe)
5. Pass levels to `run_step_up(cfg, levels)`
6. Pass `ceiling_mbps` to `run_sustained()`, charts, and report
7. Pass `tcp_csv_path` to `generate_final_report()`

```python
#!/usr/bin/env python3
"""AWS EC2 Bandwidth Checker — Main Entry Point."""
import argparse
import os
import signal
import sys
import time

from config import TestConfig
from cleanup import cleanup_all
from discovery import discover_burst_ceiling, generate_step_up_levels
from setup.remote import setup_remote_servers, kill_remote_iperf3
from phases.step_up import run_step_up
from phases.sustained import run_sustained
from phases.throttled import run_throttled
from report.generator import generate_step_up_report, generate_final_report
from report.charts import generate_step_up_charts, generate_timeline_charts, generate_comparison_chart


_cfg: TestConfig = None
_no_ssh: bool = False


def _cleanup(signum=None, frame=None):
    """Graceful shutdown: kill processes, flush data, generate partial report."""
    print("\n\nInterrupted! Cleaning up...", flush=True)

    cleanup_all()

    # Kill remote iperf3
    if _cfg and not _no_ssh:
        try:
            kill_remote_iperf3(_cfg)
        except Exception:
            pass

    # Generate partial report from CSV data on disk
    if _cfg:
        try:
            report_dir = os.path.join(_cfg.data_dir, "report")
            os.makedirs(report_dir, exist_ok=True)
            print("Generating partial report from collected data...", flush=True)
            generate_step_up_report([], report_dir)
        except Exception:
            pass

    print("Cleanup done. Partial data saved in data/.", flush=True)
    sys.exit(1)


def main():
    global _cfg, _no_ssh

    parser = argparse.ArgumentParser(description="AWS EC2 Bandwidth Checker")
    parser.add_argument("--host", required=True, help="Remote host IP or hostname")
    parser.add_argument("--user", default="ec2-user", help="SSH user (default: ec2-user)")
    parser.add_argument("--key", default="", help="SSH private key path")
    parser.add_argument("--port", type=int, default=5201, help="iperf3 base port (default: 5201)")
    parser.add_argument("--data-dir", default="data", help="Data output directory")
    parser.add_argument("--skip-phase1", action="store_true", help="Skip Phase 1 (step-up)")
    parser.add_argument("--skip-phase2", action="store_true", help="Skip Phase 2 (sustained)")
    parser.add_argument("--skip-phase3", action="store_true", help="Skip Phase 3 (throttled)")
    parser.add_argument("--no-ssh", action="store_true",
                        help="Skip SSH setup/cleanup (manually start iperf3 servers on remote)")
    parser.add_argument("--ceiling", type=int, default=0,
                        help="Manual burst ceiling in Mbps (skip auto-discovery)")
    parser.add_argument("--phase2-duration", type=int, default=0,
                        help="Phase 2 duration in seconds (default: 2100 = 35 min)")
    args = parser.parse_args()

    cfg = TestConfig(
        remote_host=args.host,
        remote_user=args.user,
        ssh_key=args.key,
        iperf_base_port=args.port,
        data_dir=args.data_dir,
    )
    if args.phase2_duration > 0:
        cfg.phase2_duration = args.phase2_duration

    _cfg = cfg
    _no_ssh = args.no_ssh

    # Register signal handlers
    signal.signal(signal.SIGINT, _cleanup)
    signal.signal(signal.SIGTERM, _cleanup)

    # Pre-flight
    print("=" * 60)
    print("AWS EC2 Bandwidth Checker")
    print("=" * 60)

    if args.no_ssh:
        print("--no-ssh: skipping remote setup (ensure iperf3 servers are running on "
              f"ports {cfg.iperf_base_port} and {cfg.iperf_base_port + 1})", flush=True)
    else:
        ports = [cfg.iperf_base_port, cfg.iperf_base_port + 1]
        if not setup_remote_servers(cfg, ports):
            print("Pre-flight checks failed. Exiting.", file=sys.stderr)
            sys.exit(1)

    # Discover burst ceiling
    if args.ceiling > 0:
        ceiling_mbps = args.ceiling
        print(f"\nUsing manual burst ceiling: {ceiling_mbps} Mbps", flush=True)
    else:
        print("\nAuto-discovering burst ceiling...", flush=True)
        ceiling_mbps = discover_burst_ceiling(cfg)
        if ceiling_mbps is None:
            print("ERROR: Could not discover burst ceiling. Use --ceiling to set manually.",
                  file=sys.stderr)
            sys.exit(1)

    levels = generate_step_up_levels(ceiling_mbps)
    print(f"Step-up levels: {[l['bandwidth_mbps'] for l in levels]} Mbps", flush=True)

    os.makedirs(cfg.data_dir, exist_ok=True)
    report_dir = os.path.join(cfg.data_dir, "report")
    chart_dir = os.path.join(report_dir, "charts")

    step_up_results = []
    sustained_results = {}
    throttled_results = {}

    # Phase 1
    if not args.skip_phase1:
        step_up_results = run_step_up(cfg, levels)

        # Generate intermediate report
        print("\nGenerating intermediate report...", flush=True)
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
                level = r["level_mbps"]
                tcp_chart_data.append({
                    "level_mbps": level, "bits_per_second": avg_bps,
                    "retransmits": avg_retrans, "direction": r.get("direction", ""),
                })
            else:
                avg_loss = sum(row.get("lost_percent", 0) for row in iperf) / len(iperf)
                avg_jitter = sum(row.get("jitter_ms", 0) for row in iperf) / len(iperf)
                level = r["level_mbps"]
                udp_chart_data.append({
                    "level_mbps": level, "lost_percent": avg_loss,
                    "jitter_ms": avg_jitter, "direction": r.get("direction", ""),
                })
            if r.get("avg_rtt"):
                ping_chart_data.append({"level_mbps": r["level_mbps"], "rtt_avg": r["avg_rtt"]})

        chart_paths = generate_step_up_charts(
            tcp_chart_data, udp_chart_data, ping_chart_data, chart_dir,
            ceiling_mbps=ceiling_mbps,
        )
        report_path = generate_step_up_report(step_up_results, report_dir, chart_paths)
        print(f"  Intermediate report: {report_path}")

    # Phase 2
    if not args.skip_phase2:
        sustained_results = run_sustained(cfg, ceiling_mbps=ceiling_mbps)

    # Phase 3
    if not args.skip_phase3:
        throttled_results = run_throttled(cfg)

    # Final report
    print("\nGenerating final report...", flush=True)
    all_chart_paths = []

    tcp_csv_path = os.path.join(cfg.data_dir, "sustained_iperf_tcp.csv")
    if os.path.exists(tcp_csv_path):
        timeline_paths = generate_timeline_charts(
            tcp_csv_path,
            os.path.join(cfg.data_dir, "sustained_iperf_udp.csv"),
            os.path.join(cfg.data_dir, "sustained_ping.csv"),
            chart_dir,
            ceiling_mbps=ceiling_mbps,
        )
        all_chart_paths.extend(timeline_paths)

    final_path = generate_final_report(
        step_up_results, sustained_results, throttled_results,
        report_dir, all_chart_paths,
        tcp_csv_path=tcp_csv_path if os.path.exists(tcp_csv_path) else None,
    )
    print(f"  Final report: {final_path}")

    # Cleanup remote
    if not args.no_ssh:
        print("\nCleaning up remote iperf3 servers...", flush=True)
        kill_remote_iperf3(cfg)

    print("\nDone!")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run full test suite**

Run: `uv run python -m pytest tests/ -v`
Expected: All tests pass. If any fail, fix them.

- [ ] **Step 3: Commit**

```bash
git add run_test.py
git commit -m "feat: wire auto-discovery, dynamic levels, and CSV-based depletion analysis"
```

---

### Task 8: Final test run and cleanup

**Files:**
- All test files

- [ ] **Step 1: Run full test suite**

Run: `uv run python -m pytest tests/ -v`
Expected: All tests pass.

- [ ] **Step 2: Verify CLI help**

Run: `uv run python run_test.py --help`
Expected: Shows `--ceiling`, `--phase2-duration`, `--no-ssh`, all phase skip flags.

- [ ] **Step 3: Verify imports work end-to-end**

```bash
uv run python -c "from discovery import generate_step_up_levels, discover_burst_ceiling; print(generate_step_up_levels(12500))"
```
Expected: Prints 8 level dicts with bandwidth values [2500, 6250, 10000, 11250, 12500, 15000, 18750, 25000].

- [ ] **Step 4: Commit any fixes**

```bash
git add -A
git commit -m "chore: final test fixes for auto-discovery feature"
```
