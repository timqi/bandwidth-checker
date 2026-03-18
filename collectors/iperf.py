"""iperf3 process management and JSON result parsing."""
import csv
import json
import os
import subprocess
import time
from typing import Any, Dict, List

from config import TestConfig


def parse_iperf_tcp_json(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Parse iperf3 TCP JSON output into per-interval rows.

    Handles both normal (sum) and --bidir (sum_sent/sum_received) formats.
    For bidir, combines sent+received throughput into a single row.
    """
    rows = []
    for interval in data.get("intervals", []):
        if "sum_sent" in interval:
            sent = interval["sum_sent"]
            recv = interval.get("sum_received", {})
            rows.append({
                "start": sent.get("start", 0),
                "end": sent.get("end", 0),
                "seconds": sent.get("seconds", 0),
                "bytes": sent.get("bytes", 0) + recv.get("bytes", 0),
                "bits_per_second": sent.get("bits_per_second", 0) + recv.get("bits_per_second", 0),
                "retransmits": sent.get("retransmits", 0) + recv.get("retransmits", 0),
            })
        else:
            s = interval.get("sum", {})
            rows.append({
                "start": s.get("start", 0),
                "end": s.get("end", 0),
                "seconds": s.get("seconds", 0),
                "bytes": s.get("bytes", 0),
                "bits_per_second": s.get("bits_per_second", 0),
                "retransmits": s.get("retransmits", 0),
            })
    return rows


def parse_iperf_udp_json(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Parse iperf3 UDP JSON output into per-interval rows.

    Handles both normal (sum) and --bidir (sum_sent/sum_received) formats.
    """
    rows = []
    for interval in data.get("intervals", []):
        if "sum_sent" in interval:
            sent = interval["sum_sent"]
            recv = interval.get("sum_received", {})
            rows.append({
                "start": sent.get("start", 0),
                "end": sent.get("end", 0),
                "seconds": sent.get("seconds", 0),
                "bytes": sent.get("bytes", 0) + recv.get("bytes", 0),
                "bits_per_second": sent.get("bits_per_second", 0) + recv.get("bits_per_second", 0),
                "lost_packets": sent.get("lost_packets", 0) + recv.get("lost_packets", 0),
                "packets": sent.get("packets", 0) + recv.get("packets", 0),
                "lost_percent": (
                    (sent.get("lost_packets", 0) + recv.get("lost_packets", 0))
                    / max(sent.get("packets", 0) + recv.get("packets", 0), 1) * 100
                ),
                "jitter_ms": max(sent.get("jitter_ms", 0), recv.get("jitter_ms", 0)),
            })
        else:
            s = interval.get("sum", {})
            rows.append({
                "start": s.get("start", 0),
                "end": s.get("end", 0),
                "seconds": s.get("seconds", 0),
                "bytes": s.get("bytes", 0),
                "bits_per_second": s.get("bits_per_second", 0),
                "lost_packets": s.get("lost_packets", 0),
                "packets": s.get("packets", 0),
                "lost_percent": s.get("lost_percent", 0),
                "jitter_ms": s.get("jitter_ms", 0),
            })
    return rows


def write_iperf_csv(rows: List[Dict[str, Any]], filepath: str) -> None:
    """Append iperf3 parsed rows to CSV file. Creates file with header if new."""
    if not rows:
        return
    file_exists = os.path.exists(filepath)
    with open(filepath, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        if not file_exists:
            writer.writeheader()
        writer.writerows(rows)


class IperfRunner:
    """Manage an iperf3 client process and collect results."""

    def __init__(self, cfg: TestConfig, protocol: str, direction: str,
                 bandwidth_mbps: int, port: int, duration: int = 60,
                 small_packet: bool = False):
        self.cfg = cfg
        self.protocol = protocol
        self.direction = direction
        self.bandwidth_mbps = bandwidth_mbps
        self.port = port
        self.duration = duration
        self.small_packet = small_packet
        self._process: subprocess.Popen = None

    def build_command(self) -> list:
        """Build iperf3 command line."""
        cmd = [
            "iperf3", "-c", self.cfg.remote_host,
            "-p", str(self.port),
            "-t", str(self.duration),
            "-J",
        ]
        if self.protocol == "udp":
            cmd.extend(["-u", "-b", f"{self.bandwidth_mbps}M"])
            if self.small_packet:
                cmd.extend(["-l", "512"])
        else:
            if self.bandwidth_mbps >= 1000:
                cmd.extend(["-P", str(self.cfg.tcp_parallel_streams)])

        if self.direction == "ingress":
            cmd.append("-R")
        elif self.direction == "bidir":
            cmd.append("--bidir")

        return cmd

    def run(self) -> dict:
        """Run iperf3 and return parsed JSON. Blocking."""
        cmd = self.build_command()
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=self.duration + 30,
            )
            if result.returncode != 0:
                return {"error": result.stderr, "intervals": []}
            return json.loads(result.stdout)
        except subprocess.TimeoutExpired:
            return {"error": "timeout", "intervals": []}
        except json.JSONDecodeError:
            return {"error": "invalid json", "intervals": []}

    def run_background(self) -> None:
        """Start iperf3 in background (non-blocking). Use wait() to get result."""
        cmd = self.build_command()
        self._process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )

    def wait(self, timeout: int = None) -> dict:
        """Wait for background process and return parsed JSON."""
        if not self._process:
            return {"error": "no process", "intervals": []}
        try:
            stdout, stderr = self._process.communicate(timeout=timeout)
            if self._process.returncode != 0:
                return {"error": stderr, "intervals": []}
            return json.loads(stdout)
        except subprocess.TimeoutExpired:
            self._process.kill()
            return {"error": "timeout", "intervals": []}
        except json.JSONDecodeError:
            return {"error": "invalid json", "intervals": []}

    def kill(self) -> None:
        """Kill the background process if running."""
        if self._process and self._process.poll() is None:
            self._process.kill()
            self._process.wait(timeout=5)
