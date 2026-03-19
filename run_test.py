#!/usr/bin/env python3
"""AWS EC2 Bandwidth Checker — Main Entry Point."""
import argparse
import os
import signal
import sys
import time
from datetime import datetime

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

    # Auto-timestamp data directory
    run_dir = os.path.join(args.data_dir, datetime.now().strftime("%Y-%m-%d_%H%M%S"))

    cfg = TestConfig(
        remote_host=args.host,
        remote_user=args.user,
        ssh_key=args.key,
        iperf_base_port=args.port,
        data_dir=run_dir,
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
                tcp_chart_data.append({
                    "level_mbps": r["level_mbps"], "bits_per_second": avg_bps,
                    "retransmits": avg_retrans, "direction": r.get("direction", ""),
                })
            else:
                avg_loss = sum(row.get("lost_percent", 0) for row in iperf) / len(iperf)
                avg_jitter = sum(row.get("jitter_ms", 0) for row in iperf) / len(iperf)
                udp_chart_data.append({
                    "level_mbps": r["level_mbps"], "lost_percent": avg_loss,
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
