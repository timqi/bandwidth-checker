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
    ceiling_mbps: int = 0,
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
    if ceiling_mbps > 0:
        ax.axhline(y=ceiling_mbps, color="red", linestyle="--", label=f"Burst ceiling ({ceiling_mbps} Mbps)")
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
    ceiling_mbps: int = 0,
) -> List[str]:
    """Generate full-test timeline charts from CSV data."""
    import csv

    os.makedirs(output_dir, exist_ok=True)
    paths = []

    def read_csv(path):
        if not os.path.exists(path):
            return []
        with open(path) as f:
            return list(csv.DictReader(f))

    tcp_rows = read_csv(tcp_csv)
    udp_rows = read_csv(udp_csv)
    ping_rows = read_csv(ping_csv)

    if tcp_rows:
        fig, ax = plt.subplots(figsize=(14, 5))
        x = [float(r.get("phase_elapsed_sec", r.get("start", 0))) for r in tcp_rows]
        y = [float(r["bits_per_second"]) / 1e6 for r in tcp_rows]
        ax.plot(x, y, linewidth=0.5, color="tab:blue")
        ax.set_xlabel("Time (seconds)")
        ax.set_ylabel("Throughput (Mbps)")
        ax.set_title("TCP Throughput Timeline")
        if ceiling_mbps > 0:
            ax.axhline(y=ceiling_mbps, color="red", linestyle="--", alpha=0.5, label=f"Ceiling ({ceiling_mbps} Mbps)")
        if phase_boundaries:
            for pb in phase_boundaries:
                ax.axvline(x=pb["time"], color="gray", linestyle=":", alpha=0.5)
                ax.text(pb["time"], ax.get_ylim()[1] * 0.95, pb["label"], fontsize=8)
        ax.legend()
        ax.grid(True, alpha=0.3)
        paths.append(_save(fig, os.path.join(output_dir, "timeline_throughput.png")))

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
