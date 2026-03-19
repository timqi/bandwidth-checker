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
        ceiling_mbps: Discovered burst ceiling, used to set iperf target rate.
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
    target_mbps = int(ceiling_mbps * 1.5)  # push 50% above ceiling to ensure saturation

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
