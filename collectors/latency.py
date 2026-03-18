"""Ping latency collection and parsing."""
import csv
import os
import re
from typing import Any, Dict, List, Optional

_REPLY_RE = re.compile(
    r"icmp_seq=(\d+)\s+ttl=(\d+)\s+time=([\d.]+)\s*ms"
)
_SUMMARY_RTT_RE = re.compile(
    r"rtt min/avg/max/mdev = ([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+)"
)
_SUMMARY_LOSS_RE = re.compile(
    r"(\d+) packets transmitted, (\d+) received, ([\d.]+)% packet loss"
)


def parse_ping_line(line: str) -> Optional[Dict[str, Any]]:
    """Parse a single ping reply line. Returns None if not a reply."""
    m = _REPLY_RE.search(line)
    if not m:
        return None
    return {
        "icmp_seq": int(m.group(1)),
        "ttl": int(m.group(2)),
        "time_ms": float(m.group(3)),
    }


def parse_ping_summary(lines: List[str]) -> Dict[str, Any]:
    """Parse ping summary lines into a dict."""
    result: Dict[str, Any] = {}
    for line in lines:
        m = _SUMMARY_LOSS_RE.search(line)
        if m:
            result["packets_sent"] = int(m.group(1))
            result["packets_received"] = int(m.group(2))
            result["loss_percent"] = float(m.group(3))
        m = _SUMMARY_RTT_RE.search(line)
        if m:
            result["rtt_min"] = float(m.group(1))
            result["rtt_avg"] = float(m.group(2))
            result["rtt_max"] = float(m.group(3))
            result["rtt_mdev"] = float(m.group(4))
    return result


def write_ping_csv(rows: List[Dict[str, Any]], filepath: str) -> None:
    """Append ping rows to CSV."""
    if not rows:
        return
    file_exists = os.path.exists(filepath)
    with open(filepath, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        if not file_exists:
            writer.writeheader()
        writer.writerows(rows)
