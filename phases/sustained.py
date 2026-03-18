"""Phase 2: Sustained full-load until credit depletion."""
import json
import os
import subprocess
import time
from typing import Optional

from config import TestConfig
from collectors.iperf import IperfRunner, parse_iperf_tcp_json, parse_iperf_udp_json, write_iperf_csv
from collectors.latency import LatencyCollector
from collectors.tcp_stats import TcpStatsCollector


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


def run_sustained(cfg: TestConfig) -> dict:
    """Run Phase 2: sustained full-load until credit depletion."""
    data_dir = cfg.data_dir
    os.makedirs(data_dir, exist_ok=True)

    port_tcp = cfg.iperf_base_port
    port_udp = cfg.iperf_base_port + 1

    print("\n=== Phase 2: Sustained Full-Load ===", flush=True)

    ping_collector = LatencyCollector(
        cfg.remote_host, os.path.join(data_dir, "sustained_ping.csv"),
    )
    ss_collector = TcpStatsCollector(
        cfg.remote_host, os.path.join(data_dir, "sustained_ss.csv"),
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
    interval_duration = 10
    elapsed = 0

    while elapsed < cfg.phase2_timeout:
        remaining = min(interval_duration, cfg.phase2_timeout - int(elapsed))
        if remaining <= 0:
            break

        if int(elapsed) % 60 == 0:
            print(f"  Sustained: {int(elapsed)}s elapsed...", flush=True)

        tcp_runner = IperfRunner(
            cfg, protocol="tcp", direction="bidir",
            bandwidth_mbps=5000, port=port_tcp, duration=remaining,
        )
        udp_runner = IperfRunner(
            cfg, protocol="udp", direction="bidir",
            bandwidth_mbps=5000, port=port_udp, duration=remaining,
        )

        tcp_runner.run_background()
        udp_runner.run_background()

        tcp_data = tcp_runner.wait(timeout=remaining + 30)
        udp_data = udp_runner.wait(timeout=remaining + 30)

        # Check for iperf3 crash — retry the interval
        tcp_crashed = tcp_data.get("error") and "timeout" not in str(tcp_data["error"])
        if tcp_crashed:
            print(f"  WARNING: iperf3 TCP crashed, restarting server...", flush=True)
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

        for row in tcp_rows:
            detector.add_sample(row.get("bits_per_second", 0))
            if detector.is_depleted and depletion_time is None:
                depletion_time = elapsed + row.get("start", 0)
                print(f"  *** Credit depletion detected at {depletion_time:.0f}s ***", flush=True)

        elapsed = time.time() - start_time

        if detector.is_depleted:
            break

    ping_collector.stop()
    ss_collector.stop()

    return {
        "depletion_time_sec": depletion_time,
        "total_elapsed_sec": time.time() - start_time,
        "depleted": detector.is_depleted,
    }
