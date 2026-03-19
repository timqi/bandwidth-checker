"""Phase 3: Throttled state observation."""
import os
import time
from typing import Optional

from config import TestConfig
from cleanup import register_for_cleanup, unregister_for_cleanup
from collectors.iperf import IperfRunner, parse_iperf_tcp_json, parse_iperf_udp_json, write_iperf_csv
from collectors.latency import LatencyCollector
from collectors.tcp_stats import TcpStatsCollector


def run_throttled(cfg: TestConfig) -> dict:
    """Run Phase 3: observe throttled state behavior."""
    data_dir = cfg.data_dir
    os.makedirs(data_dir, exist_ok=True)

    port = cfg.iperf_base_port
    print("\n=== Phase 3: Throttled State Observation ===", flush=True)

    ping_collector = LatencyCollector(
        cfg.remote_host, os.path.join(data_dir, "throttled_ping.csv"),
    )
    ss_collector = TcpStatsCollector(
        cfg.remote_host, os.path.join(data_dir, "throttled_ss.csv"),
    )
    ping_collector.start()
    register_for_cleanup(ping_collector)
    ss_collector.start()
    register_for_cleanup(ss_collector)

    tcp_csv = os.path.join(data_dir, "throttled_iperf_tcp.csv")
    udp_csv = os.path.join(data_dir, "throttled_iperf_udp.csv")

    # Part 1: Steady-state observation (~6 min)
    print("  Observing steady-state throttled behavior (3 min)...", flush=True)

    tcp_runner = IperfRunner(
        cfg, protocol="tcp", direction="bidir",
        bandwidth_mbps=5000, port=port, duration=180,
    )
    udp_runner = IperfRunner(
        cfg, protocol="udp", direction="bidir",
        bandwidth_mbps=5000, port=port + 1, duration=180,
    )
    tcp_runner.run_background()
    register_for_cleanup(tcp_runner)
    udp_runner.run_background()
    register_for_cleanup(udp_runner)
    tcp_data = tcp_runner.wait(timeout=210)
    unregister_for_cleanup(tcp_runner)
    udp_data = udp_runner.wait(timeout=210)
    unregister_for_cleanup(udp_runner)

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
        tcp_r.run_background()
        register_for_cleanup(tcp_r)
        udp_r.run_background()
        register_for_cleanup(udp_r)
        tcp_d = tcp_r.wait(timeout=60)
        unregister_for_cleanup(tcp_r)
        udp_d = udp_r.wait(timeout=60)
        unregister_for_cleanup(udp_r)

        tcp_mini = parse_iperf_tcp_json(tcp_d)
        udp_mini = parse_iperf_udp_json(udp_d)
        for row in tcp_mini:
            row["sub_phase"] = f"mini_{bw}"
        for row in udp_mini:
            row["sub_phase"] = f"mini_{bw}"
        write_iperf_csv(tcp_mini, tcp_csv)
        write_iperf_csv(udp_mini, udp_csv)

        time.sleep(cfg.cooldown)

    ping_collector.stop()
    unregister_for_cleanup(ping_collector)
    ss_collector.stop()
    unregister_for_cleanup(ss_collector)

    return {
        "steady_tcp_rows": len(tcp_rows),
        "steady_udp_rows": len(udp_rows),
        "mini_levels_tested": mini_levels,
    }
