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
