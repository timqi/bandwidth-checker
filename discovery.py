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
    Includes small-packet UDP at the level closest to 50% of ceiling.
    """
    if ceiling_mbps <= 0:
        return []

    seen = set()
    levels = []
    for pct in STEP_UP_PERCENTAGES:
        bw = int(ceiling_mbps * pct)
        if bw < 1 or bw in seen:
            continue
        seen.add(bw)

        if pct <= 0.20:
            tcp_dirs = ["egress", "ingress"]
            udp_dirs = ["egress", "ingress"]
        elif pct <= 0.80:
            tcp_dirs = ["egress", "ingress", "bidir"]
            udp_dirs = ["egress", "ingress", "bidir"]
        else:
            tcp_dirs = ["bidir"]
            udp_dirs = ["bidir"]

        level = {
            "bandwidth_mbps": bw,
            "tcp_directions": tcp_dirs,
            "udp_directions": udp_dirs,
        }
        # Add small-packet UDP at the 50% level (closest to baseline)
        if pct == 0.50:
            level["small_packet_udp"] = True

        levels.append(level)
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
