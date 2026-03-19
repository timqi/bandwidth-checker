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
        if level.get("small_packet_udp"):
            for direction in level["udp_directions"]:
                tests.append(("udp", direction, True))

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
                print("  STOPPING step-up: bandwidth ceiling reached.", flush=True)
                break
        else:
            consecutive_limited = 0

    return all_results
