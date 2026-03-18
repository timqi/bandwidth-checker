"""iperf3 process management and JSON result parsing."""
import csv
import json
import os
from typing import Any, Dict, List


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
