"""TCP socket statistics collection via ss."""
import csv
import os
import re
from typing import Any, Dict, List

_RTT_RE = re.compile(r"rtt:([\d.]+)/([\d.]+)")
_CWND_RE = re.compile(r"cwnd:(\d+)")
_RETRANS_RE = re.compile(r"retrans:(\d+)/(\d+)")
_ESTAB_RE = re.compile(
    r"ESTAB\s+\d+\s+\d+\s+([\d.]+):(\d+)\s+([\d.]+):(\d+)"
)


def parse_ss_output(output: str) -> List[Dict[str, Any]]:
    """Parse ss -tin output into a list of per-socket dicts."""
    if not output.strip():
        return []

    results = []
    lines = output.strip().split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        m = _ESTAB_RE.match(line)
        if m:
            entry: Dict[str, Any] = {
                "local_addr": m.group(1),
                "local_port": int(m.group(2)),
                "remote_addr": m.group(3),
                "remote_port": int(m.group(4)),
                "rtt_ms": 0.0,
                "rttvar_ms": 0.0,
                "cwnd": 0,
                "retrans_current": 0,
                "retrans_total": 0,
            }
            detail = ""
            while i + 1 < len(lines) and not _ESTAB_RE.match(lines[i + 1]):
                i += 1
                detail += " " + lines[i]

            m2 = _RTT_RE.search(detail)
            if m2:
                entry["rtt_ms"] = float(m2.group(1))
                entry["rttvar_ms"] = float(m2.group(2))

            m2 = _CWND_RE.search(detail)
            if m2:
                entry["cwnd"] = int(m2.group(1))

            m2 = _RETRANS_RE.search(detail)
            if m2:
                entry["retrans_current"] = int(m2.group(1))
                entry["retrans_total"] = int(m2.group(2))

            results.append(entry)
        i += 1
    return results


def write_ss_csv(rows: List[Dict[str, Any]], filepath: str) -> None:
    """Append ss stats rows to CSV."""
    if not rows:
        return
    file_exists = os.path.exists(filepath)
    with open(filepath, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        if not file_exists:
            writer.writeheader()
        writer.writerows(rows)
