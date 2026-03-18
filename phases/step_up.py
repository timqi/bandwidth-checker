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
    if ss_collector:
        ss_collector.start()

    runner = IperfRunner(
        cfg, protocol=protocol, direction=direction,
        bandwidth_mbps=bw, port=port,
        duration=cfg.test_duration, small_packet=small_packet,
    )
    iperf_data = runner.run()

    ping_collector.stop()
    if ss_collector:
        ss_collector.stop()

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


def run_step_up(cfg: TestConfig, on_progress: Optional[Callable] = None) -> list:
    """Run Phase 1: step-up pressure test."""
    data_dir = cfg.data_dir
    os.makedirs(data_dir, exist_ok=True)
    port = cfg.iperf_base_port
    all_results = []

    for level in cfg.step_up_levels:
        bw = level["bandwidth_mbps"]
        print(f"\n=== Level: {bw} Mbps ===", flush=True)

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
            is_last = (level == cfg.step_up_levels[-1] and i == len(tests) - 1)
            if not is_last:
                time.sleep(cfg.cooldown)

    return all_results
